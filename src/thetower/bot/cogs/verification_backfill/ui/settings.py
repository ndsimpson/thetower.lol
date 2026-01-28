"""Settings UI for Verification Backfill cog."""

import discord


class VerificationBackfillSettingsView(discord.ui.View):
    """Settings view for Verification Backfill cog."""

    def __init__(self, context):
        """Initialize using the unified constructor pattern."""
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.interaction = context.interaction
        self.is_bot_owner = context.is_bot_owner
        self.guild_id = context.guild_id

        # Add global log channel selector (row 0)
        self.add_item(GlobalLogChannelSelect(self.cog))

        # Add action buttons (row 1) - will be customized based on state
        self.add_item(PreviewBackfillButton(self.cog, self.guild_id))
        self.add_item(ApplyBackfillButton(self.cog, self.guild_id, resume=False))
        self.add_item(CancelBackfillButton(self.cog, self.guild_id))

        # Add row 2 for resume/reset when there's saved state
        self.add_item(ResumeBackfillButton(self.cog, self.guild_id))
        self.add_item(ResetProgressButton(self.cog, self.guild_id))


class GlobalLogChannelSelect(discord.ui.ChannelSelect):
    """Channel select for global log channel."""

    def __init__(self, cog):
        super().__init__(
            placeholder="Select global log channel (optional)",
            channel_types=[discord.ChannelType.text],
            row=0,
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Set global log channel."""
        if not self.values:
            # Clear the channel
            self.cog.set_global_setting("global_log_channel_id", None)
            await interaction.response.send_message("✅ Global log channel cleared.", ephemeral=True)
            return

        channel = self.values[0]
        self.cog.set_global_setting("global_log_channel_id", channel.id)
        await interaction.response.send_message(
            f"✅ Global log channel set to {channel.mention}\n\n" f"All backfill operations across all servers will be logged here.",
            ephemeral=True,
        )


class PreviewBackfillButton(discord.ui.Button):
    """Button to preview verification date backfill."""

    def __init__(self, cog, guild_id: int):
        super().__init__(
            label="Preview Backfill",
            style=discord.ButtonStyle.primary,
            emoji="🔍",
            row=1,
        )
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Preview backfill operation."""
        await self.cog.preview_backfill(interaction, self.guild_id)


class ApplyBackfillButton(discord.ui.Button):
    """Button to apply verification date backfill (start fresh)."""

    def __init__(self, cog, guild_id: int, resume: bool = False):
        super().__init__(
            label="Start Fresh",
            style=discord.ButtonStyle.success,
            emoji="🆕",
            row=1,
        )
        self.cog = cog
        self.guild_id = guild_id
        self.resume = resume

    async def callback(self, interaction: discord.Interaction):
        """Apply backfill operation (start fresh)."""
        await self.cog.apply_backfill(interaction, self.guild_id, start_fresh=True)


class CancelBackfillButton(discord.ui.Button):
    """Button to cancel running backfill."""

    def __init__(self, cog, guild_id: int):
        # Check if backfill is running to set button state
        is_running = guild_id in cog.backfill_tasks and not cog.backfill_tasks[guild_id].done()

        super().__init__(
            label="Cancel",
            style=discord.ButtonStyle.danger,
            emoji="🛑",
            row=1,
            disabled=not is_running,
        )
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Cancel running backfill."""
        await self.cog.cancel_backfill(interaction, self.guild_id)


class ResumeBackfillButton(discord.ui.Button):
    """Button to resume backfill from saved position."""

    def __init__(self, cog, guild_id: int):
        super().__init__(
            label="Resume",
            style=discord.ButtonStyle.primary,
            emoji="▶️",
            row=2,
        )
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Resume backfill operation from saved position."""
        # Check if there's saved state
        status = await self.cog.get_backfill_status(self.guild_id)
        if not status["has_saved_state"]:
            await interaction.response.send_message("❌ No saved progress to resume.", ephemeral=True)
            return

        # Show status first
        status_embed = discord.Embed(
            title="📍 Resume Backfill",
            description="Continuing from saved position...",
            color=discord.Color.blue(),
        )
        if status["message_date"]:
            status_embed.add_field(name="Last Scanned", value=f"<t:{int(status['message_date'].timestamp())}:F>", inline=False)
        status_embed.add_field(
            name="Progress",
            value=f"**Accounts updated:** {status['updated_count']}\n"
            f"**Accounts remaining:** {len(status['accounts_remaining'])}\n"
            f"**Messages scanned:** {status['message_count']}",
            inline=False,
        )
        await interaction.response.send_message(embed=status_embed, ephemeral=True)

        # Start backfill (will resume from saved position)
        await self.cog.apply_backfill(interaction, self.guild_id, start_fresh=False)


class ResetProgressButton(discord.ui.Button):
    """Button to reset saved backfill progress."""

    def __init__(self, cog, guild_id: int):
        super().__init__(
            label="Reset Progress",
            style=discord.ButtonStyle.secondary,
            emoji="🔄",
            row=2,
        )
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Clear saved backfill state."""
        await self.cog._clear_backfill_state(self.guild_id)
        await interaction.response.send_message("✅ Backfill progress reset. You can start fresh now.", ephemeral=True)
