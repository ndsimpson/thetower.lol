# Third-party

# Local
from .core import RoleCacheHelpers, SettingsEmbed


class SettingsCommand:
    """Command for displaying role cache settings."""

    @staticmethod
    async def execute(ctx, cog):
        """Execute the settings command."""
        settings = cog.get_all_settings(ctx=ctx)
        embed = SettingsEmbed.create(settings)
        await ctx.send(embed=embed)


class SetSettingCommand:
    """Command for changing role cache settings."""

    @staticmethod
    async def execute(ctx, cog, setting_name: str, value: int):
        """Execute the set setting command."""
        valid_settings = ["refresh_interval", "staleness_threshold", "save_interval"]

        if setting_name not in valid_settings:
            valid_settings_str = ", ".join(valid_settings)
            return await ctx.send(f"Invalid setting name. Valid options: {valid_settings_str}")

        # Validate inputs based on the setting
        if setting_name in ["refresh_interval", "staleness_threshold", "save_interval"]:
            if value < 60:  # Minimum 60 seconds for time intervals
                return await ctx.send(f"Value for {setting_name} must be at least 60 seconds")

        # Update instance variables immediately
        if setting_name == "refresh_interval":
            cog.refresh_interval = value
        elif setting_name == "staleness_threshold":
            cog.staleness_threshold = value
        elif setting_name == "save_interval":
            cog.save_interval = value

        # Save the setting
        cog.set_setting(setting_name, value, ctx=ctx)

        # Format confirmation message
        hours = value // 3600
        minutes = (value % 3600) // 60
        seconds = value % 60
        time_format = f"{hours}h {minutes}m {seconds}s"
        await ctx.send(f"✅ Set {setting_name} to {value} seconds ({time_format})")

        cog.logger.info(f"Settings changed: {setting_name} set to {value} by {ctx.author}")


class StatusCommand:
    """Command for displaying operational status."""

    @staticmethod
    async def execute(ctx, cog):
        """Execute the status command."""
        # Determine overall status
        has_errors = hasattr(cog, "_has_errors") and cog._has_errors

        embed = RoleCacheHelpers.create_status_embed(cog, has_errors)

        # Add cache statistics
        RoleCacheHelpers.add_cache_stats_fields(embed, cog)

        # Add cache file information
        RoleCacheHelpers.add_file_info_field(embed, cog.cache_file)

        # Add active process information
        RoleCacheHelpers.add_process_info_field(embed, cog)

        # Add last activity information
        RoleCacheHelpers.add_activity_info_field(embed, cog)

        # Add task tracking information
        cog.add_task_status_fields(embed)

        await ctx.send(embed=embed)


class ForceFetchCommand:
    """Command for forcing a complete member fetch."""

    @staticmethod
    async def execute(ctx, cog):
        """Execute the force fetch command."""
        async with cog.task_tracker.task_context("Force Fetch", "Starting complete member fetch") as tracker:
            progress_msg = await ctx.send("Starting complete member fetch for all guilds...")

            for guild in cog.bot.guilds:
                tracker.update_status(f"Fetching {guild.name}")
                await progress_msg.edit(content=f"Fetching {guild.name}...")

                try:
                    await cog.build_cache(guild)
                    await ctx.send(f"✅ Fetched members from {guild.name}")
                except Exception as e:
                    cog.logger.error(f"Error fetching {guild.name}: {e}", exc_info=True)
                    await ctx.send(f"❌ Error fetching {guild.name}: {str(e)}")

            await progress_msg.edit(content="Complete member fetch finished!")


class AdminCommands:
    """Container for administrative role cache commands."""

    def __init__(self, cog):
        self.cog = cog

    async def settings(self, ctx):
        """Display current role cache settings."""
        await SettingsCommand.execute(ctx, self.cog)

    async def set_setting(self, ctx, setting_name: str, value: int):
        """Change a role cache setting."""
        await SetSettingCommand.execute(ctx, self.cog, setting_name, value)

    async def status(self, ctx):
        """Display current operational status and statistics."""
        await StatusCommand.execute(ctx, self.cog)

    async def forcefetch(self, ctx):
        """Force a complete refresh using fetch_members."""
        await ForceFetchCommand.execute(ctx, self.cog)
