# Security Policy

## Supported version

Security fixes are applied to the current `master` branch.

## Sensitive local data

The live input file `data/Connections.csv`, local Chrome profile data, generated results, logs, and optional screenshots are ignored by Git. Do not commit exported LinkedIn data, cookies, browser profiles, authenticated page snapshots, or profile lists.

The tracked `data/Connections.example.csv` contains only explicit placeholder profile URLs.

## Browser authentication

The tool does not accept usernames, passwords, session cookies, or authentication tokens. Authentication is performed manually in the dedicated browser profile. Never add credentials to source code, command-line arguments, or tracked configuration.

## Platform protections

This project does not attempt to bypass CAPTCHAs, checkpoints, login challenges, rate limits, or other platform protections. When a known challenge URL is detected, execution stops rather than attempting a bypass.

## Destructive-action safety

Dry-run is the default. Live removal requires the `--execute` flag, an interactive terminal, and an exact typed confirmation containing the validated target count. The source CSV is never modified. UI actions are accepted only when exact removal semantics are uniquely identified; ambiguous controls fail closed.

## Debugging privacy

Debug screenshots are opt-in. Page HTML is never persisted by the tool. Result files store a short hash reference instead of profile URLs.

## Reporting a vulnerability

Please use GitHub's private security reporting features when available. Do not include credentials, cookies, exported connection lists, private profile URLs, or authenticated screenshots in public issues.
