# Contributing to KindEro

Thanks for your interest in KindEro. Bug reports, fixes and improvements are welcome.

## Development setup

```bash
git clone https://github.com/LucasDavidTPE/KindEro
cd KindEro
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Python 3.10 or newer is required.

## Running the tests

```bash
python -m pytest
```

Tests must not access the network. HTTP calls to the Zotero API and SMTP connections must be replaced by fakes or mocks in the tests. A test that needs the network is a bug in the test.

## Code structure

KindEro is split into small modules (`zotero.py`, `kindle.py`, `clippings.py`, `sync.py`, `devices.py`, `config.py`, `cli.py`, with shared dataclasses in `models.py`). The module boundaries and function signatures are described in `PLAN.md`. Keep each module within its contract: if a change needs a different signature or a new shared type, discuss it in an issue first rather than changing it silently.

## Guidelines

- Add or update tests for every behavior change.
- Keep dependencies to the minimum (`requests`, `pypdf`, and `tomli` on Python below 3.11).
- Keep the Kindle side free of any software installed on the device: that is a project constraint.

## Licensing of contributions

KindEro is licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later). By submitting a contribution, you agree that it is licensed under the same terms. See [LICENSE](LICENSE).
