"""
Verification Backfill Cog

Bot owner utility to backfill verification dates from verification log channel.
Allows previewing changes before applying them via the settings UI.
"""

import asyncio
import datetime
import logging

import discord
from asgiref.sync import sync_to_async

from thetower.backend.sus.models import LinkedAccount
from thetower.bot.basecog import BaseCog

from .ui import VerificationBackfillSettingsView

logger = logging.getLogger(__name__)

# Placeholder date used for unknown verification times
PLACEHOLDER_TIMESTAMP = 1577836800  # 2020-01-01 00:00:00 UTC


class VerificationBackfill(BaseCog, name="Verification Backfill"):
    """Bot owner cog for backfilling verification dates from log channel."""

    settings_view_class = VerificationBackfillSettingsView

    # Bot owner only settings
    global_settings = {
        "enabled": True,
        "public": False,  # Only bot owner can use this
        "global_log_channel_id": None,  # Global log channel for all backfill operations
    }

    def __init__(self, bot):
        super().__init__(bot)

        # Track running backfill tasks
        self.backfill_tasks = {}  # {guild_id: asyncio.Task}
        self.backfill_cancelled = {}  # {guild_id: bool}

    async def cog_load(self):
        """Load saved backfill state on cog load."""
        await super().cog_load()
        # Load backfill states
        self.backfill_states = await self.load_data("backfill_states.json", default={})

    def _get_backfill_state(self, guild_id: int) -> dict:
        """Get saved backfill state for a guild."""
        return self.backfill_states.get(str(guild_id), {})

    async def _save_backfill_state(self, guild_id: int, state: dict) -> None:
        """Save backfill state for a guild."""
        self.backfill_states[str(guild_id)] = state
        await self.save_data_if_modified(self.backfill_states, "backfill_states.json")

    async def _clear_backfill_state(self, guild_id: int) -> None:
        """Clear saved backfill state for a guild."""
        self.backfill_states.pop(str(guild_id), None)
        await self.save_data_if_modified(self.backfill_states, "backfill_states.json")

    async def get_backfill_status(self, guild_id: int) -> dict:
        """Get current backfill status including saved state info."""
        state = self._get_backfill_state(guild_id)
        if not state:
            return {"has_saved_state": False}

        # Try to get message details
        oldest_message_id = state.get("oldest_message_id")
        message_date = None
        if oldest_message_id:
            validation_cog = self.bot.get_cog("Validation")
            if validation_cog:
                log_channel_id = validation_cog.get_setting("verification_log_channel_id", guild_id=guild_id)
                if log_channel_id:
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        log_channel = guild.get_channel(log_channel_id)
                        if log_channel:
                            try:
                                message = await log_channel.fetch_message(oldest_message_id)
                                message_date = message.created_at
                            except discord.NotFound:
                                pass

        return {
            "has_saved_state": True,
            "oldest_message_id": oldest_message_id,
            "message_date": message_date,
            "accounts_remaining": state.get("accounts_remaining", []),
            "updated_count": state.get("updated_count", 0),
            "message_count": state.get("message_count", 0),
            "last_save_time": state.get("last_save_time"),
        }

    async def _log_to_global_channel(self, embed: discord.Embed, guild_name: str = None, guild_id: int = None) -> None:
        """Log an update to the global log channel if configured."""
        global_log_channel_id = self.get_global_setting("global_log_channel_id")
        if not global_log_channel_id:
            return

        try:
            channel = self.bot.get_channel(global_log_channel_id)
            if not channel:
                return

            # Add guild context if provided
            if guild_name and guild_id:
                embed.set_footer(text=f"Server: {guild_name} (ID: {guild_id})")
            elif guild_name:
                embed.set_footer(text=f"Server: {guild_name}")

            await channel.send(embed=embed)
        except Exception as e:
            self.logger.error(f"Failed to log to global channel: {e}")

    async def preview_backfill(self, interaction: discord.Interaction, guild_id: int) -> None:
        """Preview what verification dates would be backfilled."""
        await interaction.response.defer(ephemeral=True)

        # Get verification log channel
        validation_cog = self.bot.get_cog("Validation")
        if not validation_cog:
            await interaction.followup.send("❌ Validation cog not loaded.", ephemeral=True)
            return

        log_channel_id = validation_cog.get_setting("verification_log_channel_id", guild_id=guild_id)
        if not log_channel_id:
            await interaction.followup.send("❌ No verification log channel configured.", ephemeral=True)
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            await interaction.followup.send("❌ Guild not found.", ephemeral=True)
            return

        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            await interaction.followup.send("❌ Verification log channel not found.", ephemeral=True)
            return

        # Get accounts needing update
        placeholder_date = datetime.datetime.fromtimestamp(PLACEHOLDER_TIMESTAMP, tz=datetime.timezone.utc)

        @sync_to_async
        def get_accounts_needing_update():
            return list(
                LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, verified=True, verified_at=placeholder_date).values_list(
                    "account_id", flat=True
                )
            )

        accounts_needing_update = await get_accounts_needing_update()

        if not accounts_needing_update:
            await interaction.followup.send("✅ No accounts need updating - all verification dates are already set!", ephemeral=True)
            return

        # Scan log channel
        embed = discord.Embed(
            title="🔍 Scanning Verification Log",
            description=f"Reading #{log_channel.name}...",
            color=discord.Color.blue(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        verification_dates = {}  # {discord_id: earliest_verification_timestamp}
        message_count = 0

        async for message in log_channel.history(limit=None, oldest_first=True):
            message_count += 1

            # Update every 100 messages
            if message_count % 100 == 0:
                embed.description = f"Reading #{log_channel.name}... ({message_count} messages scanned)"
                await interaction.edit_original_response(embed=embed)

            if not message.embeds:
                continue

            for embed_item in message.embeds:
                if not embed_item.title or "Verification Successful" not in embed_item.title:
                    continue

                # Extract Discord ID
                discord_id = None
                for field in embed_item.fields:
                    if field.name == "Discord ID":
                        discord_id = field.value.strip("`")
                        break

                if not discord_id:
                    continue

                timestamp = embed_item.timestamp or message.created_at

                if discord_id in verification_dates:
                    if timestamp < verification_dates[discord_id]:
                        verification_dates[discord_id] = timestamp
                else:
                    verification_dates[discord_id] = timestamp

        # Build results
        result_embed = discord.Embed(
            title="📊 Backfill Preview",
            description=f"Scanned {message_count} messages in #{log_channel.name}",
            color=discord.Color.green(),
        )

        # Count how many would be updated
        would_update = [discord_id for discord_id in verification_dates if discord_id in accounts_needing_update]

        result_embed.add_field(
            name="📋 Summary",
            value=f"**Accounts with unknown dates:** {len(accounts_needing_update)}\n"
            f"**Verifications found in log:** {len(verification_dates)}\n"
            f"**Would be updated:** {len(would_update)}",
            inline=False,
        )

        # Log to global channel
        await self._log_to_global_channel(result_embed.copy(), guild.name, guild.id)

        if would_update:
            # Show sample of updates (first 10)
            sample = []
            for i, discord_id in enumerate(would_update[:10]):
                timestamp = verification_dates[discord_id]
                unix_ts = int(timestamp.timestamp())
                sample.append(f"<@{discord_id}> → <t:{unix_ts}:f>")

            sample_text = "\n".join(sample)
            if len(would_update) > 10:
                sample_text += f"\n_...and {len(would_update) - 10} more_"

            result_embed.add_field(name="📝 Sample Updates", value=sample_text, inline=False)

            result_embed.set_footer(text="Use 'Apply Backfill' button to apply these changes")

        await interaction.edit_original_response(embed=result_embed)

    async def apply_backfill(self, interaction: discord.Interaction, guild_id: int, start_fresh: bool = False) -> None:
        """Apply verification date backfill (with optional resume from saved state)."""
        # Check if already running
        if guild_id in self.backfill_tasks and not self.backfill_tasks[guild_id].done():
            await interaction.response.send_message("❌ Backfill is already running. Use 'Cancel' button to stop it.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Clear state if starting fresh
        if start_fresh:
            await self._clear_backfill_state(guild_id)
        else:
            # Check for saved state and show resume info
            status = await self.get_backfill_status(guild_id)
            if status["has_saved_state"]:
                resume_embed = discord.Embed(
                    title="📍 Resuming Backfill",
                    description="Continuing from saved position...",
                    color=discord.Color.blue(),
                )
                if status["message_date"]:
                    resume_embed.add_field(name="Resume Point", value=f"Last scanned: <t:{int(status['message_date'].timestamp())}:F>", inline=False)
                resume_embed.add_field(
                    name="Progress So Far",
                    value=f"**Accounts updated:** {status['updated_count']}\n"
                    f"**Accounts remaining:** {len(status['accounts_remaining'])}\n"
                    f"**Messages scanned:** {status['message_count']}",
                    inline=False,
                )
                await interaction.followup.send(embed=resume_embed, ephemeral=True)

        # Get verification log channel
        validation_cog = self.bot.get_cog("Validation")
        if not validation_cog:
            await interaction.followup.send("❌ Validation cog not loaded.", ephemeral=True)
            return

        log_channel_id = validation_cog.get_setting("verification_log_channel_id", guild_id=guild_id)
        if not log_channel_id:
            await interaction.followup.send("❌ No verification log channel configured.", ephemeral=True)
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            await interaction.followup.send("❌ Guild not found.", ephemeral=True)
            return

        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            await interaction.followup.send("❌ Verification log channel not found.", ephemeral=True)
            return

        # Start backfill task
        self.backfill_cancelled[guild_id] = False
        task = asyncio.create_task(self._run_backfill(interaction, log_channel, guild_id))
        self.backfill_tasks[guild_id] = task

        # Log to global channel
        start_embed = discord.Embed(
            title="🔄 Backfill Started",
            description=f"Backfill operation started in #{log_channel.name}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        start_embed.add_field(name="Initiated By", value=f"{interaction.user.mention}", inline=True)
        await self._log_to_global_channel(start_embed, guild.name, guild.id)

    async def cancel_backfill(self, interaction: discord.Interaction, guild_id: int) -> None:
        """Cancel running backfill."""
        if guild_id not in self.backfill_tasks or self.backfill_tasks[guild_id].done():
            await interaction.response.send_message("❌ No backfill is currently running.", ephemeral=True)
            return

        self.backfill_cancelled[guild_id] = True
        await interaction.response.send_message("🛑 Cancelling backfill...", ephemeral=True)

    async def _run_backfill(self, interaction: discord.Interaction, log_channel: discord.TextChannel, guild_id: int) -> None:
        """Run the actual backfill process."""

        try:
            # Load saved state if exists
            saved_state = self._get_backfill_state(guild_id)
            resume_from_message_id = saved_state.get("oldest_message_id") if saved_state else None

            # Get accounts needing update
            placeholder_date = datetime.datetime.fromtimestamp(PLACEHOLDER_TIMESTAMP, tz=datetime.timezone.utc)

            @sync_to_async
            def get_accounts_needing_update():
                return list(
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, verified=True, verified_at=placeholder_date).values_list(
                        "account_id", flat=True
                    )
                )

            accounts_needing_update = await get_accounts_needing_update()

            # If resuming, use saved accounts_remaining; otherwise use fresh list
            if saved_state and saved_state.get("accounts_remaining"):
                total_accounts = saved_state.get("total_accounts", len(accounts_needing_update))
                accounts_still_needed = set(saved_state["accounts_remaining"])
                updated_count = saved_state.get("updated_count", 0)
                message_count = saved_state.get("message_count", 0)
                self.logger.info(f"Resuming backfill from message {resume_from_message_id}, {len(accounts_still_needed)} accounts remaining")
            else:
                total_accounts = len(accounts_needing_update)
                accounts_still_needed = set(accounts_needing_update)
                updated_count = 0
                message_count = 0
                resume_from_message_id = None  # Fresh start
                self.logger.info(f"Starting fresh backfill, {total_accounts} accounts to process")

            if not accounts_still_needed:
                embed = discord.Embed(
                    title="✅ Backfill Complete",
                    description="No accounts need updating!",
                    color=discord.Color.green(),
                )
                await interaction.edit_original_response(embed=embed)
                await self._clear_backfill_state(guild_id)
                return

            # Scan log channel (backwards from newest, or resume from saved position)
            embed = discord.Embed(
                title="🔄 Running Backfill",
                description=f"Scanning #{log_channel.name}...\nFound {total_accounts - len(accounts_still_needed)} of {total_accounts} accounts",
                color=discord.Color.blue(),
            )
            await interaction.edit_original_response(embed=embed)

            oldest_message_id = resume_from_message_id
            start_time = datetime.datetime.now(datetime.timezone.utc)

            # Build history iterator with optional resume point
            if resume_from_message_id:
                history_iter = log_channel.history(limit=None, before=discord.Object(id=resume_from_message_id))
            else:
                history_iter = log_channel.history(limit=None)

            async for message in history_iter:
                if self.backfill_cancelled.get(guild_id, False):
                    # Save state before cancelling
                    await self._save_backfill_state(
                        guild_id,
                        {
                            "oldest_message_id": oldest_message_id,
                            "accounts_remaining": list(accounts_still_needed),
                            "total_accounts": total_accounts,
                            "updated_count": updated_count,
                            "message_count": message_count,
                            "last_save_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        },
                    )

                    embed = discord.Embed(
                        title="🛑 Backfill Cancelled",
                        description=f"Cancelled after {message_count} messages\nFound {total_accounts - len(accounts_still_needed)} of {total_accounts} accounts\n\n_Progress saved - use Resume to continue_",
                        color=discord.Color.orange(),
                    )
                    await interaction.edit_original_response(embed=embed)
                    return

                message_count += 1
                oldest_message_id = message.id  # Track for resume capability

                # Update progress every 100 messages
                if message_count % 100 == 0:
                    elapsed = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()
                    found = total_accounts - len(accounts_still_needed)
                    embed.description = (
                        f"Scanning #{log_channel.name}...\n"
                        f"Found {found} of {total_accounts} accounts\n"
                        f"Scanned {message_count} messages ({elapsed:.0f}s)"
                    )
                    await interaction.edit_original_response(embed=embed)

                    # Save state for resume capability
                    await self._save_backfill_state(
                        guild_id,
                        {
                            "oldest_message_id": oldest_message_id,
                            "accounts_remaining": list(accounts_still_needed),
                            "total_accounts": total_accounts,
                            "updated_count": updated_count,
                            "message_count": message_count,
                            "last_save_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        },
                    )

                if not message.embeds:
                    continue

                for embed_item in message.embeds:
                    if not embed_item.title or "Verification Successful" not in embed_item.title:
                        continue

                    discord_id = None
                    for field in embed_item.fields:
                        if field.name == "Discord ID":
                            discord_id = field.value.strip("`")
                            break

                    if not discord_id:
                        continue

                    # Only process if this account still needs updating
                    if discord_id not in accounts_still_needed:
                        continue

                    # This is the newest verification for this account (scanning backwards)
                    timestamp = embed_item.timestamp or message.created_at

                    # Update database immediately
                    @sync_to_async
                    def update_account(discord_id: str, verified_at: datetime.datetime):
                        try:
                            account = LinkedAccount.objects.get(
                                platform=LinkedAccount.Platform.DISCORD, account_id=discord_id, verified_at=placeholder_date
                            )
                            account.verified_at = verified_at
                            account.save()
                            return True, None
                        except LinkedAccount.DoesNotExist:
                            return False, "Not found or already updated"
                        except Exception as e:
                            return False, str(e)

                    success, error = await update_account(discord_id, timestamp)
                    if success:
                        updated_count += 1
                        accounts_still_needed.remove(discord_id)

                        # Log to global channel
                        guild = self.bot.get_guild(guild_id)
                        if guild:
                            log_embed = discord.Embed(
                                title="✅ Account Updated",
                                description=f"<@{discord_id}> verified at <t:{int(timestamp.timestamp())}:F>",
                                color=discord.Color.green(),
                                timestamp=discord.utils.utcnow(),
                            )
                            await self._log_to_global_channel(log_embed, guild.name, guild.id)

                # Check if all accounts found - early exit
                if not accounts_still_needed:
                    self.logger.info(f"All accounts found after {message_count} messages, stopping scan")
                    break

            # Final results
            elapsed_time = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()
            not_found_count = len(accounts_still_needed)

            result_embed = discord.Embed(
                title="✅ Backfill Complete",
                description=f"Successfully updated {updated_count} of {total_accounts} account(s)",
                color=discord.Color.green() if not_found_count == 0 else discord.Color.orange(),
                timestamp=discord.utils.utcnow(),
            )

            result_embed.add_field(
                name="📊 Results",
                value=f"**Messages scanned:** {message_count}\n"
                f"**Accounts updated:** {updated_count}\n"
                f"**Not found:** {not_found_count}\n"
                f"**Time elapsed:** {elapsed_time:.0f}s",
                inline=False,
            )

            if accounts_still_needed and not_found_count <= 10:
                not_found_text = "\n".join([f"<@{acc}>" for acc in list(accounts_still_needed)[:10]])
                result_embed.add_field(name="⚠️ Not Found in Logs", value=not_found_text, inline=False)
            elif not_found_count > 10:
                result_embed.add_field(name="⚠️ Not Found in Logs", value=f"{not_found_count} accounts not found in channel history", inline=False)

            await interaction.edit_original_response(embed=result_embed)

            # Clear saved state on successful completion
            await self._clear_backfill_state(guild_id)

            # Log to global channel
            guild = self.bot.get_guild(guild_id)
            if guild:
                await self._log_to_global_channel(result_embed.copy(), guild.name, guild.id)

        except Exception as e:
            self.logger.error(f"Error during backfill: {e}", exc_info=True)
            error_embed = discord.Embed(
                title="❌ Backfill Failed",
                description=f"An error occurred: {str(e)}",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
            await interaction.edit_original_response(embed=error_embed)

            # Log error to global channel
            guild = self.bot.get_guild(guild_id)
            if guild:
                await self._log_to_global_channel(error_embed.copy(), guild.name, guild.id)
        finally:
            # Cleanup
            if guild_id in self.backfill_tasks:
                del self.backfill_tasks[guild_id]
            if guild_id in self.backfill_cancelled:
                del self.backfill_cancelled[guild_id]

    async def cog_unload(self) -> None:
        """Cancel any running tasks on unload."""
        for guild_id in list(self.backfill_tasks.keys()):
            self.backfill_cancelled[guild_id] = True
            if not self.backfill_tasks[guild_id].done():
                self.backfill_tasks[guild_id].cancel()

        await super().cog_unload()
