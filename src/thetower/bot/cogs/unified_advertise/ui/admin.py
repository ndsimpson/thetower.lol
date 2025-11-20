# Standard library imports
import datetime
from typing import TYPE_CHECKING

# Third-party imports
import discord
from discord.ui import Button, Select, View

if TYPE_CHECKING:
    from ..cog import UnifiedAdvertise


class AdminAdManagementView(View):
    """View for administrators to manage advertisements in the guild."""

    def __init__(self, cog: "UnifiedAdvertise", guild_id: int):
        super().__init__(timeout=600)  # 10 minute timeout
        self.cog = cog
        self.guild_id = guild_id

    async def update_view(self, interaction: discord.Interaction):
        """Update the view with current advertisement status."""
        # Get all active advertisements in this guild
        active_ads = []
        for thread_id, deletion_time, author_id, notify, ad_guild_id in self.cog.pending_deletions:
            if ad_guild_id == self.guild_id:
                try:
                    thread = await self.cog.bot.fetch_channel(thread_id)
                    if thread:
                        author = await self.cog.bot.fetch_user(author_id)
                        author_name = author.name if author else f"User {author_id}"
                        time_left = deletion_time - datetime.datetime.now()
                        hours_left = time_left.total_seconds() / 3600
                        active_ads.append((thread_id, thread.name, author_name, hours_left, notify))
                except Exception:
                    continue

        # Build embed
        embed = discord.Embed(
            title="Admin Advertisement Management",
            description="Manage all advertisements in this server",
            color=discord.Color.red()
        )

        if active_ads:
            ads_text = []
            for thread_id, name, author, hours_left, notify in active_ads:
                notify_icon = "🔔" if notify else "🔕"
                ads_text.append(f"**{name}**\n👤 {author} • {notify_icon} Expires in {hours_left:.1f} hours")
            embed.add_field(name="Active Advertisements", value="\n\n".join(ads_text), inline=False)
        else:
            embed.add_field(name="Active Advertisements", value="No active advertisements", inline=False)

        # Add statistics
        embed.add_field(
            name="Statistics",
            value=f"Total Active Ads: {len(active_ads)}",
            inline=True
        )

        # Update buttons
        self.clear_items()

        if active_ads:
            # Add delete button if there are ads
            delete_btn = Button(label="Delete Advertisement", style=discord.ButtonStyle.danger, emoji="🗑️")
            delete_btn.callback = self.delete_advertisement
            self.add_item(delete_btn)

            # Add toggle notification button
            toggle_btn = Button(label="Toggle Notifications", style=discord.ButtonStyle.secondary, emoji="🔔")
            toggle_btn.callback = self.toggle_notifications
            self.add_item(toggle_btn)

        # Add create advertisement button (switch to user view)
        create_btn = Button(label="Create Advertisement", style=discord.ButtonStyle.success, emoji="✨")
        create_btn.callback = self.create_advertisement
        self.add_item(create_btn)

        # Add settings button
        settings_btn = Button(label="Settings", style=discord.ButtonStyle.primary, emoji="⚙️")
        settings_btn.callback = self.open_settings
        self.add_item(settings_btn)

        # Always add refresh button
        refresh_btn = Button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
        refresh_btn.callback = self.refresh_view
        self.add_item(refresh_btn)

        return embed

    async def delete_advertisement(self, interaction: discord.Interaction):
        """Handle deleting an advertisement."""
        # Get all ads in this guild
        guild_ads = []
        for thread_id, deletion_time, author_id, notify, ad_guild_id in self.cog.pending_deletions:
            if ad_guild_id == self.guild_id:
                try:
                    thread = await self.cog.bot.fetch_channel(thread_id)
                    if thread:
                        author = await self.cog.bot.fetch_user(author_id)
                        author_name = author.name if author else f"User {author_id}"
                        guild_ads.append((thread_id, thread.name, author_name))
                except Exception:
                    continue

        if len(guild_ads) == 1:
            # Only one ad, delete it directly
            thread_id = guild_ads[0][0]
            await self._delete_ad(interaction, thread_id)
        else:
            # Multiple ads, show selection dropdown
            options = [
                discord.SelectOption(
                    label=name[:80],
                    value=str(tid),
                    description=f"By {author}"
                )
                for tid, name, author in guild_ads
            ]
            select = Select(placeholder="Select advertisement to delete", options=options)

            async def select_callback(select_interaction: discord.Interaction):
                thread_id = int(select.values[0])
                await self._delete_ad(select_interaction, thread_id)

            select.callback = select_callback
            view = View()
            view.add_item(select)
            await interaction.response.send_message("Select the advertisement you want to delete:", view=view, ephemeral=True)

    async def _delete_ad(self, interaction: discord.Interaction, thread_id: int):
        """Delete a specific advertisement."""
        try:
            thread = await self.cog.bot.fetch_channel(thread_id)
            await thread.delete()

            # Remove from pending deletions
            self.cog.pending_deletions = [
                entry for entry in self.cog.pending_deletions if entry[0] != thread_id
            ]
            await self.cog._save_pending_deletions()

            await interaction.response.send_message("✅ Advertisement deleted successfully.", ephemeral=True)

            # Refresh the main view
            embed = await self.update_view(interaction)
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            self.cog.logger.error(f"Error deleting advertisement: {e}")
            await interaction.response.send_message("❌ Failed to delete advertisement.", ephemeral=True)

    async def toggle_notifications(self, interaction: discord.Interaction):
        """Toggle notification settings for an advertisement."""
        # Get all ads in this guild
        guild_ads = []
        for entry in self.cog.pending_deletions:
            thread_id, deletion_time, author_id, notify, ad_guild_id = entry
            if ad_guild_id == self.guild_id:
                try:
                    thread = await self.cog.bot.fetch_channel(thread_id)
                    if thread:
                        author = await self.cog.bot.fetch_user(author_id)
                        author_name = author.name if author else f"User {author_id}"
                        guild_ads.append((thread_id, thread.name, author_name, notify))
                except Exception:
                    continue

        if len(guild_ads) == 1:
            # Only one ad, toggle it directly
            thread_id, name, author, current_notify = guild_ads[0]
            await self._toggle_notify(interaction, thread_id, not current_notify)
        else:
            # Multiple ads, show selection dropdown
            options = [
                discord.SelectOption(
                    label=name[:80],
                    value=str(tid),
                    description=f"By {author} • Notifications {'ON' if notify else 'OFF'}",
                    emoji="🔔" if notify else "🔕"
                )
                for tid, name, author, notify in guild_ads
            ]
            select = Select(placeholder="Select advertisement", options=options)

            async def select_callback(select_interaction: discord.Interaction):
                thread_id = int(select.values[0])
                # Find current notify state
                current_notify = False
                for tid, _, _, notify in guild_ads:
                    if tid == thread_id:
                        current_notify = notify
                        break
                await self._toggle_notify(select_interaction, thread_id, not current_notify)

            select.callback = select_callback
            view = View()
            view.add_item(select)
            await interaction.response.send_message("Select advertisement to toggle notifications:", view=view, ephemeral=True)

    async def _toggle_notify(self, interaction: discord.Interaction, thread_id: int, new_state: bool):
        """Toggle notification for a specific ad."""
        updated_deletions = []
        for t_id, t_time, t_author, t_notify, t_guild_id in self.cog.pending_deletions:
            if t_id == thread_id:
                updated_deletions.append((t_id, t_time, t_author, new_state, t_guild_id))
            else:
                updated_deletions.append((t_id, t_time, t_author, t_notify, t_guild_id))

        self.cog.pending_deletions = updated_deletions
        await self.cog._save_pending_deletions()

        state_text = "enabled" if new_state else "disabled"
        await interaction.response.send_message(f"✅ Notifications have been {state_text}.", ephemeral=True)

        # Refresh the main view
        embed = await self.update_view(interaction)
        await interaction.message.edit(embed=embed, view=self)

    async def refresh_view(self, interaction: discord.Interaction):
        """Refresh the view."""
        embed = await self.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=self)

    async def create_advertisement(self, interaction: discord.Interaction):
        """Switch to user view for creating an advertisement."""
        from .user import AdManagementView
        view = AdManagementView(self.cog, interaction.user.id, self.guild_id)
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def open_settings(self, interaction: discord.Interaction):
        """Open the settings view."""
        from .settings import GuildSettingsView
        view = GuildSettingsView(self.cog, self.guild_id)
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)
