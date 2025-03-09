import asyncio
import json
import logging
import datetime
import concurrent.futures
from fish_bot.basecog import BaseCog
import discord
from discord.ext import commands
from pathlib import Path


class RoleCache(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)  # Initialize the BaseCog

        # Role cache storage with timestamps
        # {guild_id: {user_id: {"roles": [role_ids], "updated_at": timestamp}}}
        self.member_roles = {}

        # Create an event that signals when cache is ready
        self._cache_ready = asyncio.Event()

        # Flag to track if changes need to be saved
        self._cache_modified = False

        # Lock for save operations to prevent race conditions
        self._save_lock = asyncio.Lock()

        # Store a reference to this cog on the bot for easy access
        self.bot.role_cache = self

        # Configure cache settings from stored settings
        self.staleness_threshold = self.get_setting('staleness_threshold', 3600)
        self.refresh_interval = self.get_setting('refresh_interval', 1800)
        self.save_interval = self.get_setting('save_interval', 3600)  # Default to 1 hour if not set

        self.logger = logging.getLogger(__name__)
        self.logger.info(f"RoleCache initialized with refresh_interval={self.refresh_interval}s, "
                         f"staleness_threshold={self.staleness_threshold}s, "
                         f"save_interval={self.save_interval}s")

        # Try to load existing cache from file
        self.load_cache_from_file()

        # Start building cache after bot is ready
        self.bot.loop.create_task(self._build_initial_cache())

        # Start periodic refresh task
        self.refresh_task = self.bot.loop.create_task(self.periodic_refresh())

        # Start periodic save task (separate from refresh)
        self.save_task = self.bot.loop.create_task(self.periodic_save())

    @property
    def cache_file(self) -> Path:
        """Get the cache file path using the cog's data directory"""
        cache_filename = self.get_setting('cache_filename', 'role_cache.json')
        return self.data_directory / cache_filename

    # Add a command to modify settings
    @commands.group(name="rolecache", aliases=["rc"], invoke_without_command=True)
    async def rolecache_group(self, ctx):
        """Commands for managing the role cache"""
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

            # Format confirmation message with time breakdown
            hours = value // 3600
            minutes = (value % 3600) // 60
            seconds = value % 60
            time_format = f"{hours}h {minutes}m {seconds}s"
            await ctx.send(f"✅ Set {setting_name} to {value} seconds ({time_format})")

    @rolecache_group.command(name="rolestats")
    async def role_stats_command(self, ctx, *, role_name=None):
        """Show member counts for roles

        If no role name is provided, shows counts for all roles.
        Role name can be partial - will match any role containing the text.
        """
        if not ctx.guild:
            await ctx.send("This command can only be used in a server.")
            return

        guild_id = ctx.guild.id
        if guild_id not in self.member_roles:
            await ctx.send("No role cache data available for this server.")
            return

        # Build role counts from cache
        role_counts = {}
        for user_id, user_data in self.member_roles[guild_id].items():
            for role_id in user_data.get("roles", []):
                if role_id not in role_counts:
                    role_counts[role_id] = 0
                role_counts[role_id] += 1

        # Get role objects from the guild
        guild_roles = {role.id: role for role in ctx.guild.roles}

        # If a specific role is requested, filter the results
        if role_name:
            matching_roles = {
                rid: role for rid, role in guild_roles.items()
                if role_name.lower() in role.name.lower()
            }

            if not matching_roles:
                await ctx.send(f"No roles found matching '{role_name}'")
                return

            # Show only matching roles
            lines = []
            for role_id, role in matching_roles.items():
                count = role_counts.get(role_id, 0)
                lines.append(f"**{role.name}**: {count} members")

            # Split into chunks if too long
            chunks = []
            current_chunk = []
            for line in lines:
                if len("\n".join(current_chunk + [line])) > 1900:  # Discord message limit buffer
                    chunks.append("\n".join(current_chunk))
                    current_chunk = [line]
                else:
                    current_chunk.append(line)
            if current_chunk:
                chunks.append("\n".join(current_chunk))

            # Send results
            for i, chunk in enumerate(chunks):
                header = f"**Role Stats** (Matching '{role_name}')" if i == 0 else ""
                await ctx.send(f"{header}\n{chunk}")
        else:
            # Show all roles, sorted by count
            sorted_roles = sorted(
                [(guild_roles.get(rid), count) for rid, count in role_counts.items() if rid in guild_roles],
                key=lambda x: x[1],
                reverse=True
            )

            # Generate chunks to stay within Discord message limits
            chunks = []
            current_chunk = []
            for role, count in sorted_roles:
                if not role:  # Skip roles that don't exist anymore
                    continue
                line = f"**{role.name}**: {count} members"
                if len("\n".join(current_chunk + [line])) > 1900:  # Discord message limit buffer
                    chunks.append("\n".join(current_chunk))
                    current_chunk = [line]
                else:
                    current_chunk.append(line)
            if current_chunk:
                chunks.append("\n".join(current_chunk))

            # Send results
            for i, chunk in enumerate(chunks):
                header = "**All Role Stats**" if i == 0 else "**All Role Stats** (Continued)"
                await ctx.send(f"{header}\n{chunk}")

    def load_cache_from_file(self):
        """Load the role cache from file if it exists"""
        try:
            cache_path = self.cache_file
            if cache_path.exists():
                with open(cache_path, 'r') as f:
                    cache_data = json.load(f)

                # Convert string keys to integers for guild_id and user_id
                self.member_roles = {}
                for guild_id_str, guild_data in cache_data.items():
                    guild_id = int(guild_id_str)
                    self.member_roles[guild_id] = {}
                    for user_id_str, user_data in guild_data.items():
                        user_id = int(user_id_str)
                        self.member_roles[guild_id][user_id] = user_data

                self.logger.info(f"Loaded role cache from {cache_path}")
                return True
        except Exception as e:
            self.logger.error(f"Failed to load role cache from file: {str(e)}")

        return False

    def mark_modified(self):
        """Mark the cache as modified, needing to be saved"""
        self._cache_modified = True

    async def save_cache_to_file(self, force=False):
        """Save the current role cache to file if modified or forced"""
        # Skip saving if nothing has changed and not forced
        if not force and not self._cache_modified:
            return True

        # Use a lock to prevent multiple simultaneous saves
        async with self._save_lock:
            try:
                # Ensure directory exists
                cache_path = self.cache_file
                cache_path.parent.mkdir(parents=True, exist_ok=True)

                with open(cache_path, 'w') as f:
                    json.dump(self.member_roles, f)

                self._cache_modified = False  # Reset modified flag
                self.logger.info(f"Saved role cache to {cache_path}")
                return True
            except Exception as e:
                self.logger.error(f"Failed to save role cache to file: {str(e)}")
                return False

    async def periodic_save(self):
        """Periodically save the cache to file"""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(self.save_interval)  # Use dedicated save interval
            await self.save_cache_to_file()  # Only saves if modified

    async def _build_initial_cache(self):
        """Build role cache for all guilds after bot is ready"""
        await self.bot.wait_until_ready()
        self.logger.info("Building initial role cache...")

        # Only build cache for primary guild if we don't already have data for it
        if self.guild.id not in self.member_roles or not self.member_roles.get(self.guild.id):
            self.logger.info(f"No cached data found for {self.guild.name}. Building fresh cache...")
            await self.build_cache(self.guild)
        else:
            self.logger.info(f"Using cached data for {self.guild.name} with {len(self.member_roles[self.guild.id])} members")
            # Optionally refresh stale entries
            await self.refresh_stale_roles()

        self.logger.info("Role cache is ready")
        self._cache_ready.set()

        # Save the cache to file if we built a new one
        if self.guild.id not in self.member_roles:
            await self.save_cache_to_file()

    async def build_cache(self, guild):
        """Cache roles for a specific guild"""
        if not guild:
            self.logger.warning("Attempted to build cache for None guild")
            return

        self.member_roles[guild.id] = {}
        for member in guild.members:
            self.update_member_roles(member)

        self.logger.info(f"Built role cache for {guild.name} with {len(guild.members)} members")

    async def wait_until_ready(self):
        """Wait until the cache is fully built - other cogs can call this"""
        await self._cache_ready.wait()

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
        self._cache_modified = True

    def has_role(self, guild_id, user_id, role_id):
        """Check if user has role from cache"""
        user_data = self.member_roles.get(guild_id, {}).get(user_id, {})
        return role_id in user_data.get("roles", [])

    def get_roles(self, guild_id, user_id):
        """Get all cached roles for a user"""
        user_data = self.member_roles.get(guild_id, {}).get(user_id, {})
        return user_data.get("roles", [])

    def is_stale(self, guild_id, user_id):
        """Check if a user's role cache is stale"""
        user_data = self.member_roles.get(guild_id, {}).get(user_id, {})
        if not user_data:
            return True

        last_updated = user_data.get("updated_at", 0)
        current_time = datetime.datetime.now(datetime.timezone.utc).timestamp()
        return (current_time - last_updated) > self.staleness_threshold

    async def refresh_stale_roles(self):
        """Refresh roles for users whose cache is stale"""
        self.logger.info("Refreshing stale role caches...")
        refreshed_count = 0

        for guild in self.bot.guilds:
            for member in guild.members:
                if self.is_stale(guild.id, member.id):
                    self.update_member_roles(member)
                    refreshed_count += 1

        if refreshed_count > 0:
            self.logger.info(f"Refreshed roles for {refreshed_count} members")
            # No need to explicitly save here - will be saved by periodic_save

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
                self.mark_modified()  # Mark cache as modified

        if removed_count > 0:
            self.logger.info(f"Cleaned up {removed_count} cached entries for members no longer in guilds")
            # No need to explicitly save here - will be saved by periodic_save

        return removed_count

    async def periodic_refresh(self):
        """Periodically refresh stale role entries and clean up missing members"""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(self.refresh_interval)
            await self.refresh_stale_roles()

            # Run cleanup every few refresh cycles using explicit UTC time
            current_time = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
            if current_time % (self.refresh_interval * 3) < self.refresh_interval:
                await self.cleanup_missing_members()

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles != after.roles:
            self.update_member_roles(after)
            self.logger.debug(f"Updated roles for {after.display_name} in {after.guild.name}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        self.update_member_roles(member)
        self.logger.debug(f"Cached roles for new member {member.display_name} in {member.guild.name}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if member.guild.id in self.member_roles:
            if member.id in self.member_roles[member.guild.id]:
                del self.member_roles[member.guild.id][member.id]
                self.mark_modified()  # Mark as modified instead of saving
                self.logger.debug(f"Removed cached roles for {member.display_name} leaving {member.guild.name}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.build_cache(guild)
        self.logger.info(f"Built role cache for new guild: {guild.name}")
        # Force save after adding a new guild
        await self.save_cache_to_file(force=True)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Remove guild data from cache when bot leaves a guild"""
        if guild.id in self.member_roles:
            # Store number of members for logging
            members_count = len(self.member_roles[guild.id])

            # Remove the guild data
            del self.member_roles[guild.id]
            self.mark_modified()  # Mark as modified

            self.logger.info(f"Removed role cache for departed guild: {guild.name} ({members_count} members)")

    # Refresh stale roles on reconnect instead of rebuilding entire cache
    async def on_reconnect(self):
        await super().on_reconnect()  # Call the parent method first
        self.logger.info("Refreshing stale roles after reconnect")
        await self.refresh_stale_roles()

    def cog_unload(self):
        """Called when the cog is unloaded. Ensures data is saved."""
        # Cancel the background tasks first
        if hasattr(self, 'refresh_task'):
            self.refresh_task.cancel()
        if hasattr(self, 'save_task'):
            self.save_task.cancel()

        # Force a synchronous save
        loop = asyncio.get_event_loop()
        if self._cache_modified and loop.is_running():
            # We're in an async context, run the save coroutine
            future = asyncio.run_coroutine_threadsafe(
                self.save_cache_to_file(force=True),
                loop
            )
            try:
                # Wait for a short time to allow save to complete
                future.result(timeout=5)
                self.logger.info("Role cache saved during cog unload")
            except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
                self.logger.warning("Timed out while saving role cache during unload")
            except Exception as e:
                self.logger.error(f"Error saving role cache during unload: {e}")
        else:
            # We can't run the coroutine, log a warning
            self.logger.warning("Could not save role cache during unload - no running event loop")

        self.logger.info("Role cache unloaded")


async def setup(bot):
    await bot.add_cog(RoleCache(bot))
