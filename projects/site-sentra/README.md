# site-sentra

Sample OMA mission. This folder is not the public website.

- `mission-site-v1.txt` is a Portuguese prompt that asks OMA to build a small static site as five DAG tasks, each kept near the project's 250-line delivery size.
- `tests/test_site.py` only checks that this directory exists. `pytest.ini` collects the repository-root `tests/` tree, so this file is not part of `python -B -m pytest tests -q`.
- The published download page lives in `site/` and is linked from the root README.

Nothing in this folder starts a server.
