import asyncio
import discord
from discord.ext import commands
import datetime
from pathlib import Path

from thetower.bot.basecog import BaseCog


class TourneyRoles(BaseCog, name="Tournament Roles"):
    """
    Tournament role management system.

    Automatically assigns Discord roles based on tournament participation
    and performance across different leagues.
    """

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

        # Define settings with descriptions
        settings_config = {
            # Core Settings
            "league_hierarchy": (
                ["Legend", "Champion", "Platinum", "Gold", "Silver", "Copper"],
                "Hierarchy of leagues from highest to lowest"
            ),
            "roles_config": ({}, "Configuration of tournament roles"),
            "verified_role_id": (None, "Role ID required for tournament role eligibility"),

            # Update Settings
            "update_interval": (
                6 * 60 * 60,  # 6 hours in seconds
                "How often to run automatic role updates"
            ),
            "role_update_cooldown": (
                24 * 60 * 60,  # 24 hours in seconds
                "Cooldown between manual role updates"
            ),
            "update_on_startup": (True, "Whether to update roles when bot starts"),

            # Processing Settings
            "process_batch_size": (50, "Number of users to process in each batch"),
            "process_delay": (5, "Seconds to wait between processing batches"),
            "error_retry_delay": (300, "Seconds to wait after error before retrying"),

            # Mode Settings
            "dry_run": (False, "Test mode - log changes without applying them"),
            "dry_run_limit": (100, "Maximum users to process in dry run mode"),
            "pause": (False, "Pause all role updates"),
            "debug_logging": (False, "Enable detailed debug logging"),

            # Logging Settings
            "log_channel_id": (None, "Channel ID for role update logs"),
            "log_batch_size": (10, "Number of log messages to batch before sending"),
            "immediate_logging": (True, "Send logs during updates vs only at end"),
            "roles_cache_filename": ("tourney_roles.json", "Filename for cached role data")
        }

        # Initialize settings
        for name, (value, description) in settings_config.items():
            if not self.has_setting(name):
                self.set_setting(name, value, description=description)

        # Initialize settings into instance variables
        self._load_settings()

    def _load_settings(self) -> None:
        """Load settings into instance variables."""
        self.update_interval = self.get_setting("update_interval")
        self.role_update_cooldown = self.get_setting("role_update_cooldown")
        self.process_batch_size = self.get_setting("process_batch_size")
        self.process_delay = self.get_setting("process_delay")
        self.error_retry_delay = self.get_setting("error_retry_delay")
        self.dry_run = self.get_setting("dry_run")
        self.dry_run_limit = self.get_setting("dry_run_limit")
        self.debug_logging = self.get_setting("debug_logging")
        self.pause = self.get_setting("pause")
        self.update_on_startup = self.get_setting("update_on_startup")
        self.roles_cache_filename = self.get_setting("roles_cache_filename")

    @property
    def cache_file(self) -> Path:
        """Get the cache file path using the cog's data directory"""
        return self.data_directory / self.roles_cache_filename

    async def save_data(self) -> bool:
        """Save tournament role data using BaseCog's utility."""
        try:
            # Prepare serializable data
            save_data = {
                "roles_config": self.get_setting("roles_config", {}),
                "last_full_update": self.last_full_update.isoformat() if self.last_full_update else None,
                "processed_users": self.processed_users,
                "roles_assigned": self.roles_assigned,
                "roles_removed": self.roles_removed,
                "users_with_no_player_data": self.users_with_no_player_data
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
                self.set_setting("roles_config", roles_config)

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

    async def get_known_players_cog(self):
        """Get a reference to the KnownPlayers cog"""
        known_players_cog = self.bot.get_cog("Known Players")
        if not known_players_cog:
            self.logger.error("KnownPlayers cog not found!")
            return None

        # Make sure the cache is ready
        await known_players_cog.wait_until_ready()
        return known_players_cog

    async def get_tourney_stats_cog(self):
        """Get a reference to the TourneyStats cog"""
        tourney_stats_cog = self.bot.get_cog("Tourney Stats")

        if not tourney_stats_cog:
            self.logger.error("TourneyStats cog not found!")
            return None

        # Make sure the cache is ready
        await tourney_stats_cog.wait_until_ready()
        return tourney_stats_cog

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
                    if self.get_setting("update_on_startup"):
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
                    # For automatic updates, create a message in the log channel
                    log_channel_id = self.get_setting("log_channel_id")
                    if log_channel_id:
                        try:
                            channel = self.bot.get_channel(int(log_channel_id))
                            if channel:
                                # Get dry run status
                                dry_run = self.get_setting("dry_run")
                                initial_message = "🔍 Starting automatic role update in DRY RUN mode..." if dry_run else "🔄 Starting automatic role update..."
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
                await asyncio.sleep(self.get_setting("error_retry_delay", 300))  # Sleep on error

    async def update_all_roles(self):
        """Update roles for all users based on tournament performance"""
        if self.currently_updating:
            self.logger.warning("Role update already in progress, skipping")
            return

        # Check if updates are paused
        if self.get_setting("pause"):
            self.logger.info("Role updates are currently paused. Skipping update.")
            return

        async with self.task_tracker.task_context("Role Update", "Updating tournament roles"):
            start_time = datetime.datetime.now(datetime.timezone.utc)
            try:
                self.currently_updating = True
                self.logger.info("Starting full role update")

                # Get role configurations early and check once
                roles_config = self.get_setting("roles_config", {})
                if not roles_config:
                    self.logger.warning("No roles configured for tournament role assignment. Add roles with the 'roles add_role' command.")
                    self.currently_updating = False
                    return

                # Log if in dry run mode
                dry_run = self.get_setting("dry_run")
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

                guild = self.guild
                if not guild:
                    self.logger.error("Could not find guild")
                    return

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
                    batch = discord_ids[i:i + self.process_batch_size]

                    for discord_id in batch:
                        try:
                            player_data = discord_to_player[discord_id]
                            if not player_data:
                                self.logger.debug(f"No player data for Discord ID {discord_id}")
                                continue

                            # Validate required fields
                            if 'all_ids' not in player_data:
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
                            player_tournaments = await self.get_player_tournament_stats(
                                tourney_stats_cog, player_ids
                            )

                            # Get all role objects
                            roles_config = self.get_setting("roles_config", {})
                            role_objects = {}
                            for role_name, config in roles_config.items():
                                role_id = config.get("id")
                                if role_id:
                                    role = guild.get_role(int(role_id))
                                    if role:
                                        role_objects[role_name] = role
                                    else:
                                        self.logger.warning(f"Could not find role with ID {role_id} for '{role_name}'")

                            # Update member's roles
                            # Get the log message but DON'T add it to buffer here
                            # It will be added to log_messages and sent in batches
                            roles_added, roles_removed, log_message = await self.update_member_roles(member, player_tournaments, role_objects)

                            # Handle logging
                            if log_message:
                                log_messages.append(log_message)

                                # If we've reached batch size, send logs
                                log_batch_size = self.get_setting("log_batch_size", 10)
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

                self.logger.info(f"Stats: Processed {self.processed_users} users, {self.roles_assigned} roles assigned, {self.roles_removed} roles removed")
                await self.add_log_message(f"📊 Stats: Processed {self.processed_users} users, {self.roles_assigned} roles assigned, {self.roles_removed} roles removed")

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

    async def get_player_tournament_stats(self, tourney_stats_cog, player_ids):
        """
        Get detailed tournament statistics for a player across all their player IDs.

        Args:
            tourney_stats_cog: The TourneyStats cog instance
            player_ids: List of player IDs associated with the Discord user

        Returns:
            Dictionary containing:
            - Per-league statistics
            - Latest tournament data
            - Latest patch data for role determination
        """
        # Initialize result dictionary with structure compatible with determine_best_role
        result = {
            "leagues": {},  # Stats by league
            "latest_tournament": {
                "placement": None,
                "league": None,
                "date": None
            },
            "latest_patch": {
                "best_placement": float("inf"),
                "max_wave": 0
            },
            "total_tourneys": 0
        }

        latest_tournament_date = None

        # Process each player ID (a Discord user might have multiple player accounts)
        for player_id in player_ids:
            try:
                # Get comprehensive stats for this player across all leagues
                player_stats = await tourney_stats_cog.get_player_stats(player_id)

                # For each league the player has participated in
                for league_name, league_stats in player_stats.items():
                    # Initialize this league if not present
                    if league_name not in result["leagues"]:
                        result["leagues"][league_name] = {
                            "best_wave": 0,
                            "best_position": float("inf"),
                            "position_at_best_wave": 0,
                            "total_tourneys": 0,
                            "avg_wave": 0,
                            "avg_position": 0
                        }

                    # Skip this league if no tournaments
                    tourney_count = league_stats.get("total_tourneys", 0)
                    if tourney_count == 0:
                        continue

                    # Update tournament counts
                    league_result = result["leagues"][league_name]
                    prev_count = league_result["total_tourneys"]
                    league_result["total_tourneys"] += tourney_count
                    result["total_tourneys"] += tourney_count

                    # Calculate weighted averages for waves and positions
                    if prev_count > 0:
                        total_tourneys = prev_count + tourney_count
                        # Weighted average calculation
                        league_result["avg_wave"] = (
                            (league_result["avg_wave"] * prev_count) +
                            (league_stats.get("avg_wave", 0) * tourney_count)
                        ) / total_tourneys

                        league_result["avg_position"] = (
                            (league_result["avg_position"] * prev_count) +
                            (league_stats.get("avg_position", 0) * tourney_count)
                        ) / total_tourneys
                    else:
                        # First data for this league
                        league_result["avg_wave"] = league_stats.get("avg_wave", 0)
                        league_result["avg_position"] = league_stats.get("avg_position", 0)

                    # Update best wave if higher (for this league)
                    best_wave = league_stats.get("best_wave", 0)
                    if best_wave > league_result["best_wave"]:
                        league_result["best_wave"] = best_wave
                        league_result["position_at_best_wave"] = league_stats.get("position_at_best_wave", 0)

                    # Update best position if better (for this league)
                    best_position = league_stats.get("best_position", float("inf"))
                    if best_position < league_result["best_position"]:
                        league_result["best_position"] = best_position

                    # Update latest patch data (aggregating across all leagues)
                    if best_position < result["latest_patch"]["best_placement"]:
                        result["latest_patch"]["best_placement"] = best_position

                    max_wave = league_stats.get("max_wave", 0)
                    if max_wave > result["latest_patch"]["max_wave"]:
                        result["latest_patch"]["max_wave"] = max_wave

                    # Check for latest tournament
                    latest_date = league_stats.get("latest_date")
                    if latest_date and (latest_tournament_date is None or latest_date > latest_tournament_date):
                        latest_tournament_date = latest_date
                        result["latest_tournament"] = {
                            "league": league_name,
                            "wave": league_stats.get("latest_wave"),
                            "placement": league_stats.get("latest_position"),
                            "date": latest_date
                        }

                    self.logger.debug(f"Player {player_id}: {tourney_count} tournaments in {league_name}, best wave: {best_wave}")
            except Exception as e:
                self.logger.error(f"Error getting stats for player {player_id}: {e}")

        # Clean up infinity value if no tournaments found
        if result["latest_patch"]["best_placement"] == float("inf"):
            result["latest_patch"]["best_placement"] = None

        return result

    async def update_member_roles(self, member, player_tournaments, league_roles):
        """
        Update a member's roles based on tournament performance

        Args:
            member: Discord member to update
            player_tournaments: Tournament data for this player
            league_roles: Dictionary mapping role names to Discord role objects

        Returns:
            tuple: (roles_added, roles_removed, log_message or None)
        """
        try:
            # Dispatch start event
            self.bot.dispatch('bot_role_update_start', member.id)

            # Check if verified role is required
            verified_role_id = self.get_setting("verified_role_id")
            if verified_role_id:
                verified_role = member.guild.get_role(int(verified_role_id))
                if not verified_role:
                    self.logger.warning(f"Verified role with ID {verified_role_id} not found in guild")
                elif verified_role not in member.roles:
                    # Remove all tournament roles if user isn't verified
                    roles_config = self.get_setting("roles_config", {})
                    all_managed_role_ids = [config.get("id") for config in roles_config.values()]

                    dry_run = self.get_setting("dry_run")
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
                                log_msg = f"{'Would remove' if dry_run else 'Removed'} {role.name} role from {member.name} ({member.id}) - not verified"
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
            best_role_id = self.determine_best_role(player_tournaments)

            # Get all managed role IDs for comparison
            roles_config = self.get_setting("roles_config", {})
            all_managed_role_ids = [config.get("id") for config in roles_config.values()]

            dry_run = self.get_setting("dry_run")

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
            self.bot.dispatch('bot_role_update_end', member.id)

    def determine_best_role(self, player_tournaments):
        """
        Determine the best role for a player based on tournament performance.

        Evaluates roles in Champion → Placement → Wave priority order:
        Champion: Latest tournament winner in the top-most league (e.g., "Current Champion")
        Placement: Placement across all tournaments in latest patch (e.g., "Top100")
        Wave: Wave-based across all tournaments in latest patch (e.g., "Champion500")

        Args:
            player_tournaments: Dictionary containing player's tournament data

        Returns:
            str: Role ID to assign, or None if no qualifying role
        """
        # Get role configurations from settings
        roles_config = self.get_setting("roles_config", {})
        debug_logging = self.get_setting("debug_logging")

        if not roles_config:
            self.logger.warning("No roles configured for tournament role assignment")
            return None

        # Get league hierarchy
        league_hierarchy = self.get_setting("league_hierarchy",
                                            ["Legend", "Champion", "Platinum", "Gold", "Silver", "Copper"])

        if debug_logging:
            self.logger.info("==== ROLE DETERMINATION ANALYSIS ====")
            self.logger.info(f"Player latest tournament: {player_tournaments.get('latest_tournament', {})}")
            self.logger.info(f"League hierarchy: {' > '.join(league_hierarchy)}")

        # Champion method: Latest tournament placement-based (highest priority)
        champion_roles = {role_name: config for role_name, config in roles_config.items()
                          if config.get('method') == 'Champion'}

        if champion_roles:
            # Check if multiple "Current Champion" roles are configured
            if len(champion_roles) > 1 and debug_logging:
                self.logger.warning(f"Multiple Champion method roles detected: {', '.join(champion_roles.keys())}. Only one should be configured.")

            # Get latest tournament data
            latest_tournament = player_tournaments.get("latest_tournament", {})
            if latest_tournament:
                placement = latest_tournament.get("placement")
                league = latest_tournament.get("league")

                if debug_logging:
                    self.logger.info(f"Latest tournament: League={league}, Placement={placement}")

                # Only assign Champion role if the player placed first in the top-most league
                if placement and league:
                    # Check if this is the top league in the hierarchy
                    is_top_league = league == league_hierarchy[0] if league_hierarchy else False

                    if debug_logging:
                        self.logger.info(f"Is top league? {is_top_league} (Top league: {league_hierarchy[0]})")

                    if is_top_league:
                        for role_name, config in champion_roles.items():
                            threshold = config.get('threshold', 1)
                            if debug_logging:
                                self.logger.info(f"Checking champion role '{role_name}' with threshold {threshold}")

                            if placement <= threshold:
                                if debug_logging:
                                    self.logger.info(f"✅ CHAMPION ROLE MATCH: '{role_name}' - player placed {placement} in {league} (threshold: {threshold})")
                                return config.get('id')
                            elif debug_logging:
                                self.logger.info(f"❌ Champion role '{role_name}' not matched - placement {placement} > threshold {threshold}")
                    elif debug_logging:
                        self.logger.info(f"❌ Champion role not applied - {league} is not the top league ({league_hierarchy[0]})")
                elif debug_logging:
                    self.logger.info("❌ Champion role not applied - missing placement or league data")
            elif debug_logging:
                self.logger.info("❌ Champion role not applied - no latest tournament data")

        # Placement method: Placement-based roles respecting league hierarchy
        placement_roles = {role_name: config for role_name, config in roles_config.items()
                           if config.get('method') == 'Placement'}

        if placement_roles:
            if debug_logging:
                self.logger.info(f"\nPLACEMENT METHOD: Checking {len(placement_roles)} placement roles")

            # Get the top league from the hierarchy
            league_hierarchy = self.get_setting("league_hierarchy",
                                                ["Legend", "Champion", "Platinum", "Gold", "Silver", "Copper"])
            top_league = league_hierarchy[0] if league_hierarchy else None

            if debug_logging and top_league:
                self.logger.info(f"Top league in hierarchy: {top_league}")

            # Group roles by league
            league_placement_roles = {}
            for role_name, config in placement_roles.items():
                # If role name starts with "Top", assign to top league
                if role_name.startswith("Top") and top_league:
                    if debug_logging:
                        self.logger.info(f"Role '{role_name}' starts with 'Top', assigning to top league: {top_league}")
                    league = top_league
                else:
                    league = config.get('league')

                if league:
                    if league not in league_placement_roles:
                        league_placement_roles[league] = []
                    league_placement_roles[league].append((role_name, config))

            # Check each league in order of hierarchy
            for league in league_hierarchy:
                if debug_logging:
                    has_roles = league in league_placement_roles
                    has_data = league in player_tournaments.get("leagues", {})
                    self.logger.info(f"Checking league {league} - Has roles: {has_roles}, Has player data: {has_data}")

                if league in league_placement_roles and league in player_tournaments.get("leagues", {}):
                    league_data = player_tournaments["leagues"][league]
                    best_position = league_data.get("best_position")

                    if best_position and best_position != float('inf'):
                        # Sort roles within this league by threshold (ascending)
                        sorted_roles = sorted(league_placement_roles[league],
                                              key=lambda x: x[1].get('threshold', float('inf')))

                        if debug_logging:
                            role_thresholds = [(r[0], r[1].get('threshold')) for r in sorted_roles]
                            self.logger.info(f"Available roles in {league} (sorted by threshold): {role_thresholds}")

                        # Check if player qualifies for any role in this league
                        for role_name, config in sorted_roles:
                            threshold = config.get('threshold', 100)
                            if debug_logging:
                                self.logger.info(f"Checking placement role '{role_name}' with threshold {threshold}")

                            if best_position <= threshold:
                                if debug_logging:
                                    self.logger.info(f"✅ PLACEMENT ROLE MATCH: '{role_name}' - player best position {best_position} in {league} (threshold: {threshold})")
                                return config.get('id')
                            elif debug_logging:
                                self.logger.info(f"❌ Placement role '{role_name}' not matched - position {best_position} > threshold {threshold}")
                    elif debug_logging:
                        self.logger.info(f"❌ No valid position data for {league}")

        # Wave method: Wave-based across all tournaments in latest patch
        wave_roles = {role_name: config for role_name, config in roles_config.items()
                      if config.get('method') == 'Wave'}

        if wave_roles:
            if debug_logging:
                self.logger.info(f"\nWAVE METHOD: Checking {len(wave_roles)} wave roles")

            # Get wave data across all tournaments in the latest patch
            patch_data = player_tournaments.get("latest_patch", {})
            if patch_data:
                max_wave = patch_data.get("max_wave", 0)

                if debug_logging:
                    self.logger.info(f"Player's max wave: {max_wave}")

                # Group roles by league
                league_roles = {}
                for role_name, config in wave_roles.items():
                    league = config.get('league')
                    if league:
                        if league not in league_roles:
                            league_roles[league] = []
                        league_roles[league].append((role_name, config))

                # Check each league in order of hierarchy
                for league in league_hierarchy:
                    if debug_logging and league in league_roles:
                        self.logger.info(f"Checking wave roles for league {league}")

                    if league in league_roles:
                        # Sort roles within this league by threshold (descending)
                        sorted_roles = sorted(league_roles[league],
                                              key=lambda x: x[1].get('threshold', 0),
                                              reverse=True)

                        if debug_logging:
                            role_thresholds = [(r[0], r[1].get('threshold')) for r in sorted_roles]
                            self.logger.info(f"Available roles in {league} (sorted by threshold desc): {role_thresholds}")

                        # Check if player qualifies for any role in this league
                        for role_name, config in sorted_roles:
                            threshold = config.get('threshold', 0)
                            if debug_logging:
                                self.logger.info(f"Checking wave role '{role_name}' with threshold {threshold}")

                            # Get league-specific best wave instead of global max wave
                            league_data = player_tournaments.get("leagues", {}).get(league, {})
                            league_max_wave = league_data.get("best_wave", 0)

                            if league_max_wave >= threshold:
                                if debug_logging:
                                    self.logger.info(f"✅ WAVE ROLE MATCH: '{role_name}' - player max wave {league_max_wave} in {league} meets threshold of {threshold}")
                                return config.get('id')
                            elif debug_logging:
                                self.logger.info(f"❌ Wave role '{role_name}' not matched - wave {league_max_wave} < threshold {threshold}")
            elif debug_logging:
                self.logger.info("❌ No patch data available for wave-based roles")

        # No qualifying role found
        if debug_logging:
            self.logger.info("❌ NO QUALIFYING ROLE FOUND")
            self.logger.info("==== END ROLE DETERMINATION ANALYSIS ====")

        return None

    @commands.group(
        name="tourneyroles",
        aliases=["tr"],
        description="Tournament role management commands"
    )
    async def tourneyroles_group(self, ctx):
        """Tournament role management commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @tourneyroles_group.command(
        name="status",
        description="Display operational status and information"
    )
    async def roles_status_command(self, ctx):
        """Show current status of the tournament roles system"""
        main_embed = discord.Embed(
            title="Tournament Roles Status",
            description="Current operational state and information",
            color=discord.Color.blue()
        )

        # Determine status and color
        if not self.is_ready:
            status_emoji = "⏳"
            status_text = "Initializing"
            embed_color = discord.Color.orange()
        elif self._has_errors:
            status_emoji = "❌"
            status_text = "Error"
            embed_color = discord.Color.red()
        elif self.currently_updating:
            status_emoji = "🔄"
            status_text = "Updating Roles"
            embed_color = discord.Color.blue()
        elif self.get_setting("pause"):
            status_emoji = "⏸️"
            status_text = "Paused"
            embed_color = discord.Color.orange()
        else:
            status_emoji = "✅"
            status_text = "Operational"
            embed_color = discord.Color.green()

        main_embed.color = embed_color

        # System state
        status_value = [f"{status_emoji} **Status:** {status_text}"]
        if self._has_errors:
            status_value.append("⚠️ System has encountered errors")
        if self.get_setting("dry_run"):
            status_value.append("🔍 Running in dry run mode")
        main_embed.add_field(
            name="System State",
            value="\n".join(status_value),
            inline=False
        )

        # Dependencies field
        dependencies = []
        known_players_cog = self.bot.get_cog("Known Players")
        tourney_stats_cog = self.bot.get_cog("Tourney Stats")
        dependencies.append(f"{'✅' if known_players_cog else '❌'} KnownPlayers")
        dependencies.append(f"{'✅' if tourney_stats_cog else '❌'} TourneyStats")
        main_embed.add_field(
            name="Dependencies",
            value="\n".join(dependencies),
            inline=False
        )

        # Last update info
        if self.last_full_update:
            time_since_update = (datetime.datetime.now(datetime.timezone.utc) - self.last_full_update).total_seconds()
            if time_since_update < 60:
                time_str = f"{time_since_update:.1f} seconds ago"
            elif time_since_update < 3600:
                time_str = f"{time_since_update / 60:.1f} minutes ago"
            else:
                time_str = f"{time_since_update / 3600:.1f} hours ago"

            update_info = f"{self.last_full_update.strftime('%Y-%m-%d %H:%M:%S')} UTC ({time_str})"
        else:
            update_info = "Never run"

        main_embed.add_field(name="Last Full Update", value=update_info, inline=False)

        # Add logging configuration
        log_channel_id = self.get_setting("log_channel_id")
        log_status = "❌ Disabled"
        if log_channel_id:
            log_channel = ctx.guild.get_channel(int(log_channel_id))
            if log_channel:
                log_status = f"✅ Enabled - {log_channel.mention} (ID: {log_channel_id})"
            else:
                log_status = f"⚠️ Channel not found (ID: {log_channel_id})"
        main_embed.add_field(name="Role Update Logging", value=log_status, inline=False)

        if log_channel_id:
            batch_size = self.get_setting("log_batch_size", 10)
            main_embed.add_field(name="Log Batch Size", value=str(batch_size), inline=True)

        # Stats info if available
        if self.processed_users > 0:
            stats_info = (
                f"**Users Processed:** {self.processed_users}\n"
                f"**Roles Assigned:** {self.roles_assigned}\n"
                f"**Roles Removed:** {self.roles_removed}\n"
                f"**No Player Data:** {self.users_with_no_player_data}"
            )
            main_embed.add_field(name="Last Update Stats", value=stats_info, inline=False)

        # Timing settings
        settings = []
        settings.append(f"Update Interval: {self.format_duration(self.update_interval)}")
        settings.append(f"Role Update Cooldown: {self.format_duration(self.role_update_cooldown)}")
        settings.append(f"Process Batch Size: {self.process_batch_size}")
        main_embed.add_field(
            name="Current Settings",
            value="\n".join(settings),
            inline=False
        )

        await ctx.send(embed=main_embed)

    @tourneyroles_group.command(
        name="pause",
        description="Pause or unpause role updates"
    )
    async def pause_command(self, ctx):
        """Pause or unpause role updates."""
        current = self.get_setting("pause", False)
        new_value = not current
        self.set_setting("pause", new_value)

        if new_value:
            await ctx.send("⏸️ Role updates are now paused")
        else:
            await ctx.send("▶️ Role updates have been resumed")

    @tourneyroles_group.command(
        name="refresh",
        aliases=["reload"],
        description="Refresh role assignments"
    )
    async def refresh_command(self, ctx):
        """Refresh/reload role assignments."""
        if self.currently_updating:
            return await ctx.send("⚠️ Update already in progress")

        message = await ctx.send("🔄 Starting role refresh...")
        await self.start_update_with_progress(message, manual_update=True)

    def format_duration(self, seconds: int) -> str:
        """Format a duration in seconds to a human readable string."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)

    @tourneyroles_group.command(name="settings")
    async def roles_settings_command(self, ctx):
        """Display current tournament roles settings"""
        settings = self.get_all_settings()

        # Create main settings embed
        embed = discord.Embed(
            title="Tournament Roles Settings",
            description="Current configuration for tournament role assignment",
            color=discord.Color.blue()
        )

        # Process simple settings first (non-dictionary values)
        simple_settings = {k: v for k, v in settings.items()
                           if not isinstance(v, dict) and k != "league_hierarchy"}

        # Timing settings
        timing_embed = discord.Embed(
            title="Timing Settings",
            color=discord.Color.blue()
        )

        for name in ["update_interval", "role_update_cooldown", "process_delay", "error_retry_delay"]:
            if name in simple_settings:
                value = simple_settings.pop(name)
                hours = value // 3600
                minutes = (value % 3600) // 60
                seconds = value % 60
                formatted_value = f"{hours}h {minutes}m {seconds}s ({value} seconds)"
                timing_embed.add_field(name=name, value=formatted_value, inline=True)

        # Flag settings
        flag_embed = discord.Embed(
            title="Operation Flags",
            color=discord.Color.blue()
        )

        for name in ["dry_run", "pause", "update_on_startup", "debug_logging"]:
            if name in simple_settings:
                value = simple_settings.pop(name)
                emoji = "✅" if value else "❌"
                formatted_value = f"{emoji} {'Enabled' if value else 'Disabled'}"
                flag_embed.add_field(name=name, value=formatted_value, inline=True)

        # Add immediate logging status to embed
        if "immediate_logging" in settings:
            value = settings.pop("immediate_logging")
            emoji = "✅" if value else "❌"
            formatted_value = f"{emoji} {'Enabled' if value else 'Disabled'}"
            flag_embed.add_field(name="Immediate Logging", value=formatted_value, inline=True)

        # Process threshold settings
        threshold_embed = discord.Embed(
            title="Processing Settings",
            color=discord.Color.blue()
        )

        for name in ["process_batch_size"]:
            if name in simple_settings:
                value = simple_settings.pop(name)
                threshold_embed.add_field(name=name, value=str(value), inline=True)

        # League hierarchy
        if "league_hierarchy" in settings:
            league_hierarchy = settings["league_hierarchy"]
            league_str = " → ".join(league_hierarchy)
            embed.add_field(
                name="League Hierarchy (Highest to Lowest)",
                value=f"```{league_str}```",
                inline=False
            )

        # Handle roles config separately
        roles_embed = None
        if "roles_config" in settings:
            roles_config = settings["roles_config"]
            if roles_config:
                # Create a separate embed for role configuration
                roles_embed = discord.Embed(
                    title="Tournament Role Configuration",
                    description=f"{len(roles_config)} roles configured",
                    color=discord.Color.gold()
                )

                # Group roles by method
                champion_roles = []
                placement_roles = []
                wave_roles = []

                for role_name, config in roles_config.items():
                    method = config.get('method', '')
                    threshold = config.get('threshold', 0)
                    role_id = config.get('id', '0')
                    role = ctx.guild.get_role(int(role_id)) if role_id else None
                    role_display = f"**{role.name}**" if role else f"(ID: {role_id})"

                    if method == 'Champion':
                        champion_roles.append(f"• {role_name}: {role_display}")
                    elif method == 'Placement':
                        placement_roles.append(f"• {role_name}: {role_display} (Top {threshold})")
                    elif method == 'Wave':
                        league = config.get('league', 'Unknown')
                        wave_roles.append(f"• {role_name}: {role_display} ({league} {threshold}+)")

                # Add fields for each method
                if champion_roles:
                    roles_embed.add_field(
                        name="Champion Method: Tournament Winner Roles",
                        value="\n".join(champion_roles) or "None configured",
                        inline=False
                    )

                if placement_roles:
                    roles_embed.add_field(
                        name="Placement Method: Placement-Based Roles",
                        value="\n".join(placement_roles) or "None configured",
                        inline=False
                    )

                if wave_roles:
                    roles_embed.add_field(
                        name="Wave Method: Wave-Based Roles",
                        value="\n".join(wave_roles) or "None configured",
                        inline=False
                    )

        # Add any remaining simple settings to the main embed
        for name, value in simple_settings.items():
            embed.add_field(name=name, value=str(value), inline=True)

        # Add status information to main embed
        status = "✅ Ready" if self.is_ready else "⏳ Initializing"
        if self.currently_updating:
            status = "🔄 Updating roles"
        if self.get_setting("pause"):
            status = "⏸️ Paused"
        elif self.get_setting("dry_run"):
            status = "🔍 Dry Run Mode"
        embed.add_field(name="Status", value=status, inline=False)

        # Add last update information
        if self.last_full_update:
            time_since_update = (datetime.datetime.now(datetime.timezone.utc) - self.last_full_update).total_seconds()
            if time_since_update < 60:
                time_str = f"{time_since_update:.1f} seconds ago"
            elif time_since_update < 3600:
                time_str = f"{time_since_update / 60:.1f} minutes ago"
            else:
                time_str = f"{time_since_update / 3600:.1f} hours ago"

            embed.add_field(
                name="Last Full Update",
                value=f"{self.last_full_update.strftime('%Y-%m-%d %H:%M:%S')} UTC ({time_str})",
                inline=False
            )

        # Send the embeds - main settings first
        await ctx.send(embed=embed)

        # Then send the specialized embeds if they have fields
        if flag_embed.fields:
            await ctx.send(embed=flag_embed)
        if timing_embed.fields:
            await ctx.send(embed=timing_embed)
        if threshold_embed.fields:
            await ctx.send(embed=threshold_embed)
        if roles_embed and roles_embed.fields:
            await ctx.send(embed=roles_embed)

    @tourneyroles_group.command(name="add_role")
    async def add_role_command(self, ctx, role: discord.Role, method: str,
                               threshold: int, league: str = None):
        """
        Add a tournament role to be managed

        Args:
            role: Discord role to manage
            method: Assignment method (Champion=Tournament winner, Placement=Placement-based, Wave=Wave-based)
            threshold: Wave count or placement threshold
            league: League name (required for Wave method, optional for others)
        """
        method = method.title()
        valid_methods = ['Champion', 'Placement', 'Wave']
        if method not in valid_methods:
            return await ctx.send(f"❌ Invalid method. Use {', '.join(valid_methods)}")

        # Validate league for Wave method
        if method == 'Wave' and not league:
            return await ctx.send("❌ League parameter is required for Wave method")

        # Get league hierarchy
        league_hierarchy = self.get_setting("league_hierarchy",
                                            ["Legend", "Champion", "Platinum", "Gold", "Silver", "Copper"])

        # For Wave method, validate league is in hierarchy
        if method == 'Wave' and league not in league_hierarchy:
            league_list = ", ".join(league_hierarchy)
            return await ctx.send(f"❌ Invalid league. Must be one of: {league_list}")

        # Generate role name based on method
        if method == 'Champion':
            role_name = "Current Champion"
        elif method == 'Placement':
            role_name = f"Top{threshold}"
        else:  # method == 'Wave'
            role_name = f"{league}{threshold}"

        # Get existing roles config
        roles_config = self.get_setting("roles_config", {})

        # Check if this is a duplicate role name
        if role_name in roles_config:
            return await ctx.send(f"❌ Role with name '{role_name}' already exists")

        # Add new role configuration
        roles_config[role_name] = {
            'id': str(role.id),
            'method': method,
            'threshold': threshold
        }
        if method == 'Wave':
            roles_config[role_name]['league'] = league

        # Save updated configuration
        self.set_setting("roles_config", roles_config)
        self.mark_data_modified()

        await ctx.send(f"✅ Added tournament role '{role_name}' ({role.name}) with {method} method")

    @tourneyroles_group.command(name="remove_role")
    async def remove_role_command(self, ctx, role_name: str):
        """
        Remove a tournament role from management

        Args:
            role_name: Name of the role config to remove
        """
        # Get existing roles config
        roles_config = self.get_setting("roles_config", {})

        # Check if the role exists
        if role_name not in roles_config:
            return await ctx.send(f"❌ Role configuration '{role_name}' not found")

        # Remove the role
        removed_config = roles_config.pop(role_name)
        self.set_setting("roles_config", roles_config)
        self.mark_data_modified()

        # Get the actual role name for confirmation message
        role_id = removed_config.get('id')
        role_obj = ctx.guild.get_role(int(role_id)) if role_id else None
        role_display = role_obj.name if role_obj else f"ID: {role_id}"

        await ctx.send(f"✅ Removed tournament role '{role_name}' ({role_display})")

    @tourneyroles_group.command(name="list_roles")
    async def list_roles_command(self, ctx):
        """List all configured tournament roles"""
        # Get existing roles config
        roles_config = self.get_setting("roles_config", {})

        if not roles_config:
            return await ctx.send("No tournament roles have been configured")

        embed = discord.Embed(
            title="Tournament Roles Configuration",
            description="Current roles managed by the tournament system",
            color=discord.Color.blue()
        )

        # Group roles by method
        champion_roles = []
        placement_roles = []
        wave_roles = []

        for role_name, config in roles_config.items():
            method = config.get('method')
            threshold = config.get('threshold')
            role_id = config.get('id')
            role_obj = ctx.guild.get_role(int(role_id)) if role_id else None
            role_display = role_obj.name if role_obj else f"(ID: {role_id})"

            role_info = f"• **{role_name}** - {role_display}"

            if method == 'Champion':
                champion_roles.append(role_info)
            elif method == 'Placement':
                # Store tuple of (threshold, formatted string) for sorting
                placement_roles.append((threshold, f"{role_info} (Top {threshold})"))
            else:  # method == 'Wave'
                league = config.get('league', 'Unknown')
                wave_roles.append(f"{role_info} ({league} wave {threshold}+)")

        # Sort placement roles by threshold numerically and extract display strings
        placement_roles.sort(key=lambda x: x[0])  # Sort by threshold
        placement_roles = [role[1] for role in placement_roles]  # Extract display strings

        # Add fields for each method
        if champion_roles:
            embed.add_field(
                name="Champion Method: Latest Tournament Winner",
                value="\n".join(champion_roles),
                inline=False
            )

        if placement_roles:
            embed.add_field(
                name="Placement Method: Placement-Based",
                value="\n".join(placement_roles),
                inline=False
            )

        if wave_roles:
            embed.add_field(
                name="Wave Method: Wave-Based",
                value="\n".join(wave_roles),
                inline=False
            )

        await ctx.send(embed=embed)

    @tourneyroles_group.command(name="set_league_hierarchy")
    async def set_league_hierarchy_command(self, ctx, *, leagues: str):
        """
        Set the hierarchy of leagues for role assignment

        Args:
            leagues: Comma-separated list of league names, in order from highest to lowest
        """
        # Parse league names from comma-separated string
        league_hierarchy = [name.strip() for name in leagues.split(',')]

        # Validate that we have at least one league
        if not league_hierarchy or not all(league_hierarchy):
            return await ctx.send("❌ Please provide a valid comma-separated list of league names")

        # Save the league hierarchy
        self.set_setting("league_hierarchy", league_hierarchy)
        self.mark_data_modified()

        await ctx.send(f"✅ League hierarchy set: {', '.join(league_hierarchy)}")

    @tourneyroles_group.command(name="set")
    async def roles_set_setting_command(self, ctx, setting_name: str, value: int):
        """
        Change a tournament roles setting

        Args:
            setting_name: Setting to change (update_interval, role_update_cooldown, process_batch_size, process_delay, error_retry_delay, dry_run_limit)
            value: New value for the setting
        """
        valid_settings = [
            "update_interval",
            "role_update_cooldown",
            "process_batch_size",
            "process_delay",
            "error_retry_delay",
            "dry_run_limit"
        ]

        if setting_name not in valid_settings:
            valid_settings_str = ", ".join(valid_settings)
            return await ctx.send(f"Invalid setting name. Valid options: {valid_settings_str}")

        # Validate inputs based on the setting
        if setting_name in ["update_interval", "role_update_cooldown"]:
            if value < 300:  # Minimum 5 minutes for main intervals
                return await ctx.send(f"Value for {setting_name} must be at least 300 seconds (5 minutes)")
        elif setting_name == "process_delay":
            if value < 1 or value > 30:
                return await ctx.send(f"Value for {setting_name} must be between 1 and 30 seconds")
        elif setting_name == "error_retry_delay":
            if value < 60 or value > 1800:
                return await ctx.send(f"Value for {setting_name} must be between 60 and 1800 seconds (1-30 minutes)")
        elif setting_name == "process_batch_size":
            if value < 10 or value > 200:
                return await ctx.send(f"Value for {setting_name} must be between 10 and 200")
        elif setting_name == "dry_run_limit":
            if value < 0 or value > 250:
                return await ctx.send(f"Value for {setting_name} must be between 0 and 250")

        # Save the setting
        self.set_setting(setting_name, value)

        # Update instance variable
        if hasattr(self, setting_name):
            setattr(self, setting_name, value)

        # Log the change
        if setting_name in ["update_interval", "role_update_cooldown", "process_delay"]:
            hours = value // 3600
            minutes = (value % 3600) // 60
            seconds = value % 60
            time_format = f"{hours}h {minutes}m {seconds}s"
            self.logger.info(f"Settings changed: {setting_name} set to {value} seconds ({time_format})")
        else:
            self.logger.info(f"Settings changed: {setting_name} set to {value}")

        # Mark settings as modified
        self.mark_data_modified()

        await ctx.send(f"✅ Set {setting_name} to {value}")

    @tourneyroles_group.command(name="update")
    async def roles_update_command(self, ctx):
        """Force update all tournament roles"""
        if self.currently_updating:
            return await ctx.send("⚠️ Role update already in progress. Please wait until it completes.")

        # Check and mention dry run mode
        dry_run = self.get_setting("dry_run")
        initial_message = "🔍 Starting role update in DRY RUN mode..." if dry_run else "🔄 Starting role update..."
        message = await ctx.send(f"{initial_message} This may take a while.")

        # Start the update with the message for progress tracking
        await self.start_update_with_progress(message, manual_update=True)

        # Let the command finish - updates will continue in background
        return await ctx.send("Role update started in the background. Progress will be updated in the original message.")

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
        dry_run = self.get_setting("dry_run")

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
            "manual_update": manual_update
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
                    color=discord.Color.green()
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
                    inline=False
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

    @tourneyroles_group.command(name="update_user")
    async def roles_update_user_command(self, ctx, user: discord.Member = None):
        """
        Update tournament roles for a specific user

        Args:
            user: The Discord user to update roles for. If not specified, updates the command author.
        """
        # If no user specified, use the command author
        if user is None:
            user = ctx.author

        if self.currently_updating:
            return await ctx.send("⚠️ Full role update is in progress. Please wait until it completes.")

        message = await ctx.send(f"🔄 Updating roles for {user.display_name}...")

        try:
            # Get required cogs
            known_players_cog = await self.get_known_players_cog()
            if not known_players_cog:
                return await message.edit(content="❌ KnownPlayers cog not available.")

            tourney_stats_cog = await self.get_tourney_stats_cog()
            if not tourney_stats_cog:
                return await message.edit(content="❌ TourneyStats cog not available.")

            # Get user's player data
            discord_id = str(user.id)
            discord_mapping = await self.get_discord_to_player_mapping()
            player_data = discord_mapping.get(discord_id)
            if not player_data:
                return await message.edit(content=f"❌ No player data found for {user.display_name}.")

            # Reset stats for this operation
            self.processed_users = 1
            self.roles_assigned = 0
            self.roles_removed = 0

            # Get tournament participation data
            player_tournaments = await self.get_player_tournament_stats(
                tourney_stats_cog,
                player_data.get('all_ids', [])
            )

            # Get all role objects
            roles_config = self.get_setting("roles_config", {})
            role_objects = {}
            for role_name, config in roles_config.items():
                role_id = config.get("id")
                if role_id:
                    role = ctx.guild.get_role(int(role_id))
                    if role:
                        role_objects[role_name] = role
                    else:
                        self.logger.warning(f"Could not find role with ID {role_id} for '{role_name}'")

            # Update member's roles and get log message
            roles_added, roles_removed, log_message = await self.update_member_roles(
                user, player_tournaments, role_objects
            )

            # If we have a log message, send it to the log channel
            if log_message:
                dry_run = self.get_setting("dry_run")
                prefix = "🔍 [DRY RUN] " if dry_run else ""
                await self.add_log_message(f"{prefix}{log_message}")
                await self.flush_log_buffer()  # Force send the log message immediately

            # Create response embed
            embed = discord.Embed(
                title="Tournament Roles Updated",
                description=f"Updated roles for {user.display_name}",
                color=discord.Color.green()
            )

            # Show their player data
            primary_id = player_data.get('primary_id', 'None')
            all_ids = player_data.get('all_ids', [])
            id_list = f"✅ {primary_id}" if primary_id and primary_id != 'None' else "None"
            if len(all_ids) > 1:
                other_ids = [pid for pid in all_ids if pid != primary_id]
                if other_ids:
                    id_list += f", {', '.join(other_ids[:3])}"
                    if len(other_ids) > 3:
                        id_list += f" (+{len(other_ids) - 3} more)"

            embed.add_field(
                name="Player Data",
                value=f"**Name:** {player_data.get('name', 'Unknown')}\n**Player IDs:** {id_list}",
                inline=False
            )

            # Add role changes
            dry_run = self.get_setting("dry_run")
            changes = []
            if roles_added > 0:
                changes.append(f"🟢 {roles_added} role{'s' if roles_added != 1 else ''} {'would be ' if dry_run else ''}added")
            if roles_removed > 0:
                changes.append(f"🔴 {roles_removed} role{'s' if roles_removed != 1 else ''} {'would be ' if dry_run else ''}removed")
            if not changes:
                changes.append("No role changes needed")

            embed.add_field(
                name="Role Changes" + (" (Dry Run)" if dry_run else ""),
                value="\n".join(changes),
                inline=False
            )

            # Add tournament stats if available
            if player_tournaments.get("total_tourneys", 0) > 0:
                latest = player_tournaments.get("latest_tournament", {})
                patch = player_tournaments.get("latest_patch", {})

                stats = []
                if latest.get("league"):
                    stats.append(f"**Latest Tournament:** {latest['league']} (Position: {latest.get('placement', 'N/A')})")
                if patch.get("max_wave"):
                    stats.append(f"**Best Wave:** {patch['max_wave']}")
                if patch.get("best_placement"):
                    stats.append(f"**Best Placement:** {patch['best_placement']}")

                if stats:
                    embed.add_field(
                        name="Tournament Stats",
                        value="\n".join(stats),
                        inline=False
                    )

            await message.edit(content=None, embed=embed)

        except Exception as e:
            self.logger.error(f"Error updating roles for user {user.id}: {e}")
            await message.edit(content=f"❌ Error updating roles: {str(e)}")
            # Also log the error to the log channel
            await self.add_log_message(f"⚠️ Error updating roles for {user.display_name} ({user.id}): {e}")
            await self.flush_log_buffer()

    @tourneyroles_group.command(name="toggle")
    async def roles_toggle_setting_command(self, ctx, setting_name: str):
        """
        Toggle a boolean tournament roles setting on or off

        Args:
            setting_name: Setting to toggle (dry_run, pause, update_on_startup, debug_logging)
        """
        valid_settings = ["dry_run", "pause", "update_on_startup", "debug_logging"]

        if setting_name not in valid_settings:
            valid_settings_str = ", ".join(valid_settings)
            return await ctx.send(f"Invalid setting name. Valid options: {valid_settings_str}")

        # Toggle the setting
        current_value = self.get_setting(setting_name, False)
        new_value = not current_value
        self.set_setting(setting_name, new_value)

        # Update instance variable
        if hasattr(self, setting_name):
            setattr(self, setting_name, new_value)

        # Send confirmation with emoji
        state = "enabled" if new_value else "disabled"
        if setting_name == "dry_run" and new_value:
            emoji = "🧪"
        elif setting_name == "pause" and new_value:
            emoji = "⏸️"
        elif setting_name == "update_on_startup" and new_value:
            emoji = "🔄"
        elif setting_name == "debug_logging" and new_value:
            emoji = "🔍"
        else:
            emoji = "✅"

        display_name = setting_name.replace('_', ' ').title()
        await ctx.send(f"{emoji} {display_name} is now {state}")

        # Log the change
        self.logger.info(f"Settings changed: {setting_name} set to {new_value} by {ctx.author}")

        # Mark settings as modified
        self.mark_data_modified()

    @tourneyroles_group.command(name="set_log_channel")
    async def set_log_channel_command(self, ctx, channel: discord.TextChannel = None):
        """
        Set the channel for role update logs

        Args:
            channel: The channel to send logs to. If none, disables logging.
        """
        if channel:
            self.set_setting("log_channel_id", channel.id)
            await ctx.send(f"✅ Role update logs will be sent to {channel.mention}")
        else:
            self.set_setting("log_channel_id", None)
            await ctx.send("✅ Role update logging disabled")

        # Mark settings as modified
        self.mark_data_modified()

    @tourneyroles_group.command(name="set_log_batch_size")
    async def set_log_batch_size_command(self, ctx, size: int):
        """
        Set how many role updates to process before sending a batch log

        Args:
            size: The number of updates to batch (1-50)
        """
        if not 1 <= size <= 50:
            return await ctx.send("❌ Batch size must be between 1 and 50")

        self.set_setting("log_batch_size", size)
        await ctx.send(f"✅ Role update log batch size set to {size}")

        # Mark settings as modified
        self.mark_data_modified()

    @tourneyroles_group.command(name="toggle_immediate_logging")
    async def toggle_immediate_logging_command(self, ctx):
        """Toggle whether logs are sent immediately during role updates or only at the end"""
        current_value = self.get_setting("immediate_logging", True)
        new_value = not current_value
        self.set_setting("immediate_logging", new_value)

        if new_value:
            await ctx.send("✅ Immediate logging enabled - logs will be sent during role updates")
        else:
            await ctx.send("📊 Immediate logging disabled - logs will only be sent at the end of role updates")

        # Log the change
        self.logger.info(f"Immediate logging {'enabled' if new_value else 'disabled'} by {ctx.author}")

        # Mark settings as modified
        self.mark_data_modified()

    @tourneyroles_group.command(name="set_verified_role")
    async def set_verified_role_command(self, ctx, role: discord.Role = None):
        """
        Set the role required for tournament role eligibility

        Args:
            role: The role users must have to be eligible for tournament roles. If none, disables verification requirement.
        """
        if role:
            self.set_setting("verified_role_id", role.id)
            await ctx.send(f"✅ Users must have the {role.mention} role to be eligible for tournament roles")
        else:
            self.set_setting("verified_role_id", None)
            await ctx.send("✅ Verification role requirement disabled")

        # Mark settings as modified
        self.mark_data_modified()

    async def add_log_message(self, message):
        """
        Add a message to the log buffer and potentially send it.

        Args:
            message: The log message to add
        """
        self.log_buffer.append(message)

        # Check if we should send immediately
        if self.get_setting("immediate_logging", True):
            # Check if we've hit batch size or buffer size limit
            batch_size = self.get_setting("log_batch_size", 10)

            # Check if we've hit batch size
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

        log_channel_id = self.get_setting("log_channel_id")
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

                # 1. Verify settings
                self.logger.debug("Loading settings")
                tracker.update_status("Verifying settings")
                self._load_settings()

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


async def setup(bot) -> None:
    await bot.add_cog(TourneyRoles(bot))
