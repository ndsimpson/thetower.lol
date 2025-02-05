# The Tower tourney results
- python3.12

- make sure you're running the venv: `source /tourney/tourney_venv/bin/activate`

- install everything:
    - `pip install -r requirements.txt` to install the dependencies3
    - `pip install -e .` to install the app
    - `pip install -e thetower` to install the django stuff
    - `pip install -e discord_bot` to install the discord bot

- streamlit run with: `streamlit run components/pages.py`

- django collect all needed static files: `cd thetower/dtower && python .\manage.py collectstatic`
- django admin run with: `cd thetower/dtower && DEBUG=true python manage.py runserver`

- `db.sqlite3` goes to `thetower/dtower`
- `uploads` csv folder goes to `thetower/dtower`
