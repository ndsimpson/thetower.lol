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
from fish_bot import const


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
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.GUILD, guild_id)


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
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.MEMBER)


class UnifiedAdvertiseCog(commands.Cog):
    """Combined cog for both guild and member advertisements."""

    def __init__(self, bot):
        self.bot = bot
        self.cooldown_hours = 6  # Cooldown period in hours
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
        self.bot.loop.create_task(self._resume_deletion_tasks())
        self.weekly_cleanup.start()

    def cog_unload(self):
        """Called when the cog is unloaded."""
        self.weekly_cleanup.cancel()

    @tasks.loop(hours=168)  # 168 hours = 1 week
    async def weekly_cleanup(self):
        """Weekly task to clean up expired cooldowns."""
        await self._cleanup_cooldowns()

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
            print(f"Weekly cleanup: Removed {expired_count} expired cooldowns")

    def _load_cooldowns(self):
        """Load cooldowns from file."""
        try:
            if os.path.exists(self.cooldown_file):
                with open(self.cooldown_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
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
            print(f"Error saving cooldowns: {e}")

    def _load_pending_deletions(self):
        """Load pending message deletions from file."""
        try:
            if os.path.exists(self.pending_deletions_file):
                with open(self.pending_deletions_file, 'rb') as f:
                    return pickle.load(f)
        except Exception as e:
            print(f"Error loading pending deletions: {e}")
        return []

    def _save_pending_deletions(self):
        """Save pending message deletions to file."""
        try:
            with open(self.pending_deletions_file, 'wb') as f:
                pickle.dump(self.pending_deletions, f)
        except Exception as e:
            print(f"Error saving pending deletions: {e}")

    async def _resume_deletion_tasks(self):
        """Resume deletion tasks for threads that were scheduled before restart."""
        await self.bot.wait_until_ready()

        current_time = datetime.datetime.now()
        new_pending = []

        for item in self.pending_deletions:
            # Forum posts are stored with 2 elements (thread_id, deletion_time)
            is_forum_thread = len(item) == 2

            if is_forum_thread:
                thread_id, deletion_time = item

                if current_time >= deletion_time:
                    # Thread should already be deleted
                    try:
                        thread = await self.bot.fetch_channel(thread_id)
                        await thread.delete()
                        print(f"Deleted advertisement thread {thread_id} after restart")
                    except (discord.NotFound, discord.HTTPException):
                        # Thread already deleted or not found
                        pass
                else:
                    # Schedule this thread for deletion
                    delay = (deletion_time - current_time).total_seconds()
                    self.bot.loop.create_task(self._delete_thread_after_delay(thread_id, delay))
                    new_pending.append(item)
            else:
                # Handle old format for backward compatibility
                # We can just ignore old format items as they use different files
                pass

        self.pending_deletions = new_pending
        self._save_pending_deletions()

    async def _delete_thread_after_delay(self, thread_id, delay):
        """Delete a thread after a specified delay in seconds."""
        await asyncio.sleep(delay)
        try:
            thread = await self.bot.fetch_channel(thread_id)
            await thread.delete()
            print(f"Deleted advertisement thread {thread_id} after {delay / 3600:.1f} hours")

            # Remove from pending deletions
            self.pending_deletions = [item for item in self.pending_deletions if item[0] != thread_id]
            self._save_pending_deletions()
        except (discord.NotFound, discord.HTTPException) as e:
            print(f"Error deleting thread {thread_id}: {e}")
            # Still remove from pending deletions if the thread is gone
            self.pending_deletions = [item for item in self.pending_deletions if item[0] != thread_id]
            self._save_pending_deletions()

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
                await interaction.response.send_message(
                    "There was an error posting your advertisement. Please contact a moderator.",
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
                    print(f"Error finding guild tag: {e}")

            elif ad_type == AdvertisementType.MEMBER and self.member_tag_id:
                try:
                    # Find the tag object by ID
                    for tag in channel.available_tags:
                        if tag.id == self.member_tag_id:
                            applied_tags.append(tag)
                            break
                except Exception as e:
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

            # Create task to delete the thread after delay
            self.bot.loop.create_task(
                self._delete_thread_after_delay(thread.id, self.cooldown_hours * 3600)
            )

        except Exception as e:
            print(f"Error in post_advertisement: {e}")
            if interaction.response.is_done():
                await interaction.followup.send(
                    "There was an error posting your advertisement. Please contact a moderator.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "There was an error posting your advertisement. Please contact a moderator.",
                    ephemeral=True
                )

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
        print(f"Error syncing app commands: {e}")
