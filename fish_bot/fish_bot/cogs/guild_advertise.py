import discord
from discord.ext import commands, tasks
from typing import Dict, Optional
from fish_bot import const
import datetime  # Add this import
import json
import os
import asyncio
import pickle
from discord import app_commands


class GuildFormState:
    """Tracks the state of a user's guild form submission."""

    questions = [
        "What is your guild name?",
        "What is your guild id?",
        "Who is the guild leader?",
        "How many active members do you have?",
        "Tell us a brief description of your guild:"
    ]

    # Abbreviated versions for the embed display
    question_labels = [
        "Guild Name",
        "Guild ID",
        "Leader",
        "Member Count",
        "Description"
    ]

    def __init__(self):
        self.current_question = 0
        self.answers = []
        self.active = True

    def is_complete(self) -> bool:
        return self.current_question >= len(self.questions)

    def get_current_question(self) -> Optional[str]:
        if self.is_complete():
            return None
        return self.questions[self.current_question]

    def add_answer(self, answer: str):
        self.answers.append(answer)
        self.current_question += 1


class GuildForm(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.form_states: Dict[int, GuildFormState] = {}  # User ID -> form state
        self.guild_channel_id = const.guild_advertise_channel_id
        self.mod_channel_id = const.rude_people_channel_id
        self.prefix = "!guild"  # Custom prefix for this cog
        self.cooldown_hours = 6  # Cooldown period in hours
        self.cooldown_file = os.path.join(os.path.dirname(__file__), "data", "guild_cooldowns.json")
        # Track both user and guild cooldowns
        self.cooldowns = self._load_cooldowns()  # Load cooldowns from file
        self.pending_deletions_file = os.path.join(os.path.dirname(__file__), "data", "pending_deletions.pkl")
        self.pending_deletions = self._load_pending_deletions()
        self.bot.loop.create_task(self._resume_deletion_tasks())
        self.weekly_cleanup.start()

    def cog_unload(self):
        """Called when the cog is unloaded. Cancel any scheduled tasks."""
        self.weekly_cleanup.cancel()

    @tasks.loop(hours=168)  # 168 hours = 1 week
    async def weekly_cleanup(self):
        """Weekly task to clean up expired cooldowns and other data files."""
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
        expired_users = []
        expired_guilds = []

        # Find users with expired cooldowns
        for user_id, timestamp in list(self.cooldowns['users'].items()):
            elapsed = current_time - timestamp
            if elapsed.total_seconds() > self.cooldown_hours * 3600:
                expired_users.append(user_id)

        # Find guilds with expired cooldowns
        for guild_id, timestamp in list(self.cooldowns['guilds'].items()):
            elapsed = current_time - timestamp
            if elapsed.total_seconds() > self.cooldown_hours * 3600:
                expired_guilds.append(guild_id)

        # Remove expired cooldowns
        for user_id in expired_users:
            del self.cooldowns['users'][user_id]

        for guild_id in expired_guilds:
            del self.cooldowns['guilds'][guild_id]

        # If any were removed, save the updated cooldowns
        if expired_users or expired_guilds:
            self._save_cooldowns()
            print(f"Weekly cleanup: Removed {len(expired_users)} expired user cooldowns and {len(expired_guilds)} expired guild cooldowns")
        else:
            print("Weekly cleanup: No expired cooldowns found")

    def _load_cooldowns(self) -> Dict[str, Dict[str, datetime.datetime]]:
        """Load cooldowns from file."""
        try:
            if os.path.exists(self.cooldown_file):
                with open(self.cooldown_file, 'r') as f:
                    cooldown_dict = json.load(f)

                    # Convert nested structure with string timestamps back to datetime objects
                    result = {
                        'users': {},
                        'guilds': {}
                    }

                    if 'users' in cooldown_dict:
                        result['users'] = {int(user_id): datetime.datetime.fromisoformat(timestamp)
                                           for user_id, timestamp in cooldown_dict['users'].items()}

                    if 'guilds' in cooldown_dict:
                        result['guilds'] = {guild_id: datetime.datetime.fromisoformat(timestamp)
                                            for guild_id, timestamp in cooldown_dict['guilds'].items()}

                    return result

        except Exception as e:
            print(f"Error loading cooldowns: {e}")

        # Return empty structure if file doesn't exist or there's an error
        return {'users': {}, 'guilds': {}}

    def _save_cooldowns(self):
        """Save cooldowns to file."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.cooldown_file), exist_ok=True)

            # Convert datetime objects to ISO format strings
            cooldown_dict = {
                'users': {str(user_id): timestamp.isoformat()
                          for user_id, timestamp in self.cooldowns['users'].items()},
                'guilds': {str(guild_id): timestamp.isoformat()
                           for guild_id, timestamp in self.cooldowns['guilds'].items()}
            }

            with open(self.cooldown_file, 'w') as f:
                json.dump(cooldown_dict, f)

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
            os.makedirs(os.path.dirname(self.pending_deletions_file), exist_ok=True)
            with open(self.pending_deletions_file, 'wb') as f:
                pickle.dump(self.pending_deletions, f)
        except Exception as e:
            print(f"Error saving pending deletions: {e}")

    async def _resume_deletion_tasks(self):
        """Resume deletion tasks for messages that were scheduled before restart."""
        await self.bot.wait_until_ready()

        current_time = datetime.datetime.now()
        new_pending = []

        for channel_id, message_id, deletion_time in self.pending_deletions:
            if current_time >= deletion_time:
                # Message should already be deleted
                try:
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        try:
                            message = await channel.fetch_message(message_id)
                            await message.delete()
                            print(f"Deleted message {message_id} after restart")
                        except discord.NotFound:
                            # Message already deleted or not found
                            pass
                except Exception as e:
                    print(f"Error deleting message after restart: {e}")
            else:
                # Schedule this message for deletion
                delay = (deletion_time - current_time).total_seconds()
                self.bot.loop.create_task(self._delete_after_delay(channel_id, message_id, delay))
                new_pending.append((channel_id, message_id, deletion_time))

        self.pending_deletions = new_pending
        self._save_pending_deletions()

    async def _delete_after_delay(self, channel_id, message_id, delay):
        """Delete a message after a specified delay in seconds."""
        await asyncio.sleep(delay)
        try:
            channel = self.bot.get_channel(channel_id)
            if channel:
                message = await channel.fetch_message(message_id)
                await message.delete()
                print(f"Deleted message {message_id} after {delay / 3600:.1f} hours")

                # Remove from pending deletions
                self.pending_deletions = [(c, m, d) for c, m, d in self.pending_deletions
                                          if m != message_id]
                self._save_pending_deletions()
        except Exception as e:
            print(f"Error deleting message: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore bot messages
        if message.author.bot:
            return

        # Check for the custom prefix (case insensitive)
        if message.content.lower().startswith(self.prefix.lower()):
            # Extract the command name and make it lowercase
            cmd = message.content[len(self.prefix):].strip().lower()

            # Process the custom prefixed command
            if cmd == "advertise":
                # Create a fake context
                ctx = await self.bot.get_context(message)
                await self.start_guild_registration(ctx)
                return

        # Continue with existing form processing logic for DMs
        if message.guild is not None:
            return

        # Check if user has an active form
        user_id = message.author.id
        if user_id not in self.form_states or not self.form_states[user_id].active:
            return

        # Check for cancellation (case insensitive)
        if message.content.lower() == "cancel":
            self.form_states[user_id].active = False
            return await message.channel.send("Guild advertisement cancelled.")

        # Process the answer
        form_state = self.form_states[user_id]
        form_state.add_answer(message.content)

        # Check if form is complete
        if form_state.is_complete():
            await self._process_completed_form(message.channel, message.author)
        else:
            # Pass both channel and user_id
            await self._send_next_question(message.channel, user_id)

    async def start_guild_registration(self, ctx):
        """Start the guild registration process via DM."""
        # Only allow in DMs
        if ctx.guild is not None:
            return await ctx.send("Please use this command in a direct message.")

        user_id = ctx.author.id

        # Check user cooldown
        if user_id in self.cooldowns['users']:
            elapsed = datetime.datetime.now() - self.cooldowns['users'][user_id]
            if elapsed.total_seconds() < self.cooldown_hours * 3600:  # Convert hours to seconds
                hours_left = self.cooldown_hours - (elapsed.total_seconds() / 3600)

                # Send notification to mod channel about bypass attempt
                mod_channel = self.bot.get_channel(self.mod_channel_id)
                if mod_channel:
                    await mod_channel.send(f"⚠️ **Guild Cooldown Bypass Attempt**\n"
                                           f"User: {ctx.author.name} (ID: {ctx.author.id})\n"
                                           f"Type: User cooldown\n"
                                           f"Time remaining: {hours_left:.1f} hours")

                return await ctx.send(f"You can only advertise once every {self.cooldown_hours} hours. "
                                      f"Please try again in {hours_left:.1f} hours."
                                      f"If you or a member of your guild attempts to bypass this limit, your guild will be banned from advertising.")

        # Check if form is already in progress
        if user_id in self.form_states and self.form_states[user_id].active:
            return await ctx.send("You already have a guild form in progress. Please complete it first.")

        # Create new form state
        self.form_states[user_id] = GuildFormState()

        await ctx.send("Welcome to the guild advertisement process! I'll ask you a series of questions. "
                       "Type 'cancel' at any time to stop.\n\n"
                       "Let's begin!")

        # Send first question - pass both ctx and user_id
        await self._send_next_question(ctx, user_id)

    async def _send_next_question(self, channel, user_id):
        """Send the next question to the user."""
        form_state = self.form_states[user_id]

        question = form_state.get_current_question()
        if question:
            await channel.send(f"**{question}**")

    async def _process_completed_form(self, channel, user):
        """Process a completed form and post it to the guild channel."""
        form_state = self.form_states[user.id]
        form_state.active = False

        # Get the guild ID from the form answers (second question)
        guild_id = form_state.answers[1]  # Guild ID is the second answer
        guild_name = form_state.answers[0]  # Guild name is the first answer

        # Check if this guild is on cooldown
        if guild_id in self.cooldowns['guilds']:
            elapsed = datetime.datetime.now() - self.cooldowns['guilds'][guild_id]
            if elapsed.total_seconds() < self.cooldown_hours * 3600:
                hours_left = self.cooldown_hours - (elapsed.total_seconds() / 3600)

                # Send notification to mod channel about guild cooldown bypass attempt
                mod_channel = self.bot.get_channel(self.mod_channel_id)
                if mod_channel:
                    await mod_channel.send(f"⚠️ **Guild Cooldown Bypass Attempt**\n"
                                           f"User: {user.name} (ID: {user.id})\n"
                                           f"Guild: {guild_name} (ID: {guild_id})\n"
                                           f"Type: Guild cooldown\n"
                                           f"Time remaining: {hours_left:.1f} hours")

                await channel.send(f"This guild was already advertised in the past {self.cooldown_hours} hours. "
                                   f"Please try again in {hours_left:.1f} hours."
                                   f"If you or a member of your guild attempts to bypass this limit, your guild will be banned from advertising.")
                return

        # Record submission time for both user and guild cooldowns
        now = datetime.datetime.now()
        self.cooldowns['users'][user.id] = now
        self.cooldowns['guilds'][guild_id] = now
        self._save_cooldowns()  # Save cooldowns after updating

        # Create the embed for the guild channel with the guild name as title
        embed = discord.Embed(
            title=form_state.answers[0],  # Use the guild name as title
            color=discord.Color.blue()
        )

        embed.set_author(name=f"Submitted by {user.name}", icon_url=user.avatar.url if user.avatar else None)

        # Add all answers as fields, but skip the first one (guild name) since it's now the title
        for i, question in enumerate(form_state.questions):
            # Skip the first question since it's now the title
            if i == 0:
                continue

            # Use the abbreviated labels for the embed fields
            label = form_state.question_labels[i]

            # Make the description field larger
            if i == 4:  # Index of the description question
                embed.add_field(name=label, value=form_state.answers[i], inline=False)
            else:
                embed.add_field(name=label, value=form_state.answers[i], inline=True)

        embed.set_footer(text=f"DM TowerBot to submit your own guild advertisement using:  {self.prefix} advertise ")
        embed.timestamp = discord.utils.utcnow()

        # Send to the guild channel
        guild_channel = self.bot.get_channel(self.guild_channel_id)

        if guild_channel:
            # Send the embed and get the message object
            sent_message = await guild_channel.send(embed=embed)
            await channel.send("Thank you! Your guild advertisement has been submitted."
                               " This guild may not be advertised for another 6 hours.")

            # Schedule message for deletion after cooldown period
            deletion_time = datetime.datetime.now() + datetime.timedelta(hours=self.cooldown_hours)
            self.pending_deletions.append((guild_channel.id, sent_message.id, deletion_time))
            self._save_pending_deletions()

            # Create a task to delete the message after the delay
            self.bot.loop.create_task(
                self._delete_after_delay(guild_channel.id, sent_message.id, self.cooldown_hours * 3600)
            )
        else:
            await channel.send("There was an error submitting your guild advertisement. Please contact @disasterfish.")

        self.form_states[user.id].active = False

    # Add the slash command implementation
    @app_commands.command(name="guild", description="Advertise your guild to find new members")
    async def guild_slash(self, interaction: discord.Interaction):
        """Slash command to start the guild advertisement process."""
        # Respond to the interaction immediately
        await interaction.response.send_message(
            "I'll send you a DM to collect information for your guild advertisement.",
            ephemeral=True
        )

        # Get or create DM channel
        try:
            dm_channel = await interaction.user.create_dm()

            # Call the guild registration process with the DM channel
            await self.start_guild_registration_slash(dm_channel, interaction.user)
        except discord.Forbidden:
            await interaction.followup.send(
                "I couldn't DM you. Please make sure your privacy settings allow DMs from server members.",
                ephemeral=True
            )

    async def start_guild_registration_slash(self, channel, user):
        """Start the guild registration process via DM (for slash command)."""
        user_id = user.id

        # Check user cooldown
        if user_id in self.cooldowns['users']:
            elapsed = datetime.datetime.now() - self.cooldowns['users'][user_id]
            if elapsed.total_seconds() < self.cooldown_hours * 3600:  # Convert hours to seconds
                hours_left = self.cooldown_hours - (elapsed.total_seconds() / 3600)

                # Send notification to mod channel about bypass attempt
                mod_channel = self.bot.get_channel(self.mod_channel_id)
                if mod_channel:
                    await mod_channel.send(f"⚠️ **Guild Cooldown Bypass Attempt**\n"
                                           f"User: {user.name} (ID: {user.id})\n"
                                           f"Type: User cooldown\n"
                                           f"Time remaining: {hours_left:.1f} hours")

                return await channel.send(f"You can only advertise once every {self.cooldown_hours} hours. "
                                          f"Please try again in {hours_left:.1f} hours."
                                          f"If you or a member of your guild attempts to bypass this limit, your guild will be banned from advertising.")

        # Check if form is already in progress
        if user_id in self.form_states and self.form_states[user_id].active:
            return await channel.send("You already have a guild form in progress. Please complete it first.")

        # Create new form state
        self.form_states[user_id] = GuildFormState()

        await channel.send("Welcome to the guild advertisement process! I'll ask you a series of questions. "
                           "Type 'cancel' at any time to stop.\n\n"
                           "Let's begin!")

        # Send first question - pass both channel and user_id
        await self._send_next_question(channel, user_id)


async def setup(bot) -> None:
    cog = GuildForm(bot)
    await bot.add_cog(cog)

    # Sync the slash commands with Discord
    try:
        # For specific guild testing (faster updates):
        guild = discord.Object(id=const.guild_id)  # Your test server ID
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    except Exception as e:
        print(f"Error syncing app commands: {e}")
