# Standard library imports
import re

# Third-party imports
import discord
from discord.ui import Button, Modal, TextInput, View

from thetower.bot.ui.context import SettingsViewContext


class AdvertisementType:
    """Constants for advertisement types."""

    GUILD: str = "guild"
    MEMBER: str = "member"


class AdTypeSelection(View):
    """View with buttons to select advertisement type."""

    def __init__(self, context: SettingsViewContext) -> None:
        """Initialize the view with a reference to the cog.

        Args:
            context: The settings view context
        """
        super().__init__(timeout=900)  # 15 minute timeout
        self.cog = context.cog_instance
        self.context = context

    @discord.ui.button(label="Guild Advertisement", style=discord.ButtonStyle.primary, emoji="🏰")
    async def guild_button(self, interaction: discord.Interaction, button: Button) -> None:
        # Defer the response early to prevent timeouts
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        form = GuildAdvertisementForm(self.context)
        view = NotificationView(form)

        if interaction.response.is_done():
            await interaction.followup.send("Please select your notification preference:", view=view, ephemeral=True)
        else:
            await interaction.response.send_message("Please select your notification preference:", view=view, ephemeral=True)

    @discord.ui.button(label="Member Advertisement", style=discord.ButtonStyle.success, emoji="👤")
    async def member_button(self, interaction: discord.Interaction, button: Button) -> None:
        # Defer the response early to prevent timeouts
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        form = MemberAdvertisementForm(self.context)
        view = NotificationView(form)  # Reuse the same NotificationView

        if interaction.response.is_done():
            await interaction.followup.send("Please select your notification preference:", view=view, ephemeral=True)
        else:
            await interaction.response.send_message("Please select your notification preference:", view=view, ephemeral=True)

    async def on_timeout(self) -> None:
        # Disable all buttons when the view times out
        for item in self.children:
            item.disabled = True
        # Try to edit the original message with disabled buttons
        try:
            if hasattr(self, "message"):
                await self.message.edit(view=self)
        except discord.NotFound:
            pass  # Message might have been deleted


class GuildAdvertisementForm(Modal, title="Guild Advertisement Form"):
    """Modal form for collecting guild advertisement information."""

    def __init__(self, context: SettingsViewContext) -> None:
        """Initialize the view with a reference to the cog.

        Args:
            context: The settings view context
        """
        super().__init__(timeout=900)  # 15 minute timeout
        self.cog = context.cog_instance
        self.context = context
        self.notify = True
        self.interaction = None  # Store interaction object

    guild_name = TextInput(label="Guild Name", placeholder="Enter your guild's name", required=True, max_length=100)

    guild_id = TextInput(label="Guild ID", placeholder="Enter your guild's ID (e.g. A1B2C3)", required=True, min_length=6, max_length=6)

    guild_leader = TextInput(label="Guild Leader", placeholder="Enter guild leader's name", required=True, max_length=100)

    member_count = TextInput(label="Member Count", placeholder="How many active members?", required=True, max_length=10)

    description = TextInput(
        label="Guild Description", placeholder="Tell us about your guild...", required=True, max_length=1000, style=discord.TextStyle.paragraph
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        import time

        start_time = time.time()
        self.interaction = interaction  # Store interaction when form is submitted
        await self.cog._send_debug_message(f"Guild advertisement form submitted by user {interaction.user.id} ({interaction.user.name})")

        # Normalize and validate guild ID
        guild_id = self.cog._normalize_guild_id(self.guild_id.value)
        if not re.match(r"^[A-Z0-9]{6}$", guild_id):
            await self.cog._send_debug_message(f"Invalid guild ID format from user {interaction.user.id}: {guild_id}")
            await interaction.response.send_message(
                "Guild ID must be exactly 6 characters and only contain letters A-Z and numbers 0-9.", ephemeral=True
            )
            return

        # Process notification preference
        notify = self.notify

        # Check cooldowns before processing
        user_id = interaction.user.id
        cooldown_start = time.time()

        cooldown_check = await self.cog.check_cooldowns(interaction, user_id, guild_id, AdvertisementType.GUILD)
        cooldown_time = time.time() - cooldown_start
        await self.cog._send_debug_message(f"Cooldown check completed in {cooldown_time:.2f}s for user {interaction.user.id}")

        # Warn if cooldown check took too long
        if cooldown_time > 1.0:
            await self.cog._send_debug_message(f"⚠️ Cooldown check took {cooldown_time:.2f}s - potential timeout risk for user {interaction.user.id}")

        if not cooldown_check:
            return

        # Create guild advertisement embed
        embed = discord.Embed(
            title=self.guild_name.value, description=self.description.value, color=discord.Color.blue(), timestamp=discord.utils.utcnow()
        )

        embed.set_author(name=f"Guild Ad by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.add_field(name="Guild ID", value=guild_id, inline=True)  # Display uppercase ID
        embed.add_field(name="Leader", value=self.guild_leader.value, inline=True)
        embed.add_field(name="Member Count", value=self.member_count.value, inline=True)
        embed.add_field(name="Posted by", value=f"<@{interaction.user.id}>", inline=True)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        # CRITICAL: Respond to interaction IMMEDIATELY before heavy work
        discord_guild_id = interaction.guild.id if interaction.guild else None
        cooldown_hours = self.cog._get_cooldown_hours(discord_guild_id) if discord_guild_id else 168

        await interaction.response.send_message(
            f"Thank you! Your {AdvertisementType.GUILD} advertisement is being posted. " f"It will remain visible for {cooldown_hours} hours.",
            ephemeral=True,
        )

        # Post advertisement and update cooldowns
        thread_title = f"[Guild] {self.guild_name.value} ({guild_id})"
        total_time = time.time() - start_time
        await self.cog._send_debug_message(
            f"Guild form processing completed in {total_time:.2f}s, posting advertisement for user {interaction.user.id}"
        )
        # Save last ad data as a template for future use
        self.cog.save_last_ad_data(interaction.user.id, AdvertisementType.GUILD, {
            "guild_name": self.guild_name.value,
            "guild_id": guild_id,
            "guild_leader": self.guild_leader.value,
            "member_count": self.member_count.value,
            "description": self.description.value,
        })
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.GUILD, guild_id, notify)

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            if self.interaction:  # Only try to send message if we have an interaction
                await self.interaction.response.send_message("The form timed out. Please try submitting your advertisement again.", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass


class EditGuildAdvertisementForm(Modal, title="Edit Guild Advertisement"):
    """Modal form for editing guild advertisement information."""

    def __init__(self, context: SettingsViewContext, thread_id: int, message_id: int, current_embed: discord.Embed) -> None:
        """Initialize the edit form with current advertisement data.

        Args:
            context: The settings view context
            thread_id: The thread ID of the advertisement
            message_id: The message ID of the starter message
            current_embed: The current embed to extract data from
        """
        super().__init__(timeout=900)  # 15 minute timeout
        self.cog = context.cog_instance
        self.context = context
        self.thread_id = thread_id
        self.message_id = message_id
        self.interaction = None

        # Extract current values from embed
        guild_name = current_embed.title or ""
        description = current_embed.description or ""

        # Extract from fields
        guild_id = ""
        leader = ""
        member_count = ""

        for field in current_embed.fields:
            if field.name == "Guild ID":
                guild_id = field.value
            elif field.name == "Leader":
                leader = field.value
            elif field.name == "Member Count":
                member_count = field.value

        # Store guild ID as read-only (not editable)
        self.guild_id_value = guild_id

        # Set default values for text inputs
        self.guild_name = TextInput(
            label="Guild Name", placeholder="Enter your guild's name", required=True, max_length=100, default=guild_name[:100]
        )
        self.guild_leader = TextInput(
            label="Guild Leader", placeholder="Enter guild leader's name", required=True, max_length=100, default=leader[:100]
        )
        self.member_count = TextInput(
            label="Member Count", placeholder="How many active members?", required=True, max_length=10, default=member_count[:10]
        )
        self.description = TextInput(
            label="Guild Description",
            placeholder="Tell us about your guild...",
            required=True,
            max_length=1000,
            style=discord.TextStyle.paragraph,
            default=description[:1000],
        )

        # Add the fields to the modal (guild_id not included - it's read-only)
        self.add_item(self.guild_name)
        self.add_item(self.guild_leader)
        self.add_item(self.member_count)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.interaction = interaction
        await self.cog._send_debug_message(f"Guild advertisement edit form submitted by user {interaction.user.id} ({interaction.user.name})")

        # Use the stored guild ID (not editable)
        guild_id = self.guild_id_value

        # Create updated guild advertisement embed
        embed = discord.Embed(
            title=self.guild_name.value, description=self.description.value, color=discord.Color.blue(), timestamp=discord.utils.utcnow()
        )

        embed.set_author(name=f"Guild Ad by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.add_field(name="Guild ID", value=guild_id, inline=True)
        embed.add_field(name="Leader", value=self.guild_leader.value, inline=True)
        embed.add_field(name="Member Count", value=self.member_count.value, inline=True)
        embed.add_field(name="Posted by", value=f"<@{interaction.user.id}>", inline=True)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        # Update the advertisement
        thread_title = f"[Guild] {self.guild_name.value} ({guild_id})"
        await interaction.response.send_message("✏️ Updating your advertisement...", ephemeral=True)

        success = await self.cog.update_advertisement(interaction, self.thread_id, self.message_id, embed, thread_title)

        if success:
            await interaction.edit_original_response(content="✅ Your advertisement has been updated successfully!")
        else:
            await interaction.edit_original_response(content="❌ Failed to update advertisement. It may have been deleted.")

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            if self.interaction:
                await self.interaction.response.send_message("The form timed out. Please try editing your advertisement again.", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass


class EditMemberAdvertisementForm(Modal, title="Edit Member Advertisement"):
    """Modal form for editing member advertisement information."""

    def __init__(self, context: SettingsViewContext, thread_id: int, message_id: int, current_embed: discord.Embed) -> None:
        """Initialize the edit form with current advertisement data.

        Args:
            context: The settings view context
            thread_id: The thread ID of the advertisement
            message_id: The message ID of the starter message
            current_embed: The current embed to extract data from
        """
        super().__init__(timeout=900)  # 15 minute timeout
        self.cog = context.cog_instance
        self.context = context
        self.thread_id = thread_id
        self.message_id = message_id
        self.interaction = None

        # Extract current values from embed
        player_id = ""
        weekly_boxes = ""
        additional_info = ""

        for field in current_embed.fields:
            if field.name == "Player ID":
                # Extract player ID from markdown link if present
                value = field.value
                if value.startswith("[") and "](" in value:
                    player_id = value.split("[")[1].split("]")[0]
                else:
                    player_id = value
            elif field.name == "Weekly Box Count":
                weekly_boxes = field.value
            elif field.name == "Additional Info":
                additional_info = field.value

        # Set default values for text inputs
        self.player_id = TextInput(label="Player ID", placeholder="Your player ID", required=True, max_length=50, default=player_id[:50])
        self.weekly_boxes = TextInput(
            label="Weekly Box Count",
            placeholder="How many weekly boxes do you usually clear? (out of 7)",
            required=True,
            max_length=10,
            default=weekly_boxes[:10],
        )
        self.additional_info = TextInput(
            label="Additional Information",
            placeholder="What else should we know about you?",
            required=True,
            max_length=1000,
            style=discord.TextStyle.paragraph,
            default=additional_info[:1000],
        )

        # Add the fields to the modal
        self.add_item(self.player_id)
        self.add_item(self.weekly_boxes)
        self.add_item(self.additional_info)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.interaction = interaction

        # Check if player ID is valid (only A-Z, 0-9)
        player_id = self.player_id.value.upper()
        if not re.match(r"^[A-Z0-9]+$", player_id):
            self.cog.logger.warning(f"User {interaction.user.id} provided invalid player ID format: {player_id}")
            await interaction.response.send_message("Player ID can only contain letters A-Z and numbers 0-9.", ephemeral=True)
            return

        # Create updated member advertisement embed
        embed = discord.Embed(title=f"Player: {interaction.user.name}", color=discord.Color.green(), timestamp=discord.utils.utcnow())

        embed.set_author(name=f"Submitted by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

        # Make the Player ID a clickable link (uppercase)
        url_value = f"[{player_id}](https://thetower.lol/player?player={player_id})"
        embed.add_field(name="Player ID", value=url_value, inline=True)
        embed.add_field(name="Weekly Box Count", value=self.weekly_boxes.value, inline=True)
        embed.add_field(name="Posted by", value=f"<@{interaction.user.id}>", inline=True)
        embed.add_field(name="Additional Info", value=self.additional_info.value, inline=False)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        # Update the advertisement
        thread_title = f"[Member] {interaction.user.name} ({player_id})"
        await interaction.response.send_message("✏️ Updating your advertisement...", ephemeral=True)

        success = await self.cog.update_advertisement(interaction, self.thread_id, self.message_id, embed, thread_title)

        if success:
            await interaction.edit_original_response(content="✅ Your advertisement has been updated successfully!")
        else:
            await interaction.edit_original_response(content="❌ Failed to update advertisement. It may have been deleted.")

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            if self.interaction:
                await self.interaction.response.send_message("The form timed out. Please try editing your advertisement again.", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass


class NotificationView(View):
    def __init__(self, form: GuildAdvertisementForm):
        super().__init__(timeout=900)
        self.form = form

    @discord.ui.select(
        placeholder="Would you like to be notified when your ad expires?",
        options=[discord.SelectOption(label="Yes", value="yes", emoji="✉️"), discord.SelectOption(label="No", value="no", emoji="🔕")],
        min_values=1,
        max_values=1,
    )
    async def notify_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.form.notify = select.values[0] == "yes"
        await interaction.response.send_modal(self.form)


class MemberAdvertisementForm(Modal, title="Member Advertisement Form"):
    """Modal form for collecting member advertisement information."""

    def __init__(self, context: SettingsViewContext) -> None:
        """Initialize the view with a reference to the cog.

        Args:
            context: The settings view context
        """
        super().__init__(timeout=900)  # 15 minute timeout
        self.cog = context.cog_instance
        self.context = context
        self.notify = True
        self.interaction = None  # Store interaction object

    player_id = TextInput(label="Player ID", placeholder="Your player ID", required=True, max_length=50)

    weekly_boxes = TextInput(
        label="Weekly Box Count", placeholder="How many weekly boxes do you usually clear? (out of 7)", required=True, max_length=10
    )

    additional_info = TextInput(
        label="Additional Information",
        placeholder="What else should we know about you?",
        required=True,
        max_length=1000,
        style=discord.TextStyle.paragraph,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.interaction = interaction  # Store interaction when form is submitted
        # Check if player ID is valid (only A-Z, 0-9)
        player_id = self.player_id.value.upper()
        if not re.match(r"^[A-Z0-9]+$", player_id):
            self.cog.logger.warning(f"User {interaction.user.id} provided invalid player ID format: {player_id}")
            await interaction.response.send_message("Player ID can only contain letters A-Z and numbers 0-9.", ephemeral=True)
            return

        # Process notification preference
        notify = self.notify

        # Check cooldowns before processing
        user_id = interaction.user.id

        cooldown_check = await self.cog.check_cooldowns(interaction, user_id, None, AdvertisementType.MEMBER)

        if not cooldown_check:
            return

        # Create member advertisement embed
        embed = discord.Embed(title=f"Player: {interaction.user.name}", color=discord.Color.green(), timestamp=discord.utils.utcnow())

        embed.set_author(name=f"Submitted by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

        # Make the Player ID a clickable link (uppercase)
        url_value = f"[{player_id}](https://thetower.lol/player?player={player_id})"
        embed.add_field(name="Player ID", value=url_value, inline=True)
        embed.add_field(name="Weekly Box Count", value=self.weekly_boxes.value, inline=True)
        embed.add_field(name="Posted by", value=f"<@{interaction.user.id}>", inline=True)
        embed.add_field(name="Additional Info", value=self.additional_info.value, inline=False)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        # CRITICAL: Respond to interaction IMMEDIATELY before heavy work
        discord_guild_id = interaction.guild.id if interaction.guild else None
        cooldown_hours = self.cog._get_cooldown_hours(discord_guild_id) if discord_guild_id else 168

        await interaction.response.send_message(
            f"Thank you! Your {AdvertisementType.MEMBER} advertisement is being posted. " f"It will remain visible for {cooldown_hours} hours.",
            ephemeral=True,
        )

        # Post advertisement and update cooldowns
        thread_title = f"[Member] {interaction.user.name} ({player_id})"
        # Save last ad data as a template for future use
        self.cog.save_last_ad_data(interaction.user.id, AdvertisementType.MEMBER, {
            "player_id": player_id,
            "weekly_boxes": self.weekly_boxes.value,
            "additional_info": self.additional_info.value,
        })
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.MEMBER, None, notify)

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            if self.interaction:  # Only try to send message if we have an interaction
                await self.interaction.response.send_message("The form timed out. Please try submitting your advertisement again.", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass


class GuildAdvertisementTemplateForm(Modal, title="Guild Advertisement Form"):
    """Pre-filled modal for posting a guild ad using a previous ad as a template."""

    def __init__(self, context: SettingsViewContext, defaults: dict) -> None:
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.notify = True
        self.interaction = None

        self.guild_name = TextInput(
            label="Guild Name", placeholder="Enter your guild's name", required=True, max_length=100,
            default=defaults.get("guild_name", "")[:100],
        )
        self.guild_id_input = TextInput(
            label="Guild ID", placeholder="Enter your guild's ID (e.g. A1B2C3)", required=True, min_length=6, max_length=6,
            default=defaults.get("guild_id", "")[:6],
        )
        self.guild_leader = TextInput(
            label="Guild Leader", placeholder="Enter guild leader's name", required=True, max_length=100,
            default=defaults.get("guild_leader", "")[:100],
        )
        self.member_count = TextInput(
            label="Member Count", placeholder="How many active members?", required=True, max_length=10,
            default=defaults.get("member_count", "")[:10],
        )
        self.description = TextInput(
            label="Guild Description", placeholder="Tell us about your guild...", required=True, max_length=1000,
            style=discord.TextStyle.paragraph, default=defaults.get("description", "")[:1000],
        )

        self.add_item(self.guild_name)
        self.add_item(self.guild_id_input)
        self.add_item(self.guild_leader)
        self.add_item(self.member_count)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        import time

        self.interaction = interaction
        await self.cog._send_debug_message(f"Guild ad template form submitted by user {interaction.user.id} ({interaction.user.name})")

        guild_id = self.cog._normalize_guild_id(self.guild_id_input.value)
        if not re.match(r"^[A-Z0-9]{6}$", guild_id):
            await interaction.response.send_message(
                "Guild ID must be exactly 6 characters and only contain letters A-Z and numbers 0-9.", ephemeral=True
            )
            return

        user_id = interaction.user.id
        cooldown_check = await self.cog.check_cooldowns(interaction, user_id, guild_id, AdvertisementType.GUILD)
        if not cooldown_check:
            return

        embed = discord.Embed(
            title=self.guild_name.value, description=self.description.value, color=discord.Color.blue(), timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=f"Guild Ad by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.add_field(name="Guild ID", value=guild_id, inline=True)
        embed.add_field(name="Leader", value=self.guild_leader.value, inline=True)
        embed.add_field(name="Member Count", value=self.member_count.value, inline=True)
        embed.add_field(name="Posted by", value=f"<@{interaction.user.id}>", inline=True)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        discord_guild_id = interaction.guild.id if interaction.guild else None
        cooldown_hours = self.cog._get_cooldown_hours(discord_guild_id) if discord_guild_id else 168
        await interaction.response.send_message(
            f"Thank you! Your {AdvertisementType.GUILD} advertisement is being posted. It will remain visible for {cooldown_hours} hours.",
            ephemeral=True,
        )

        # Save updated template data (captures any edits the user made to the pre-filled form)
        self.cog.save_last_ad_data(interaction.user.id, AdvertisementType.GUILD, {
            "guild_name": self.guild_name.value,
            "guild_id": guild_id,
            "guild_leader": self.guild_leader.value,
            "member_count": self.member_count.value,
            "description": self.description.value,
        })

        thread_title = f"[Guild] {self.guild_name.value} ({guild_id})"
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.GUILD, guild_id, self.notify)

    async def on_timeout(self) -> None:
        try:
            if self.interaction:
                await self.interaction.response.send_message("The form timed out. Please try submitting your advertisement again.", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass


class MemberAdvertisementTemplateForm(Modal, title="Member Advertisement Form"):
    """Pre-filled modal for posting a member ad using a previous ad as a template."""

    def __init__(self, context: SettingsViewContext, defaults: dict) -> None:
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.notify = True
        self.interaction = None

        self.player_id = TextInput(
            label="Player ID", placeholder="Your player ID", required=True, max_length=50,
            default=defaults.get("player_id", "")[:50],
        )
        self.weekly_boxes = TextInput(
            label="Weekly Box Count", placeholder="How many weekly boxes do you usually clear? (out of 7)", required=True, max_length=10,
            default=defaults.get("weekly_boxes", "")[:10],
        )
        self.additional_info = TextInput(
            label="Additional Information", placeholder="What else should we know about you?", required=True, max_length=1000,
            style=discord.TextStyle.paragraph, default=defaults.get("additional_info", "")[:1000],
        )

        self.add_item(self.player_id)
        self.add_item(self.weekly_boxes)
        self.add_item(self.additional_info)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.interaction = interaction
        player_id = self.player_id.value.upper()
        if not re.match(r"^[A-Z0-9]+$", player_id):
            self.cog.logger.warning(f"User {interaction.user.id} provided invalid player ID format: {player_id}")
            await interaction.response.send_message("Player ID can only contain letters A-Z and numbers 0-9.", ephemeral=True)
            return

        user_id = interaction.user.id
        cooldown_check = await self.cog.check_cooldowns(interaction, user_id, None, AdvertisementType.MEMBER)
        if not cooldown_check:
            return

        embed = discord.Embed(title=f"Player: {interaction.user.name}", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        embed.set_author(name=f"Submitted by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        url_value = f"[{player_id}](https://thetower.lol/player?player={player_id})"
        embed.add_field(name="Player ID", value=url_value, inline=True)
        embed.add_field(name="Weekly Box Count", value=self.weekly_boxes.value, inline=True)
        embed.add_field(name="Posted by", value=f"<@{interaction.user.id}>", inline=True)
        embed.add_field(name="Additional Info", value=self.additional_info.value, inline=False)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        discord_guild_id = interaction.guild.id if interaction.guild else None
        cooldown_hours = self.cog._get_cooldown_hours(discord_guild_id) if discord_guild_id else 168
        await interaction.response.send_message(
            f"Thank you! Your {AdvertisementType.MEMBER} advertisement is being posted. It will remain visible for {cooldown_hours} hours.",
            ephemeral=True,
        )

        # Save updated template data (captures any edits the user made to the pre-filled form)
        self.cog.save_last_ad_data(interaction.user.id, AdvertisementType.MEMBER, {
            "player_id": player_id,
            "weekly_boxes": self.weekly_boxes.value,
            "additional_info": self.additional_info.value,
        })

        thread_title = f"[Member] {interaction.user.name} ({player_id})"
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.MEMBER, None, self.notify)

    async def on_timeout(self) -> None:
        try:
            if self.interaction:
                await self.interaction.response.send_message("The form timed out. Please try submitting your advertisement again.", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass
