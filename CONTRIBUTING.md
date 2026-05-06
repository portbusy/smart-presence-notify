# Contributing to Smart Presence Notify

Thanks for taking the time to contribute.

## Requirements

- Python 3.13
- Home Assistant ≥ 2026.1.0

## Setup

```bash
git clone https://github.com/portbusy/smart-presence-notify.git
cd smart-presence-notify
python -m venv .venv && source .venv/bin/activate
pip install homeassistant pip install -r requirements_test.txt
```

## Running tests

```bash
pytest tests/ -v
```

All tests must pass before submitting a PR.

## Submitting changes

1. Fork the repo and create a branch from `main`.
2. Make your changes.
3. Add or update tests to cover the changed behaviour.
4. Bump `manifest.json` version if the change is user-facing.
5. Open a pull request — the template will guide you through the checklist.

## Reporting bugs

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml). For security vulnerabilities, see [SECURITY.md](SECURITY.md).

## Code style

- Follow existing patterns in the codebase.
- No new comments unless the *why* is non-obvious.
- Keep changes focused — one concern per PR.
