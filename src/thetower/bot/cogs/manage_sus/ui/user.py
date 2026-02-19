# User-facing interface for the Manage Sus cog

import discord

from .core import ModerationRecordSearch


class GameInstanceSelectionView(discord.ui.View):
    """View for selecting which game instance to manage when a player has multiple."""

    def __init__(self, cog, details: dict, requesting_user: discord.User, guild_id: int, game_instances: list):
        super().__init__(timeout=300)
        self.cog = cog
        self.details = details
        self.requesting_user = requesting_user
        self.guild_id = guild_id
        self.game_instances = game_instances

        # Add a select dropdown with game instances
        self.add_item(GameInstanceSelect(cog, details, requesting_user, guild_id, game_instances))


class GameInstanceSelect(discord.ui.Select):
    """Dropdown to select which game instance to manage."""

    def __init__(self, cog, details: dict, requesting_user: discord.User, guild_id: int, game_instances: list):
        self.cog = cog
        self.details = details
        self.requesting_user = requesting_user
        self.guild_id = guild_id
        self.game_instances = game_instances

        # Build options from game instances
        options = []
        for instance in game_instances:
            instance_name = instance["account_name"]
            primary_id = instance["primary_player_id"]
            is_primary = instance["primary"]

            # Add star emoji for primary instance
            label = f"{instance_name} ⭐" if is_primary else instance_name
            description = f"ID: {primary_id}"

            options.append(discord.SelectOption(label=label, description=description, value=primary_id))  # Use player ID as value

        super().__init__(placeholder="Select a game account...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        """Handle selection of a game instance."""
        selected_player_id = self.values[0]

        # Create a new details dict with the selected player ID
        moderation_details = {**self.details, "primary_id": selected_player_id}

        # Open the moderation view for this player ID
        view = PlayerModerationView(self.cog, moderation_details, self.requesting_user, self.guild_id)
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)


class PlayerModerationView(discord.ui.View):
    """View for managing a specific player's moderation records."""

    def __init__(self, cog, details: dict, requesting_user: discord.User, guild_id: int):
        super().__init__(timeout=900)
        self.cog = cog
        self.details = details
        self.requesting_user = requesting_user
        self.guild_id = guild_id
        self.show_all_records = False  # Default to showing active only
        self.records = []
        self.search = ModerationRecordSearch(cog)

        # Add buttons
        self.add_item(ToggleViewButton())
        self.add_item(RefreshButton())

        # Load initial records
        # We'll load them when update_view is called

    async def _get_creator_display(self, record) -> str:
        """Get a human-readable display of who created this record."""
        from asgiref.sync import sync_to_async

        # Access Django relationships asynchronously
        created_by = await sync_to_async(lambda: record.created_by)()
        if created_by:
            username = await sync_to_async(lambda: created_by.username)()
            return f"Admin: {username}"

        if record.created_by_discord_id:
            # Try to fetch Discord user to get their username
            try:
                user = await self.cog.bot.fetch_user(int(record.created_by_discord_id))
                return f"@{user.name}"
            except Exception:
                # Fallback to ID if user fetch fails
                return f"Discord ID: {record.created_by_discord_id}"

        created_by_api_key = await sync_to_async(lambda: record.created_by_api_key)()
        if created_by_api_key:
            user = await sync_to_async(lambda: created_by_api_key.user)()
            username = await sync_to_async(lambda: user.username)()
            return f"API: {username}"

        return "System"

    async def update_view(self, interaction: discord.Interaction) -> discord.Embed:
        """Update the view and return the embed to display."""
        try:
            # Get the primary player ID from details
            primary_id = self.details.get("primary_id")

            if not primary_id:
                embed = discord.Embed(
                    title="❌ No Primary ID",
                    description="This player doesn't have a primary ID set.",
                    color=discord.Color.red(),
                )
                return embed

            # Load records
            self.records = await self.search.search_records(tower_id=primary_id, active_only=not self.show_all_records, limit=50)

            # Create embed
            embed = discord.Embed(
                title="⚖️ Moderation Records",
                description=f"Player ID: `{primary_id}`",
                color=discord.Color.blue(),
            )

            # Add view toggle info
            view_mode = "All Records" if self.show_all_records else "Active Records Only"
            embed.add_field(
                name="📊 View Mode",
                value=f"Currently showing: **{view_mode}**\nClick 'Toggle View' to switch",
                inline=False,
            )

            # Add records summary
            if self.records:
                active_count = sum(1 for r in self.records if r.is_active)
                resolved_count = len(self.records) - active_count

                embed.add_field(
                    name="📈 Records Summary",
                    value=f"**Total:** {len(self.records)}\n**Active:** {active_count}\n**Resolved:** {resolved_count}",
                    inline=True,
                )

                # Show records
                for record in self.records[:5]:  # Show first 5 records
                    status_emoji = "🔴" if record.is_active else "✅"
                    status_text = "Active" if record.is_active else "Resolved"

                    # Get creator display with Discord username if available
                    created_by = await self._get_creator_display(record)

                    record_info = (
                        f"**Type:** {record.get_moderation_type_display()}\n"
                        f"**Status:** {status_text}\n"
                        f"**Created:** {record.created_at.strftime('%Y-%m-%d')}\n"
                        f"**Created By:** {created_by}"
                    )

                    if record.reason:
                        # Truncate reason if too long
                        reason = record.reason[:100] + "..." if len(record.reason) > 100 else record.reason
                        record_info += f"\n**Reason:** {reason}"

                    embed.add_field(
                        name=f"{status_emoji} Record #{record.id}",
                        value=record_info,
                        inline=False,
                    )

                if len(self.records) > 5:
                    embed.add_field(
                        name="📄 More Records",
                        value=f"... and {len(self.records) - 5} more records",
                        inline=False,
                    )
            else:
                embed.add_field(
                    name="📭 No Records",
                    value="No moderation records found for this player.",
                    inline=False,
                )

            # Add active moderation actions if user has manage permissions
            can_manage = await self.cog._user_can_manage_moderation_records(self.requesting_user)
            if can_manage:
                active_records = [r for r in self.records if r.is_active]
                # Clear existing action buttons and add new ones
                self.clear_items()

                # Re-add standard buttons
                self.add_item(ToggleViewButton())
                self.add_item(RefreshButton())

                # Check for active sus and ban records
                active_sus = next((r for r in active_records if r.moderation_type == "sus"), None)
                active_ban = next((r for r in active_records if r.moderation_type == "ban"), None)
                active_shun = next((r for r in active_records if r.moderation_type == "shun"), None)

                # Add shun options first (independent of ban status)
                if active_shun:
                    self.add_item(UnshunButton(active_shun))
                else:
                    self.add_item(ShunButton(primary_id))

                # Add sus/ban buttons based on current state
                if active_ban:
                    # If banned, show unban button and don't show sus options
                    self.add_item(UnbanButton(active_ban))
                else:
                    # If not banned, show sus options
                    if active_sus:
                        self.add_item(UnsusButton(active_sus))
                    else:
                        self.add_item(SusButton(primary_id))
                    self.add_item(BanButton(primary_id))

                if active_records:
                    # Add resolve buttons for other active records (soft_ban, etc.)
                    other_active = [r for r in active_records if r.moderation_type not in ["sus", "ban", "shun"]]
                    for record in other_active[:3]:  # Limit to 3 to avoid UI clutter
                        resolve_button = ResolveModerationButton(record)
                        self.add_item(resolve_button)

                    embed.add_field(
                        name="🔧 Management Actions",
                        value="Use the buttons below to manage moderation records.",
                        inline=False,
                    )
                else:
                    embed.add_field(
                        name="🔧 Management Actions",
                        value="Use the buttons below to create new moderation records.",
                        inline=False,
                    )

            embed.set_footer(text="Session expires in 15 minutes • Use buttons to manage records")
            return embed

        except Exception as e:
            self.cog.logger.error(f"Error updating player moderation view: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to load moderation records. Please try again.",
                color=discord.Color.red(),
            )
            return embed


class ToggleViewButton(discord.ui.Button):
    """Button to toggle between showing all records and active only."""

    def __init__(self):
        super().__init__(label="Toggle View", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="toggle_view")

    async def callback(self, interaction: discord.Interaction):
        """Handle toggle view button click."""
        view = self.view
        view.show_all_records = not view.show_all_records

        # Update the embed
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)


class RefreshButton(discord.ui.Button):
    """Button to refresh the moderation records view."""

    def __init__(self):
        super().__init__(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="refresh_records")

    async def callback(self, interaction: discord.Interaction):
        """Handle refresh button click."""
        view = self.view

        # Update the embed
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)


class ResolveModerationButton(discord.ui.Button):
    """Button to resolve a specific moderation record."""

    def __init__(self, record):
        # Create appropriate label based on moderation type
        mod_type = record.moderation_type
        if mod_type == "sus":
            label = "Unsus"
            emoji = "👀"
        elif mod_type == "ban":
            label = "Unban"
            emoji = "🔓"
        elif mod_type == "shun":
            label = "Unshun"
            emoji = "🔊"
        elif mod_type == "soft_ban":
            label = "Remove Soft Ban"
            emoji = "⚠️"
        else:
            label = "Resolve"
            emoji = "✅"

        super().__init__(label=f"{label} #{record.id}", style=discord.ButtonStyle.success, emoji=emoji, custom_id=f"resolve_{record.id}")
        self.record = record

    async def callback(self, interaction: discord.Interaction):
        """Handle resolve button click."""
        # Show modal to enter resolution notes
        modal = ResolveModerationModal(self.view.cog, self.record)
        await interaction.response.send_modal(modal)


class ResolveModerationModal(discord.ui.Modal):
    """Modal for entering resolution notes when resolving a moderation record."""

    def __init__(self, cog, record):
        # Create appropriate title based on moderation type
        mod_type = record.moderation_type
        if mod_type == "sus":
            title = f"Unsus Player {record.tower_id}"
        elif mod_type == "ban":
            title = f"Unban Player {record.tower_id}"
        elif mod_type == "shun":
            title = f"Unshun Player {record.tower_id}"
        elif mod_type == "soft_ban":
            title = f"Remove Soft Ban for {record.tower_id}"
        else:
            title = f"Resolve Moderation for {record.tower_id}"

        super().__init__(title=title)
        self.cog = cog
        self.record = record

        self.notes_input = discord.ui.TextInput(
            label="Resolution Notes (optional)",
            placeholder="Enter any notes about this resolution...",
            default="",
            required=False,
            max_length=1000,
            style=discord.TextStyle.paragraph,
        )

        self.add_item(self.notes_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle resolution form submission."""
        try:
            notes = self.notes_input.value.strip() or None
            from asgiref.sync import sync_to_async
            from django.utils import timezone

            # Restrict ban resolution to API or bot owner
            if self.record.moderation_type == "ban":
                # Check if API or bot owner
                # is_api variable removed (not used)
                is_owner = False
                # Check API context (not available in bot UI, so only bot owner allowed)
                bot_owner_id = getattr(self.cog.bot, "owner_id", None)
                if bot_owner_id and str(interaction.user.id) == str(bot_owner_id):
                    is_owner = True
                # Optionally, check for API context if available
                # If not API or owner, block resolution
                if not (is_owner):
                    await interaction.response.send_message("❌ Only the API or bot owner may resolve a ban.", ephemeral=True)
                    return

            # Update the record with resolution notes
            if notes:
                if self.record.reason:
                    self.record.reason += f"\n\n--- Resolution Notes ({timezone.now().strftime('%Y-%m-%d %H:%M UTC')}) ---\n{notes}"
                else:
                    self.record.reason = f"--- Resolution Notes ({timezone.now().strftime('%Y-%m-%d %H:%M UTC')}) ---\n{notes}"

            # Mark as resolved
            self.record.resolved_at = timezone.now()
            self.record.resolved_by_discord_id = str(interaction.user.id)
            # Try to set resolved_by (Django user) if linked
            from thetower.backend.sus.models import KnownPlayer
            known_player = await sync_to_async(KnownPlayer.get_by_discord_id)(interaction.user.id)
            if known_player and known_player.django_user:
                self.record.resolved_by = known_player.django_user
            await sync_to_async(self.record.save)()

            embed = discord.Embed(
                title="✅ Moderation Resolved",
                description=f"Successfully resolved {self.record.get_moderation_type_display()} record #{self.record.id} for player {self.record.tower_id}.",
                color=discord.Color.green(),
            )
            if notes:
                embed.add_field(name="Resolution Notes", value=notes, inline=False)

            await interaction.response.send_message(embed=embed, ephemeral=True)

            # Refresh the parent view
            embed = await self.view.update_view(interaction)
            await interaction.followup.edit_message(embed=embed, view=self.view)

        except Exception as e:
            self.cog.logger.error(f"Error resolving moderation record: {e}")
            await interaction.response.send_message("❌ Failed to resolve the moderation record. Please try again.", ephemeral=True)


class SusButton(discord.ui.Button):
    """Button to create a new sus record for the player."""

    def __init__(self, tower_id):
        super().__init__(label="Sus", style=discord.ButtonStyle.danger, emoji="👀", custom_id=f"sus_{tower_id}")
        self.tower_id = tower_id

    async def callback(self, interaction: discord.Interaction):
        """Handle sus button click."""
        from asgiref.sync import sync_to_async
        from thetower.backend.sus.models import ModerationRecord
        # Check for existing active sus
        existing_active = await sync_to_async(list)(
            ModerationRecord.objects.filter(tower_id=self.tower_id, moderation_type="sus", resolved_at__isnull=True)
        )
        if existing_active:
            # Show modal to add notes to existing sus
            modal = AddSusNotesModal(self.view.cog, existing_active[0])
            await interaction.response.send_modal(modal)
        else:
            # Show modal to create new sus
            modal = CreateModerationModal(self.view.cog, self.tower_id, "sus")
            await interaction.response.send_modal(modal)


class AddSusNotesModal(discord.ui.Modal):
    """Modal for adding notes to an existing sus record."""

    def __init__(self, cog, record):
        super().__init__(title=f"Add Notes to SUS for {record.tower_id}")
        self.cog = cog
        self.record = record
        self.notes_input = discord.ui.TextInput(
            label="Additional Notes",
            placeholder="Enter additional notes...",
            default="",
            required=True,
            max_length=1000,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.notes_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            notes = self.notes_input.value.strip()
            from django.utils import timezone
            if notes:
                timestamp = timezone.now().strftime('%Y-%m-%d %H:%M UTC')
                if self.record.reason:
                    self.record.reason += f"\n\n--- Additional Notes ({timestamp}) ---\n{notes}"
                else:
                    self.record.reason = f"--- Additional Notes ({timestamp}) ---\n{notes}"
                from asgiref.sync import sync_to_async
                await sync_to_async(self.record.save)()
            embed = discord.Embed(
                title="✅ Notes Added",
                description=f"Notes added to SUS record #{self.record.id} for player {self.record.tower_id}.",
                color=discord.Color.green(),
            )
            embed.add_field(name="Notes", value=notes, inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            # Refresh parent view
            embed = await self.view.update_view(interaction)
            await interaction.followup.edit_message(embed=embed, view=self.view)
        except Exception as e:
            self.cog.logger.error(f"Error adding notes to sus record: {e}")
            await interaction.response.send_message("❌ Failed to add notes. Please try again.", ephemeral=True)


class BanButton(discord.ui.Button):
    """Button to create a new ban record for the player."""

    def __init__(self, tower_id):
        super().__init__(label="Ban", style=discord.ButtonStyle.danger, emoji="🚫", custom_id=f"ban_{tower_id}")
        self.tower_id = tower_id

    async def callback(self, interaction: discord.Interaction):
        """Handle ban button click."""
        # Show modal to enter reason
        modal = CreateModerationModal(self.view.cog, self.tower_id, "ban")
        await interaction.response.send_modal(modal)


class UnsusButton(discord.ui.Button):
    """Button to resolve an active sus record for the player."""

    def __init__(self, record):
        super().__init__(label="Unsus", style=discord.ButtonStyle.success, emoji="👀", custom_id=f"unsus_{record.id}")
        self.record = record

    async def callback(self, interaction: discord.Interaction):
        """Handle unsus button click."""
        # Show modal to enter resolution notes
        modal = ResolveModerationModal(self.view.cog, self.record)
        await interaction.response.send_modal(modal)


class UnbanButton(discord.ui.Button):
    """Button to resolve an active ban record for the player."""

    def __init__(self, record):
        super().__init__(label="Unban", style=discord.ButtonStyle.success, emoji="🔓", custom_id=f"unban_{record.id}")
        self.record = record

    async def callback(self, interaction: discord.Interaction):
        """Handle unban button click."""
        # Show modal to enter resolution notes
        modal = ResolveModerationModal(self.view.cog, self.record)
        await interaction.response.send_modal(modal)


class ShunButton(discord.ui.Button):
    """Button to create a new shun record for the player."""

    def __init__(self, tower_id):
        super().__init__(label="Shun", style=discord.ButtonStyle.danger, emoji="🔇", custom_id=f"shun_{tower_id}")
        self.tower_id = tower_id

    async def callback(self, interaction: discord.Interaction):
        """Handle shun button click."""
        # Show modal to enter reason
        modal = CreateModerationModal(self.view.cog, self.tower_id, "shun")
        await interaction.response.send_modal(modal)


class UnshunButton(discord.ui.Button):
    """Button to resolve an active shun record for the player."""

    def __init__(self, record):
        super().__init__(label="Unshun", style=discord.ButtonStyle.success, emoji="🔊", custom_id=f"unshun_{record.id}")
        self.record = record

    async def callback(self, interaction: discord.Interaction):
        """Handle unshun button click."""
        # Show modal to enter resolution notes
        modal = ResolveModerationModal(self.view.cog, self.record)
        await interaction.response.send_modal(modal)


class CreateModerationModal(discord.ui.Modal):
    """Modal for creating a new moderation record."""

    def __init__(self, cog, tower_id, moderation_type):
        title = f"Create {moderation_type.upper()} Record for {tower_id}"
        super().__init__(title=title)
        self.cog = cog
        self.tower_id = tower_id
        self.moderation_type = moderation_type

        self.reason_input = discord.ui.TextInput(
            label="Reason (required)",
            placeholder="Enter the reason for this moderation action...",
            default="",
            required=True,
            max_length=1000,
            style=discord.TextStyle.paragraph,
        )

        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle creation form submission."""
        try:
            reason = self.reason_input.value.strip()
            if not reason:
                await interaction.response.send_message("❌ Reason is required.", ephemeral=True)
                return

            from asgiref.sync import sync_to_async
            from thetower.backend.sus.models import ModerationRecord, KnownPlayer
            from django.utils import timezone

            # Enforce only one active moderation status at a time
            existing_active = await sync_to_async(list)(
                ModerationRecord.objects.filter(tower_id=self.tower_id, resolved_at__isnull=True)
            )
            existing_sus = next((r for r in existing_active if r.moderation_type == "sus"), None)
            existing_ban = next((r for r in existing_active if r.moderation_type == "ban"), None)

            # Prevent sus if banned
            if self.moderation_type == "sus" and existing_ban:
                await interaction.response.send_message("❌ Cannot mark as sus while banned.", ephemeral=True)
                return

            # Prevent ban if already banned
            if self.moderation_type == "ban" and existing_ban:
                await interaction.response.send_message("❌ Player is already banned.", ephemeral=True)
                return

            # If banning, auto-resolve sus
            if self.moderation_type == "ban" and existing_sus:
                existing_sus.resolved_at = timezone.now()
                existing_sus.resolved_by_discord_id = str(interaction.user.id)
                # Try to set resolved_by (Django user) if linked
                known_player = await sync_to_async(KnownPlayer.get_by_discord_id)(interaction.user.id)
                if known_player and known_player.django_user:
                    existing_sus.resolved_by = known_player.django_user
                await sync_to_async(existing_sus.save)()

            # Try to set created_by (Django user) if linked
            known_player = await sync_to_async(KnownPlayer.get_by_discord_id)(interaction.user.id)
            created_by_user = known_player.django_user if known_player and known_player.django_user else None

            # Create the new moderation record
            await sync_to_async(ModerationRecord.objects.create)(
                tower_id=self.tower_id,
                moderation_type=self.moderation_type,
                source=ModerationRecord.ModerationSource.BOT,
                created_by_discord_id=str(interaction.user.id),
                created_by=created_by_user,
                reason=reason,
            )

            embed = discord.Embed(
                title="✅ Moderation Record Created",
                description=f"Successfully created {self.moderation_type.upper()} record for player {self.tower_id}.",
                color=discord.Color.green(),
            )
            embed.add_field(name="Reason", value=reason, inline=False)

            await interaction.response.send_message(embed=embed, ephemeral=True)

            # Refresh the parent view
            embed = await self.view.update_view(interaction)
            await interaction.followup.edit_message(embed=embed, view=self.view)

        except Exception as e:
            self.cog.logger.error(f"Error creating moderation record: {e}")
            await interaction.response.send_message("❌ Failed to create the moderation record. Please try again.", ephemeral=True)


class SusManagementView(discord.ui.View):
    """Button to search for moderation records."""

    def __init__(self):
        super().__init__(label="Search Records", style=discord.ButtonStyle.primary, emoji="🔍", custom_id="search_records")

    async def callback(self, interaction: discord.Interaction):
        """Handle search button click."""
        # Show search modal
        modal = SearchModal(self.view.cog)
        await interaction.response.send_modal(modal)


class MyRecordsButton(discord.ui.Button):
    """Button to view user's own records."""

    def __init__(self):
        super().__init__(label="My Records", style=discord.ButtonStyle.secondary, emoji="📋", custom_id="my_records")

    async def callback(self, interaction: discord.Interaction):
        """Handle my records button click."""
        view = self.view

        # Search for records created by this user
        try:
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import ModerationRecord

            # Get records created by this Discord user
            records = await sync_to_async(list)(
                ModerationRecord.objects.filter(created_by_discord_id=str(interaction.user.id)).order_by("-created_at")[: view.results_per_page]
            )

            view.records = records
            view.current_page = 0

            embed = await view._create_records_embed()
            await interaction.response.edit_message(embed=embed, view=view)

        except Exception as e:
            view.cog.logger.error(f"Error loading user records: {e}")
            embed = discord.Embed(title="Error", description="Failed to load your records. Please try again.", color=discord.Color.red())
            await interaction.response.edit_message(embed=embed, view=view)


class SearchModal(discord.ui.Modal):
    """Modal for searching moderation records."""

    def __init__(self, cog):
        super().__init__(title="Search Moderation Records")
        self.cog = cog

        self.tower_id_input = discord.ui.TextInput(
            label="Tower ID (optional)",
            placeholder="Enter Tower player ID to search for",
            required=False,
            max_length=32,
        )

        self.type_input = discord.ui.TextInput(
            label="Moderation Type (optional)",
            placeholder="sus, ban, shun, or soft_ban",
            required=False,
            max_length=20,
        )

        self.active_only_input = discord.ui.TextInput(
            label="Active Only",
            placeholder="true or false (default: false)",
            default="false",
            required=False,
            max_length=5,
        )

        self.add_item(self.tower_id_input)
        self.add_item(self.type_input)
        self.add_item(self.active_only_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle search form submission."""
        try:
            tower_id = self.tower_id_input.value.strip() or None
            mod_type = self.type_input.value.strip().lower() or None
            active_only_str = self.active_only_input.value.strip().lower()
            active_only = active_only_str in ["true", "1", "yes", "on"]

            # Validate moderation type if provided
            if mod_type and mod_type not in ["sus", "ban", "shun", "soft_ban"]:
                await interaction.response.send_message("❌ Invalid moderation type. Must be one of: sus, ban, shun, soft_ban", ephemeral=True)
                return

            # Perform search
            search = ModerationRecordSearch(self.cog)
            limit = 50

            records = await search.search_records(tower_id=tower_id, moderation_type=mod_type, active_only=active_only, limit=limit)

            # Create results view
            view = SearchResultsView(self.cog, records, tower_id, mod_type, active_only)
            embed = await view.create_embed()

            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error in search: {e}")
            await interaction.response.send_message("❌ An error occurred while searching. Please try again.", ephemeral=True)


class SearchResultsView(discord.ui.View):
    """View for displaying search results."""

    def __init__(self, cog, records, tower_id=None, mod_type=None, active_only=False):
        super().__init__(timeout=900)
        self.cog = cog
        self.records = records
        self.tower_id = tower_id
        self.mod_type = mod_type
        self.active_only = active_only
        self.current_page = 0
        self.results_per_page = 5

        # Load settings
        # Results per page is hardcoded to 5

        # Add navigation buttons if needed
        if len(records) > self.results_per_page:
            self.add_item(PrevPageButton())
            self.add_item(NextPageButton())

        # Add back button
        self.add_item(BackButton())

    async def create_embed(self) -> discord.Embed:
        """Create the embed for current page of results."""
        start_idx = self.current_page * self.results_per_page
        end_idx = start_idx + self.results_per_page
        page_records = self.records[start_idx:end_idx]

        embed = discord.Embed(title=f"🔍 Search Results ({len(self.records)} total)", color=discord.Color.blue())

        # Add search criteria
        criteria = []
        if self.tower_id:
            criteria.append(f"Tower ID: `{self.tower_id}`")
        if self.mod_type:
            criteria.append(f"Type: {self.mod_type}")
        if self.active_only:
            criteria.append("Active only: Yes")

        if criteria:
            embed.add_field(name="Search Criteria", value="\n".join(criteria), inline=False)

        # Add records
        if page_records:
            for i, record in enumerate(page_records, start_idx + 1):
                embed.add_field(
                    name=f"Record #{record.id}",
                    value=f"**Player:** {record.tower_id}\n**Type:** {record.get_moderation_type_display()}\n**Status:** {'Active' if record.is_active else 'Resolved'}",
                    inline=True,
                )
        else:
            embed.add_field(name="No Results", value="No moderation records found matching your criteria.", inline=False)

        # Add pagination info
        if len(self.records) > self.results_per_page:
            total_pages = (len(self.records) - 1) // self.results_per_page + 1
            embed.set_footer(text=f"Page {self.current_page + 1}/{total_pages} • {len(self.records)} total results")

        return embed


class PrevPageButton(discord.ui.Button):
    """Button to go to previous page."""

    def __init__(self):
        super().__init__(label="Previous", style=discord.ButtonStyle.secondary, emoji="⬅️", custom_id="prev_page")

    async def callback(self, interaction: discord.Interaction):
        """Handle previous page button click."""
        view = self.view
        if view.current_page > 0:
            view.current_page -= 1
            embed = await view.create_embed()
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.defer()


class NextPageButton(discord.ui.Button):
    """Button to go to next page."""

    def __init__(self):
        super().__init__(label="Next", style=discord.ButtonStyle.secondary, emoji="➡️", custom_id="next_page")

    async def callback(self, interaction: discord.Interaction):
        """Handle next page button click."""
        view = self.view
        max_page = (len(view.records) - 1) // view.results_per_page
        if view.current_page < max_page:
            view.current_page += 1
            embed = await view.create_embed()
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.defer()


class BackButton(discord.ui.Button):
    """Button to go back to main view."""

    def __init__(self):
        super().__init__(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", custom_id="back_to_main")

    async def callback(self, interaction: discord.Interaction):
        """Handle back button click."""
        # Return to main management view
        from .user import SusManagementView

        view = SusManagementView(self.view.cog, interaction.user.id, interaction.guild.id)
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)
