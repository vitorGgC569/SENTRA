# Contributing to SENTRA

Thank you for helping improve SENTRA. Before starting, check [open issues](https://github.com/vitorGgC569/SENTRA/issues) or the [starter task list](docs/GOOD_FIRST_ISSUES.md). For a substantial change, open an issue to agree on scope first.

## Development environment

Install Python 3.11 or newer, Git, and Node.js for desktop interface work. Clone the repository, create a virtual environment and install the development dependencies:

```sh
git clone https://github.com/vitorGgC569/SENTRA.git
cd SENTRA
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on Linux/macOS or `.venv\Scripts\Activate.ps1` in PowerShell, then run:

```sh
python -m pip install -r requirements.txt
python -m pytest tests/unit -q
```

The full suite can require optional external services, browsers or platform-specific software; use the relevant targeted tests and report skips. Desktop changes also require `npm ci` and `npm run build` in `sentra_canvas/desktop_ui`. Do not commit credentials, browser profiles, local state, build artifacts or personal data.

## Pull requests

Create a branch, keep changes focused, run tests appropriate to the change, and open a pull request against `main`. Explain the problem, the change and validation in the pull request template. Include screenshots for visible UI changes and disclose any untested platforms or services. See [SECURITY.md](SECURITY.md) for private vulnerability reporting and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community expectations.
