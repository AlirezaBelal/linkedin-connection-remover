import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_validate_placeholder_input(self):
        result = subprocess.run(
            [
                sys.executable,
                "remove_linkedin_connections.py",
                "--input",
                "data/Connections.example.csv",
                "--validate-input",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Input valid: 3 unique target(s).", result.stdout)

    def test_live_execution_is_rejected_without_interactive_terminal(self):
        result = subprocess.run(
            [
                sys.executable,
                "remove_linkedin_connections.py",
                "--input",
                "data/Connections.example.csv",
                "--execute",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("interactive terminal", result.stderr)

    def test_invalid_input_does_not_echo_unsafe_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "invalid.csv"
            path.write_text("URL\nhttps://private.invalid/not-a-profile\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "remove_linkedin_connections.py",
                    "--input",
                    str(path),
                    "--validate-input",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("row", result.stderr.lower())
        self.assertNotIn("private.invalid", result.stderr)


if __name__ == "__main__":
    unittest.main()
