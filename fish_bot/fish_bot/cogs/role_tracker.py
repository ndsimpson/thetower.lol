import discord
from discord.ext import commands, tasks
import logging
import asyncio
import datetime
import pickle
from typing import Dict, List, Set
from asgiref.sync import sync_to_async

from fish_bot.basecog import BaseCog
from dtower.sus.models import KnownPlayer

# Set up logging
logger = logging.getLogger(__name__)


class TrackedMember:
    """Class to store information about a tracked Discord member."""

    def __init__(self, discord_id: int, player_id: str = None, name: str = None):
        self.discord_id = discord_id
        self.player_id = player_id
        self.name = name


class RoleTracker(BaseCog, name="Role Tracker"):
    """Tracks roles for known players from the database.

    Monitors and updates role information for Discord users
    that are registered as known players in the database.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.tracked_members: Dict[int, TrackedMember] = {}  # discord_id -> TrackedMember
        self.tracked_roles: Set[int] = set()  # Role IDs we're interested in (for fast lookup)
        self.tracked_roles_ordered: List[int] = []  # Role IDs in order from config (for display)
        self.data_file = self.data_directory / "role_tracker_data.pkl"
        self._role_cache = None

        # Load tracked roles
        self.load_tracked_roles()

        # Load any previously saved member data
        self.load_data()

        # Schedule the initial data loading if needed
        if not self.tracked_members:
            self.bot.loop.create_task(self.load_known_players())

        # Initialize role cache access
        self.bot.loop.create_task(self._initialize_role_cache())

    async def _initialize_role_cache(self):
        """Wait for role cache to become available"""
        await self.bot.wait_until_ready()

        while self._role_cache is None:
            self._role_cache = self.bot.get_cog('RoleCache')
            if self._role_cache is not None:
                await self._role_cache.wait_until_ready()
                logger.info("RoleCache is now available to RoleTracker")
                return
            await asyncio.sleep(1)

    async def _ensure_role_cache(self):
        """Ensure role cache is available before using it"""
        if self._role_cache is None:
            # Immediately check if it's available now
            self._role_cache = self.bot.get_cog('RoleCache')
            if self._role_cache is None:
                # If not available, log a warning and return False
                logger.warning("Role cache not available")
                return False
            # Make sure it's ready before proceeding
            await self._role_cache.wait_until_ready()
        return True

    def has_role(self, guild_id, user_id, role_id):
        """Check if user has role using RoleCache if available, otherwise fallback"""
        if hasattr(self.bot, 'role_cache') and self.bot.role_cache:
            return self.bot.role_cache.has_role(guild_id, user_id, role_id)
        return False

    def get_roles(self, guild_id, user_id):
        """Get all roles for a user using RoleCache if available"""
        if hasattr(self.bot, 'role_cache') and self.bot.role_cache:
            return self.bot.role_cache.get_roles(guild_id, user_id)
        return []

    def cog_unload(self):
        """Called when the cog is unloaded."""
        self.refresh_player_data.cancel()
        self.save_data()
        logger.info("Role tracker unloaded, data saved.")

    def load_tracked_roles(self):
        """Load the role IDs we want to track from rankings configuration."""
        # Clear existing tracked roles
        self.tracked_roles.clear()
        self.tracked_roles_ordered.clear()

        # Get legend rankings
        legend_ranks = self.config.get("rankings", {}).get("legend", {})
        # Track top1 separately as it's a special case
        self.top1_role_id = None
        for rank_name, role_id in legend_ranks.items():
            if role_id:
                if rank_name == "top1":
                    self.top1_role_id = role_id
                self.tracked_roles.add(role_id)
                self.tracked_roles_ordered.append(role_id)
                logger.info(f"Tracking legend rank {rank_name} ({role_id})")

        # Get other league rankings
        other_leagues = self.config.get("rankings", {}).get("other_leagues", {})
        for rank_name, role_id in other_leagues.items():
            if role_id:
                self.tracked_roles.add(role_id)
                self.tracked_roles_ordered.append(role_id)
                logger.info(f"Tracking league rank {rank_name} ({role_id})")

        # Also track verified role
        verified_role_id = self.config.get_role_id("verified")
        if verified_role_id:
            self.tracked_roles.add(verified_role_id)
            self.tracked_roles_ordered.append(verified_role_id)
            logger.info(f"Tracking verified role ({verified_role_id})")

        logger.info(f"Total tracked roles: {len(self.tracked_roles)}")

    @tasks.loop(hours=24)
    async def refresh_player_data(self):
        """Periodically refresh player data from the database."""
        await self.load_known_players()

    @refresh_player_data.before_loop
    async def before_refresh_player_data(self):
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()

    async def load_known_players(self, ctx=None, status_message=None):
        """Load known players from the database and fetch their Discord roles efficiently."""
        logger.info("Loading known players from database...")
        try:
            # Use sync_to_async to perform database operations asynchronously
            players = await sync_to_async(list)(KnownPlayer.objects.filter(discord_id__isnull=False).exclude(discord_id=''))

            logger.info(f"Found {len(players)} players with Discord IDs in database")
            if ctx and status_message:
                await status_message.edit(content=f"Found {len(players)} players with Discord IDs in database. Processing...")

            # Clear existing tracked members
            self.tracked_members.clear()

            # Temporary dict to store players by discord_id
            players_by_discord_id = {}
            valid_discord_ids = []

            # First pass: Process database data without Discord API calls
            for player in players:
                try:
                    discord_id = int(player.discord_id)

                    # Get the primary player ID if available
                    primary_id = await sync_to_async(lambda p=player: p.ids.filter(primary=True).first())()
                    player_id = primary_id.id if primary_id else None

                    if player_id:
                        # Create a TrackedMember object without roles yet
                        member = TrackedMember(discord_id, player_id, player.name)
                        players_by_discord_id[discord_id] = member
                        valid_discord_ids.append(discord_id)
                except ValueError:
                    logger.warning(f"Invalid discord_id for player {player.name}: {player.discord_id}")
                except Exception as e:
                    logger.error(f"Error processing player {player.name}: {e}")

            if not valid_discord_ids:
                logger.warning("No valid Discord IDs found")
                if ctx and status_message:
                    await status_message.edit(content="No valid Discord IDs found in database.")
                return

            # Fetch the guild object
            guild = self.bot.get_guild(self.config.get_guild_id())
            if not guild:
                logger.error("Could not find guild")
                if ctx and status_message:
                    await status_message.edit(content="Error: Could not find Discord guild.")
                return

            # Second pass: Fetch members in bulk where possible
            start_message = f"Starting bulk fetch of {len(valid_discord_ids)} Discord members"
            logger.info(start_message)
            if ctx and status_message:
                await status_message.edit(content=start_message)

            # Track progress
            total_members = len(valid_discord_ids)
            processed_members = 0
            successful_fetches = 0
            start_time = datetime.datetime.now()

            # Some Discord libraries support bulk member fetching, but if not available,
            # we'll chunk the requests to minimize API calls
            chunk_size = 100  # Adjust based on API limits
            total_chunks = (total_members + chunk_size - 1) // chunk_size

            last_update_chunk = 0  # Track when we last sent a channel update

            for i in range(0, len(valid_discord_ids), chunk_size):
                chunk = valid_discord_ids[i:i + chunk_size]
                chunk_num = i // chunk_size + 1
                chunk_start_time = datetime.datetime.now()

                logger.info(f"Fetching chunk {chunk_num}/{total_chunks} ({len(chunk)} members)")

                try:
                    # Try to use guild.query_members for bulk fetching if available
                    if hasattr(guild, 'query_members'):
                        members = await guild.query_members(user_ids=chunk)
                    else:
                        # Fall back to individual fetching but in a smaller batch
                        members = []
                        for idx, discord_id in enumerate(chunk):
                            try:
                                # Provide periodic updates within the chunk
                                if idx > 0 and idx % 10 == 0:
                                    logger.info(f"Progress: {idx}/{len(chunk)} members in current chunk")
                                    await asyncio.sleep(0)  # Allow other tasks to run

                                member = await guild.fetch_member(discord_id)
                                if member:
                                    members.append(member)
                            except discord.NotFound:
                                logger.warning(f"Discord member not found: {discord_id}")
                            except Exception as e:
                                logger.error(f"Error fetching member {discord_id}: {e}")

                    # Process the fetched members
                    fetch_count = len(members)
                    successful_fetches += fetch_count
                    processed_members += len(chunk)

                    for member in members:
                        if member.id in players_by_discord_id:
                            tracked_member = players_by_discord_id[member.id]
                            tracked_member.update_roles(member.roles)
                            self.tracked_members[member.id] = tracked_member

                    # Log progress after each chunk
                    chunk_time = datetime.datetime.now() - chunk_start_time
                    logger.info(f"Chunk {chunk_num}/{total_chunks} completed: {fetch_count}/{len(chunk)} members fetched in {chunk_time.total_seconds():.1f}s")
                    logger.info(f"Overall progress: {processed_members}/{total_members} processed, {successful_fetches} successful")

                    # Calculate estimated time remaining
                    elapsed = datetime.datetime.now() - start_time
                    if processed_members > 0:
                        time_per_member = elapsed.total_seconds() / processed_members
                        remaining_members = total_members - processed_members
                        est_remaining = datetime.timedelta(seconds=time_per_member * remaining_members)
                        logger.info(f"Estimated time remaining: {est_remaining}")

                    # Send update to channel every 10 chunks or on last chunk
                    if ctx and status_message and (chunk_num - last_update_chunk >= 10 or chunk_num == total_chunks):
                        progress_percent = (processed_members / total_members) * 100
                        update_msg = (
                            f"Progress: {processed_members}/{total_members} members processed ({progress_percent:.1f}%)\n"
                            f"Successful fetches: {successful_fetches}\n"
                        )

                        if est_remaining:
                            update_msg += f"Time elapsed: {elapsed}, estimated time remaining: {est_remaining}"

                        await status_message.edit(content=update_msg)
                        last_update_chunk = chunk_num

                except Exception as e:
                    logger.error(f"Error fetching members batch: {e}")

            total_time = datetime.datetime.now() - start_time
            logger.info(f"Bulk fetch completed: {successful_fetches}/{total_members} members fetched in {total_time}")
            logger.info(f"Successfully loaded {len(self.tracked_members)} known players with Discord data")

            # Final update to channel if using the command
            if ctx and status_message:
                await status_message.edit(
                    content=f"✅ Bulk fetch completed: {successful_fetches}/{total_members} members fetched in {total_time}.\n"
                    f"Total tracked members: {len(self.tracked_members)}"
                )

            # Save the updated data
            self.save_data()

        except Exception as e:
            logger.error(f"Failed to load known players: {e}")
            if ctx and status_message:
                await status_message.edit(content=f"❌ Error: {str(e)}")

    async def update_member_roles(self, tracked_member: TrackedMember):
        """Update the roles for a tracked member."""
        try:
            # Fetch the guild from the bot
            guild = self.guild
            if not guild:
                logger.error("Could not find guild")
                return

            # Fetch the member
            member = await guild.fetch_member(tracked_member.discord_id)
            if not member:
                logger.warning(f"Could not find Discord member for {tracked_member.name} ({tracked_member.discord_id})")
                return

            # Update roles
            tracked_member.update_roles(member.roles)
            logger.debug(f"Updated roles for {tracked_member.name} ({tracked_member.discord_id})")
        except discord.NotFound:
            logger.warning(f"Discord member not found: {tracked_member.discord_id}")
        except discord.HTTPException as e:
            logger.error(f"HTTP error fetching member {tracked_member.discord_id}: {e}")
        except Exception as e:
            logger.error(f"Error updating roles for {tracked_member.discord_id}: {e}")

    def save_data(self):
        """Save tracked members data to a pickle file."""
        try:
            # Ensure the directory exists
            self.data_file.parent.mkdir(parents=True, exist_ok=True)

            # Save the data
            with open(self.data_file, 'wb') as f:
                pickle.dump(self.tracked_members, f)

            logger.info(f"Saved {len(self.tracked_members)} tracked members to {self.data_file}")
        except Exception as e:
            logger.error(f"Failed to save tracked members data: {e}")

    def load_data(self):
        """Load tracked members data from a pickle file."""
        try:
            if self.data_file.exists():
                with open(self.data_file, 'rb') as f:
                    self.tracked_members = pickle.load(f)

                logger.info(f"Loaded {len(self.tracked_members)} tracked members from {self.data_file}")
            else:
                logger.info(f"No saved data file found at {self.data_file}")
        except Exception as e:
            logger.error(f"Failed to load tracked members data: {e}")
            # Initialize as empty in case of loading error
            self.tracked_members = {}

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Called when a member's roles change."""
        # Check if this member is being tracked
        if after.id in self.tracked_members:
            # Get the tracked member
            tracked_member = self.tracked_members[after.id]

            # Get the role changes
            old_roles = set(role.id for role in before.roles)
            new_roles = set(role.id for role in after.roles)

            # Filter to only consider tracked roles
            added_tracked_roles = (new_roles - old_roles).intersection(self.tracked_roles)
            removed_tracked_roles = (old_roles - new_roles).intersection(self.tracked_roles)

            # Get the verified role ID
            verified_role_id = self.config.get_role_id("verified")

            # Check if verified role was removed
            if verified_role_id and verified_role_id in removed_tracked_roles:
                logger.info(f"Member {tracked_member.name} ({after.id}) lost verified role - triggering role update")

                # Find a suitable channel to use for the context (same as we do for verification)
                log_channel_id = self.config.get_channel_id("testing")
                channel = None

                if log_channel_id:
                    channel = after.guild.get_channel(log_channel_id)

                # Create a minimal context-like object with a proper message object
                class MinimalContext:
                    def __init__(self, bot, guild, channel=None):
                        self.bot = bot
                        self.guild = guild
                        self.channel = channel

                    async def send(self, content=None, **kwargs):
                        # Log messages to console
                        logger.info(f"Auto-verification removal update: {content}")

                        # Send to channel if available
                        if self.channel:
                            return await self.channel.send(content, **kwargs)

                        # Create a fake message object that supports edit
                        class MinimalMessage:
                            def __init__(self, content):
                                self.content = content

                            async def edit(self, content=None, **kwargs):
                                # Just log edits instead of actually editing
                                logger.info(f"Auto-verification update edit: {content}")
                                self.content = content
                                return self

                        # Return a message-like object that supports edit()
                        return MinimalMessage(content)

                # Create minimal context with the necessary attributes
                ctx = MinimalContext(self.bot, after.guild, channel)

                # Run updateroles for this user (not a dry run)
                self.bot.loop.create_task(self.updateroles(ctx, after.id, False))

            # Handle role change logging
            if added_tracked_roles or removed_tracked_roles:
                # Log the changes
                if added_tracked_roles:
                    added_role_names = [discord.utils.get(after.guild.roles, id=role_id).name
                                        for role_id in added_tracked_roles]
                    logger.info(f"Member {tracked_member.name} ({after.id}) gained roles: {', '.join(added_role_names)}")

                # Check if verified role was added
                if verified_role_id and verified_role_id in added_tracked_roles:
                    # Run updateroles when a user gets verified
                    logger.info(f"Member {tracked_member.name} ({after.id}) was verified - running automatic role update")
                    self.bot.loop.create_task(self.process_new_verification(after.id, after.guild))

                if removed_tracked_roles:
                    removed_role_names = [discord.utils.get(before.guild.roles, id=role_id).name
                                          for role_id in removed_tracked_roles]
                    logger.info(f"Member {tracked_member.name} ({after.id}) lost roles: {', '.join(removed_role_names)}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Automatically assign verified role to tracked members when they join the server."""
        # Check if this member is being tracked
        if member.id in self.tracked_members:
            tracked_member = self.tracked_members[member.id]
            logger.info(f"Tracked member {tracked_member.name} ({member.id}) joined the server")

            # Get the verified role ID
            verified_role_id = self.config.get_role_id("verified")
            if not verified_role_id:
                logger.error("Cannot auto-verify member: No verified role defined in config")
                return

            # Get the verified role object
            verified_role = member.guild.get_role(verified_role_id)
            if not verified_role:
                logger.error(f"Cannot auto-verify member: Role with ID {verified_role_id} not found")
                return

            # Assign the verified role
            try:
                await member.add_roles(verified_role, reason="Auto-verification of tracked member")
                logger.info(f"Auto-verified member {tracked_member.name} ({member.id})")
            except discord.Forbidden:
                logger.error(f"Bot does not have permission to assign roles to {member.id}")
            except Exception as e:
                logger.error(f"Error auto-verifying member {member.id}: {e}")

    async def process_new_verification(self, discord_id, guild):
        """Process a newly verified member by updating their roles based on tournament performance."""
        try:
            logger.info(f"Processing automatic role update for newly verified member {discord_id}")

            # Find a suitable channel to use for the context (needed for status messages)
            log_channel_id = self.config.get_channel_id("testing")
            channel = None

            if log_channel_id:
                channel = guild.get_channel(log_channel_id)

            if not channel:
                logger.error(f"Could not find a suitable channel to process verification for {discord_id}")
                return

            # Create a minimal context-like object
            class MinimalContext:
                def __init__(self, bot, guild, channel):
                    self.bot = bot
                    self.guild = guild
                    self.channel = channel

                async def send(self, content=None, **kwargs):
                    # Log messages instead of sending them to keep the automatic process quiet
                    logger.info(f"Auto-verification update: {content}")
                    return await self.channel.send(content, **kwargs)

            ctx = MinimalContext(self.bot, guild, channel)

            # Call updateroles with the discord_id (not a dry run)
            await self.updateroles(ctx, discord_id, False)

            logger.info(f"Completed automatic role update for newly verified member {discord_id}")

        except Exception as e:
            logger.error(f"Error in automatic role update for {discord_id}: {e}")

    @commands.group(name="roletracker", aliases=["rt"], invoke_without_command=True)
    async def roletracker(self, ctx):
        """Role tracker commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @roletracker.command(name="refresh")
    async def refresh(self, ctx):
        """Manually refresh player data from the database."""
        status_message = await ctx.send("Refreshing player data from database...")
        try:
            await self.load_known_players(ctx=ctx, status_message=status_message)
            await status_message.edit(content=f"✅ Successfully loaded {len(self.tracked_members)} known players with Discord IDs.")
        except Exception as e:
            await status_message.edit(content=f"❌ Error refreshing player data: {e}")

    @roletracker.command(name="status")
    async def status(self, ctx):
        """Show status of role tracking."""
        # Create an embed with status information
        embed = discord.Embed(
            title="Role Tracker Status",
            color=discord.Color.blue()
        )

        # Add tracked roles in the order from config
        tracked_role_names = []
        for role_id in self.tracked_roles_ordered:
            role = discord.utils.get(ctx.guild.roles, id=role_id)
            if role:
                tracked_role_names.append(f"{role.name} ({role_id})")
            else:
                tracked_role_names.append(f"Unknown ({role_id})")

        embed.add_field(
            name="Tracked Roles",
            value="\n".join(tracked_role_names) if tracked_role_names else "None",
            inline=False
        )

        # Add tracked member count
        embed.add_field(
            name="Tracked Members",
            value=str(len(self.tracked_members)),
            inline=True
        )

        await ctx.send(embed=embed)

    @roletracker.command(name="count")
    async def count(self, ctx):
        """Show count of tracked members with each role."""
        # Count members with each tracked role
        role_counts = {role_id: 0 for role_id in self.tracked_roles}

        for member in self.tracked_members.values():
            for role_id in self.tracked_roles:
                if member.has_role(role_id):
                    role_counts[role_id] += 1

        # Get roles configuration to identify league types
        legend_roles = self.config.get("rankings", {}).get("legend", {})
        other_leagues = self.config.get("rankings", {}).get("other_leagues", {})

        # Split roles by league type
        legend_role_ids = set(legend_roles.values())
        other_role_ids = set(other_leagues.values())

        # Create separate embeds for legend and other leagues
        embeds = []

        # Create Legend league embed
        legend_embed = discord.Embed(
            title="Legend League Role Counts",
            description="Number of members with each Legend league role",
            color=discord.Color.gold()
        )

        # Add Legend roles in order from config
        for role_id in self.tracked_roles_ordered:
            if role_id in legend_role_ids:
                role = discord.utils.get(ctx.guild.roles, id=role_id)
                role_name = role.name if role else f"Unknown ({role_id})"
                count = role_counts.get(role_id, 0)
                legend_embed.add_field(
                    name=role_name,
                    value=str(count),
                    inline=True
                )

        embeds.append(legend_embed)

        # Create Other Leagues embed
        other_embed = discord.Embed(
            title="Other Leagues Role Counts",
            description="Number of members with each non-Legend league role",
            color=discord.Color.blue()
        )

        # Add other league roles in order from config
        for role_id in self.tracked_roles_ordered:
            if role_id in other_role_ids:
                role = discord.utils.get(ctx.guild.roles, id=role_id)
                role_name = role.name if role else f"Unknown ({role_id})"
                count = role_counts.get(role_id, 0)
                other_embed.add_field(
                    name=role_name,
                    value=str(count),
                    inline=True
                )

        embeds.append(other_embed)

        # Add a third embed for any other tracked roles (like verified)
        other_tracked_roles = [r for r in self.tracked_roles_ordered
                               if r not in legend_role_ids and r not in other_role_ids]

        if other_tracked_roles:
            misc_embed = discord.Embed(
                title="Other Tracked Roles",
                description="Number of members with other tracked roles",
                color=discord.Color.green()
            )

            for role_id in other_tracked_roles:
                role = discord.utils.get(ctx.guild.roles, id=role_id)
                role_name = role.name if role else f"Unknown ({role_id})"
                count = role_counts.get(role_id, 0)
                misc_embed.add_field(
                    name=role_name,
                    value=str(count),
                    inline=True
                )

            embeds.append(misc_embed)

        # Send all embeds
        for embed in embeds:
            # Add totals to each embed footer
            embed.set_footer(text=f"Total tracked members: {len(self.tracked_members)}")
            await ctx.send(embed=embed)

    @roletracker.command(name="unverified")
    async def unverified(self, ctx):
        """Show tracked members who don't have the verified role."""
        # Get the verified role ID
        verified_role_id = self.config.get_role_id("verified")
        if not verified_role_id:
            await ctx.send("❌ No verified role defined in the config!")
            return

        # Find tracked members without the verified role
        unverified_members = []
        for discord_id, member in self.tracked_members.items():
            if not member.has_role(verified_role_id):
                unverified_members.append(member)

        # Sort by name for easier reading
        unverified_members.sort(key=lambda m: m.name.lower() if m.name else "")

        # Check if we found any unverified members
        if not unverified_members:
            await ctx.send("✅ All tracked members have the verified role!")
            return

        total_unverified = len(unverified_members)

        # Handle pagination for large lists
        PAGE_SIZE = 20
        total_pages = (total_unverified + PAGE_SIZE - 1) // PAGE_SIZE

        for page_num in range(total_pages):
            page_embed = discord.Embed(
                title=f"Unverified Members (Page {page_num + 1}/{total_pages})",
                description=f"Found {total_unverified} tracked members without the verified role",
                color=discord.Color.orange()
            )

            start_idx = page_num * PAGE_SIZE
            end_idx = min(start_idx + PAGE_SIZE, total_unverified)

            # Format without clickable mentions - just ID and name
            member_list = []
            for idx, member in enumerate(unverified_members[start_idx:end_idx], start=start_idx + 1):
                member_list.append(f"{idx}. `{member.discord_id}` - {member.name or 'Unknown'}")

            page_embed.add_field(
                name=f"Members ({start_idx + 1}-{end_idx} of {total_unverified})",
                value="\n".join(member_list) if member_list else "None",
                inline=False
            )

            # Add footer with helpful instructions
            page_embed.set_footer(text="Use $roletracker userinfo [name/ID] to see more details")

            await ctx.send(embed=page_embed)

    @roletracker.command(name="userinfo")
    async def userinfo(self, ctx, *, user_input: str = None):
        """Show tracked roles for a user from existing data without querying Discord.

        Arguments:
            user_input: Can be a Discord user mention, ID, or name
        """
        discord_id = None
        tracked_member = None

        # Handle case when no input is provided
        if not user_input and not ctx.message.mentions:
            await ctx.send("Please provide a user mention, ID, or name.")
            return

        # Try to extract user from mention
        if ctx.message.mentions:
            discord_id = ctx.message.mentions[0].id
            tracked_member = self.tracked_members.get(discord_id)
        else:
            # Try by ID
            if user_input.isdigit():
                discord_id = int(user_input)
                tracked_member = self.tracked_members.get(discord_id)

            # Try by name if we still don't have a user
            if not tracked_member:
                # Case-insensitive search by name
                user_input_lower = user_input.lower()
                for member_id, member in self.tracked_members.items():
                    if member.name and user_input_lower in member.name.lower():
                        tracked_member = member
                        discord_id = member_id
                        break

        if not tracked_member:
            await ctx.send(f"❌ No tracked data found for: {user_input}")
            return

        # Build embed with tracked information
        embed = discord.Embed(
            title=f"Role Information for {tracked_member.name}",
            description="Data from role cache (not querying Discord)",
            color=discord.Color.green()
        )

        embed.add_field(
            name="Discord ID",
            value=str(discord_id),
            inline=True
        )

        embed.add_field(
            name="Tower Player ID",
            value=tracked_member.player_id or "Unknown",
            inline=True
        )

        # Get tracked roles using the role cache
        guild_id = ctx.guild.id
        user_tracked_roles = []
        for role_id in self.tracked_roles_ordered:
            if self.has_role(guild_id, discord_id, role_id):
                # Try to get the role name from guild if possible without API call
                role = discord.utils.get(ctx.guild.roles, id=role_id)
                role_name = role.name if role else f"Role ID: {role_id}"
                user_tracked_roles.append(role_name)

        if user_tracked_roles:
            embed.add_field(
                name="Tracked Roles",
                value="\n".join(user_tracked_roles),
                inline=False
            )
        else:
            embed.add_field(
                name="Tracked Roles",
                value="None",
                inline=False
            )

        # Add timestamp to show when the data was last updated
        embed.set_footer(text="Data from role cache")

        await ctx.send(embed=embed)

    @roletracker.command(name="updateroles")
    async def updateroles(self, ctx, discord_id: int = None, dryrun: bool = False):
        """Update roles based on tournament performance.

        Arguments:
                discord_id: If provided, update only that user, otherwise update all tracked members
                dryrun: If True, calculates changes but doesn't apply them
        """
        # Get the TourneyStats cog
        tourney_stats = self.bot.get_cog("Tourney Stats")
        if not tourney_stats:
            await ctx.send("❌ TourneyStats cog is not loaded!")
            return

        # Set up status message
        status_prefix = "[DRY RUN] " if dryrun else ""
        status_message = await ctx.send(f"{status_prefix}Starting role update based on tournament data...")

        # Get the guild
        guild = self.bot.get_guild(self.config.get_guild_id())
        if not guild:
            await status_message.edit(content=f"❌ {status_prefix}Could not find guild!")
            return

        # OPTIMIZATION 1: Pre-cache all roles for faster lookups
        role_cache = {role.id: role for role in guild.roles}

        # Get the verified role ID
        verified_role_id = self.config.get_role_id("verified")

        # Get the roles configuration
        legend_roles = self.config.get("rankings", {}).get("legend", {})
        other_league_roles = self.config.get("rankings", {}).get("other_leagues", {})

        # Convert to ordered lists for role precedence
        legend_role_ids = []
        legend_thresholds = []
        for role_name, role_id in legend_roles.items():
            if role_name.startswith("top"):
                try:
                    threshold = int(role_name[3:])  # Extract number from "topX"
                    legend_role_ids.append(role_id)
                    legend_thresholds.append(threshold)
                except ValueError:
                    logger.warning(f"Could not parse threshold from {role_name}")

        # Sort by threshold (ascending) so top1 comes first, top2000 last
        legend_roles_sorted = sorted(zip(legend_thresholds, legend_role_ids))
        legend_thresholds = [t for t, _ in legend_roles_sorted]
        legend_role_ids = [r for _, r in legend_roles_sorted]

        # Parse other league roles
        league_wave_roles = {}
        for role_name, role_id in other_league_roles.items():
            # Parse role name like "championXXX" to get league and wave threshold
            for league in tourney_stats.league_dfs.keys():
                if league != "legend":
                    # Case-insensitive check if role_name starts with league name
                    if role_name.lower().startswith(league.lower()):
                        try:
                            # Extract wave threshold from the part after the league name
                            wave_part = role_name[len(league):]
                            wave_threshold = int(wave_part)

                            if league.lower() not in league_wave_roles:
                                league_wave_roles[league.lower()] = []
                            league_wave_roles[league.lower()].append((wave_threshold, role_id))
                        except ValueError:
                            logger.warning(f"Could not parse wave threshold from {role_name}")

        # Sort each league's roles by wave threshold (descending)
        for league in league_wave_roles:
            league_wave_roles[league] = sorted(league_wave_roles[league], reverse=True)

        # Count how many members we need to process
        if discord_id:
            total_members = 1
            members_to_process = [discord_id]
        else:
            members_to_process = list(self.tracked_members.keys())
            total_members = len(members_to_process)

        await status_message.edit(content=f"{status_prefix}Processing {total_members} members for role updates...")

        # Track statistics
        processed = 0
        updated = 0
        roles_added = 0
        roles_removed = 0
        errors = 0

        # For detailed reporting (for both dry run and actual updates)
        role_change_details = []
        role_add_counts = {}
        role_remove_counts = {}

        # Process members in batches to prevent rate limiting
        batch_size = 100
        for i in range(0, total_members, batch_size):
            batch = members_to_process[i:i + batch_size]
            batch_start = datetime.datetime.now()

            # Define league hierarchy (highest to lowest)
            league_hierarchy = ["legend", "champion", "platinum", "gold", "silver", "copper"]

            for discord_id in batch:
                try:
                    # Yield control to event loop periodically
                    if processed % 10 == 0:
                        await asyncio.sleep(0)
                    tracked_member = self.tracked_members.get(discord_id)
                    if not tracked_member or not tracked_member.player_id:
                        logger.warning(f"Missing player ID for Discord user {discord_id}")
                        continue

                    # OPTIMIZATION: Only fetch Discord member if we need to apply changes
                    # Avoids unnecessary API calls during dry runs or when no changes needed
                    member = None

                    # Initialize role changes
                    roles_to_add_ids = set()
                    roles_to_remove_ids = set()

                    # Check if the user has the verified role
                    has_verified_role = tracked_member.has_role(verified_role_id) if verified_role_id else False

                    # If the user doesn't have the verified role, remove all other tracked roles
                    if not has_verified_role:
                        logger.info(f"Member {tracked_member.name} not verified - removing all tournament roles")

                        # Add all tracked roles except the verified role to the remove list
                        for role_id in self.tracked_roles:
                            if role_id != verified_role_id and tracked_member.has_role(role_id):
                                roles_to_remove_ids.add(role_id)

                        # Skip the tournament stat processing for unverified users
                        if roles_to_remove_ids:
                            # OPTIMIZATION: Convert role IDs to objects only when needed
                            roles_to_remove = [role_cache.get(role_id) for role_id in roles_to_remove_ids if role_id in role_cache]

                            # Create a member details object for reporting
                            member_details = {
                                "name": tracked_member.name,
                                "discord_id": tracked_member.discord_id,
                                "player_id": tracked_member.player_id,
                                "add_roles": [],
                                "remove_roles": [{"id": role.id, "name": role.name} for role in roles_to_remove]
                            }
                            role_change_details.append(member_details)

                            # Update statistics
                            updated += 1
                            roles_removed += len(roles_to_remove)

                            # Track role removal counts
                            for role in roles_to_remove:
                                role_remove_counts[role.name] = role_remove_counts.get(role.name, 0) + 1

                            # Apply changes if not a dry run
                            if not dryrun:
                                try:
                                    # Only fetch the member if we haven't already
                                    if member is None:
                                        try:
                                            member = await guild.fetch_member(discord_id)
                                        except discord.NotFound:
                                            logger.warning(f"Discord member not found: {discord_id}")
                                            continue
                                        except Exception as e:
                                            logger.error(f"Error fetching Discord member {discord_id}: {e}")
                                            errors += 1
                                            continue

                                    # Create new role list without the tracked roles
                                    new_roles = [role for role in member.roles if role.id not in roles_to_remove_ids]

                                    await member.edit(roles=new_roles, reason="Automatic role removal due to loss of verified status")

                                    # Update the tracked member's roles
                                    tracked_member.update_roles(new_roles)

                                    # Log the removed roles
                                    removed_role_names = [role.name for role in roles_to_remove]
                                    logger.info(f"Removed roles from unverified member {tracked_member.name}: {', '.join(removed_role_names)}")

                                except discord.Forbidden:
                                    logger.error(f"Bot doesn't have permission to remove roles from member {discord_id}")
                                    errors += 1
                                except Exception as e:
                                    logger.error(f"Error removing roles from unverified member {discord_id}: {e}")
                                    errors += 1

                        # Continue to the next user since we've handled this unverified case
                        processed += 1
                        continue

                    # Continue with your existing tournament stats processing for verified users...
                    # Get this player's tournament stats
                    player_stats = await tourney_stats.get_player_tournament_stats(tracked_member.player_id)
                    if not player_stats:
                        logger.info(f"No tournament stats found for {tracked_member.name}")
                        processed += 1
                        continue

                    # Track the highest league the player qualifies for
                    highest_qualified_league = None
                    highest_qualified_role = None

                    # ---- Process Legend league first (highest precedence) ----
                    legend_stats = None
                    for league_name, stats in player_stats.items():
                        if league_name.lower() == "legend":
                            legend_stats = stats
                            break

                    if legend_stats and "best_position" in legend_stats:
                        best_position = legend_stats["best_position"]

                        # Regular legend role assignment - no special handling for top1 role
                        for i, threshold in enumerate(legend_thresholds):
                            if best_position <= threshold:
                                highest_qualified_league = "legend"
                                highest_qualified_role = legend_role_ids[i]
                                if not tracked_member.has_role(highest_qualified_role):
                                    roles_to_add_ids.add(highest_qualified_role)
                                break

                    # ---- Process other leagues only if not qualified for Legend ----
                    if not highest_qualified_league:
                        # Check each league in hierarchy order
                        for league in league_hierarchy[1:]:  # Skip legend as we already checked it
                            league_stats = None
                            # Find stats for this league (case-insensitive)
                            for league_name, stats in player_stats.items():
                                if league_name.lower() == league:
                                    league_stats = stats
                                    break

                            if league_stats and "best_wave" in league_stats:
                                best_wave = league_stats["best_wave"]
                                # Find if they qualify for any role in this league
                                if league.lower() in league_wave_roles:
                                    for wave_threshold, role_id in league_wave_roles[league.lower()]:
                                        if best_wave >= wave_threshold:
                                            highest_qualified_league = league
                                            highest_qualified_role = role_id
                                            # OPTIMIZATION: Use role IDs directly
                                            if not tracked_member.has_role(highest_qualified_role):
                                                roles_to_add_ids.add(highest_qualified_role)
                                            break

                                    # If we found a qualifying role in this league, stop checking lower leagues
                                    if highest_qualified_league:
                                        break

                    # ---- Remove ALL roles that don't match the highest qualified league ----
                    if highest_qualified_league:
                        # Remove any Legend roles if not qualified for the exact one
                        if highest_qualified_league == "legend":
                            # Remove other legend roles that don't match the exact qualified role
                            for role_id in legend_role_ids:
                                if role_id != highest_qualified_role and tracked_member.has_role(role_id):
                                    roles_to_remove_ids.add(role_id)
                        else:
                            # Remove ALL legend roles if qualified for a different league
                            for role_id in legend_role_ids:
                                if tracked_member.has_role(role_id):
                                    roles_to_remove_ids.add(role_id)

                        # Remove ALL roles from other leagues
                        for league in league_hierarchy[1:]:  # Process non-legend leagues
                            if league.lower() in league_wave_roles:
                                # If this is not the highest league, remove all its roles
                                if league.lower() != highest_qualified_league.lower():
                                    for _, role_id in league_wave_roles[league.lower()]:
                                        if tracked_member.has_role(role_id):
                                            roles_to_remove_ids.add(role_id)
                                # If this is the highest league, remove all except the qualified role
                                else:
                                    for _, role_id in league_wave_roles[league.lower()]:
                                        if role_id != highest_qualified_role and tracked_member.has_role(role_id):
                                            roles_to_remove_ids.add(role_id)

                    # OPTIMIZATION: Convert role IDs to objects only when needed
                    roles_to_add = [role_cache.get(role_id) for role_id in roles_to_add_ids if role_id in role_cache]
                    roles_to_remove = [role_cache.get(role_id) for role_id in roles_to_remove_ids if role_id in role_cache]

                    # ---- Apply role changes as before ----
                    if roles_to_add or roles_to_remove:
                        reason = f"Tournament performance role update ({datetime.datetime.now().strftime('%Y-%m-%d')})"

                        # For both dry run and actual updates, track changes for reporting
                        updated += 1
                        roles_added += len(roles_to_add)
                        roles_removed += len(roles_to_remove)

                        # Track role change counts
                        for role in roles_to_add:
                            role_add_counts[role.name] = role_add_counts.get(role.name, 0) + 1
                        for role in roles_to_remove:
                            role_remove_counts[role.name] = role_remove_counts.get(role.name, 0) + 1

                        # Add to detailed report for both dry run and actual updates
                        member_details = {
                            "name": tracked_member.name,
                            "discord_id": tracked_member.discord_id,
                            "player_id": tracked_member.player_id,
                            "add_roles": [{"id": role.id, "name": role.name} for role in roles_to_add],
                            "remove_roles": [{"id": role.id, "name": role.name} for role in roles_to_remove]
                        }
                        role_change_details.append(member_details)

                        if dryrun:
                            # Log instead of applying
                            if roles_to_add:
                                added_role_names = [role.name for role in roles_to_add]
                                logger.info(f"[DRY RUN] Would add roles to {tracked_member.name}: {', '.join(added_role_names)}")

                            if roles_to_remove:
                                removed_role_names = [role.name for role in roles_to_remove]
                                logger.info(f"[DRY RUN] Would remove roles from {tracked_member.name}: {', '.join(removed_role_names)}")

                            # OPTIMIZATION: Update tracked member roles in dry run for accurate reporting
                            if roles_to_add_ids or roles_to_remove_ids:
                                # Update the tracked roles in our cache (dry run simulation)
                                updated_roles = tracked_member.roles.copy()
                                for role_id in roles_to_add_ids:
                                    updated_roles.add(role_id)
                                for role_id in roles_to_remove_ids:
                                    if role_id in updated_roles:
                                        updated_roles.remove(role_id)
                                tracked_member.roles = updated_roles
                        else:
                            # Actually apply the changes - now we need to fetch the member
                            try:
                                # Only fetch the member if we haven't already
                                if member is None:
                                    try:
                                        member = await guild.fetch_member(discord_id)
                                    except discord.NotFound:
                                        logger.warning(f"Discord member not found: {discord_id}")
                                        continue
                                    except Exception as e:
                                        logger.error(f"Error fetching Discord member {discord_id}: {e}")
                                        errors += 1
                                        continue

                                # Use the atomic role editor to batch changes
                                new_roles = list(member.roles)

                                # Add roles
                                for role in roles_to_add:
                                    if role not in new_roles:
                                        new_roles.append(role)

                                # Remove roles
                                for role in roles_to_remove:
                                    if role in new_roles:
                                        new_roles.remove(role)

                                await member.edit(roles=new_roles, reason=reason)

                                # Log the changes
                                if roles_to_add:
                                    added_role_names = [role.name for role in roles_to_add]
                                    logger.info(f"Added roles to {tracked_member.name}: {', '.join(added_role_names)}")

                                if roles_to_remove:
                                    removed_role_names = [role.name for role in roles_to_remove]
                                    logger.info(f"Removed roles from {tracked_member.name}: {', '.join(removed_role_names)}")

                                # Update the tracked member's roles
                                tracked_member.update_roles(new_roles)

                            except discord.Forbidden:
                                logger.error(f"Bot does not have permission to modify roles for {discord_id}")
                                errors += 1
                            except Exception as e:
                                logger.error(f"Error updating roles for {discord_id}: {e}")
                                errors += 1

                    processed += 1

                    # Update status message periodically
                    if processed % 250 == 0:
                        progress = (processed / total_members) * 100
                        if dryrun:
                            await status_message.edit(
                                content=f"{status_prefix}Progress: {processed}/{total_members} ({progress:.1f}%)\n"
                                f"Would update: {updated}, Would add: {roles_added}, Would remove: {roles_removed}, Errors: {errors}"
                            )
                        else:
                            await status_message.edit(
                                content=f"Progress: {processed}/{total_members} ({progress:.1f}%)\n"
                                f"Updated: {updated}, Added: {roles_added}, Removed: {roles_removed}, Errors: {errors}"
                            )

                except Exception as e:
                    logger.error(f"Error processing member {discord_id}: {e}")
                    errors += 1
                    processed += 1

            # Short delay between batches to prevent rate limiting
            batch_time = datetime.datetime.now() - batch_start
            logger.info(f"{status_prefix}Processed batch of {len(batch)} members in {batch_time.total_seconds():.1f}s")

        # Only save data if not in dry run
        if not dryrun:
            self.save_data()

        # Final status update
        action_prefix = "Would " if dryrun else ""
        await status_message.edit(
            content=f"✅ {status_prefix}Role update complete!\n"
            f"Processed: {processed}/{total_members}\n"
            f"{action_prefix}Update{'' if dryrun else 'd'}: {updated} members\n"
            f"{action_prefix}Add{'' if dryrun else 'ed'}: {roles_added} roles\n"
            f"{action_prefix}Remove{'' if dryrun else 'd'}: {roles_removed} roles\n"
            f"Errors: {errors}"
        )

        # Send role change summary regardless of dry run mode
        if role_change_details:
            # First message with summary counts by role
            summary_message = f"**Role Changes Summary{' (Dry Run)' if dryrun else ''}**\n\n"

            if role_add_counts:
                summary_message += "**Roles to Add:**\n"
                for name, count in sorted(role_add_counts.items(), key=lambda x: x[1], reverse=True):
                    summary_message += f"{name}: {count}\n"

            if role_remove_counts:
                summary_message += "\n**Roles to Remove:**\n"
                for name, count in sorted(role_remove_counts.items(), key=lambda x: x[1], reverse=True):
                    summary_message += f"{name}: {count}\n"

            await ctx.send(summary_message)

            # Create simplified change list
            detailed_changes = []

            for detail in role_change_details:
                username = detail["name"]
                role_changes = []

                # Process role additions
                for role in detail["add_roles"]:
                    role_name = role["name"]
                    # Extract league and threshold
                    league = None
                    threshold = None

                    # Parse role names like "Legend Top 10" or "Platinum 250"
                    if "top" in role_name.lower():
                        league = "Legend"
                        # Extract number after "top"
                        parts = role_name.lower().split("top")
                        if len(parts) > 1 and parts[1].strip().isdigit():
                            threshold = parts[1].strip()
                    else:
                        for league_name in ["Champion", "Platinum", "Gold", "Silver", "Copper"]:
                            if league_name.lower() in role_name.lower():
                                league = league_name
                                # Extract number after league name
                                parts = role_name.lower().split(league_name.lower())
                                if len(parts) > 1:
                                    threshold_part = parts[1].strip()
                                    if threshold_part.isdigit():
                                        threshold = threshold_part
                                break

                    if league and threshold:
                        role_changes.append(f"+{league}: {threshold}")
                    else:
                        # Fallback if parsing fails
                        role_changes.append(f"+{role_name}")

                # Process role removals
                for role in detail["remove_roles"]:
                    role_name = role["name"]
                    # Extract league and threshold using same logic as above
                    league = None
                    threshold = None

                    # Parse role names like "Legend Top 10" or "Platinum 250"
                    if "top" in role_name.lower():
                        league = "Legend"
                        # Extract number after "top"
                        parts = role_name.lower().split("top")
                        if len(parts) > 1 and parts[1].strip().isdigit():
                            threshold = parts[1].strip()
                    else:
                        for league_name in ["Champion", "Platinum", "Gold", "Silver", "Copper"]:
                            if league_name.lower() in role_name.lower():
                                league = league_name
                                # Extract number after league name
                                parts = role_name.lower().split(league_name.lower())
                                if len(parts) > 1:
                                    threshold_part = parts[1].strip()
                                    if threshold_part.isdigit():
                                        threshold = threshold_part
                                break

                    if league and threshold:
                        role_changes.append(f"-{league}: {threshold}")
                    else:
                        # Fallback if parsing fails
                        role_changes.append(f"-{role_name}")

                if role_changes:
                    detailed_changes.append(f"{username}: {', '.join(role_changes)}")

            # Send the detailed changes in chunks
            CHUNK_SIZE = 40  # Number of users per message
            for i in range(0, len(detailed_changes), CHUNK_SIZE):
                chunk = detailed_changes[i:i + CHUNK_SIZE]
                message = "\n".join(chunk)

                # Split if message is too long
                if len(message) > 1900:
                    # Further split into smaller chunks
                    for j in range(0, len(message), 1900):
                        await ctx.send(message[j:j + 1900])
                else:
                    await ctx.send(message)

    @roletracker.command(name="debugrole")
    async def debugrole(self, ctx, discord_id: int):
        """Debug role assignment for a specific user across all leagues respecting hierarchy."""
        tracked_member = self.tracked_members.get(discord_id)
        if not tracked_member:
            await ctx.send(f"❌ User {discord_id} is not being tracked")
            return

        # Get TourneyStats cog
        tourney_stats = self.bot.get_cog("Tourney Stats")
        if not tourney_stats:
            await ctx.send("❌ TourneyStats cog is not loaded")
            return

        # Get roles configuration
        legend_roles = self.config.get("rankings", {}).get("legend", {})
        other_league_roles = self.config.get("rankings", {}).get("other_leagues", {})

        # Define league hierarchy (highest to lowest)
        league_hierarchy = ["legend", "champion", "platinum", "gold", "silver", "copper"]

        # Get ALL player IDs for this Discord ID
        player_ids = await tourney_stats.get_player_ids_by_discord_id(discord_id)
        await ctx.send(f"Player IDs found: `{player_ids}`")
        await ctx.send(f"Role tracker's player ID: `{tracked_member.player_id}`")

        # Parse legend roles
        legend_thresholds = []
        legend_role_ids = []
        for role_name, role_id in legend_roles.items():
            if role_name.startswith("top"):
                try:
                    threshold = int(role_name[3:])  # Extract number from "topX"
                    legend_thresholds.append(threshold)
                    legend_role_ids.append(role_id)
                except ValueError:
                    pass

        # Sort by threshold (ascending)
        legend_roles_sorted = sorted(zip(legend_thresholds, legend_role_ids))
        legend_thresholds = [t for t, _ in legend_roles_sorted]
        legend_role_ids = [r for _, r in legend_roles_sorted]

        # Parse league wave roles
        league_wave_roles = {}
        for role_name, role_id in other_league_roles.items():
            for league in tourney_stats.league_dfs.keys():
                if league.lower() != "legend" and role_name.lower().startswith(league.lower()):
                    try:
                        wave_threshold = int(role_name[len(league):])
                        if league.lower() not in league_wave_roles:
                            league_wave_roles[league.lower()] = []
                        league_wave_roles[league.lower()].append((wave_threshold, role_id))
                    except ValueError:
                        pass

        # Sort each league's roles by wave threshold (descending)
        for league in league_wave_roles:
            league_wave_roles[league] = sorted(league_wave_roles[league], reverse=True)

        # Get stats for EACH player ID
        all_stats = {}
        for player_id in player_ids:
            player_stats = await tourney_stats.get_player_tournament_stats(player_id)
            if player_stats:
                await ctx.send(f"Found stats for player ID `{player_id}`")

                # Merge into all_stats, taking the best results
                for league, league_stats in player_stats.items:
                    if league not in all_stats:
                        all_stats[league] = league_stats
                    else:
                        # For legend, keep the best position
                        if league.lower() == "legend" and 'best_position' in league_stats:
                            if league_stats['best_position'] < all_stats[league]['best_position']:
                                all_stats[league] = league_stats
                        # For others, keep the best wave
                        elif 'best_wave' in league_stats:
                            if league_stats['best_wave'] > all_stats[league]['best_wave']:
                                all_stats[league] = league_stats
            else:
                await ctx.send(f"No stats found for player ID `{player_id}`")

        # Create an embed for the results
        embed = discord.Embed(
            title=f"Role Qualification Analysis: {tracked_member.name}",
            description="Shows the highest role the player qualifies for based on tournament performance",
            color=discord.Color.blue()
        )

        # Determine the highest league the player qualifies for
        highest_qualified_league = None
        highest_qualified_role = None

        # Initialize roles_to_add_ids (this was missing)
        roles_to_add_ids = set()

        # Check Legend league first
        legend_stats = None
        for league_name, stats in all_stats.items():
            if league_name.lower() == "legend":
                legend_stats = stats
                break

        if legend_stats and "best_position" in legend_stats:
            best_position = legend_stats["best_position"]
            # Find the highest precedence role player qualifies for
            for i, threshold in enumerate(legend_thresholds):
                if best_position <= threshold:
                    highest_qualified_league = "legend"
                    highest_qualified_role = legend_role_ids[i]
                    if not tracked_member.has_role(highest_qualified_role):
                        roles_to_add_ids.add(highest_qualified_role)
                    break

        # Only check other leagues if not qualified for Legend
        if not highest_qualified_league:
            for league in league_hierarchy[1:]:  # Skip legend as we already checked it
                league_stats = None
                # Find stats for this league (case-insensitive)
                for league_name, stats in all_stats.items():
                    if league_name.lower() == league:
                        league_stats = stats
                        break

                if league_stats and "best_wave" in league_stats:
                    best_wave = league_stats["best_wave"]
                    # Find if they qualify for any role in this league
                    if league.lower() in league_wave_roles:
                        for wave_threshold, role_id in league_wave_roles[league.lower()]:
                            if best_wave >= wave_threshold:
                                highest_qualified_league = league
                                highest_qualified_role = role_id
                                break

                        # If we found a qualifying role in this league, stop checking lower leagues
                        if highest_qualified_league:
                            break

        # Display detailed information about the player's highest qualification
        if highest_qualified_league:
            # Display info for the highest league
            if highest_qualified_league.lower() == "legend":
                position = legend_stats["best_position"]
                wave = legend_stats.get("best_wave", "N/A")
                date = legend_stats.get("best_date", "Unknown")

                # Format output
                status = []
                status.append(f"Best Position: {position} (Wave {wave})")
                status.append(f"Achieved on: {date}")

                role_obj = discord.utils.get(ctx.guild.roles, id=highest_qualified_role)
                role_name = role_obj.name if role_obj else f"Role ID: {highest_qualified_role}"
                has_role = tracked_member.has_role(highest_qualified_role)

                if has_role:
                    status.append(f"✅ Has correct role: {role_name}")
                else:
                    status.append(f"❌ Missing qualified role: {role_name}")

                embed.add_field(
                    name=f"{highest_qualified_league.capitalize()} League (Highest Qualified)",
                    value="\n".join(status),
                    inline=False
                )
            else:
                # For other leagues
                for league_name, stats in all_stats.items():
                    if league_name.lower() == highest_qualified_league.lower():
                        wave = stats["best_wave"]
                        position = stats.get("position_at_best", "N/A")
                        date = stats.get("best_date", "Unknown")

                        # Find wave threshold
                        wave_threshold = 0
                        for threshold, role_id in league_wave_roles[league_name.lower()]:
                            if wave >= threshold and role_id == highest_qualified_role:
                                wave_threshold = threshold
                                break

                        # Format output
                        status = []
                        status.append(f"Best Wave: {wave} (Position {position})")
                        status.append(f"Achieved on: {date}")

                        role_obj = discord.utils.get(ctx.guild.roles, id=highest_qualified_role)
                        role_name = role_obj.name if role_obj else f"Role ID: {highest_qualified_role}"
                        has_role = tracked_member.has_role(highest_qualified_role)

                        if has_role:
                            status.append(f"✅ Has correct role: {role_name} ({wave_threshold}+ waves)")
                        else:
                            status.append(f"❌ Missing qualified role: {role_name} ({wave_threshold}+ waves)")

                        embed.add_field(
                            name=f"{highest_qualified_league.capitalize()} League (Highest Qualified)",
                            value="\n".join(status),
                            inline=False
                        )
                        break

            # List any roles that should be removed (from any league)
            roles_to_remove = []

            # Check for legend roles that should be removed
            if highest_qualified_league.lower() == "legend":
                # If in legend league, only check for other legend roles
                for role_id in legend_role_ids:
                    if role_id != highest_qualified_role and tracked_member.has_role(role_id):
                        role_obj = discord.utils.get(ctx.guild.roles, id=role_id)
                        if role_obj:
                            roles_to_remove.append(f"{role_obj.name} (Legend)")
            else:
                # If in other league, all legend roles should be removed
                for role_id in legend_role_ids:
                    if tracked_member.has_role(role_id):
                        role_obj = discord.utils.get(ctx.guild.roles, id=role_id)
                        if role_obj:
                            roles_to_remove.append(f"{role_obj.name} (Legend)")

            # Check other leagues roles
            for league in league_hierarchy[1:]:  # Process non-legend leagues
                if league.lower() in league_wave_roles:
                    # If this isn't the highest qualified league, all roles should be removed
                    if league.lower() != highest_qualified_league.lower():
                        for _, role_id in league_wave_roles[league.lower()]:
                            if tracked_member.has_role(role_id):
                                role_obj = discord.utils.get(ctx.guild.roles, id=role_id)
                                if role_obj:
                                    roles_to_remove.append(f"{role_obj.name} ({league.capitalize()})")
                    # If this is the highest league, all except the qualified role should be removed
                    else:
                        for _, role_id in league_wave_roles[league.lower()]:
                            if role_id != highest_qualified_role and tracked_member.has_role(role_id):
                                role_obj = discord.utils.get(ctx.guild.roles, id=role_id)
                                if role_obj:
                                    roles_to_remove.append(f"{role_obj.name} ({league.capitalize()})")

            if roles_to_remove:
                embed.add_field(
                    name="Roles To Remove",
                    value="\n".join([f"❌ {role}" for role in roles_to_remove]),
                    inline=False
                )
        else:
            embed.description = "Player does not qualify for any tournament role"

            # List any tournament roles that should be removed
            roles_to_remove = []

            # Check legend roles
            for role_id in legend_role_ids:
                if tracked_member.has_role(role_id):
                    role_obj = discord.utils.get(ctx.guild.roles, id=role_id)
                    if role_obj:
                        roles_to_remove.append(f"{role_obj.name} (Legend)")

            # Check other league roles
            for league in league_hierarchy[1:]:
                if league.lower() in league_wave_roles:
                    for _, role_id in league_wave_roles[league.lower()]:
                        if tracked_member.has_role(role_id):
                            role_obj = discord.utils.get(ctx.guild.roles, id=role_id)
                            if role_obj:
                                roles_to_remove.append(f"{role_obj.name} ({league.capitalize()})")

            if roles_to_remove:
                embed.add_field(
                    name="Tournament Roles To Remove",
                    value="\n".join([f"❌ {role}" for role in roles_to_remove]),
                    inline=False
                )

        # Show stats for other leagues (informational only)
        if highest_qualified_league:
            other_leagues_info = []
            for league_name, stats in all_stats.items():
                # Skip the highest qualified league as we've already displayed it
                if league_name.lower() == highest_qualified_league.lower():
                    continue

                if league_name.lower() == "legend" and "best_position" in stats:
                    other_leagues_info.append(f"**{league_name.capitalize()}**: Position {stats['best_position']} (Wave {stats.get('best_wave', 'N/A')})")
                elif "best_wave" in stats:
                    other_leagues_info.append(f"**{league_name.capitalize()}**: Wave {stats['best_wave']} (Position {stats.get('position_at_best', 'N/A')})")

            if other_leagues_info:
                embed.add_field(
                    name="Other League Stats (Not Qualifying Due to Hierarchy)",
                    value="\n".join(other_leagues_info),
                    inline=False
                )

        # Add a footer with command info
        embed.set_footer(text=f"Use $roletracker updateroles {discord_id} to apply changes")

        await ctx.send(embed=embed)

    @roletracker.command(name="multiroles")
    async def multiroles(self, ctx):
        """Show tracked members who have multiple tournament roles (excluding verified role)."""
        # Get the verified role ID
        verified_role_id = self.config.get_role_id("verified")
        if not verified_role_id:
            await ctx.send("❌ No verified role defined in the config!")
            return

        # Find members with multiple roles (excluding verified role)
        members_with_multiroles = []

        for discord_id, member in self.tracked_members.items():
            # Count tracked roles excluding verified role
            role_ids = [role_id for role_id in self.tracked_roles if
                        member.has_role(role_id) and role_id != verified_role_id]
            role_count = len(role_ids)

            if role_count > 1:
                # Store member along with their role ids and count for display
                members_with_multiroles.append((member, role_ids, role_count))

        # Sort by role count (descending) then by name
        members_with_multiroles.sort(key=lambda x: (-x[2], x[0].name.lower() if x[0].name else ""))

        # Check if we found any members
        if not members_with_multiroles:
            await ctx.send("✅ No tracked members have multiple tournament roles!")
            return

        total_members = len(members_with_multiroles)

        # Create role count summary
        role_combinations = {}
        for member, role_ids, _ in members_with_multiroles:
            # Convert role IDs to role names
            role_names = []
            for role_id in role_ids:
                role = discord.utils.get(ctx.guild.roles, id=role_id)
                if role:
                    # Extract league and threshold like in updateroles
                    role_name = role.name
                    league = None
                    threshold = None

                    if "top" in role_name.lower():
                        league = "Legend"
                        parts = role_name.lower().split("top")
                        if len(parts) > 1 and parts[1].strip().isdigit():
                            threshold = parts[1].strip()
                    else:
                        for league_name in ["Champion", "Platinum", "Gold", "Silver", "Copper"]:
                            if league_name.lower() in role_name.lower():
                                league = league_name
                                parts = role_name.lower().split(league_name.lower())
                                if len(parts) > 1:
                                    threshold_part = parts[1].strip()
                                    if threshold_part.isdigit():
                                        threshold = threshold_part
                                break

                    if league and threshold:
                        role_names.append(f"{league}: {threshold}")
                    else:
                        role_names.append(role_name)
                else:
                    role_names.append(f"Unknown ({role_id})")

            # Sort role names consistently
            role_names.sort()
            combo_key = tuple(role_names)
            role_combinations[combo_key] = role_combinations.get(combo_key, 0) + 1

        # First message: summary counts by role combination
        summary_message = f"**Members with Multiple Tournament Roles: {total_members} total**\n\n"
        summary_message += "**Role Combinations:**\n"

        for combo, count in sorted(role_combinations.items(), key=lambda x: x[1], reverse=True):
            summary_message += f"{' + '.join(combo)}: {count}\n"

        await ctx.send(summary_message)

        # Create simplified list of members with their roles
        detailed_changes = []
        for member, role_ids, _ in members_with_multiroles:
            username = member.name or f"Unknown ({member.discord_id})"

            # Process roles
            role_details = []
            for role_id in role_ids:
                role = discord.utils.get(ctx.guild.roles, id=role_id)
                if role:
                    role_name = role.name
                    league = None
                    threshold = None

                    # Same parsing logic as before
                    if "top" in role_name.lower():
                        league = "Legend"
                        parts = role_name.lower().split("top")
                        if len(parts) > 1 and parts[1].strip().isdigit():
                            threshold = parts[1].strip()
                    else:
                        for league_name in ["Champion", "Platinum", "Gold", "Silver", "Copper"]:
                            if league_name.lower() in role_name.lower():
                                league = league_name
                                parts = role_name.lower().split(league_name.lower())
                                if len(parts) > 1:
                                    threshold_part = parts[1].strip()
                                    if threshold_part.isdigit():
                                        threshold = threshold_part
                                break

                    if league and threshold:
                        role_details.append(f"{league}: {threshold}")
                    else:
                        role_details.append(role_name)
                else:
                    role_details.append(f"Unknown ({role_id})")

            # Sort roles consistently
            role_details.sort()
            detailed_changes.append(f"{username}: {', '.join(role_details)}")

        # Send the detailed changes in chunks by number of users
        CHUNK_SIZE = 40  # Number of users per message
        for i in range(0, len(detailed_changes), CHUNK_SIZE):
            chunk = detailed_changes[i:i + CHUNK_SIZE]
            message = "\n".join(chunk)

            # Split if message is too long
            if len(message) > 1900:
                # Further split into smaller chunks
                for j in range(0, len(message), 1900):
                    await ctx.send(message[j + j + 1900])
            else:
                await ctx.send(message)

    @roletracker.command(name="missing_verified")
    async def missing_verified(self, ctx):
        """Show tracked members who are in the server but don't have the verified role."""
        # Get the verified role ID
        verified_role_id = self.config.get_role_id("verified")
        if not verified_role_id:
            await ctx.send("❌ No verified role defined in the config!")
            return

        status_message = await ctx.send("Scanning server for tracked members without verified role...")

        # Get guild and build member cache to minimize API calls
        guild = ctx.guild

        # Get all guild members (once) and build a set of their IDs for fast lookup
        guild_member_ids = {m.id for m in guild.members}

        # Find tracked members who are in the guild but don't have the verified role
        missing_verified = []

        for discord_id, tracked_member in self.tracked_members.items():
            # Check if member is in the guild and doesn't have the verified role
            if discord_id in guild_member_ids and not tracked_member.has_role(verified_role_id):
                # Get member object (single API call per member)
                member = guild.get_member(discord_id)
                if member:  # Double check in case member left during processing
                    missing_verified.append({
                        "discord_id": discord_id,
                        "name": tracked_member.name or "Unknown",
                        "member": member
                    })

        # Sort by name for easier reading
        missing_verified.sort(key=lambda x: x["name"].lower())
        total_missing = len(missing_verified)

        if not missing_verified:
            await status_message.edit(content="✅ All tracked members in the server have the verified role!")
            return

        await status_message.edit(content=f"Found {total_missing} tracked members in the server without the verified role:")

        # Format all members in a single list
        header = "__Members Missing Verified Role__\n"
        member_list = []

        for idx, member_data in enumerate(missing_verified, start=1):
            member = member_data["member"]
            join_date = member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "Unknown"
            member_list.append(f"{idx}. {member.mention} - {member_data['name']} (Joined: {join_date})")

        # Combine the list with a note about bulk verification
        message_content = header + "\n".join(member_list) + "\n\nUse `$roletracker bulk_verify` to verify these members"

        # Check if message is too long for a single Discord message
        if len(message_content) > 1900:  # Leave some buffer
            # Split into chunks based on character count
            chunks = []
            current_chunk = header

            for line in member_list:
                if len(current_chunk) + len(line) + 1 > 1900:  # +1 for newline
                    chunks.append(current_chunk)
                    current_chunk = line
                else:
                    current_chunk += "\n" + line

            # Add the last chunk if not empty
            if current_chunk:
                chunks.append(current_chunk)

            # Send each chunk
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:  # Add note to the last chunk
                    chunk += "\n\nUse `$roletracker bulk_verify` to verify these members"
                await ctx.send(chunk)
        else:
            # Send everything in one message
            await ctx.send(message_content)

    @roletracker.command(name="bulk_verify")
    async def bulk_verify(self, ctx):
        """Assign the verified role to all tracked members who are in the server but don't have it."""
        # Get the verified role ID
        verified_role_id = self.config.get_role_id("verified")
        if not verified_role_id:
            await ctx.send("❌ No verified role defined in the config!")
            return

        # Get the verified role object
        verified_role = ctx.guild.get_role(verified_role_id)
        if not verified_role:
            await ctx.send(f"❌ Verified role with ID {verified_role_id} not found in the server!")
            return

        # Check bot permissions
        if not ctx.guild.me.guild_permissions.manage_roles:
            await ctx.send("❌ I don't have permission to manage roles in this server!")
            return

        # Check role hierarchy
        if verified_role.position >= ctx.guild.me.top_role.position:
            await ctx.send(f"❌ Cannot assign {verified_role.name} role - it's higher than my highest role!")
            return

        status_message = await ctx.send("Finding tracked members who need verification...")

        # Get all guild members but only get their IDs (more efficient)
        guild = ctx.guild
        guild_member_ids = {m.id for m in guild.members}

        # Find tracked members who are in the guild but don't have the verified role
        # Use our cached role data instead of querying Discord again
        to_verify_ids = []

        for discord_id, tracked_member in self.tracked_members.items():
            # Check if member is in the guild and doesn't have the verified role
            if discord_id in guild_member_ids and not tracked_member.has_role(verified_role_id):
                to_verify_ids.append(discord_id)

        total_to_verify = len(to_verify_ids)

        if not total_to_verify:
            await status_message.edit(content="✅ All tracked members in the server already have the verified role!")
            return

        await status_message.edit(content=f"Found {total_to_verify} tracked members to verify. Starting verification...")

        # Track statistics
        verified_count = 0
        error_count = 0
        already_verified = 0

        # Process members in batches to prevent rate limiting
        batch_size = 10
        for i in range(0, total_to_verify, batch_size):
            batch = to_verify_ids[i:i + batch_size]

            # Update status every batch
            if i > 0:
                progress = (i / total_to_verify) * 100
                await status_message.edit(
                    content=f"Progress: {i}/{total_to_verify} ({progress:.1f}%)\n"
                    f"Verified: {verified_count}, Errors: {error_count}"
                )

            # Process each member in the batch
            for discord_id in batch:
                tracked_member = self.tracked_members[discord_id]

                try:
                    # Only fetch member from Discord when we need to assign the role
                    # This is the only unavoidable API call
                    member = guild.get_member(discord_id)
                    if not member:
                        logger.error(f"Member {discord_id} not found despite being in guild members")
                        error_count += 1
                        continue

                    # Double-check if they already have the role
                    if verified_role in member.roles:
                        already_verified += 1
                        continue

                    # Add the verified role
                    await member.add_roles(verified_role, reason=f"Bulk verification by {ctx.author}")

                    # Update the tracked member's roles
                    tracked_member.update_roles(member.roles + [verified_role])

                    verified_count += 1
                    logger.info(f"Bulk verified member {tracked_member.name} ({discord_id})")

                    # Small delay between role assignments to avoid rate limits
                    await asyncio.sleep(0.5)

                except discord.Forbidden:
                    error_count += 1
                    logger.error(f"Missing permissions to assign role to {discord_id}")
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error verifying member {discord_id}: {e}")

        # Save the updated data
        self.save_data()

        # Final status update
        await status_message.edit(
            content=f"✅ Bulk verification complete!\n"
            f"Successfully verified: {verified_count}/{total_to_verify}\n"
            f"Already verified: {already_verified}\n"
            f"Errors: {error_count}"
        )

        # No need to call process_bulk_verification as on_member_update will handle role updates automatically


async def setup(bot) -> None:
    await bot.add_cog(RoleTracker(bot))