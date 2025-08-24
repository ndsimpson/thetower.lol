import asyncio
import discord
from discord.ext import commands
import logging
from datetime import datetime, timedelta
from collections import deque

from thetower.bot.basecog import BaseCog

logger = logging.getLogger(__name__)


class TourneyRoleSupervisor(BaseCog,
                            name="Tournament Role Supervisor",
                            description="Supervises tournament role assignments"):
    """Tournament role supervisor.

    Monitors role changes and new members to manage tournament role assignments.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing TourneyRoleSupervisor")

        # Initialize queues and tracking
        self.update_queue = asyncio.Queue()
        self.recently_updated = deque(maxlen=100)  # Track recently processed users
        self.processing = False
        self._last_update = None
        self.update_task = None

        # Add debouncing system
        self.pending_updates = {}  # {user_id: {'task': Task, 'initial_roles': set(), 'final_roles': set(), 'timer_start': datetime}}
        self.debounce_delay = 2.0  # Seconds to wait for additional changes

        # Add state tracking for dependency availability
        self._cogs_available = False

        # Initialize settings with defaults and descriptions
        settings_config = {
            "cooldown_seconds": (300, "Seconds before allowing another update for the same user"),
            "process_interval": (5, "Seconds between processing queue items"),
            "queue_size_limit": (1000, "Maximum number of users to queue"),
            "debug_logging": (False, "Enable detailed debug logging")
        }

        # Initialize settings
        for name, (value, description) in settings_config.items():
            if not self.has_setting(name):
                self.set_setting(name, value, description)

        # Track bot role updates
        self.bot_role_updates = set()  # Set of member IDs currently being updated by bot

    async def cog_initialize(self) -> None:
        """Initialize the supervisor cog."""
        self.logger.info("Starting TourneyRoleSupervisor initialization")

        try:
            # Start the queue processor
            self.update_task = self.bot.loop.create_task(self.process_queue())
            self.logger.info("Started queue processor task")

            # Set ready state
            self.set_ready(True)
            self.logger.info("TourneyRoleSupervisor initialization complete")

        except Exception as e:
            self.logger.error(f"Error during initialization: {e}", exc_info=True)
            self._has_errors = True
            raise

    async def get_required_cogs(self):
        """Get references to required cogs."""
        known_players = self.bot.get_cog("Known Players")
        tourney_roles = self.bot.get_cog("Tourney Roles")

        # Check if state changed
        cogs_available = bool(known_players and tourney_roles)
        if cogs_available != self._cogs_available:
            if cogs_available:
                self.logger.info("Required cogs now available, functions resumed")
            else:
                self.logger.warning("Required cogs unavailable, functions paused")
            self._cogs_available = cogs_available

        if not cogs_available:
            return None, None

        # Wait for both cogs to be ready
        await known_players.wait_until_ready()
        await tourney_roles.wait_until_ready()

        return known_players, tourney_roles

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handle new member joins."""
        if member.bot:
            return

        known_players, tourney_roles = await self.get_required_cogs()
        if not known_players or not tourney_roles:
            return

        try:
            # Check if this is a known player
            player = await known_players.get_player_by_discord_id(str(member.id))
            if not player:
                if self.get_setting("debug_logging"):
                    self.logger.debug(f"Member {member} joined but is not a known player")
                return

            # Queue the member for role update
            await self.queue_role_update(member, "member join")

        except Exception as e:
            self.logger.error(f"Error handling member join for {member}: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Handle member updates, specifically role changes."""
        if before.roles == after.roles:
            return

        # Ignore if this is a bot-initiated update
        if after.id in self.bot_role_updates:
            if self.get_setting("debug_logging"):
                self.logger.debug(f"Ignoring bot-initiated role change for {after}")
            return

        known_players, tourney_roles = await self.get_required_cogs()
        if not known_players or not tourney_roles:
            return

        try:
            # Get verified role ID
            verified_role_id = tourney_roles.get_setting("verified_role_id")
            if not verified_role_id:
                return

            # Convert to int for comparison
            verified_role_id = int(verified_role_id)

            # Cancel any pending update task for this user
            user_id = str(after.id)
            if user_id in self.pending_updates:
                pending = self.pending_updates[user_id]
                if not pending['task'].done():
                    pending['task'].cancel()
                # Update final roles state
                pending['final_roles'] = set(r.id for r in after.roles)
                # Don't reset timer if changes are still coming in rapidly
                if (datetime.now() - pending['timer_start']).total_seconds() > self.debounce_delay:
                    pending['timer_start'] = datetime.now()
            else:
                # Create new pending update
                self.pending_updates[user_id] = {
                    'initial_roles': set(r.id for r in before.roles),
                    'final_roles': set(r.id for r in after.roles),
                    'timer_start': datetime.now(),
                    'task': asyncio.create_task(self.process_debounced_update(after, self.debounce_delay))
                }

        except Exception as e:
            self.logger.error(f"Error handling role update for {after}: {e}", exc_info=True)

    async def process_debounced_update(self, member: discord.Member, delay: float):
        """Process a debounced role update after waiting for changes to settle."""
        try:
            # Wait for the debounce delay
            await asyncio.sleep(delay)

            user_id = str(member.id)
            if user_id not in self.pending_updates:
                return

            pending = self.pending_updates[user_id]
            initial_roles = pending['initial_roles']
            final_roles = pending['final_roles']

            # Clean up pending update
            del self.pending_updates[user_id]

            # Get verified role status
            known_players, tourney_roles = await self.get_required_cogs()
            if not known_players or not tourney_roles:
                return

            verified_role_id = int(tourney_roles.get_setting("verified_role_id"))
            roles_config = tourney_roles.get_setting("roles_config", {})

            if not verified_role_id or not roles_config:
                return

            # Check verified role changes
            had_verified = verified_role_id in initial_roles
            has_verified = verified_role_id in final_roles

            if had_verified != has_verified:
                player = await known_players.get_player_by_discord_id(user_id)
                if not player:
                    if self.get_setting("debug_logging"):
                        self.logger.debug(f"Verified role changed for {member} but they are not a known player")
                    return

                # Queue for update if verified role was added
                if has_verified:
                    await self.queue_role_update(member, "verified role added")
                return

            # Only process other role changes if they have verified role
            if not has_verified:
                return

            # Check if any changed roles are tournament roles
            managed_role_ids = {int(config['id']) for config in roles_config.values()}
            role_changes = final_roles ^ initial_roles

            if any(role_id in managed_role_ids for role_id in role_changes):
                # Log the coalesced changes if debug logging is enabled
                if self.get_setting("debug_logging"):
                    added = final_roles - initial_roles
                    removed = initial_roles - final_roles
                    self.logger.debug(
                        f"Processing coalesced changes for {member}: "
                        f"Added: {added}, Removed: {removed}"
                    )
                await self.queue_role_update(member, "role change")

        except asyncio.CancelledError:
            # Task was cancelled, probably due to new changes
            pass
        except Exception as e:
            self.logger.error(f"Error processing debounced update for {member}: {e}")

    @commands.Cog.listener()
    async def on_bot_role_update_start(self, member_id: int):
        """Handle bot starting to update roles."""
        self.bot_role_updates.add(member_id)
        if self.get_setting("debug_logging"):
            self.logger.debug(f"Bot role update started for member {member_id}")

    @commands.Cog.listener()
    async def on_bot_role_update_end(self, member_id: int):
        """Handle bot finishing role update."""
        self.bot_role_updates.discard(member_id)
        if self.get_setting("debug_logging"):
            self.logger.debug(f"Bot role update completed for member {member_id}")

    async def ensure_verified_role(self, member: discord.Member) -> bool:
        """Ensure member has the verified role if they're a known player."""
        try:
            known_players, _ = await self.get_required_cogs()
            if not known_players:
                return False

            # Check if they're a known player
            player = await known_players.get_player_by_discord_id(str(member.id))
            if not player:
                return False

            # Get verified role ID from tourney roles cog
            tourney_roles = self.bot.get_cog("Tourney Roles")
            if not tourney_roles:
                return False

            verified_role_id = tourney_roles.get_setting("verified_role_id")
            if not verified_role_id:
                return True  # No verification required

            # Get the role object
            verified_role = member.guild.get_role(int(verified_role_id))
            if not verified_role:
                self.logger.warning(f"Verified role {verified_role_id} not found")
                return False

            # Add the role if they don't have it
            if verified_role not in member.roles:
                await member.add_roles(verified_role, reason="Known player verification")
                self.logger.info(f"Added verified role to {member}")
                return True

            return True

        except Exception as e:
            self.logger.error(f"Error ensuring verified role for {member}: {e}", exc_info=True)
            return False

    async def queue_role_update(self, member: discord.Member, trigger: str):
        """Add a member to the role update queue."""
        try:
            # Check cooldown
            cooldown = self.get_setting("cooldown_seconds")
            user_id = str(member.id)

            if user_id in self.recently_updated:
                last_update = next(d['time'] for d in self.recently_updated if d['id'] == user_id)
                if datetime.now() - last_update < timedelta(seconds=cooldown):
                    if self.get_setting("debug_logging"):
                        self.logger.debug(f"Skipping update for {member} - in cooldown")
                    return

            # Check queue size limit
            if self.update_queue.qsize() >= self.get_setting("queue_size_limit"):
                self.logger.warning("Update queue full, skipping new request")
                return

            # Ensure they have verified role first
            await self.ensure_verified_role(member)

            # Add to queue
            await self.update_queue.put({
                'member': member,
                'trigger': trigger,
                'time': datetime.now()
            })

            if self.get_setting("debug_logging"):
                self.logger.debug(f"Queued role update for {member} (trigger: {trigger})")

        except Exception as e:
            self.logger.error(f"Error queueing role update for {member}: {e}", exc_info=True)

    async def process_queue(self):
        """Process the role update queue."""
        await self.bot.wait_until_ready()
        await self.wait_until_ready()

        while not self.bot.is_closed():
            try:
                if not self.processing:
                    # Add default value of 5 seconds if setting is missing
                    interval = self.get_setting("process_interval", 5)
                    await asyncio.sleep(interval)
                    continue

                # Get next item from queue
                try:
                    item = await asyncio.wait_for(
                        self.update_queue.get(),
                        timeout=self.get_setting("process_interval", 5)
                    )
                except asyncio.TimeoutError:
                    continue

                member = item['member']
                trigger = item['trigger']

                try:
                    # Update the member's roles
                    tourney_roles = self.bot.get_cog("Tourney Roles")
                    if tourney_roles:
                        self.logger.info(f"Processing role update for {member} (trigger: {trigger})")
                        await tourney_roles.roles_update_user_command(None, member)

                        # Track the update
                        self.recently_updated.append({
                            'id': str(member.id),
                            'time': datetime.now()
                        })
                        self._last_update = datetime.now()

                except Exception as e:
                    self.logger.error(f"Error updating roles for {member}: {e}", exc_info=True)

                finally:
                    self.update_queue.task_done()

            except Exception as e:
                self.logger.error(f"Error in queue processor: {e}", exc_info=True)
                await asyncio.sleep(5)  # Wait before retrying

    @property
    def is_processing(self) -> bool:
        """Check if the queue processor is active."""
        return self.processing

    def start_processing(self):
        """Start processing the queue."""
        self.processing = True
        self.logger.info("Started queue processing")

    def stop_processing(self):
        """Stop processing the queue."""
        self.processing = False
        self.logger.info("Stopped queue processing")

    async def cog_unload(self):
        """Clean up when cog is unloaded."""
        # Cancel any pending debounced updates
        for pending in self.pending_updates.values():
            if not pending['task'].done():
                pending['task'].cancel()
        self.pending_updates.clear()

        # Clear bot role updates set
        self.bot_role_updates.clear()

        self.stop_processing()
        if self.update_task and not self.update_task.done():
            self.update_task.cancel()

        # Wait for any remaining items
        if not self.update_queue.empty():
            self.logger.warning(f"Unloading with {self.update_queue.qsize()} items in queue")

        await super().cog_unload()
        self.logger.info("TourneyRoleSupervisor unloaded")


async def setup(bot) -> None:
    await bot.add_cog(TourneyRoleSupervisor(bot))
