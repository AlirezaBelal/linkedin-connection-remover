import csv
import tempfile
import unittest
from pathlib import Path

from connection_remover import (
    ConfigurationError,
    RemovalResult,
    ResultsWriter,
    choose_confirmation_label,
    choose_remove_label,
    confirm_live_execution,
    dialog_describes_connection_removal,
    is_challenge_url,
    load_targets,
    normalize_profile_url,
    required_confirmation,
    target_ref_for_url,
)


class UrlValidationTests(unittest.TestCase):
    def test_normalizes_supported_profile_url(self):
        url = normalize_profile_url("https://linkedin.com/in/example-profile")
        self.assertEqual(url, "https://www.linkedin.com/in/example-profile/")
        self.assertEqual(len(target_ref_for_url(url)), 16)

    def test_rejects_unsafe_or_non_profile_urls(self):
        invalid = [
            "http://www.linkedin.com/in/example-profile",
            "https://example.com/in/example-profile",
            "https://www.linkedin.com/company/example",
            "https://www.linkedin.com/in/example-profile?trk=test",
            "https://user:pass@www.linkedin.com/in/example-profile",
            "https://www.linkedin.com:8443/in/example-profile",
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                normalize_profile_url(value)


class CsvTests(unittest.TestCase):
    def _write(self, directory: Path, rows):
        path = directory / "connections.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["URL"])
            writer.writeheader()
            for row in rows:
                writer.writerow({"URL": row})
        return path

    def test_load_targets_deduplicates_and_respects_batch_cap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write(
                Path(temp_dir),
                [
                    "https://www.linkedin.com/in/example-a/",
                    "https://linkedin.com/in/example-a",
                    "https://www.linkedin.com/in/example-b/",
                ],
            )
            targets = load_targets(path, max_targets=2)
            self.assertEqual(len(targets), 2)
            self.assertNotEqual(targets[0].target_ref, targets[1].target_ref)

    def test_invalid_rows_fail_closed_without_echoing_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write(Path(temp_dir), ["https://malicious.example/path"])
            with self.assertRaises(ConfigurationError) as context:
                load_targets(path)
            self.assertIn("row", str(context.exception).lower())
            self.assertNotIn("malicious.example", str(context.exception))

    def test_batch_over_limit_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write(
                Path(temp_dir),
                [f"https://www.linkedin.com/in/example-{index}/" for index in range(3)],
            )
            with self.assertRaises(ConfigurationError):
                load_targets(path, max_targets=2)


class SafetySemanticsTests(unittest.TestCase):
    def test_live_confirmation_is_exact(self):
        self.assertEqual(required_confirmation(3), "REMOVE 3 CONNECTIONS")
        self.assertTrue(confirm_live_execution(3, input_fn=lambda _prompt: "REMOVE 3 CONNECTIONS"))
        self.assertFalse(confirm_live_execution(3, input_fn=lambda _prompt: "yes"))

    def test_remove_action_requires_unique_exact_semantics(self):
        self.assertEqual(choose_remove_label(["Message", "Remove connection", "Follow"]), 1)
        self.assertEqual(choose_remove_label(["Remove your connection"]), 0)
        self.assertIsNone(choose_remove_label(["Remove", "Message"]))
        self.assertIsNone(choose_remove_label(["Remove connection", "Remove your connection"]))

    def test_confirmation_accepts_only_unique_remove(self):
        self.assertEqual(choose_confirmation_label(["Cancel", "Remove"]), 1)
        self.assertIsNone(choose_confirmation_label(["Cancel", "Yes"]))
        self.assertIsNone(choose_confirmation_label(["Remove", "Remove"]))

    def test_dialog_requires_affirmative_connection_removal_phrase(self):
        self.assertTrue(dialog_describes_connection_removal("Remove connection?"))
        self.assertTrue(
            dialog_describes_connection_removal("Are you sure you want to remove this connection?")
        )
        self.assertTrue(
            dialog_describes_connection_removal("Remove Example Person from your connections?")
        )
        self.assertFalse(
            dialog_describes_connection_removal(
                "Remove saved item? This dialog does not describe connection removal."
            )
        )

    def test_challenge_detection_stops_known_paths(self):
        self.assertTrue(is_challenge_url("https://www.linkedin.com/checkpoint/challenge/abc"))
        self.assertTrue(is_challenge_url("https://www.linkedin.com/challenge/abc"))
        self.assertFalse(is_challenge_url("https://www.linkedin.com/in/example/"))


class ResultsTests(unittest.TestCase):
    def test_results_are_privacy_safe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "results.csv"
            writer = ResultsWriter(path)
            writer.append(
                RemovalResult(
                    "abcdef1234567890",
                    "dry-run",
                    "eligible",
                    "exact action found",
                )
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("target_ref", text)
            self.assertNotIn("linkedin.com/in/", text)


if __name__ == "__main__":
    unittest.main()
