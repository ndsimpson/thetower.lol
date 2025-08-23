# Standard library
import asyncio
import datetime
from pathlib import Path
from collections import deque
from typing import Optional

# Third-party
import discord
from discord.ext import commands, tasks

# Local
from fish_bot.basecog import BaseCog


class RoleCache(BaseCog,
                name="Role Cache",
                description="Cache for Discord role assignments."):
    """Cache for Discord role assignments.

    Maintains a cache of user roles to reduce API calls and improve performance
    of role-based operations across the bot.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing RoleCache")

        # Initialize core instance variables with descriptions
        self.member_roles = {}  # {guild_id: {user_id: {"roles": [role_ids], "updated_at": timestamp}}}
        self._fetching_guilds = set()
        self._update_queues = {}  # {guild_id: deque()}

        # Status tracking variables
        self._active_process = None
        self._process_start_time = None

        # Store reference on bot
        self.bot.role_cache = self

        # Define settings with descriptions
        settings_config = {
            "refresh_interval": (1800, "How often to refresh data (seconds, default 30 minutes)"),
            "staleness_threshold": (3600, "Maximum age before data is considered stale (seconds, default 1 hour)"),
            "save_interval": (300, "How often to save data to disk (seconds, default 5 minutes)"),
            "cache_filename": ("role_cache.json", "Cache data filename")
        }

        # Initialize settings
        for name, (value, description) in settings_config.items():
            if not self.has_setting(name):
                self.set_setting(name, value, description=description)

        # Load settings into instance variables
        self._load_settings()

    def _load_settings(self) -> None:
        """Load settings into instance variables."""
        self.refresh_interval = self.get_setting('refresh_interval')
        self.staleness_threshold = self.get_setting('staleness_threshold')
        self.save_interval = self.get_setting('save_interval')
        self.cache_filename = self.get_setting('cache_filename')

    @property
    def cache_file(self) -> Path:
        """Get the cache file path using the cog's data directory"""
        return self.data_directory / self.cache_filename

    async def save_cache(self) -> bool:
        """Save the member role cache using BaseCog's utility."""
        async with self.task_tracker.task_context("Save Cache", "Preparing data") as tracker:
            try:
                # Prepare serializable data
                tracker.update_status("Serializing cache data")
                save_data = {
                    guild_id: {
                        str(user_id): data
                        for user_id, data in guild_data.items()
                    }
                    for guild_id, guild_data in self.member_roles.items()
                }

                # Use BaseCog's utility to save data
                tracker.update_status("Writing to disk")
                success = await self.save_data_if_modified(save_data, self.cache_file)
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
            save_data = await self.load_data(self.cache_file, default={})

            if save_data:
                # Convert string user IDs back to ints
                self.member_roles = {
                    guild_id: {
                        int(user_id): data
                        for user_id, data in guild_data.items()
                    }
                    for guild_id, guild_data in save_data.items()
                }
                self.logger.info(f"Loaded role cache with {len(self.member_roles)} guild entries")
                return True

            self.logger.info("No role cache file found, starting with empty cache")
            self.member_roles = {}
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

                # 0. Create inherited commands
                self.create_pause_commands(self.rolecache_group)

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

                # 3. Start maintenance tasks with proper task tracking
                self.logger.debug("Starting maintenance tasks")
                tracker.update_status("Starting maintenance tasks")

                # Start tasks after ensuring they're not already running
                if not self.periodic_save.is_running():
                    self.periodic_save.start()
                if not self.periodic_refresh.is_running():
                    self.periodic_refresh.start()

                # 4. Mark as ready and complete initialization
                self.set_ready(True)
                self.logger.info("Role Cache initialization complete")

        except Exception as e:
            self.logger.error(f"Error during Role Cache initialization: {e}", exc_info=True)
            self._has_errors = True
            raise

    @tasks.loop(seconds=None)  # Will set interval in start method
    async def periodic_refresh(self):
        """Periodically refresh stale roles and clean up missing members."""
        try:
            # Skip if paused
            if not self.is_paused:
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

        if member.guild.id not in self.member_roles:
            self.member_roles[member.guild.id] = {}

        # Store roles with explicit UTC timestamp
        self.member_roles[member.guild.id][member.id] = {
            "roles": [role.id for role in member.roles],
            "updated_at": datetime.datetime.now(datetime.timezone.utc).timestamp()
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
            return self.member_roles[guild_id][user_id]["roles"]
        except (KeyError, TypeError):
            return []

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
            for member in guild.members:
                if self.is_stale(guild.id, member.id):
                    self.update_member_roles(member)
                    refreshed_count += 1

        if refreshed_count > 0:
            self.logger.info(f"Refreshed roles for {refreshed_count} members")
        else:
            self.logger.info("No stale roles found to refresh")
        return refreshed_count

    async def cleanup_missing_members(self):
        """Remove cache entries for members who are no longer in guilds"""
        removed_count = 0

        for guild in self.bot.guilds:
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

    @commands.group(name="rolecache", aliases=["rc"], invoke_without_command=True)
    async def rolecache_group(self, ctx):
        """Role cache commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @rolecache_group.command(name="settings")
    async def settings_command(self, ctx):
        """Display current role cache settings"""
        settings = self.get_all_settings()

        embed = discord.Embed(
            title="Role Cache Settings",
            description="Current configuration for role caching system",
            color=discord.Color.blue()
        )

        for name, value in settings.items():
            # Format durations in a more readable way for time-based settings
            if name in ["refresh_interval", "staleness_threshold", "save_interval"]:
                hours = value // 3600
                minutes = (value % 3600) // 60
                seconds = value % 60
                formatted_value = f"{hours}h {minutes}m {seconds}s ({value} seconds)"
                embed.add_field(name=name, value=formatted_value, inline=False)
            else:
                embed.add_field(name=name, value=str(value), inline=False)

        await ctx.send(embed=embed)

    @rolecache_group.command(name="set")
    async def set_setting_command(self, ctx, setting_name: str, value: int):
        """Change a role cache setting

        Args:
            setting_name: Setting to change (refresh_interval, staleness_threshold, save_interval)
            value: New value for the setting (in seconds)
        """
        valid_settings = [
            "refresh_interval",
            "staleness_threshold",
            "save_interval"
        ]

        if setting_name not in valid_settings:
            valid_settings_str = ", ".join(valid_settings)
            return await ctx.send(f"Invalid setting name. Valid options: {valid_settings_str}")

        # Validate inputs based on the setting
        if setting_name in ["refresh_interval", "staleness_threshold", "save_interval"]:
            if value < 60:  # Minimum 60 seconds for time intervals
                return await ctx.send(f"Value for {setting_name} must be at least 60 seconds")

        # Update instance variables immediately
        if setting_name == 'refresh_interval':
            self.refresh_interval = value
        elif setting_name == 'staleness_threshold':
            self.staleness_threshold = value
        elif setting_name == 'save_interval':
            self.save_interval = value

        # Save the setting
        self.set_setting(setting_name, value)

        # Format confirmation message
        hours = value // 3600
        minutes = (value % 3600) // 60
        seconds = value % 60
        time_format = f"{hours}h {minutes}m {seconds}s"
        await ctx.send(f"✅ Set {setting_name} to {value} seconds ({time_format})")

        self.logger.info(f"Settings changed: {setting_name} set to {value} by {ctx.author}")

    @rolecache_group.command(name="rolestats")
    async def rolestats_command(self, ctx, *, match_string=None):
        """Show counts of how many users have each role

        Args:
            match_string: Optional filter to show only roles containing this string
        """
        await ctx.typing()

        if not ctx.guild:
            return await ctx.send("This command must be used in a server.")

        # Make sure the cache for this guild is ready
        if not self.is_ready:
            return await ctx.send("Role cache is still being built. Please try again later.")

        # Count users per role
        role_counts = {}
        guild_id = ctx.guild.id

        # Initialize counts for all roles in the guild
        for role in ctx.guild.roles:
            role_counts[role.id] = 0

        # Count instances of each role
        if guild_id in self.member_roles:
            for member_id, data in self.member_roles[guild_id].items():
                for role_id in data.get("roles", []):
                    if role_id in role_counts:
                        role_counts[role_id] += 1

        # Create a list of (role, count) tuples filtered by match string if provided
        role_stats = []
        for role in ctx.guild.roles:
            if match_string is None or match_string.lower() in role.name.lower():
                role_stats.append((role, role_counts[role.id]))

        # Sort by count (highest first)
        role_stats.sort(key=lambda x: x[1], reverse=True)

        # No matching roles
        if not role_stats:
            return await ctx.send(f"No roles found matching '{match_string}'")

        # Create plain text output
        header = f"Role Statistics in {ctx.guild.name}"
        if match_string:
            header += f" matching '{match_string}'"

        lines = [header, "=" * len(header), ""]

        # Add role counts
        for role, count in role_stats:
            lines.append(f"{role.name}: {count} members")

        # Footer with total count
        lines.append("")
        lines.append(f"Total: {len(role_stats)} roles")

        # Join all lines
        full_text = "\n".join(lines)

        # Handle Discord's 2000 character limit
        if len(full_text) <= 1994:  # Leave room for code block markers
            await ctx.send(f"```\n{full_text}\n```")
        else:
            # Split into multiple messages if too long
            chunks = []
            current_chunk = [header, "=" * len(header), ""]
            current_length = sum(len(line) + 1 for line in current_chunk)  # +1 for newline

            for line in lines[3:-2]:  # Skip header and footer we already added
                # Check if adding this line would exceed limit
                line_length = len(line) + 1  # +1 for newline
                if current_length + line_length > 1900:  # Conservative limit
                    # Finish current chunk
                    chunks.append("\n".join(current_chunk))
                    # Start new chunk
                    current_chunk = [f"{header} (continued)", "=" * len(header), ""]
                    current_length = sum(len(line) + 1 for line in current_chunk)

                # Add line to current chunk
                current_chunk.append(line)
                current_length += line_length

            # Add footer to last chunk
            current_chunk.append("")
            current_chunk.append(f"Total: {len(role_stats)} roles")
            chunks.append("\n".join(current_chunk))

            # Send all chunks
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await ctx.send(f"```\n{chunk}\n```")
                else:
                    await ctx.send(f"```\n{chunk}\n```")

    @rolecache_group.command(name="status")
    async def show_status(self, ctx):
        """Display current operational status and statistics of the role cache system."""
        # Determine overall status
        has_errors = hasattr(self, '_has_errors') and self._has_errors

        if not self.is_ready:
            status_emoji = "⏳"
            status_text = "Initializing"
            embed_color = discord.Color.orange()
        elif has_errors:
            status_emoji = "❌"
            status_text = "Error"
            embed_color = discord.Color.red()
        else:
            status_emoji = "✅"
            status_text = "Operational"
            embed_color = discord.Color.blue()

        # Create status embed
        embed = discord.Embed(
            title="Role Cache Status",
            description=f"Current status: {status_emoji} {status_text}",
            color=embed_color
        )

        # Add general cache statistics
        guild_count = len(self.member_roles)
        total_members = sum(len(guild_data) for guild_data in self.member_roles.values())

        # Count stale entries
        stale_count = 0
        for guild_id, members in self.member_roles.items():
            for member_id, data in members.items():
                if self.is_stale(guild_id, member_id):
                    stale_count += 1

        # Main statistics
        stats_fields = [
            ("Cache Overview", [
                f"**Guilds Cached**: {guild_count}",
                f"**Members Cached**: {total_members}",
                f"**Stale Entries**: {stale_count}",
                f"**Status**: {'Ready' if self.is_ready else 'Building'}"
            ]),
            ("Configuration", [
                f"**Refresh Interval**: {self.format_time_value(self.refresh_interval)}",
                f"**Staleness Threshold**: {self.format_time_value(self.staleness_threshold)}",
                f"**Save Interval**: {self.format_time_value(self.save_interval)}"
            ])
        ]

        for name, items in stats_fields:
            embed.add_field(
                name=name,
                value="\n".join(items),
                inline=False
            )

        # Add cache file information
        cache_file = self.cache_file
        if cache_file.exists():
            size_kb = cache_file.stat().st_size / 1024
            modified = datetime.datetime.fromtimestamp(cache_file.stat().st_mtime)
            embed.add_field(
                name="Cache File",
                value=f"Size: {size_kb:.1f} KB\nLast Modified: {modified.strftime('%Y-%m-%d %H:%M:%S')}",
                inline=False
            )

        # Add active process information
        active_process = getattr(self, '_active_process', None)
        if active_process:
            process_start = getattr(self, '_process_start_time', None)
            if process_start:
                time_since = (datetime.datetime.now() - process_start).total_seconds()
                time_str = f"{int(time_since // 60)}m {int(time_since % 60)}s ago"
                embed.add_field(
                    name="Active Processes",
                    value=f"🔄 {active_process} (started {time_str})",
                    inline=False
                )

        # Add last activity information
        last_refresh = getattr(self, '_last_refresh_time', None)
        if last_refresh:
            time_str = self.format_relative_time(last_refresh)
            embed.add_field(
                name="Last Activity",
                value=f"Cache refreshed: {time_str}",
                inline=False
            )

        # Add task tracking information
        self.add_task_status_fields(embed)

        await ctx.send(embed=embed)

    @rolecache_group.command(name="reload")
    async def reload_command(self, ctx, target: Optional[discord.Member] = None):
        """Reload/refresh role cache for a user or the entire server."""
        if not ctx.guild:
            return await ctx.send("This command must be used in a server.")

        # Defer response for potentially long operation
        await ctx.defer()

        async with self.task_tracker.task_context("Manual Refresh") as tracker:
            if target:
                tracker.update_status(f"Refreshing roles for {target.display_name}")
                self.update_member_roles(target)
                await ctx.send(f"✅ Refreshed roles for {target.display_name}")
            else:
                total_members = len(ctx.guild.members)
                message = await ctx.send(f"🔄 Refreshing roles for all members in {ctx.guild.name}...")

                try:
                    for i, member in enumerate(ctx.guild.members, 1):
                        tracker.update_status(f"Processing member {i}/{total_members}")
                        self.update_member_roles(member)

                        if i % 100 == 0:  # Update progress every 100 members
                            try:
                                await message.edit(content=f"🔄 Refreshing roles: {i}/{total_members} members processed...")
                            except discord.NotFound:
                                # Message was deleted, create new one
                                message = await ctx.send(f"🔄 Refreshing roles: {i}/{total_members} members processed...")

                    await message.edit(content=f"✅ Refreshed roles for all {total_members} members in {ctx.guild.name}")
                    await self.save_data_if_modified(self.member_roles, self.cache_file, force=True)

                except discord.Forbidden:
                    await ctx.send("❌ I don't have permission to manage roles in this server.")
                except discord.HTTPException as e:
                    if e.status == 429:  # Rate limited
                        await ctx.send(f"⚠️ Rate limited by Discord. Please try again in {e.retry_after:.1f} seconds.")
                    else:
                        await ctx.send(f"❌ Discord API error: {e.text}")
                except Exception as e:
                    self.logger.error(f"Error refreshing roles: {e}", exc_info=True)
                    await ctx.send(f"❌ An error occurred: {str(e)}")

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
        self.update_member_roles(member)
        self.logger.debug(f"Added new member {member.display_name} to role cache for {member.guild.name}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Remove member from role cache when they leave"""
        if member.guild.id in self.member_roles:
            if member.id in self.member_roles[member.guild.id]:
                del self.member_roles[member.guild.id][member.id]
                self.mark_data_modified()
                self.logger.debug(f"Removed cached roles for {member.display_name} leaving {member.guild.name}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Build role cache when bot joins a new guild"""
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

    @rolecache_group.command(name="forcefetch")
    async def force_fetch(self, ctx: commands.Context) -> None:
        """Force a complete refresh using fetch_members"""
        async with self.task_tracker.task_context("Force Fetch", "Starting complete member fetch") as tracker:
            progress_msg = await ctx.send("Starting complete member fetch for all guilds...")

            for guild in self.bot.guilds:
                tracker.update_status(f"Fetching {guild.name}")
                await progress_msg.edit(content=f"Fetching {guild.name}...")

                try:
                    count = await self.build_cache(guild)
                    await ctx.send(f"✅ Fetched {count} members from {guild.name}")
                except Exception as e:
                    self.logger.error(f"Error fetching {guild.name}: {e}", exc_info=True)
                    await ctx.send(f"❌ Error fetching {guild.name}: {str(e)}")

            await progress_msg.edit(content="Complete member fetch finished!")

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

    @rolecache_group.command(name="refresh")
    async def refresh_command(self, ctx: commands.Context, target: Optional[discord.Member] = None) -> None:
        """Refresh role cache for a user or the entire server."""
        if not ctx.guild:
            return await ctx.send("This command must be used in a server.")

        # Defer response for potentially long operation
        await ctx.defer()

        async with self.task_tracker.task_context("Manual Refresh") as tracker:
            if target:
                tracker.update_status(f"Refreshing roles for {target.display_name}")
                self.update_member_roles(target)
                await ctx.send(f"✅ Refreshed roles for {target.display_name}")
            else:
                total_members = len(ctx.guild.members)
                message = await ctx.send(f"🔄 Refreshing roles for all members in {ctx.guild.name}...")

                try:
                    for i, member in enumerate(ctx.guild.members, 1):
                        tracker.update_status(f"Processing member {i}/{total_members}")
                        self.update_member_roles(member)

                        if i % 100 == 0:  # Update progress every 100 members
                            try:
                                await message.edit(content=f"🔄 Refreshing roles: {i}/{total_members} members processed...")
                            except discord.NotFound:
                                # Message was deleted, create new one
                                message = await ctx.send(f"🔄 Refreshing roles: {i}/{total_members} members processed...")

                    await message.edit(content=f"✅ Refreshed roles for all {total_members} members in {ctx.guild.name}")
                    await self.save_data_if_modified(self.member_roles, self.cache_file, force=True)

                except discord.Forbidden:
                    await ctx.send("❌ I don't have permission to manage roles in this server.")
                except discord.HTTPException as e:
                    if e.status == 429:  # Rate limited
                        await ctx.send(f"⚠️ Rate limited by Discord. Please try again in {e.retry_after:.1f} seconds.")
                    else:
                        await ctx.send(f"❌ Discord API error: {e.text}")
                except Exception as e:
                    self.logger.error(f"Error refreshing roles: {e}", exc_info=True)
                    await ctx.send(f"❌ An error occurred: {str(e)}")

    @rolecache_group.command(name="lookup")
    async def lookup_command(self, ctx, member: discord.Member):
        """Look up cached roles for a member

        Args:
            member: The member to look up roles for
        """
        if not ctx.guild:
            return await ctx.send("This command must be used in a server.")

        guild_id = ctx.guild.id
        user_id = member.id

        if guild_id not in self.member_roles or user_id not in self.member_roles[guild_id]:
            return await ctx.send(f"❌ No cached roles found for {member.display_name}")

        # Get cached data
        cache_data = self.member_roles[guild_id][user_id]
        role_ids = cache_data["roles"]
        updated_at = datetime.datetime.fromtimestamp(cache_data["updated_at"], tz=datetime.timezone.utc)

        # Calculate how old the cache is
        now = datetime.datetime.now(datetime.timezone.utc)
        cache_age = now - updated_at

        # Create embed
        embed = discord.Embed(
            title=f"Cached Roles for {member.display_name}",
            color=discord.Color.blue()
        )

        # Get role names from IDs
        role_names = []
        for role_id in role_ids:
            role = ctx.guild.get_role(role_id)
            if role:
                role_names.append(f"{role.name}")

        # Format embed fields
        embed.add_field(
            name="Roles",
            value="\n".join(role_names) if role_names else "No roles",
            inline=False
        )

        # Add information about cache freshness
        hours, remainder = divmod(int(cache_age.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        age_str = f"{hours}h {minutes}m {seconds}s ago"

        embed.add_field(name="Last Updated", value=f"{updated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n({age_str})", inline=False)

        # Add indicator if cache is stale
        if self.is_stale(guild_id, user_id):
            embed.add_field(name="Status", value="⚠️ Stale cache", inline=False)
            embed.color = discord.Color.orange()
        else:
            embed.add_field(name="Status", value="✅ Cache is fresh", inline=False)

        await ctx.send(embed=embed)

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
        await bot.add_cog(RoleCache(bot))
        bot.logger.info("Successfully loaded RoleCache cog")
    except Exception as e:
        bot.logger.error(f"Failed to load RoleCache cog: {e}", exc_info=True)
        raise
