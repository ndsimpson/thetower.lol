# Settings interface for the Django Admin cog

import discord

from thetower.bot.basecog import BaseCog
from thetower.bot.ui.context import BaseSettingsView, SettingsViewContext

from .main import DjangoAdminMainView


class DjangoAdminSettingsView(BaseSettingsView):
    """Settings view for Django Admin cog that integrates with global settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(context)
        self.guild_id = str(context.guild_id) if context.guild_id else None

        # Get current global settings
        self.allowed_bot_owners = self.cog.get_global_setting("allowed_bot_owners", [])

        # Add button to open Django admin interface
        admin_button = discord.ui.Button(label="Open Django Admin", style=discord.ButtonStyle.primary, emoji="🔧", row=0)
        admin_button.callback = self.open_admin_interface
        self.add_item(admin_button)

        # Build options list for settings
        options = [
            discord.SelectOption(
                label="Allowed Bot Owners",
                value="allowed_bot_owners",
                description="Additional Discord user IDs that can use admin commands",
            ),
        ]

        # Create the select for settings
        self.setting_select = discord.ui.Select(placeholder="Modify settings", options=options, row=1)
        self.setting_select.callback = self.setting_select_callback
        self.add_item(self.setting_select)

    def create_settings_embed(self) -> discord.Embed:
        """Create the settings embed with current values."""
        embed = discord.Embed(
            title="⚙️ Django Admin Settings",
            color=discord.Color.blue(),
            description="Configure bot owner permissions and access Django administration tools.",
        )

        embed.add_field(
            name="🔧 Django Administration", value="Click **Open Django Admin** to manage Django users, groups, and user linking.", inline=False
        )

        embed.add_field(
            name="🔐 Permission Settings",
            value=f"**Allowed Bot Owners:** {len(self.allowed_bot_owners)} additional users",
            inline=False,
        )

        if self.allowed_bot_owners:
            owners_list = "\n".join(f"• <@{uid}> (`{uid}`)" for uid in self.allowed_bot_owners[:10])
            if len(self.allowed_bot_owners) > 10:
                owners_list += f"\n... and {len(self.allowed_bot_owners) - 10} more"
            embed.add_field(name="Additional Bot Owners", value=owners_list, inline=False)

        embed.set_footer(text="Click button to open admin interface • Use dropdown to manage settings")
        return embed

    async def open_admin_interface(self, interaction: discord.Interaction):
        """Open the Django admin interface."""
        view = DjangoAdminMainView(self.cog, interaction, parent_view=self)
        embed = view.create_main_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    async def setting_select_callback(self, interaction: discord.Interaction):
        """Handle setting selection for configuration."""
        setting_name = self.setting_select.values[0]

        # Handle allowed bot owners setting
        if setting_name == "allowed_bot_owners":
            view = AllowedOwnersView(self.cog, interaction, self.allowed_bot_owners)
            embed = view.create_selection_embed()
            await interaction.response.edit_message(embed=embed, view=view)
            return

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Return to cog management."""
        embed = discord.Embed(
            title="Returned to Cog Management",
            description="Use the cog management interface to select another cog or return to the main menu.",
            color=discord.Color.blue(),
        )
        await interaction.response.edit_message(embed=embed, view=None)


class AllowedOwnersView(discord.ui.View):
    """View for managing additional bot owners."""

    def __init__(self, cog: BaseCog, interaction: discord.Interaction, current_owners: list):
        super().__init__(timeout=900)
        self.cog = cog
        self.original_interaction = interaction
        self.current_owners = set(current_owners)
        self.selected_owners = self.current_owners.copy()

        # Add the "Add User" button
        add_button = discord.ui.Button(label="Add User", style=discord.ButtonStyle.primary, emoji="➕", custom_id="add_user")
        add_button.callback = self.add_user_callback
        self.add_item(add_button)

        # Add the "Remove Users" button
        if self.current_owners:
            remove_button = discord.ui.Button(label="Remove Users", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="remove_users")
            remove_button.callback = self.remove_users_callback
            self.add_item(remove_button)

    async def add_user_callback(self, interaction: discord.Interaction):
        """Handle adding a new bot owner."""
        modal = AddOwnerModal(self)
        await interaction.response.send_modal(modal)

    async def remove_users_callback(self, interaction: discord.Interaction):
        """Handle removing bot owners via dropdown."""
        if not self.selected_owners:
            embed = discord.Embed(
                title="No Users to Remove",
                description="There are no additional bot owners configured.",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Create select dropdown of current owners
        options = [
            discord.SelectOption(label=f"User ID: {uid}", value=str(uid), description="Click to remove") for uid in sorted(self.selected_owners)
        ][
            :25
        ]  # Discord limit

        select = discord.ui.Select(
            placeholder="Select users to remove",
            options=options,
            max_values=len(options),
            min_values=1,
            custom_id="remove_owners_select",
        )

        temp_view = discord.ui.View(timeout=300)
        temp_view.add_item(select)

        async def select_callback(select_interaction: discord.Interaction):
            users_to_remove = [int(uid) for uid in select_interaction.data["values"]]
            for uid in users_to_remove:
                self.selected_owners.discard(uid)

            # Update the view
            embed = self.create_selection_embed()
            await select_interaction.response.edit_message(embed=embed, view=self)

        select.callback = select_callback

        embed = discord.Embed(
            title="Remove Additional Bot Owners",
            description="Select one or more users to remove from the allowed bot owners list.",
            color=discord.Color.red(),
        )

        await interaction.response.send_message(embed=embed, view=temp_view, ephemeral=True)

    def create_selection_embed(self) -> discord.Embed:
        """Create embed showing current owner selection."""
        embed = discord.Embed(
            title="🔐 Additional Bot Owners",
            description="Configure which Discord users can use bot owner commands.\n\n**Current Users:**",
            color=discord.Color.blue(),
        )

        if self.selected_owners:
            owners_list = "\n".join(f"• <@{uid}> (`{uid}`)" for uid in sorted(self.selected_owners))
            embed.add_field(name=f"Allowed Users ({len(self.selected_owners)})", value=owners_list, inline=False)
        else:
            embed.add_field(name="Allowed Users (0)", value="*No additional bot owners configured*", inline=False)

        embed.set_footer(text="Use 'Add User' to add users • Use 'Remove Users' to remove users • Click Save when done")
        return embed

    @discord.ui.button(label="Save Changes", style=discord.ButtonStyle.success, emoji="💾", row=4)
    async def save_changes(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Save the selected owners."""
        new_owners = sorted(list(self.selected_owners))

        # Save the setting globally
        self.cog.set_global_setting("allowed_bot_owners", new_owners)

        description = f"**Additional Bot Owners:** {len(new_owners)} users configured\n"
        if new_owners:
            owners_list = ", ".join(f"<@{uid}>" for uid in new_owners[:5])
            if len(new_owners) > 5:
                owners_list += f" and {len(new_owners) - 5} more"
            description += f"**Users:** {owners_list}"
        else:
            description += "**No additional owners configured**"

        embed = discord.Embed(
            title="Bot Owners Updated",
            description=description,
            color=discord.Color.green(),
        )

        # Return to the main settings view
        view = DjangoAdminSettingsView(
            self.cog.SettingsViewContext(
                guild_id=interaction.guild.id if interaction.guild else None,
                cog_instance=self.cog,
                interaction=interaction,
                is_bot_owner=await self.cog.bot.is_owner(interaction.user),
            )
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=4)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel and return to main settings."""
        embed = discord.Embed(title="Cancelled", description="User selection cancelled. No changes were made.", color=discord.Color.orange())

        # Return to the main settings view
        view = DjangoAdminSettingsView(
            self.cog.SettingsViewContext(
                guild_id=interaction.guild.id if interaction.guild else None,
                cog_instance=self.cog,
                interaction=interaction,
                is_bot_owner=await self.cog.bot.is_owner(interaction.user),
            )
        )
        await interaction.response.edit_message(embed=embed, view=view)


class AddOwnerModal(discord.ui.Modal):
    """Modal for adding a new bot owner by Discord ID."""

    def __init__(self, parent_view: AllowedOwnersView):
        super().__init__(title="Add Additional Bot Owner")
        self.parent_view = parent_view

        self.user_id_input = discord.ui.TextInput(
            label="Discord User ID", placeholder="Enter the Discord user ID (numeric)", required=True, max_length=20
        )
        self.add_item(self.user_id_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle user ID submission."""
        try:
            user_id_str = self.user_id_input.value.strip()

            # Try to convert to integer
            user_id = int(user_id_str)

            # Check if already in the list
            if user_id in self.parent_view.selected_owners:
                embed = discord.Embed(
                    title="User Already Added",
                    description=f"User <@{user_id}> (`{user_id}`) is already in the allowed bot owners list.",
                    color=discord.Color.orange(),
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Add to selected owners
            self.parent_view.selected_owners.add(user_id)

            # Update the view
            embed = self.parent_view.create_selection_embed()
            await interaction.response.edit_message(embed=embed, view=self.parent_view)

        except ValueError:
            embed = discord.Embed(
                title="Invalid User ID",
                description="Please enter a valid numeric Discord user ID.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = discord.Embed(
                title="Error",
                description=f"Failed to add user: {str(e)}",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
