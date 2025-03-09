import asyncio
import json
import logging
import datetime
from fish_bot.basecog import BaseCog
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

        # Store a reference to this cog on the bot for easy access
        self.bot.role_cache = self

        # Setup default settings if they don't exist yet
        if not self.has_setting('refresh_interval'):
            self.update_settings({
                'refresh_interval': 1800,  # 30 minutes in seconds
                'staleness_threshold': 3600,  # 1 hour in seconds
                'cache_filename': 'role_cache.json'
            })

        # Configure cache settings from stored settings
        self.staleness_threshold = self.get_setting('staleness_threshold')
        self.refresh_interval = self.get_setting('refresh_interval')

        self.logger = logging.getLogger(__name__)
        self.logger.info(f"RoleCache initialized with refresh_interval={self.refresh_interval}s, "
                         f"staleness_threshold={self.staleness_threshold}s")

        # Try to load existing cache from file
        self.load_cache_from_file()

        # Start building cache after bot is ready
        self.bot.loop.create_task(self._build_initial_cache())

        # Start periodic refresh task
        self.refresh_task = self.bot.loop.create_task(self.periodic_refresh())

        # Start periodic save task
        self.save_task = self.bot.loop.create_task(self.periodic_save())

    @property
    def cache_file(self) -> Path:
        """Get the cache file path using the cog's data directory"""
        cache_filename = self.get_setting('cache_filename')
        return self.data_directory / cache_filename

    # Add a command to modify settings
    @commands.group(name="rolecache")
    async def rolecache_group(self, ctx):
        """Commands for managing the role cache"""
        if ctx.invoked_subcommand is None:
            settings = self.get_all_settings()
            settings_str = "\n".join(f"• {k}: {v}" for k, v in settings.items())
            await ctx.send(f"**Role Cache Settings:**\n{settings_str}")

    @rolecache_group.command(name="set")
    async def set_setting_command(self, ctx, setting_name: str, value: int):
        """Change a role cache setting

        Valid settings: refresh_interval, staleness_threshold
        Values are in seconds
        """
        if setting_name not in ['refresh_interval', 'staleness_threshold']:
            await ctx.send("Invalid setting name. Valid options: refresh_interval, staleness_threshold")
            return

        self.set_setting(setting_name, value)

        # Update instance variables
        if setting_name == 'refresh_interval':
            self.refresh_interval = value
        elif setting_name == 'staleness_threshold':
            self.staleness_threshold = value

        await ctx.send(f"✅ Set {setting_name} to {value} seconds")

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

    async def save_cache_to_file(self):
        """Save the current role cache to file"""
        try:
            # Ensure directory exists
            cache_path = self.cache_file
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            with open(cache_path, 'w') as f:
                json.dump(self.member_roles, f)

            self.logger.info(f"Saved role cache to {cache_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save role cache to file: {str(e)}")
            return False

    async def periodic_save(self):
        """Periodically save the cache to file"""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(self.refresh_interval)  # Save at the same interval as refresh
            await self.save_cache_to_file()

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

        self.logger.info(f"Refreshed roles for {refreshed_count} members")

        # Save cache after refreshing
        if refreshed_count > 0:
            await self.save_cache_to_file()

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

        if removed_count > 0:
            self.logger.info(f"Cleaned up {removed_count} cached entries for members no longer in guilds")
            await self.save_cache_to_file()

        return removed_count

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
                self.logger.debug(f"Removed cached roles for {member.display_name} leaving {member.guild.name}")
                # Save cache after removing a member
                self.bot.loop.create_task(self.save_cache_to_file())

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.build_cache(guild)
        self.logger.info(f"Built role cache for new guild: {guild.name}")
        # Save cache after adding a new guild
        await self.save_cache_to_file()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Remove guild data from cache when bot leaves a guild"""
        if guild.id in self.member_roles:
            # Store number of members for logging
            members_count = len(self.member_roles[guild.id])

            # Remove the guild data
            del self.member_roles[guild.id]

            self.logger.info(f"Removed role cache for departed guild: {guild.name} ({members_count} members)")

            # Save cache after removing guild data
            await self.save_cache_to_file()

    # Refresh stale roles on reconnect instead of rebuilding entire cache
    async def on_reconnect(self):
        await super().on_reconnect()  # Call the parent method first
        self.logger.info("Refreshing stale roles after reconnect")
        await self.refresh_stale_roles()


async def setup(bot):
    await bot.add_cog(RoleCache(bot))
