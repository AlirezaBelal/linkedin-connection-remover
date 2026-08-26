#!/usr/bin/env python3
"""CLI for the safety-first LinkedIn connection removal utility."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from connection_remover import (
    ConfigurationError,
    LinkedInBrowser,
    RemovalError,
    ResultsWriter,
    confirm_live_execution,
    load_targets,
    run_targets,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Review LinkedIn profile targets in dry-run mode by default and only submit "
            "connection removals after an explicit live confirmation."
        )
    )
    parser.add_argument("--input", default="data/Connections.csv", help="CSV file containing a URL column")
    parser.add_argument("--results", default="output/results.csv", help="Privacy-safe result CSV path")
    parser.add_argument(
        "--profile-dir",
        default=".local/chrome-profile",
        help="Dedicated local Chrome profile directory",
    )
    parser.add_argument("--max-targets", type=int, default=10, help="Safety batch cap (1-50; default: 10)")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=5.0,
        help="Fixed delay between targets (default: 5 seconds)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Enable destructive removal after exact interactive confirmation",
    )
    parser.add_argument(
        "--debug-screenshots",
        action="store_true",
        help="Opt in to local screenshots on failures; page HTML is never saved",
    )
    parser.add_argument(
        "--validate-input",
        action="store_true",
        help="Validate and count targets without launching a browser",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.delay_seconds < 0 or args.delay_seconds > 300:
            raise ConfigurationError("delay_seconds must be between 0 and 300")

        targets = load_targets(Path(args.input), max_targets=args.max_targets)
        if args.validate_input:
            print(f"Input valid: {len(targets)} unique target(s).")
            return 0

        mode = "LIVE EXECUTION" if args.execute else "DRY RUN"
        print(f"Mode: {mode}; targets: {len(targets)}; source CSV will not be modified.")

        if args.execute:
            if args.delay_seconds < 2:
                raise ConfigurationError("live execution requires delay_seconds of at least 2")
            if not sys.stdin.isatty():
                raise ConfigurationError("live execution requires an interactive terminal")
            if not confirm_live_execution(len(targets)):
                raise ConfigurationError("live execution confirmation did not match exactly")

        browser = LinkedInBrowser(
            profile_dir=Path(args.profile_dir),
            debug_dir=Path("output/debug"),
            debug_screenshots=args.debug_screenshots,
        )
        writer = ResultsWriter(Path(args.results))
        try:
            browser.start()
            browser.ensure_manual_login()
            results = run_targets(
                browser=browser,
                targets=targets,
                writer=writer,
                execute=args.execute,
                delay_seconds=args.delay_seconds,
            )
        finally:
            browser.close()

        failures = sum(result.status in {"failed"} for result in results)
        skips = sum(result.status == "skipped" for result in results)
        print(f"Completed: {len(results)} target(s); failed={failures}; safety-skipped={skips}.")
        return 1 if failures else 0

    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except RemovalError as exc:
        print(f"Run stopped: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
