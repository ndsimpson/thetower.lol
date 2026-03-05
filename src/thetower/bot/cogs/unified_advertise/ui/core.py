# Standard library imports
import re

# Third-party imports
import discord
from discord.ui import Button, Modal, Select, TextInput, View

from thetower.bot.ui.context import SettingsViewContext


class AdvertisementType:
    """Constants for advertisement types."""

    GUILD: str = "guild"


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

        # Check cooldowns before processing
        user_id = interaction.user.id
        discord_guild_id = interaction.guild.id if interaction.guild else None

        cooldown_check = await self.cog.check_cooldowns(interaction, user_id, guild_id)
        if not cooldown_check:
            return

        # Create guild advertisement embed
        embed = discord.Embed(
            title=self.guild_name.value, description=self.description.value, color=discord.Color.blue(), timestamp=discord.utils.utcnow()
        )

        embed.set_author(name=f"Guild Ad by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.add_field(name="Guild ID", value=guild_id, inline=True)
        embed.add_field(name="Leader", value=self.guild_leader.value, inline=True)
        embed.add_field(name="Member Count", value=self.member_count.value, inline=True)
        embed.add_field(name="Posted by", value=f"<@{interaction.user.id}>", inline=True)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        thread_title = f"{self.guild_name.value} ({guild_id})"

        form_data = {
            "guild_name": self.guild_name.value,
            "guild_id": guild_id,
            "guild_leader": self.guild_leader.value,
            "member_count": self.member_count.value,
            "description": self.description.value,
        }

        # Check for custom tags — show tag selection view if any are configured
        custom_tags = self.cog._get_custom_tags(discord_guild_id) if discord_guild_id else []
        if custom_tags:
            context = SettingsViewContext(guild_id=discord_guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
            pending = {
                "user_id": user_id,
                "embed": embed,
                "thread_title": thread_title,
                "ad_guild_id": guild_id,
                "notify": self.notify,
                "form_data": form_data,
            }
            view = TagSelectionView(context, pending)
            tag_embed = discord.Embed(
                title="🏷️ Select Tags",
                description="Choose tags for your advertisement, then click **Post Advertisement**.",
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=tag_embed, view=view, ephemeral=True)
        else:
            cooldown_hours = self.cog._get_cooldown_hours(discord_guild_id) if discord_guild_id else 168
            await interaction.response.send_message(
                f"Thank you! Your guild advertisement is being posted. It will remain visible for {cooldown_hours} hours.",
                ephemeral=True,
            )
            await self.cog._send_debug_message(f"Guild form processing completed, posting advertisement for user {interaction.user.id}")
            self.cog.save_last_ad_data(user_id, AdvertisementType.GUILD, form_data)
            await self.cog.post_advertisement(interaction, embed, thread_title, guild_id, self.notify, tag_ids=[])

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            if self.interaction:  # Only try to send message if we have an interaction
                await self.interaction.response.send_message("The form timed out. Please try submitting your advertisement again.", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass


class EditGuildAdvertisementForm(Modal, title="Edit Guild Advertisement"):
    """Modal form for editing guild advertisement information."""

    def __init__(
        self, context: SettingsViewContext, thread_id: int, message_id: int, current_embed: discord.Embed, current_tag_ids: list = None
    ) -> None:
        """Initialize the edit form with current advertisement data.

        Args:
            context: The settings view context
            thread_id: The thread ID of the advertisement
            message_id: The message ID of the starter message
            current_embed: The current embed to extract data from
            current_tag_ids: List of currently applied forum tag IDs
        """
        super().__init__(timeout=900)  # 15 minute timeout
        self.cog = context.cog_instance
        self.context = context
        self.thread_id = thread_id
        self.message_id = message_id
        self.current_tag_ids = current_tag_ids or []
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

        thread_title = f"[Guild] {self.guild_name.value} ({guild_id})"
        form_data = {
            "guild_name": self.guild_name.value,
            "guild_id": guild_id,
            "guild_leader": self.guild_leader.value,
            "member_count": self.member_count.value,
            "description": self.description.value,
        }

        discord_guild_id = interaction.guild.id if interaction.guild else None
        custom_tags = self.cog._get_custom_tags(discord_guild_id) if discord_guild_id else []
        if custom_tags:
            context = SettingsViewContext(guild_id=discord_guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
            pending = {
                "user_id": interaction.user.id,
                "embed": embed,
                "thread_title": thread_title,
                "form_data": form_data,
                "is_edit": True,
                "thread_id": self.thread_id,
                "message_id": self.message_id,
                "saved_tag_ids": self.current_tag_ids,
            }
            view = TagSelectionView(context, pending)
            tag_embed = discord.Embed(
                title="🏷️ Update Tags",
                description="Adjust tags for your advertisement, then click **Update Advertisement**.",
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=tag_embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message("✏️ Updating your advertisement...", ephemeral=True)
            self.cog.save_last_ad_data(interaction.user.id, AdvertisementType.GUILD, {**form_data, "tags": []})
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
    """View for selecting notification preference before submitting a form."""

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
    """Removed — member advertisements are no longer supported.

    This stub is kept temporarily to avoid import errors.
    DO NOT USE.
    """

    pass


class GuildAdvertisementTemplateForm(Modal, title="Guild Advertisement Form"):
    """Pre-filled modal for posting a guild ad using a previous ad as a template."""

    def __init__(self, context: SettingsViewContext, defaults: dict) -> None:
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.notify = True
        self.interaction = None
        # Store saved tag IDs for pre-selection in the tag view
        self._saved_tag_ids: list = defaults.get("tags", [])

        self.guild_name = TextInput(
            label="Guild Name",
            placeholder="Enter your guild's name",
            required=True,
            max_length=100,
            default=defaults.get("guild_name", "")[:100],
        )
        self.guild_id_input = TextInput(
            label="Guild ID",
            placeholder="Enter your guild's ID (e.g. A1B2C3)",
            required=True,
            min_length=6,
            max_length=6,
            default=defaults.get("guild_id", "")[:6],
        )
        self.guild_leader = TextInput(
            label="Guild Leader",
            placeholder="Enter guild leader's name",
            required=True,
            max_length=100,
            default=defaults.get("guild_leader", "")[:100],
        )
        self.member_count = TextInput(
            label="Member Count",
            placeholder="How many active members?",
            required=True,
            max_length=10,
            default=defaults.get("member_count", "")[:10],
        )
        self.description = TextInput(
            label="Guild Description",
            placeholder="Tell us about your guild...",
            required=True,
            max_length=1000,
            style=discord.TextStyle.paragraph,
            default=defaults.get("description", "")[:1000],
        )

        self.add_item(self.guild_name)
        self.add_item(self.guild_id_input)
        self.add_item(self.guild_leader)
        self.add_item(self.member_count)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.interaction = interaction
        await self.cog._send_debug_message(f"Guild ad template form submitted by user {interaction.user.id} ({interaction.user.name})")

        guild_id = self.cog._normalize_guild_id(self.guild_id_input.value)
        if not re.match(r"^[A-Z0-9]{6}$", guild_id):
            await interaction.response.send_message(
                "Guild ID must be exactly 6 characters and only contain letters A-Z and numbers 0-9.", ephemeral=True
            )
            return

        user_id = interaction.user.id
        discord_guild_id = interaction.guild.id if interaction.guild else None

        cooldown_check = await self.cog.check_cooldowns(interaction, user_id, guild_id)
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

        thread_title = f"[Guild] {self.guild_name.value} ({guild_id})"

        form_data = {
            "guild_name": self.guild_name.value,
            "guild_id": guild_id,
            "guild_leader": self.guild_leader.value,
            "member_count": self.member_count.value,
            "description": self.description.value,
        }

        # Check for custom tags — show tag selection with pre-selections if configured
        custom_tags = self.cog._get_custom_tags(discord_guild_id) if discord_guild_id else []
        if custom_tags:
            context = SettingsViewContext(guild_id=discord_guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
            pending = {
                "user_id": user_id,
                "embed": embed,
                "thread_title": thread_title,
                "ad_guild_id": guild_id,
                "notify": self.notify,
                "form_data": form_data,
                "saved_tag_ids": self._saved_tag_ids,
            }
            view = TagSelectionView(context, pending)
            tag_embed = discord.Embed(
                title="🏷️ Select Tags",
                description="Choose tags for your advertisement, then click **Post Advertisement**.",
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=tag_embed, view=view, ephemeral=True)
        else:
            cooldown_hours = self.cog._get_cooldown_hours(discord_guild_id) if discord_guild_id else 168
            await interaction.response.send_message(
                f"Thank you! Your guild advertisement is being posted. It will remain visible for {cooldown_hours} hours.",
                ephemeral=True,
            )
            self.cog.save_last_ad_data(user_id, AdvertisementType.GUILD, form_data)
            await self.cog.post_advertisement(interaction, embed, thread_title, guild_id, self.notify, tag_ids=[])

    async def on_timeout(self) -> None:
        try:
            if self.interaction:
                await self.interaction.response.send_message("The form timed out. Please try submitting your advertisement again.", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass


class TagSelectionView(View):
    """View shown after the advertisement form, allowing users to select custom forum tags.

    Each custom tag group configured by the admin is rendered as follows:
    - type 'group': a Select dropdown (pick one of the options)
    - type 'solo':  a toggle Button (on/off)

    After selecting, the user clicks 'Post Advertisement' to finalize.
    """

    def __init__(self, context: SettingsViewContext, pending_data: dict) -> None:
        """Initialize the tag selection view.

        Args:
            context: Settings view context (provides guild_id and cog_instance)
            pending_data: Dict with keys: user_id, embed, thread_title, ad_guild_id, notify, form_data,
                          and optionally saved_tag_ids (list of int) for pre-selection.
        """
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.pending_data = pending_data
        self.selected_tag_ids: set = {int(t) for t in pending_data.get("saved_tag_ids", [])}
        self._rebuild_items()

    def _rebuild_items(self) -> None:
        """Rebuild all UI items reflecting the current selection state."""
        self.clear_items()
        guild_id = self.context.guild_id
        custom_tags = self.cog._get_custom_tags(guild_id)

        # Pass 1: group selects — one per row, rows 0-3.
        current_row = 0
        for tag_group in custom_tags:
            if tag_group.get("type") != "group":
                continue
            options_data = tag_group.get("options", [])
            if not options_data or current_row >= 4:
                continue
            label = tag_group.get("label", "Tag")
            all_option_ids = {int(opt["tag_id"]) for opt in options_data}
            options = [
                discord.SelectOption(
                    label=opt["name"][:100],
                    value=str(opt["tag_id"]),
                    default=int(opt["tag_id"]) in self.selected_tag_ids,
                )
                for opt in options_data
            ]
            select = Select(placeholder=label[:100], options=options[:25], min_values=0, max_values=1, row=current_row)

            async def group_callback(inter: discord.Interaction, s=select, opt_ids=all_option_ids) -> None:
                for oid in opt_ids:
                    self.selected_tag_ids.discard(oid)
                if s.values:
                    self.selected_tag_ids.add(int(s.values[0]))
                await inter.response.defer()

            select.callback = group_callback
            self.add_item(select)
            current_row += 1

        # Pass 2: solo buttons — pack up to 5 per row, starting after the group rows.
        # The post button is appended last and shares whatever row has space remaining.
        items_in_row = 0
        for tag_group in custom_tags:
            if tag_group.get("type") != "solo":
                continue
            options_data = tag_group.get("options", [])
            if not options_data or current_row > 4:
                continue
            if items_in_row >= 5:
                current_row += 1
                items_in_row = 0
            if current_row > 4:
                break
            label = tag_group.get("label", "Tag")
            opt = options_data[0]
            tag_id = int(opt["tag_id"])
            is_selected = tag_id in self.selected_tag_ids
            btn = Button(
                label=(f"✅ {label}" if is_selected else f"☑️ {label}")[:80],
                style=discord.ButtonStyle.success if is_selected else discord.ButtonStyle.secondary,
                row=current_row,
            )

            async def solo_callback(inter: discord.Interaction, o=opt, b=btn, lbl=label) -> None:
                tid = int(o["tag_id"])
                if tid in self.selected_tag_ids:
                    self.selected_tag_ids.discard(tid)
                    b.style = discord.ButtonStyle.secondary
                    b.label = f"☑️ {lbl}"[:80]
                else:
                    self.selected_tag_ids.add(tid)
                    b.style = discord.ButtonStyle.success
                    b.label = f"✅ {lbl}"[:80]
                await inter.response.edit_message(view=self)

            btn.callback = solo_callback
            self.add_item(btn)
            items_in_row += 1

        # Post/Update button: own row if possible, otherwise shares row 4.
        if items_in_row > 0 and current_row < 4:
            current_row += 1
        current_row = min(current_row, 4)
        is_edit = self.pending_data.get("is_edit", False)
        btn_label = "✏️ Update Advertisement" if is_edit else "📢 Post Advertisement"
        post_btn = Button(label=btn_label, style=discord.ButtonStyle.primary, row=current_row)
        post_btn.callback = self.post_advertisement
        self.add_item(post_btn)

    async def post_advertisement(self, interaction: discord.Interaction) -> None:
        """Gather selected tags and post or update the advertisement."""
        pd = self.pending_data
        form_data = {**pd["form_data"], "tags": list(self.selected_tag_ids)}

        if pd.get("is_edit"):
            await interaction.response.send_message("✏️ Updating your advertisement...", ephemeral=True)
            self.cog.save_last_ad_data(pd["user_id"], AdvertisementType.GUILD, form_data)
            success = await self.cog.update_advertisement(
                interaction, pd["thread_id"], pd["message_id"], pd["embed"], pd["thread_title"], tag_ids=list(self.selected_tag_ids)
            )
            if success:
                await interaction.edit_original_response(content="✅ Your advertisement has been updated successfully!")
            else:
                await interaction.edit_original_response(content="❌ Failed to update advertisement. It may have been deleted.")
        else:
            discord_guild_id = interaction.guild.id if interaction.guild else None
            cooldown_hours = self.cog._get_cooldown_hours(discord_guild_id) if discord_guild_id else 168
            await interaction.response.send_message(
                f"Thank you! Your guild advertisement is being posted. It will remain visible for {cooldown_hours} hours.",
                ephemeral=True,
            )
            self.cog.save_last_ad_data(pd["user_id"], AdvertisementType.GUILD, form_data)
            await self.cog.post_advertisement(
                interaction,
                pd["embed"],
                pd["thread_title"],
                pd["ad_guild_id"],
                pd["notify"],
                tag_ids=list(self.selected_tag_ids),
            )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        try:
            if hasattr(self, "message"):
                await self.message.edit(view=self)
        except discord.NotFound:
            pass
