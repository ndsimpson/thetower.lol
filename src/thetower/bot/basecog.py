# Standard library imports
import asyncio
import datetime
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    from thetower.backend.sus.models import KnownPlayer, LinkedAccount

# Third-party imports
import discord
from discord.ext import commands
from discord.ext.commands import Context

# Local application imports
from thetower.bot.exceptions import ChannelUnauthorized, UserUnauthorized
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
    is_bot_owner: bool = False

    def has_any_group(self, groups: List[str]) -> bool:
        """Check if user has any of the required Django groups."""
        return any(group in self.django_groups for group in groups)

    def has_all_groups(self, groups: List[str]) -> bool:
        """Check if user has all of the required Django groups."""
        return all(group in self.django_groups for group in groups)

    def has_django_group(self, group: str) -> bool:
        """Check if user has a specific Django group."""
        return group in self.django_groups

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

    Cogs can declare default settings as class attributes:
    - global_settings: Dict of bot-wide settings
    - guild_settings: Dict of per-guild settings
    """

    # Default settings that cogs can override
    global_settings = {}
    guild_settings = {}

    def __init__(self, bot):
        super().__init__()  # Initialize commands.Cog
        self.bot = bot
        self.config = ConfigManager()
        self._cog_data_directory = None  # Cache for cog data directory
        self._has_errors = False  # Track if the cog has errors
        self._last_operation = None  # Track the last operation time
        self._operation_count = 0  # Track the number of operations

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

        # Initialize settings from class attributes
        self._initialize_settings_from_class()

        # Automatically register cog on bot for easy access
        setattr(self.bot, self.cog_name, self)
        self.logger.debug(f"Registered cog as bot.{self.cog_name}")

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
        return self.get_setting("paused", False)

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
        """Standard initialization with logging, task tracking, and error handling."""
        cog_name = self.__class__.__name__
        self.logger.info(f"Initializing {cog_name}")

        try:
            async with self.task_tracker.task_context("Initialization") as tracker:
                # Call cog-specific initialization if it exists
                if hasattr(self, "_initialize_cog_specific"):
                    await self._initialize_cog_specific(tracker)

        except Exception as e:
            self._has_errors = True
            self.logger.error(f"Failed to initialize {cog_name}: {e}", exc_info=True)
            raise
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

    def _initialize_settings_from_class(self) -> None:
        """Initialize settings from class attributes, allowing cogs to override defaults."""
        # Get settings from class, falling back to empty dicts
        self.global_settings = getattr(self.__class__, "global_settings", {}).copy()
        self.guild_settings = getattr(self.__class__, "guild_settings", {}).copy()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check permissions for slash commands - always includes cog authorization."""
        try:
            # Step 1: Always check cog authorization first
            if not await self._check_cog_authorization(interaction):
                return False

            # Step 2: Allow cogs to add additional checks
            return await self._check_additional_interaction_permissions(interaction)
        except Exception as e:
            # Re-raise custom exceptions as CheckFailure so discord.py handles them properly
            from thetower.bot.exceptions import CogNotEnabled

            if isinstance(e, CogNotEnabled):
                raise discord.app_commands.CheckFailure(str(e)) from e
            raise

    async def _check_cog_authorization(self, interaction: discord.Interaction) -> bool:
        """Check if this cog is authorized for the guild (not overridable)."""
        if interaction.guild:
            is_bot_owner = await self.bot.is_owner(interaction.user)
            if not self.bot.cog_manager.can_guild_use_cog(self.cog_name, interaction.guild.id, is_bot_owner):
                # Import here to avoid circular imports
                from thetower.bot.exceptions import CogNotEnabled

                raise CogNotEnabled(self.cog_name, interaction.guild.id)
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
                await interaction.response.send_message(
                    "❌ You don't have permission to use this command.\n" "💡 Contact your server administrator if you believe this is incorrect.",
                    ephemeral=True,
                )
            elif isinstance(e, ChannelUnauthorized):
                await interaction.response.send_message(
                    "❌ This command cannot be used in this channel.\n"
                    "💡 Please use this command in an authorized channel, or contact your server administrator to configure channel permissions via `/settings`.",
                    ephemeral=True,
                )
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

    def cancel_save_tasks(self):
        """Cancel all periodic save tasks."""
        for task in self._save_tasks.values():
            if not task.done():
                task.cancel()
        self._save_tasks.clear()

    # ----- Utility Methods -----

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

    async def cog_load(self):
        """Called when the cog is loaded. Default implementation provides logging."""
        self.logger.info(f"{self.__class__.__name__} cog loaded")

    async def cog_unload(self):
        """Clean up resources when cog is unloaded."""
        self.logger.info(f"{self.__class__.__name__} cog unloaded")

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

    async def get_user_django_groups(self, user: discord.User) -> List[str]:
        """
        Get Django groups for a Discord user.

        This is a centralized method for fetching Django user groups that can be reused
        across all cogs to avoid code duplication.

        Args:
            user: The Discord user to get groups for

        Returns:
            List of Django group names the user belongs to
        """
        from asgiref.sync import sync_to_async

        @sync_to_async
        def get_django_user_groups():
            try:
                from thetower.backend.sus.models import LinkedAccount

                # Get the active LinkedAccount for this Discord user
                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=str(user.id), active=True)
                    .select_related("player__django_user")
                    .first()
                )

                if not linked_account:
                    return []

                # Check if the player has a django_user linked
                player = linked_account.player
                django_user = player.django_user if player else None
                if not django_user:
                    return []

                groups = list(django_user.groups.values_list("name", flat=True))
                return groups
            except Exception:
                return []

        return await get_django_user_groups()

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

    async def _fetch_user_permissions(self, user: discord.User) -> PermissionContext:
        """
        Fetch user permissions from Django database.

        Args:
            user: The Discord user to fetch permissions for

        Returns:
            PermissionContext: Fresh permission context for the user
        """
        # Get Django groups using the centralized method
        django_groups = await self.get_user_django_groups(user)

        # Get Discord roles (if user is in a guild context, we'll need to handle this differently)
        # For now, just get basic user info
        discord_roles = []

        # Check if user is bot owner
        is_bot_owner = await self.bot.is_owner(user)

        return PermissionContext(user_id=user.id, django_groups=django_groups, discord_roles=discord_roles, is_bot_owner=is_bot_owner)

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

    # ====================
    # Django ORM Query Helpers
    # ====================

    async def get_linked_account_by_discord_id(
        self, discord_id: str, active_only: bool = True, select_related: bool = True
    ) -> Optional[LinkedAccount]:
        """
        Get LinkedAccount by Discord ID.

        This is a centralized method for LinkedAccount queries to avoid code duplication.

        Args:
            discord_id: Discord user ID as string
            active_only: If True, only return active accounts
            select_related: If True, select_related player and django_user

        Returns:
            LinkedAccount if found, None otherwise
        """
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import LinkedAccount

        @sync_to_async
        def query_linked_account():
            query = LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=str(discord_id))
            if active_only:
                query = query.filter(active=True)
            if select_related:
                query = query.select_related("player__django_user")
            return query.first()

        return await query_linked_account()

    async def get_player_by_discord_id(self, discord_id: str, active_only: bool = True) -> Optional[KnownPlayer]:
        """
        Get KnownPlayer by Discord ID.

        Args:
            discord_id: Discord user ID as string
            active_only: If True, only consider active LinkedAccounts

        Returns:
            KnownPlayer if found, None otherwise
        """
        linked_account = await self.get_linked_account_by_discord_id(discord_id, active_only=active_only)
        return linked_account.player if linked_account else None

    async def get_linked_accounts_by_player(self, player: "KnownPlayer", platform: str = None, active_only: bool = True) -> List["LinkedAccount"]:
        """
        Get all LinkedAccounts for a player.

        Args:
            player: KnownPlayer instance
            platform: Optional platform filter (e.g., 'DISCORD')
            active_only: If True, only return active accounts

        Returns:
            List of LinkedAccount objects
        """
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import LinkedAccount

        @sync_to_async
        def query_linked_accounts():
            query = LinkedAccount.objects.filter(player=player)
            if platform:
                query = query.filter(platform=platform)
            if active_only:
                query = query.filter(active=True)
            return list(query)

        return await query_linked_accounts()

    async def get_primary_linked_account(self, player: KnownPlayer, platform: str = "DISCORD") -> Optional[LinkedAccount]:
        """
        Get the primary LinkedAccount for a player.

        Args:
            player: KnownPlayer instance
            platform: Platform to filter by (default: DISCORD)

        Returns:
            Primary LinkedAccount if found, None otherwise
        """
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import LinkedAccount

        @sync_to_async
        def query_primary_account():
            return LinkedAccount.objects.filter(player=player, platform=platform, primary=True).first()

        return await query_primary_account()

    async def get_player_by_player_id(self, player_id: str) -> Optional[KnownPlayer]:
        """
        Get KnownPlayer by Tower player ID.

        Args:
            player_id: Tower player ID

        Returns:
            KnownPlayer if found, None otherwise
        """
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import KnownPlayer

        @sync_to_async
        def query_player():
            return KnownPlayer.objects.filter(game_instances__player_ids__id=player_id).select_related("django_user").first()

        return await query_player()

    async def get_player_by_name(self, name: str, case_sensitive: bool = False) -> Optional[KnownPlayer]:
        """
        Get KnownPlayer by name.

        Args:
            name: Player name
            case_sensitive: If True, use exact case matching

        Returns:
            KnownPlayer if found, None otherwise
        """
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import KnownPlayer

        @sync_to_async
        def query_player():
            if case_sensitive:
                return KnownPlayer.objects.filter(name=name).select_related("django_user").first()
            else:
                return KnownPlayer.objects.filter(name__iexact=name).select_related("django_user").first()

        return await query_player()

    async def check_discord_account_exists(self, discord_id: str, active_only: bool = True) -> bool:
        """
        Check if a Discord account exists in the database.

        Args:
            discord_id: Discord user ID as string
            active_only: If True, only check active accounts

        Returns:
            True if account exists, False otherwise
        """
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import LinkedAccount

        @sync_to_async
        def check_exists():
            query = LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=str(discord_id))
            if active_only:
                query = query.filter(active=True)
            return query.exists()

        return await check_exists()
