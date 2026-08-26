# LinkedIn Connection Remover

A safety-first, browser-assisted Python utility for reviewing a bounded list of LinkedIn profile connections and, only after explicit confirmation, submitting removal actions.

## Why this version is different

The project treats connection removal as a destructive operation. It is intentionally conservative:

- dry-run is the default;
- live execution requires `--execute`, an interactive terminal, and an exact typed confirmation;
- input URLs are strictly validated as HTTPS LinkedIn `/in/` profile URLs;
- the batch size is capped (10 by default, 50 maximum);
- ambiguous UI controls fail closed;
- only an exact `Remove connection` action and an exact `Remove` confirmation are accepted;
- the source CSV is never modified;
- result files use a hashed target reference rather than profile URLs;
- debug screenshots are opt-in and page HTML is never saved;
- CAPTCHA/checkpoint/challenge flows are not bypassed.

> LinkedIn UI automation can break when the site changes and may be restricted by LinkedIn's terms or policies. Use this project only for an account you control and only where your use is permitted.

## Architecture

```text
Connections.csv
      |
      v
strict URL validation + deduplication + batch cap
      |
      v
manual login in dedicated Chrome profile
      |
      v
exact profile action discovery
      |
      +---- dry-run (default) ---> eligibility result only
      |
      +---- --execute -----------> exact confirmation gate
                                     |
                                     v
                            submit Remove confirmation
      |
      v
privacy-safe results.csv
```

## Requirements

- Python 3.10+
- Google Chrome or Chromium
- Selenium 4

Selenium Manager is used by Selenium itself for compatible driver discovery, so this project does not depend on `webdriver-manager`.

## Install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

## Prepare input

Copy the tracked placeholder file and replace its entries locally:

```bash
cp data/Connections.example.csv data/Connections.csv
```

The only required column is `URL`:

```csv
URL
https://www.linkedin.com/in/example-profile-001/
```

`data/Connections.csv` is ignored by Git. Additional columns from a LinkedIn export are allowed but are not read by the tool.

Validate the input without launching Chrome:

```bash
python remove_linkedin_connections.py --validate-input
```

## Dry-run workflow (default)

```bash
python remove_linkedin_connections.py
```

Dry-run can open each validated profile and inspect its actions, but it does **not** click the removal item or confirmation button. It reports `eligible` only when one unique exact removal action is found.

The default safety batch cap is 10:

```bash
python remove_linkedin_connections.py --max-targets 5
```

The maximum accepted cap is 50.

## Live execution

Live removal must be explicitly enabled:

```bash
python remove_linkedin_connections.py --execute
```

Before Chrome starts, the CLI requires a typed phrase containing the validated target count, for example:

```text
REMOVE 3 CONNECTIONS
```

There is intentionally no non-interactive `--yes` bypass.

## Login and browser profile

A dedicated Chrome profile is stored under `.local/chrome-profile/` by default. If LinkedIn is not logged in, log in manually in the opened browser and then return to the terminal. The tool does not accept or store usernames, passwords, cookies, or tokens.

If LinkedIn redirects to a known checkpoint/challenge path, the run stops rather than attempting to bypass it.

## Results and privacy

`output/results.csv` contains:

```text
timestamp,target_ref,mode,status,detail
```

`target_ref` is a short SHA-256-derived identifier. Profile URLs are not written to the result file.

Debug screenshots are disabled by default. To opt in:

```bash
python remove_linkedin_connections.py --debug-screenshots
```

Screenshots may contain private account information. They are stored under ignored `output/debug/`. HTML snapshots are never persisted.

## Status meanings

- `eligible` — dry-run found one unique exact removal action.
- `submitted` — live mode clicked the exact `Remove` confirmation; this describes submission, not guaranteed server-side completion.
- `skipped` — a safety check could not establish unambiguous removal semantics.
- `failed` — an unexpected browser interaction failed.

## Testing and CI

Tests are deliberately offline and do not connect to LinkedIn. They cover:

- strict URL validation and canonicalization;
- duplicate handling and batch caps;
- privacy-safe error/result behavior;
- exact live confirmation semantics;
- exact action/confirmation matching;
- challenge-path detection;
- CLI validation using placeholder input.

GitHub Actions tests Python 3.10 through 3.14 and runs dependency auditing. CI never performs account actions or sends traffic to LinkedIn.

## Project scope

This is a small browser-assisted automation project, not a general LinkedIn bot framework. It does not implement CAPTCHA solving, challenge bypass, stealth/anti-detection techniques, credential automation, scraping at scale, or destructive source-data mutation.

## License

MIT License. See `LICENSE`.
