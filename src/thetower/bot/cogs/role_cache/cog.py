# Standard library
import asyncio
import datetime
from collections import defaultdict, deque
from typing import Optional

# Third-party
import discord
from discord.ext import commands, tasks

# Local
from thetower.bot.basecog import BaseCog

from .ui import (
    AdminCommands,
    RoleCacheSettingsView,
    UserCommands,
)


class RoleCache(BaseCog, name="Role Cache", description="Cache for Discord role assignments."):
    """Cache for Discord role assignments.

    Maintains a cache of user roles to reduce API calls and improve performance
    of role-based operations across the bot.
    """

    # Settings view class for the cog manager
    settings_view_class = RoleCacheSettingsView

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing RoleCache")

        # Initialize core instance variables with descriptions
        self.member_roles = defaultdict(dict)  # {guild_id: {user_id: {"roles": set(role_ids), "updated_at": timestamp}}}
        self._fetching_guilds = set()
        self._update_queues = {}  # {guild_id: deque()}

        # Status tracking variables
        self._active_process = None
        self._process_start_time = None

        # Store reference on bot
        self.bot.role_cache = self

        # Global settings (bot-wide)
        self.global_settings = {
            "refresh_interval": 1800,  # 30 minutes
            "staleness_threshold": 3600,  # 1 hour
            "save_interval": 300,  # 5 minutes
            "cache_filename": "role_cache_all.json",
        }

        # Guild-specific settings (none for this cog currently)
        self.guild_settings = {}

    async def save_cache(self) -> bool:
        """Save the member role cache using BaseCog's utility."""
        async with self.task_tracker.task_context("Save Cache", "Preparing data") as tracker:
            try:
                # Prepare serializable data
                tracker.update_status("Serializing cache data")
                save_data = {
                    guild_id: {str(user_id): {"roles": list(data["roles"]), "updated_at": data["updated_at"]} for user_id, data in guild_data.items()}
                    for guild_id, guild_data in self.member_roles.items()
                }

                # Use BaseCog's utility to save data
                tracker.update_status("Writing to disk")
                success = await self.save_data_if_modified(save_data, self.data_directory / self.cache_file)
                if success:
                    self.logger.info(f"Saved role cache with {len(self.member_roles)} guild entries")
                return success

            except Exception as e:
                self.logger.error(f"Error saving role cache: {e}", exc_info=True)
                self._has_errors = True
                return False

    async def load_cache(self) -> bool:
        """Load the member role cache using BaseCog's utility."""
        try:
            save_data = await self.load_data(self.data_directory / self.cache_file, default={})

            if save_data:
                # Convert string user IDs back to ints and roles to sets
                self.member_roles = defaultdict(
                    dict,
                    {
                        guild_id: {
                            int(user_id): {"roles": set(data["roles"]), "updated_at": data["updated_at"]} for user_id, data in guild_data.items()
                        }
                        for guild_id, guild_data in save_data.items()
                    },
                )
                self.logger.info(f"Loaded role cache with {len(self.member_roles)} guild entries")
                return True

            self.logger.info("No role cache file found, starting with empty cache")
            self.member_roles = defaultdict(dict)
            return False

        except Exception as e:
            self.logger.error(f"Error loading role cache: {e}", exc_info=True)
            self._has_errors = True
            self.member_roles = {}
            return False

    async def cog_initialize(self) -> None:
        """Initialize the Role Cache cog."""
        self.logger.info("Initializing RoleCache cog")
        try:
            self.logger.info("Starting Role Cache initialization")

            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                await super().cog_initialize()

                # 1. Verify settings
                self.logger.debug("Loading settings")
                tracker.update_status("Verifying settings")
                self._load_settings()

                # 2. Load cache
                self.logger.debug("Loading cache from disk")
                tracker.update_status("Loading cache")
                if await self.load_cache():
                    self.logger.info("Loaded cache from disk")
                else:
                    self.logger.info("No cache file found, will create new cache")

                # 3. Clean up cache for disabled guilds
                self.logger.debug("Cleaning up cache for disabled guilds")
                tracker.update_status("Cleaning up disabled guilds")
                removed_guilds, removed_members = await self.cleanup_disabled_guilds()
                if removed_guilds > 0:
                    self.logger.info(f"Cleaned up cache for {removed_guilds} disabled guilds")

                # 4. Start maintenance tasks with proper task tracking
                self.logger.debug("Starting maintenance tasks")
                tracker.update_status("Starting maintenance tasks")

                # Start tasks after ensuring they're not already running
                if not self.periodic_save.is_running():
                    self.periodic_save.start()
                if not self.periodic_refresh.is_running():
                    self.periodic_refresh.start()

                # 5. Mark as ready and complete initialization
                self.set_ready(True)
                self.logger.info("Role Cache initialization complete")

        except Exception as e:
            self.logger.error(f"Error during Role Cache initialization: {e}", exc_info=True)
            self._has_errors = True
            raise

    def _load_settings(self):
        """Load settings from defaults and initialize instance attributes."""
        # Initialize settings in the config system for guilds where the cog is allowed
        for guild in self.bot.guilds:
            if self.bot.cog_manager.can_guild_use_cog("role_cache", guild.id):
                self.ensure_settings_initialized(guild_id=guild.id, default_settings=self.guild_settings)

        # Initialize instance attributes from global settings
        self.refresh_interval = self.global_settings["refresh_interval"]
        self.staleness_threshold = self.global_settings["staleness_threshold"]
        self.save_interval = self.global_settings["save_interval"]
        self.cache_file = self.global_settings["cache_filename"]

        self.logger.debug("Settings loaded and instance attributes initialized")

    @tasks.loop(seconds=None)  # Will set interval in start method
    async def periodic_refresh(self):
        """Periodically refresh stale roles and clean up missing members."""
        try:
            # Skip if paused
            if self.is_paused:
                return

            async with self.task_tracker.task_context("Cache Refresh", "Starting refresh cycle") as tracker:
                self.logger.debug("Starting periodic role cache refresh cycle")

                # Perform the refresh operations
                tracker.update_status("Refreshing stale roles")
                await self.refresh_stale_roles()

                tracker.update_status("Cleaning up missing members")
                await self.cleanup_missing_members()

                self._last_refresh_time = datetime.datetime.now()
                self.logger.debug("Completed periodic role cache refresh cycle")

        except asyncio.CancelledError:
            self.logger.info("Role cache refresh task was cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error in periodic refresh: {e}", exc_info=True)
            self._has_errors = True

    @periodic_refresh.before_loop
    async def before_periodic_refresh(self):
        """Setup before the refresh task starts."""
        self.logger.info(f"Starting periodic role cache refresh task (interval: {self.refresh_interval}s)")
        await self.bot.wait_until_ready()
        await self.wait_until_ready()  # Ensure cog is fully initialized

        # Set the interval dynamically based on settings
        self.periodic_refresh.change_interval(seconds=self.refresh_interval)

    @periodic_refresh.after_loop
    async def after_periodic_refresh(self):
        """Cleanup after the refresh task ends."""
        if self.periodic_refresh.is_being_cancelled():
            self.logger.info("Role cache refresh task was cancelled")
        else:
            self.logger.warning("Role cache refresh task ended unexpectedly")

    @tasks.loop(seconds=None)
    async def periodic_save(self):
        """Periodically save the role cache to disk."""
        try:
            async with self.task_tracker.task_context("Cache Save", "Saving to disk") as tracker:
                self.logger.debug("Starting periodic role cache save")
                await self.save_cache()
                tracker.update_status("Save complete")
        except Exception as e:
            self.logger.error(f"Error in periodic save: {e}", exc_info=True)
            self._has_errors = True

    @periodic_save.before_loop
    async def before_periodic_save(self):
        """Setup before the save task starts."""
        self.logger.info(f"Starting periodic role cache save task (interval: {self.save_interval}s)")
        await self.bot.wait_until_ready()
        await self.wait_until_ready()  # Ensure cog is fully initialized

        # Set the interval dynamically based on settings
        self.periodic_save.change_interval(seconds=self.save_interval)

    @periodic_save.after_loop
    async def after_periodic_save(self):
        """Cleanup after the save task ends."""
        if self.periodic_save.is_being_cancelled():
            self.logger.info("Role cache save task was cancelled")
            # Do one final save
            await self.save_cache()
        else:
            self.logger.warning("Role cache save task ended unexpectedly")

    async def _build_initial_cache(self):
        """Build the initial role cache for all guilds."""
        async with self.task_tracker.task_context("Initial Cache Build", "Building role cache for all guilds"):
            try:
                guild = self.guild
                if not guild:
                    self.logger.error("Could not find guild")
                    return

                self.task_tracker.update_status("Initial Cache Build", f"Building cache for guild {guild.name}")
                await self.build_cache(guild)
                self.logger.info("Initial role cache build complete")

            except Exception as e:
                self.logger.error(f"Error building initial cache: {e}")
                raise

    async def get_all_members(self, guild: discord.Guild) -> list[discord.Member]:
        """Get all members from a guild, handling chunk requests and rate limits."""
        async with self.task_tracker.task_context("Member Fetch", f"Fetching members for {guild.name}"):
            if guild.id in self._fetching_guilds:
                self.logger.warning(f"Already fetching members for guild {guild.id}")
                return []

            self._fetching_guilds.add(guild.id)
            self._update_queues[guild.id] = deque()

            try:
                # Handle rate limits gracefully
                try:
                    await guild.chunk(cache=True)
                except discord.HTTPException as e:
                    if e.code == 50001:  # Missing Access
                        self.logger.error(f"Missing permissions to fetch members in {guild.name}")
                        return []
                    elif e.status == 429:  # Rate limited
                        retry_after = e.retry_after
                        self.logger.warning(f"Rate limited while fetching members. Waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        await guild.chunk(cache=True)
                    else:
                        raise

                members = guild.members
                self.logger.info(f"Fetched {len(members)} members from {guild.name}")
                return members
            finally:
                self._fetching_guilds.remove(guild.id)
                self._update_queues.pop(guild.id, None)

    async def build_cache(self, guild):
        """Build the role cache for a guild."""
        async with self.task_tracker.task_context("Cache Build", f"Building cache for {guild.name}"):
            members = await self.get_all_members(guild)

            if not members:
                self.logger.warning("No members returned from get_all_members")
                return

            self.task_tracker.update_status("Cache Build", f"Processing {len(members)} members")

            for member in members:
                self.update_member_roles(member)

            self.logger.info(f"Built role cache for {len(members)} members in {guild.name}")

    def update_member_roles(self, member):
        """Update cached roles for a member with timestamp"""
        if not member or not member.guild:
            return

        # Store roles with explicit UTC timestamp
        self.member_roles[member.guild.id][member.id] = {
            "roles": {role.id for role in member.roles},
            "updated_at": datetime.datetime.now(datetime.timezone.utc).timestamp(),
        }

        # Mark data as modified using BaseCog's method
        self.mark_data_modified()

    def has_role(self, guild_id, user_id, role_id):
        """Check if a user has a specific role"""
        try:
            return role_id in self.member_roles[guild_id][user_id]["roles"]
        except (KeyError, TypeError):
            return False

    def get_roles(self, guild_id, user_id):
        """Get all role IDs for a user"""
        try:
            return self.member_roles.get(guild_id, {}).get(user_id, {}).get("roles", set())
        except (KeyError, TypeError):
            return set()

    def is_stale(self, guild_id, user_id):
        """Check if cached roles for a user are stale and need refresh"""
        try:
            updated_at = self.member_roles[guild_id][user_id]["updated_at"]
            now = datetime.datetime.now(datetime.timezone.utc).timestamp()
            return (now - updated_at) > self.staleness_threshold
        except (KeyError, TypeError):
            return True

    async def refresh_stale_roles(self):
        """Refresh roles for users whose cache is stale"""
        self.logger.info("Checking for stale roles to refresh...")
        refreshed_count = 0

        for guild in self.bot.guilds:
            # Only refresh for guilds where the cog is allowed
            if not self.bot.cog_manager.can_guild_use_cog("role_cache", guild.id):
                continue

            for member in guild.members:
                if self.is_stale(guild.id, member.id):
                    self.update_member_roles(member)
                    refreshed_count += 1

        if refreshed_count > 0:
            self.logger.info(f"Refreshed roles for {refreshed_count} members")
        else:
            self.logger.info("No stale roles found to refresh")
        return refreshed_count

    async def cleanup_disabled_guilds(self):
        """Remove cache entries for guilds where the cog is no longer allowed"""
        removed_guilds = []
        removed_members = 0

        for guild_id in list(self.member_roles.keys()):
            if not self.bot.cog_manager.can_guild_use_cog("role_cache", guild_id):
                members_count = len(self.member_roles[guild_id])
                del self.member_roles[guild_id]
                removed_guilds.append(guild_id)
                removed_members += members_count
                self.mark_data_modified()

        if removed_guilds:
            self.logger.info(f"Cleaned up cache for {len(removed_guilds)} disallowed guilds ({removed_members} members)")

        return len(removed_guilds), removed_members

    async def cleanup_missing_members(self):
        """Remove cache entries for members who are no longer in guilds"""
        removed_count = 0

        for guild in self.bot.guilds:
            # Only cleanup for guilds where the cog is allowed
            if not self.bot.cog_manager.can_guild_use_cog("role_cache", guild.id):
                continue

            if guild.id not in self.member_roles:
                continue

            # Get set of current member IDs in the guild
            current_member_ids = {member.id for member in guild.members}

            # Find cached members who are no longer in the guild
            cached_member_ids = set(self.member_roles[guild.id].keys())
            missing_member_ids = cached_member_ids - current_member_ids

            # Remove those members from cache
            for member_id in missing_member_ids:
                del self.member_roles[guild.id][member_id]
                removed_count += 1
                self.mark_data_modified()

        if removed_count > 0:
            self.logger.info(f"Cleaned up {removed_count} cached entries for members no longer in guilds")

        return removed_count

    # Initialize UI command containers
    def __post_init__(self):
        """Initialize UI command containers after cog initialization."""
        self.user_commands = UserCommands(self)
        self.admin_commands = AdminCommands(self)

    @commands.group(name="rolecache", aliases=["rc"], invoke_without_command=True)
    async def rolecache_group(self, ctx):
        """Role cache commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @rolecache_group.command(name="settings")
    async def settings_command(self, ctx):
        """Display current role cache settings"""
        await self.admin_commands.settings(ctx)

    @rolecache_group.command(name="set")
    async def set_setting_command(self, ctx, setting_name: str, value: int):
        """Change a role cache setting"""
        await self.admin_commands.set_setting(ctx, setting_name, value)

    @rolecache_group.command(name="status")
    async def show_status(self, ctx):
        """Display current operational status and statistics of the role cache system."""
        await self.admin_commands.status(ctx)

    @rolecache_group.command(name="rolestats")
    async def rolestats_command(self, ctx, *, match_string=None):
        """Show counts of how many users have each role"""
        await self.user_commands.rolestats(ctx, match_string=match_string)

    @rolecache_group.command(name="lookup")
    async def lookup_command(self, ctx, member: discord.Member):
        """Look up cached roles for a member"""
        await self.user_commands.lookup(ctx, member)

    @rolecache_group.command(name="refresh")
    async def refresh_command(self, ctx, target: Optional[discord.Member] = None):
        """Refresh role cache for a user or the entire server."""
        await self.user_commands.refresh(ctx, target)

    @rolecache_group.command(name="reload")
    async def reload_command(self, ctx, target: Optional[discord.Member] = None):
        """Reload/refresh role cache for a user or the entire server."""
        await self.user_commands.reload(ctx, target)

    @rolecache_group.command(name="forcefetch")
    async def force_fetch(self, ctx: commands.Context) -> None:
        """Force a complete refresh using fetch_members"""
        await self.admin_commands.forcefetch(ctx)

    @rolecache_group.error
    async def rolecache_error(self, ctx: commands.Context, error: Exception) -> None:
        """Error handler for rolecache command group."""
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command.")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send("❌ I don't have the required permissions to do this.")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("❌ This command can't be used in private messages.")
        else:
            self.logger.error(f"Error in rolecache command: {error}", exc_info=True)
            await ctx.send(f"❌ An error occurred: {str(error)}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Update role cache when member's roles change."""
        # Only cache for guilds where the cog is allowed
        if not self.bot.cog_manager.can_guild_use_cog("role_cache", after.guild.id):
            return

        if before.roles != after.roles:
            guild_id = after.guild.id

            try:
                # If we're currently fetching this guild, queue the update
                if guild_id in self._fetching_guilds:
                    self._update_queues[guild_id].append(after)
                    self.logger.debug(f"Queued role update for {after.display_name} during fetching")
                else:
                    # Otherwise process it immediately
                    self.update_member_roles(after)
                    self.logger.debug(f"Updated roles for {after.display_name} in {after.guild.name}")
            except Exception as e:
                self.logger.error(f"Error updating roles for {after.display_name}: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Add new member to role cache"""
        # Only cache for guilds where the cog is allowed
        if not self.bot.cog_manager.can_guild_use_cog("role_cache", member.guild.id):
            return

        self.update_member_roles(member)
        self.logger.debug(f"Added new member {member.display_name} to role cache for {member.guild.name}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Remove member from role cache when they leave"""
        # Only manage cache for guilds where the cog is allowed
        if not self.bot.cog_manager.can_guild_use_cog("role_cache", member.guild.id):
            return

        if member.guild.id in self.member_roles:
            if member.id in self.member_roles[member.guild.id]:
                del self.member_roles[member.guild.id][member.id]
                self.mark_data_modified()
                self.logger.debug(f"Removed cached roles for {member.display_name} leaving {member.guild.name}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Build role cache when bot joins a new guild"""
        # Only build cache for guilds where the cog is allowed
        if not self.bot.cog_manager.can_guild_use_cog("role_cache", guild.id):
            return

        await self.build_cache(guild)
        self.logger.info(f"Built role cache for new guild: {guild.name}")
        # Force save using BaseCog's utility
        await self.save_data_if_modified(self.member_roles, self.cache_file, force=True)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Remove guild data from cache when bot leaves a guild"""
        if guild.id in self.member_roles:
            # Store number of members for logging
            members_count = len(self.member_roles[guild.id])

            # Remove the guild data
            del self.member_roles[guild.id]
            self.mark_data_modified()

            self.logger.info(f"Removed role cache for departed guild: {guild.name} ({members_count} members)")

    async def on_reconnect(self):
        await super().on_reconnect()
        async with self.task_tracker.task_context("Role Refresh", "Refreshing stale roles after reconnect"):
            await self.refresh_stale_roles()

    @commands.Cog.listener()
    async def on_guild_members_chunk(self, guild: discord.Guild, members: list[discord.Member]) -> None:
        """Log when receiving member chunks from Discord"""
        self.logger.debug(f"Received member chunk from Discord: {len(members)} members for {guild.name}")

    async def refresh_user_roles(self, guild_id: int, user_id: int) -> bool:
        """Refresh roles for a specific user

        Args:
            guild_id: ID of the guild
            user_id: ID of the user to refresh

        Returns:
            bool: True if user was found and refreshed, False otherwise
        """
        async with self.task_tracker.task_context("User Refresh", f"Refreshing user {user_id} in guild {guild_id}"):
            guild = self.bot.get_guild(guild_id)
            if not guild:
                self.logger.warning(f"Couldn't refresh user {user_id}: Guild {guild_id} not found")
                return False

            member = guild.get_member(user_id)
            if not member:
                self.logger.warning(f"Couldn't refresh user {user_id}: Member not found in guild {guild.name}")
                return False

            self.update_member_roles(member)
            self.logger.info(f"Manually refreshed roles for {member.display_name} in {guild.name}")
            return True

    async def cog_unload(self):
        """Clean up when cog is unloaded."""
        # Cancel all periodic tasks
        for task in [self.periodic_refresh, self.periodic_save]:
            if task.is_running():
                task.cancel()

        # Use parent implementation to save data if modified
        await super().cog_unload()


async def setup(bot):
    try:
        cog = RoleCache(bot)
        cog.__post_init__()  # Initialize UI command containers
        await bot.add_cog(cog)
        bot.logger.info("Successfully loaded RoleCache cog")
    except Exception as e:
        bot.logger.error(f"Failed to load RoleCache cog: {e}", exc_info=True)
        raise
