# LinkedIn Connection Remover

Automates removing LinkedIn connections from a list of profile URLs.

Important notes
- This script automates actions on LinkedIn. Using automation may violate LinkedIn's Terms of Service and can risk account restrictions. Use carefully, add human-like delays, and test on a spare account first.
- The script opens a separate Chrome process with its own profile (stored in `chrome-user-data/` next to the project) so it does not interfere with your daily Chrome profile.

Prerequisites
- Google Chrome installed.
- Python 3.9+.
- Create and activate a virtual environment.

Install
1. Create and activate virtualenv:
   - Windows: `python -m venv .venv && .venv\Scripts\activate`
   - macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`

2. Install requirements:
```
pip install -r requirements.txt
```

Prepare input CSV
- The script expects `data/Connections.csv` with a header column named `URL`.
- Example:
```
URL
https://www.linkedin.com/in/example1
https://www.linkedin.com/in/example2
```

Where to get profile URLs
- Option A — LinkedIn data export:
  - LinkedIn > Me > Settings & Privacy > Data privacy > Get a copy of your data > Connections.
  - Note: LinkedIn export may not include profile URLs. If not present, use Option B.
- Option B — Manual copy:
  - Open each connection's profile and copy the profile URL (the `https://www.linkedin.com/in/...`).
  - Paste into `data/Connections.csv`.

Run (first time)
1. Ensure Chrome is installed.
2. Run:
   - Windows: `.venv\Scripts\python.exe remove_linkedin_connections.py`
   - macOS/Linux: `./.venv/bin/python remove_linkedin_connections.py`
3. On first run the script creates `chrome-user-data/` and opens a Chrome window. If not logged in in that profile, log in and press ENTER in terminal to continue.

Configuration
- `DRY_RUN` in `remove_linkedin_connections.py`: set `True` to simulate actions without performing removals.
- `MIN_DELAY` / `MAX_DELAY`: adjust delays between profiles to mimic human behavior.

Output
- `output/results.csv` contains the run results.
- `output/debug/` contains screenshots and HTML snapshots for failures.

Security & safety
- Test on a secondary account before using on your main account.
- Keep execution rate conservative and randomize delays.
- Do not commit `chrome-user-data/` or any sensitive debug snapshots to the repository.

License
- MIT License (see LICENSE file).