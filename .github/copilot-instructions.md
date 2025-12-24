# GitHub Copilot Instructions for thetower.lol

## Project Overview

A multi-service platform for "The Tower" game tournament results and community management:

-   **Django Backend** (`src/thetower/backend/`): SQLite database with tourney results, player management, and REST API
-   **Discord Bot** (`src/thetower/bot/`): Multi-guild bot with cog-based architecture for verification, roles, stats
-   **Streamlit Web** (`src/thetower/web/`): Public/admin web interfaces for visualizing tournament data
-   **Background Services**: Automated result fetching, data imports, recalculation workers

## Architecture & Structure

### Modern src/ Layout (Aug 2025 Restructure)

The codebase was reorganized from flat structure to modern `src/` layout:

```
src/thetower/
├── backend/          # Django project
│   ├── towerdb/     # Django settings (DJANGO_SETTINGS_MODULE="thetower.backend.towerdb.settings")
│   ├── tourney_results/  # Main app: models, views, import scripts
│   └── sus/         # Player management/ban system
├── bot/             # Discord bot
│   ├── bot.py       # Main bot entry point
│   ├── basecog.py   # Base class for all cogs with shared functionality
│   ├── cogs/        # Feature modules (validation, roles, stats, etc.)
│   └── utils/       # ConfigManager, PermissionManager, TaskTracker
└── web/             # Streamlit interfaces
    ├── pages.py     # Main entry point
    ├── admin/       # Admin interface pages
    ├── live/        # Live tournament tracking
    └── historical/  # Historical data visualization
```

### Django + Shared Database Pattern

-   Bot and web components both import Django: `environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings"); django.setup()`
-   Database at `/data/tower.sqlite3` (Linux prod) or `c:\data\tower.sqlite3` (Windows dev) - same path structure for consistency
-   Models in `tourney_results/models.py`: `TourneyResult`, `Role`, `PatchNew`, `TourneyRow`, etc.
-   Always use Django ORM for database access, never raw SQL

### Discord Bot Cog Architecture

All bot features extend `BaseCog` (`src/thetower/bot/basecog.py`):

-   **Per-guild settings**: `self.get_setting(guild_id, key)`, `self.set_setting(guild_id, key, value)`
-   **Data persistence**: `self.load_data()`, `self.save_data_if_modified()` with `DataManager`
-   **Task tracking**: `async with self.task_tracker.task_context("task_name"):` for background tasks
-   **Ready state**: Wait for `await self.ready.wait()` before accessing guild data
-   **Settings UI**: Each cog defines `settings_view_class` for `CogManager` to integrate into global `/settings` command

Example cog structure (see `docs/cog_design.md` for detailed architecture):

```python
class MyCog(BaseCog, name="My Feature"):
    settings_view_class = MySettingsView  # For global settings access

    async def cog_load(self):
        await super().cog_load()
        # Load cog-specific data

    @app_commands.command(name="mycommand")
    async def my_slash(self, interaction: discord.Interaction):
        # Slash command implementation
```

## Development Workflows

### Setup & Installation

```powershell
# Windows PowerShell - activate venv
.\.venv\Scripts\Activate.ps1

# Install project with all dependencies
pip install -e .

# Optional dependency groups
pip install -e ".[dev]"   # pytest, black, isort, flake8
pip install -e ".[bot]"   # Discord bot only
pip install -e ".[web]"   # Streamlit only

# Install battle conditions predictor
python src\thetower\scripts\install_towerbcs.py --auto

# Centralized bytecode caching (recommended)
python scripts\manage_bytecode.py setup
```

### Running Components Locally

```powershell
# Streamlit web interface
streamlit run src\thetower\web\pages.py

# Django admin (for database management)
cd src\thetower\backend
$env:DEBUG="true"; python manage.py runserver
python manage.py collectstatic  # Collect static files first

# Discord bot (requires env vars)
$env:DISCORD_TOKEN="..."; python -m thetower.bot.bot
```

### Production Deployment

Services run via systemd on Linux (see `c:\data\Services\UPDATE_CHECKLIST.md`):

-   `tower-public_site.service`, `tower-admin_site.service`, `tower-hidden_site.service`
-   `discord_bot.service` (unified bot, replaces old fish_bot/validation_bot)
-   `import_results.service`, `get_results.service`, `get_live_results.service`
-   Database: `/data/tower.sqlite3`, uploads: `/data/uploads/`

**Critical**: Always stop ALL services before deploying code changes.

### Testing

```powershell
# Run tests with pytest (requires [dev] dependencies)
pytest src\thetower\backend\tourney_results\tests\
pytest --tb=short  # Shorter traceback format
```

## Project-Specific Conventions

### Python Standards

-   PEP 8 compliance: 79 char lines, 4-space indents, snake_case functions, CamelCase classes
-   Import order: standard library → third-party → local (`from thetower.backend...`)
-   Type hints on public functions/methods
-   Docstrings with clear descriptions of parameters and return values

### Package Management

-   **Use `pyproject.toml` exclusively** - no `requirements.txt`
-   Dependencies declared in `[project.dependencies]` and `[project.optional-dependencies]`
-   Pin exact versions for reproducibility (e.g., `Django==5.2.4`)
-   Update `pyproject.toml` when adding dependencies, then `pip install -e .`

### Django Conventions

-   **Models**: Use ForeignKey relationships, ColorField for colors, `simple_history` for tracking
-   **Settings**: Centralized in `towerdb/settings.py`, read SECRET_KEY from file, use `/data/` for production paths
-   **Migrations**: Always generate migrations: `python manage.py makemigrations`
-   **Admin**: Customize admin in `admin.py` for each app

### Discord Bot Patterns

-   **Slash commands only**: Use `@app_commands.command()`, no text commands
-   **Permission checks**: Bot has `PermissionManager` and custom `UserUnauthorized`/`ChannelUnauthorized` exceptions
-   **Guild isolation**: All cog data keyed by `guild_id`, settings per-guild via `BaseCog.get_setting()`
-   **UI components**: Use `discord.ui.View` subclasses in `cogs/*/ui/` directories
-   **Background tasks**: Wrap in `task_tracker.task_context()` for monitoring/error handling

### Logging

-   Use module-level `logger = logging.getLogger(__name__)` consistently
-   Bot components: `from thetower.bot import logger` or `self.logger` in cogs
-   Format: `"%(asctime)s UTC [%(name)s] %(levelname)s: %(message)s"`
-   Control via `LOG_LEVEL` environment variable

### Data Files & Paths

-   Production data: `/data/` (Linux) - database, uploads, static files
-   Dev data: `c:\data\` (Windows) - uses same path structure as prod for consistency
-   Database: `/data/tower.sqlite3` (prod) or `c:\data\tower.sqlite3` (dev)
-   Centralized bytecode: `.cache/python/` (via `scripts/manage_bytecode.py setup`)
-   Keep `__pycache__` out of git

## Critical Integration Points

### Django ↔ Discord Bot

-   Bot imports Django models directly after `django.setup()`
-   Example: `from thetower.backend.sus.models import KnownPlayer`
-   Access tourney results, roles, player data via Django ORM
-   Bot modifies database (e.g., verification, role assignments)

### Streamlit ↔ Django

-   Streamlit pages import Django: same `django.setup()` pattern
-   Query models for visualization: `TourneyResult.objects.filter(...)`
-   No direct database writes from Streamlit in production

### Background Services ↔ Django

-   Services like `import_results.py` run as modules: `python -m thetower.backend.tourney_results.import.import_results`
-   Schedule-based polling (via `schedule` library)
-   Import CSV data from `/data/uploads/` into Django models

## Key Files Reference

-   `src/thetower/bot/basecog.py`: Base class for all bot cogs (600+ lines of shared functionality)
-   `src/thetower/bot/utils/`: ConfigManager, PermissionManager, TaskTracker, DataManager
-   `src/thetower/backend/tourney_results/models.py`: Core database schema
-   `src/thetower/backend/towerdb/settings.py`: Django configuration
-   `docs/cog_design.md`: Detailed cog architecture guide (read for complex bot features)
-   `scripts/manage_bytecode.py`: Bytecode cache management (run `setup` first)
-   `c:\data\Services\UPDATE_CHECKLIST.md`: Production deployment procedures

## Windows PowerShell Environment

-   Primary development OS is Windows with PowerShell
-   Command chaining: Use `;` (NOT `&&`)
-   Path separators: `\` in PowerShell, `/` for Python Path objects
-   Environment variables: `$env:VAR_NAME="value"` (temporary) or `[System.Environment]::SetEnvironmentVariable()`
-   Virtual env activation: `.\.venv\Scripts\Activate.ps1`
