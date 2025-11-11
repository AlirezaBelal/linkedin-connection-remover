#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LinkedIn Connection Remover - Clean Version
Author: AlirezaBelal
Date: 2025-11-11

Features:
- Removes processed connections from CSV
- Clean English messaging
- Better error handling
- Progress tracking
"""

from __future__ import annotations

import csv
import logging
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
    SessionNotCreatedException,
    TimeoutException,
    WebDriverException
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# Fix Unicode encoding for Windows console
if sys.platform == "win32":
    import codecs

    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())


@dataclass
class Config:
    """Configuration settings"""
    # Paths
    PROJECT_ROOT: str = os.path.dirname(os.path.abspath(__file__))
    CHROME_USER_DATA_DIR: str = os.path.join(PROJECT_ROOT, "chrome-user-data")
    CHROME_PROFILE_DIR: str = "Default"
    CSV_FILE_PATH: str = os.path.join(PROJECT_ROOT, "data", "Connections.csv")
    OUTPUT_DEBUG_DIR: str = os.path.join(PROJECT_ROOT, "output", "debug")
    RESULTS_CSV: str = os.path.join(PROJECT_ROOT, "output", "results.csv")
    BACKUP_CSV: str = os.path.join(PROJECT_ROOT, "data", "Connections_backup.csv")

    # Chrome settings
    CHROME_BINARY: str = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    # Timing
    MIN_DELAY: float = 2.0
    MAX_DELAY: float = 4.0
    WAIT_TIMEOUT: int = 15

    # Behavior
    DRY_RUN: bool = False
    MAX_RETRIES: int = 3
    HEADLESS: bool = False
    REMOVE_FROM_CSV: bool = True

    # LinkedIn specific
    PROFILE_MARKER_FILENAME: str = "profile_initialized.txt"


class Logger:
    """Simple logging system"""

    def __init__(self, name: str = "LinkedInRemover"):
        self.logger = logging.getLogger(name)
        self._setup_logging()

    def _setup_logging(self):
        """Setup logging"""
        if self.logger.handlers:
            return

        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

        # File handler
        try:
            file_handler = logging.FileHandler('linkedin_remover.log', encoding='utf-8')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        except Exception:
            pass

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

    def info(self, message: str):
        print(f"[INFO] {message}")
        try:
            self.logger.info(message)
        except Exception:
            pass

    def error(self, message: str):
        print(f"[ERROR] {message}")
        try:
            self.logger.error(message)
        except Exception:
            pass

    def warning(self, message: str):
        print(f"[WARNING] {message}")
        try:
            self.logger.warning(message)
        except Exception:
            pass


class CSVManager:
    """Manages CSV operations"""

    def __init__(self, csv_path: str, backup_path: str, logger: Logger):
        self.csv_path = csv_path
        self.backup_path = backup_path
        self.logger = logger
        self._create_backup()

    def _create_backup(self):
        """Create backup of original CSV"""
        try:
            if os.path.exists(self.csv_path):
                shutil.copy2(self.csv_path, self.backup_path)
                self.logger.info(f"Backup created: {self.backup_path}")
        except Exception as e:
            self.logger.error(f"Backup failed: {e}")

    def read_urls(self) -> List[str]:
        """Read URLs from CSV file"""
        try:
            df = pd.read_csv(self.csv_path)
            urls = df['URL'].dropna().tolist()
            self.logger.info(f"Loaded {len(urls)} URLs from CSV")
            return urls
        except Exception as e:
            self.logger.error(f"CSV read failed: {e}")
            return []

    def remove_url(self, url: str):
        """Remove specific URL from CSV"""
        try:
            df = pd.read_csv(self.csv_path)
            initial_count = len(df)
            df = df[df['URL'] != url]
            df.to_csv(self.csv_path, index=False)

            if len(df) < initial_count:
                self.logger.info(f"Removed from CSV: {url}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"CSV remove failed: {e}")
            return False

    def get_remaining_count(self) -> int:
        """Get count of remaining URLs"""
        try:
            df = pd.read_csv(self.csv_path)
            return len(df['URL'].dropna())
        except Exception:
            return 0


class ChromeManager:
    """Manages Chrome browser and WebDriver"""

    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger
        self.driver: Optional[webdriver.Chrome] = None
        self.wait: Optional[WebDriverWait] = None
        self.chrome_process: Optional[subprocess.Popen] = None

    def _find_free_port(self) -> int:
        """Find available port"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    def _wait_for_port(self, host: str, port: int, timeout: float = 20.0) -> bool:
        """Wait for port to become available"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection((host, port), timeout=1):
                    return True
            except Exception:
                time.sleep(0.2)
        return False

    def _find_chrome_binary(self) -> Optional[str]:
        """Find Chrome executable"""
        if self.config.CHROME_BINARY and os.path.exists(self.config.CHROME_BINARY):
            return self.config.CHROME_BINARY

        default_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]

        for path in default_paths:
            if os.path.exists(path):
                return path

        return shutil.which("chrome") or shutil.which("google-chrome")

    def _start_chrome_process(self, port: int) -> subprocess.Popen:
        """Start Chrome process"""
        chrome_binary = self._find_chrome_binary()
        if not chrome_binary:
            raise RuntimeError("Chrome not found")

        args = [
            chrome_binary,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={self.config.CHROME_USER_DATA_DIR}",
            f"--profile-directory={self.config.CHROME_PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-sync",
        ]

        try:
            return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            raise RuntimeError(f"Chrome start failed: {e}")

    def _create_driver(self, port: int) -> webdriver.Chrome:
        """Create WebDriver"""
        options = Options()
        options.debugger_address = f"127.0.0.1:{port}"
        service = Service(ChromeDriverManager().install())

        try:
            return webdriver.Chrome(service=service, options=options)
        except Exception as e:
            raise SessionNotCreatedException(f"Driver creation failed: {e}")

    def setup(self) -> Tuple[webdriver.Chrome, WebDriverWait]:
        """Setup Chrome and WebDriver"""
        os.makedirs(self.config.CHROME_USER_DATA_DIR, exist_ok=True)

        port = self._find_free_port()
        self.chrome_process = self._start_chrome_process(port)

        if not self._wait_for_port("127.0.0.1", port, timeout=25.0):
            self.cleanup()
            raise RuntimeError("Chrome startup timeout")

        self.driver = self._create_driver(port)
        self.wait = WebDriverWait(self.driver, self.config.WAIT_TIMEOUT)

        return self.driver, self.wait

    def cleanup(self):
        """Clean up resources"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass

        if self.chrome_process:
            try:
                self.chrome_process.terminate()
            except Exception:
                pass


class LinkedInProfileChecker:
    """Check LinkedIn profile connection status"""

    def __init__(self, driver: webdriver.Chrome, wait: WebDriverWait, logger: Logger):
        self.driver = driver
        self.wait = wait
        self.logger = logger

    def is_connected(self) -> bool:
        """Check if profile is connected"""
        try:
            time.sleep(0.6)

            # Check for 1st degree badge
            one_badge = self.driver.find_elements(By.XPATH, "//*[contains(text(),'1st')]")
            if one_badge:
                return True

            # Check for Connect button
            connect_btns = self.driver.find_elements(By.XPATH, "//button[contains(.,'Connect')]")
            if connect_btns:
                return False

            # Check for Message button
            msg_btn = self.driver.find_elements(By.XPATH, "//button[contains(.,'Message')]")
            if msg_btn:
                return True

            return True

        except Exception:
            return True


class LinkedInRemover:
    """Main LinkedIn connection remover"""

    def __init__(self, driver: webdriver.Chrome, wait: WebDriverWait,
                 config: Config, logger: Logger):
        self.driver = driver
        self.wait = wait
        self.config = config
        self.logger = logger
        self.checker = LinkedInProfileChecker(driver, wait, logger)

    def save_debug_snapshot(self, name_prefix: str = "snapshot") -> Tuple[str, str]:
        """Save debug files"""
        timestamp = int(time.time())
        safe_prefix = re.sub(r"[^0-9a-zA-Z_-]", "_", name_prefix)[:60]

        png_path = os.path.join(self.config.OUTPUT_DEBUG_DIR, f"{safe_prefix}_{timestamp}.png")
        html_path = os.path.join(self.config.OUTPUT_DEBUG_DIR, f"{safe_prefix}_{timestamp}.html")

        try:
            self.driver.save_screenshot(png_path)
        except Exception:
            png_path = ""

        try:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
        except Exception:
            html_path = ""

        return png_path, html_path

    def _profile_slug_from_url(self, url: str) -> str:
        """Extract profile slug from URL"""
        try:
            path = urlparse(url).path.strip("/")
            return path.split("/")[-1]
        except Exception:
            return "profile"

    def _find_more_button(self) -> bool:
        """Find and click More button"""
        try:
            self.wait.until(EC.presence_of_element_located((By.XPATH, "//main")))
        except TimeoutException:
            pass

        more_button_xpaths = [
            "//button[contains(@aria-label,'more') or contains(@aria-label,'More')]",
            "//button[.//span[text()='More']]",
            "//button[contains(@id,'overflow')]",
            "//button[.//svg[contains(@class,'ellipsis')]]"
        ]

        for xpath in more_button_xpaths:
            try:
                elements = self.driver.find_elements(By.XPATH, xpath)
                for element in elements:
                    if element.is_displayed():
                        self.driver.execute_script("arguments[0].click();", element)
                        time.sleep(0.5)
                        return True
            except Exception:
                continue

        return False

    def _find_remove_menu_item(self) -> bool:
        """Find and click remove menu item"""
        try:
            self.wait.until(EC.presence_of_element_located((By.XPATH, "//div[@role='menu']")))
        except TimeoutException:
            return False

        menu_items = self.driver.find_elements(By.XPATH, "//div[@role='menu']//button | //div[@role='menu']//a")

        remove_keywords = ["remove connection", "disconnect", "remove"]

        for item in menu_items:
            try:
                text = (item.text or "").strip().lower()
                aria_label = (item.get_attribute("aria-label") or "").strip().lower()
                combined_text = " ".join([text, aria_label]).strip()

                if any(keyword in combined_text for keyword in remove_keywords):
                    if self.config.DRY_RUN:
                        self.logger.info(f"[DRY RUN] Would click: {text}")
                        return True

                    self.driver.execute_script("arguments[0].click();", item)
                    return True

            except Exception:
                continue

        return False

    def _confirm_removal_modal(self) -> bool:
        """Confirm removal in modal"""
        try:
            self.wait.until(EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']//button")))
        except TimeoutException:
            time.sleep(1.0)
            return not self.checker.is_connected()

        buttons = self.driver.find_elements(By.XPATH, "//div[@role='dialog']//button")
        confirm_keywords = ["remove", "disconnect", "confirm", "yes", "ok"]

        for button in buttons:
            try:
                text = (button.text or "").strip().lower()
                if any(keyword in text for keyword in confirm_keywords):
                    if self.config.DRY_RUN:
                        self.logger.info(f"[DRY RUN] Would confirm: {text}")
                        return True

                    self.driver.execute_script("arguments[0].click();", button)
                    time.sleep(0.6)
                    return not self.checker.is_connected()

            except Exception:
                continue

        return False

    def remove_connection(self, profile_url: str) -> Tuple[bool, str, str, str]:
        """Remove LinkedIn connection"""
        error_msg = ""
        screenshot = ""
        html = ""

        try:
            self.driver.get(profile_url)
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(1.5)

            # Check if connected
            if not self.checker.is_connected():
                return False, "Not connected", "", ""

            # Find More button
            if not self._find_more_button():
                error_msg = "More button not found"
                screenshot, html = self.save_debug_snapshot(self._profile_slug_from_url(profile_url) + "_no_more")
                return False, error_msg, screenshot, html

            # Find remove option
            if not self._find_remove_menu_item():
                error_msg = "Remove option not found"
                screenshot, html = self.save_debug_snapshot(self._profile_slug_from_url(profile_url) + "_no_remove")
                return False, error_msg, screenshot, html

            # Confirm removal
            if not self._confirm_removal_modal():
                error_msg = "Confirmation failed"
                screenshot, html = self.save_debug_snapshot(self._profile_slug_from_url(profile_url) + "_no_confirm")
                return False, error_msg, screenshot, html

            return True, "", "", ""

        except Exception as e:
            error_msg = str(e)
            screenshot, html = self.save_debug_snapshot(self._profile_slug_from_url(profile_url) + "_error")
            return False, error_msg, screenshot, html


class ResultsManager:
    """Manages results logging"""

    def __init__(self, results_path: str, logger: Logger):
        self.results_path = results_path
        self.logger = logger
        self._ensure_results_file()

    def _ensure_results_file(self):
        """Create results file"""
        os.makedirs(os.path.dirname(self.results_path), exist_ok=True)

        if not os.path.exists(self.results_path):
            headers = ["timestamp", "url", "removed", "error", "screenshot", "html"]
            try:
                with open(self.results_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=headers)
                    writer.writeheader()
            except Exception as e:
                self.logger.error(f"Results file creation failed: {e}")

    def append_result(self, url: str, removed: bool, error: str = "", screenshot: str = "", html: str = ""):
        """Append result"""
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "removed": removed,
            "error": error,
            "screenshot": screenshot,
            "html": html,
        }

        try:
            with open(self.results_path, "a", newline="", encoding="utf-8") as f:
                headers = ["timestamp", "url", "removed", "error", "screenshot", "html"]
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writerow(row)
        except Exception as e:
            self.logger.error(f"Result write failed: {e}")


class LoginManager:
    """Manages LinkedIn login"""

    def __init__(self, driver: webdriver.Chrome, wait: WebDriverWait, config: Config, logger: Logger):
        self.driver = driver
        self.wait = wait
        self.config = config
        self.logger = logger

    def ensure_logged_in(self) -> bool:
        """Ensure logged into LinkedIn"""
        self.driver.get("https://www.linkedin.com/feed")
        time.sleep(3)

        current_url = self.driver.current_url.lower()
        if "login" in current_url or self.driver.find_elements(By.ID, "username"):
            print("\n" + "=" * 50)
            print("Please login to LinkedIn in Chrome")
            print("Press ENTER after login...")
            print("=" * 50)
            input()

            self.driver.get("https://www.linkedin.com/feed")
            time.sleep(3)

            current_url = self.driver.current_url.lower()
            if "login" in current_url or self.driver.find_elements(By.ID, "username"):
                return False

        return True


def smart_delay(config: Config):
    """Smart delay"""
    base_delay = random.uniform(config.MIN_DELAY, config.MAX_DELAY)
    if random.random() < 0.1:
        base_delay += random.uniform(5, 15)
    time.sleep(base_delay)


def show_progress(current: int, total: int, url: str, removed_count: int):
    """Show progress"""
    percentage = (current / total) * 100
    print(f"\n{'=' * 50}")
    print(f"Progress: {current}/{total} ({percentage:.1f}%)")
    print(f"Removed: {removed_count}")
    print(f"URL: {url}")
    print(f"{'=' * 50}")


def main():
    """Main function"""
    config = Config()
    logger = Logger()

    # Create directories
    os.makedirs(config.OUTPUT_DEBUG_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(config.RESULTS_CSV), exist_ok=True)
    os.makedirs(os.path.dirname(config.CSV_FILE_PATH), exist_ok=True)

    logger.info("Starting LinkedIn connection removal")
    logger.info(f"DRY RUN: {config.DRY_RUN}")

    # Initialize managers
    csv_manager = CSVManager(config.CSV_FILE_PATH, config.BACKUP_CSV, logger)
    urls = csv_manager.read_urls()

    if not urls:
        logger.error("No URLs found!")
        return

    results_manager = ResultsManager(config.RESULTS_CSV, logger)
    chrome_manager = ChromeManager(config, logger)

    try:
        driver, wait = chrome_manager.setup()
        logger.info("Chrome started")

        login_manager = LoginManager(driver, wait, config, logger)
        if not login_manager.ensure_logged_in():
            logger.error("Login failed")
            return

        logger.info("Login successful")

        remover = LinkedInRemover(driver, wait, config, logger)

        # Process URLs
        total_urls = len(urls)
        removed_count = 0

        for i, url in enumerate(urls, 1):
            show_progress(i, total_urls, url, removed_count)

            try:
                success, error, screenshot, html = remover.remove_connection(url)

                if success:
                    removed_count += 1
                    logger.info(f"SUCCESS: {url}")

                    if config.REMOVE_FROM_CSV and not config.DRY_RUN:
                        csv_manager.remove_url(url)
                else:
                    logger.warning(f"FAILED: {url} - {error}")

                results_manager.append_result(url, success, error, screenshot, html)

                if i < total_urls:
                    smart_delay(config)

            except KeyboardInterrupt:
                logger.info("Stopped by user")
                break
            except Exception as e:
                logger.error(f"Error: {url} - {e}")
                results_manager.append_result(url, False, str(e))

        # Summary
        remaining_count = csv_manager.get_remaining_count()
        print(f"\n{'=' * 50}")
        print(f"COMPLETED!")
        print(f"Total: {total_urls}")
        print(f"Removed: {removed_count}")
        print(f"Remaining: {remaining_count}")
        print(f"Results: {config.RESULTS_CSV}")
        print(f"Backup: {config.BACKUP_CSV}")
        print(f"{'=' * 50}")

        logger.info(f"Done! {removed_count}/{total_urls} removed")

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        chrome_manager.cleanup()
        logger.info("Cleanup complete")


if __name__ == "__main__":
    main()