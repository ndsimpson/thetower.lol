import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Button, View, Modal, TextInput
import datetime
import json
import os
import asyncio
import pickle
import re
import logging
from fish_bot import const

# Set up logger
logger = logging.getLogger('fish_bot.cogs.unified_advertise')


class AdvertisementType:
    GUILD = "guild"
    MEMBER = "member"


class AdTypeSelection(View):
    """View with buttons to select advertisement type."""

    def __init__(self, cog):
        super().__init__(timeout=180)  # 3 minute timeout
        self.cog = cog

    @discord.ui.button(label="Guild Advertisement", style=discord.ButtonStyle.primary, emoji="🏰")
    async def guild_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(GuildAdvertisementForm(self.cog))

    @discord.ui.button(label="Member Advertisement", style=discord.ButtonStyle.success, emoji="👤")
    async def member_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(MemberAdvertisementForm(self.cog))

    async def on_timeout(self):
        # Disable all buttons when the view times out
        for item in self.children:
            item.disabled = True


class GuildAdvertisementForm(Modal, title="Guild Advertisement Form"):
    """Modal form for collecting guild advertisement information."""

    guild_name = TextInput(
        label="Guild Name",
        placeholder="Enter your guild's name",
        required=True,
        max_length=100
    )

    guild_id = TextInput(
        label="Guild ID",
        placeholder="Enter your guild's ID (e.g. A1B2C3)",
        required=True,
        min_length=6,
        max_length=6
    )

    guild_leader = TextInput(
        label="Guild Leader",
        placeholder="Enter guild leader's name",
        required=True,
        max_length=100
    )

    member_count = TextInput(
        label="Member Count",
        placeholder="How many active members?",
        required=True,
        max_length=10
    )

    description = TextInput(
        label="Guild Description",
        placeholder="Tell us about your guild...",
        required=True,
        max_length=1000,
        style=discord.TextStyle.paragraph
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        # Check if guild ID is valid (only A-Z, 0-9, exactly 6 chars)
        guild_id = self.guild_id.value.upper()
        if not re.match(r'^[A-Z0-9]{6}$', guild_id):
            await interaction.response.send_message(
                "Guild ID must be exactly 6 characters and only contain letters A-Z and numbers 0-9.",
                ephemeral=True
            )
            return

        # Check cooldowns before processing
        user_id = interaction.user.id

        cooldown_check = await self.cog.check_cooldowns(
            interaction,
            user_id,
            guild_id,
            AdvertisementType.GUILD
        )

        if not cooldown_check:
            return

        # Create guild advertisement embed
        embed = discord.Embed(
            title=self.guild_name.value,
            description=self.description.value,
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        embed.set_author(name=f"Guild Ad by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.add_field(name="Guild ID", value=guild_id, inline=True)  # Display uppercase ID
        embed.add_field(name="Leader", value=self.guild_leader.value, inline=True)
        embed.add_field(name="Member Count", value=self.member_count.value, inline=True)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        # Post advertisement and update cooldowns
        thread_title = f"[Guild] {self.guild_name.value} ({guild_id})"
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.GUILD, None)


class MemberAdvertisementForm(Modal, title="Member Advertisement Form"):
    """Modal form for collecting member advertisement information."""

    player_id = TextInput(
        label="Player ID",
        placeholder="Your player ID",
        required=True,
        max_length=50
    )

    weekly_boxes = TextInput(
        label="Weekly Box Count",
        placeholder="How many weekly boxes do you usually clear? (out of 7)",
        required=True,
        max_length=10
    )

    additional_info = TextInput(
        label="Additional Information",
        placeholder="What else should we know about you?",
        required=True,
        max_length=1000,
        style=discord.TextStyle.paragraph
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        # Check if player ID is valid (only A-Z, 0-9)
        player_id = self.player_id.value.upper()
        if not re.match(r'^[A-Z0-9]+$', player_id):
            logger.warning(f"User {interaction.user.id} provided invalid player ID format: {player_id}")
            await interaction.response.send_message(
                "Player ID can only contain letters A-Z and numbers 0-9.",
                ephemeral=True
            )
            return

        # Check cooldowns before processing
        user_id = interaction.user.id

        cooldown_check = await self.cog.check_cooldowns(
            interaction,
            user_id,
            None,
            AdvertisementType.MEMBER
        )

        if not cooldown_check:
            return

        # Create member advertisement embed
        embed = discord.Embed(
            title=f"Player: {interaction.user.name}",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )

        embed.set_author(name=f"Submitted by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

        # Make the Player ID a clickable link (uppercase)
        url_value = f"[{player_id}](https://thetower.lol/player?player={player_id})"
        embed.add_field(name="Player ID", value=url_value, inline=True)
        embed.add_field(name="Weekly Box Count", value=self.weekly_boxes.value, inline=True)
        embed.add_field(name="Additional Info", value=self.additional_info.value, inline=False)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        # Post advertisement and update cooldowns
        thread_title = f"[Member] {interaction.user.name} ({player_id})"
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.MEMBER, None)


class UnifiedAdvertiseCog(commands.Cog):
    """Combined cog for both guild and member advertisements."""

    def __init__(self, bot):
        self.bot = bot
        self.cooldown_hours = 24  # Cooldown period in hours
        self.advertise_channel_id = const.guild_advertise_channel_id  # Using the guild channel for all ads
        self.mod_channel_id = const.rude_people_channel_id

        # Add tag IDs for guild and member advertisements
        self.guild_tag_id = const.guild_tag_id if hasattr(const, 'guild_tag_id') else None
        self.member_tag_id = const.member_tag_id if hasattr(const, 'member_tag_id') else None

        # Data storage paths
        self.data_dir = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(self.data_dir, exist_ok=True)

        self.cooldown_file = os.path.join(self.data_dir, "advertisement_cooldowns.json")
        self.pending_deletions_file = os.path.join(self.data_dir, "advertisement_pending_deletions.pkl")

        # Load stored data
        self.cooldowns = self._load_cooldowns()
        self.pending_deletions = self._load_pending_deletions()

        # Start tasks
        self.check_deletions.start()
        self.weekly_cleanup.start()

        logger.info("UnifiedAdvertiseCog initialized")

    def cog_unload(self):
        """Called when the cog is unloaded."""
        self.weekly_cleanup.cancel()
        self.check_deletions.cancel()

    @tasks.loop(hours=168)  # 168 hours = 1 week
    async def weekly_cleanup(self):
        """Weekly task to clean up expired cooldowns."""
        await self._cleanup_cooldowns()

    @tasks.loop(minutes=1)  # Check for threads to delete every minute (changed from 5 minutes)
    async def check_deletions(self):
        """Check for threads that need to be deleted."""
        current_time = datetime.datetime.now()
        threads_to_delete = []

        for thread_id, deletion_time in self.pending_deletions:
            if current_time >= deletion_time:
                threads_to_delete.append(thread_id)

        # Delete threads that have reached their time
        for thread_id in threads_to_delete:
            try:
                thread = await self.bot.fetch_channel(thread_id)
                await thread.delete()
                logger.info(f"Deleted advertisement thread {thread_id} (scheduled for {deletion_time})")
                print(f"Deleted advertisement thread {thread_id} (scheduled for {deletion_time})")
            except (discord.NotFound, discord.HTTPException) as e:
                logger.error(f"Error deleting thread {thread_id}: {e}")
                print(f"Error deleting thread {thread_id}: {e}")

            # Remove from pending deletions
            self.pending_deletions = [(t_id, t_time) for t_id, t_time in self.pending_deletions if t_id != thread_id]

        if threads_to_delete:
            self._save_pending_deletions()

    @check_deletions.before_loop
    async def before_check_deletions(self):
        """Wait until the bot is ready before starting the deletion check task."""
        await self.bot.wait_until_ready()

    @weekly_cleanup.before_loop
    async def before_weekly_cleanup(self):
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()

        # Calculate time until next midnight
        now = datetime.datetime.now()
        tomorrow = now + datetime.timedelta(days=1)
        midnight = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)
        seconds_until_midnight = (midnight - now).total_seconds()

        # Wait until midnight to start the first run
        await asyncio.sleep(seconds_until_midnight)

    async def _cleanup_cooldowns(self):
        """Remove expired cooldowns from the cooldowns dictionary."""
        try:
            current_time = datetime.datetime.now()
            sections = ['users', 'guilds']
            expired_count = 0

            for section in sections:
                expired_items = []

                for item_id, timestamp in list(self.cooldowns[section].items()):
                    timestamp_dt = datetime.datetime.fromisoformat(timestamp)
                    elapsed = current_time - timestamp_dt
                    if elapsed.total_seconds() > self.cooldown_hours * 3600:
                        expired_items.append(item_id)

                for item_id in expired_items:
                    del self.cooldowns[section][item_id]
                    expired_count += 1

            if expired_count > 0:
                self._save_cooldowns()
                logger.info(f"Weekly cleanup: Removed {expired_count} expired cooldowns")
                print(f"Weekly cleanup: Removed {expired_count} expired cooldowns")
        except Exception as e:
            logger.error(f"Error during cooldown cleanup: {e}")
            print(f"Error during cooldown cleanup: {e}")

    def _load_cooldowns(self):
        """Load cooldowns from file."""
        try:
            if os.path.exists(self.cooldown_file):
                with open(self.cooldown_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading cooldowns: {e}")
            print(f"Error loading cooldowns: {e}")

        # Default structure if file doesn't exist
        return {
            'users': {},
            'guilds': {}
        }

    def _save_cooldowns(self):
        """Save cooldowns to file."""
        try:
            with open(self.cooldown_file, 'w') as f:
                json.dump(self.cooldowns, f)
        except Exception as e:
            logger.error(f"Error saving cooldowns: {e}")
            print(f"Error saving cooldowns: {e}")

    def _load_pending_deletions(self):
        """Load pending message deletions from file."""
        try:
            if os.path.exists(self.pending_deletions_file):
                with open(self.pending_deletions_file, 'rb') as f:
                    return pickle.load(f)
        except Exception as e:
            logger.error(f"Error loading pending deletions: {e}")
            print(f"Error loading pending deletions: {e}")
        return []

    def _save_pending_deletions(self):
        """Save pending message deletions to file."""
        try:
            with open(self.pending_deletions_file, 'wb') as f:
                pickle.dump(self.pending_deletions, f)
        except Exception as e:
            logger.error(f"Error saving pending deletions: {e}")
            print(f"Error saving pending deletions: {e}")

    async def _resume_deletion_tasks(self):
        """Check for threads that were scheduled for deletion before restart."""
        await self.bot.wait_until_ready()

        # No need to create separate tasks or do anything here
        # The check_deletions task will automatically handle all pending deletions
        logger.info(f"Resumed tracking {len(self.pending_deletions)} pending thread deletions")
        print(f"Resumed tracking {len(self.pending_deletions)} pending thread deletions")

    async def check_cooldowns(self, interaction, user_id, guild_id=None, ad_type=None):
        """Check if user or guild is on cooldown and handle the response."""

        # Check user cooldown
        if str(user_id) in self.cooldowns['users']:
            timestamp = self.cooldowns['users'][str(user_id)]
            elapsed = (datetime.datetime.now() - datetime.datetime.fromisoformat(timestamp)).total_seconds()

            if elapsed < self.cooldown_hours * 3600:
                hours_left = self.cooldown_hours - (elapsed / 3600)

                # Send notification to mod channel about bypass attempt
                mod_channel = self.bot.get_channel(self.mod_channel_id)
                if mod_channel:
                    await mod_channel.send(f"⚠️ **Advertisement Cooldown Bypass Attempt**\n"
                                           f"User: {interaction.user.name} (ID: {interaction.user.id})\n"
                                           f"Type: User cooldown ({ad_type})\n"
                                           f"Time remaining: {hours_left:.1f} hours")

                await interaction.response.send_message(
                    f"You can only post one advertisement every {self.cooldown_hours} hours. "
                    f"Please try again in {hours_left:.1f} hours.\n"
                    f"If you attempt to bypass this limit, you will be banned from advertising.",
                    ephemeral=True
                )
                return False

        # Check guild cooldown if applicable
        if guild_id and str(guild_id) in self.cooldowns['guilds']:
            timestamp = self.cooldowns['guilds'][str(guild_id)]
            elapsed = (datetime.datetime.now() - datetime.datetime.fromisoformat(timestamp)).total_seconds()

            if elapsed < self.cooldown_hours * 3600:
                hours_left = self.cooldown_hours - (elapsed / 3600)

                # Send notification to mod channel about guild cooldown bypass attempt
                mod_channel = self.bot.get_channel(self.mod_channel_id)
                if mod_channel:
                    await mod_channel.send(f"⚠️ **Guild Advertisement Cooldown Bypass Attempt**\n"
                                           f"User: {interaction.user.name} (ID: {interaction.user.id})\n"
                                           f"Guild ID: {guild_id}\n"
                                           f"Time remaining: {hours_left:.1f} hours")

                await interaction.response.send_message(
                    f"This guild was already advertised in the past {self.cooldown_hours} hours. "
                    f"Please try again in {hours_left:.1f} hours.\n"
                    f"If you attempt to bypass this limit, your guild will be banned from advertising.",
                    ephemeral=True
                )
                return False

        return True

    async def post_advertisement(self, interaction, embed, thread_title, ad_type, guild_id=None):
        """Post the advertisement as a thread in the forum channel."""
        try:
            # Get the forum channel
            channel = self.bot.get_channel(self.advertise_channel_id)

            if not channel:
                logger.error(f"Advertisement channel not found: {self.advertise_channel_id}")
                await interaction.response.send_message(
                    "There was an error posting your advertisement. Please contact @thedisasterfish.",
                    ephemeral=True
                )
                return

            # Determine which tag to apply based on advertisement type
            applied_tags = []
            if ad_type == AdvertisementType.GUILD and self.guild_tag_id:
                try:
                    # Find the tag object by ID
                    for tag in channel.available_tags:
                        if tag.id == self.guild_tag_id:
                            applied_tags.append(tag)
                            break
                except Exception as e:
                    logger.error(f"Error finding guild tag: {e}")
                    print(f"Error finding guild tag: {e}")

            elif ad_type == AdvertisementType.MEMBER and self.member_tag_id:
                try:
                    # Find the tag object by ID
                    for tag in channel.available_tags:
                        if tag.id == self.member_tag_id:
                            applied_tags.append(tag)
                            break
                except Exception as e:
                    logger.error(f"Error finding member tag: {e}")
                    print(f"Error finding member tag: {e}")

            # Create the forum thread with tags
            thread_with_message = await channel.create_thread(
                name=thread_title,
                content="",  # Empty content
                embed=embed,
                applied_tags=applied_tags,  # Apply the tags
                auto_archive_duration=1440  # Auto-archive after 24 hours
            )

            thread = thread_with_message.thread
            logger.info(f"Created new advertisement thread: {thread.id} for user {interaction.user.id} (type: {ad_type})")

            # Confirm to the user
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Thank you! Your {ad_type} advertisement has been posted. "
                    f"It will remain visible for {self.cooldown_hours} hours.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"Thank you! Your {ad_type} advertisement has been posted. "
                    f"It will remain visible for {self.cooldown_hours} hours.",
                    ephemeral=True
                )

            # Update cooldowns
            current_time = datetime.datetime.now().isoformat()
            self.cooldowns['users'][str(interaction.user.id)] = current_time

            # If it's a guild advertisement, also add guild cooldown
            if guild_id:
                self.cooldowns['guilds'][str(guild_id)] = current_time

            self._save_cooldowns()

            # Schedule thread for deletion
            deletion_time = datetime.datetime.now() + datetime.timedelta(hours=self.cooldown_hours)
            self.pending_deletions.append((thread.id, deletion_time))
            self._save_pending_deletions()
            logger.info(f"Scheduled thread {thread.id} for deletion at {deletion_time}")

        except Exception as e:
            logger.error(f"Error in post_advertisement: {e}", exc_info=True)
            print(f"Error in post_advertisement: {e}")
            if interaction.response.is_done():
                await interaction.followup.send(
                    "There was an error posting your advertisement. Please contact @thedisasterfish.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "There was an error posting your advertisement. Please contact @thedisasterfish.",
                    ephemeral=True
                )

    # Add new owner-only DM commands
    @commands.command(name="owner_delete_post")
    async def owner_delete_post(self, ctx, message_url: str):
        """Delete a post based on message URL and remove it from pending deletions.

        Only works for the bot owner in DMs.
        """
        # Check if command is used by bot owner in DMs
        if not await self._check_owner_dm(ctx):
            return

        try:
            # Extract channel and message IDs from URL
            # Example URL: https://discord.com/channels/guild_id/channel_id/message_id
            parts = message_url.split('/')
            if len(parts) < 7:
                await ctx.send("Invalid message URL format. Expected: https://discord.com/channels/guild_id/channel_id/message_id")
                return

            channel_id = int(parts[-2])

            # Try to fetch the channel (should be a thread)
            try:
                thread = await self.bot.fetch_channel(channel_id)

                # Delete the thread
                await thread.delete()

                # Remove from pending deletions
                updated_list = []
                deleted = False

                for thread_id, deletion_time in self.pending_deletions:
                    if thread_id == channel_id:
                        deleted = True
                    else:
                        updated_list.append((thread_id, deletion_time))

                if deleted:
                    self.pending_deletions = updated_list
                    self._save_pending_deletions()
                    logger.info(f"Owner manually deleted thread {channel_id} and removed from pending deletions")
                    await ctx.send("Successfully deleted thread and removed from pending deletions.")
                else:
                    logger.info(f"Owner manually deleted thread {channel_id} (not in pending deletions)")
                    await ctx.send("Successfully deleted thread, but it wasn't in the pending deletions list.")

            except discord.NotFound:
                logger.warning(f"Owner tried to delete non-existent thread {channel_id}")
                await ctx.send("Thread not found. It might have been already deleted.")
            except discord.Forbidden:
                logger.error(f"No permission to delete thread {channel_id}")
                await ctx.send("I don't have permission to delete that thread.")
            except Exception as e:
                logger.error(f"Error deleting thread {channel_id}: {str(e)}")
                await ctx.send(f"Error deleting thread: {str(e)}")

        except Exception as e:
            logger.error(f"Error processing owner_delete_post command: {str(e)}")
            await ctx.send(f"Error processing command: {str(e)}")

    @commands.command(name="owner_reset_timeout")
    async def owner_reset_timeout(self, ctx, timeout_type: str, identifier: str):
        """Reset a timeout for a user or guild.

        timeout_type: 'user' or 'guild'
        identifier: Discord user ID or Guild ID
        Only works for the bot owner in DMs.
        """
        # Check if command is used by bot owner in DMs
        if not await self._check_owner_dm(ctx):
            return

        try:
            timeout_type = timeout_type.lower()

            if timeout_type not in ['user', 'guild']:
                await ctx.send("Invalid timeout type. Use 'user' or 'guild'.")
                return

            # Map timeout type to the cooldowns dictionary key
            cooldown_key = 'users' if timeout_type == 'user' else 'guilds'

            # Check if the identifier exists in the cooldowns
            if identifier in self.cooldowns[cooldown_key]:
                # Remove the timeout
                del self.cooldowns[cooldown_key][identifier]
                self._save_cooldowns()
                await ctx.send(f"Successfully reset {timeout_type} timeout for {identifier}.")
            else:
                await ctx.send(f"No timeout found for {timeout_type} {identifier}.")

        except Exception as e:
            await ctx.send(f"Error processing command: {str(e)}")

    @commands.command(name="owner_list_timeouts")
    async def owner_list_timeouts(self, ctx, timeout_type: str = None):
        """List all active timeouts.

        timeout_type: Optional 'user' or 'guild' to filter results
        Only works for the bot owner in DMs.
        """
        # Check if command is used by bot owner in DMs
        if not await self._check_owner_dm(ctx):
            return

        try:
            now = datetime.datetime.now()
            sections = []

            # Determine which sections to show
            if timeout_type:
                timeout_type = timeout_type.lower()
                if timeout_type not in ['user', 'guild']:
                    await ctx.send("Invalid timeout type. Use 'user', 'guild' or omit for all.")
                    return

                if timeout_type == 'user':
                    sections = ['users']
                else:
                    sections = ['guilds']
            else:
                # Show all sections if no type specified
                sections = ['users', 'guilds']

            # Build the message
            result = []

            for section in sections:
                if not self.cooldowns[section]:
                    result.append(f"No active {section} timeouts.")
                    continue

                result.append(f"**{section.capitalize()} Timeouts:**")

                for item_id, timestamp in self.cooldowns[section].items():
                    timestamp_dt = datetime.datetime.fromisoformat(timestamp)
                    elapsed = now - timestamp_dt
                    hours_left = self.cooldown_hours - (elapsed.total_seconds() / 3600)

                    if hours_left > 0:
                        result.append(f"- ID: `{item_id}`, Time left: {hours_left:.1f} hours")
                    else:
                        result.append(f"- ID: `{item_id}`, **EXPIRED** ({abs(hours_left):.1f} hours ago)")

                result.append("")  # Add a blank line between sections

            # Send the message
            if result:
                await ctx.send("\n".join(result))
            else:
                await ctx.send("No active timeouts found.")

        except Exception as e:
            await ctx.send(f"Error processing command: {str(e)}")

    @commands.command(name="owner_list_pending")
    async def owner_list_pending(self, ctx):
        """List all pending deletions.

        Only works for the bot owner in DMs.
        """
        # Check if command is used by bot owner in DMs
        if not await self._check_owner_dm(ctx):
            return

        try:
            now = datetime.datetime.now()

            if not self.pending_deletions:
                await ctx.send("No pending thread deletions.")
                return

            result = ["**Pending Thread Deletions:**"]

            for thread_id, deletion_time in self.pending_deletions:
                time_left = deletion_time - now
                hours_left = time_left.total_seconds() / 3600

                thread_url = f"https://discord.com/channels/{const.guild_id}/{thread_id}"

                if hours_left > 0:
                    result.append(f"- Thread ID: `{thread_id}`, Time left: {hours_left:.1f} hours\n  URL: {thread_url}")
                else:
                    result.append(f"- Thread ID: `{thread_id}`, **OVERDUE** by {abs(hours_left):.1f} hours\n  URL: {thread_url}")

            # Send the message(s) - discord has a 2000 char limit
            messages = []
            current_msg = ""

            for line in result:
                if len(current_msg) + len(line) + 1 > 1990:  # Leave some buffer
                    messages.append(current_msg)
                    current_msg = line
                else:
                    if current_msg:
                        current_msg += "\n" + line
                    else:
                        current_msg = line

            if current_msg:
                messages.append(current_msg)

            for msg in messages:
                await ctx.send(msg)

        except Exception as e:
            await ctx.send(f"Error processing command: {str(e)}")

    async def _check_owner_dm(self, ctx):
        """Check if the command is being used by the bot owner in DMs."""
        # Check if command is in DMs
        if not isinstance(ctx.channel, discord.DMChannel):
            logger.warning(f"Non-DM attempt to use owner command from {ctx.author.id}")
            return False

        # Check if user is bot owner
        if ctx.author.id != self.bot.owner_id:
            logger.warning(f"Non-owner {ctx.author.id} attempted to use owner command")
            await ctx.send("This command is only available to the bot owner.")
            return False

        return True

    @app_commands.command(name="advertise", description="Create a guild or member advertisement")
    async def advertise_slash(self, interaction: discord.Interaction):
        """Slash command for advertisement."""
        # Create the selection view
        view = AdTypeSelection(self)

        # Show the advertisement type selection
        await interaction.response.send_message(
            "What type of advertisement would you like to post?",
            view=view,
            ephemeral=True
        )


async def setup(bot) -> None:
    await bot.add_cog(UnifiedAdvertiseCog(bot))

    # Sync the slash commands
    try:
        guild = discord.Object(id=const.guild_id)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    except Exception as e:
        logger.error(f"Error syncing app commands: {e}")
        print(f"Error syncing app commands: {e}")
