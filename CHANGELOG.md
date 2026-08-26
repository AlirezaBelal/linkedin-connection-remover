# Changelog

All notable changes to this project are documented here.

## [1.0.0] - 2026-08-26

### Added
- Safety-first CLI with dry-run as the default operating mode.
- Explicit `--execute` gate with exact interactive confirmation.
- Strict LinkedIn profile URL validation, deduplication, and bounded batch sizes.
- Privacy-safe result records using hashed target references instead of profile URLs.
- Optional local debug screenshots without persisted page HTML.
- Checkpoint/challenge detection that stops rather than attempts bypasses.
- Offline unit tests across Python 3.10 through 3.14.
- Fixture-based integration tests for production browser-flow semantics using static HTML and an offline fake driver.
- Dependency auditing, Dependabot configuration, and security documentation.

### Changed
- Removal menu matching now requires one unique exact `Remove connection` semantic action.
- Confirmation requires one unique exact `Remove` button in a dialog that clearly describes connection removal.
- Source CSV files are never mutated and real local input is ignored by Git.

### Removed
- Generic destructive keyword fallbacks such as broad `remove`, `yes`, or `ok` matches.
- Automatic mutation of the source CSV.
- Persistent HTML debug snapshots.
- Anti-detection or human-mimicking guidance.
- `pandas` and `webdriver-manager` dependencies.
