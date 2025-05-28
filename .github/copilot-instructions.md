# Fish Bot Copilot Instructions

You are assisting with a Discord.py bot project called "Fish Bot" with a structured codebase centered around the BaseCog pattern.

## Project Architecture

- This project uses Discord.py with a custom BaseCog class as the foundation for all cogs
- Cogs follow a consistent initialization pattern with settings validation, task tracking, and status reporting
- The project uses mixins for shared functionality and follows a structured error handling approach
- Data persistence is handled through the BaseCog's data management system
- The project follows a standardized directory structure for organizing cog components
- Cogs are organized into functional modules with clear separation of concerns
- Components communicate through well-defined interfaces and state management

## Environment Configuration

### Development Environment
- Windows operating system
- PowerShell as primary terminal
- Development tools and testing run in PowerShell environment
- Use PowerShell-compatible commands in development scripts
- Path separators should use `Path` from `pathlib` for cross-platform compatibility

### Production Environment
- Linux operating system
- Standard shell environment
- Production deployment and execution on Linux
- All scripts must maintain cross-platform compatibility

### Cross-Platform Development Guidelines
- Use `pathlib.Path` for all file path operations
- Avoid platform-specific shell commands
- Test scripts in both PowerShell and bash environments
- Use platform-agnostic environment variables
- Handle line endings appropriately (use .gitattributes)
- Use forward slashes (/) in string paths when hardcoding is necessary
- For file operations, prefer Python's built-in functions over shell commands

### Directory Structure
```
cogs/
  example_cog/
    __init__.py      # Cog registration
    cog.py           # Main cog implementation
    commands.py      # Command definitions
    tasks.py         # Background tasks and periodic operations
    listeners.py     # Event listeners and handlers
    utils.py         # Utility functions and mixins
    constants.py     # Constants and enums
```

### Core Components

1. **BaseCog**: Foundation class providing:
   - Asynchronous initialization and ready state management
   - Settings management with validation
   - Data management with automatic saving
   - Command registration and permission handling
   - Status monitoring and statistics
   - Task tracking and management
   - Pause/resume functionality

2. **TaskTracker**: System for monitoring operations:
   - Active task tracking
   - Status reporting
   - Error monitoring
   - Performance statistics

3. **Mixins Architecture**:
   - CommandsMixin for command definitions
   - ListenersMixin for event handlers
   - TasksMixin for background task management (implemented in tasks.py)
   - UtilityMixin for shared functionality

## Code Generation Guidelines

1. When creating new cogs:
   - Extend BaseCog
   - Define settings_config in __init__ with proper validation rules
   - Override cog_initialize() with proper task tracking
   - Use task_context for all operations
   - Implement _add_status_fields() for status reporting

2. When implementing commands:
   - Use Discord.py command decorators (@commands.command, @commands.group)
   - Group related commands into command groups
   - Follow error handling patterns
   - Include complete docstrings
   - Rely on BaseCog for permission checks (no need to implement cog_check)

3. When creating background tasks:
   - Use @tasks.loop decorator with appropriate interval
   - Include bot.wait_until_ready() and wait_until_ready() checks
   - Check is_paused state before operation
   - Use task_tracker.task_context for tracking
   - Handle exceptions properly

4. When implementing settings:
   - Define in settings_config with (default, description, validators)
   - Use appropriate validators: type.*, range(), time.*, discord.*
   - Group related settings
   - Include descriptive comments

## Coding Standards

- Use Python type hints consistently
- Follow PEP 8 style guidelines
- Import order: standard library → third-party → local
- Class structure: docstring → class vars → __init__ → properties → public methods → private methods
- Use descriptive variable and function names following snake_case
- Classes use CapWords convention
- Private methods/variables are prefixed with _

## Code Patterns

```python
# BaseCog initialization pattern
def __init__(self, bot):
    settings_config = {
        "setting_name": (default_value, "Setting description", "validator"),
    }
    super().__init__(bot, settings_config)
    self.additional_setup()

# Task initialization pattern
async def cog_initialize(self) -> None:
    try:
        async with self.task_tracker.task_context("Initialization") as tracker:
            await super().cog_initialize()
            tracker.update_status("Starting tasks")
            # Cog-specific initialization
            self.set_ready(True)
            tracker.update_status("Ready")
    except Exception:
        self._has_errors = True
        raise

# Background task pattern
@tasks.loop(minutes=5, reconnect=True)
async def periodic_task(self):
    await self.bot.wait_until_ready()
    await self.wait_until_ready()

    if self.is_paused:
        return

    async with self.task_tracker.task_context("Task Name") as tracker:
        try:
            tracker.update_status("Processing")
            # Task implementation
            tracker.update_status("Completed successfully")
        except Exception as e:
            tracker.update_status("Failed", success=False)
            self.logger.error(f"Task failed: {e}")
            raise

# Command implementation pattern
class MyCog(BaseCog):
    def __init__(self, bot):
        # ... initialization code ...

    @commands.command(name="mycommand")
    async def my_command(self, ctx):
        """Command description for help text."""
        async with self.task_tracker.task_context("MyCommand") as tracker:
            try:
                # Command implementation
                await ctx.send("Command executed successfully")
            except Exception as e:
                tracker.update_status("Failed", success=False)
                self.logger.error(f"Command failed: {e}")
                await ctx.send("An error occurred")
                raise
```

## Error Handling

Fish Bot uses a consistent error handling pattern across all cogs, integrating with the TaskTracker system for comprehensive error management:

### Task Context Error Handling
```python
async with self.task_tracker.task_context("Operation Name") as tracker:
    try:
        tracker.update_status("Processing")
        # Implementation
        tracker.update_status("Complete")
    except Exception as e:
        self.logger.error(f"Operation failed: {e}")
        tracker.update_status("Failed", success=False)
        raise  # Always re-raise to ensure proper error propagation
```

### Initialization Error Pattern
```python
async def cog_initialize(self) -> None:
    try:
        async with self.task_tracker.task_context("Initialization") as tracker:
            await super().cog_initialize()
            tracker.update_status("Starting tasks")
            # Initialization code
            self.set_ready(True)
    except Exception:
        self._has_errors = True  # Set error state
        raise  # Re-raise to prevent cog loading
```

### Background Task Error Handling
```python
@tasks.loop(minutes=1, reconnect=True)
async def periodic_task(self):
    await self.wait_until_ready()

    async with self.task_tracker.task_context("Task Name") as tracker:
        try:
            tracker.update_status("Running")
            # Task implementation
        except Exception as e:
            self.logger.error(f"Task error: {e}")
            tracker.update_status(f"Error: {e}")
            self._has_errors = True
            await asyncio.sleep(self.error_retry_delay)
```

### Error Recovery
```python
async def handle_error(self, error: Exception) -> None:
    """Handle errors with proper logging and state updates."""
    self._has_errors = True
    self.logger.error(f"Error occurred: {error}", exc_info=True)

    # Implementation-specific recovery
    if isinstance(error, RecoverableError):
        await self.attempt_recovery()
    else:
        await self.cleanup_resources()
```

### Retry Logic
```python
async def operation_with_retry(self):
    retries = 3
    for attempt in range(retries):
        try:
            return await self.operation()
        except RetryableError as e:
            if attempt == retries - 1:
                raise
            self.logger.warning(f"Retry {attempt + 1}/{retries}: {e}")
            await asyncio.sleep(self.retry_delay)
```

### Resource Cleanup
```python
async def cleanup_resources(self):
    async with self.task_tracker.task_context("Cleanup") as tracker:
        try:
            tracker.update_status("Cleaning up")
            # Cleanup implementation
            self._has_errors = False  # Reset error state
        except Exception as e:
            self.logger.error(f"Cleanup failed: {e}")
            tracker.update_status("Failed")
            self._has_errors = True
            raise
```

### Error Best Practices
- Use task_context for operation tracking
- Set appropriate error states
- Log errors with context
- Clean up resources on failure
- Re-raise when appropriate
- Use appropriate log levels
- Handle recoverable vs. non-recoverable errors
- Implement retry logic when appropriate

## Validation Rules

Fish Bot implements a sophisticated settings validation system:

### Basic Validators
- `type.int`: Integer validation
- `type.str`: String validation
- `type.bool`: Boolean validation
- `type.float`: Float validation
- `type.list`: List validation
- `type.dict`: Dictionary validation

### Range and Length Validators
- `range(min,max)`: Numeric range validation
- `length(min,max)`: Sequence length validation
- `pattern(regex)`: String pattern matching

### Time Validators
- `time.seconds(min,max)`: Time in seconds
- `time.minutes(min,max)`: Time in minutes (auto-converted)
- `time.hours(min,max)`: Time in hours (auto-converted)

### Discord Entity Validators
- `discord.channel`: Channel ID validation
- `discord.role`: Role ID validation
- `discord.user`: User ID validation

### Collection Validators
- `collection.list(item_type,unique,min_length,max_length)`: List validation
- `collection.dict(key_type,value_type,required_keys)`: Dictionary validation

### Combining Validators
Validators can be combined in lists or chained:
```python
settings_config = {
    # Multiple validators
    "interval": (300, "Update interval in seconds",
        ["type.int", "range(60,3600)"]),  # Between 1 and 60 minutes

    # Collection validation
    "allowed_roles": ([], "List of allowed role IDs",
        ["type.list", "collection.list(item_type=int,unique=true)"]),

    # Custom validation function
    "custom_setting": (10, "Custom setting",
        lambda x: x > 0 and x < 100)
}
```

### Settings Access Patterns
```python
# Get a setting with default fallback
interval = self.get_setting("update_interval", 300)

# Get guild-specific setting
guild_setting = self.get_setting("setting_name", default, guild_id=guild.id)

# Update a setting
self.set_setting("max_items", 20)  # Validates automatically

# Update multiple settings
self.update_settings({
    "batch_size": 100,
    "retry_count": 5
})  # All updates validated
```

## Data Management

Fish Bot provides a sophisticated data management system with automatic persistence, change tracking, and caching. The system handles two distinct types of data:

### 1. Settings Data
Settings data is managed centrally by BaseCog's ConfigManager and stored in a centralized bot settings file:
- Automatically loaded during cog initialization
- Automatically saved when changed (via set_setting or update_settings)
- Typically changes infrequently
- Accessed through the settings management API
- No manual loading/saving required by individual cogs

```python
# Access settings (automatically loaded by BaseCog)
interval = self.get_setting("update_interval", 300)

# Update settings (automatically saved by ConfigManager)
self.set_setting("max_items", 20)
```

### 2. Cache Data
Cache data is specific to each cog, changes more frequently, and is managed by the individual cog:
- Cog is responsible for loading/saving its own cache data
- Requires explicit saving by the cog
- Typically stored in cog-specific files
- Often changes frequently
- May require periodic saving

```python
# Cache file path property
@property
def cache_file(self) -> Path:
    """Get the cache file path."""
    return self.data_directory / self.get_setting('cache_filename')
```

### Cache Data Loading and Saving
```python
# Loading cache data with default fallback
self._cache = await self.load_data(self.cache_file, default={})

# Saving cache data if modified
await self.save_data_if_modified(self._cache, self.cache_file)

# Setting up periodic save for frequently changing cache data
await self.create_periodic_save_task(
    self._cache,
    self.cache_file,
    save_interval=300  # 5 minutes
)
```

### Change Tracking
```python
# Mark cache data as modified
self.mark_data_modified()

# Check if cache data modified
if self.is_data_modified():
    await self.save_data_if_modified(self._cache, self.cache_file)
```

### Cache Management
```python
# Cache initialization in __init__
def __init__(self, bot):
    settings_config = {
        # Other settings
        "cache_filename": ("my_cache.json", "Filename for cache data"),
        "cache_save_interval": (300, "Cache save interval in seconds", "type.int"),
        "cache_max_age": (3600, "Maximum cache age in seconds", "type.int")
    }
    super().__init__(bot, settings_config)
    self._cache = {}
    self._cache_timestamp = None

# Cache update
async def update_cache(self):
    """Update the cache with fresh data."""
    self._cache = await self.fetch_fresh_data()
    self._cache_timestamp = datetime.now(timezone.utc)
    self.mark_data_modified()

# Cache validation
async def validate_cache(self):
    """Check if cache needs refresh."""
    if not self._cache_timestamp:
        return False

    age = datetime.now(timezone.utc) - self._cache_timestamp
    max_age = self.get_setting('cache_max_age', 3600)
    
    return age.total_seconds() < max_age
```

### Lifecycle Management
During initialization, load cache data and set up periodic saves:
```python
async def cog_initialize(self) -> None:
    try:
        async with self.task_tracker.task_context("Initialization"):
            await super().cog_initialize()
            
            # Settings are already loaded by BaseCog automatically
            
            # Load cog-specific cache data
            self._cache = await self.load_data(self.cache_file, default={})
            
            # Start periodic saves for cache data
            await self.create_periodic_save_task(
                self._cache,
                self.cache_file,
                self.get_setting('cache_save_interval', 300)
            )
            
            self.set_ready(True)
    except Exception:
        self._has_errors = True
        raise
```

During unload, ensure cache data is saved:
```python
async def cog_unload(self) -> None:
    try:
        # Save cache data one last time
        if self.is_data_modified():
            await self.save_data_if_modified(
                self._cache,
                self.cache_file,
                force=True
            )

        # Cancel save tasks
        self.cancel_save_tasks()
        
        await super().cog_unload()
    except Exception as e:
        self.logger.error(f"Error during unload: {e}")
        raise
```

### Data Management Best Practices
- Use settings for configuration options that change infrequently
- Use cache data for frequently changing state or retrieved information
- Implement proper cache invalidation
- Set appropriate save intervals based on update frequency
- Always clean up resources during unload
- Use default values for resilience
- Validate data after loading
- Implement error recovery for corrupt data

## Permission System

Fish Bot provides a comprehensive permission system for controlling access to commands and features. **This system is implemented in BaseCog and automatically applied to all derived cogs - individual cogs should not implement permission checks directly.**

### Basic Permission Infrastructure
```python
from fish_bot.exceptions import ChannelUnauthorized, UserUnauthorized

# These methods are implemented in BaseCog and don't need to be 
# reimplemented in derived cogs
class BaseCog:
    async def check_permissions(self, ctx) -> bool:
        """Check if operation is permitted."""
        # Channel authorization
        if not await self.is_channel_authorized(ctx.channel):
            raise ChannelUnauthorized("Not an authorized channel")

        # Role checking
        if not await self.has_required_role(ctx.author):
            raise UserUnauthorized("Missing required role")

        return True
            
    async def cog_check(self, ctx: commands.Context) -> bool:
        """Permission check for traditional commands."""
        try:
            return await self.check_permissions(ctx)
        except (ChannelUnauthorized, UserUnauthorized) as e:
            self.logger.warning(f"Permission denied: {e}")
            return False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Permission check for slash commands."""
        try:
            return await self.check_permissions(interaction)
        except (ChannelUnauthorized, UserUnauthorized) as e:
            self.logger.warning(f"Permission denied: {e}")
            return False
```

### Channel Authorization
BaseCog provides methods for channel authorization:
```python
async def is_channel_authorized(self, channel: discord.TextChannel) -> bool:
    """Check if channel is authorized."""
    allowed_channels = self.get_setting('allowed_channels', [])
    restricted_channels = self.get_setting('restricted_channels', [])

    # Check restrictions
    if restricted_channels and channel.id in restricted_channels:
        return False

    # Check allowlist
    if allowed_channels:
        return channel.id in allowed_channels

    return True  # No restrictions
```

### Role Requirements
```python
async def has_required_role(self, member: discord.Member) -> bool:
    """Check if member has required roles."""
    required_roles = self.get_setting('required_roles', [])

    # No requirements
    if not required_roles:
        return True

    # Check member roles
    member_roles = [role.id for role in member.roles]
    return any(role_id in member_roles for role_id in required_roles)
```

### Command-Specific Permissions
```python
async def check_command_permissions(self, ctx, command_name: str) -> bool:
    """Check command-specific permissions."""
    permissions = self.load_command_permissions()

    if command_name in permissions:
        cmd_perms = permissions[command_name]

        # Check roles
        if 'roles' in cmd_perms:
            member_roles = [role.id for role in ctx.author.roles]
            if not any(role in member_roles
                      for role in cmd_perms['roles']):
                return False

        # Check channels
        if 'channels' in cmd_perms:
            if ctx.channel.id not in cmd_perms['channels']:
                return False

    return True
```

### Permission Best Practices
- Layer permissions (global → role → channel → command)
- Use clear rules with descriptive error messages
- Log permission denials with appropriate context
- Handle edge cases (DMs, guild-specific permissions)
- Update permission settings dynamically
- Cache permission data when appropriate
- Document permission requirements for commands

## Task Management

Fish Bot implements a comprehensive task management system for handling background operations, scheduled tasks, and state persistence:

### tasks.py - Background Task Implementation
```python
from discord.ext import tasks

class UnifiedAdvertiseTasks:
    """Tasks for UnifiedAdvertise cog."""
    
    def __init__(self, cog):
        self.cog = cog
        self.start_tasks()  # Start tasks during initialization

    def start_tasks(self):
        """Start all background tasks."""
        if not self.weekly_cleanup.is_running():
            self.weekly_cleanup.start()
        if not self.check_deletions.is_running():
            self.check_deletions.start()

    def stop_tasks(self):
        """Stop all background tasks."""
        self.weekly_cleanup.cancel()
        self.check_deletions.cancel()

    @tasks.loop(hours=168)  # Weekly cleanup
    async def weekly_cleanup(self):
        async with self.cog.task_tracker.task_context("Weekly Cleanup"):
            await self.cog._cleanup_cooldowns()

    @weekly_cleanup.before_loop
    async def before_weekly_cleanup(self):
        """Setup for weekly cleanup task."""
        await self.cog.bot.wait_until_ready()
        await self.cog.wait_until_ready()

    @tasks.loop(minutes=1)
    async def check_deletions(self):
        if self.cog.is_paused:
            return
            
        async with self.cog.task_tracker.task_context("Ad Deletion Check"):
            # Task implementation
```

### cog.py - Main Cog Implementation
```python
class UnifiedAdvertise(BaseCog):
    def __init__(self, bot):
        # ... initialization code ...
        self.tasks = None  # Tasks instance

    async def cog_initialize(self):
        try:
            async with self.task_tracker.task_context("Initialization"):
                await super().cog_initialize()
                # Initialize tasks
                self.tasks = UnifiedAdvertiseTasks(self)
                self.set_ready(True)
        except Exception:
            self._has_errors = True
            raise

    async def cog_unload(self):
        """Clean up tasks on unload."""
        if self.tasks:
            self.tasks.stop_tasks()
        await super().cog_unload()
```

### Task Management Best Practices
- Use tasks.py for consistent task lifecycle management
- Implement proper start/stop patterns
- Track task status with task_tracker
- Handle errors consistently
- Log task progress
- Respect bot and cog state (ready, paused)
- Implement proper resource cleanup
- Use appropriate intervals and reconnect settings

## Discord Interaction Patterns

Fish Bot follows specific patterns for Discord interactions:

### Command Groups Organization
```python
@commands.group(name="feature")
async def feature_group(self, ctx):
    """Main command group for feature."""
    if ctx.invoked_subcommand is None:
        await ctx.send_help(ctx.command)

@feature_group.command(name="list")
async def list_items(self, ctx):
    """List all items."""
    # Implementation

@feature_group.command(name="add")
async def add_item(self, ctx, name: str):
    """Add a new item."""
    # Implementation

@feature_group.group(name="config")
async def config_group(self, ctx):
    """Configure feature settings."""
    if ctx.invoked_subcommand is None:
        await ctx.send_help(ctx.command)

@config_group.command(name="show")
async def show_config(self, ctx):
    """Show current configuration."""
    # Implementation
```

### Embeds and Messages
```python
async def create_status_embed(self) -> discord.Embed:
    """Create status embed with consistent styling."""
    embed = discord.Embed(
        title="Feature Status",
        description="Current status information",
        color=discord.Color.blue()
    )

    # Add status fields
    embed.add_field(
        name="Status",
        value="Online" if not self._has_errors else "Error",
        inline=True
    )

    embed.add_field(
        name="Last Update",
        value=f"<t:{int(self._last_operation_time.timestamp())}:R>",
        inline=True
    )

    # Add cog-specific fields
    await self._add_status_fields(embed)

    # Add footer
    embed.set_footer(
        text=f"v{self.get_setting('version', '1.0')}"
    )

    return embed
```

### Interaction Responses
```python
async def handle_interaction(self, interaction: discord.Interaction) -> None:
    """Handle Discord interaction."""
    async with self.task_tracker.task_context("Interaction") as tracker:
        try:
            tracker.update_status("Processing")

            # Acknowledge interaction
            await interaction.response.defer(ephemeral=True)

            # Process the interaction
            result = await self.process_interaction(interaction)

            # Send response
            await interaction.followup.send(
                content=result,
                ephemeral=True
            )

            tracker.update_status("Complete")
        except Exception as e:
            tracker.update_status("Failed", success=False)
            self.logger.error(f"Interaction error: {e}")

            # Send error response if not already responded
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    content=f"Error: {e}",
                    ephemeral=True
                )
```

### View Management
```python
class FeatureView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.green,
        custom_id="feature:refresh"
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Refresh the display."""
        async with self.cog.task_tracker.task_context("Refresh") as tracker:
            try:
                tracker.update_status("Refreshing")

                # Update the embed
                embed = await self.cog.create_status_embed()

                # Update the message
                await interaction.response.edit_message(
                    embed=embed,
                    view=self
                )

                tracker.update_status("Complete")
            except Exception as e:
                tracker.update_status("Failed", success=False)
                self.cog.logger.error(f"Refresh error: {e}")
                await interaction.response.send_message(
                    content=f"Error: {e}",
                    ephemeral=True
                )
```

### Message Component Handling
```python
@commands.Cog.listener()
async def on_interaction(self, interaction: discord.Interaction):
    """Handle interactions for this cog."""
    if not interaction.data:
        return

    # Check if interaction belongs to this cog
    custom_id = interaction.data.get("custom_id", "")
    if not custom_id.startswith("feature:"):
        return

    async with self.task_tracker.task_context("Component") as tracker:
        try:
            # Extract action from custom_id
            action = custom_id.split(":", 1)[1]

            # Handle different actions
            if action == "action1":
                await self.handle_action1(interaction)
            elif action == "action2":
                await self.handle_action2(interaction)
            else:
                await interaction.response.send_message(
                    content="Unknown action",
                    ephemeral=True
                )
        except Exception as e:
            self.logger.error(f"Component error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    content=f"Error: {e}",
                    ephemeral=True
                )
```

### Discord Interaction Best Practices
- Use consistent command naming and grouping
- Handle interactions with proper error management
- Use embeds with consistent styling
- Implement proper component lifecycle management
- Handle interaction timeouts
- Use ephemeral responses when appropriate
- Provide clear user feedback
- Use proper permission checks for all interactions

## DjangoManager Integration

Fish Bot provides Django integration through the DjangoManager system in BaseCog. This allows cogs to interact with Django models safely in an asynchronous environment.

### Core Concepts

1. **Django Integration Flag**: Cogs that need Django access must set:
```python
def __init__(self, bot):
    self.requires_django = True
    # ...rest of initialization
```

2. **Model Access**: Models are accessed through DjangoManager in `self._django`:
```python
self._models = {
    'ModelName': self._django.get_model('app_name', 'model_name')
}
```

3. **Async Operations**: All database operations should use sync_to_async:
```python
results = await sync_to_async(self._models['ModelName'].objects.filter)(**query)
```

### Implementation Pattern

```python
class MyCog(BaseCog):
    """Cog with Django integration."""
    
    def __init__(self, bot):
        self.requires_django = True
        settings_config = {
            # Settings configuration...
        }
        super().__init__(bot, settings_config)
        self._models = None

    async def cog_initialize(self) -> None:
        """Initialize cog with Django models."""
        try:
            async with self.task_tracker.task_context("Initialization") as tracker:
                await super().cog_initialize()

                # Load Django models
                tracker.update_status("Loading Django models")
                self._models = {
                    'ModelName': self._django.get_model('app_name', 'model_name'),
                }

                if not all(self._models.values()):
                    raise RuntimeError("Failed to load required Django models")

                self.set_ready(True)
                tracker.update_status("Ready")
        except Exception as e:
            self._has_errors = True
            self.logger.error(f"Failed to initialize: {e}", exc_info=True)
            raise

    async def database_operation(self):
        """Example database operation."""
        try:
            # Use sync_to_async for database operations
            results = await sync_to_async(list)(
                self._models['ModelName'].objects.filter(field=value)
            )
            return results
        except Exception as e:
            self.logger.error(f"Database operation failed: {e}")
            raise
```

### Best Practices

1. **Model Access**
- Store model references during initialization
- Validate all models are loaded before continuing
- Use descriptive names in the models dictionary

2. **Async Operations**
- Always use sync_to_async for database operations
- Handle database exceptions properly
- Use proper transaction management

3. **Error Handling**
- Set _has_errors on database failures
- Log errors with context
- Clean up resources on failures

4. **State Management**
- Track database connection state
- Implement proper cleanup in cog_unload
- Handle reconnection scenarios

5. **Validation**
- Validate model existence during initialization
- Check required fields before operations
- Validate foreign key relationships

### Common