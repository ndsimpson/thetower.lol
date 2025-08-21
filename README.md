# The Tower tourney results
- python3.13

- make sure you're running the venv: `source /tourney/tourney_venv/bin/activate`

- install everything:
    - `cd /tourney` to make sure we're in the working directory
    - `pip install -e .` to install the unified project with all dependencies
    - Optional dependency groups:
        - `pip install -e ".[dev]"` for development tools (pytest, etc.)
        - `pip install -e ".[bot]"` for Discord bot only
        - `pip install -e ".[web]"` for web interface only
    - `pip install -e towerbcs` to install the private BC generator

- streamlit run with: `streamlit run components/pages.py`

- django collect all needed static files: `cd thetower/dtower && python manage.py collectstatic`
- django admin run with: `cd thetower/dtower && DEBUG=true python manage.py runserver`

- `db.sqlite3` goes to `thetower/dtower`
- `uploads` csv folder goes to `thetower/dtower`

## Modern Package Management

This project now uses `pyproject.toml` for dependency management instead of `requirements.txt`.
All configuration (pytest, black, isort, flake8) is consolidated in this single file.
