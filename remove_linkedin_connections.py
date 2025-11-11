#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Automated LinkedIn connection remover.
- Creates a chrome-user-data folder next to the script and caches session.
- Launches a separate Chrome process with remote debugging and attaches chromedriver.
- Reads input URLs from data/Connections.csv (column "URL").
- Writes results to output/results.csv and saves snapshots to output/debug/.
- Set DRY_RUN = True to simulate actions without performing removals.
- Set REMOVE_PROCESSED_FROM_CSV = True to remove successfully processed entries from CSV.
"""

from __future__ import annotations

import csv
import random
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
    SessionNotCreatedException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


class Config:
    """Configuration constants for the LinkedIn connection remover."""

    # Paths
    PROJECT_ROOT = Path(__file__).parent.absolute()
    CHROME_USER_DATA_DIR = PROJECT_ROOT / "chrome-user-data"
    CHROME_PROFILE_DIR = "Default"
    CHROME_BINARY = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

    CSV_FILE_PATH = PROJECT_ROOT / "data" / "Connections.csv"
    OUTPUT_DEBUG_DIR = PROJECT_ROOT / "output" / "debug"
    RESULTS_CSV = PROJECT_ROOT / "output" / "results.csv"

    # Settings
    MIN_DELAY = 2
    MAX_DELAY = 4
    DRY_RUN = False
    REMOVE_PROCESSED_FROM_CSV = True
    PROFILE_MARKER_FILENAME = "profile_initialized.txt"

    # Chrome arguments
    CHROME_ARGS = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-translate",
        "--disable-popup-blocking",
        "--disable-background-timer-throttling",
    ]

    # XPath selectors
    CONNECTION_INDICATORS = [
        "//*[contains(text(),'1st') or contains(text(),'1\u200fst') or contains(text(),'1\u202fst')]"
    ]

    CONNECT_BUTTONS = [
        "//button[.//span[contains(text(),'Connect')] or contains(.,'Connect')]"
    ]

    MESSAGE_BUTTONS = [
        "//button[.//span[contains(text(),'Message')] or contains(.,'Message')]"
    ]

    MORE_BUTTON_SELECTORS = [
        "//button[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'more actions')]",
        "//button[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'more')]",
        "//button[.//span[normalize-space(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'))='more']]",
        "//button[.//span[normalize-space(text())='More']]",
        "//button[contains(@id,'profile-overflow-action')]",
        "//button[.//svg and (contains(@class,'ellipsis') or contains(@data-icon,'ellipsis') or contains(.,'...') or contains(.,'⋯'))]"
    ]

    MENU_CANDIDATES_SELECTOR = (
        "//div[@role='menu']//button | //div[@role='menu']//a | "
        "//div[@role='menu']//div[@role='menuitem'] | //div[@role='menu']//div[@role='button'] | "
        "//div[contains(@class,'artdeco-popover__content')]//button | "
        "//div[contains(@class,'artdeco-popover__content')]//div[@role='button'] | "
        "//div[contains(@class,'artdeco-dropdown__content')]//*[(@role='button' or @role='menuitem') or self::button or self::a]"
    )

    REMOVE_KEYWORDS = [
        "remove connection", "remove connections", "disconnect", "remove"
    ]


class FileManager:
    """Handles file operations and directory management."""

    @staticmethod
    def ensure_directories() -> None:
        """Create necessary directories if they don't exist."""
        Config.OUTPUT_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        Config.RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
        Config.CHROME_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def save_debug_snapshot(driver: webdriver.Chrome, name_prefix: str = "snapshot") -> Tuple[str, str]:
        """Save screenshot and HTML snapshot for debugging."""
        timestamp = int(time.time())
        safe_prefix = re.sub(r"[^0-9a-zA-Z_-]", "_", name_prefix)[:60]

        png_path = Config.OUTPUT_DEBUG_DIR / f"{safe_prefix}_{timestamp}.png"
        html_path = Config.OUTPUT_DEBUG_DIR / f"{safe_prefix}_{timestamp}.html"

        try:
            driver.save_screenshot(str(png_path))
        except Exception:
            png_path = ""

        try:
            html_path.write_text(driver.page_source, encoding="utf-8")
        except Exception:
            html_path = ""

        return str(png_path), str(html_path)

    @staticmethod
    def profile_slug_from_url(url: str) -> str:
        """Extract profile slug from LinkedIn URL."""
        try:
            path = urlparse(url).path.strip("/")
            return path.split("/")[-1]
        except Exception:
            return "profile"


class ChromeManager:
    """Manages Chrome browser process and WebDriver connection."""

    @staticmethod
    def find_free_port() -> int:
        """Find an available port for Chrome remote debugging."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    @staticmethod
    def wait_for_port(host: str, port: int, timeout: float = 20.0) -> bool:
        """Wait for Chrome to start listening on the debug port."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection((host, port), timeout=1):
                    return True
            except Exception:
                time.sleep(0.2)
        return False

    @staticmethod
    def find_chrome_binary() -> Optional[str]:
        """Find Chrome executable path."""
        if Config.CHROME_BINARY.exists():
            return str(Config.CHROME_BINARY)

        default_windows_path = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if default_windows_path.exists():
            return str(default_windows_path)

        for name in ["chrome", "google-chrome", "chromium"]:
            path = shutil.which(name)
            if path:
                return path

        return None

    @staticmethod
    def create_chrome_process(port: int) -> subprocess.Popen:
        """Start Chrome process with remote debugging enabled."""
        chrome_binary = ChromeManager.find_chrome_binary()
        if not chrome_binary:
            raise RuntimeError("Chrome executable not found")

        args = [
            chrome_binary,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={Config.CHROME_USER_DATA_DIR}",
            f"--profile-directory={Config.CHROME_PROFILE_DIR}",
            *Config.CHROME_ARGS,
        ]

        try:
            return subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start Chrome process: {e}")

    @staticmethod
    def create_webdriver(port: int) -> webdriver.Chrome:
        """Create WebDriver instance connected to Chrome debug port."""
        options = Options()
        options.debugger_address = f"127.0.0.1:{port}"
        service = Service(ChromeDriverManager().install())

        try:
            return webdriver.Chrome(service=service, options=options)
        except SessionNotCreatedException as e:
            raise SessionNotCreatedException(
                f"Failed to create WebDriver attached to Chrome debug port {port}: {e}"
            )


class ProfileManager:
    """Manages Chrome profile and login state."""

    @staticmethod
    def ensure_profile_marker() -> bool:
        """Check if profile has been initialized."""
        marker_path = Config.CHROME_USER_DATA_DIR / Config.PROFILE_MARKER_FILENAME
        return marker_path.exists()

    @staticmethod
    def write_profile_marker() -> None:
        """Write profile initialization marker."""
        marker_path = Config.CHROME_USER_DATA_DIR / Config.PROFILE_MARKER_FILENAME
        try:
            marker_path.write_text(f"initialized_at={int(time.time())}\n", encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def ensure_logged_in_state(driver: webdriver.Chrome, wait: WebDriverWait) -> bool:
        """Ensure user is logged into LinkedIn."""
        driver.get("https://www.linkedin.com/feed")
        time.sleep(3)

        need_manual_login = False

        try:
            if "login" in driver.current_url or driver.find_elements(By.ID, "username"):
                need_manual_login = True
        except Exception:
            pass

        if need_manual_login:
            print("Profile not logged in. Please log in to LinkedIn in the opened Chrome window and press ENTER here.")
            input()
            driver.get("https://www.linkedin.com/feed")
            time.sleep(3)

            try:
                if "login" in driver.current_url or driver.find_elements(By.ID, "username"):
                    print("Still not logged in.")
                    return False
            except Exception:
                return False

        ProfileManager.write_profile_marker()
        return True


class ConnectionChecker:
    """Handles checking and managing LinkedIn connections."""

    @staticmethod
    def is_connected(driver: webdriver.Chrome) -> bool:
        """Check if current profile is a 1st-degree connection."""
        time.sleep(0.6)

        # Check for 1st degree badge
        try:
            one_badge = driver.find_elements(By.XPATH, Config.CONNECTION_INDICATORS[0])
            if one_badge:
                return True
        except Exception:
            pass

        # Check for Connect vs Message buttons
        try:
            connect_btns = driver.find_elements(By.XPATH, Config.CONNECT_BUTTONS[0])
            if connect_btns:
                msg_btns = driver.find_elements(By.XPATH, Config.MESSAGE_BUTTONS[0])
                return bool(msg_btns)
            return False
        except Exception:
            pass

        # Check for Message button (indicates connection)
        try:
            msg_btn = driver.find_elements(By.XPATH, Config.MESSAGE_BUTTONS[0])
            if msg_btn:
                return True
        except Exception:
            pass

        return True

    @staticmethod
    def find_click_more_button(driver: webdriver.Chrome, wait: WebDriverWait, debug: bool = False) -> bool:
        """Find and click the More actions button."""
        # Wait for profile section to load
        try:
            wait.until(EC.presence_of_element_located((
                By.XPATH,
                "//main//section[contains(@class,'pv-top-card') or contains(@class,'top-card') or "
                "contains(@class,'profile-topcard') or contains(@class,'pvs-sticky-header-profile-actions')]"
            )))
        except Exception:
            pass

        # Try different selectors for More button
        for xpath in Config.MORE_BUTTON_SELECTORS:
            try:
                elements = driver.find_elements(By.XPATH, xpath)
                for element in elements:
                    if not element.is_displayed():
                        continue

                    try:
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                            element
                        )
                        time.sleep(0.12)
                        driver.execute_script("arguments[0].click();", element)

                        # Wait for menu to appear
                        try:
                            wait.until(EC.presence_of_element_located((
                                By.XPATH,
                                "//div[@role='menu' or contains(@class,'artdeco-popover__content') or "
                                "contains(@class,'artdeco-dropdown__content')]"
                            )))
                        except Exception:
                            time.sleep(0.6)

                        return True
                    except Exception:
                        continue
            except Exception:
                continue

        if debug:
            ConnectionChecker._debug_print_buttons(driver)

        return False

    @staticmethod
    def _debug_print_buttons(driver: webdriver.Chrome) -> None:
        """Debug helper to print all buttons on page."""
        try:
            all_buttons = driver.find_elements(By.XPATH, "//button")
            print("---- debug: all buttons (text | aria-label | id | class) ----")
            for i, button in enumerate(all_buttons[:300], 1):
                try:
                    text = (button.text or "").strip()
                    aria = button.get_attribute("aria-label") or ""
                    button_id = button.get_attribute("id") or ""
                    class_name = button.get_attribute("class") or ""
                    print(f"{i:03d}: text='{text}' | aria='{aria}' | id='{button_id}' | class='{class_name}'")
                except Exception:
                    pass
            print("---- end debug ----")
        except Exception:
            pass

    @staticmethod
    def find_and_click_menu_item_remove(driver: webdriver.Chrome, wait: WebDriverWait,
                                        dry_run: bool = False, debug: bool = False) -> bool:
        """Find and click the 'Remove connection' menu item."""
        # Wait for menu to appear
        try:
            wait.until(EC.presence_of_element_located((
                By.XPATH,
                "//div[@role='menu' or contains(@class,'artdeco-popover__content') or "
                "contains(@class,'artdeco-dropdown__content')]"
            )))
        except Exception:
            return False

        # Find menu candidates
        try:
            candidates = driver.find_elements(By.XPATH, Config.MENU_CANDIDATES_SELECTOR)
        except Exception:
            candidates = []

        # Look for remove connection items
        for element in candidates:
            try:
                text = (element.text or "").strip().lower()
                if not text:
                    text = (element.get_attribute("innerText") or "").strip().lower()

                aria = (element.get_attribute("aria-label") or "").strip().lower()
                title = (element.get_attribute("title") or "").strip().lower()
                combined = " ".join([text, aria, title]).strip()

                # Check for exact match first
                if ("remove connection" in combined or "remove your connection" in combined or
                        ("remove" in combined and "connection" in combined)):

                    if dry_run:
                        print(f"[dry-run] would click remove item: text='{text}' aria='{aria}' title='{title}'")
                        return True

                    return ConnectionChecker._click_element(driver, element)

                # Check for keyword matches
                for keyword in Config.REMOVE_KEYWORDS:
                    if keyword in combined:
                        if dry_run:
                            print(
                                f"[dry-run] would click remove item (kw-match): '{keyword}' -> text='{text}' aria='{aria}'")
                            return True

                        return ConnectionChecker._click_element(driver, element)

            except StaleElementReferenceException:
                continue
            except Exception:
                continue

        if debug:
            ConnectionChecker._debug_print_menu_candidates(candidates)

        return False

    @staticmethod
    def _click_element(driver: webdriver.Chrome, element) -> bool:
        """Helper method to click an element with fallback options."""
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            time.sleep(0.12)
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            try:
                element.click()
                return True
            except Exception:
                return False

    @staticmethod
    def _debug_print_menu_candidates(candidates: List) -> None:
        """Debug helper to print menu candidates."""
        try:
            print("---- debug: menu candidates ----")
            for i, element in enumerate(candidates, 1):
                try:
                    text = (element.text or "").strip()
                    aria = element.get_attribute("aria-label") or ""
                    title = element.get_attribute("title") or ""
                    class_name = element.get_attribute("class") or ""
                    print(f"{i:03d}: text='{text}' | aria='{aria}' | title='{title}' | class='{class_name}'")
                except Exception:
                    pass
            print("---- end debug ----")
        except Exception:
            pass

    @staticmethod
    def confirm_remove_modal(driver: webdriver.Chrome, wait: WebDriverWait, dry_run: bool = False) -> bool:
        """Confirm the removal in the modal dialog."""
        # Wait for modal buttons
        try:
            wait.until(EC.presence_of_all_elements_located((
                By.XPATH,
                "//div[@role='dialog']//button | //div[contains(@class,'artdeco-modal__actionbar')]//button"
            )))
        except Exception:
            # Check if removal was successful without modal
            time.sleep(1.0)
            return ConnectionChecker._check_removal_success(driver)

        # Find and click confirmation button
        try:
            buttons = driver.find_elements(By.XPATH,
                                           "//div[@role='dialog']//button | //div[contains(@class,'artdeco-modal__actionbar')]//button")
        except Exception:
            buttons = []

        confirm_texts = ["remove", "disconnect", "confirm", "yes", "ok"]
        for button in buttons:
            try:
                text = (button.text or "").strip().lower()
                if not text:
                    text = (button.get_attribute("innerText") or "").strip().lower()

                if any(keyword in text for keyword in confirm_texts):
                    if dry_run:
                        print(f"[dry-run] would click confirm button with text: {text}")
                        return True

                    try:
                        driver.execute_script("arguments[0].click();", button)
                        time.sleep(0.6)
                        return ConnectionChecker._check_removal_success(driver) or True
                    except Exception:
                        try:
                            button.click()
                            time.sleep(0.6)
                            return ConnectionChecker._check_removal_success(driver) or True
                        except Exception:
                            continue

            except StaleElementReferenceException:
                continue

        return False

    @staticmethod
    def _check_removal_success(driver: webdriver.Chrome) -> bool:
        """Check if connection removal was successful."""
        try:
            if not ConnectionChecker.is_connected(driver):
                return True
        except Exception:
            pass

        try:
            connect_btns = driver.find_elements(By.XPATH, Config.CONNECT_BUTTONS[0])
            if connect_btns:
                return True
        except Exception:
            pass

        try:
            toasts = driver.find_elements(By.XPATH,
                                          "//*[(@role='status' or @aria-live='polite' or contains(@class,'toast') or "
                                          "contains(@class,'artdeco-toast'))]")
            for toast in toasts:
                text = (toast.text or "").lower()
                if any(keyword in text for keyword in ("removed", "remove", "connection removed")):
                    return True
        except Exception:
            pass

        return False


class ResultsManager:
    """Manages result logging and CSV operations."""

    @staticmethod
    def append_result_row(row: Dict) -> None:
        """Append a result row to the results CSV file."""
        header = ["timestamp", "url", "removed", "error", "screenshot", "html"]
        write_header = not Config.RESULTS_CSV.exists()

        try:
            with open(Config.RESULTS_CSV, "a", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=header)
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            pass

    @staticmethod
    def remove_processed_entries_from_csv(processed_urls: List[str]) -> None:
        """Remove processed URLs from the original CSV file."""
        if not Config.REMOVE_PROCESSED_FROM_CSV or not processed_urls:
            return

        try:
            # Read the current CSV
            df = pd.read_csv(Config.CSV_FILE_PATH)

            # Filter out processed URLs
            df_filtered = df[~df['URL'].isin(processed_urls)]

            # Save back to CSV
            df_filtered.to_csv(Config.CSV_FILE_PATH, index=False)

            removed_count = len(df) - len(df_filtered)
            print(f"Removed {removed_count} processed entries from CSV file")

        except Exception as e:
            print(f"Error removing processed entries from CSV: {e}")


class LinkedInConnectionRemover:
    """Main class that orchestrates the LinkedIn connection removal process."""

    def __init__(self):
        self.driver = None
        self.wait = None
        self.chrome_process = None
        self.processed_urls = []

    def setup(self) -> bool:
        """Set up the Chrome browser and WebDriver."""
        try:
            FileManager.ensure_directories()

            port = ChromeManager.find_free_port()
            self.chrome_process = ChromeManager.create_chrome_process(port)

            if not ChromeManager.wait_for_port("127.0.0.1", port, timeout=25.0):
                self._cleanup()
                raise RuntimeError("Chrome failed to open remote debugging port or started too slowly.")

            self.driver = ChromeManager.create_webdriver(port)
            self.wait = WebDriverWait(self.driver, 12)

            # Ensure login state
            if not ProfileManager.ensure_logged_in_state(self.driver, self.wait):
                self._cleanup()
                raise RuntimeError("Login required but not completed.")

            return True

        except Exception as e:
            print(f"Error during setup: {e}")
            self._cleanup()
            return False

    def process_profiles(self, profiles: List[str]) -> None:
        """Process a list of LinkedIn profile URLs."""
        for profile_url in profiles:
            try:
                result = self._process_single_profile(profile_url)
                ResultsManager.append_result_row(result)

                # Track processed URLs for potential CSV cleanup
                if result["removed"]:
                    self.processed_urls.append(profile_url)

                # Random delay between profiles
                time.sleep(random.uniform(Config.MIN_DELAY, Config.MAX_DELAY))

            except KeyboardInterrupt:
                print("Interrupted by user.")
                break
            except Exception as e:
                print(f"Unexpected error processing {profile_url}: {e}")

                # Log the error
                error_result = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "url": profile_url,
                    "removed": False,
                    "error": str(e),
                    "screenshot": "",
                    "html": "",
                }
                ResultsManager.append_result_row(error_result)

    def _process_single_profile(self, profile_url: str) -> Dict:
        """Process a single LinkedIn profile URL."""
        print(f"Processing: {profile_url}")

        removed = False
        error_msg = ""
        screenshot = ""
        html = ""

        # Navigate to profile
        self.driver.get(profile_url)
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(1.2 + random.random() * 1.4)

        # Check if connected
        if not ConnectionChecker.is_connected(self.driver):
            print(f"Not a 1st-degree connection, skipping: {profile_url}")
            return self._create_result_dict(profile_url, False, "Not a 1st-degree connection", "", "")

        # Try to open More menu
        if not ConnectionChecker.find_click_more_button(self.driver, self.wait):
            error_msg = "Could not open More menu"
            print(f"{error_msg}: {profile_url}")
            screenshot, html = FileManager.save_debug_snapshot(
                self.driver,
                FileManager.profile_slug_from_url(profile_url) + "_no_more"
            )
            return self._create_result_dict(profile_url, False, error_msg, screenshot, html)

        # Try to find and click remove connection
        if not ConnectionChecker.find_and_click_menu_item_remove(self.driver, self.wait, dry_run=Config.DRY_RUN):
            error_msg = "Menu opened but no 'Remove connection' item found"
            print(f"{error_msg}: {profile_url}")
            screenshot, html = FileManager.save_debug_snapshot(
                self.driver,
                FileManager.profile_slug_from_url(profile_url) + "_no_remove_item"
            )
            return self._create_result_dict(profile_url, False, error_msg, screenshot, html)

        # Confirm removal
        confirmed = ConnectionChecker.confirm_remove_modal(self.driver, self.wait, dry_run=Config.DRY_RUN)
        if not confirmed:
            time.sleep(0.6)
            if not ConnectionChecker.is_connected(self.driver):
                confirmed = True
                print(f"Removal inferred (no modal shown) for: {profile_url}")
            else:
                print(f"Modal confirm not found and still appears connected: {profile_url}")

        if confirmed:
            status_msg = "Removed connection" if not Config.DRY_RUN else "[dry-run] Removed (simulated)"
            print(f"{status_msg}: {profile_url}")
            removed = True

        return self._create_result_dict(profile_url, removed, error_msg, screenshot, html)

    def _create_result_dict(self, url: str, removed: bool, error: str,
                            screenshot: str, html: str) -> Dict:
        """Create a result dictionary for logging."""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "removed": removed,
            "error": error,
            "screenshot": screenshot,
            "html": html,
        }

    def cleanup(self) -> None:
        """Clean up resources and optionally remove processed entries from CSV."""
        # Remove processed entries from CSV if enabled
        if Config.REMOVE_PROCESSED_FROM_CSV:
            ResultsManager.remove_processed_entries_from_csv(self.processed_urls)

        self._cleanup()

    def _cleanup(self) -> None:
        """Clean up Chrome process and WebDriver."""
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


def load_profiles_from_csv() -> List[str]:
    """Load LinkedIn profile URLs from CSV file."""
    if not Config.CSV_FILE_PATH.exists():
        print(f"CSV file not found: {Config.CSV_FILE_PATH}")
        return []

    try:
        df = pd.read_csv(Config.CSV_FILE_PATH)
        profiles = df['URL'].dropna().tolist()

        if not profiles:
            print("No URLs found in CSV.")
            return []

        print(f"Loaded {len(profiles)} profile URLs from CSV")
        return profiles

    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return []


def main():
    """Main function to run the LinkedIn connection remover."""
    print("LinkedIn Connection Remover")
    print(f"DRY_RUN mode: {Config.DRY_RUN}")
    print(f"Remove processed entries from CSV: {Config.REMOVE_PROCESSED_FROM_CSV}")
    print("-" * 50)

    # Load profile URLs
    profiles = load_profiles_from_csv()
    if not profiles:
        return

    # Initialize and run the remover
    remover = LinkedInConnectionRemover()

    try:
        if remover.setup():
            remover.process_profiles(profiles)
        else:
            print("Failed to set up the connection remover")
    finally:
        remover.cleanup()

    print("Process completed.")


if __name__ == "__main__":
    main()
