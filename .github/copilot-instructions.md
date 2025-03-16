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
  - [Standard Cog Commands](#standard-cog-commands)
  - [Settings Commands](#settings-commands)
  - [Status Commands](#status-commands)
  - [Info Commands](#info-commands)
  - [Time & Toggle Patterns](#time--toggle-patterns)
  - [Cog Initialization & Ready State Pattern](#cog-initialization--ready-state-pattern)
  - [Command Type System](#command-type-system)
- [Project-Specific Guidelines](#project-specific-guidelines)
  - [Imports](#imports)
  - [Configuration Management](#configuration-management)
  - [Settings Management](#settings-management)
  - [Data Persistence](#data-persistence)
  - [File Handling Patterns](#file-handling-patterns)
  - [Logging Patterns](#logging-patterns)
  - [Task Tracking](#task-tracking)
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

### Standard Cog Commands
Each cog should implement the following standard commands:

1. **Settings Command**: Displays all configurable settings for the cog
   - Command name: `settings`
   - Shows current configuration with formatting based on setting type
   - Allows administrators to view how the cog is configured

2. **Status Command**: Shows operational status of the cog
   - Command name: `status`
   - Displays current state, dependencies, and relevant metrics
   - Provides administrators with immediate insight into cog functionality

These standard commands ensure consistent user experience and simplify administration across all cogs.

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

#### Multiple Embeds Pattern
For complex settings, consider using multiple embeds grouped by category:
1. Primary embed with core settings and status
2. Secondary embeds for detailed configuration groups

### Status Commands
All cogs should implement a `status` command that provides at-a-glance operational information:

#### Embed Structure
- **Title**: "{Feature Name} Status"
- **Description**: Brief summary of operational state
- **Color**: Varies based on status (blue for normal, orange for warnings, red for errors)

#### Key Elements to Include
1. **Operational State**: Current running state with appropriate emoji
   - `✅ Operational` - All systems functioning normally
   - `⚠️ Degraded` - Functioning with limitations or warnings
   - `❌ Error` - Not functioning properly
   - `⏸️ Paused` - Temporarily suspended

2. **Dependencies**:
   - List required services/cogs with their availability status
   - Format: `{dependency_name}: ✅ Available` or `{dependency_name}: ❌ Unavailable`

3. **Active Processes**:
   - Show currently running operations: `🔄 Process X running (started HH:MM:SS ago)`
   - Show queued operations: `⏳ N operations in queue`

4. **Resource Usage** (when applicable):
   - Memory usage
   - API call counts/limits
   - Cache status

5. **Last Activity**:
   - When was the last operation completed
   - Format with relative time: `Last operation: 5 minutes ago`

#### Example Implementation
```python
@commands.command(name="status")
async def show_status(self, ctx):
    """Display current operational status of this feature."""

    # Determine overall status
    if self.paused:
        status_emoji = "⏸️"
        status_text = "Paused"
        embed_color = discord.Color.orange()
    elif self._has_errors:
        status_emoji = "❌"
        status_text = "Error"
        embed_color = discord.Color.red()
    else:
        status_emoji = "✅"
        status_text = "Operational"
        embed_color = discord.Color.blue()

    # Create status embed
    embed = discord.Embed(
        title="Feature Name Status",
        description=f"Current status: {status_emoji} {status_text}",
        color=embed_color
    )

    # Add dependency information
    dependencies = []
    if hasattr(self.bot, "required_cog"):
        dependencies.append(f"Required Cog: {'✅ Available' if self.bot.get_cog('RequiredCog') else '❌ Unavailable'}")

    if dependencies:
        embed.add_field(name="Dependencies", value="\n".join(dependencies), inline=False)

    # Add process information
    if self._active_process:
        embed.add_field(
            name="Active Processes",
            value=f"🔄 {self._active_process} (started {self._format_relative_time(self._process_start_time)} ago)",
            inline=False
        )

    # Add statistics
    if hasattr(self, '_operation_count'):
        embed.add_field(name="Statistics", value=f"Operations completed: {self._operation_count}", inline=False)

    # Add last activity
    if self._last_operation_time:
        embed.add_field(
            name="Last Activity",
            value=f"Last operation: {self._format_relative_time(self._last_operation_time)} ago",
            inline=False
        )

    await ctx.send(embed=embed)
```

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

#### Time Formatting Helper Methods
BaseCog provides two standard helper methods for time formatting that all cogs inherit:

1. `format_time_value(seconds)`: Formats seconds into a human-readable string
   ```python
   # Example usage in a cog
   formatted_time = self.format_time_value(3665)  # Returns "1h 1m 5s (3665 seconds)"
   ```

2. `format_relative_time(timestamp)`: Shows time elapsed since a timestamp
   ```python
   # Example usage in a cog
   relative_time = self.format_relative_time(some_datetime)  # Returns "5 minutes ago"
   ```

These methods should be used in status commands, settings displays, and other places where
consistent time representation is needed. There's no need to implement these methods in
individual cogs as they're inherited from BaseCog.

### Cog Initialization & Ready State Pattern

### Cog Lifecycle Management
- All cogs must inherit from `BaseCog` to leverage consistent initialization
- Don't emit custom events for cog ready state; use the built-in ready state tracking system
- The `BaseCog` class provides a complete ready state tracking system using `asyncio.Event`
- All cogs MUST implement the `cog_initialize()` async method for initialization
- Every cog MUST ensure it properly signals readiness through the BaseCog ready system
- Cog class names and command groups should follow the cog file names and be lowercase without underscores.
  - Example: `foo_bar.py` should define class `FooBar(BaseCog)` with command group `foobar` and command group method of `foobar_group`
  - This ensures consistent and predictable command navigation for users

### Ready State Pattern
The `BaseCog` class implements a standardized ready state tracking system:

1. **State Tracking Attributes**
   - `_ready`: asyncio.Event that signals when the cog is fully initialized
   - `_ready_task`: Task that handles initialization sequence
   - `_ready_timeout`: Maximum time to wait for initialization (default 60 seconds)

2. **Initialization Flow**
   - When bot emits `on_ready`, the base cog creates an initialization task
   - Initialization calls `cog_initialize()` if implemented by the cog
   - After successful initialization, the `_ready` event is set automatically
   - If `cog_initialize()` raises an exception, the cog will be marked as failed

3. **Ready State Methods**
   - `wait_until_ready()`: Async method to wait for cog initialization
   - `is_ready`: Property that returns whether the cog is ready
   - `set_ready_timeout()`: Method to customize the timeout duration
   - `mark_ready()`: Method to manually mark cog as ready (rarely needed)

### Implementation Pattern (REQUIRED)
Every cog MUST implement the cog_initialize method:

```python
from fish_bot.basecog import BaseCog

class MyCog(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        self.my_data = None  # Will be populated during initialization

    async def cog_initialize(self) -> None:
        """Initialize cog-specific resources after bot is ready.

        This method is REQUIRED for all cogs. The BaseCog will automatically
        mark the cog as ready when this method completes successfully.
        """
        # Perform async initialization tasks here
        self.my_data = await self.load_data("my_data_file.json", default={})

        # Optional: set up periodic tasks
        self.bot.loop.create_task(self.periodic_maintenance())

        # NOTE: No need to call self.mark_ready() - BaseCog does this automatically
        # when cog_initialize() completes successfully

    async def my_command(self, ctx):
        """A command that requires cog to be fully initialized."""
        # Wait for initialization before proceeding
        if not await self.wait_until_ready():
            await ctx.send("⏳ Still initializing, please try again later.")
            return

        # Now safe to use initialized resources
        await ctx.send(f"Data loaded: {len(self.my_data)} items")
```

### Important Implementation Notes
1. The `cog_initialize()` method is **REQUIRED** for all cogs
2. Do NOT manually call `self.mark_ready()` unless you have a specific reason
3. The base initialization system will:
   - Call your `cog_initialize()` method when the bot is ready
   - Automatically mark the cog as ready when initialization succeeds
   - Mark the cog as failed if initialization raises an exception
   - Apply the configured timeout to prevent indefinite blocking
4. Always implement proper ready-state checking for commands that depend on initialization

### Command Type System

The bot supports dynamic command registration that can be configured at runtime using a flexible command type system.

#### Command Type Options
Commands can be configured to use one of four modes:
- `prefix`: Traditional prefix commands only (e.g., `$command`)
- `slash`: Slash commands only (e.g., `/command`)
- `both`: Both prefix and slash commands enabled
- `none`: Command disabled completely

#### Implementation Pattern
All cogs MUST use the `@BaseCog.command` and `@BaseCog.group` decorators:

```python
from fish_bot.basecog import BaseCog

class MyCog(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)

    @BaseCog.command(name="example")
    async def example_command(self, ctx, parameter: str = None):
        """An example command with type flexibility."""
        await ctx.send(f"Command executed with: {parameter}")

    @BaseCog.command(name="search")
    async def search_command(
        self,
        ctx,
        query: str = commands.param(description="Search term to look for"),
        limit: int = commands.param(description="Maximum results to return", default=5)
    ):
        """Search for something in the system."""
        await ctx.send(f"Searching for: {query} with limit {limit}")
```

#### Dynamic Command Configuration
Commands can be configured through bot commands:

1. Set Default Mode:
   ```
   $command_type set_default both     # Sets default mode for all commands
   ```

2. Configure Individual Commands:
   ```
   $command_type set settings slash   # Force a command to slash-only
   $command_type set help prefix      # Force a command to prefix-only
   ```

3. Reset to Default:
   ```
   $command_type reset settings       # Reset command to use default mode
   ```

4. View Configuration:
   ```
   $command_type                      # Shows current command type settings
   ```

#### Command Registration Process
The command type system follows this process:

1. During cog initialization, `cog_initialize()` calls `register_commands()`
2. Each command's type is determined from settings:
   - First checks command-specific setting
   - Falls back to default mode if no override exists
3. Commands are registered according to their type:
   - `prefix`: Only traditional command
   - `slash`: Only slash command
   - `both`: Both command types
   - `none`: Command is disabled
4. Changes require syncing with Discord:
   ```
   $command_type sync    # Updates slash commands with Discord
   ```

#### Guidelines for Command Design
When creating commands that support both prefix and slash modes:
- Use `commands.param()` for all parameters to provide descriptions
- Keep parameter types compatible with slash commands
- Avoid using `*args` or `**kwargs`
- Use command groups for organization
- Provide clear help text and parameter descriptions

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

### File Handling Patterns

#### BaseCog Data Management Pattern
When implementing file operations in cogs, follow these patterns for consistent data management:

##### File Path Management
- Use `Path` objects from `pathlib` instead of string manipulation
- Define file paths as properties to centralize path construction
- Always use the BaseCog's data directory as the base path

```python
from pathlib import Path

class MyCog(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)

        # Initialize file settings
        if not self.has_setting("data_filename"):
            self.set_setting("data_filename", "my_data.json")

        self.data_filename = self.get_setting("data_filename")

    @property
    def data_file(self) -> Path:
        """Get the data file path using the cog's data directory"""
        return self.data_directory / self.data_filename
```

##### Data Loading and Saving
- Use BaseCog's built-in utilities instead of raw file operations
- For JSON: `load_json_sync()`, `save_json_sync()`
- For Pickle: `load_pickle_sync()`, `save_pickle_sync()`
- Call `mark_data_modified()` after modifying data to track changes
- Async versions are also available: `await self.load_data()`, `await self.save_data_if_modified()`

```python
def load_my_data(self) -> Dict:
    """Load data from file."""
    try:
        # Use BaseCog's utility to load data
        data = self.load_json_sync(self.data_file)
        if (data):
            return data
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        self._has_errors = True

    return {}  # Default empty structure

def save_my_data(self) -> None:
    """Save data to file."""
    try:
        # Use BaseCog's utility to save data
        self.save_json_sync(self.my_data, self.data_file)
        self.mark_data_modified()
    except Exception as e:
        logger.error(f"Error saving data: {e}")
        self._has_errors = True
```

##### Settings for File Management
- Store filenames in settings rather than hardcoding them
- Include toggle commands to allow changing filenames without code changes
- Update file paths when settings change

##### Error Handling
- Set `self._has_errors` flag when file operations fail
- Log specific error messages with appropriate severity
- Provide fallbacks for missing or corrupted data

##### Cog Initialization and Unloading
- Load data during `cog_initialize()`
- Save modified data during `cog_unload()`
- Setup periodic saving tasks when appropriate

### Logging Patterns

#### Using BaseCog Logger

BaseCog provides a built-in logger property that cogs should use for all logging:

```python
# CORRECT - Use the BaseCog logger
async def my_command(self, ctx):
    try:
        result = await self.perform_operation()
        self.logger.info(f"Operation completed successfully with result: {result}")
        await ctx.send("Success!")
    except Exception as e:
        self.logger.error(f"Error in my_command: {e}", exc_info=True)
        await ctx.send("An error occurred")
```

The `logger` property automatically:
- Configures the correct logger name based on the cog class name
- Inherits the project's log formatting and output destinations
- Ensures consistent log behavior across all cogs

#### Log Levels

Use appropriate log levels based on the significance of the event:

1. **DEBUG**: Detailed information used for troubleshooting
   ```python
   self.logger.debug(f"Processing item {item_id} with parameters {params}")
   ```

2. **INFO**: Confirmation that things are working as expected
   ```python
   self.logger.info(f"User {user.name} successfully updated their settings")
   ```

3. **WARNING**: Something unexpected happened but the application can continue
   ```python
   self.logger.warning(f"Rate limit approaching: {rate_limit_info}")
   ```

4. **ERROR**: An operation failed but the application can still function
   ```python
   self.logger.error(f"Failed to process request: {e}", exc_info=True)
   ```

5. **CRITICAL**: A failure that requires immediate attention
   ```python
   self.logger.critical(f"Database connection lost: {e}", exc_info=True)
   ```

#### Error Logging Best Practices

When logging exceptions:
- Always include the exception object
- Use `exc_info=True` for ERROR and CRITICAL logs to include the traceback
- Provide context about what operation was being attempted

```python
try:
    await self.complex_operation()
except Exception as e:
    self.logger.error(
        f"Failed during {operation_name} for user {user_id}: {e}",
        exc_info=True
    )
```

#### Command Execution Logging

For command-specific logging:
- Log the start and end of complex commands
- Include the command invoker's information
- Log performance metrics for resource-intensive operations

```python
@commands.command()
async def complex_command(self, ctx, *args):
    """Execute a complex operation."""
    start_time = time.time()
    self.logger.info(f"Command {ctx.command.name} invoked by {ctx.author} with args: {args}")

    try:
        # Command implementation
        result = await self.process_command_logic(*args)
        elapsed = time.time() - start_time
        self.logger.info(f"Command {ctx.command.name} completed in {elapsed:.2f}s")
        await ctx.send(f"Operation completed with result: {result}")
    except Exception as e:
        self.logger.error(f"Error in {ctx.command.name}: {e}", exc_info=True)
        await ctx.send("An error occurred during command execution")
```

#### Avoiding Common Logging Mistakes

1. **Don't** create new loggers in cog methods - always use `self.logger`
2. **Don't** use print statements for debugging - use `logger.debug` instead
3. **Don't** log sensitive information (tokens, passwords, etc.)
4. **Don't** log excessive information at INFO level (use DEBUG for detailed logs)
5. **Avoid** string formatting for DEBUG logs that won't be shown in production

### Task Tracking

The TaskTracker utility provides standardized task tracking, history, and performance statistics.

#### Using TaskTracker

All cogs should use the `task_tracker` property from BaseCog to track significant operations:

```python
# Begin tracking a task with an initial status
self.task_tracker.begin_task("Data Update", "Fetching data from API")

# Update status during execution
self.task_tracker.update_task_status("Data Update", "Processing results")

# End task with success/failure status
self.task_tracker.end_task("Data Update", success=True)
# OR for failure:
self.task_tracker.end_task("Data Update", success=False, status="Error: API timeout")
```

#### Simplified Task Wrapping

For simple task tracking, use the convenience wrapper method:

```python
# Automatically handles begin_task and end_task
result = await self.task_tracker.task_wrapped(
    "Complex Operation",
    self._process_data,  # Any async function
    arg1, arg2,          # Positional args
    kwarg=value          # Keyword args
)
```

#### Status Commands Integration

Use the BaseCog helper method to add task tracking to status embeds:

```python
@commands.command(name="status")
async def show_status(self, ctx):
    """Display operational status."""
    embed = discord.Embed(title="Status", color=discord.Color.blue())

    # Add task tracking fields to the embed
    self.add_task_status_fields(embed)

    await ctx.send(embed=embed)
```

#### TaskTracker Key Methods

- `begin_task(task_name, status)`: Start tracking a new task
- `end_task(task_name, success, status)`: End tracking for a task
- `update_task_status(task_name, status)`: Update status during execution
- `get_active_tasks()`: Get all currently running tasks
- `get_task_stats()`: Get execution statistics for tasks
- `get_task_history()`: Get execution history records
- `has_errors()`: Check if any tasks have failed
- `get_status_report()`: Generate comprehensive status report

#### Error State Management

Check for and handle task errors in commands:

```python
if self.task_tracker.has_errors():
    # Handle error state (e.g., show in status command)
    embed.color = discord.Color.red()
    embed.description = "❌ System has encountered errors"
```

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