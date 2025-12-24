# Standard library imports
import asyncio
import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Union

# Third-party imports
import discord
from discord.ext import commands
from discord.ext.commands import Context

# Local application imports
from thetower.bot.exceptions import ChannelUnauthorized, UserUnauthorized
from thetower.bot.ui.context import SettingsViewContext
from thetower.bot.utils import ConfigManager
from thetower.bot.utils.data_management import DataManager
from thetower.bot.utils.task_tracker import TaskTracker

logger = logging.getLogger(__name__)


@dataclass
class PermissionContext:
    """Context object containing user permissions for efficient checking."""

    user_id: int
    django_groups: List[str]
    discord_roles: List[int]

    def has_any_group(self, groups: List[str]) -> bool:
        """Check if user has any of the required Django groups."""
        return any(group in self.django_groups for group in groups)

    def has_all_groups(self, groups: List[str]) -> bool:
        """Check if user has all of the required Django groups."""
        return all(group in self.django_groups for group in groups)

    def has_discord_role(self, role_id: int) -> bool:
        """Check if user has a specific Discord role."""
        return role_id in self.discord_roles


class BaseCog(commands.Cog):
    """
    Base class for all cogs with common functionality.

    Provides utilities for:
    - Command permission management
    - Settings management
    - Data persistence
    - Standard command interfaces
    - Ready state tracking
    - Task status tracking
    - Logging
    """

    # Make SettingsViewContext available to all cogs without individual imports
    SettingsViewContext = SettingsViewContext

    def __init__(self, bot):
        super().__init__()  # Initialize commands.Cog
        self.bot = bot
        self.config = ConfigManager()
        self._cog_data_directory = None  # Cache for cog data directory
        self._has_errors = False  # Track if the cog has errors
        self._last_operation = None  # Track the last operation time
        self._operation_count = 0  # Track the number of operations
        self._is_paused = False  # Track if the cog is paused

        # Just get the logger, inheriting parent configuration
        self._logger = logging.getLogger(f"thetower.bot.{self.__class__.__name__}")

        # Data management components
        self._data_manager = DataManager()
        self._save_tasks = {}  # Store periodic save tasks

        # Ready state tracking
        self._ready = asyncio.Event()
        self._ready_task = None
        self._ready_timeout = 60  # Default timeout in seconds
        self._is_ready = False

        # Initialize task tracker with the cog's logger
        self._task_tracker = TaskTracker(logger=self._logger, history_size=10)

        # Register for the reconnect event to clear the guild cache
        self.logger.debug(f"Registering listeners for {self.__class__.__name__}")
        self.bot.add_listener(self.on_reconnect, "on_resumed")

        # Manually call _initialize_cog if bot is already ready
        if self.bot.is_ready():
            self.logger.debug("Bot already ready, initializing cog directly")
            self.bot.loop.create_task(self._initialize_cog())
        else:
            # Otherwise register for the ready event
            self.bot.add_listener(self._on_ready, "on_ready")

        self.logger.debug(f"Registered listeners for {self.__class__.__name__}")

        # Register cog settings view if one exists
        self._register_cog_settings_view()

        # Register UI extensions if this cog provides them
        self._register_ui_extensions()

        # Register info extensions if this cog provides them
        self._register_info_extensions()

    def _register_cog_settings_view(self) -> None:
        """Register this cog's settings view with the cog manager if it exists."""
        # Check if this cog has a settings view class
        settings_view_class = getattr(self, "settings_view_class", None)
        if settings_view_class:
            self.bot.cog_manager.register_cog_settings_view(self.cog_name, settings_view_class)
            self.logger.debug(f"Registered settings view for cog '{self.cog_name}'")

    def _register_ui_extensions(self) -> None:
        """Register this cog's UI extensions with the cog manager if they exist."""
        # Check if this cog has UI extensions to register
        if hasattr(self, "register_ui_extensions"):
            try:
                self.register_ui_extensions()
                self.logger.debug(f"Registered UI extensions for cog '{self.cog_name}'")
            except Exception as e:
                self.logger.error(f"Error registering UI extensions for cog '{self.cog_name}': {e}")

    def _register_info_extensions(self) -> None:
        """Register this cog's info extensions with the cog manager if they exist."""
        # Check if this cog has info extensions to register
        if hasattr(self, "register_info_extensions"):
            try:
                self.register_info_extensions()
                self.logger.debug(f"Registered info extensions for cog '{self.cog_name}'")
            except Exception as e:
                self.logger.error(f"Error registering info extensions for cog '{self.cog_name}': {e}")

    @property
    def logger(self) -> logging.Logger:
        """
        Get the cog-specific logger.

        Returns:
            logging.Logger: Logger instance for this cog
        """
        return self._logger

    @property
    def task_tracker(self) -> TaskTracker:
        """
        Get the cog's task tracker.

        This provides direct access to the TaskTracker instance for tracking
        task execution, history, and statistics.

        Returns:
            TaskTracker: The task tracker instance
        """
        return self._task_tracker

    @property
    def is_paused(self) -> bool:
        """Check if the cog is currently paused."""
        return self._is_paused

    # Status command helper for task tracking
    def add_task_status_fields(self, embed: discord.Embed) -> None:
        """
        Add task tracking fields to a status embed.

        Args:
            embed: The discord Embed to add fields to
        """
        # Add active tasks
        active_tasks = self.task_tracker.get_active_tasks()
        if active_tasks:
            active_tasks_text = []
            for name, info in active_tasks.items():
                elapsed = self.format_relative_time(info["start_time"])
                active_tasks_text.append(f"🔄 **{name}**: {info['status']} (started {elapsed} ago)")

            if active_tasks_text:
                embed.add_field(name="Active Processes", value="\n".join(active_tasks_text), inline=False)

        # Add recent task activity
        report = self.task_tracker.get_status_report()
        recent_activity = report.get("recent_activity", {})
        if recent_activity:
            for name, info in recent_activity.items():
                time_ago = self.format_relative_time(info["time"])
                status = "✅ Succeeded" if info["success"] else f"❌ Failed: {info['status']}"
                duration = self.task_tracker.format_task_time(info["execution_time"])

                embed.add_field(name="Last Activity", value=f"**{name}**: {status} ({time_ago} ago, took {duration})", inline=False)
                break  # Just show the first recent activity

        # Add task statistics
        statistics = report.get("statistics", {})
        if statistics:
            stats_text = []
            for name, stats in statistics.items():
                if stats.get("total", 0) > 0:
                    success_rate = (stats.get("success", 0) / stats.get("total", 1)) * 100
                    avg_time = self.task_tracker.format_task_time(stats.get("avg_time", 0))
                    stats_text.append(f"**{name}**: {stats.get('total', 0)} runs, " f"{success_rate:.1f}% success, avg {avg_time}")

            if stats_text:
                embed.add_field(name="Task Statistics", value="\n".join(stats_text[:3]), inline=False)  # Limit to 3 for readability

    async def _on_ready(self):
        """Internal handler for bot ready event."""
        # If there's no ready task, create one
        if not self._ready_task or self._ready_task.done():
            self._ready_task = self.bot.loop.create_task(self._initialize_cog())

    async def _initialize_cog(self):
        """Initialize the cog and set the ready event."""
        self.logger.debug(f"Starting _initialize_cog for {self.__class__.__name__}")
        try:
            # Call the cog-specific initialization if it exists
            if hasattr(self, "cog_initialize") and callable(self.cog_initialize):
                self.logger.debug(f"Calling cog_initialize for {self.__class__.__name__}")
                await self.cog_initialize()
                self.logger.debug(f"Completed cog_initialize for {self.__class__.__name__}")
            else:
                self.logger.debug(f"No cog_initialize method found for {self.__class__.__name__}")

            # Set the ready event to signal the cog is fully initialized
            self._ready.set()
            self.logger.info(f"Cog {self.__class__.__name__} is now ready")
        except Exception as e:
            self.logger.error(f"Error initializing cog {self.__class__.__name__}: {e}", exc_info=True)
            # Don't set ready event on error

    async def cog_initialize(self) -> None:
        """Initialize cog-specific resources after bot is ready.

        This method should be overridden by cogs to perform async initialization.
        """
        # Cogs can override this for custom initialization
        pass

    async def wait_until_ready(self, timeout: Optional[float] = None) -> bool:
        """
        Wait until the cog is ready to use.

        Args:
            timeout: Maximum time to wait in seconds. If None, uses the cog's default timeout.

        Returns:
            bool: True if the cog is ready, False if timed out
        """
        timeout = timeout if timeout is not None else self._ready_timeout
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            self.logger.warning(f"Timed out waiting for cog {self.__class__.__name__} to become ready")
            return False

    @property
    def is_ready(self) -> bool:
        """Check if the cog is ready for use."""
        return self._is_ready and self._ready.is_set()

    def set_ready(self, ready: bool = True) -> None:
        """Set the cog's ready state."""
        self._is_ready = ready
        if ready:
            self._ready.set()
        else:
            self._ready.clear()

    async def on_reconnect(self):
        """Called when the bot reconnects to Discord."""
        self.logger.debug(f"Reconnected for {self.__class__.__name__}")

    @property
    def cog_name(self) -> str:
        """Get the standardized cog name in snake_case format.

        This ensures consistency between how cogs are referenced in bot_owner_settings
        (which uses filenames like 'battle_conditions') and guild settings.

        Returns:
            str: The cog name in snake_case format (e.g., 'battle_conditions')
        """
        import re

        # Convert PascalCase to snake_case
        class_name = self.__class__.__name__
        snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", class_name)
        return snake.lower()

    @property
    def data_directory(self) -> Path:
        """Get and cache the cog's data directory."""
        if self._cog_data_directory is None:
            self._cog_data_directory = self.config.get_cog_data_directory(self.cog_name)
        return self._cog_data_directory

    def get_command_name(self, ctx: Context) -> str:
        """Get the full command name including parent commands."""
        cmd = ctx.command
        parent = cmd.parent
        if parent is None:
            return cmd.name
        return f"{parent.name} {cmd.name}"

    async def cog_check(self, ctx: Context) -> bool:
        """Automatically check permissions for all commands in the cog."""
        if not ctx.command:
            return False

        # Skip permission checks for help command
        if ctx.command.name == "help":
            return True

        # Check if this cog is enabled for the current guild
        if ctx.guild:
            cog_name = self.__class__.__name__.replace("Cog", "").lower()
            # Convert CamelCase to snake_case for cog names like "TourneyRolesCog" -> "tourney_roles"
            import re

            cog_name = re.sub(r"(?<!^)(?=[A-Z])", "_", cog_name).lower()

            is_bot_owner = await ctx.bot.is_owner(ctx.author)

            # Check if cog is enabled for this guild
            if not ctx.bot.cog_manager.can_guild_use_cog(cog_name, ctx.guild.id, is_bot_owner):
                # Don't send a message here - just silently fail
                # The cog simply won't respond if not enabled for the guild
                return False

        # Get the full command name for subcommands
        command_name = self.get_command_name(ctx)

        # Use the bot's permission manager to check permissions
        try:
            return await self.bot.permission_manager.check_command_permissions(ctx, command_name)
        except (UserUnauthorized, ChannelUnauthorized):
            # Let these exceptions propagate for the error handler
            raise

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check permissions for slash commands - always includes cog authorization."""
        # Step 1: Always check cog authorization first
        if not await self._check_cog_authorization(interaction):
            return False

        # Step 2: Allow cogs to add additional checks
        return await self._check_additional_interaction_permissions(interaction)

    async def _check_cog_authorization(self, interaction: discord.Interaction) -> bool:
        """Check if this cog is authorized for the guild (not overridable)."""
        if interaction.guild:
            is_bot_owner = await self.bot.is_owner(interaction.user)
            if not self.bot.cog_manager.can_guild_use_cog(self.cog_name, interaction.guild.id, is_bot_owner):
                # Silently fail - command won't respond if cog not authorized
                return False
        return True

    async def _check_additional_interaction_permissions(self, interaction: discord.Interaction) -> bool:
        """Additional permission checks that cogs can override."""
        if not interaction.command:
            return True

        # Create a mock context for permission manager
        # Include parent attribute to match expected command structure
        ctx = SimpleNamespace(
            command=SimpleNamespace(name=interaction.command.name, parent=getattr(interaction.command, "parent", None)),
            bot=interaction.client,
            guild=interaction.guild,
            channel=interaction.channel,
            author=interaction.user,
            message=SimpleNamespace(channel_mentions=[]),
        )

        try:
            await self.bot.permission_manager.check_command_permissions(ctx)
            return True
        except (UserUnauthorized, ChannelUnauthorized) as e:
            # Send error message as ephemeral response
            if isinstance(e, UserUnauthorized):
                await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            elif isinstance(e, ChannelUnauthorized):
                await interaction.response.send_message("❌ This command cannot be used in this channel.", ephemeral=True)
            return False

    # Cog settings methods

    def _extract_guild_id(self, guild_id: int = None, ctx: Context = None, interaction: discord.Interaction = None) -> int:
        """Extract guild ID from various sources.

        Priority order:
        1. Explicit guild_id parameter
        2. Context object (ctx.guild.id)
        3. Interaction object (interaction.guild_id)
        4. Raise error if none available

        Args:
            guild_id: Explicit guild ID
            ctx: Command context (optional)
            interaction: Discord interaction (optional)

        Returns:
            The guild ID

        Raises:
            ValueError: If guild_id cannot be determined
        """
        if guild_id is not None:
            return guild_id

        if ctx is not None and ctx.guild is not None:
            return ctx.guild.id

        if interaction is not None and interaction.guild is not None:
            return interaction.guild_id

        # Try to inspect the call stack for ctx or interaction
        import inspect

        frame = inspect.currentframe()
        try:
            # Walk up the call stack looking for ctx or interaction
            for _ in range(10):  # Limit depth to avoid infinite loops
                frame = frame.f_back
                if frame is None:
                    break

                local_vars = frame.f_locals

                # Check for ctx in local variables
                if "ctx" in local_vars:
                    ctx_obj = local_vars["ctx"]
                    if isinstance(ctx_obj, Context) and ctx_obj.guild is not None:
                        return ctx_obj.guild.id

                # Check for interaction in local variables
                if "interaction" in local_vars:
                    inter_obj = local_vars["interaction"]
                    if isinstance(inter_obj, discord.Interaction) and inter_obj.guild is not None:
                        return inter_obj.guild_id

                # Check for self.ctx (some cogs might store it)
                if "self" in local_vars:
                    self_obj = local_vars["self"]
                    if hasattr(self_obj, "ctx") and isinstance(self_obj.ctx, Context):
                        if self_obj.ctx.guild is not None:
                            return self_obj.ctx.guild.id
        finally:
            del frame

        raise ValueError(
            "guild_id is required but could not be determined automatically. "
            "Please pass guild_id=ctx.guild.id explicitly, or ensure this is called "
            "within a command context."
        )

    def ensure_settings_initialized(
        self, guild_id: int = None, default_settings: Dict[str, Any] = None, ctx: Context = None, interaction: discord.Interaction = None
    ) -> None:
        """Ensure settings are initialized for a specific guild.

        Args:
            guild_id: The guild ID to initialize settings for (auto-detected from ctx if not provided)
            default_settings: Dictionary of default setting values (optional)
            ctx: Command context (optional, used for auto-detecting guild_id)
            interaction: Discord interaction (optional, used for auto-detecting guild_id)

        Example:
            # Automatic guild detection:
            self.ensure_settings_initialized(ctx=ctx, default_settings={
                'notification_hour': 0,
                'enabled_leagues': ['Legend', 'Champion']
            })

            # Or explicit:
            self.ensure_settings_initialized(guild_id=ctx.guild.id, default_settings={...})
        """
        if default_settings is None:
            return

        guild_id = self._extract_guild_id(guild_id, ctx, interaction)

        for key, value in default_settings.items():
            if not self.has_setting(key, guild_id=guild_id, ctx=ctx, interaction=interaction):
                self.set_setting(key, value, guild_id=guild_id, ctx=ctx, interaction=interaction)

    def get_setting(self, key: str, default: Any = None, guild_id: int = None, ctx: Context = None, interaction: discord.Interaction = None) -> Any:
        """Get a cog-specific setting.

        Args:
            key: Setting name
            default: Default value if setting doesn't exist
            guild_id: Guild ID (auto-detected from ctx/interaction if not provided)
            ctx: Command context (optional, used for auto-detecting guild_id)
            interaction: Discord interaction (optional, used for auto-detecting guild_id)

        Returns:
            The setting value or default

        Example:
            # Automatic - just pass ctx:
            value = self.get_setting('timeout_seconds', 60, ctx=ctx)

            # Or explicit:
            value = self.get_setting('timeout_seconds', 60, guild_id=ctx.guild.id)
        """
        guild_id = self._extract_guild_id(guild_id, ctx, interaction)
        return self.config.get_cog_setting(self.cog_name, key, default, guild_id)

    def set_setting(self, key: str, value: Any, guild_id: int = None, ctx: Context = None, interaction: discord.Interaction = None) -> None:
        """Save a cog-specific setting.

        Args:
            key: Setting name
            value: Setting value
            guild_id: Guild ID (auto-detected from ctx/interaction if not provided)
            ctx: Command context (optional, used for auto-detecting guild_id)
            interaction: Discord interaction (optional, used for auto-detecting guild_id)

        Example:
            # Automatic - just pass ctx:
            self.set_setting('timeout_seconds', 120, ctx=ctx)

            # Or explicit:
            self.set_setting('timeout_seconds', 120, guild_id=ctx.guild.id)
        """
        guild_id = self._extract_guild_id(guild_id, ctx, interaction)
        self.config.set_cog_setting(self.cog_name, key, value, guild_id)

    def update_settings(self, settings: Dict[str, Any], guild_id: int = None, ctx: Context = None, interaction: discord.Interaction = None) -> None:
        """Update multiple cog settings at once.

        Args:
            settings: Dictionary of settings to update
            guild_id: Guild ID (auto-detected from ctx/interaction if not provided)
            ctx: Command context (optional, used for auto-detecting guild_id)
            interaction: Discord interaction (optional, used for auto-detecting guild_id)

        Example:
            # Automatic - just pass ctx:
            self.update_settings({
                'timeout_seconds': 120,
                'max_retries': 3,
                'enabled': True
            }, ctx=ctx)
        """
        guild_id = self._extract_guild_id(guild_id, ctx, interaction)
        self.config.update_cog_settings(self.cog_name, settings, guild_id)

    def remove_setting(self, key: str, guild_id: int = None, ctx: Context = None, interaction: discord.Interaction = None) -> bool:
        """Remove a cog-specific setting.

        Args:
            key: Setting name to remove
            guild_id: Guild ID (auto-detected from ctx/interaction if not provided)
            ctx: Command context (optional, used for auto-detecting guild_id)
            interaction: Discord interaction (optional, used for auto-detecting guild_id)

        Returns:
            True if setting was removed, False if it didn't exist

        Example:
            self.remove_setting('legacy_option', ctx=ctx)
        """
        guild_id = self._extract_guild_id(guild_id, ctx, interaction)
        return self.config.remove_cog_setting(self.cog_name, key, guild_id)

    def has_setting(self, key: str, guild_id: int = None, ctx: Context = None, interaction: discord.Interaction = None) -> bool:
        """Check if a cog-specific setting exists.

        Args:
            key: Setting name to check
            guild_id: Guild ID (auto-detected from ctx/interaction if not provided)
            ctx: Command context (optional, used for auto-detecting guild_id)
            interaction: Discord interaction (optional, used for auto-detecting guild_id)

        Returns:
            True if setting exists, False otherwise

        Example:
            if self.has_setting('feature_enabled', ctx=ctx):
                # use the feature
        """
        guild_id = self._extract_guild_id(guild_id, ctx, interaction)
        return self.config.has_cog_setting(self.cog_name, key, guild_id)

    def get_global_setting(self, key: str, default: Any = None) -> Any:
        """Get a global cog-specific setting (bot owner level).

        Args:
            key: Setting name
            default: Default value if setting doesn't exist

        Returns:
            The setting value or default
        """
        return self.config.get_global_cog_setting(self.cog_name, key, default)

    def set_global_setting(self, key: str, value: Any) -> None:
        """Save a global cog-specific setting (bot owner level).

        Args:
            key: Setting name
            value: Setting value
        """
        self.config.set_global_cog_setting(self.cog_name, key, value)

    def update_global_settings(self, settings: Dict[str, Any]) -> None:
        """Update multiple global cog settings at once.

        Args:
            settings: Dictionary of settings to update
        """
        self.config.update_global_cog_settings(self.cog_name, settings)

    def remove_global_setting(self, key: str) -> bool:
        """Remove a global cog-specific setting.

        Args:
            key: Setting name to remove

        Returns:
            True if setting was removed, False if it didn't exist
        """
        return self.config.remove_global_cog_setting(self.cog_name, key)

    def has_global_setting(self, key: str) -> bool:
        """Check if a global cog-specific setting exists.

        Args:
            key: Setting name to check

        Returns:
            True if setting exists, False otherwise
        """
        return self.config.has_global_cog_setting(self.cog_name, key)

    def get_all_global_settings(self) -> Dict[str, Any]:
        """Get all global settings for this cog.

        Returns:
            Dictionary of all global cog settings
        """
        return self.config.get_all_global_cog_settings(self.cog_name)

    # ----- Data Management Methods -----

    def mark_data_modified(self):
        """Mark the cog's data as modified, needing to be saved."""
        self._data_manager.mark_modified()

    def is_data_modified(self) -> bool:
        """Check if the cog's data has been modified."""
        return self._data_manager.is_modified()

    async def save_data_if_modified(self, data: Any, file_path: Union[str, Path], force: bool = False) -> bool:
        """
        Save data to file if it's been modified or if forced.

        Args:
            data: The data to save (must be JSON/pickle serializable)
            file_path: Path where the data should be saved
            force: Whether to save even if not modified

        Returns:
            bool: True if save was successful, False otherwise
        """
        return await self._data_manager.save_if_modified(data, file_path, force)

    async def load_data(self, file_path: Union[str, Path], default: Any = None) -> Any:
        """
        Load data from a file with fallback to default if file doesn't exist.

        Args:
            file_path: Path to the data file
            default: Default value to return if file doesn't exist

        Returns:
            The loaded data or default value
        """
        return await self._data_manager.load_data(file_path, default)

    async def create_periodic_save_task(self, data: Any, file_path: Union[str, Path], save_interval: int) -> asyncio.Task:
        """
        Create a task that periodically saves data.

        Args:
            data: The data to save (must be serializable)
            file_path: Path where the data should be saved
            save_interval: How often to save (in seconds)

        Returns:
            asyncio.Task: The created task
        """

        async def periodic_save():
            await self.bot.wait_until_ready()
            while not self.bot.is_closed():
                await asyncio.sleep(save_interval)
                await self.save_data_if_modified(data, file_path)

        # Cancel any existing task for this file
        file_key = str(file_path)
        if file_key in self._save_tasks and not self._save_tasks[file_key].done():
            self._save_tasks[file_key].cancel()

        # Create and store the new task
        task = self.bot.loop.create_task(periodic_save())
        self._save_tasks[file_key] = task
        return task

    def cancel_save_tasks(self):
        """Cancel all periodic save tasks."""
        for task in self._save_tasks.values():
            if not task.done():
                task.cancel()
        self._save_tasks.clear()

    # ----- Utility Methods -----

    def format_time_value(self, seconds: int) -> str:
        """Format seconds into a human-readable string.

        Args:
            seconds: Number of seconds

        Returns:
            str: Formatted string like "1h 30m 45s (5445 seconds)"
        """
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs}s ({seconds} seconds)"

    def format_relative_time(self, timestamp) -> str:
        """Format a timestamp as a relative time string.

        Args:
            timestamp: Datetime object

        Returns:
            str: Human readable relative time (e.g., "5 minutes ago")
        """
        # Handle None values gracefully
        if timestamp is None:
            return "unknown time"

        now = datetime.datetime.now()

        # Handle timezone-aware timestamps
        if hasattr(timestamp, "tzinfo") and timestamp.tzinfo:
            if not now.tzinfo:
                now = now.replace(tzinfo=datetime.timezone.utc)

        diff = now - timestamp
        seconds = diff.total_seconds()

        if seconds < 60:
            return f"{int(seconds)} seconds ago"
        elif seconds < 3600:
            return f"{int(seconds // 60)} minutes ago"
        elif seconds < 86400:
            return f"{int(seconds // 3600)} hours ago"
        else:
            return f"{int(seconds // 86400)} days ago"

    async def cog_unload(self):
        """Clean up resources when cog is unloaded."""
        # Cancel periodic save tasks
        self.cancel_save_tasks()

        # Cancel the ready task if it exists and is still running
        if self._ready_task and not self._ready_task.done():
            self._ready_task.cancel()

        # Clear the ready event
        self._ready.clear()

        # Clean up UI extensions registered by this cog
        self.bot.cog_manager.unregister_ui_extensions_from_source(self.__class__.__name__)

        # Clean up info extensions registered by this cog
        self.bot.cog_manager.unregister_info_extensions_from_source(self.__class__.__name__)

        # Force save any modified data
        if self.is_data_modified():
            self.logger.warning(f"Cog {self.__class__.__name__} has unsaved data on unload")

        # Call parent implementation if it exists
        if hasattr(super(), "cog_unload"):
            await super().cog_unload()

    # ====================
    # Permission System Methods
    # ====================

    async def get_user_permissions(self, user: discord.User) -> PermissionContext:
        """
        Get permission context for a user by fetching from Django.

        This method provides a centralized way to get user permissions that all cogs
        can use. It fetches fresh permissions each time to ensure immediate
        propagation of permission changes from Django admin.

        Args:
            user: The Discord user to get permissions for

        Returns:
            PermissionContext: Context containing user's Django groups and Discord roles
        """
        # Fetch fresh permissions each time for immediate propagation
        return await self._fetch_user_permissions(user)

    async def check_user_groups(self, user: discord.User, required_groups: List[str], require_all: bool = False) -> bool:
        """
        Check if a user has specific Django groups.

        Args:
            user: The Discord user to check
            required_groups: List of Django group names required
            require_all: If True, user must have ALL groups; if False, user must have ANY group

        Returns:
            bool: True if user has the required group(s), False otherwise
        """
        permissions = await self.get_user_permissions(user)

        if require_all:
            return permissions.has_all_groups(required_groups)
        else:
            return permissions.has_any_group(required_groups)

    async def _fetch_user_permissions(self, user: discord.User) -> PermissionContext:
        """
        Fetch user permissions from Django database.

        Args:
            user: The Discord user to fetch permissions for

        Returns:
            PermissionContext: Fresh permission context for the user
        """
        from asgiref.sync import sync_to_async

        @sync_to_async
        def get_django_user_groups():
            try:
                from thetower.backend.sus.models import KnownPlayer

                # Get the KnownPlayer linked to this Discord user by Discord ID
                known_player = KnownPlayer.objects.filter(discord_id=str(user.id)).select_related("django_user").first()
                if not known_player:
                    return []

                # Check if the KnownPlayer has a django_user linked
                django_user = known_player.django_user
                if not django_user:
                    return []

                groups = list(django_user.groups.values_list("name", flat=True))
                return groups
            except Exception:
                return []

        # Get Django groups
        django_groups = await get_django_user_groups()

        # Get Discord roles (if user is in a guild context, we'll need to handle this differently)
        # For now, just get basic user info
        discord_roles = []

        return PermissionContext(user_id=user.id, django_groups=django_groups, discord_roles=discord_roles)

    # ====================
    # Slash Command Permission Helpers
    # ====================

    async def check_slash_action_permission(self, interaction: discord.Interaction, action_name: str, *, default_to_owner: bool = True) -> bool:
        """Check if a user has permission to use a specific slash command action.

        Args:
            interaction: The Discord interaction
            action_name: The name of the action (e.g., "generate", "resend")
            default_to_owner: If True, bot/guild owners can always use the action

        Returns:
            True if the user has permission, False otherwise
        """
        guild_id = interaction.guild.id
        user_id = interaction.user.id

        # Bot owner and guild owner bypass if default_to_owner is True
        if default_to_owner:
            is_bot_owner = await self.bot.is_owner(interaction.user)
            is_guild_owner = interaction.guild.owner_id == user_id

            if is_bot_owner or is_guild_owner:
                return True

        # Get permissions config for this action
        config_key = f"slash_permissions.{action_name}"
        permissions = self.get_setting(config_key, default={}, guild_id=guild_id)

        # If no specific permissions set, default based on default_to_owner
        if not permissions:
            return default_to_owner  # Already checked owner above

        # Check allowed users
        allowed_users = permissions.get("allowed_users", [])
        if user_id in allowed_users:
            return True

        # Check allowed roles
        allowed_roles = permissions.get("allowed_roles", [])
        user_role_ids = [role.id for role in interaction.user.roles]
        if any(role_id in allowed_roles for role_id in user_role_ids):
            return True

        return False

    async def check_slash_channel_permission(self, interaction: discord.Interaction, action_name: str) -> bool:
        """Check if a slash command action can be used in the current channel.

        Args:
            interaction: The Discord interaction
            action_name: The name of the action (e.g., "generate")

        Returns:
            True if the action can be used in this channel, False otherwise
        """
        guild_id = interaction.guild.id
        channel_id = interaction.channel.id

        # Get channel permissions config for this action
        config_key = f"slash_permissions.{action_name}"
        permissions = self.get_setting(config_key, default={}, guild_id=guild_id)

        # If no channel restrictions, allow all channels
        allowed_channels = permissions.get("allowed_channels", [])
        if not allowed_channels:
            return True

        # Check if current channel is in allowed list
        return channel_id in allowed_channels

    def get_slash_action_target_channel(self, guild_id: int, action_name: str) -> Optional[int]:
        """Get the pre-configured target channel for a slash command action.

        This is used for actions that post to a specific channel (like scheduled reposts).

        Args:
            guild_id: The guild ID
            action_name: The name of the action (e.g., "resend")

        Returns:
            Channel ID if configured, None otherwise
        """
        config_key = f"slash_permissions.{action_name}"
        permissions = self.get_setting(config_key, default={}, guild_id=guild_id)
        return permissions.get("target_channel")

    def set_slash_action_permission(
        self,
        guild_id: int,
        action_name: str,
        *,
        allowed_users: Optional[list] = None,
        allowed_roles: Optional[list] = None,
        allowed_channels: Optional[list] = None,
        target_channel: Optional[int] = None,
    ) -> None:
        """Set permissions for a slash command action.

        Args:
            guild_id: The guild ID
            action_name: The name of the action
            allowed_users: List of user IDs that can use this action
            allowed_roles: List of role IDs that can use this action
            allowed_channels: List of channel IDs where action can be used
            target_channel: Pre-configured target channel for this action
        """
        config_key = f"slash_permissions.{action_name}"
        permissions = {}

        if allowed_users is not None:
            permissions["allowed_users"] = allowed_users
        if allowed_roles is not None:
            permissions["allowed_roles"] = allowed_roles
        if allowed_channels is not None:
            permissions["allowed_channels"] = allowed_channels
        if target_channel is not None:
            permissions["target_channel"] = target_channel

        self.set_setting(config_key, permissions, guild_id=guild_id)
