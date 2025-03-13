import asyncio
import json
import logging
import datetime
from fish_bot.basecog import BaseCog
import discord
from discord.ext import commands
from pathlib import Path
from collections import deque


class RoleCache(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)  # Initialize the BaseCog

        # Role cache storage with timestamps
        # {guild_id: {user_id: {"roles": [role_ids], "updated_at": timestamp}}}
        self.member_roles = {}

        # Track which guilds are currently being fetched
        self._fetching_guilds = set()

        # Queue for role updates during fetching
        self._update_queues = {}  # {guild_id: deque()}

        # Store a reference to this cog on the bot for easy access
        self.bot.role_cache = self

        # Set default settings if they don't exist
        if not self.has_setting("refresh_interval"):
            self.set_setting("refresh_interval", 1800)  # 30 minutes

        if not self.has_setting("staleness_threshold"):
            self.set_setting("staleness_threshold", 3600)  # 1 hour

        if not self.has_setting("save_interval"):
            self.set_setting("save_interval", 3600)  # 1 hour by default

        # Configure cache settings from stored settings
        self.staleness_threshold = self.get_setting('staleness_threshold')
        self.refresh_interval = self.get_setting('refresh_interval')
        self.save_interval = self.get_setting('save_interval')

        self.logger = logging.getLogger(__name__)
        self.logger.info(f"RoleCache initialized with refresh_interval={self.refresh_interval}s, "
                         f"staleness_threshold={self.staleness_threshold}s, "
                         f"save_interval={self.save_interval}s")

        # Try to load existing cache from file
        self.load_cache_from_file()

    async def cog_initialize(self):
        """Initialize the cog - called by BaseCog during ready process"""
        # Build the initial cache
        await self._build_initial_cache()

        # Start periodic refresh task
        self.refresh_task = self.bot.loop.create_task(self.periodic_refresh())

        # Start periodic save task using BaseCog's functionality
        self.save_task = await self.create_periodic_save_task(
            data=self.member_roles,
            file_path=self.cache_file,
            save_interval=self.save_interval
        )

        self.logger.info("RoleCache initialization complete")

    @property
    def cache_file(self) -> Path:
        """Get the cache file path using the cog's data directory"""
        cache_filename = self.get_setting('cache_filename', 'role_cache.json')
        return self.data_directory / cache_filename

    def load_cache_from_file(self):
        """Load role cache from file."""
        try:
            cache_file = self.cache_file
            if not cache_file.exists():
                self.logger.info("No role cache file found, starting with empty cache")
                return

            with open(cache_file, 'r') as f:
                self.member_roles = json.load(f)

            self.logger.info(f"Loaded role cache from {cache_file}")
        except Exception as e:
            self.logger.error(f"Failed to load role cache: {e}")
            # Start with empty cache on error
            self.member_roles = {}

    async def _build_initial_cache(self):
        """Build the initial role cache for all guilds"""
        self.logger.info("Building initial role cache...")

        total_members = 0
        for guild in self.bot.guilds:
            guild_members = await self.build_cache(guild)
            total_members += guild_members

        self.logger.info(f"Initial role cache built with {total_members} members across {len(self.bot.guilds)} guilds")

    async def get_all_members(self, guild):
        """Fetch all members from a guild using the async iterator."""
        members = []
        async for member in guild.fetch_members(limit=None):
            members.append(member)
        return members

    async def build_cache(self, guild):
        """Build role cache for a specific guild using fetch_members for completeness"""
        if guild.id not in self.member_roles:
            self.member_roles[guild.id] = {}

        # Mark that we're fetching this guild and create an update queue
        self._fetching_guilds.add(guild.id)
        self._update_queues[guild.id] = deque()

        self.logger.info(f"Fetching all members for {guild.name} (ID: {guild.id})")

        try:
            # Fetch all members using fetch_members for complete data
            members = await self.get_all_members(guild)
            count = len(members)

            # Build the cache from fetched members
            for member in members:
                self.update_member_roles(member)

            # Process any role updates that happened during fetching
            updates_count = len(self._update_queues[guild.id])
            if updates_count > 0:
                self.logger.info(f"Processing {updates_count} queued role updates for {guild.name}")

            while self._update_queues[guild.id]:
                member = self._update_queues[guild.id].popleft()
                self.update_member_roles(member)

            self.logger.info(f"Built role cache for {count} members in {guild.name} (including {updates_count} updates during fetch)")

        except Exception as e:
            self.logger.error(f"Error fetching members for {guild.name}: {e}", exc_info=True)
            # Fall back to using guild.members if fetch_members fails
            self.logger.info(f"Falling back to cached members for {guild.name}")
            count = 0
            for member in guild.members:
                self.update_member_roles(member)
                count += 1
            self.logger.info(f"Built role cache with fallback method for {count} members in {guild.name}")
        finally:
            # Clean up
            self._fetching_guilds.remove(guild.id)
            del self._update_queues[guild.id]

        return count

    async def periodic_refresh(self):
        """Periodically refresh stale roles and clean up missing members"""
        await self.wait_until_ready()  # Wait for cog initialization to complete using BaseCog method

        while not self.bot.is_closed():
            try:
                await self.refresh_stale_roles()
                await self.cleanup_missing_members()
            except Exception as e:
                self.logger.error(f"Error in periodic refresh: {e}", exc_info=True)

            # Sleep between refresh cycles
            await asyncio.sleep(self.refresh_interval)

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

        # Format confirmation message
        hours = value // 3600
        minutes = (value % 3600) // 60
        seconds = value % 60
        time_format = f"{hours}h {minutes}m {seconds}s"
        await ctx.send(f"✅ Set {setting_name} to {value} seconds ({time_format})")

        self.logger.info(f"Settings changed: {setting_name} set to {value} by {ctx.author}")

    @rolecache_group.command(name="stats")
    async def cache_stats_command(self, ctx):
        """Show statistics about the role cache"""
        embed = discord.Embed(
            title="Role Cache Statistics",
            color=discord.Color.blue()
        )

        # Calculate statistics
        guild_count = len(self.member_roles)
        total_members = sum(len(guild_data) for guild_data in self.member_roles.values())

        # Count stale entries
        stale_count = 0
        for guild_id, members in self.member_roles.items():
            for member_id, data in members.items():
                if self.is_stale(guild_id, member_id):
                    stale_count += 1

        # Add fields to embed
        embed.add_field(name="Guilds Cached", value=str(guild_count), inline=True)
        embed.add_field(name="Members Cached", value=str(total_members), inline=True)
        embed.add_field(name="Stale Entries", value=str(stale_count), inline=True)

        embed.add_field(name="Cache Status", value="Ready" if self.is_ready else "Building", inline=True)
        embed.add_field(name="Refresh Interval", value=f"{self.refresh_interval}s", inline=True)
        embed.add_field(name="Staleness Threshold", value=f"{self.staleness_threshold}s", inline=True)

        # Add cache file info
        cache_file = self.cache_file
        if cache_file.exists():
            size_kb = cache_file.stat().st_size / 1024
            modified = datetime.datetime.fromtimestamp(cache_file.stat().st_mtime)
            embed.add_field(
                name="Cache File",
                value=f"Size: {size_kb:.1f} KB\nLast Modified: {modified.strftime('%Y-%m-%d %H:%M:%S')}",
                inline=False
            )

        await ctx.send(embed=embed)

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

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Update role cache when member's roles change"""
        if before.roles != after.roles:
            guild_id = after.guild.id

            # If we're currently fetching this guild, queue the update
            if guild_id in self._fetching_guilds:
                self._update_queues[guild_id].append(after)
                self.logger.debug(f"Queued role update for {after.display_name} during fetching")
            else:
                # Otherwise process it immediately
                self.update_member_roles(after)
                self.logger.debug(f"Updated roles for {after.display_name} in {after.guild.name}")

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
        # Force save after adding a new guild
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

    # Refresh stale roles on reconnect instead of rebuilding entire cache
    async def on_reconnect(self):
        await super().on_reconnect()  # Call the parent method first
        self.logger.info("Refreshing stale roles after reconnect")
        await self.refresh_stale_roles()

    # Add listener for GUILD_MEMBERS_CHUNK for better debugging
    @commands.Cog.listener()
    async def on_guild_members_chunk(self, guild, members):
        """Log when receiving member chunks from Discord"""
        self.logger.debug(f"Received member chunk from Discord: {len(members)} members for {guild.name}")

    # Add command to force refresh using fetch_members
    @commands.command(name="forcefetch")
    async def force_fetch_command(self, ctx):
        """Force a complete refresh using fetch_members"""
        await ctx.send("Starting complete member fetch for all guilds...")

        for guild in self.bot.guilds:
            await ctx.send(f"Fetching {guild.name}...")
            try:
                count = await self.build_cache(guild)
                await ctx.send(f"✅ Fetched {count} members from {guild.name}")
            except Exception as e:
                await ctx.send(f"❌ Error fetching {guild.name}: {str(e)}")

        await ctx.send("Complete member fetch finished!")

    async def refresh_user_roles(self, guild_id, user_id):
        """Refresh roles for a specific user

        Args:
            guild_id: ID of the guild
            user_id: ID of the user to refresh

        Returns:
            bool: True if user was found and refreshed, False otherwise
        """
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
    async def refresh_command(self, ctx, target: discord.Member = None):
        """Refresh role cache for a user or the entire server

        Args:
            target: Optional member to refresh. If omitted, refreshes all members in the server.
        """
        if not ctx.guild:
            return await ctx.send("This command must be used in a server.")

        async with ctx.typing():
            if target:
                # Refresh a specific user
                self.update_member_roles(target)
                await ctx.send(f"✅ Refreshed roles for {target.display_name}")
            else:
                # Refresh all users in the guild
                message = await ctx.send(f"🔄 Refreshing roles for all members in {ctx.guild.name}...")

                # Track progress
                total_members = len(ctx.guild.members)
                processed = 0
                last_update = datetime.datetime.now()
                update_interval = datetime.timedelta(seconds=2)  # Update progress every 2 seconds

                for member in ctx.guild.members:
                    self.update_member_roles(member)
                    processed += 1

                    # Update progress message periodically
                    now = datetime.datetime.now()
                    if now - last_update > update_interval:
                        await message.edit(content=f"🔄 Refreshing roles: {processed}/{total_members} members processed...")
                        last_update = now

                await message.edit(content=f"✅ Refreshed roles for all {total_members} members in {ctx.guild.name}")

                # Save the cache immediately after a full refresh
                await self.save_data_if_modified(self.member_roles, self.cache_file, force=True)
                self.logger.info(f"Manual refresh completed for {ctx.guild.name} by {ctx.author}")

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


async def setup(bot):
    await bot.add_cog(RoleCache(bot))
