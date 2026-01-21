# GitHub Copilot Instructions for thetower.lol

## Project Overview

Multi-service platform for "The Tower" game tournament results and community management:

- **Django Backend** (`src/thetower/backend/`): SQLite database with tourney results, player moderation, REST API
- **Discord Bot** (`src/thetower/bot/`): Multi-guild bot with cog-based architecture for validation, roles, stats, live data
- **Streamlit Web** (`src/thetower/web/`): Public/admin interfaces for visualizing tournament data and statistics
- **Background Services**: Automated result fetching, data imports, recalculation workers, live bracket generation

## Architecture & Structure

### Modern src/ Layout (Aug 2025 Restructure)

Reorganized from flat structure to modern `src/` layout with entry points in `pyproject.toml`:

```
src/thetower/
├── backend/          # Django project
│   ├── towerdb/     # Django settings (DJANGO_SETTINGS_MODULE="thetower.backend.towerdb.settings")
│   ├── tourney_results/  # Main app: models, views, import/export, background services
│   │   ├── import/  # CSV import logic
│   │   └── management/  # Django management commands
│   └── sus/         # Player moderation/ban system
├── bot/             # Discord bot
│   ├── bot.py       # Main bot entry point
│   ├── basecog.py   # Base class for all cogs (~1000 lines of shared functionality)
│   ├── cogs/        # Feature modules (11 cogs: validation, roles, stats, etc.)
│   │   └── */ui/    # UI components organized by function (core, user, admin, settings)
│   ├── utils/       # ConfigManager, PermissionManager, TaskTracker, DataManager
│   └── exceptions.py  # Custom exceptions (UserUnauthorized, ChannelUnauthorized)
└── web/             # Streamlit interfaces
    ├── pages.py     # Main entry point with page routing
    ├── admin/       # Admin interface (service status, migrations, codebase analysis)
    ├── live/        # Live tournament tracking and bracket visualization
    └── historical/  # Historical data analysis and player stats
```

### Django + Shared Database Pattern

- All components import Django: `os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings"); django.setup()`
- Database: `/data/tower.sqlite3` (Linux prod) or `c:\data\tower.sqlite3` (Windows dev) - same path structure
- Core models in `tourney_results/models.py`: `TourneyResult`, `TourneyRow`, `Role`, `PatchNew`, `BattleCondition`, `Avatar`, `Relic`
- Moderation in `sus/models.py`: `KnownPlayer`, `PlayerId`, `ModerationRecord`
- Always use Django ORM - never raw SQL
- SQLite timeout set to 60s in settings to handle concurrent access

### Discord Bot Cog Architecture

All bot features extend `BaseCog` (`src/thetower/bot/basecog.py` - 1000+ lines):

- **Per-guild settings**: `self.get_setting(guild_id, key)`, `self.set_setting(guild_id, key, value)`
- **Data persistence**: `self.load_data()`, `self.save_data_if_modified()` with `DataManager`
- **Task tracking**: `async with self.task_tracker.task_context("task_name"):` for background tasks
- **Ready state**: Wait for `await self.ready.wait()` before accessing guild data
- **Settings UI**: Each cog defines `settings_view_class` for `CogManager` to integrate into global `/settings` command
- **Permission context**: `PermissionContext` dataclass with `.has_any_group()`, `.has_all_groups()`, `.has_discord_role()`

Example cog structure (see [../docs/cog_design.md](../docs/cog_design.md) for detailed 968-line architecture guide):

```python
class MyCog(BaseCog, name="My Feature"):
    settings_view_class = MySettingsView  # For global settings integration

    def __init__(self, bot):
        super().__init__(bot)
        self.guild_settings = {"enabled": True, "channel_id": None}
        self.global_settings = {"admin_groups": ["Moderators"]}

    async def cog_load(self):
        await super().cog_load()
        # Load cog-specific data

    @app_commands.command(name="mycommand")
    async def my_slash(self, interaction: discord.Interaction):
        # Slash command implementation - await self.ready.wait() if needed
```

**Current cogs** (11 total):

- `battle_conditions`: Battle condition predictor (towerbcs integration)
- `django_admin`: Web admin interface access via Discord
- `manage_sus`: Player moderation and ban management
- `player_lookup`: Player stats and history lookup
- `role_cache`: Guild role caching and management
- `tourney_live_data`: Live tournament data fetching and display
- `tourney_roles`: Tournament role assignment automation
- `tourney_role_colors`: Role color management
- `tourney_stats`: Tournament statistics and analysis
- `unified_advertise`: Cross-guild advertisement system
- `validation`: Player verification system

### External Cog Plugin System

**CogManager** (`src/thetower/bot/utils/cogmanager.py`) supports loading cogs from multiple sources via Python entry points:

- **Built-in cogs**: `src/thetower/bot/cogs/` (always available)
- **External cog packages**: Auto-discovered via `importlib.metadata.entry_points()` group `"thetower.bot.cogs"`
- **Discovery**: Happens at bot startup, can be refreshed via `/settings` → Bot Settings → Cog Management → "Refresh Cog Sources"
- **No hardcoding needed**: External packages self-register by declaring entry points in their `pyproject.toml`

**Creating external cog packages**:

1. Create separate repository with structure:

    ```
    my-external-cogs/
    ├── pyproject.toml
    └── src/
        └── my_package/
            └── cogs/
                ├── __init__.py
                └── my_cog.py
    ```

2. Declare entry point in `pyproject.toml`:

    ```toml
    [project]
    name = "my-external-cogs"
    dependencies = ["thetower @ git+https://github.com/ndsimpson/thetower.lol.git"]

    [project.entry-points."thetower.bot.cogs"]
    my_external_cogs = "my_package.cogs"
    ```

3. External cogs inherit `BaseCog` normally:

    ```python
    from thetower.bot.basecog import BaseCog

    class MyExternalCog(BaseCog, name="External Feature"):
        # Full BaseCog functionality available
    ```

4. Install and discover:
    ```powershell
    pip install git+https://github.com/yourname/my-external-cogs.git
    # In Discord: /settings → Bot Settings → Cog Management → Click "Refresh Cog Sources"
    ```

**Benefits**: Separate repositories for sensitive/proprietary cogs, optional features, or experimental code without cluttering main repo.

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

# Install battle conditions predictor (requires repo access)
python src\thetower\scripts\install_towerbcs.py --auto

# Centralized bytecode caching (recommended - keeps __pycache__ out of git)
python scripts\manage_bytecode.py setup
python scripts\manage_bytecode.py status    # Check configuration
python scripts\manage_bytecode.py cleanup   # Clean existing __pycache__
```

### Running Components Locally

```powershell
# Streamlit web interface
streamlit run src\thetower\web\pages.py

# Django admin (for database management)
cd src\thetower\backend
python manage.py collectstatic  # Collect static files first
$env:DEBUG="true"; python manage.py runserver

# Discord bot (requires environment variables)
$env:DISCORD_TOKEN="..."; $env:DISCORD_APPLICATION_ID="..."; python -m thetower.bot.bot

# Background services (run as modules)
python -m thetower.backend.tourney_results.import.import_results
python -m thetower.backend.tourney_results.get_results
python -m thetower.backend.tourney_results.get_live_results
```

### Production Deployment

Services run via systemd on Linux:

**Service files**:

- Web: `tower-public_site.service`, `tower-admin_site.service`, `tower-hidden_site.service`
- Bot: `discord_bot.service` (unified bot, replaces old fish_bot/validation_bot)
- Data: `import_results.service`, `get_results.service`, `get_live_results.service`
- Workers: `tower-recalc_worker.service`, `generate_live_bracket_cache.service`

**Environment variables** in service files:

- `DJANGO_SETTINGS_MODULE=thetower.backend.towerdb.settings`
- `DISCORD_TOKEN`, `DISCORD_APPLICATION_ID`, `DISCORD_BOT_CONFIG=/data`
- `HIDDEN_FEATURES=true` (enables admin features)
- `BASE_URL=hidden.thetower.lol` (for bot URL generation)
- `ANTHROPIC_API_KEY` (for AI features)
- `TOWERBCS_REPO_URL` (for battle conditions predictor updates)

**Paths**:

- Database: `/data/tower.sqlite3`
- Uploads: `/data/uploads/`
- Static files: `/data/static/`
- Bot config: `/data/` (guild configs, data persistence)
- Working directory: `/tourney` (most services) or `/tourney/src` (Django module execution)

**Deployment**: Code deployments are automated through the web admin interface - git pull and service restarts are handled programmatically (see [src/thetower/web/admin/](../src/thetower/web/admin/) for deployment tools).

## Project-Specific Conventions

### Python Standards

- **Line length**: 150 characters (NOT 79) - configured in black/flake8/isort
- PEP 8 naming: 4-space indents, snake_case functions, CamelCase classes
- Import order: standard library → third-party → local (`from thetower.backend...`)
- Type hints on public functions/methods
- Docstrings with clear parameter and return descriptions

### Package Management

- **Use `pyproject.toml` exclusively** - no `requirements.txt`
- Dependencies: `[project.dependencies]` for core, `[project.optional-dependencies]` for dev/bot/web
- Pin exact versions for reproducibility (e.g., `Django==5.2.4`)
- Entry points: `[project.scripts]` defines `thetower-web` and `thetower-bot` commands
- Update dependencies: Edit `pyproject.toml`, then `pip install -e .`

### Django Conventions

- **Models**: Use ForeignKey relationships, ColorField for colors, `simple_history` for audit trails
- **Settings**: Centralized in `towerdb/settings.py`, SECRET_KEY read from file, `/data/` for production
- **Migrations**: Always generate: `python manage.py makemigrations`
- **Admin**: Customize in `admin.py` for each app, register models with sensible list_display
- **Database**: SQLite with 60s timeout, shared across all services via `/data/tower.sqlite3`

### Discord Bot Patterns

- **Slash commands only**: Use `@app_commands.command()`, no text commands (`command_prefix=[]` in bot init)
- **Permission checks**: Use `PermissionManager.check_command_permissions()`, raise `UserUnauthorized`/`ChannelUnauthorized`
- **Guild isolation**: All cog data keyed by `guild_id`, settings per-guild via `BaseCog.get_setting()`
- **UI organization**: Discord UI components in `cogs/*/ui/` directories (core, user, admin, settings subdirs)
- **Background tasks**: Wrap in `async with self.task_tracker.task_context("name"):` for monitoring
- **Ready state**: Always `await self.ready.wait()` before accessing guild data in cog methods
- **Exception handling**: Cogs raise custom exceptions, bot's global error handler formats user-friendly messages

### Logging

- Module-level: `logger = logging.getLogger(__name__)` consistently
- Bot cogs: Use `self.logger` (inherited from BaseCog) or `self._logger` internally
- Format: `"%(asctime)s UTC [%(name)s] %(levelname)s: %(message)s"` with UTC timestamps
- Control: `LOG_LEVEL` environment variable (INFO/DEBUG/WARNING)
- Discord logging: Separate logger with `propagate=False` to avoid duplicates

### Data Files & Paths

- **Production**: `/data/` (Linux) - database, uploads, static, bot configs
- **Development**: `c:\data\` (Windows) - mirrors prod structure for consistency
- **Database**: `/data/tower.sqlite3` or `c:\data\tower.sqlite3`
- **Uploads**: `/data/uploads/` (CSV files for import)
- **Static**: `/data/static/` (Django collectstatic output)
- **Bot config**: `/data/` (DataManager saves guild-specific JSON files)
- **Bytecode cache**: `.cache/python/` (via `scripts/manage_bytecode.py setup`) - keeps `__pycache__` out of git

## Critical Integration Points

### Django ↔ Discord Bot

- Bot imports Django models directly after `django.setup()`
- Example: `from thetower.backend.sus.models import KnownPlayer`
- Access tourney results, roles, player data via Django ORM
- Bot modifies database (e.g., verification, role assignments)

### Streamlit ↔ Django

- Streamlit pages import Django: same `django.setup()` pattern
- Query models for visualization: `TourneyResult.objects.filter(...)`
- No direct database writes from Streamlit in production

### Background Services ↔ Django

- Services like `import_results.py` run as modules: `python -m thetower.backend.tourney_results.import.import_results`
- Schedule-based polling (via `schedule` library)
- Import CSV data from `/data/uploads/` into Django models

## Key Files Reference

- `src/thetower/bot/basecog.py`: Base class for all bot cogs (~1000 lines of shared functionality)
- `src/thetower/bot/utils/`: ConfigManager, PermissionManager, TaskTracker, DataManager
- `src/thetower/backend/tourney_results/models.py`: Core database schema
- `src/thetower/backend/towerdb/settings.py`: Django configuration
- `../docs/cog_design.md`: Detailed 968-line cog architecture guide (read for complex bot features)
- `scripts/manage_bytecode.py`: Centralized bytecode cache management (run `setup` first)
- `c:\data\Services\UPDATE_CHECKLIST.md`: Production deployment procedures (575 lines)
- `pyproject.toml`: All dependencies, build config, and tool settings (black, pytest, isort, flake8)

## Windows PowerShell Environment

- Primary development OS is Windows with PowerShell
- Command chaining: Use `;` (NOT `&&`)
- Path separators: `\` in PowerShell commands, `/` for Python Path objects
- Environment variables: `$env:VAR_NAME="value"` (temporary) or `[System.Environment]::SetEnvironmentVariable()` (persistent)
- Virtual env activation: `.\.venv\Scripts\Activate.ps1`
- Common gotchas: PowerShell doesn't support `&&` chaining, use `;` instead for sequential commands

``
