# Settings interface for the Manage Sus cog

import discord

from thetower.bot.basecog import BaseCog
from thetower.bot.ui.context import BaseSettingsView, SettingsViewContext


class ManageSusSettingsView(BaseSettingsView):
    """Settings view for Manage Sus cog that integrates with global settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(context)
        self.guild_id = str(context.guild_id) if context.guild_id else None

        # Get current global settings (stored in bot config under manage_sus)
        self.view_groups = self.cog.config.get_global_cog_setting("manage_sus", "view_groups", [])
        self.manage_groups = self.cog.config.get_global_cog_setting("manage_sus", "manage_groups", [])
        self.privileged_groups_for_full_ids = self.cog.config.get_global_cog_setting("manage_sus", "privileged_groups_for_full_ids", [])
        self.show_moderation_records_in_profiles = self.cog.config.get_global_cog_setting("manage_sus", "show_moderation_records_in_profiles", True)
        self.privileged_groups_for_moderation_records = self.cog.config.get_global_cog_setting(
            "manage_sus", "privileged_groups_for_moderation_records", []
        )

        # Add configuration buttons for each group setting
        self.add_item(ManageSusConfigureGroupButton(self.cog, "view_groups", "View Groups", "👁️"))
        self.add_item(ManageSusConfigureGroupButton(self.cog, "manage_groups", "Manage Groups", "✏️"))
        self.add_item(ManageSusConfigureGroupButton(self.cog, "privileged_groups_for_full_ids", "Full IDs Groups", "🆔"))
        self.add_item(ManageSusConfigureGroupButton(self.cog, "privileged_groups_for_moderation_records", "Mod Records Groups", "📋"))

        # Add toggle button for boolean setting
        self.add_item(ManageSusToggleButton(self.cog, "show_moderation_records_in_profiles", "Show Moderation Records"))

        # Add back button
        self.add_back_button()

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed with current manage sus settings."""
        embed = discord.Embed(
            title="⚙️ Manage Sus Settings", description="Configure moderation record permissions and visibility", color=discord.Color.blue()
        )

        # Get current settings
        view_groups = self.cog.config.get_global_cog_setting("manage_sus", "view_groups", [])
        manage_groups = self.cog.config.get_global_cog_setting("manage_sus", "manage_groups", [])
        full_ids_groups = self.cog.config.get_global_cog_setting("manage_sus", "privileged_groups_for_full_ids", [])
        mod_records_groups = self.cog.config.get_global_cog_setting("manage_sus", "privileged_groups_for_moderation_records", [])
        show_mod_records = self.cog.config.get_global_cog_setting("manage_sus", "show_moderation_records_in_profiles", True)

        # View Groups
        view_text = ", ".join(view_groups) if view_groups else "None configured"
        embed.add_field(name="👁️ View Groups", value=view_text, inline=False)

        # Manage Groups
        manage_text = ", ".join(manage_groups) if manage_groups else "None configured"
        embed.add_field(name="✏️ Manage Groups", value=manage_text, inline=False)

        # Full IDs Groups
        full_ids_text = ", ".join(full_ids_groups) if full_ids_groups else "None configured"
        embed.add_field(name="🆔 Full IDs Groups", value=full_ids_text, inline=False)

        # Moderation Records Groups
        mod_records_text = ", ".join(mod_records_groups) if mod_records_groups else "None configured"
        embed.add_field(name="📋 Mod Records Groups", value=mod_records_text, inline=False)

        # Show Moderation Records
        show_text = "✅ Enabled" if show_mod_records else "❌ Disabled"
        embed.add_field(name="Show Moderation Records in Profiles", value=show_text, inline=False)

        await interaction.response.edit_message(embed=embed, view=self)


class ManageSusConfigureGroupButton(discord.ui.Button):
    """Button to configure Django groups for a specific permission."""

    def __init__(self, cog: BaseCog, setting_key: str, label: str, emoji: str):
        super().__init__(label=label, style=discord.ButtonStyle.primary, emoji=emoji)
        self.cog = cog
        self.setting_key = setting_key

    async def callback(self, interaction: discord.Interaction):
        # Get current groups
        current_groups = self.cog.config.get_global_cog_setting("manage_sus", self.setting_key, [])

        # Show groups management view
        view = GroupsSelectView(self.cog, interaction, current_groups, setting_key=self.setting_key)
        embed = view.create_selection_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class ManageSusToggleButton(discord.ui.Button):
    """Button to toggle a boolean setting."""

    def __init__(self, cog: BaseCog, setting_key: str, label: str):
        self.cog = cog
        self.setting_key = setting_key
        current_value = cog.config.get_global_cog_setting("manage_sus", setting_key, True)

        emoji = "✅" if current_value else "❌"
        style = discord.ButtonStyle.success if current_value else discord.ButtonStyle.secondary

        super().__init__(label=f"{label}: {'ON' if current_value else 'OFF'}", style=style, emoji=emoji)

    async def callback(self, interaction: discord.Interaction):
        # Toggle the setting
        current_value = self.cog.config.get_global_cog_setting("manage_sus", self.setting_key, True)
        new_value = not current_value

        # Save immediately
        self.cog.config.set_global_cog_setting("manage_sus", self.setting_key, new_value)

        # Recreate main settings view with updated value
        from thetower.bot.ui.context import SettingsViewContext

        context = SettingsViewContext(
            guild_id=interaction.guild.id if interaction.guild else None,
            cog_instance=self.cog,
            interaction=interaction,
            is_bot_owner=await self.cog.bot.is_owner(interaction.user),
        )
        settings_view = ManageSusSettingsView(context)
        await settings_view.update_display(interaction)


class SettingModal(discord.ui.Modal):
    """Modal for editing individual settings."""

    def __init__(self, cog: BaseCog, setting_name: str, current_value):
        # Create appropriate title and input based on setting type
        title = f"Set {setting_name.replace('_', ' ').title()}"

        super().__init__(title=title)

        self.cog = cog
        self.setting_name = setting_name
        self.current_value = current_value

        # Create input field based on type
        placeholder = f"Enter value (current: {current_value})"

        self.value_input = discord.ui.TextInput(
            label=f"New {setting_name.replace('_', ' ').title()}", placeholder=placeholder, default=str(current_value), required=True, max_length=50
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle setting value submission."""
        try:
            new_value_str = self.value_input.value.strip()

            # Convert value based on type
            new_value = new_value_str

            # Save the setting globally
            self.cog.config.set_global_cog_setting("manage_sus", self.setting_name, new_value)

            embed = discord.Embed(
                title="Setting Updated",
                description=f"**{self.setting_name.replace('_', ' ').title()}:** {self.current_value} → {new_value}",
                color=discord.Color.green(),
            )

            # Update the view with new settings
            view = ManageSusSettingsView(
                self.cog.SettingsViewContext(
                    guild_id=interaction.guild.id if interaction.guild else None,
                    cog_instance=self.cog,
                    interaction=interaction,
                    is_bot_owner=await self.cog.bot.is_owner(interaction.user),
                )
            )
            await interaction.response.edit_message(embed=embed, view=view)

        except ValueError as e:
            embed = discord.Embed(title="Invalid Value", description=f"Error: {str(e)}", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = discord.Embed(title="Error", description=f"Failed to update setting: {str(e)}", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)


class GroupsSelectView(discord.ui.View):
    """View for managing Django groups for view/manage permissions."""

    def __init__(self, cog: BaseCog, interaction: discord.Interaction, current_groups: list, setting_key: str = "view_groups"):
        super().__init__(timeout=900)
        self.cog = cog
        self.original_interaction = interaction
        self.current_groups = set(current_groups)
        self.selected_groups = self.current_groups.copy()
        self.setting_key = setting_key
        self.available_groups = []

        # Get available Django groups
        self._load_available_groups()

        # Add the "Add Group" button
        add_button = discord.ui.Button(label="Add Group", style=discord.ButtonStyle.primary, emoji="➕", custom_id="add_group")
        add_button.callback = self.add_group_callback
        self.add_item(add_button)

        # Add the "Remove Groups" button
        if self.current_groups:  # Only show if there are groups to remove
            remove_button = discord.ui.Button(label="Remove Groups", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="remove_groups")
            remove_button.callback = self.remove_groups_callback
            self.add_item(remove_button)

    @property
    def has_unsaved_changes(self) -> bool:
        """Check if there are unsaved changes."""
        return self.selected_groups != self.current_groups

    def _load_available_groups(self):
        """Load available Django groups synchronously."""
        # For now, we'll use common defaults. In a future update, this could query Django directly
        self.available_groups = ["admin", "moderators", "staff", "verified", "premium", "beta_testers", "supporters"]

    async def add_group_callback(self, interaction: discord.Interaction):
        """Handle adding a new group."""
        # Query Django for available groups
        try:
            from asgiref.sync import sync_to_async
            from django.contrib.auth.models import Group

            # Get all Django groups
            django_groups = await sync_to_async(list)(Group.objects.all().order_by("name"))
            available_groups = [group.name for group in django_groups]
        except Exception as e:
            self.cog.logger.warning(f"Could not query Django groups: {e}, using defaults")
            available_groups = self.available_groups

        # Create dropdown of available groups not already selected
        available_options = [g for g in available_groups if g not in self.selected_groups]

        if not available_options:
            embed = discord.Embed(
                title="No Groups Available",
                description="All available Django groups are already selected, or no groups are configured in Django.",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Create select dropdown
        options = [discord.SelectOption(label=group, value=group) for group in available_options[:25]]  # Discord limit

        select = discord.ui.Select(
            placeholder="Select Django groups to add",
            options=options,
            max_values=len(options),  # Allow selecting multiple
            min_values=1,
            custom_id="add_group_select",
        )

        # Create a temporary view with just the select
        temp_view = discord.ui.View(timeout=300)
        temp_view.add_item(select)

        async def select_callback(select_interaction: discord.Interaction):
            selected_groups = select_interaction.data["values"]
            for group in selected_groups:
                self.selected_groups.add(group)

            # Update the view
            embed = self.create_selection_embed()
            await select_interaction.response.edit_message(embed=embed, view=self)

        select.callback = select_callback

        embed = discord.Embed(
            title="Add Django Groups",
            description="Select one or more Django groups to add to the permission list.",
            color=discord.Color.blue(),
        )

        await interaction.response.send_message(embed=embed, view=temp_view, ephemeral=True)

    async def remove_groups_callback(self, interaction: discord.Interaction):
        """Handle removing multiple groups via dropdown."""
        if not self.selected_groups:
            embed = discord.Embed(
                title="No Groups to Remove",
                description="There are no groups currently selected to remove.",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Create select dropdown of currently selected groups
        options = [discord.SelectOption(label=group, value=group) for group in sorted(self.selected_groups)[:25]]  # Discord limit

        select = discord.ui.Select(
            placeholder="Select groups to remove",
            options=options,
            max_values=len(options),  # Allow selecting all
            min_values=1,
            custom_id="remove_groups_select",
        )

        # Create a temporary view with just the select
        temp_view = discord.ui.View(timeout=300)
        temp_view.add_item(select)

        async def select_callback(select_interaction: discord.Interaction):
            groups_to_remove = select_interaction.data["values"]
            for group in groups_to_remove:
                self.selected_groups.discard(group)

            # Update the view
            embed = self.create_selection_embed()
            await select_interaction.response.edit_message(embed=embed, view=self)

        select.callback = select_callback

        embed = discord.Embed(
            title="Remove Django Groups",
            description="Select one or more Django groups to remove from the permission list.",
            color=discord.Color.red(),
        )

        await interaction.response.send_message(embed=embed, view=temp_view, ephemeral=True)

    def create_selection_embed(self) -> discord.Embed:
        """Create embed showing current group selection."""
        if self.setting_key == "view_groups":
            title = "🔐 Privileged Groups for View"
            description = "Configure which Django groups can view moderation records.\n\n**Current Groups:**"
            no_groups_message = "*No groups selected - no one can view records*"
        elif self.setting_key == "manage_groups":
            title = "🔐 Privileged Groups for Manage"
            description = "Configure which Django groups can create and update moderation records.\n\n**Current Groups:**"
            no_groups_message = "*No groups selected - no one can manage records*"
        elif self.setting_key == "privileged_groups_for_full_ids":
            title = "🔐 Privileged Groups for Full IDs"
            description = "Configure which Django groups can see all player IDs in profiles.\n\n**Current Groups:**"
            no_groups_message = "*No groups selected - only primary IDs shown*"
        elif self.setting_key == "privileged_groups_for_moderation_records":
            title = "🔐 Privileged Groups for Moderation Records"
            description = "Configure which Django groups can see moderation records in profiles.\n\n**Current Groups:**"
            no_groups_message = "*No groups selected - moderation records hidden*"
        else:
            title = "🔐 Manage Django Groups"
            description = "Configure Django group permissions.\n\n**Current Groups:**"
            no_groups_message = "*No groups selected*"

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blue(),
        )

        if self.selected_groups:
            group_list = "\n".join(f"• {group}" for group in sorted(self.selected_groups))
            embed.add_field(name=f"Selected Groups ({len(self.selected_groups)})", value=group_list, inline=False)
        else:
            embed.add_field(name="Selected Groups (0)", value=no_groups_message, inline=False)

        # Show unsaved changes indicator
        if self.has_unsaved_changes:
            embed.color = discord.Color.orange()
            embed.set_footer(text="⚠️ UNSAVED CHANGES • Click 'Save Changes' to apply or 'Cancel' to discard")
        else:
            embed.set_footer(text="Use 'Add Group' to add more groups • Use 'Remove Groups' to delete groups")
        return embed

    @discord.ui.button(label="Save Changes", style=discord.ButtonStyle.success, emoji="💾", row=4)
    async def save_changes(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Save the selected groups."""
        new_groups = sorted(list(self.selected_groups))

        # Save the setting globally in bot config
        self.cog.config.set_global_cog_setting("manage_sus", self.setting_key, new_groups)

        setting_name = (
            "View Groups"
            if self.setting_key == "view_groups"
            else (
                "Manage Groups"
                if self.setting_key == "manage_groups"
                else (
                    "Full IDs Groups"
                    if self.setting_key == "privileged_groups_for_full_ids"
                    else "Moderation Records Groups" if self.setting_key == "privileged_groups_for_moderation_records" else "Groups"
                )
            )
        )
        description = f"**{setting_name}:** {len(new_groups)} groups configured\n"
        if new_groups:
            description += f"**Groups:** {', '.join(new_groups)}"
        else:
            description += "**No groups configured**"

        embed = discord.Embed(
            title=f"{setting_name} Updated",
            description=description,
            color=discord.Color.green(),
        )

        # Send confirmation message
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Update the original message with main settings view
        from thetower.bot.ui.context import SettingsViewContext

        context = SettingsViewContext(
            guild_id=interaction.guild.id if interaction.guild else None,
            cog_instance=self.cog,
            interaction=self.original_interaction,
            is_bot_owner=await self.cog.bot.is_owner(interaction.user),
        )
        settings_view = ManageSusSettingsView(context)
        main_embed = discord.Embed(
            title="⚙️ Manage Sus Settings", description="Configure moderation record permissions and visibility", color=discord.Color.blue()
        )
        # Manually update display
        await self.original_interaction.edit_original_response(embed=main_embed, view=settings_view)
        await settings_view.update_display(self.original_interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=4)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel and return to main settings."""
        # Return to the main settings view
        from thetower.bot.ui.context import SettingsViewContext

        context = SettingsViewContext(
            guild_id=interaction.guild.id if interaction.guild else None,
            cog_instance=self.cog,
            interaction=self.original_interaction,
            is_bot_owner=await self.cog.bot.is_owner(interaction.user),
        )
        settings_view = ManageSusSettingsView(context)
        await settings_view.update_display(interaction)
