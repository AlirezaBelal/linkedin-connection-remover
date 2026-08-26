from html.parser import HTMLParser
from pathlib import Path
import unittest

from connection_remover import ChallengeStop, LinkedInBrowser, Target, normalize_ui_text


FIXTURES = Path(__file__).parent / "fixtures"


class FixtureElement:
    def __init__(self, text="", attrs=None, children=None):
        self.text = text
        self.attrs = dict(attrs or {})
        self.children = list(children or [])
        self.click_count = 0

    def is_displayed(self):
        return True

    def click(self):
        self.click_count += 1

    def get_attribute(self, name):
        return self.attrs.get(name, "")

    def find_elements(self, _by, xpath):
        if xpath == ".//button":
            return list(self.children)
        return []


class FixtureDocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.main_depth = 0
        self.menu_depth = 0
        self.dialog_depth = 0
        self.current_button = None
        self.main_buttons = []
        self.menu_items = []
        self.dialog_buttons = []
        self.dialog_text_parts = []
        self.current_url = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        flags = {
            "main": tag == "main",
            "menu": tag == "div" and attributes.get("role") == "menu",
            "dialog": tag == "div" and attributes.get("role") == "dialog",
            "button": tag == "button",
        }
        self.stack.append(flags)
        self.main_depth += int(flags["main"])
        self.menu_depth += int(flags["menu"])
        self.dialog_depth += int(flags["dialog"])

        if tag == "meta" and attributes.get("name") == "fixture-current-url":
            self.current_url = attributes.get("content")

        if tag == "button":
            button = FixtureElement(attrs=attributes)
            self.current_button = button
            if self.main_depth:
                self.main_buttons.append(button)
            if self.menu_depth or attributes.get("role") == "menuitem":
                self.menu_items.append(button)
            if self.dialog_depth:
                self.dialog_buttons.append(button)

    def handle_data(self, data):
        if self.current_button is not None:
            self.current_button.text += data
        if self.dialog_depth:
            self.dialog_text_parts.append(data)

    def handle_endtag(self, _tag):
        if not self.stack:
            return
        flags = self.stack.pop()
        if flags["button"]:
            self.current_button = None
        self.main_depth -= int(flags["main"])
        self.menu_depth -= int(flags["menu"])
        self.dialog_depth -= int(flags["dialog"])


class FixtureDriver:
    def __init__(self, fixture_path):
        parser = FixtureDocumentParser()
        parser.feed(Path(fixture_path).read_text(encoding="utf-8"))
        self.fixture_url = parser.current_url
        self.current_url = "about:blank"
        self.main_buttons = parser.main_buttons
        self.menu_items = parser.menu_items
        dialog_text = " ".join(part.strip() for part in parser.dialog_text_parts if part.strip())
        self.dialog = (
            FixtureElement(text=dialog_text, children=parser.dialog_buttons)
            if parser.dialog_buttons or dialog_text
            else None
        )
        self.dialog_buttons = parser.dialog_buttons

    def get(self, url):
        self.current_url = self.fixture_url or url

    def find_elements(self, _by, xpath):
        if "@aria-label='More actions'" in xpath:
            return [
                button
                for button in self.main_buttons
                if button.get_attribute("aria-label") == "More actions"
            ]
        if "normalize-space(.)='More'" in xpath:
            return [
                button for button in self.main_buttons if normalize_ui_text(button.text) == "more"
            ]
        if "role='menu'" in xpath and "menuitem" in xpath:
            return list(self.menu_items)
        return []


class FakeBy:
    XPATH = "xpath"


class FakeEC:
    @staticmethod
    def presence_of_element_located(locator):
        return locator


class FakeWait:
    def __init__(self, driver, _timeout):
        self.driver = driver

    def until(self, locator):
        _by, xpath = locator
        if "role='dialog'" in xpath:
            if self.driver.dialog is None:
                raise RuntimeError("dialog missing")
            return self.driver.dialog
        if "role='menu'" in xpath or "artdeco-dropdown__content" in xpath:
            if not self.driver.menu_items:
                raise RuntimeError("menu missing")
            return object()
        raise RuntimeError("unsupported fixture locator")


class FixtureBrowser(LinkedInBrowser):
    @staticmethod
    def _selenium():
        return None, FakeBy, FakeEC, FakeWait


class DomFixtureIntegrationTests(unittest.TestCase):
    def make_browser(self, fixture_name):
        browser = FixtureBrowser(profile_dir="unused-profile", debug_dir="unused-debug")
        browser.driver = FixtureDriver(FIXTURES / fixture_name)
        return browser

    @staticmethod
    def target():
        return Target("https://www.linkedin.com/in/example-profile/", "fixture-target")

    def test_dry_run_finds_exact_action_without_clicking_it(self):
        browser = self.make_browser("eligible.html")
        result = browser.process_target(self.target(), execute=False)
        self.assertEqual(result.status, "eligible")
        remove = next(
            item
            for item in browser.driver.menu_items
            if normalize_ui_text(item.text) == "remove connection"
        )
        self.assertEqual(remove.click_count, 0)

    def test_execute_submits_only_exact_confirmation(self):
        browser = self.make_browser("execute.html")
        result = browser.process_target(self.target(), execute=True)
        self.assertEqual(result.status, "submitted")
        remove_item = next(
            item
            for item in browser.driver.menu_items
            if normalize_ui_text(item.text) == "remove connection"
        )
        confirm = next(
            item
            for item in browser.driver.dialog_buttons
            if normalize_ui_text(item.text) == "remove"
        )
        self.assertEqual(remove_item.click_count, 1)
        self.assertEqual(confirm.click_count, 1)

    def test_ambiguous_remove_menu_fails_closed(self):
        browser = self.make_browser("ambiguous_menu.html")
        result = browser.process_target(self.target(), execute=True)
        self.assertEqual(result.status, "skipped")
        self.assertTrue(all(item.click_count == 0 for item in browser.driver.menu_items))

    def test_ambiguous_confirmation_fails_closed(self):
        browser = self.make_browser("ambiguous_confirmation.html")
        result = browser.process_target(self.target(), execute=True)
        self.assertEqual(result.status, "skipped")
        self.assertTrue(all(item.click_count == 0 for item in browser.driver.dialog_buttons))

    def test_misleading_dialog_fails_closed(self):
        browser = self.make_browser("misleading_dialog.html")
        result = browser.process_target(self.target(), execute=True)
        self.assertEqual(result.status, "skipped")
        self.assertTrue(all(item.click_count == 0 for item in browser.driver.dialog_buttons))

    def test_challenge_fixture_aborts_before_action_discovery(self):
        browser = self.make_browser("challenge.html")
        with self.assertRaises(ChallengeStop):
            browser.process_target(self.target(), execute=False)
        self.assertTrue(all(item.click_count == 0 for item in browser.driver.main_buttons))


if __name__ == "__main__":
    unittest.main()
