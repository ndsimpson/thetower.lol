# The Tower tourney results

-   python3.13

## Setup

### Virtual Environment & Dependencies

-   make sure you're running the venv: `source /tourney/.venv/bin/activate`

-   install everything:
    -   `cd /tourney` to make sure we're in the working directory
    -   `pip install -e .` to install the unified project with all dependencies
    -   `python src/thetower/scripts/install_towerbcs.py --auto` to install the battle conditions predictor package
    -   Optional dependency groups:
        -   `pip install -e ".[dev]"` for development tools (pytest, etc.)
        -   `pip install -e ".[bot]"` for Discord bot only
        -   `pip install -e ".[web]"` for web interface only

### Bytecode Cache Management (Recommended)

To keep your project directories clean by centralizing Python bytecode files:

```bash
# Setup centralized bytecode caching
python scripts/manage_bytecode.py setup

# Check current configuration
python scripts/manage_bytecode.py status

# Clean up existing __pycache__ directories
python scripts/manage_bytecode.py cleanup

# For backward compatibility, setup can also be run without arguments
python scripts/manage_bytecode.py
```

This will:

-   Install `sitecustomize.py` to your virtual environment
-   Redirect all `.pyc` files to `.cache/python/` instead of creating `__pycache__` folders
-   Keep your project structure clean for version control
-   Preserve bytecode cache across virtual environment recreations

## Running

-   streamlit run with: `streamlit run components/pages.py`

-   django collect all needed static files: `cd src/thetower/backend && python manage.py collectstatic`
-   django admin run with: `cd src/thetower/backend && DEBUG=true python manage.py runserver`

-   `db.sqlite3` goes to `src/thetower/backend`
-   `uploads` csv folder goes to `src/thetower/backend`

## Modern Package Management

This project now uses `pyproject.toml` for dependency management instead of `requirements.txt`.
All configuration (pytest, black, isort, flake8) is consolidated in this single file.
