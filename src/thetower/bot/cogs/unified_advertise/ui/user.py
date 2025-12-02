# Standard library imports
import datetime
from typing import TYPE_CHECKING

# Third-party imports
import discord
from discord.ui import Button, Select, View

from thetower.bot.ui.context import SettingsViewContext

if TYPE_CHECKING:
    from ..cog import UnifiedAdvertise


class AdManagementView(View):
    """View for users to manage their advertisements."""

    def __init__(self, cog: "UnifiedAdvertise", user_id: int, guild_id: int):
        super().__init__(timeout=900)  # 5 minute timeout
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id

    async def update_view(self, interaction: discord.Interaction):
        """Update the view with current advertisement status."""
        # Get user's active advertisements in this guild
        user_ads = []
        for thread_id, deletion_time, author_id, notify, ad_guild_id in self.cog.pending_deletions:
            if author_id == self.user_id and ad_guild_id == self.guild_id:
                try:
                    thread = await self.cog.bot.fetch_channel(thread_id)
                    if thread:
                        time_left = deletion_time - datetime.datetime.now()
                        hours_left = time_left.total_seconds() / 3600
                        user_ads.append((thread_id, thread.name, hours_left, notify))
                except Exception:
                    continue

        # Check cooldown status
        cooldown_hours = self.cog._get_cooldown_hours(self.guild_id)
        guild_cooldowns = self.cog.cooldowns.get(self.guild_id, {"users": {}, "guilds": {}})
        user_cooldown_str = guild_cooldowns["users"].get(str(self.user_id))

        on_cooldown = False
        cooldown_hours_left = 0

        if user_cooldown_str:
            stored_time = datetime.datetime.fromisoformat(user_cooldown_str)
            if stored_time.tzinfo is None:
                stored_time = stored_time.replace(tzinfo=datetime.timezone.utc)
            current_time = datetime.datetime.now(datetime.timezone.utc)
            elapsed = (current_time - stored_time).total_seconds()

            if elapsed < cooldown_hours * 3600:
                on_cooldown = True
                cooldown_hours_left = cooldown_hours - (elapsed / 3600)

        # Build embed
        embed = discord.Embed(title="Advertisement Management", description="Manage your advertisements in this server", color=discord.Color.blue())

        if user_ads:
            ads_text = []
            for thread_id, name, hours_left, notify in user_ads:
                notify_icon = "🔔" if notify else "🔕"
                ads_text.append(f"**{name}**\n{notify_icon} Expires in {hours_left:.1f} hours")
            embed.add_field(name="Your Active Advertisements", value="\n\n".join(ads_text), inline=False)
        else:
            embed.add_field(name="Active Advertisements", value="You have no active advertisements", inline=False)

        if on_cooldown:
            embed.add_field(name="Cooldown Status", value=f"⏳ You can post a new advertisement in {cooldown_hours_left:.1f} hours", inline=False)
        else:
            embed.add_field(name="Cooldown Status", value="✅ You can post a new advertisement now!", inline=False)

        # Update buttons
        self.clear_items()

        if user_ads:
            # Add delete button if user has ads
            delete_btn = Button(label="Delete Advertisement", style=discord.ButtonStyle.danger, emoji="🗑️")
            delete_btn.callback = self.delete_advertisement
            self.add_item(delete_btn)

            # Add toggle notification button
            toggle_btn = Button(label="Toggle Notifications", style=discord.ButtonStyle.secondary, emoji="🔔")
            toggle_btn.callback = self.toggle_notifications
            self.add_item(toggle_btn)

        if not on_cooldown:
            # Add create new ad button
            create_btn = Button(label="Create Advertisement", style=discord.ButtonStyle.success, emoji="✨")
            create_btn.callback = self.create_advertisement
            self.add_item(create_btn)

        # Always add refresh button
        refresh_btn = Button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
        refresh_btn.callback = self.refresh_view
        self.add_item(refresh_btn)

        return embed

    async def delete_advertisement(self, interaction: discord.Interaction):
        """Handle deleting an advertisement."""
        # Get user's ads
        user_ads = []
        for thread_id, deletion_time, author_id, notify, ad_guild_id in self.cog.pending_deletions:
            if author_id == self.user_id and ad_guild_id == self.guild_id:
                try:
                    thread = await self.cog.bot.fetch_channel(thread_id)
                    if thread:
                        user_ads.append((thread_id, thread.name))
                except Exception:
                    continue

        if len(user_ads) == 1:
            # Only one ad, delete it directly
            thread_id = user_ads[0][0]
            await self._delete_ad(interaction, thread_id)
        else:
            # Multiple ads, show selection dropdown
            options = [discord.SelectOption(label=name[:100], value=str(tid)) for tid, name in user_ads]
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
            self.cog.pending_deletions = [entry for entry in self.cog.pending_deletions if entry[0] != thread_id]
            await self.cog._save_pending_deletions()

            await interaction.response.send_message("✅ Advertisement deleted successfully.", ephemeral=True)

            # Refresh the main view
            embed = await self.update_view(interaction)
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            self.cog.logger.error(f"Error deleting advertisement: {e}")
            await interaction.response.send_message("❌ Failed to delete advertisement.", ephemeral=True)

    async def toggle_notifications(self, interaction: discord.Interaction):
        """Toggle notification settings."""
        # Get user's ads
        user_ads = []
        for entry in self.cog.pending_deletions:
            thread_id, deletion_time, author_id, notify, ad_guild_id = entry
            if author_id == self.user_id and ad_guild_id == self.guild_id:
                try:
                    thread = await self.cog.bot.fetch_channel(thread_id)
                    if thread:
                        user_ads.append((thread_id, thread.name, notify))
                except Exception:
                    continue

        if len(user_ads) == 1:
            # Only one ad, toggle it directly
            thread_id, name, current_notify = user_ads[0]
            await self._toggle_notify(interaction, thread_id, not current_notify)
        else:
            # Multiple ads, show selection dropdown
            options = [
                discord.SelectOption(
                    label=name[:80], value=str(tid), description=f"Notifications {'ON' if notify else 'OFF'}", emoji="🔔" if notify else "🔕"
                )
                for tid, name, notify in user_ads
            ]
            select = Select(placeholder="Select advertisement", options=options)

            async def select_callback(select_interaction: discord.Interaction):
                thread_id = int(select.values[0])
                # Find current notify state
                current_notify = False
                for tid, _, notify in user_ads:
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

    async def create_advertisement(self, interaction: discord.Interaction):
        """Launch the advertisement creation flow."""
        from .core import AdTypeSelection

        # Create a proper context object for AdTypeSelection
        context = SettingsViewContext(
            guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False  # This field is not critical for ad creation
        )
        view = AdTypeSelection(context)
        await interaction.response.send_message("What type of advertisement would you like to post?", view=view, ephemeral=True)

    async def refresh_view(self, interaction: discord.Interaction):
        """Refresh the view."""
        embed = await self.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=self)
