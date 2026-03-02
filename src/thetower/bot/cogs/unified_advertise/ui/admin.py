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

    ADS_PER_PAGE = 10  # Number of ads to show per page

    def __init__(self, cog: "UnifiedAdvertise", guild_id: int, page: int = 0):
        super().__init__(timeout=900)  # 10 minute timeout
        self.cog = cog
        self.guild_id = guild_id
        self.page = page

    async def update_view(self, interaction: discord.Interaction):
        """Update the view with current advertisement status."""
        # Get all active advertisements in this guild
        active_ads = []
        cooldown_hours = self.cog._get_cooldown_hours(self.guild_id)
        for thread_id, posted_time, author_id, notify, ad_guild_id, thread_name, author_name in self.cog.pending_deletions:
            if ad_guild_id == self.guild_id:
                expiration_time = posted_time + datetime.timedelta(hours=cooldown_hours)
                hours_left = (expiration_time - datetime.datetime.now()).total_seconds() / 3600
                active_ads.append((thread_id, thread_name, author_name, hours_left, notify))

        # Calculate pagination
        total_ads = len(active_ads)
        total_pages = max(1, (total_ads + self.ADS_PER_PAGE - 1) // self.ADS_PER_PAGE)

        # Ensure page is within valid range
        self.page = max(0, min(self.page, total_pages - 1))

        start_idx = self.page * self.ADS_PER_PAGE
        end_idx = min(start_idx + self.ADS_PER_PAGE, total_ads)
        page_ads = active_ads[start_idx:end_idx]

        # Build embed
        embed = discord.Embed(
            title="Admin Advertisement Management", description="Manage all advertisements in this server", color=discord.Color.red()
        )

        if active_ads:
            ads_text = []
            for thread_id, name, author, hours_left, notify in page_ads:
                notify_icon = "🔔" if notify else "🔕"
                ads_text.append(f"**{name}**\n👤 {author} • {notify_icon} Expires in {hours_left:.1f} hours")

            page_info = f" (Page {self.page + 1}/{total_pages})" if total_pages > 1 else ""
            embed.add_field(name=f"Active Advertisements{page_info}", value="\n\n".join(ads_text), inline=False)
        else:
            embed.add_field(name="Active Advertisements", value="No active advertisements", inline=False)

        # Add statistics
        stats_text = f"Total Active Ads: {total_ads}"
        if total_pages > 1:
            stats_text += f"\nShowing: {start_idx + 1}-{end_idx}"
        embed.add_field(name="Statistics", value=stats_text, inline=True)

        # Update buttons
        self.clear_items()

        # Add pagination buttons if needed (first row)
        if total_pages > 1:
            prev_btn = Button(label="Previous", style=discord.ButtonStyle.secondary, emoji="◀️", disabled=self.page == 0)
            prev_btn.callback = self.previous_page
            self.add_item(prev_btn)

            next_btn = Button(label="Next", style=discord.ButtonStyle.secondary, emoji="▶️", disabled=self.page >= total_pages - 1)
            next_btn.callback = self.next_page
            self.add_item(next_btn)

        if active_ads:
            # Add delete button if there are ads
            delete_btn = Button(label="Delete Advertisement", style=discord.ButtonStyle.danger, emoji="🗑️")
            delete_btn.callback = self.delete_advertisement
            self.add_item(delete_btn)

            # Add toggle notification button
            toggle_btn = Button(label="Toggle Notifications", style=discord.ButtonStyle.secondary, emoji="🔔")
            toggle_btn.callback = self.toggle_notifications
            self.add_item(toggle_btn)

            # Add clear all ads button
            clear_btn = Button(label="Clear All Ads", style=discord.ButtonStyle.danger, emoji="💥")
            clear_btn.callback = self.clear_all_ads
            self.add_item(clear_btn)

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
        for thread_id, posted_time, author_id, notify, ad_guild_id, thread_name, author_name in self.cog.pending_deletions:
            if ad_guild_id == self.guild_id:
                guild_ads.append((thread_id, thread_name, author_name))

        if len(guild_ads) == 1:
            # Only one ad, delete it directly
            thread_id = guild_ads[0][0]
            await self._delete_ad(interaction, thread_id)
        else:
            # Multiple ads, show selection dropdown
            options = [discord.SelectOption(label=name[:80], value=str(tid), description=f"By {author}") for tid, name, author in guild_ads]
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
        """Toggle notification settings for an advertisement."""
        # Get all ads in this guild
        guild_ads = []
        for thread_id, posted_time, author_id, notify, ad_guild_id, thread_name, author_name in self.cog.pending_deletions:
            if ad_guild_id == self.guild_id:
                guild_ads.append((thread_id, thread_name, author_name, notify))

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
                    emoji="🔔" if notify else "🔕",
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
        for t_id, t_time, t_author, t_notify, t_guild_id, t_thread_name, t_author_name in self.cog.pending_deletions:
            if t_id == thread_id:
                updated_deletions.append((t_id, t_time, t_author, new_state, t_guild_id, t_thread_name, t_author_name))
            else:
                updated_deletions.append((t_id, t_time, t_author, t_notify, t_guild_id, t_thread_name, t_author_name))

        self.cog.pending_deletions = updated_deletions
        await self.cog._save_pending_deletions()

        state_text = "enabled" if new_state else "disabled"
        await interaction.response.send_message(f"✅ Notifications have been {state_text}.", ephemeral=True)

        # Refresh the main view
        embed = await self.update_view(interaction)
        await interaction.message.edit(embed=embed, view=self)

    async def previous_page(self, interaction: discord.Interaction):
        """Navigate to the previous page."""
        self.page = max(0, self.page - 1)
        embed = await self.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=self)

    async def next_page(self, interaction: discord.Interaction):
        """Navigate to the next page."""
        self.page += 1
        embed = await self.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=self)

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

        is_bot_owner = await self.cog.bot.is_owner(interaction.user)
        context = self.cog.SettingsViewContext(self.guild_id, self.cog, interaction, is_bot_owner)
        view = GuildSettingsView(context)
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def clear_all_ads(self, interaction: discord.Interaction):
        """Show a confirmation prompt before clearing all ads for this guild."""
        guild_ad_count = sum(1 for _, _, _, _, gid, _, _ in self.cog.pending_deletions if gid == self.guild_id)
        confirm_view = ClearAllAdsConfirmView(self.cog, self.guild_id, self)
        embed = discord.Embed(
            title="⚠️ Clear All Advertisements",
            description=(
                f"This will **permanently delete all {guild_ad_count} active advertisement(s)** in this server "
                f"and reset all user and guild cooldowns.\n\n"
                f"Users will be able to post again immediately. Are you sure?"
            ),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)


class ClearAllAdsConfirmView(View):
    """Confirmation view before wiping all advertisements for a guild."""

    def __init__(self, cog: "UnifiedAdvertise", guild_id: int, parent_view: "AdminAdManagementView"):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.parent_view = parent_view

    @discord.ui.button(label="Yes, delete everything", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: Button):
        """Proceed with clearing all ads and resetting cooldowns."""
        await interaction.response.defer(ephemeral=True)

        # Collect thread IDs to delete
        thread_ids = [t_id for t_id, _, _, _, gid, _, _ in self.cog.pending_deletions if gid == self.guild_id]

        deleted = 0
        failed = 0
        for thread_id in thread_ids:
            try:
                thread = await self.cog.bot.fetch_channel(thread_id)
                await thread.delete()
                deleted += 1
            except discord.NotFound:
                deleted += 1  # Already gone — still counts as cleared
            except Exception as e:
                self.cog.logger.error(f"ClearAllAds: failed to delete thread {thread_id}: {e}")
                failed += 1

        # Remove all guild entries from pending_deletions
        self.cog.pending_deletions = [entry for entry in self.cog.pending_deletions if entry[4] != self.guild_id]
        await self.cog._save_pending_deletions()

        # Reset cooldowns for this guild
        self.cog.cooldowns[self.guild_id] = {"users": {}, "guilds": {}}
        await self.cog._save_cooldowns(self.guild_id)

        result = f"✅ Cleared {deleted} advertisement(s) and reset all cooldowns."
        if failed:
            result += f" ({failed} thread(s) could not be deleted — they may still exist in Discord.)"

        await interaction.followup.send(result, ephemeral=True)

        # Refresh the parent admin view if possible
        try:
            embed = await self.parent_view.update_view(interaction)
            await interaction.message.edit(embed=embed, view=self.parent_view)
        except Exception:
            pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: Button):
        """Cancel the clear operation."""
        await interaction.response.send_message("Cancelled. No advertisements were deleted.", ephemeral=True)
        self.stop()
