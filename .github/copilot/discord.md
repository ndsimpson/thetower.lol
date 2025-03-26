# Discord Bot Development Patterns

## Cog Structure
### Basic Structure
```python
from discord.ext import commands
from discord import app_commands
import discord
from typing import Optional, Dict, Any
import datetime

from fish_bot.basecog import BaseCog
from fish_bot.exceptions import UserUnauthorized, ChannelUnauthorized

class MyCog(BaseCog,
           name="My Cog",
           description="Example cog demonstrating standard patterns"):
    """Example cog demonstrating standard command patterns and structure.

    Shows recommended implementation of settings, status tracking,
    and command organization using command groups.
    """

    # ====================
    # Initialization
    # ====================

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing MyCog")

        # Initialize core instance variables with descriptions
        self._active_process = None
        self._process_start_time = None
        self._operation_count = 0
        self._last_operation = None

        # Define settings with descriptions
        settings_config = {
            # Core Settings
            "max_items": (10, "Maximum items to display"),
            "update_interval": (300, "Update interval in seconds"),

            # Feature Settings
            "feature_enabled": (True, "Enable special feature"),
            "cache_lifetime": (3600, "How long to keep cache (seconds)"),

            # Processing Settings
            "batch_size": (50, "Number of items to process in each batch"),
            "process_delay": (5, "Seconds between processing batches")
        }

        # Initialize settings
        for name, (value, description) in settings_config.items():
            if not self.has_setting(name):
                self.set_setting(name, value, description)

        # Load settings into instance variables
        self._load_settings()

    async def cog_initialize(self) -> None:
        """Initialize the cog."""
        self.logger.info("Initializing cog")
        try:
            self.logger.info("Starting MyCog initialization")

            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                await super().cog_initialize()

                # 1. Verify settings
                self.logger.debug("Loading settings")
                tracker.update_status("Verifying settings")
                self._load_settings()

                # 2. Create inherited commands
                self.create_pause_commands(self.mycog_group)

                # 3. Load any saved data
                self.logger.debug("Loading saved data")
                tracker.update_status("Loading data")
                if await self.load_data():
                    self.logger.info("Loaded saved data")
                else:
                    self.logger.info("No saved data found, using defaults")

                # 4. Start any background tasks
                self.logger.debug("Starting background tasks")
                tracker.update_status("Starting tasks")

                # 5. Mark as ready and complete initialization
                self.set_ready(True)
                self.logger.info("MyCog initialization complete")

        except Exception as e:
            self.logger.error(f"Error during MyCog initialization: {e}", exc_info=True)
            self._has_errors = True
            raise

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded."""
        try:
            # Cancel any scheduled tasks
            if hasattr(self, 'background_task'):
                self.background_task.cancel()

            # Force save any modified data
            if self.is_data_modified():
                await self.save_data()

            # Clear tasks by invalidating the tracker
            if hasattr(self, 'task_tracker'):
                self.task_tracker.invalidate()

            # Call parent implementation
            await super().cog_unload()

            self.logger.info("MyCog unloaded successfully")

        except Exception as e:
            self.logger.error(f"Error during cog unload: {e}", exc_info=True)

    # ====================
    # Commands
    # ====================

    @commands.group(
        name="mycog",
        aliases=["mc"],
        description="My cog management commands"
    )
    async def mycog_group(self, ctx):
        """My cog management commands."""
    # No permission decorator necessary as permissions are handled via basecog inheritance
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @mycog_group.command(
        name="status",
        description="Display operational status and information"
    )
    async def status_command(self, ctx: commands.Context) -> None:
        """Display operational status and information."""
    # No permission decorator necessary as permissions are inherited from group
        # Determine status and color
        if not self.is_ready:
            status_emoji = "⏳"
            status_text = "Initializing"
            embed_color = discord.Color.orange()
        elif self._has_errors:
            status_emoji = "❌"
            status_text = "Error"
            embed_color = discord.Color.red()
        else:
            status_emoji = "✅"
            status_text = "Operational"
            embed_color = discord.Color.blue()

        embed = discord.Embed(
            title="System Status",
            description="Current operational state and statistics",
            color=embed_color
        )

        status_value = [f"{status_emoji} Status: {status_text}"]
        if self._last_operation:
            time_since = self.format_relative_time(self._last_operation)
            status_value.append(f"🕒 Last Operation: {time_since}")

        embed.add_field(name="System State", value="\n".join(status_value), inline=False)

        settings = self.get_all_settings()
        settings_text = []
        for name, value in settings.items():
            settings_text.append(f"**{name}:** {value}")

        embed.add_field(name="Current Settings", value="\n".join(settings_text), inline=False)

        if self._operation_count:
            embed.add_field(
                name="Statistics",
                value=f"Operations completed: {self._operation_count}",
                inline=False
            )

        await ctx.send(embed=embed)

    @mycog_group.command(
        name="settings",
        description="Manage cog settings"
    )
    @app_commands.describe(
        setting_name="Setting to change",
        value="New value for the setting"
    )
    async def settings_command(self, ctx: commands.Context, setting_name: str, value: str) -> None:
        """Change a cog setting."""
        try:
            if not self.has_setting(setting_name):
                valid_settings = list(self.get_all_settings().keys())
                return await ctx.send(f"Invalid setting. Valid options: {', '.join(valid_settings)}")

            current_value = self.get_setting(setting_name)
            if isinstance(current_value, bool):
                value = value.lower() in ('true', '1', 'yes')
            elif isinstance(current_value, int):
                value = int(value)
            elif isinstance(current_value, float):
                value = float(value)

            self.set_setting(setting_name, value)

            if hasattr(self, setting_name):
                setattr(self, setting_name, value)

            await ctx.send(f"✅ Set {setting_name} to {value}")
            self.logger.info(f"Setting changed: {setting_name} = {value}")

        except ValueError:
            await ctx.send(f"Invalid value format for {setting_name}")
        except Exception as e:
            self.logger.error(f"Error changing setting: {e}")
            await ctx.send("An error occurred changing the setting")

    # ====================
    # Listeners
    # ====================

    # Add any event listeners here

    # ====================
    # Error Handling
    # ====================

    # Add error handlers here

    # ====================
    # Helper Methods
    # ====================

    def _load_settings(self) -> None:
        """Load settings into instance variables."""
        self.max_items = self.get_setting("max_items")
        self.update_interval = self.get_setting("update_interval")
        self.feature_enabled = self.get_setting("feature_enabled")
        self.cache_lifetime = self.get_setting("cache_lifetime")
        self.batch_size = self.get_setting("batch_size")
        self.process_delay = self.get_setting("process_delay")

# ====================
# Cog Setup
# ====================

async def setup(bot):
    await bot.add_cog(MyCog(bot))
```

## Command Patterns
### Standard Commands
- settings: Display configuration
- status: Show operational state.  Info command should be migrated to status.
- toggle: Boolean settings
- pause: Operational state - implemented via BaseCog
- (optional) refresh: Refreshes/reloads cache data.  Reload is an alias of refresh.

### Pause Command Pattern
The BaseCog provides standardized pause functionality that can be added to any cog. Here's how to implement it:

```python
class MyCog(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)

    async def my_operation(self):
        # Check pause state before operations
        if self.is_paused:
            self.logger.debug("Operation skipped - cog is paused")
            return

        # Operation code here
        ...
```

This adds three commands to your group:
- `pause`: Pauses cog operations
- `resume`: Resumes cog operations
- `toggle`: Toggles pause state

The pause state is tracked via `self.is_paused` and automatically handles:
- State management
- Status updates
- Logging
- User feedback
- Both prefix and slash command support

### Status Integration
The pause state is automatically integrated with the status command:
```python
@mycog_group.command(name="status")
async def status_command(self, ctx):
    embed = await self.create_standard_status_embed()

    # Pause state is included in status
    if self.is_paused:
        embed.add_field(
            name="Operation State",
            value="⏸️ Operations Paused",
            inline=False
        )

    await ctx.send(embed=embed)
```

## Status Management
- Track initialization state
- Monitor dependencies
- Log operational status
- Handle errors gracefully

## Settings Management
- Use BaseCog settings system
- Document default values
- Group by category
- Support runtime changes

## Command Permissions
### Permission Structure
- Permissions are managed through BaseCog and PermissionManager
- Each command can have channel and user-level permissions
- Commands can be public or private in specific channels
- Wildcard permissions supported with `*`

### Configuration Format
```json
{
  "command_permissions": {
    "commands": {
      "command_name": {
        "channels": {
          "channel_id": {
            "public": true,
            "authorized_users": ["user_id1", "user_id2"]
                              }
                }
            }
        }
    }
}
```

### Permission Management
```python
# Add channel permission
!perm add_channel command_name #channel public

# Add authorized user
!perm add_user command_name #channel @user

# Remove channel permission
!perm remove_channel command_name #channel

# Set channel to public/private
!perm set_public command_name #channel true/false
```

### Implementation
- Inherit from BaseCog to get automatic permission checking
- No manual permission decorators needed
- Permissions checked through cog_check()
- Throws UserUnauthorized or ChannelUnauthorized on denial

### Examples
```python
class MyCog(BaseCog):
    @commands.command()
    async def my_command(self, ctx):
        # Permissions automatically checked
        await ctx.send("Command executed!")
```
