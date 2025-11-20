"""
Tournament Roles Cog

A modular Discord bot cog for automatically assigning tournament-based roles
based on competitive performance across different leagues.

This cog follows the unified cog design architecture with:
- Modular UI components separated by function/role
- Integration with global settings system
- Slash command-based interface
- Robust background processing and task management
"""

import asyncio
import datetime

import discord

from thetower.bot.basecog import BaseCog

from .ui import (
    TournamentRolesCore,
    TournamentRolesSettingsView,
)


class TourneyRoles(BaseCog, name="Tourney Roles"):
    """
    Tournament role management system.

    Automatically assigns Discord roles based on tournament participation
    and performance across different leagues.
    """

    # Settings view class for the cog manager
    settings_view_class = TournamentRolesSettingsView

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing TourneyRoles")

        # Initialize core instance variables with descriptions
        self.member_roles = {}  # {guild_id: {user_id: roles}}
        self.processed_users = 0
        self.roles_assigned = 0
        self.roles_removed = 0
        self.users_with_no_player_data = 0

        # Status tracking variables
        self.last_full_update = None
        self.currently_updating = False
        self.update_task = None
        self.startup_message_shown = False

        # Initialize log buffer
        self.log_buffer = []
        self.log_buffer_max_size = 8000  # Characters before forcing flush

        # Core components
        self.core = TournamentRolesCore(self)

        # UI components (no longer separate cogs)
        # self.user_ui = UserTournamentRoles(self)
        # self.admin_ui = AdminTournamentRoles(self)

        # Default settings
        self.default_settings = {
            # Core Settings
            "league_hierarchy": ["Legend", "Champion", "Platinum", "Gold", "Silver", "Copper"],
            "roles_config": {},
            "verified_role_id": None,
            # Update Settings
            "update_interval": 6 * 60 * 60,  # 6 hours in seconds
            "role_update_cooldown": 24 * 60 * 60,  # 24 hours in seconds
            "update_on_startup": True,
            # Processing Settings
            "process_batch_size": 50,
            "process_delay": 5,
            "error_retry_delay": 300,
            # Mode Settings
            "dry_run": False,
            "dry_run_limit": 100,
            "pause": False,
            "debug_logging": False,
            # Logging Settings
            "log_channel_id": None,
            "log_batch_size": 10,
            "immediate_logging": True,
            "roles_cache_filename": "tourney_roles.json",
        }

    async def save_data(self) -> bool:
        """Save tournament role data using BaseCog's utility."""
        try:
            # Prepare serializable data
            save_data = {
                "roles_config": self.default_settings.get("roles_config", {}),
                "last_full_update": self.last_full_update.isoformat() if self.last_full_update else None,
                "processed_users": self.processed_users,
                "roles_assigned": self.roles_assigned,
                "roles_removed": self.roles_removed,
                "users_with_no_player_data": self.users_with_no_player_data,
            }

            # Use BaseCog's utility to save data
            success = await self.save_data_if_modified(save_data, self.cache_file)
            if success:
                self.logger.info("Saved tournament role data")
            return success

        except Exception as e:
            self.logger.error(f"Error saving tournament role data: {e}", exc_info=True)
            self._has_errors = True
            return False

    async def load_data(self) -> bool:
        """Load tournament role data using BaseCog's utility."""
        try:
            save_data = await super().load_data(self.cache_file)

            if save_data:
                # Load roles configuration
                roles_config = save_data.get("roles_config", {})
                if roles_config:
                    self.default_settings["roles_config"] = roles_config

                # Load tracking data
                self.last_full_update = datetime.datetime.fromisoformat(save_data["last_full_update"]) if save_data.get("last_full_update") else None
                self.processed_users = save_data.get("processed_users", 0)
                self.roles_assigned = save_data.get("roles_assigned", 0)
                self.roles_removed = save_data.get("roles_removed", 0)
                self.users_with_no_player_data = save_data.get("users_with_no_player_data", 0)

                self.logger.info("Loaded tournament role data")
                return True

            self.logger.info("No saved tournament role data found")
            return False

        except Exception as e:
            self.logger.error(f"Error loading tournament role data: {e}", exc_info=True)
            self._has_errors = True
            return False

    @property
    def update_interval(self):
        """Get the update interval in seconds."""
        return self.default_settings.get("update_interval", 6 * 60 * 60)

    @property
    def dry_run_limit(self):
        """Get the dry run limit."""
        return self.default_settings.get("dry_run_limit", 100)

    @property
    def process_batch_size(self):
        """Get the process batch size."""
        return self.default_settings.get("process_batch_size", 50)

    @property
    def process_delay(self):
        """Get the process delay between batches."""
        return self.default_settings.get("process_delay", 5)

    async def _load_settings(self) -> None:
        """Load and initialize default settings."""
        # Ensure tourney_roles config section exists
        tourney_config = self.config.config.setdefault("tourney_roles", {})

        # Set defaults for any missing settings
        for key, default_value in self.default_settings.items():
            if key not in tourney_config:
                tourney_config[key] = default_value
                self.logger.debug(f"Set default setting {key} = {default_value}")

        # Save the config if any defaults were set
        if tourney_config:
            self.config.save_config()
            self.logger.debug("Saved updated config with default settings")

    async def get_discord_to_player_mapping(self):
        """Get mapping of Discord IDs to player information from KnownPlayers"""
        known_players_cog = await self.get_known_players_cog()
        if not known_players_cog:
            self.logger.error("Failed to get KnownPlayers cog")
            return {}

        try:
            # Wait for KnownPlayers to be ready
            if not known_players_cog.is_ready:
                self.logger.info("Waiting for KnownPlayers to be ready...")
                await known_players_cog.wait_until_ready()

            # Get the mapping
            mapping = await known_players_cog.get_discord_to_player_mapping()

            # Add detailed debug logging
            if mapping:
                self.logger.debug(f"Retrieved {len(mapping)} entries from KnownPlayers")
                sample_entry = next(iter(mapping.items()))
                self.logger.debug(f"Sample mapping entry: {sample_entry}")
            else:
                self.logger.warning("KnownPlayers returned empty mapping")
                # Check if KnownPlayers has any data at all
                if hasattr(known_players_cog, "player_details_cache"):
                    cache_size = len(known_players_cog.player_details_cache)
                    self.logger.debug(f"KnownPlayers cache size: {cache_size}")
                    if cache_size > 0:
                        self.logger.debug("KnownPlayers has data but mapping is empty")
                    else:
                        self.logger.warning("KnownPlayers cache is empty")

            return mapping or {}  # Ensure we return at least an empty dict

        except Exception as e:
            self.logger.error(f"Error getting player mapping: {e}", exc_info=True)
            return {}

    async def schedule_periodic_updates(self):
        """Schedule periodic role updates"""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                # Check if it's time to run an update
                should_update = False
                if not self.last_full_update:
                    # Check if update_on_startup is enabled
                    if self.default_settings.get("update_on_startup", True):
                        should_update = True
                        self.logger.info("No previous update found, running initial role update")
                    elif not self.startup_message_shown:
                        # Only log this message once
                        self.logger.info("No previous update found, but update_on_startup is disabled. Waiting for manual update.")
                        self.startup_message_shown = True
                else:
                    time_since_update = (datetime.datetime.now(datetime.timezone.utc) - self.last_full_update).total_seconds()
                    if time_since_update >= self.update_interval:
                        should_update = True
                        self.logger.info(f"Time since last update ({time_since_update:.1f}s) exceeds interval, running role update")

                if should_update and not self.currently_updating:
                    # Check if the cog is enabled for any guilds
                    enabled_guilds = []
                    for guild in self.bot.guilds:
                        try:
                            if self.bot.cog_manager.can_guild_use_cog(self.cog_name, guild.id, False):  # Assume not bot owner for guild check
                                enabled_guilds.append(guild)
                        except Exception as e:
                            self.logger.debug(f"Error checking cog enablement for guild {guild.id}: {e}")

                    if not enabled_guilds:
                        self.logger.debug("TourneyRoles cog is not enabled for any guilds, skipping update")
                        # Sleep until next check
                        await asyncio.sleep(60)  # Check every minute if update needed
                        continue

                    # For automatic updates, create a message in the log channel
                    log_channel_id = self.default_settings.get("log_channel_id")
                    if log_channel_id:
                        try:
                            channel = self.bot.get_channel(int(log_channel_id))
                            if channel:
                                # Get dry run status
                                dry_run = self.default_settings.get("dry_run")
                                initial_message = (
                                    "🔍 Starting automatic role update in DRY RUN mode..." if dry_run else "🔄 Starting automatic role update..."
                                )
                                message = await channel.send(f"{initial_message} This may take a while.")

                                # Run the update with progress tracking
                                await self.start_update_with_progress(message, manual_update=False)
                            else:
                                # No valid channel, run update without progress message
                                self.logger.warning("Log channel not found for automatic update progress message")
                                await self.update_all_roles()
                        except Exception as e:
                            self.logger.error(f"Error creating progress message for automatic update: {e}")
                            await self.update_all_roles()  # Still run the update
                    else:
                        # No log channel configured, run without progress message
                        await self.update_all_roles()

                # Sleep until next check
                await asyncio.sleep(60)  # Check every minute if update needed
            except Exception as e:
                self.logger.error(f"Error in periodic role update: {e}")
                await asyncio.sleep(self.default_settings.get("error_retry_delay", 300))  # Sleep on error

    async def update_all_roles(self):
        """Update roles for all users based on tournament performance"""
        if self.currently_updating:
            self.logger.warning("Role update already in progress, skipping")
            return

        # Check if updates are paused
        if self.default_settings.get("pause"):
            self.logger.info("Role updates are currently paused. Skipping update.")
            return

        async with self.task_tracker.task_context("Role Update", "Updating tournament roles"):
            start_time = datetime.datetime.now(datetime.timezone.utc)
            try:
                self.currently_updating = True
                self.logger.info("Starting full role update")

                # Get role configurations early and check once
                roles_config = self.default_settings.get("roles_config", {})
                if not roles_config:
                    self.logger.warning("No roles configured for tournament role assignment. Add roles with the 'roles add_role' command.")
                    self.currently_updating = False
                    return

                # Log if in dry run mode
                dry_run = self.default_settings.get("dry_run")
                if dry_run:
                    dry_run_limit = self.dry_run_limit
                    limit_message = f"first {dry_run_limit} users" if dry_run_limit > 0 else "all users"
                    self.logger.info("Running in DRY RUN mode - no actual role changes will be made")
                    self.logger.info(f"In dry run mode, processing {limit_message} for testing")

                # Reset stats
                self.processed_users = 0
                self.roles_assigned = 0
                self.roles_removed = 0
                self.users_with_no_player_data = 0
                dry_run_user_count = 0  # Counter for dry run mode

                # Get player data with retries
                max_retries = 3
                retry_delay = 5  # seconds
                discord_to_player = None

                for attempt in range(max_retries):
                    discord_to_player = await self.get_discord_to_player_mapping()
                    if discord_to_player:
                        break
                    if attempt < max_retries - 1:
                        self.logger.warning(f"Retry {attempt + 1}/{max_retries} getting player mapping...")
                        await asyncio.sleep(retry_delay)

                if not discord_to_player:
                    self.logger.error("Failed to get player mapping after retries")
                    return

                # Log mapping info
                self.logger.debug(f"Raw player mapping data keys: {list(discord_to_player.keys())}")
                self.logger.info(f"Found {len(discord_to_player)} Discord users with player data")

                # Extract Discord IDs from the mapping
                discord_ids = list(discord_to_player.keys())
                self.logger.info(f"Processing {len(discord_ids)} Discord users")

                # Get enabled guilds for this cog
                enabled_guilds = []
                for guild in self.bot.guilds:
                    try:
                        if self.bot.cog_manager.can_guild_use_cog(self.cog_name, guild.id, False):
                            enabled_guilds.append(guild)
                    except Exception as e:
                        self.logger.debug(f"Error checking cog enablement for guild {guild.id}: {e}")

                if not enabled_guilds:
                    self.logger.warning("No guilds have TourneyRoles enabled, cannot proceed with role updates")
                    self.currently_updating = False
                    return

                # For now, use the first enabled guild (this cog seems designed for single guild operation)
                # TODO: Modify to support multiple guilds
                guild = enabled_guilds[0]
                self.logger.info(f"Using guild: {guild.name} (ID: {guild.id})")

                # Get TourneyStats cog for tournament data
                tourney_stats_cog = await self.get_tourney_stats_cog()
                if not tourney_stats_cog:
                    self.logger.error("TourneyStats cog not available, cannot proceed with role updates")
                    return

                # Initialize log message collection
                log_messages = []

                # Process users in batches to avoid rate limits
                for i in range(0, len(discord_ids), self.process_batch_size):
                    batch = discord_ids[i : i + self.process_batch_size]

                    for discord_id in batch:
                        try:
                            player_data = discord_to_player[discord_id]
                            if not player_data:
                                self.logger.debug(f"No player data for Discord ID {discord_id}")
                                continue

                            # Validate required fields
                            if "all_ids" not in player_data:
                                self.logger.debug(f"Missing all_ids for Discord ID {discord_id}")
                                self.users_with_no_player_data += 1
                                continue

                            member = guild.get_member(int(discord_id))
                            if not member:
                                self.logger.debug(f"Could not find member with ID {discord_id} in guild")
                                continue

                            # Get player IDs for this user
                            player_ids = player_data["all_ids"]
                            if not player_ids:
                                self.logger.debug(f"Empty player_ids list for Discord ID {discord_id}")
                                self.users_with_no_player_data += 1
                                continue

                            self.logger.debug(f"Processing user {discord_id} with player IDs: {player_ids}")

                            # Get player tournament participation data
                            player_tournaments = await self.core.get_player_tournament_stats(tourney_stats_cog, player_ids)

                            # Update member's roles
                            # Get the log message but DON'T add it to buffer here
                            # It will be added to log_messages and sent in batches
                            roles_added, roles_removed, log_message = await self.update_member_roles(member, player_tournaments)

                            # Handle logging
                            if log_message:
                                log_messages.append(log_message)

                                # If we've reached batch size, send logs
                                log_batch_size = self.default_settings.get("log_batch_size", 10)
                                if len(log_messages) >= log_batch_size:
                                    await self.send_role_logs_batch(log_messages)
                                    log_messages = []

                            self.processed_users += 1

                            # Call progress callback if set
                            if hasattr(self, "update_callback") and self.update_callback:
                                await self.update_callback(self.processed_users, len(discord_ids))

                            # Update progress tracker if it exists
                            if hasattr(self, "update_progress"):
                                self.update_progress["processed"] += 1

                            # In dry run mode, check if we've hit the limit
                            if dry_run:
                                dry_run_user_count += 1
                                dry_run_limit = self.dry_run_limit
                                if dry_run_limit > 0 and dry_run_user_count >= dry_run_limit:
                                    self.logger.info(f"Dry run mode: Reached limit of {dry_run_limit} users, stopping processing")
                                    break

                        except Exception as e:
                            self.logger.error(f"Error processing user {discord_id}: {e}")
                            # Log errors to Discord channel too
                            await self.add_log_message(f"⚠️ Error processing user {discord_id}: {e}")

                    # Break out of batch loop if we've hit our dry run limit
                    dry_run_limit = self.dry_run_limit
                    if dry_run and dry_run_limit > 0 and dry_run_user_count >= dry_run_limit:
                        break

                    # Yield to event loop frequently to avoid blocking heartbeat
                    if self.processed_users % 5 == 0:  # Every 5 users
                        await asyncio.sleep(0)  # Small sleep to allow heartbeat processing

                    # Sleep between batches to avoid rate limits
                    if i + self.process_batch_size < len(discord_ids):
                        await asyncio.sleep(self.process_delay)

                # After processing, send any remaining logs
                if log_messages:
                    await self.send_role_logs_batch(log_messages)
                    log_messages = []

                # After processing, flush any remaining logs that might be in the buffer
                # (though there shouldn't be any if we're not adding directly to buffer)
                await self.flush_log_buffer()

                # Update timestamp - at the end of processing
                self.last_full_update = datetime.datetime.now(datetime.timezone.utc)
                duration = (self.last_full_update - start_time).total_seconds()
                if dry_run:
                    self.logger.info(f"Dry run role update completed in {duration:.1f}s (limited to {dry_run_user_count} users)")
                    await self.add_log_message(f"✅ Dry run role update completed in {duration:.1f}s (limited to {dry_run_user_count} users)")
                else:
                    self.logger.info(f"Role update completed in {duration:.1f}s")
                    await self.add_log_message(f"✅ Role update completed in {duration:.1f}s")

                self.logger.info(
                    f"Stats: Processed {self.processed_users} users, {self.roles_assigned} roles assigned, {self.roles_removed} roles removed"
                )
                await self.add_log_message(
                    f"📊 Stats: Processed {self.processed_users} users, {self.roles_assigned} roles assigned, {self.roles_removed} roles removed"
                )

                # Send any final log messages
                await self.flush_log_buffer()

                # Mark data as modified and save
                self.mark_data_modified()
                await self.save_data()

            except Exception as e:
                # Set the timestamp even if there was an error
                error_time = datetime.datetime.now(datetime.timezone.utc)
                error_duration = (error_time - start_time).total_seconds()
                self.logger.error(f"Error during role update after {error_duration:.1f}s: {e}")
                self.last_full_update = error_time
                if hasattr(self, "update_progress"):
                    self.update_progress["error"] = str(e)
                await self.add_log_message(f"❌ Error during role update: {e}")
                await self.flush_log_buffer()  # Make sure to send any buffered logs on error
                raise

            finally:
                # Make absolutely sure we unset the updating flag
                self.currently_updating = False
                if hasattr(self, "update_progress"):
                    self.update_progress["completed"] = True

    async def update_member_roles(self, member, player_tournaments):
        """
        Update a member's roles based on tournament performance

        Args:
            member: Discord member to update
            player_tournaments: Tournament data for this player

        Returns:
            tuple: (roles_added, roles_removed, log_message or None)
        """
        try:
            # Dispatch start event
            self.bot.dispatch("bot_role_update_start", member.id)

            # Check if verified role is required
            verified_role_id = self.default_settings.get("verified_role_id")
            if verified_role_id:
                verified_role = member.guild.get_role(int(verified_role_id))
                if not verified_role:
                    self.logger.warning(f"Verified role with ID {verified_role_id} not found in guild")
                elif verified_role not in member.roles:
                    # Remove all tournament roles if user isn't verified
                    roles_config = self.default_settings.get("roles_config", {})
                    all_managed_role_ids = [config.id for config in roles_config.values()]

                    dry_run = self.default_settings.get("dry_run")
                    roles_removed = 0
                    role_changes = []

                    for role in member.roles:
                        if str(role.id) in all_managed_role_ids:
                            try:
                                if not dry_run:
                                    await member.remove_roles(role, reason="User not verified for tournament roles")
                                roles_removed += 1
                                self.roles_removed += 1
                                role_changes.append(f"-{role.name}")
                                log_msg = (
                                    f"{'Would remove' if dry_run else 'Removed'} {role.name} role from {member.name} ({member.id}) - not verified"
                                )
                                self.logger.info(log_msg)
                            except Exception as e:
                                self.logger.error(f"Error removing role {role.name} from {member.name}: {e}")

                    # Return early if roles were removed
                    if role_changes:
                        log_message = f"{member.name}: {', '.join(role_changes)} (not verified)"
                        return 0, roles_removed, log_message
                    return 0, 0, None

            # Continue with normal role assignment
            # Determine the best role for this player
            best_role_id = self.core.determine_best_role(
                player_tournaments,
                self.core.get_roles_config(member.guild.id),
                self.core.get_league_hierarchy(member.guild.id),
                self.default_settings.get("debug_logging", False),
            )

            # Get all managed role IDs for comparison
            roles_config = self.default_settings.get("roles_config", {})
            all_managed_role_ids = [config.id for config in roles_config.values()]

            dry_run = self.default_settings.get("dry_run")

            # Track changes
            roles_added = 0
            roles_removed = 0
            role_changes = []  # List of role changes for logging

            # If player qualifies for a role
            if best_role_id:
                best_role = member.guild.get_role(int(best_role_id))
                if not best_role:
                    self.logger.warning(f"Role with ID {best_role_id} not found in guild")
                    return roles_added, roles_removed, None

                # Add the role if they don't have it
                if best_role not in member.roles:
                    try:
                        if not dry_run:
                            await member.add_roles(best_role, reason="Tournament participation role update")
                        roles_added += 1
                        self.roles_assigned += 1
                        role_changes.append(f"+{best_role.name}")
                        log_msg = f"{'Would add' if dry_run else 'Added'} {best_role.name} role to {member.name} ({member.id})"
                        self.logger.info(log_msg)
                    except Exception as e:
                        self.logger.error(f"Error adding role {best_role.name} to {member.name}: {e}")

            # Remove any other tournament roles they shouldn't have
            for role in member.roles:
                if str(role.id) in all_managed_role_ids and (not best_role_id or str(role.id) != best_role_id):
                    try:
                        if not dry_run:
                            await member.remove_roles(role, reason="Tournament participation role update")
                        roles_removed += 1
                        self.roles_removed += 1
                        role_changes.append(f"-{role.name}")
                        log_msg = f"{'Would remove' if dry_run else 'Removed'} {role.name} role from {member.name} ({member.id})"
                        self.logger.info(log_msg)
                    except Exception as e:
                        self.logger.error(f"Error removing role {role.name} from {member.name}: {e}")

            # Generate log message if there were changes
            log_message = None
            if role_changes:
                log_message = f"{member.name}: {', '.join(role_changes)}"

            return roles_added, roles_removed, log_message

        finally:
            self.bot.dispatch("bot_role_update_end", member.id)

    async def start_update_with_progress(self, message, manual_update=False):
        """Start a role update with progress tracking

        Args:
            message: The Discord message to update with progress
            manual_update: Whether this is a manual update (True) or automatic (False)
        """
        # Store start time with timezone awareness
        start_time = datetime.datetime.now(datetime.timezone.utc)

        # Get total number of users to process
        discord_mapping = await self.get_discord_to_player_mapping()
        total_users = len(discord_mapping)

        # Get dry run status
        dry_run = self.default_settings.get("dry_run")

        # Create shared progress data
        progress_data = {
            "processed": 0,
            "total": total_users,
            "start_time": start_time,
            "message": message,
            "dry_run": dry_run,
            "last_percentage": -1,
            "completed": False,
            "error": None,
            "manual_update": manual_update,
        }

        # Store progress data where update task can access it
        self.update_progress = progress_data

        # Create background task to handle updates
        self.update_task = asyncio.create_task(self.update_all_roles())

        # Create separate task to update the progress message
        self.progress_task = asyncio.create_task(self.update_progress_message())

    async def update_progress_message(self):
        """Background task that updates the progress message"""
        if not hasattr(self, "update_progress"):
            return

        try:
            # Keep updating until the process completes
            while not self.update_progress["completed"]:
                # Update message every 3 seconds
                await self.update_progress_display()
                await asyncio.sleep(3)

            # One final update after completion
            await self.update_progress_display(final=True)
        except Exception as e:
            self.logger.error(f"Error in progress update: {e}")
        finally:
            # Clear reference
            if hasattr(self, "update_progress"):
                del self.update_progress

    async def update_progress_display(self, final=False):
        """Update the progress message with current status"""
        data = self.update_progress
        if not data:
            return

        message = data["message"]
        processed = data["processed"]
        total = data["total"]
        start_time = data["start_time"]
        dry_run = data["dry_run"]
        error = data["error"]
        manual_update = data.get("manual_update", True)  # Default to True for backwards compatibility

        # Calculate percentage
        current_percentage = int((processed / total) * 100) if total > 0 else 0

        # Only update UI on percentage changes or final update
        if final or current_percentage % 1 == 0 and current_percentage != data["last_percentage"]:
            data["last_percentage"] = current_percentage

            # Calculate timing info
            elapsed = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()

            if final:
                if error:
                    await message.edit(content=f"❌ Error during role update: {error}")
                    return

                # Create completion embed
                duration = elapsed
                duration_str = f"{duration:.1f}"
                update_type = "Manual" if manual_update else "Automatic"
                embed = discord.Embed(
                    title=f"{update_type} Tournament Roles Updated" + (" (DRY RUN)" if dry_run else ""),
                    description=f"Successfully updated roles in {duration_str} seconds",
                    color=discord.Color.green(),
                )

                # Add stats
                embed.add_field(
                    name="Statistics",
                    value=(
                        f"**Users Processed:** {self.processed_users}\n"
                        f"**Roles Assigned:** {self.roles_assigned}\n"
                        f"**Roles Removed:** {self.roles_removed}\n"
                        f"**No Player Data:** {self.users_with_no_player_data}"
                    ),
                    inline=False,
                )

                # Add timestamp
                embed.set_footer(text=f"Completed at {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

                await message.edit(content=None, embed=embed)
            else:
                # Show progress bar during update
                if processed > 0:
                    avg_time_per_user = elapsed / processed
                    remaining_users = total - processed
                    eta_seconds = avg_time_per_user * remaining_users

                    # Format ETA
                    if eta_seconds < 60:
                        eta = f"{eta_seconds:.0f} seconds"
                    elif eta_seconds < 3600:
                        eta = f"{eta_seconds / 60:.1f} minutes"
                    else:
                        eta = f"{eta_seconds / 3600:.1f} hours"

                    progress_bar = "█" * (current_percentage // 5) + "░" * ((100 - current_percentage) // 5)
                    update_type = "Manual" if manual_update else "Automatic"
                    status = (
                        f"{update_type} {'🔍 DRY RUN: ' if dry_run else ''}Processing roles: **{processed}/{total}** users "
                        f"(**{current_percentage}%**)\n"
                        f"`{progress_bar}` \n"
                        f"⏱️ Estimated time remaining: **{eta}**"
                    )
                    await message.edit(content=status)

    async def add_log_message(self, message):
        """
        Add a message to the log buffer and potentially send it.

        Args:
            message: The log message to add
        """
        self.log_buffer.append(message)

        # Check if we should send immediately
        if self.default_settings.get("immediate_logging", True):
            # Check if we've hit batch size or buffer size limit
            batch_size = self.default_settings.get("log_batch_size", 10)

            # If we've hit batch size, send it
            if len(self.log_buffer) >= batch_size:
                should_send = True
            else:
                # Check buffer size in characters
                buffer_size = sum(len(msg) + 1 for msg in self.log_buffer)  # +1 for newline

                # If buffer is getting large, send it
                if buffer_size >= self.log_buffer_max_size:
                    should_send = True
                else:
                    should_send = False

            # Send and clear buffer if needed
            if should_send:
                await self.flush_log_buffer()

    async def flush_log_buffer(self):
        """Send all accumulated log messages in the buffer"""
        if self.log_buffer:
            await self.send_role_logs_batch(self.log_buffer)
            self.log_buffer = []  # Clear the buffer after sending

    async def send_role_logs_batch(self, log_messages):
        """Send a batch of role update logs to the configured channel

        Args:
            log_messages: List of log messages to send
        """
        if not log_messages:
            return

        log_channel_id = self.default_settings.get("log_channel_id")
        if not log_channel_id:
            return  # No logging channel configured

        channel = self.bot.get_channel(int(log_channel_id))
        if not channel:
            self.logger.warning(f"Could not find log channel with ID {log_channel_id}")
            return

        try:
            # Join messages with newlines, chunk if needed
            MAX_MESSAGE_LENGTH = 1950  # Discord limit is 2000, leave a small buffer for safety
            current_chunk = ""
            for msg in log_messages:
                # If adding this message would exceed limit, send current chunk and start new one
                if len(current_chunk) + len(msg) + 1 > MAX_MESSAGE_LENGTH:
                    if current_chunk:
                        await channel.send(current_chunk)
                    current_chunk = msg
                else:
                    if current_chunk:
                        current_chunk += "\n" + msg
                    else:
                        current_chunk = msg

            # Send any remaining messages
            if current_chunk:
                await channel.send(current_chunk)
        except Exception as e:
            self.logger.error(f"Error sending role log batch: {e}")

    async def cog_initialize(self) -> None:
        """Initialize the TourneyRoles cog."""
        self.logger.info("Initializing TourneyRoles cog")
        try:
            self.logger.info("Starting TourneyRoles initialization")

            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                await super().cog_initialize()

                # Set cache file path
                self.cache_file = self.data_directory / self.default_settings["roles_cache_filename"]

                # 1. Verify settings
                self.logger.debug("Loading settings")
                tracker.update_status("Verifying settings")
                await self._load_settings()

                # 2. Load saved data
                self.logger.debug("Loading saved data")
                tracker.update_status("Loading saved data")
                if await self.load_data():
                    self.logger.info("Loaded saved tournament role data")
                else:
                    self.logger.info("No saved tournament role data found, using defaults")

                # 3. Start the update task
                self.logger.debug("Starting update task")
                tracker.update_status("Starting update task")
                self.update_task = self.bot.loop.create_task(self.schedule_periodic_updates())

                # 4. Mark as ready and complete initialization
                self.set_ready(True)
                self.logger.info("TourneyRoles initialization complete")

        except Exception as e:
            self.logger.error(f"Error during TourneyRoles initialization: {e}", exc_info=True)
            self._has_errors = True
            raise

    async def cog_unload(self):
        """Clean up when cog is unloaded"""
        if self.update_task:
            self.update_task.cancel()
        await super().cog_unload()
        self.logger.info("Tournament roles cog unloaded")

    async def refresh_user_roles_for_user(self, user_id: int, guild_id: int) -> str:
        """Public method for other cogs to refresh tournament roles for a specific user.

        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID

        Returns:
            str: Status message describing the result
        """
        try:
            # Get the guild and member
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return "❌ Guild not found"

            member = guild.get_member(user_id)
            if not member:
                return "❌ User not found in server"

            # Get required cogs
            known_players_cog = await self.get_known_players_cog()
            if not known_players_cog:
                return "❌ Known Players system unavailable"

            tourney_stats_cog = await self.get_tourney_stats_cog()
            if not tourney_stats_cog:
                return "❌ Tournament Stats system unavailable"

            # Get user's player data
            discord_mapping = await self.get_discord_to_player_mapping()
            player_data = discord_mapping.get(str(user_id))
            if not player_data:
                return "❌ No player data found. Use `/player register` to link your account."

            # Get tournament participation data
            player_stats = await self.core.get_player_tournament_stats(tourney_stats_cog, player_data.get("all_ids", []))

            # Get roles config and settings
            roles_config = self.core.get_roles_config(guild_id)
            verified_role_id = self.core.get_verified_role_id(guild_id)
            dry_run = self.core.is_dry_run_enabled(guild_id)

            # Update member's roles
            result = await self.core.update_member_roles(member, player_stats, roles_config, verified_role_id, dry_run)

            # Create response message
            if dry_run:
                if result.roles_added > 0 or result.roles_removed > 0:
                    changes = []
                    if result.roles_added > 0:
                        changes.append(f"would add {result.roles_added} role(s)")
                    if result.roles_removed > 0:
                        changes.append(f"would remove {result.roles_removed} role(s)")
                    return f"🔍 DRY RUN: {', '.join(changes)}"
                else:
                    return "🔍 DRY RUN: No role changes needed"
            else:
                if result.roles_added > 0 or result.roles_removed > 0:
                    changes = []
                    if result.roles_added > 0:
                        changes.append(f"added {result.roles_added} role(s)")
                    if result.roles_removed > 0:
                        changes.append(f"removed {result.roles_removed} role(s)")
                    return f"✅ {', '.join(changes)}"
                else:
                    return "✅ No role changes needed"

        except Exception as e:
            self.logger.error(f"Error refreshing roles for user {user_id}: {e}")
            return f"❌ Error updating roles: {str(e)}"


async def setup(bot) -> None:
    await bot.add_cog(TourneyRoles(bot))
