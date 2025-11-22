# Core business logic and components for the Manage Sus cog

from enum import Enum
from typing import List, Optional

import discord


class ModerationType(Enum):
    """Enumeration of moderation types."""

    SUS = "sus"
    BAN = "ban"
    SHUN = "shun"
    SOFT_BAN = "soft_ban"


class ModerationSource(Enum):
    """Enumeration of moderation sources."""

    MANUAL = "manual"
    API = "api"
    BOT = "bot"
    AUTOMATED = "automated"


__all__ = [
    "ModerationType",
    "ModerationSource",
    "ModerationRecordForm",
    "ModerationRecordSearch",
    "format_moderation_record_embed",
]


class ModerationRecordForm(discord.ui.Modal):
    """Modal for creating or editing moderation records."""

    def __init__(self, cog, tower_id: str = None, existing_record=None):
        # Set title based on whether we're creating or editing
        title = "Edit Moderation Record" if existing_record else "Create Moderation Record"
        super().__init__(title=title)

        self.cog = cog
        self.tower_id = tower_id
        self.existing_record = existing_record

        # Pre-fill values if editing
        if existing_record:
            current_type = existing_record.moderation_type
            current_reason = existing_record.reason or ""
        else:
            current_type = "sus"
            current_reason = ""

        # Tower ID field (read-only for edits)
        self.tower_id_input = discord.ui.TextInput(
            label="Tower ID",
            placeholder="Enter Tower player ID",
            default=self.tower_id or "",
            required=True,
            max_length=32,
        )
        if existing_record:
            self.tower_id_input.disabled = True

        # Moderation type select
        self.moderation_type_input = discord.ui.TextInput(
            label="Moderation Type",
            placeholder="sus, ban, shun, or soft_ban",
            default=current_type,
            required=True,
            max_length=20,
        )

        # Reason field
        self.reason_input = discord.ui.TextInput(
            label="Reason",
            placeholder="Reason for this moderation action",
            default=current_reason,
            required=False,
            max_length=1000,
            style=discord.TextStyle.paragraph,
        )

        # Add items in order
        self.add_item(self.tower_id_input)
        self.add_item(self.moderation_type_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle form submission."""
        try:
            tower_id = self.tower_id_input.value.strip()
            moderation_type = self.moderation_type_input.value.strip().lower()
            reason = self.reason_input.value.strip() or None

            # Validate moderation type
            if moderation_type not in [mt.value for mt in ModerationType]:
                await interaction.response.send_message(
                    f"❌ Invalid moderation type. Must be one of: {', '.join([mt.value for mt in ModerationType])}", ephemeral=True
                )
                return

            # Validate tower ID format (basic check)
            if not tower_id or len(tower_id) > 32:
                await interaction.response.send_message("❌ Invalid Tower ID. Must be 1-32 characters.", ephemeral=True)
                return

            # Create or update the record
            if self.existing_record:
                # Update existing record
                success = await self._update_moderation_record(interaction, self.existing_record, moderation_type, reason)
            else:
                # Create new record
                success = await self._create_moderation_record(interaction, tower_id, moderation_type, reason)

            if success:
                await interaction.response.send_message(
                    f"✅ Moderation record {'updated' if self.existing_record else 'created'} successfully.", ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ Failed to save moderation record. Please try again.", ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error in moderation form submission: {e}")
            await interaction.response.send_message("❌ An error occurred while processing your request.", ephemeral=True)

    async def _create_moderation_record(self, interaction: discord.Interaction, tower_id: str, moderation_type: str, reason: str = None) -> bool:
        """Create a new moderation record."""
        try:
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import ModerationRecord

            # Create the record
            record = await sync_to_async(ModerationRecord.create_for_bot)(
                tower_id=tower_id,
                moderation_type=moderation_type,
                discord_id=str(interaction.user.id),
                reason=reason,
            )

            self.cog.logger.info(f"Created moderation record {record.id} for tower_id {tower_id} by Discord user {interaction.user.id}")
            return True

        except Exception as e:
            self.cog.logger.error(f"Error creating moderation record: {e}")
            return False

    async def _update_moderation_record(self, interaction: discord.Interaction, record, moderation_type: str, reason: str = None) -> bool:
        """Update an existing moderation record."""
        try:
            from asgiref.sync import sync_to_async

            # Update the record
            record.moderation_type = moderation_type
            record.reason = reason

            await sync_to_async(record.save)()

            self.cog.logger.info(f"Updated moderation record {record.id} by Discord user {interaction.user.id}")
            return True

        except Exception as e:
            self.cog.logger.error(f"Error updating moderation record: {e}")
            return False


class ModerationRecordSearch:
    """Utility class for searching moderation records."""

    def __init__(self, cog):
        self.cog = cog

    async def search_records(
        self, tower_id: Optional[str] = None, moderation_type: Optional[str] = None, active_only: bool = False, limit: int = 50
    ) -> List:
        """Search for moderation records with optional filters."""
        try:
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import ModerationRecord

            # Build query
            query = ModerationRecord.objects.all()

            if tower_id:
                query = query.filter(tower_id__icontains=tower_id)

            if moderation_type:
                query = query.filter(moderation_type=moderation_type)

            if active_only:
                query = query.filter(resolved_at__isnull=True)

            # Order by creation date (newest first)
            query = query.order_by("-created_at")[:limit]

            # Execute query
            records = await sync_to_async(list)(query)
            return records

        except Exception as e:
            self.cog.logger.error(f"Error searching moderation records: {e}")
            return []

    async def get_record_by_id(self, record_id: int):
        """Get a specific moderation record by ID."""
        try:
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import ModerationRecord

            record = await sync_to_async(ModerationRecord.objects.get)(id=record_id)
            return record

        except ModerationRecord.DoesNotExist:
            return None
        except Exception as e:
            self.cog.logger.error(f"Error getting moderation record {record_id}: {e}")
            return None


def format_moderation_record_embed(record, show_details: bool = True) -> discord.Embed:
    """Format a moderation record as a Discord embed."""
    embed = discord.Embed(
        title=f"Moderation Record #{record.id}", color=discord.Color.red() if record.is_active else discord.Color.green(), timestamp=record.created_at
    )

    # Basic info
    embed.add_field(
        name="Player",
        value=f"Tower ID: `{record.tower_id}`" + (f"\nKnown Player: {record.known_player.name}" if record.known_player else ""),
        inline=True,
    )

    embed.add_field(name="Type", value=record.get_moderation_type_display(), inline=True)

    embed.add_field(name="Status", value="Active" if record.is_active else "Resolved", inline=True)

    if show_details:
        embed.add_field(name="Source", value=record.get_source_display(), inline=True)

        embed.add_field(name="Created By", value=record.created_by_display, inline=True)

        if record.resolved_at:
            embed.add_field(name="Resolved By", value=record.resolved_by_display, inline=True)

        if record.reason:
            embed.add_field(name="Reason", value=record.reason, inline=False)

    embed.set_footer(text=f"Created: {record.created_at.strftime('%Y-%m-%d %H:%M UTC')}")
    if record.resolved_at:
        embed.set_footer(text=f"Resolved: {record.resolved_at.strftime('%Y-%m-%d %H:%M UTC')}")

    return embed
