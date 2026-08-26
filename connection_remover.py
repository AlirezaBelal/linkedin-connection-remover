"""Safety-first LinkedIn connection-removal workflow.

The module intentionally keeps destructive behavior behind an explicit execution
mode and exact UI semantics. It does not attempt to bypass login challenges,
CAPTCHAs, rate limits, or other platform protections.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import csv
from pathlib import Path
import re
import time
from typing import Callable, Iterable, Optional, Sequence
from urllib.parse import urlparse


ALLOWED_HOSTS = frozenset({"linkedin.com", "www.linkedin.com"})
PROFILE_PATH_RE = re.compile(r"^/in/([A-Za-z0-9._~%-]{1,200})/?$")
MAX_BATCH_LIMIT = 50
REMOVE_LABEL_RE = re.compile(r"^remove (?:your )?connection(?: with .+)?$", re.IGNORECASE)
CHALLENGE_PATH_MARKERS = ("/checkpoint/", "/challenge/", "/captcha/")


class RemovalError(RuntimeError):
    """Base error for validation, browser, and safety failures."""


class ConfigurationError(RemovalError):
    """Raised when local input or options are unsafe or invalid."""


class SafetyStop(RemovalError):
    """Raised when an individual action must fail closed rather than guess."""


class ChallengeStop(SafetyStop):
    """Raised when a platform challenge requires aborting the whole run."""


@dataclass(frozen=True)
class Target:
    """Validated LinkedIn profile target."""

    url: str
    target_ref: str


@dataclass(frozen=True)
class RemovalResult:
    """Privacy-safe outcome for one target."""

    target_ref: str
    mode: str
    status: str
    detail: str = ""


def normalize_profile_url(raw_url: str) -> str:
    """Validate and canonicalize one LinkedIn profile URL."""
    value = str(raw_url or "").strip()
    if not value:
        raise ConfigurationError("profile URL is empty")

    parsed = urlparse(value)
    if parsed.scheme.lower() != "https":
        raise ConfigurationError("profile URL must use HTTPS")
    if parsed.username or parsed.password:
        raise ConfigurationError("profile URL must not include credentials")
    if parsed.hostname is None or parsed.hostname.lower() not in ALLOWED_HOSTS:
        raise ConfigurationError("profile URL must use linkedin.com")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError("profile URL has an invalid port") from exc
    if port not in (None, 443):
        raise ConfigurationError("profile URL must not use a custom port")
    if parsed.query or parsed.fragment or parsed.params:
        raise ConfigurationError("profile URL must not include query parameters or fragments")

    match = PROFILE_PATH_RE.fullmatch(parsed.path)
    if not match:
        raise ConfigurationError("profile URL must match https://www.linkedin.com/in/<profile>/")

    slug = match.group(1)
    return f"https://www.linkedin.com/in/{slug}/"


def target_ref_for_url(url: str) -> str:
    """Return a stable short hash so results do not need to store profile URLs."""
    return sha256(url.encode("utf-8")).hexdigest()[:16]


def load_targets(csv_path: Path | str, max_targets: int = 10) -> list[Target]:
    """Load, validate, deduplicate, and cap targets from a CSV file."""
    if not isinstance(max_targets, int) or isinstance(max_targets, bool):
        raise ConfigurationError("max_targets must be an integer")
    if max_targets < 1 or max_targets > MAX_BATCH_LIMIT:
        raise ConfigurationError(f"max_targets must be between 1 and {MAX_BATCH_LIMIT}")

    path = Path(csv_path)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or "URL" not in reader.fieldnames:
                raise ConfigurationError("input CSV must contain a URL column")

            targets: list[Target] = []
            seen: set[str] = set()
            invalid_rows: list[int] = []
            for row_number, row in enumerate(reader, start=2):
                try:
                    canonical = normalize_profile_url(row.get("URL", ""))
                except ConfigurationError:
                    invalid_rows.append(row_number)
                    continue
                if canonical in seen:
                    continue
                seen.add(canonical)
                targets.append(Target(canonical, target_ref_for_url(canonical)))
    except FileNotFoundError as exc:
        raise ConfigurationError("input CSV was not found") from exc
    except OSError as exc:
        raise ConfigurationError("input CSV could not be read") from exc

    if invalid_rows:
        rendered = ", ".join(str(row) for row in invalid_rows[:10])
        suffix = "..." if len(invalid_rows) > 10 else ""
        raise ConfigurationError(f"invalid profile URL at CSV row(s): {rendered}{suffix}")
    if not targets:
        raise ConfigurationError("input CSV contains no valid profile URLs")
    if len(targets) > max_targets:
        raise ConfigurationError(
            f"input contains {len(targets)} unique targets; safety limit is {max_targets}"
        )
    return targets


def required_confirmation(target_count: int) -> str:
    return f"REMOVE {target_count} CONNECTIONS"


def confirm_live_execution(
    target_count: int,
    input_fn: Callable[[str], str] = input,
) -> bool:
    """Require an exact typed phrase before destructive execution."""
    phrase = required_confirmation(target_count)
    entered = input_fn(f"Type '{phrase}' to enable live removal: ")
    return entered.strip() == phrase


def normalize_ui_text(value: object) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def choose_remove_label(labels: Sequence[str]) -> Optional[int]:
    """Return the unique exact-semantic removal item, otherwise fail closed."""
    matches = [
        index
        for index, label in enumerate(labels)
        if REMOVE_LABEL_RE.fullmatch(" ".join(str(label or "").strip().split()))
    ]
    return matches[0] if len(matches) == 1 else None


def choose_confirmation_label(labels: Sequence[str]) -> Optional[int]:
    """Accept exactly one confirmation button labelled 'Remove'."""
    matches = [
        index for index, label in enumerate(labels) if normalize_ui_text(label) == "remove"
    ]
    return matches[0] if len(matches) == 1 else None


def is_challenge_url(url: str) -> bool:
    path = urlparse(str(url or "")).path.casefold()
    return any(marker in path for marker in CHALLENGE_PATH_MARKERS)


class ResultsWriter:
    """Append privacy-safe results without storing profile URLs."""

    HEADER = ("timestamp", "target_ref", "mode", "status", "detail")

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, result: RemovalResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self.path.exists()
        try:
            with self.path.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=self.HEADER)
                if write_header:
                    writer.writeheader()
                writer.writerow(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "target_ref": result.target_ref,
                        "mode": result.mode,
                        "status": result.status,
                        "detail": result.detail,
                    }
                )
        except OSError as exc:
            raise RemovalError("unable to write results") from exc


class LinkedInBrowser:
    """Conservative Selenium adapter with exact removal semantics."""

    def __init__(
        self,
        profile_dir: Path | str,
        debug_dir: Path | str,
        debug_screenshots: bool = False,
        wait_seconds: float = 12.0,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.debug_dir = Path(debug_dir)
        self.debug_screenshots = debug_screenshots
        self.wait_seconds = wait_seconds
        self.driver = None

    @staticmethod
    def _selenium():
        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as exc:
            raise ConfigurationError("Selenium is not installed; install requirements.txt") from exc
        return webdriver, By, EC, WebDriverWait

    def start(self) -> None:
        webdriver, _By, _EC, _WebDriverWait = self._selenium()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        options = webdriver.ChromeOptions()
        options.add_argument(f"--user-data-dir={self.profile_dir.resolve()}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--remote-debugging-address=127.0.0.1")
        try:
            self.driver = webdriver.Chrome(options=options)
        except Exception as exc:
            raise RemovalError("unable to start Chrome WebDriver") from exc

    def close(self) -> None:
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def ensure_manual_login(self, input_fn: Callable[[str], str] = input) -> None:
        if self.driver is None:
            raise RemovalError("browser is not started")
        _webdriver, By, _EC, _WebDriverWait = self._selenium()
        self.driver.get("https://www.linkedin.com/feed/")
        self._stop_on_challenge()
        needs_login = "login" in str(self.driver.current_url).casefold()
        try:
            needs_login = needs_login or bool(self.driver.find_elements(By.ID, "username"))
        except Exception:
            pass
        if needs_login:
            input_fn(
                "Log in manually in the opened browser. Do not paste credentials into this tool. "
                "Press ENTER when the LinkedIn feed is visible."
            )
            self.driver.get("https://www.linkedin.com/feed/")
            self._stop_on_challenge()
            if "login" in str(self.driver.current_url).casefold():
                raise SafetyStop("manual login was not completed")

    def _stop_on_challenge(self) -> None:
        if self.driver is not None and is_challenge_url(str(self.driver.current_url)):
            raise ChallengeStop("LinkedIn challenge detected; stopping without bypass attempts")

    def _snapshot(self, target_ref: str, reason: str) -> str:
        if not self.debug_screenshots or self.driver is None:
            return ""
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        safe_reason = re.sub(r"[^a-z0-9_-]", "_", reason.casefold())[:32]
        path = self.debug_dir / f"{target_ref}_{safe_reason}.png"
        try:
            self.driver.save_screenshot(str(path))
            return str(path)
        except Exception:
            return ""

    @staticmethod
    def _element_label(element) -> str:
        try:
            text = str(element.text or "").strip()
        except Exception:
            text = ""
        if text:
            return text
        for attr in ("aria-label", "innerText", "title"):
            try:
                value = str(element.get_attribute(attr) or "").strip()
            except Exception:
                value = ""
            if value:
                return value
        return ""

    def _open_more_menu(self):
        if self.driver is None:
            raise RemovalError("browser is not started")
        _webdriver, By, EC, WebDriverWait = self._selenium()
        wait = WebDriverWait(self.driver, self.wait_seconds)
        selectors = (
            "//main//button[@aria-label='More actions']",
            "//main//button[.//span[normalize-space(.)='More']]",
        )
        for xpath in selectors:
            try:
                buttons = self.driver.find_elements(By.XPATH, xpath)
            except Exception:
                buttons = []
            visible = []
            for button in buttons:
                try:
                    if button.is_displayed():
                        visible.append(button)
                except Exception:
                    continue
            if len(visible) != 1:
                continue
            try:
                visible[0].click()
                wait.until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//div[@role='menu' or contains(@class,'artdeco-dropdown__content')]")
                    )
                )
                return
            except Exception:
                continue
        raise SafetyStop("could not identify a unique More actions control")

    def _find_remove_item(self):
        if self.driver is None:
            raise RemovalError("browser is not started")
        _webdriver, By, _EC, _WebDriverWait = self._selenium()
        xpath = (
            "//div[@role='menu']//*[@role='menuitem' or self::button or self::a] | "
            "//div[contains(@class,'artdeco-dropdown__content')]//*[@role='menuitem' or self::button or self::a]"
        )
        try:
            candidates = [item for item in self.driver.find_elements(By.XPATH, xpath) if item.is_displayed()]
        except Exception as exc:
            raise SafetyStop("unable to inspect the profile actions menu") from exc
        labels = [self._element_label(item) for item in candidates]
        index = choose_remove_label(labels)
        if index is None:
            raise SafetyStop("no unique exact Remove connection action was found")
        return candidates[index]

    def _confirm_remove_modal(self) -> None:
        if self.driver is None:
            raise RemovalError("browser is not started")
        _webdriver, By, EC, WebDriverWait = self._selenium()
        wait = WebDriverWait(self.driver, self.wait_seconds)
        try:
            dialog = wait.until(EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']")))
        except Exception as exc:
            raise SafetyStop("removal confirmation dialog did not appear") from exc
        dialog_text = normalize_ui_text(getattr(dialog, "text", ""))
        if "remove" not in dialog_text or "connection" not in dialog_text:
            raise SafetyStop("confirmation dialog did not clearly describe connection removal")
        try:
            buttons = [
                button
                for button in dialog.find_elements(By.XPATH, ".//button")
                if button.is_displayed()
            ]
        except Exception as exc:
            raise SafetyStop("unable to inspect confirmation controls") from exc
        labels = [self._element_label(button) for button in buttons]
        index = choose_confirmation_label(labels)
        if index is None:
            raise SafetyStop("no unique exact Remove confirmation button was found")
        try:
            buttons[index].click()
        except Exception as exc:
            raise SafetyStop("Remove confirmation could not be submitted") from exc

    def process_target(self, target: Target, execute: bool) -> RemovalResult:
        if self.driver is None:
            raise RemovalError("browser is not started")
        mode = "execute" if execute else "dry-run"
        try:
            self.driver.get(target.url)
            self._stop_on_challenge()
            self._open_more_menu()
            remove_item = self._find_remove_item()
            if not execute:
                return RemovalResult(target.target_ref, mode, "eligible", "exact action found")
            remove_item.click()
            self._confirm_remove_modal()
            return RemovalResult(target.target_ref, mode, "submitted", "remove confirmation submitted")
        except ChallengeStop:
            self._snapshot(target.target_ref, "challenge-stop")
            raise
        except SafetyStop as exc:
            self._snapshot(target.target_ref, "safety-stop")
            return RemovalResult(target.target_ref, mode, "skipped", str(exc))
        except Exception:
            self._snapshot(target.target_ref, "browser-error")
            return RemovalResult(target.target_ref, mode, "failed", "browser interaction failed")


def run_targets(
    browser: LinkedInBrowser,
    targets: Iterable[Target],
    writer: ResultsWriter,
    execute: bool,
    delay_seconds: float,
) -> list[RemovalResult]:
    """Process a bounded target list with a fixed operator-visible delay."""
    results: list[RemovalResult] = []
    target_list = list(targets)
    for index, target in enumerate(target_list):
        result = browser.process_target(target, execute=execute)
        writer.append(result)
        results.append(result)
        print(f"[{target.target_ref}] {result.status}: {result.detail}")
        if index + 1 < len(target_list) and delay_seconds > 0:
            time.sleep(delay_seconds)
    return results
