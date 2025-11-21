# Standard library imports
import re
from typing import TYPE_CHECKING

# Third-party imports
import discord
from discord.ui import Button, Modal, TextInput, View

from thetower.bot.ui.context import SettingsViewContext

if TYPE_CHECKING:
    from ..cog import UnifiedAdvertise


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
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.GUILD, guild_id, notify)

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            if self.interaction:  # Only try to send message if we have an interaction
                await self.interaction.response.send_message("The form timed out. Please try submitting your advertisement again.", ephemeral=True)
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

    def __init__(self, cog: "UnifiedAdvertise") -> None:
        """Initialize the view with a reference to the cog.

        Args:
            cog: The UnifiedAdvertise cog instance
        """
        super().__init__(timeout=900)  # 15 minute timeout
        self.cog = cog
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
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.MEMBER, None, notify)

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            if self.interaction:  # Only try to send message if we have an interaction
                await self.interaction.response.send_message("The form timed out. Please try submitting your advertisement again.", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass
