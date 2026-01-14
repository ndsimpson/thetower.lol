# Administrative interface for the Manage Sus cog

import discord

from .core import ModerationRecordForm, ModerationRecordSearch, format_moderation_record_embed


class AdminSusManagementView(discord.ui.View):
    """Administrative view for managing moderation records."""

    def __init__(self, cog, guild_id: int, preselected_player_id: str = None):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.preselected_player_id = preselected_player_id
        self.search = ModerationRecordSearch(cog)
        self.current_page = 0
        self.records = []
        self.results_per_page = 10

        # Load settings
        # Results per page is hardcoded to 10

        # Add buttons
        self.add_item(CreateRecordButton())
        self.add_item(SearchButton())
        self.add_item(BulkActionsButton())

    async def _get_creator_display(self, record) -> str:
        """Get a human-readable display of who created this record."""
        if record.created_by:
            return f"Admin: {record.created_by.username}"
        elif record.created_by_discord_id:
            # Try to fetch Discord user to get their username
            try:
                user = await self.cog.bot.fetch_user(int(record.created_by_discord_id))
                return f"@{user.name}"
            except Exception:
                # Fallback to ID if user fetch fails
                return f"Discord ID: {record.created_by_discord_id}"
        elif record.created_by_api_key:
            return f"API: {record.created_by_api_key.user.username}"
        return "System"

    async def update_view(self, interaction: discord.Interaction) -> discord.Embed:
        """Update the view and return the embed to display."""
        # If we have a preselected player, auto-search for their records
        if self.preselected_player_id:
            try:
                limit = 50

                self.records = await self.search.search_records(tower_id=self.preselected_player_id, limit=limit)

                # Create results embed
                embed = discord.Embed(
                    title=f"🛡️ Moderation Records for Player {self.preselected_player_id}",
                    description=f"Administrative interface showing moderation records for player `{self.preselected_player_id}`.",
                    color=discord.Color.red(),
                )

                # Add records summary
                if self.records:
                    active_count = sum(1 for r in self.records if r.is_active)
                    resolved_count = len(self.records) - active_count

                    embed.add_field(
                        name="Records Summary",
                        value=f"**Total:** {len(self.records)}\n**Active:** {active_count}\n**Resolved:** {resolved_count}",
                        inline=True,
                    )

                    # Show first few records
                    for i, record in enumerate(self.records[:3]):
                        status_emoji = "🔴" if record.is_active else "✅"
                        created_by = await self._get_creator_display(record)
                        embed.add_field(
                            name=f"{status_emoji} Record #{record.id}",
                            value=(
                                f"**Type:** {record.get_moderation_type_display()}\n"
                                f"**Created By:** {created_by}\n"
                                f"**Created:** {record.created_at.strftime('%Y-%m-%d')}"
                            ),
                            inline=True,
                        )

                    if len(self.records) > 3:
                        embed.add_field(
                            name="More Records",
                            value=f"... and {len(self.records) - 3} more records. Use search to view all.",
                            inline=False,
                        )
                else:
                    embed.add_field(
                        name="No Records Found",
                        value=f"No moderation records found for player `{self.preselected_player_id}`.",
                        inline=False,
                    )

                embed.add_field(
                    name="Available Actions",
                    value=(
                        "• **Create Record**: Add a new moderation record for this player\n"
                        "• **Search Records**: Search and manage existing records\n"
                        "• **Bulk Actions**: Perform bulk operations on records"
                    ),
                    inline=False,
                )

                embed.set_footer(text="Use the buttons below to navigate • Session expires in 15 minutes")
                return embed

            except Exception as e:
                self.cog.logger.error(f"Error auto-searching for preselected player: {e}")
                # Fall back to default view

        # Default admin view
        embed = discord.Embed(
            title="🛡️ Moderation Records Management",
            description="Administrative interface for managing moderation records.",
            color=discord.Color.red(),
        )

        embed.add_field(
            name="Available Actions",
            value=(
                "• **Create Record**: Add a new moderation record\n"
                "• **Search Records**: Search and manage existing records\n"
                "• **Bulk Actions**: Perform bulk operations on records"
            ),
            inline=False,
        )

        embed.set_footer(text="Use the buttons below to navigate • Session expires in 15 minutes")
        return embed


class CreateRecordButton(discord.ui.Button):
    """Button to create a new moderation record."""

    def __init__(self):
        super().__init__(label="Create Record", style=discord.ButtonStyle.success, emoji="➕", custom_id="create_record")

    async def callback(self, interaction: discord.Interaction):
        """Handle create record button click."""
        # Show creation modal
        modal = ModerationRecordForm(self.view.cog)
        await interaction.response.send_modal(modal)


class SearchButton(discord.ui.Button):
    """Button to search for moderation records."""

    def __init__(self):
        super().__init__(label="Search Records", style=discord.ButtonStyle.primary, emoji="🔍", custom_id="admin_search_records")

    async def callback(self, interaction: discord.Interaction):
        """Handle search button click."""
        # Show search modal
        modal = AdminSearchModal(self.view.cog)
        await interaction.response.send_modal(modal)


class BulkActionsButton(discord.ui.Button):
    """Button for bulk actions on records."""

    def __init__(self):
        super().__init__(label="Bulk Actions", style=discord.ButtonStyle.danger, emoji="⚡", custom_id="bulk_actions")

    async def callback(self, interaction: discord.Interaction):
        """Handle bulk actions button click."""
        # Show bulk actions view
        view = BulkActionsView(self.view.cog)
        embed = view.create_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class AdminSearchModal(discord.ui.Modal):
    """Advanced search modal for administrators."""

    def __init__(self, cog):
        super().__init__(title="Advanced Search - Moderation Records")
        self.cog = cog

        self.tower_id_input = discord.ui.TextInput(
            label="Tower ID (optional)",
            placeholder="Enter Tower player ID to search for",
            required=False,
            max_length=32,
        )

        self.type_input = discord.ui.TextInput(
            label="Moderation Type (optional)",
            placeholder="sus, ban, shun, soft_ban, or 'all'",
            default="all",
            required=False,
            max_length=20,
        )

        self.status_input = discord.ui.TextInput(
            label="Status (optional)",
            placeholder="active, resolved, or 'all'",
            default="all",
            required=False,
            max_length=10,
        )

        self.source_input = discord.ui.TextInput(
            label="Source (optional)",
            placeholder="manual, api, bot, automated, or 'all'",
            default="all",
            required=False,
            max_length=20,
        )

        self.add_item(self.tower_id_input)
        self.add_item(self.type_input)
        self.add_item(self.status_input)
        self.add_item(self.source_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle advanced search form submission."""
        try:
            tower_id = self.tower_id_input.value.strip() or None
            mod_type = self.type_input.value.strip().lower()
            status = self.status_input.value.strip().lower()
            source = self.source_input.value.strip().lower()

            # Parse filters
            moderation_type = None if mod_type in ["all", ""] else mod_type
            active_only = status == "active"
            resolved_only = status == "resolved"
            source_filter = None if source in ["all", ""] else source

            # Validate inputs
            if moderation_type and moderation_type not in ["sus", "ban", "shun", "soft_ban"]:
                await interaction.response.send_message(
                    "❌ Invalid moderation type. Must be one of: sus, ban, shun, soft_ban, or 'all'", ephemeral=True
                )
                return

            if source_filter and source_filter not in ["manual", "api", "bot", "automated"]:
                await interaction.response.send_message("❌ Invalid source. Must be one of: manual, api, bot, automated, or 'all'", ephemeral=True)
                return

            # Perform search
            search = ModerationRecordSearch(self.cog)
            limit = 50

            records = await search.search_records(tower_id=tower_id, moderation_type=moderation_type, active_only=active_only, limit=limit)

            # Apply additional filters
            if resolved_only:
                records = [r for r in records if not r.is_active]
            if source_filter:
                records = [r for r in records if r.source == source_filter]

            # Create results view
            view = AdminSearchResultsView(self.cog, records, tower_id, moderation_type, status, source_filter)
            embed = await view.create_embed()

            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error in admin search: {e}")
            await interaction.response.send_message("❌ An error occurred while searching. Please try again.", ephemeral=True)


class AdminSearchResultsView(discord.ui.View):
    """View for displaying admin search results with management options."""

    def __init__(self, cog, records, tower_id=None, mod_type=None, status=None, source=None):
        super().__init__(timeout=900)
        self.cog = cog
        self.records = records
        self.tower_id = tower_id
        self.mod_type = mod_type
        self.status = status
        self.source = source
        self.current_page = 0
        self.results_per_page = 5

        # Load settings
        # Results per page is hardcoded to 5

        # Add navigation buttons if needed
        if len(records) > self.results_per_page:
            self.add_item(PrevPageButton())
            self.add_item(NextPageButton())

        # Add action buttons
        self.add_item(ViewDetailsButton())
        self.add_item(EditRecordButton())
        self.add_item(ResolveRecordButton())
        self.add_item(BackButton())

    async def create_embed(self) -> discord.Embed:
        """Create the embed for current page of results."""
        start_idx = self.current_page * self.results_per_page
        end_idx = start_idx + self.results_per_page
        page_records = self.records[start_idx:end_idx]

        embed = discord.Embed(title=f"🔍 Admin Search Results ({len(self.records)} total)", color=discord.Color.red())

        # Add search criteria
        criteria = []
        if self.tower_id:
            criteria.append(f"Tower ID: `{self.tower_id}`")
        if self.mod_type and self.mod_type != "all":
            criteria.append(f"Type: {self.mod_type}")
        if self.status and self.status != "all":
            criteria.append(f"Status: {self.status}")
        if self.source and self.source != "all":
            criteria.append(f"Source: {self.source}")

        if criteria:
            embed.add_field(name="Search Criteria", value="\n".join(criteria), inline=False)

        # Add records
        if page_records:
            for i, record in enumerate(page_records, start_idx + 1):
                status_emoji = "🔴" if record.is_active else "✅"
                embed.add_field(
                    name=f"{status_emoji} Record #{record.id}",
                    value=(
                        f"**Player:** {record.tower_id}\n"
                        f"**Type:** {record.get_moderation_type_display()}\n"
                        f"**Source:** {record.get_source_display()}\n"
                        f"**Created:** {record.created_at.strftime('%Y-%m-%d')}"
                    ),
                    inline=True,
                )
        else:
            embed.add_field(name="No Results", value="No moderation records found matching your criteria.", inline=False)

        # Add pagination info
        if len(self.records) > self.results_per_page:
            total_pages = (len(self.records) - 1) // self.results_per_page + 1
            embed.set_footer(text=f"Page {self.current_page + 1}/{total_pages} • {len(self.records)} total results • Select a record to manage it")

        return embed


class ViewDetailsButton(discord.ui.Button):
    """Button to view detailed information about a record."""

    def __init__(self):
        super().__init__(label="View Details", style=discord.ButtonStyle.secondary, emoji="📋", custom_id="view_details")

    async def callback(self, interaction: discord.Interaction):
        """Handle view details button click."""
        # This would need a select menu to choose which record
        # For now, just show the first record on the current page
        view = self.view
        start_idx = view.current_page * view.results_per_page
        page_records = view.records[start_idx : start_idx + view.results_per_page]

        if not page_records:
            await interaction.response.send_message("No records to view.", ephemeral=True)
            return

        # Show details of the first record (in a real implementation, you'd have a select menu)
        record = page_records[0]
        embed = format_moderation_record_embed(record, show_details=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class EditRecordButton(discord.ui.Button):
    """Button to edit a moderation record."""

    def __init__(self):
        super().__init__(label="Edit Record", style=discord.ButtonStyle.primary, emoji="✏️", custom_id="edit_record")

    async def callback(self, interaction: discord.Interaction):
        """Handle edit record button click."""
        # This would need a select menu to choose which record
        # For now, just edit the first record on the current page
        view = self.view
        start_idx = view.current_page * view.results_per_page
        page_records = view.records[start_idx : start_idx + view.results_per_page]

        if not page_records:
            await interaction.response.send_message("No records to edit.", ephemeral=True)
            return

        # Edit the first record
        record = page_records[0]
        modal = ModerationRecordForm(view.cog, existing_record=record)
        await interaction.response.send_modal(modal)


class ResolveRecordButton(discord.ui.Button):
    """Button to resolve a moderation record."""

    def __init__(self):
        super().__init__(label="Resolve Record", style=discord.ButtonStyle.success, emoji="✅", custom_id="resolve_record")

    async def callback(self, interaction: discord.Interaction):
        """Handle resolve record button click."""
        # This would need a select menu to choose which record
        # For now, just resolve the first active record on the current page
        view = self.view
        start_idx = view.current_page * view.results_per_page
        page_records = view.records[start_idx : start_idx + view.results_per_page]

        active_records = [r for r in page_records if r.is_active]
        if not active_records:
            await interaction.response.send_message("No active records to resolve on this page.", ephemeral=True)
            return

        # Resolve the first active record
        record = active_records[0]

        try:
            from asgiref.sync import sync_to_async

            await sync_to_async(record.resolve)(resolved_by_discord_id=str(interaction.user.id))

            embed = discord.Embed(
                title="Record Resolved",
                description=f"Moderation record #{record.id} for player {record.tower_id} has been resolved.",
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

            # Refresh the view
            embed = await view.create_embed()
            await interaction.followup.edit_message(embed=embed, view=view)

        except Exception as e:
            view.cog.logger.error(f"Error resolving record: {e}")
            await interaction.response.send_message("❌ Failed to resolve the record. Please try again.", ephemeral=True)


class BulkActionsView(discord.ui.View):
    """View for bulk actions on moderation records."""

    def __init__(self, cog):
        super().__init__(timeout=900)
        self.cog = cog

        # Add bulk action buttons
        self.add_item(BulkResolveButton())
        self.add_item(BulkExportButton())
        self.add_item(BackButton())

    def create_embed(self) -> discord.Embed:
        """Create the bulk actions embed."""
        embed = discord.Embed(title="⚡ Bulk Actions", description="Perform bulk operations on moderation records.", color=discord.Color.orange())

        embed.add_field(
            name="Available Actions",
            value=("• **Bulk Resolve**: Resolve multiple records at once\n" "• **Bulk Export**: Export records to a file"),
            inline=False,
        )

        embed.set_footer(text="Use the buttons below to perform bulk actions")
        return embed


class BulkResolveButton(discord.ui.Button):
    """Button to bulk resolve records."""

    def __init__(self):
        super().__init__(label="Bulk Resolve", style=discord.ButtonStyle.danger, emoji="✅", custom_id="bulk_resolve")

    async def callback(self, interaction: discord.Interaction):
        """Handle bulk resolve button click."""
        # This would show a modal or view to select criteria for bulk resolution
        modal = BulkResolveModal(self.view.cog)
        await interaction.response.send_modal(modal)


class BulkExportButton(discord.ui.Button):
    """Button to export records."""

    def __init__(self):
        super().__init__(label="Bulk Export", style=discord.ButtonStyle.secondary, emoji="📄", custom_id="bulk_export")

    async def callback(self, interaction: discord.Interaction):
        """Handle bulk export button click."""
        # This would generate and send a file with record data
        await interaction.response.send_message("Bulk export functionality is not yet implemented.", ephemeral=True)


class BulkResolveModal(discord.ui.Modal):
    """Modal for bulk resolving records."""

    def __init__(self, cog):
        super().__init__(title="Bulk Resolve Records")
        self.cog = cog

        self.tower_id_input = discord.ui.TextInput(
            label="Tower ID Filter (optional)",
            placeholder="Only resolve records for this Tower ID",
            required=False,
            max_length=32,
        )

        self.type_input = discord.ui.TextInput(
            label="Moderation Type Filter (optional)",
            placeholder="Only resolve records of this type (sus, ban, etc.)",
            required=False,
            max_length=20,
        )

        self.confirmation_input = discord.ui.TextInput(
            label="Confirmation",
            placeholder="Type 'CONFIRM' to proceed with bulk resolution",
            required=True,
            max_length=10,
        )

        self.add_item(self.tower_id_input)
        self.add_item(self.type_input)
        self.add_item(self.confirmation_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle bulk resolve form submission."""
        if self.confirmation_input.value.strip().upper() != "CONFIRM":
            await interaction.response.send_message("❌ Confirmation failed. Bulk resolution cancelled.", ephemeral=True)
            return

        try:
            tower_id = self.tower_id_input.value.strip() or None
            mod_type = self.type_input.value.strip().lower() or None

            # Build query for records to resolve
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import ModerationRecord

            query = ModerationRecord.objects.filter(resolved_at__isnull=True)  # Only active records

            if tower_id:
                query = query.filter(tower_id=tower_id)
            if mod_type:
                query = query.filter(moderation_type=mod_type)

            # Count records that will be affected
            count = await sync_to_async(query.count)()

            if count == 0:
                await interaction.response.send_message("No active records found matching the specified criteria.", ephemeral=True)
                return

            # Resolve the records
            resolved_count = await sync_to_async(lambda: query.update(resolved_at=timezone.now(), resolved_by_discord_id=str(interaction.user.id)))()

            embed = discord.Embed(
                title="Bulk Resolution Complete",
                description=f"Successfully resolved {resolved_count} moderation records.",
                color=discord.Color.green(),
            )

            if tower_id:
                embed.add_field(name="Tower ID Filter", value=tower_id, inline=True)
            if mod_type:
                embed.add_field(name="Type Filter", value=mod_type, inline=True)

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error in bulk resolve: {e}")
            await interaction.response.send_message("❌ An error occurred during bulk resolution. Please try again.", ephemeral=True)


# Import timezone for bulk resolve
from django.utils import timezone


class PrevPageButton(discord.ui.Button):
    """Button to go to previous page."""

    def __init__(self):
        super().__init__(label="Previous", style=discord.ButtonStyle.secondary, emoji="⬅️", custom_id="admin_prev_page")

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
        super().__init__(label="Next", style=discord.ButtonStyle.secondary, emoji="➡️", custom_id="admin_next_page")

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
    """Button to go back to main admin view."""

    def __init__(self):
        super().__init__(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", custom_id="admin_back_to_main")

    async def callback(self, interaction: discord.Interaction):
        """Handle back button click."""
        # Return to main admin management view
        view = AdminSusManagementView(self.view.cog, interaction.guild.id)
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)
