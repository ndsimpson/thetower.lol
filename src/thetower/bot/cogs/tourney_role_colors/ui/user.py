"""
User-facing interaction flows for the Tourney Role Colors cog.

This module contains:
- Color selection views and buttons
- User interaction handling
"""

from typing import Any, Dict, List, Optional

import discord
from discord import ui


class ColorSelectionView(ui.View):
    """Main view for color role selection."""

    def __init__(self, cog, qualified_data: List[Dict[str, Any]], current_role_id: Optional[int]):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog
        self.qualified_data = qualified_data
        self.current_role_id = current_role_id

        # Add category buttons
        for category_info in qualified_data:
            self.add_item(CategoryButton(category_info, self.cog, self.current_role_id))

        # Add remove button if user has a color role
        if current_role_id:
            self.add_item(RemoveColorButton(self.cog))


class CategoryButton(ui.Button):
    """Button to select a color category."""

    def __init__(self, category_info: Dict[str, Any], cog, current_role_id: Optional[int]):
        category_name = category_info["category_name"]
        role_count = len(category_info["roles"])

        # Get emoji for category
        emoji = self._get_category_emoji(category_name)

        super().__init__(
            label=f"{category_name} ({role_count} available)",
            emoji=emoji,
            style=discord.ButtonStyle.primary
        )

        self.category_info = category_info
        self.cog = cog
        self.current_role_id = current_role_id

    async def callback(self, interaction: discord.Interaction):
        """Show role selection for this category."""
        # Create role selection view
        role_view = RoleSelectionView(
            self.category_info,
            self.cog,
            self.current_role_id
        )

        embed = discord.Embed(
            title=f"🎨 {self.category_info['category_name']} Roles",
            description="Select a color role from this category:",
            color=discord.Color.blue()
        )

        # Add current role info
        if self.current_role_id:
            current_role = interaction.guild.get_role(self.current_role_id)
            if current_role:
                embed.add_field(
                    name="Current Role",
                    value=current_role.mention,
                    inline=False
                )

        await interaction.response.edit_message(embed=embed, view=role_view)

    @staticmethod
    def _get_category_emoji(category_name: str) -> str:
        """Get emoji for category."""
        emoji_map = {
            "Orange": "🟠",
            "Red": "🔴",
            "Blue": "🔵",
            "Green": "🟢",
            "Purple": "🟣",
            "Yellow": "🟡",
            "Pink": "🩷",
            "VIP": "💎",
            "Premium": "⭐",
        }
        return emoji_map.get(category_name, "🎨")


class RoleSelectionView(ui.View):
    """View for selecting a specific role within a category."""

    def __init__(self, category_info: Dict[str, Any], cog, current_role_id: Optional[int]):
        super().__init__(timeout=300)
        self.category_info = category_info
        self.cog = cog
        self.current_role_id = current_role_id

        # Add role buttons
        for role_info in category_info["roles"]:
            self.add_item(RoleButton(role_info, cog, current_role_id))

        # Add back button
        self.add_item(BackButton())

        # Add remove button if user has a color role
        if current_role_id:
            self.add_item(RemoveColorButton(cog))


class RoleButton(ui.Button):
    """Button to select a specific color role."""

    def __init__(self, role_info: Dict[str, Any], cog, current_role_id: Optional[int]):
        role_name = role_info["role_name"]
        is_current = (role_info["role_id"] == current_role_id)

        # Style based on whether it's current role
        style = discord.ButtonStyle.success if is_current else discord.ButtonStyle.secondary
        label = f"✓ {role_name}" if is_current else role_name

        super().__init__(
            label=label,
            style=style,
            disabled=is_current  # Can't select current role
        )

        self.role_info = role_info
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Assign the selected color role."""
        role_id = self.role_info["role_id"]
        role_name = self.role_info["role_name"]

        # Assign the role
        success = await self.cog.core.assign_color_role(interaction.user, role_id)

        if success:
            embed = discord.Embed(
                title="✅ Color Role Updated",
                description=f"You now have the {role_name} role!",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to assign color role. Please try again or contact an administrator.",
                color=discord.Color.red()
            )

        # Disable all buttons since action is complete
        for item in self.view.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self.view)


class BackButton(ui.Button):
    """Button to go back to category selection."""

    def __init__(self):
        super().__init__(
            label="⬅️ Back",
            style=discord.ButtonStyle.secondary
        )

    async def callback(self, interaction: discord.Interaction):
        """Go back to main color selection view."""
        # Get fresh qualified data
        tourney_colors = self.view.cog
        qualified_data = tourney_colors.core.get_qualified_roles_for_user(interaction.user)
        current_role_id = tourney_colors.core.get_user_current_color_role(interaction.user)

        # Create main view
        main_view = ColorSelectionView(tourney_colors, qualified_data, current_role_id)

        embed = discord.Embed(
            title="🎨 Color Role Selection",
            description="Choose a category to view available color roles:",
            color=discord.Color.blue()
        )

        # Add current role info
        if current_role_id:
            current_role = interaction.guild.get_role(current_role_id)
            if current_role:
                embed.add_field(
                    name="Current Role",
                    value=current_role.mention,
                    inline=False
                )

        await interaction.response.edit_message(embed=embed, view=main_view)


class RemoveColorButton(ui.Button):
    """Button to remove current color role."""

    def __init__(self, cog):
        super().__init__(
            label="❌ Remove Color Role",
            style=discord.ButtonStyle.danger
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Remove the user's current color role."""
        success = await self.cog.core.remove_color_role(interaction.user)

        if success:
            embed = discord.Embed(
                title="✅ Color Role Removed",
                description="Your color role has been removed.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to remove color role. Please try again or contact an administrator.",
                color=discord.Color.red()
            )

        # Disable all buttons since action is complete
        for item in self.view.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self.view)
        await interaction.response.edit_message(embed=embed, view=self.view)
