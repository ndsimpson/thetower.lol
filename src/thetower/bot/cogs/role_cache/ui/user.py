# Third-party
import datetime

import discord

# Local
from .core import RoleLookupEmbed


class RoleStatsCommand:
    """Command for displaying role statistics."""

    @staticmethod
    async def execute(ctx, cog, match_string=None):
        """Execute the rolestats command."""
        await ctx.typing()

        if not ctx.guild:
            return await ctx.send("This command must be used in a server.")

        # Make sure the cache for this guild is ready
        if not cog.is_ready:
            return await ctx.send("Role cache is still being built. Please try again later.")

        # Count users per role
        role_counts = {}
        guild_id = ctx.guild.id

        # Initialize counts for all roles in the guild
        for role in ctx.guild.roles:
            role_counts[role.id] = 0

        # Count instances of each role
        if guild_id in cog.member_roles:
            for member_id, data in cog.member_roles[guild_id].items():
                for role_id in data.get("roles", []):
                    if role_id in role_counts:
                        role_counts[role_id] += 1

        # Create a list of (role, count) tuples filtered by match string if provided
        role_stats = []
        for role in ctx.guild.roles:
            if match_string is None or match_string.lower() in role.name.lower():
                role_stats.append((role, role_counts[role.id]))

        # Sort by count (highest first)
        role_stats.sort(key=lambda x: x[1], reverse=True)

        # No matching roles
        if not role_stats:
            return await ctx.send(f"No roles found matching '{match_string}'")

        # Create plain text output
        header = f"Role Statistics in {ctx.guild.name}"
        if match_string:
            header += f" matching '{match_string}'"

        lines = [header, "=" * len(header), ""]

        # Add role counts
        for role, count in role_stats:
            lines.append(f"{role.name}: {count} members")

        # Footer with total count
        lines.append("")
        lines.append(f"Total: {len(role_stats)} roles")

        # Join all lines
        full_text = "\n".join(lines)

        # Handle Discord's 2000 character limit
        if len(full_text) <= 1994:  # Leave room for code block markers
            await ctx.send(f"```\n{full_text}\n```")
        else:
            # Split into multiple messages if too long
            chunks = []
            current_chunk = [header, "=" * len(header), ""]
            current_length = sum(len(line) + 1 for line in current_chunk)  # +1 for newline

            for line in lines[3:-2]:  # Skip header and footer we already added
                # Check if adding this line would exceed limit
                line_length = len(line) + 1  # +1 for newline
                if current_length + line_length > 1900:  # Conservative limit
                    # Finish current chunk
                    chunks.append("\n".join(current_chunk))
                    # Start new chunk
                    current_chunk = [f"{header} (continued)", "=" * len(header), ""]
                    current_length = sum(len(line) + 1 for line in current_chunk)

                # Add line to current chunk
                current_chunk.append(line)
                current_length += line_length

            # Add footer to last chunk
            current_chunk.append("")
            current_chunk.append(f"Total: {len(role_stats)} roles")
            chunks.append("\n".join(current_chunk))

            # Send all chunks
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await ctx.send(f"```\n{chunk}\n```")
                else:
                    await ctx.send(f"```\n{chunk}\n```")


class LookupCommand:
    """Command for looking up cached roles for a member."""

    @staticmethod
    async def execute(ctx, cog, member: discord.Member):
        """Execute the lookup command."""
        if not ctx.guild:
            return await ctx.send("This command must be used in a server.")

        guild_id = ctx.guild.id
        user_id = member.id

        if guild_id not in cog.member_roles or user_id not in cog.member_roles[guild_id]:
            return await ctx.send(f"❌ No cached roles found for {member.display_name}")

        # Get cached data
        cache_data = cog.member_roles[guild_id][user_id]
        role_ids = cache_data["roles"]
        updated_at = datetime.datetime.fromtimestamp(cache_data["updated_at"], tz=datetime.timezone.utc)

        # Check if stale
        is_stale = cog.is_stale(guild_id, user_id)

        # Create and send embed
        embed = RoleLookupEmbed.create(member, role_ids, updated_at, is_stale)
        await ctx.send(embed=embed)


class RefreshCommand:
    """Command for refreshing role cache."""

    @staticmethod
    async def execute(ctx, cog, target: discord.Member = None):
        """Execute the refresh command."""
        if not ctx.guild:
            return await ctx.send("This command must be used in a server.")

        # Defer response for potentially long operation
        await ctx.defer()

        async with cog.task_tracker.task_context("Manual Refresh") as tracker:
            if target:
                tracker.update_status(f"Refreshing roles for {target.display_name}")
                cog.update_member_roles(target)
                await ctx.send(f"✅ Refreshed roles for {target.display_name}")
            else:
                total_members = len(ctx.guild.members)
                message = await ctx.send(f"🔄 Refreshing roles for all members in {ctx.guild.name}...")

                try:
                    for i, member in enumerate(ctx.guild.members, 1):
                        tracker.update_status(f"Processing member {i}/{total_members}")
                        cog.update_member_roles(member)

                        if i % 100 == 0:  # Update progress every 100 members
                            try:
                                await message.edit(content=f"🔄 Refreshing roles: {i}/{total_members} members processed...")
                            except discord.NotFound:
                                # Message was deleted, create new one
                                message = await ctx.send(f"🔄 Refreshing roles: {i}/{total_members} members processed...")

                    await message.edit(content=f"✅ Refreshed roles for all {total_members} members in {ctx.guild.name}")
                    await cog.save_data_if_modified(cog.member_roles, cog.cache_file, force=True)

                except discord.Forbidden:
                    await ctx.send("❌ I don't have permission to manage roles in this server.")
                except discord.HTTPException as e:
                    if e.status == 429:  # Rate limited
                        await ctx.send(f"⚠️ Rate limited by Discord. Please try again in {e.retry_after:.1f} seconds.")
                    else:
                        await ctx.send(f"❌ Discord API error: {e.text}")
                except Exception as e:
                    cog.logger.error(f"Error refreshing roles: {e}", exc_info=True)
                    await ctx.send(f"❌ An error occurred: {str(e)}")


class ReloadCommand:
    """Command for reloading/refresing role cache (alias for refresh)."""

    @staticmethod
    async def execute(ctx, cog, target: discord.Member = None):
        """Execute the reload command."""
        # Just delegate to refresh command
        await RefreshCommand.execute(ctx, cog, target)


class UserCommands:
    """Container for user-facing role cache commands."""

    def __init__(self, cog):
        self.cog = cog

    async def rolestats(self, ctx, *, match_string=None):
        """Show counts of how many users have each role."""
        await RoleStatsCommand.execute(ctx, self.cog, match_string)

    async def lookup(self, ctx, member: discord.Member):
        """Look up cached roles for a member."""
        await LookupCommand.execute(ctx, self.cog, member)

    async def refresh(self, ctx, target: discord.Member = None):
        """Refresh role cache for a user or the entire server."""
        await RefreshCommand.execute(ctx, self.cog, target)

    async def reload(self, ctx, target: discord.Member = None):
        """Reload/refresh role cache for a user or the entire server."""
        await ReloadCommand.execute(ctx, self.cog, target)
