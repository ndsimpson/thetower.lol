# Standard library imports
import datetime
import logging

# Third-party imports
import discord
from discord.ext import commands

# Local application imports
from thetower.bot.basecog import BaseCog

# UI imports
from .ui import DjangoAdminSettingsView

logger = logging.getLogger(__name__)


class DjangoAdmin(BaseCog, name="Django Admin"):
    """Cog for managing Django users and groups.

    Provides bot owner functionality for:
    - Managing Django groups (create, edit, delete)
    - Managing Django user memberships in groups
    - Linking/unlinking Django users to Discord users and KnownPlayers
    """

    # Settings view class for the cog manager - only accessible to bot owner
    settings_view_class = DjangoAdminSettingsView

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.logger.info("Initializing DjangoAdmin")

        # Store a reference to this cog
        self.bot.django_admin = self

        # Global settings (bot-wide) - this cog is bot owner only
        self.global_settings = {
            "allowed_bot_owners": [],  # Additional Discord user IDs that can use admin commands
        }

    async def cog_initialize(self) -> None:
        """Initialize the cog - called by BaseCog during ready process."""
        self.logger.info("Initializing Django Admin module...")

        try:
            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                tracker.update_status("Loading data")
                await super().cog_initialize()

                # Update status variables
                self._last_operation_time = datetime.datetime.utcnow()
                self._operation_count = 0

                # Mark as ready
                self.set_ready(True)
                self.logger.info("Django Admin initialization complete")

        except Exception as e:
            self._has_errors = True
            self.logger.error(f"Failed to initialize Django Admin module: {e}", exc_info=True)
            raise

    async def _check_additional_interaction_permissions(self, interaction: discord.Interaction) -> bool:
        """Override to enforce bot owner only access."""
        # Check if user is bot owner
        is_bot_owner = await self.bot.is_owner(interaction.user)

        # Check if user is in allowed bot owners list
        allowed_owners = self.get_global_setting("allowed_bot_owners", [])
        is_allowed = interaction.user.id in allowed_owners

        if not is_bot_owner and not is_allowed:
            await interaction.response.send_message("❌ This command is restricted to bot owners only.", ephemeral=True)
            return False

        return True


# ====================
# Cog Setup
# ====================


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DjangoAdmin(bot))
    bot.logger.info("DjangoAdmin cog loaded - slash commands will sync per-guild via CogManager")
