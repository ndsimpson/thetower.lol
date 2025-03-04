import discord
from discord.ext import commands
from typing import Dict, Optional
from fish_bot import const
import datetime
import json
import os
import asyncio
import pickle


class FormState:
    """Tracks the state of a user's form submission."""

    # Customize these questions for your needs
    questions = [
        "What is your player id?",
        "How many weekly event boxes do you usually clear?  There are 7 boxes total each week (35 completed missions).",
        "What else do we need to know about you?"
    ]

    # Abbreviated versions for the embed display
    question_labels = [
        "Player ID",
        "Weekly Box Count",
        "Additional Info"
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


class FormHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.form_states: Dict[int, FormState] = {}  # User ID -> form state
        self.target_channel_id = const.member_advertise_channel_id  # Set to your target channel
        self.mod_channel_id = const.rude_people_channel_id  # Same mod channel as guild_advertise
        self.prefix = "!guild"  # Custom prefix for this cog
        self.cooldown_hours = 6  # Cooldown period in hours

        # Setup file paths
        self.cooldown_file = os.path.join(os.path.dirname(__file__), "data", "member_cooldowns.json")
        self.pending_deletions_file = os.path.join(os.path.dirname(__file__), "data", "member_pending_deletions.pkl")

        # Load saved data
        self.cooldowns = self._load_cooldowns()
        self.pending_deletions = self._load_pending_deletions()

        # Resume deletion tasks from previous session
        self.bot.loop.create_task(self._resume_deletion_tasks())

    def _load_cooldowns(self) -> Dict[str, Dict[str, datetime.datetime]]:
        """Load cooldowns from file."""
        try:
            if os.path.exists(self.cooldown_file):
                with open(self.cooldown_file, 'r') as f:
                    cooldown_dict = json.load(f)

                    # Convert string timestamps back to datetime objects
                    return {int(user_id): datetime.datetime.fromisoformat(timestamp)
                            for user_id, timestamp in cooldown_dict.items()}

        except Exception as e:
            print(f"Error loading form cooldowns: {e}")

        return {}  # Return empty dict if file doesn't exist or there's an error

    def _save_cooldowns(self):
        """Save cooldowns to file."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.cooldown_file), exist_ok=True)

            # Convert datetime objects to ISO format strings
            cooldown_dict = {str(user_id): timestamp.isoformat()
                             for user_id, timestamp in self.cooldowns.items()}

            with open(self.cooldown_file, 'w') as f:
                json.dump(cooldown_dict, f)

        except Exception as e:
            print(f"Error saving form cooldowns: {e}")

    def _load_pending_deletions(self):
        """Load pending message deletions from file."""
        try:
            if os.path.exists(self.pending_deletions_file):
                with open(self.pending_deletions_file, 'rb') as f:
                    return pickle.load(f)
        except Exception as e:
            print(f"Error loading form pending deletions: {e}")
        return []

    def _save_pending_deletions(self):
        """Save pending message deletions to file."""
        try:
            os.makedirs(os.path.dirname(self.pending_deletions_file), exist_ok=True)
            with open(self.pending_deletions_file, 'wb') as f:
                pickle.dump(self.pending_deletions, f)
        except Exception as e:
            print(f"Error saving form pending deletions: {e}")

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
                            print(f"Deleted form message {message_id} after restart")
                        except discord.NotFound:
                            # Message already deleted or not found
                            pass
                except Exception as e:
                    print(f"Error deleting form message after restart: {e}")
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
                print(f"Deleted form message {message_id} after {delay / 3600:.1f} hours")

                # Remove from pending deletions
                self.pending_deletions = [(c, m, d) for c, m, d in self.pending_deletions
                                          if m != message_id]
                self._save_pending_deletions()
        except Exception as e:
            print(f"Error deleting form message: {e}")

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
            if cmd == "member":
                # Create a fake context
                ctx = await self.bot.get_context(message)
                await self.start_form_process(ctx)
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
            return await message.channel.send("Form submission cancelled.")

        # Process the answer
        form_state = self.form_states[user_id]
        form_state.add_answer(message.content)

        # Check if form is complete
        if form_state.is_complete():
            await self._process_completed_form(message.channel, message.author)
        else:
            # Pass both channel and user_id
            await self._send_next_question(message.channel, user_id)

    async def start_form_process(self, ctx):
        """Start the form submission process via DM."""
        # Only allow in DMs
        if ctx.guild is not None:
            return await ctx.send("Please use this command in a direct message.")

        user_id = ctx.author.id

        # Check cooldown
        if user_id in self.cooldowns:
            elapsed = datetime.datetime.now() - self.cooldowns[user_id]
            if elapsed.total_seconds() < self.cooldown_hours * 3600:  # Convert hours to seconds
                hours_left = self.cooldown_hours - (elapsed.total_seconds() / 3600)

                # Send notification to mod channel about bypass attempt
                mod_channel = self.bot.get_channel(self.mod_channel_id)
                if mod_channel:
                    await mod_channel.send(f"⚠️ **Member Looking Cooldown Bypass Attempt**\n"
                                           f"User: {ctx.author.name} (ID: {ctx.author.id})\n"
                                           f"Type: User cooldown\n"
                                           f"Time remaining: {hours_left:.1f} hours")

                return await ctx.send(f"You can only submit this form once every {self.cooldown_hours} hours. "
                                      f"Please try again in {hours_left:.1f} hours.")

        # Check if form is already in progress
        if user_id in self.form_states and self.form_states[user_id].active:
            return await ctx.send("You already have a form in progress. Please complete it first.")

        # Create new form state
        self.form_states[user_id] = FormState()

        await ctx.send("Welcome to the guild member advertisement process! I'll ask you a series of questions. "
                       "Type 'cancel' at any time to stop.\n\n"
                       "Let's begin!")

        # Send first question
        await self._send_next_question(ctx, user_id)

    async def _send_next_question(self, channel, user_id):
        """Send the next question to the user."""
        form_state = self.form_states[user_id]

        question = form_state.get_current_question()
        if question:
            await channel.send(f"**{question}**")

    async def _process_completed_form(self, channel, user):
        """Process a completed form and post it to the target channel."""
        form_state = self.form_states[user.id]
        form_state.active = False

        # Record submission time for cooldown
        self.cooldowns[user.id] = datetime.datetime.now()
        self._save_cooldowns()

        # Create the embed using the Discord username as the title
        embed = discord.Embed(
            title=f"Player: {user.name}",  # Use Discord username as title
            color=discord.Color.green()
        )

        embed.set_author(name=f"Submitted by {user.name}", icon_url=user.avatar.url if user.avatar else None)

        for i, question in enumerate(form_state.questions):
            # Use the abbreviated labels for the embed fields
            label = form_state.question_labels[i]

            # Make the Player ID (index 0) a clickable link
            if i == 0:
                player_id = form_state.answers[i]
                # Format as Markdown link [text](url)
                url_value = f"[{player_id}](https://thetower.lol/player?player={player_id})"
                embed.add_field(name=label, value=url_value, inline=True)
            elif i == 2:
                embed.add_field(name=label, value=form_state.answers[i], inline=False)
            else:
                embed.add_field(name=label, value=form_state.answers[i], inline=True)

        embed.set_footer(text=f"Use {self.prefix} member to submit your own advertisement.")
        embed.timestamp = discord.utils.utcnow()

        # Send to the target channel
        target_channel = self.bot.get_channel(self.target_channel_id)

        if target_channel:
            # Send the embed and get the message object
            sent_message = await target_channel.send(embed=embed)
            await channel.send("Thank you! Your advertisement has been submitted successfully."
                               f" You may submit another advertisement in {self.cooldown_hours} hours.")

            # Schedule message for deletion after cooldown period
            deletion_time = datetime.datetime.now() + datetime.timedelta(hours=self.cooldown_hours)
            self.pending_deletions.append((target_channel.id, sent_message.id, deletion_time))
            self._save_pending_deletions()

            # Create a task to delete the message after the delay
            self.bot.loop.create_task(
                self._delete_after_delay(target_channel.id, sent_message.id, self.cooldown_hours * 3600)
            )
        else:
            await channel.send("There was an error submitting your advertisement. Please contact @thedisasterfish.")


async def setup(bot) -> None:
    await bot.add_cog(FormHandler(bot))