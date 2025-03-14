# Project Copilot Context

## Table of Contents
- [Project Overview](#project-overview)
- [Technologies](#technologies)
- [Code Style & Quality](#code-style--quality)
- [Project Structure](#project-structure)
- [Documentation Standards](#documentation-standards)
- [Development Workflow](#development-workflow)
- [Discord Bot Patterns](#discord-bot-patterns)
  - [Command Security](#command-security)
  - [Settings Commands](#settings-commands)
  - [Info Commands](#info-commands)
  - [Time & Toggle Patterns](#time--toggle-patterns)
- [Project-Specific Guidelines](#project-specific-guidelines)
- [Shorthand Prompts](#shorthand-prompts)
- [Quick Reference](#quick-reference)

## Project Overview
- Python-based application using Django, Streamlit, and Discord integration
- Repository: thetower.lol
- Focus on clean, maintainable code with comprehensive documentation

## Technologies
- Python 3.10+
- Django 4.x (backend framework)
- Streamlit (data visualization and UI)
- Discord.py (Discord bot integration)

---

## Code Style & Quality

### Style Conventions
- Follow PEP 8 conventions
- Use 4 spaces for indentation
- Maximum line length: 88 characters (Black formatter compatible)
- Use type hints for all function parameters and return values
- Prefer f-strings over other string formatting methods, but if no variable is used in the string, don't use an f-string
- Use snake_case for variables and functions
- Use PascalCase for classes
- Prefer double quotes over single quotes
- Use `is`, `is not` for comparison to `None`
- Use `==`, `!=` for equality comparison
- Use `isinstance()` for type checking
- Use `if not x` for empty containers or None
- Avoid mutable default arguments

### Clean Code Principles
- Follow single responsibility principle
- Use descriptive variable and function names
- Avoid magic numbers, use constants instead
- Use list comprehensions and generator expressions where appropriate
- Avoid deeply nested code blocks
- Refactor long functions into smaller, reusable parts

---

## Project Structure
- Django apps in separate directories
- Streamlit pages in `streamlit/` directory
- Discord bot using cogs-based architecture:
  - Cogs organized in `bot/cogs/` directory
  - Each cog is a class that inherits from `commands.Cog`
  - Related commands are grouped within appropriate cogs
  - Common functionality implemented in a `BaseCog` class
- Utility functions in `utils/` directory
- Tests in `tests/` directory parallel to implementation

---

## Documentation Standards
- Docstrings: Google style
- Each function should have a docstring describing purpose, parameters, and return values
- Include examples in docstrings for complex functions
- Each module should have a module-level docstring

### Error Handling
- Use specific exception types, avoid bare `except:`
- Log errors with appropriate severity levels
- User-facing errors should be clear and actionable

### Testing
- Write unit tests for all business logic
- Integration tests for API endpoints
- Use pytest as testing framework
- Aim for >80% test coverage on core functionality

---

## Development Workflow

### Git Conventions
- Use feature branches for new features and bug fixes
- Commit messages should be descriptive and follow the 50/72 rule
- Use imperative mood in commit messages
- Squash commits before merging into main branch

---

## Discord Bot Patterns

### Command Security
- Command permissions are handled via the PermissionManager utility
- Individual cogs should not have command predicates within the cogs themselves
- NEVER add permission checks like @commands.has_permissions() or @commands.check() directly to commands
- Instead, all permission checks are automatically handled by the BaseCog.cog_check method
- All cogs MUST inherit from BaseCog to get proper permission handling
- Permissions are configured through the bot's permission commands after deployment

#### Correct Permission Pattern
1. Inherit from BaseCog
2. Define commands without permission decorators
3. Configure permissions through bot commands

#### Example Implementation
```python
# CORRECT - Do this
from fish_bot.basecog import BaseCog

class MyCog(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        # No permission registration needed in __init__

    @commands.command()
    async def admin_command(self, ctx):
        # BaseCog.cog_check will automatically handle permissions
        await ctx.send("Command executed!")
```

### Settings Commands
When implementing a `settings` command for a cog, follow these standardization patterns:

#### Embed Structure
- **Title**: "{Feature Name} Settings"
- **Description**: "Current configuration for {feature description}"
- **Color**: `discord.Color.blue()`

#### Settings Organization
Group settings into logical categories:
1. **Time Settings**: Format as `{hours}h {minutes}m {seconds}s ({total} seconds)`
   - Applies to intervals, durations, timeouts, etc.
2. **Display Settings**: User-facing configuration values
3. **Flag Settings**: Boolean settings with emoji indicators
   - `✅ Enabled` or `❌ Disabled`
4. **Threshold Settings**: Numerical limits or thresholds

#### Status Information
- Include current operational status with appropriate emoji:
  - `✅ Ready` - System is fully operational
  - `⏳ Initializing` - System is loading
  - `🔄 Processing` - System is currently performing operations
  - `⏸️ Paused` - System is paused
  - `🔍 Dry Run Mode` - System is in test mode

#### Multiple Embeds Pattern
For complex settings, consider using multiple embeds grouped by category:
1. Primary embed with core settings and status
2. Secondary embeds for detailed configuration groups

### Info Commands
When implementing an `info` command for a cog:

#### Core Elements
- **Title**: "{Feature Name} Information"
- **Description**: Brief explanation of the feature's purpose
- **Status Indicator**: Show current operational status with emoji
- **Last Updated**: When applicable, show last refresh time with relative time
- **Dependency Status**: If the feature relies on other cogs/services, show their status
- **Statistics**: Include relevant statistics about the feature's data/operations
- **Footer**: Optional usage hints or additional context

#### Status & Warning Cases
- Use different embed colors to indicate status:
  - Blue (`discord.Color.blue()`) for normal operations
  - Orange (`discord.Color.orange()`) for warnings/initializing
  - Green (`discord.Color.green()`) for success messages
  - Red (`discord.Color.red()`) for errors

### Time & Toggle Patterns

#### Time Representation
For timestamps and durations:
- Format absolute times as `YYYY-MM-DD HH:MM:SS`
- Format relative times as contextual strings:
  - `{n} seconds ago` (less than 1 minute)
  - `{n} minutes ago` (less than 1 hour)
  - `{n} hours ago` (1+ hour)

#### Toggle Formatting
- Pause settings should be toggled via a simple "pause" command:
  - Without arguments: Alternates between true and false (paused/unpaused)
  - With optional boolean argument: `/cogname pause [True|False]` to explicitly set the paused state
  - Command should confirm the new state: "System is now ⏸️ Paused" or "System is now ✅ Running"

- All other flag settings should be toggled via a single unified "toggle" command:
  - Basic usage: `/cogname toggle setting_name` alternates the specified setting between true and false
  - Extended usage: `/cogname toggle setting_name [True|False]` to explicitly set to specified state
  - The command should confirm the new state in the response: "Setting `setting_name` is now ✅ Enabled"

#### Helper Methods
Consider implementing these utility methods in your cogs:
- `format_time_value(seconds)`: Formats seconds into hours, minutes, seconds
- `format_relative_time(timestamp)`: Shows time elapsed since a timestamp

---

## Project-Specific Guidelines

### Imports
- Don't leave unused imports behind
- Use absolute imports for Discord cogs

### Configuration Management
- The ConfigManager class (primarily used in bot.py and basecog.py) handles application settings
- Configuration files store infrequently changed application parameters
- The settings file is saved in json format

### Settings Management
- **Don't** use class constants for default settings initialization (e.g., `DEFAULT_TIMEOUT = 60`)
- Instead, initialize settings directly in the `__init__` method with descriptive comments
- When initializing cog settings, check if they exist and set defaults as needed
- Document default values with clear comments when they're set
- For time-based settings, use descriptive variable assignments rather than magic numbers

#### Preferred Settings Initialization Pattern
```python
def __init__(self, bot):
    super().__init__(bot)  # Initialize the BaseCog

    # Initialize core instance variables
    self.member_roles = {}
    self._fetching_guilds = set()
    self._update_queues = {}

    # Store a reference to this cog on the bot for easy access
    self.bot.role_cache = self

    # Set default settings if they don't exist
    if not self.has_setting("results_per_page"):
        self.set_setting("results_per_page", 5)  # Show 5 results per page by default

    if not self.has_setting("cache_refresh_interval"):
        self.set_setting("cache_refresh_interval", 3600)  # Refresh cache hourly (in seconds)

    if not self.has_setting("info_max_results"):
        self.set_setting("info_max_results", 3)  # Show up to 3 matches for info command

    # Load settings into instance variables for convenience
    self.results_per_page = self.get_setting("results_per_page")
    self.cache_refresh_interval = self.get_setting("cache_refresh_interval")
    self.info_max_results = self.get_setting("info_max_results")

    # Initialize logging
    self.logger = logging.getLogger(__name__)
```

### Data Persistence
- Cogs with frequently updated user/runtime data should use self.data_directory from BaseCog
- Save files store dynamic data that changes during normal application usage
- Use appropriate serialization methods based on data complexity and access patterns
- Preferred file formats are pickle and json

---

## Shorthand Prompts
- "Add typing": Add type hints to function
- "Docstring": Generate Google-style docstring
- "Test this": Generate pytest unit tests for selected function
- "Refactor": Apply clean code principles while maintaining functionality
- "Discord command": Create a new Discord bot command with error handling
- "Django view": Create a Django view with appropriate patterns
- "Streamlit component": Create a Streamlit UI component

---

## Quick Reference

### Status Emoji
- `✅` Success / Enabled / Ready
- `❌` Disabled / Error
- `⏳` Initializing / Waiting
- `🔄` Processing / In Progress
- `⏸️` Paused
- `🔍` Dry Run / Testing Mode

### Embed Colors
- Normal operations: `discord.Color.blue()`
- Warnings/initializing: `discord.Color.orange()`
- Success messages: `discord.Color.green()`
- Errors: `discord.Color.red()`

### Command Patterns
- Settings: `/cogname settings`
- Info: `/cogname info`
- Toggle: `/cogname toggle setting_name [True|False]`
- Pause: `/cogname pause [True|False]`