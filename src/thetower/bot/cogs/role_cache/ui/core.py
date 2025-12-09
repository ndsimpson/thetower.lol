# Standard library
import datetime

# Third-party
import discord

# Local
from thetower.bot.basecog import BaseCog


class RoleCacheHelpers:
    """Helper functions for role cache operations."""

    @staticmethod
    def format_time_value(seconds: int) -> str:
        """Format seconds into a human-readable time string."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m"

    @staticmethod
    def format_relative_time(timestamp: datetime.datetime) -> str:
        """Format a timestamp as relative time."""
        now = datetime.datetime.now()
        diff = now - timestamp

        if diff.days > 0:
            return f"{diff.days} days ago"
        elif diff.seconds >= 3600:
            hours = diff.seconds // 3600
            return f"{hours} hours ago"
        elif diff.seconds >= 60:
            minutes = diff.seconds // 60
            return f"{minutes} minutes ago"
        else:
            return f"{diff.seconds} seconds ago"

    @staticmethod
    def create_status_embed(cog: BaseCog, has_errors: bool = False) -> discord.Embed:
        """Create a status embed for the role cache."""
        # Determine overall status
        if not cog.is_ready:
            status_emoji = "⏳"
            status_text = "Initializing"
            embed_color = discord.Color.orange()
        elif has_errors:
            status_emoji = "❌"
            status_text = "Error"
            embed_color = discord.Color.red()
        else:
            status_emoji = "✅"
            status_text = "Operational"
            embed_color = discord.Color.blue()

        embed = discord.Embed(title="Role Cache Status", description=f"Current status: {status_emoji} {status_text}", color=embed_color)

        return embed

    @staticmethod
    def add_cache_stats_fields(embed: discord.Embed, cog) -> None:
        """Add cache statistics fields to an embed."""
        # Get cache statistics only for allowed guilds
        enabled_guilds = []
        for guild in cog.bot.guilds:
            if cog.bot.cog_manager.can_guild_use_cog("role_cache", guild.id):
                enabled_guilds.append(guild)

        guild_count = len(cog.member_roles)  # Count actual cached guilds
        total_members = sum(len(cog.member_roles.get(guild.id, {})) for guild in enabled_guilds)

        # Count stale entries only for enabled guilds
        stale_count = 0
        for guild in enabled_guilds:
            if guild.id in cog.member_roles:
                for member_id, data in cog.member_roles[guild.id].items():
                    if cog.is_stale(guild.id, member_id):
                        stale_count += 1

        # Main statistics
        stats_fields = [
            (
                "Cache Overview",
                [
                    f"**Guilds Cached**: {guild_count}",
                    f"**Members Cached**: {total_members}",
                    f"**Stale Entries**: {stale_count}",
                    f"**Status**: {'Ready' if cog.is_ready else 'Building'}",
                ],
            ),
            (
                "Configuration",
                [
                    f"**Refresh Interval**: {RoleCacheHelpers.format_time_value(cog.refresh_interval)}",
                    f"**Staleness Threshold**: {RoleCacheHelpers.format_time_value(cog.staleness_threshold)}",
                    f"**Save Interval**: {RoleCacheHelpers.format_time_value(cog.save_interval)}",
                ],
            ),
        ]

        for name, items in stats_fields:
            embed.add_field(name=name, value="\n".join(items), inline=False)

    @staticmethod
    def add_file_info_field(embed: discord.Embed, cache_file) -> None:
        """Add cache file information to an embed."""
        if cache_file.exists():
            size_kb = cache_file.stat().st_size / 1024
            modified = datetime.datetime.fromtimestamp(cache_file.stat().st_mtime)
            embed.add_field(name="Cache File", value=f"Size: {size_kb:.1f} KB\nLast Modified: {modified.strftime('%Y-%m-%d %H:%M:%S')}", inline=False)

    @staticmethod
    def add_process_info_field(embed: discord.Embed, cog) -> None:
        """Add active process information to an embed."""
        active_process = getattr(cog, "_active_process", None)
        if active_process:
            process_start = getattr(cog, "_process_start_time", None)
            if process_start:
                time_since = (datetime.datetime.now() - process_start).total_seconds()
                time_str = f"{int(time_since // 60)}m {int(time_since % 60)}s ago"
                embed.add_field(name="Active Processes", value=f"🔄 {active_process} (started {time_str})", inline=False)

    @staticmethod
    def add_activity_info_field(embed: discord.Embed, cog) -> None:
        """Add last activity information to an embed."""
        last_refresh = getattr(cog, "_last_refresh_time", None)
        if last_refresh:
            time_str = RoleCacheHelpers.format_relative_time(last_refresh)
            embed.add_field(name="Last Activity", value=f"Cache refreshed: {time_str}", inline=False)


class RoleLookupEmbed:
    """Embed for displaying cached role information for a member."""

    @staticmethod
    def create(member: discord.Member, role_ids: set, updated_at: datetime.datetime, is_stale: bool) -> discord.Embed:
        """Create an embed showing cached roles for a member."""
        embed = discord.Embed(title=f"Cached Roles for {member.display_name}", color=discord.Color.orange() if is_stale else discord.Color.blue())

        # Get role names from IDs
        role_names = []
        for role_id in role_ids:
            role = member.guild.get_role(role_id)
            if role:
                role_names.append(f"{role.name}")

        # Format embed fields
        embed.add_field(name="Roles", value="\n".join(role_names) if role_names else "No roles", inline=False)

        # Add information about cache freshness
        now = datetime.datetime.now(datetime.timezone.utc)
        cache_age = now - updated_at

        hours, remainder = divmod(int(cache_age.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        age_str = f"{hours}h {minutes}m {seconds}s ago"

        embed.add_field(name="Last Updated", value=f"{updated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n({age_str})", inline=False)

        # Add indicator if cache is stale
        if is_stale:
            embed.add_field(name="Status", value="⚠️ Stale cache", inline=False)
        else:
            embed.add_field(name="Status", value="✅ Cache is fresh", inline=False)

        return embed


class SettingsEmbed:
    """Embed for displaying role cache settings."""

    @staticmethod
    def create(settings: dict) -> discord.Embed:
        """Create an embed displaying current settings."""
        embed = discord.Embed(title="Role Cache Settings", description="Current configuration for role caching system", color=discord.Color.blue())

        for name, value in settings.items():
            # Format durations in a more readable way for time-based settings
            if name in ["refresh_interval", "staleness_threshold", "save_interval"]:
                hours = value // 3600
                minutes = (value % 3600) // 60
                seconds = value % 60
                formatted_value = f"{hours}h {minutes}m {seconds}s ({value} seconds)"
                embed.add_field(name=name, value=formatted_value, inline=False)
            else:
                embed.add_field(name=name, value=str(value), inline=False)

        return embed
