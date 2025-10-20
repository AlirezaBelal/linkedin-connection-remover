#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Automated LinkedIn connection remover.
- Creates a chrome-user-data folder next to the script and caches session.
- Launches a separate Chrome process with remote debugging and attaches chromedriver.
- Reads input URLs from output/Other.csv (column "URL").
- Writes results to output/results.csv and saves snapshots to output/debug/.
- Set DRY_RUN = True to simulate actions without performing removals.
"""

from __future__ import annotations

import csv
import os
import random
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from typing import Tuple, Optional
from urllib.parse import urlparse

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    SessionNotCreatedException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

CHROME_USER_DATA_DIR = os.path.join(PROJECT_ROOT, "chrome-user-data")
CHROME_PROFILE_DIR = "Default"
CHROME_BINARY = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

CSV_FILE_PATH = os.path.join(PROJECT_ROOT, "data", "Connections.csv")
OUTPUT_DEBUG_DIR = os.path.join(PROJECT_ROOT, "output", "debug")
RESULTS_CSV = os.path.join(PROJECT_ROOT, "output", "results.csv")

MIN_DELAY = 2
MAX_DELAY = 4
DRY_RUN = False
PROFILE_MARKER_FILENAME = "profile_initialized.txt"

os.makedirs(OUTPUT_DEBUG_DIR, exist_ok=True)
os.makedirs(os.path.dirname(RESULTS_CSV), exist_ok=True)


def save_debug_snapshot(driver, name_prefix: str = "snapshot") -> Tuple[str, str]:
    ts = int(time.time())
    safe_prefix = re.sub(r"[^0-9a-zA-Z_-]", "_", name_prefix)[:60]
    png_path = os.path.join(OUTPUT_DEBUG_DIR, f"{safe_prefix}_{ts}.png")
    html_path = os.path.join(OUTPUT_DEBUG_DIR, f"{safe_prefix}_{ts}.html")
    try:
        driver.save_screenshot(png_path)
    except Exception:
        png_path = ""
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    except Exception:
        html_path = ""
    return png_path, html_path


def profile_slug_from_url(url: str) -> str:
    try:
        p = urlparse(url).path.strip("/")
        return p.split("/")[-1]
    except Exception:
        return "profile"


def find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    addr, port = s.getsockname()
    s.close()
    return port


def wait_for_port(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except Exception:
            time.sleep(0.2)
    return False


def pick_chrome_binary() -> Optional[str]:
    if CHROME_BINARY and os.path.exists(CHROME_BINARY):
        return CHROME_BINARY
    default_win = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if os.path.exists(default_win):
        return default_win
    path = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")
    return path


def create_chrome_process(user_data_dir: str, profile_dir: str, port: int,
                          chrome_binary: Optional[str]) -> subprocess.Popen:
    args = []
    if chrome_binary:
        args.append(chrome_binary)
    else:
        args.append("chrome")
    args += [
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        f'--profile-directory={profile_dir}',
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-translate",
        "--disable-popup-blocking",
        "--disable-background-timer-throttling",
    ]
    creationflags = 0
    try:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
    except Exception as e:
        raise RuntimeError(f"Failed to start Chrome process: {e}")
    return proc


def create_driver_attaching_to_chrome(port: int) -> webdriver.Chrome:
    options = Options()
    options.debugger_address = f"127.0.0.1:{port}"
    service = Service(ChromeDriverManager().install())
    try:
        driver = webdriver.Chrome(service=service, options=options)
    except SessionNotCreatedException as e:
        raise SessionNotCreatedException(f"Failed to create WebDriver attached to Chrome debug port {port}: {e}")
    return driver


def is_connected(driver: webdriver.Chrome) -> bool:
    try:
        time.sleep(0.6)
        one_badge = driver.find_elements(By.XPATH,
                                         "//*[contains(text(),'1st') or contains(text(),'1\u200fst') or contains(text(),'1\u202fst')]")
        if one_badge:
            return True
    except Exception:
        pass
    try:
        connect_btns = driver.find_elements(By.XPATH,
                                            "//button[.//span[contains(text(),'Connect')] or contains(.,'Connect')]")
        if connect_btns:
            msg = driver.find_elements(By.XPATH,
                                       "//button[.//span[contains(text(),'Message')] or contains(.,'Message')]")
            if msg:
                return True
            return False
    except Exception:
        pass
    try:
        msg_btn = driver.find_elements(By.XPATH,
                                       "//button[.//span[contains(text(),'Message')] or contains(.,'Message')]")
        if msg_btn:
            return True
    except Exception:
        pass
    return True


def find_click_more_button(driver: webdriver.Chrome, wait: WebDriverWait, debug: bool = False) -> bool:
    try:
        WebDriverWait(driver, 6).until(EC.presence_of_element_located((By.XPATH,
                                                                       "//main//section[contains(@class,'pv-top-card') or contains(@class,'top-card') or contains(@class,'profile-topcard') or contains(@class,'pvs-sticky-header-profile-actions')]"
                                                                       )))
    except Exception:
        pass

    candidates_xpaths = [
        "//button[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'more actions')]",
        "//button[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'more')]",
        "//button[.//span[normalize-space(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'))='more']]",
        "//button[.//span[normalize-space(text())='More']]",
        "//button[contains(@id,'profile-overflow-action')]",
        "//button[.//svg and (contains(@class,'ellipsis') or contains(@data-icon,'ellipsis') or contains(.,'...') or contains(.,'⋯'))]"
    ]

    for xp in candidates_xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xp)
            for el in elements:
                try:
                    if not el.is_displayed():
                        continue
                    driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", el)
                    time.sleep(0.12)
                    driver.execute_script("arguments[0].click();", el)
                    try:
                        WebDriverWait(driver, 4).until(EC.presence_of_element_located((By.XPATH,
                                                                                       "//div[@role='menu' or contains(@class,'artdeco-popover__content') or contains(@class,'artdeco-dropdown__content')]")))
                    except Exception:
                        time.sleep(0.6)
                    return True
                except Exception:
                    continue
        except Exception:
            continue

    if debug:
        try:
            all_buttons = driver.find_elements(By.XPATH, "//button")
            print("---- debug: all buttons (text | aria-label | id | class) ----")
            for i, b in enumerate(all_buttons[:300], 1):
                try:
                    txt = (b.text or "").strip()
                    aria = b.get_attribute("aria-label") or ""
                    bid = b.get_attribute("id") or ""
                    cls = b.get_attribute("class") or ""
                    print(f"{i:03d}: text='{txt}' | aria='{aria}' | id='{bid}' | class='{cls}'")
                except Exception:
                    pass
            print("---- end debug ----")
        except Exception:
            pass

    return False


def find_and_click_menu_item_remove(driver: webdriver.Chrome, wait: WebDriverWait, dry_run: bool = False,
                                    debug: bool = False) -> bool:
    try:
        WebDriverWait(driver, 6).until(EC.presence_of_element_located((By.XPATH,
                                                                       "//div[@role='menu' or contains(@class,'artdeco-popover__content') or contains(@class,'artdeco-dropdown__content')]")))
    except Exception:
        return False

    try:
        candidates = driver.find_elements(By.XPATH,
                                          "//div[@role='menu']//button | //div[@role='menu']//a | //div[@role='menu']//div[@role='menuitem'] | //div[@role='menu']//div[@role='button'] | //div[contains(@class,'artdeco-popover__content')]//button | //div[contains(@class,'artdeco-popover__content')]//div[@role='button'] | //div[contains(@class,'artdeco-dropdown__content')]//*[(@role='button' or @role='menuitem') or self::button or self::a]"
                                          )
    except Exception:
        candidates = []

    keywords = [
        "remove connection", "remove connections", "disconnect", "remove"
    ]

    for el in candidates:
        try:
            txt = (el.text or "").strip().lower()
            if not txt:
                txt = (el.get_attribute("innerText") or "").strip().lower()
            aria = (el.get_attribute("aria-label") or "").strip().lower()
            title = (el.get_attribute("title") or "").strip().lower()
            combined = " ".join([txt, aria, title]).strip()
            if "remove connection" in combined or "remove your connection" in combined or (
                    "remove" in combined and "connection" in combined):
                if dry_run:
                    print(f"[dry-run] would click remove item: text='{txt}' aria='{aria}' title='{title}'")
                    return True
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                    time.sleep(0.12)
                    driver.execute_script("arguments[0].click();", el)
                    return True
                except Exception:
                    try:
                        el.click()
                        return True
                    except Exception:
                        continue
            else:
                for k in keywords:
                    if k in combined:
                        if dry_run:
                            print(f"[dry-run] would click remove item (kw-match): '{k}' -> text='{txt}' aria='{aria}'")
                            return True
                        try:
                            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                            time.sleep(0.12)
                            driver.execute_script("arguments[0].click();", el)
                            return True
                        except Exception:
                            try:
                                el.click()
                                return True
                            except Exception:
                                continue
        except StaleElementReferenceException:
            continue
        except Exception:
            continue

    if debug:
        try:
            print("---- debug: menu candidates ----")
            for i, el in enumerate(candidates, 1):
                try:
                    txt = (el.text or "").strip()
                    aria = el.get_attribute("aria-label") or ""
                    title = el.get_attribute("title") or ""
                    cls = el.get_attribute("class") or ""
                    print(f"{i:03d}: text='{txt}' | aria='{aria}' | title='{title}' | class='{cls}'")
                except Exception:
                    pass
            print("---- end debug ----")
        except Exception:
            pass

    return False


def confirm_remove_modal(driver: webdriver.Chrome, wait: WebDriverWait, dry_run: bool = False) -> bool:
    try:
        WebDriverWait(driver, 6).until(EC.presence_of_all_elements_located((By.XPATH,
                                                                            "//div[@role='dialog']//button | //div[contains(@class,'artdeco-modal__actionbar')]//button"
                                                                            )))
    except Exception:
        time.sleep(1.0)
        try:
            if not is_connected(driver):
                return True
        except Exception:
            pass
        try:
            connect_btns = driver.find_elements(By.XPATH,
                                                "//button[.//span[contains(text(),'Connect')] or contains(.,'Connect')]")
            if connect_btns:
                return True
        except Exception:
            pass
        try:
            toasts = driver.find_elements(By.XPATH,
                                          "//*[(@role='status' or @aria-live='polite' or contains(@class,'toast') or contains(@class,'artdeco-toast'))]")
            for t in toasts:
                txt = (t.text or "").lower()
                if any(k in txt for k in ("removed", "remove", "connection removed")):
                    return True
        except Exception:
            pass
        return False

    try:
        buttons = driver.find_elements(By.XPATH,
                                       "//div[@role='dialog']//button | //div[contains(@class,'artdeco-modal__actionbar')]//button")
    except Exception:
        buttons = []

    confirm_texts = ["remove", "disconnect", "confirm", "yes", "ok"]
    for b in buttons:
        try:
            txt = (b.text or "").strip().lower()
            if not txt:
                txt = (b.get_attribute("innerText") or "").strip().lower()
            if any(k in txt for k in confirm_texts):
                if dry_run:
                    print(f"[dry-run] would click confirm button with text: {txt}")
                    return True
                try:
                    driver.execute_script("arguments[0].click();", b)
                    time.sleep(0.6)
                    try:
                        if not is_connected(driver):
                            return True
                    except Exception:
                        pass
                    return True
                except Exception:
                    try:
                        b.click()
                        time.sleep(0.6)
                        try:
                            if not is_connected(driver):
                                return True
                        except Exception:
                            pass
                        return True
                    except Exception:
                        continue
        except StaleElementReferenceException:
            continue
    return False


def ensure_profile_marker(user_data_dir: str) -> bool:
    marker = os.path.join(user_data_dir, PROFILE_MARKER_FILENAME)
    return os.path.exists(marker)


def write_profile_marker(user_data_dir: str) -> None:
    marker = os.path.join(user_data_dir, PROFILE_MARKER_FILENAME)
    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(f"initialized_at={int(time.time())}\n")
    except Exception:
        pass


def ensure_logged_in_state(driver: webdriver.Chrome, wait: WebDriverWait, user_data_dir: str) -> bool:
    driver.get("https://www.linkedin.com/feed")
    time.sleep(3)
    need_manual_login = False
    try:
        if "login" in driver.current_url:
            need_manual_login = True
    except Exception:
        pass
    try:
        if driver.find_elements(By.ID, "username"):
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

    write_profile_marker(user_data_dir)
    return True


def prepare_chrome_and_driver() -> Tuple[webdriver.Chrome, WebDriverWait, subprocess.Popen]:
    if not os.path.exists(CHROME_USER_DATA_DIR):
        os.makedirs(CHROME_USER_DATA_DIR, exist_ok=True)

    port = find_free_port()
    chrome_bin = pick_chrome_binary()
    chrome_proc = create_chrome_process(CHROME_USER_DATA_DIR, CHROME_PROFILE_DIR, port, chrome_bin)

    ok = wait_for_port("127.0.0.1", port, timeout=25.0)
    if not ok:
        try:
            chrome_proc.terminate()
        except Exception:
            pass
        raise RuntimeError("Chrome failed to open remote debugging port or started too slowly.")

    driver = create_driver_attaching_to_chrome(port)
    wait = WebDriverWait(driver, 12)

    first_time = not ensure_profile_marker(CHROME_USER_DATA_DIR)
    ok_login = ensure_logged_in_state(driver, wait, CHROME_USER_DATA_DIR)
    if not ok_login:
        try:
            driver.quit()
        except Exception:
            pass
        try:
            chrome_proc.terminate()
        except Exception:
            pass
        raise RuntimeError("Login required but not completed.")

    return driver, wait, chrome_proc


def append_result_row(row: dict) -> None:
    header = ["timestamp", "url", "removed", "error", "screenshot", "html"]
    write_header = not os.path.exists(RESULTS_CSV)
    try:
        with open(RESULTS_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            if write_header:
                writer.writeheader()
            writer.writerow(row)
    except Exception:
        pass


def run_main():
    if not os.path.exists(CSV_FILE_PATH):
        print(f"CSV file not found: {CSV_FILE_PATH}")
        return

    df = pd.read_csv(CSV_FILE_PATH)
    linkedin_profiles = df['URL'].dropna().tolist()
    if not linkedin_profiles:
        print("No URLs found in CSV.")
        return

    try:
        driver, wait, chrome_proc = prepare_chrome_and_driver()
    except Exception as e:
        print("Error preparing driver/profile:", e)
        return

    try:
        for profile in linkedin_profiles:
            removed = False
            error_msg = ""
            screenshot = ""
            html = ""
            try:
                driver.get(profile)
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                time.sleep(1.2 + random.random() * 1.4)

                connected = is_connected(driver)
                if not connected:
                    print(f"Not a 1st-degree connection, skipping remove: {profile}")
                else:
                    clicked_more = find_click_more_button(driver, wait, debug=False)
                    if not clicked_more:
                        error_msg = "Could not open More menu"
                        print(f"{error_msg}: {profile}")
                        screenshot, html = save_debug_snapshot(driver, profile_slug_from_url(profile) + "_no_more")
                    else:
                        removed = find_and_click_menu_item_remove(driver, wait, dry_run=DRY_RUN, debug=False)
                        if not removed:
                            error_msg = "Menu opened but no 'Remove connection' item found"
                            print(f"{error_msg}: {profile}")
                            if not screenshot:
                                screenshot, html = save_debug_snapshot(driver, profile_slug_from_url(
                                    profile) + "_no_remove_item")
                        else:
                            confirmed = confirm_remove_modal(driver, wait, dry_run=DRY_RUN)
                            if not confirmed:
                                time.sleep(0.6)
                                if not is_connected(driver):
                                    confirmed = True
                                    print(f"Removal inferred (no modal shown) for: {profile}")
                                else:
                                    print(f"Modal confirm not found and still appears connected: {profile}")
                            if confirmed:
                                print(
                                    f"Removed connection: {profile}" if not DRY_RUN else f"[dry-run] Removed (simulated): {profile}")
                                removed = True

            except KeyboardInterrupt:
                print("Interrupted by user.")
                break
            except Exception as e:
                error_msg = str(e)
                print(f"Unexpected error for {profile}: {error_msg}")
                screenshot, html = save_debug_snapshot(driver, profile_slug_from_url(profile) + "_error")

            row = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "url": profile,
                "removed": bool(removed),
                "error": error_msg,
                "screenshot": screenshot,
                "html": html,
            }
            append_result_row(row)

            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        try:
            chrome_proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    run_main()
