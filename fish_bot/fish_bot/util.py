# Standard library imports
import logging
import math
import os
import sys
from asyncio import sleep
from enum import Enum, auto
from functools import partial, wraps
from typing import Any, Dict, List, Optional, Set, Union

# Third-party imports
from asgiref.sync import sync_to_async
from asyncstdlib import lru_cache
from discord import (
    Client,
    Guild,
    HTTPException,
    Member,
    NotFound,
    Role,
    TextChannel,
    User
)
from discord.ext import commands
from discord.ext.commands import Context, check


def init_django() -> None:
    """Initialize Django ORM with error handling."""
    try:
        import django
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
        django.setup()
        logging.info("Django initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize Django: {e}")
        raise RuntimeError(f"Django initialization failed: {e}") from e


# Initialize Django
init_django()

# Local application imports
from dtower.sus.models import KnownPlayer, SusPerson
from dtower.tourney_results.models import PatchNew as Patch
from fish_bot import const, settings


@lru_cache(maxsize=1)
async def get_tower(client: Client) -> Guild:
    """Fetch and cache the guild instance."""
    try:
        guild = await client.fetch_guild(const.guild_id)
        logging.debug(f"Guild cached: {guild.name} (ID: {guild.id})")
        return guild
    except NotFound:
        logging.error(f"Guild not found: ID {const.guild_id}")
        raise RuntimeError(f"Could not find guild with ID {const.guild_id}")
    except HTTPException as e:
        logging.error(f"Failed to fetch guild: {e}")
        raise RuntimeError(f"Failed to fetch guild: {e}") from e


@lru_cache(maxsize=1)
async def get_verified_role(client: Client) -> Role:
    """Fetch and cache the verified role."""
    try:
        guild = await get_tower(client)
        role = guild.get_role(const.verified_role_id)
        if role is None:
            logging.error(f"Verified role not found: ID {const.verified_role_id}")
            raise RuntimeError(f"Could not find verified role with ID {const.verified_role_id}")
        logging.debug(f"Role cached: {role.name} (ID: {role.id})")
        return role
    except Exception as e:
        logging.error(f"Failed to fetch verified role: {e}")
        raise RuntimeError(f"Failed to fetch verified role: {e}") from e


# Function to invalidate caches if needed
async def invalidate_caches():
    """Clear all cached data with logging."""
    try:
        await get_tower.cache_clear()
        await get_verified_role.cache_clear()
        logging.info("Cache invalidated successfully")
    except Exception as e:
        logging.error(f"Failed to invalidate cache: {e}")
        raise RuntimeError(f"Failed to invalidate cache: {e}") from e


async def get_all_members(
    client: Client,
    members: Dict[int, Dict[str, Any]],
    verbose: bool = False,
    retry_attempts: int = 3,
    batch_size: int = 1000
) -> tuple[int, int]:
    """
    Fetch all guild members with error handling and progress tracking.

    Args:
        client: Discord client instance
        members: Dictionary to store member information
        verbose: Whether to enable detailed logging
        retry_attempts: Number of retry attempts for failed fetches
        batch_size: Number of members to process in each batch

    Returns:
        tuple[int, int]: (Successfully processed members, Failed members)
    """
    guild = await get_tower(client)
    total_members = guild.member_count
    processed = failed = current_batch = 0

    logger = logging.getLogger(__name__)
    log_level = logging.INFO if verbose else logging.DEBUG

    logger.log(log_level, f"Starting fetch of {total_members} members...")

    try:
        async for member in guild.fetch_members(limit=settings.memberlimit):
            current_batch += 1

            for attempt in range(retry_attempts):
                try:
                    remember_member(member, members)
                    processed += 1

                    if verbose and processed % 100 == 0:
                        logger.info(f"Processed {processed}/{total_members} members...")
                    break

                except AttributeError as e:
                    # Don't retry on attribute errors - member data is invalid
                    logger.error(f"Invalid member data for {member.id}: {e}")
                    failed += 1
                    break

                except Exception as e:
                    if attempt == retry_attempts - 1:
                        logger.error(f"Failed to process member {member.id} after {retry_attempts} attempts: {e}")
                        failed += 1
                    else:
                        # Exponential backoff
                        await sleep(2 ** attempt)
                        continue

            # Rate limit protection
            if current_batch >= batch_size:
                await sleep(1)
                current_batch = 0

    except HTTPException as e:
        logger.error(f"Discord API error while fetching members: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error while fetching members: {e}")
        raise

    logger.log(
        log_level,
        f"Completed member fetch: {processed} processed, {failed} failed"
    )

    return processed, failed


def _create_member_dict(member: Member) -> Dict[str, Any]:
    """Create a standardized member dictionary."""
    return {
        'name': member.name,
        'nick': member.nick,
        'roles': member.roles,
        'joined_at': member.joined_at
    }


def remember_member(member: Member, members: Dict[int, Dict[str, Any]]) -> None:
    """
    Store member information in the members dictionary.

    Args:
        member: Discord member to store
        members: Dictionary to store member information

    Raises:
        AttributeError: If member attributes cannot be accessed
    """
    try:
        members[member.id] = _create_member_dict(member)
    except AttributeError as e:
        logging.error(f"Failed to access member attributes for {member.id}: {str(e)}")
        raise


def forget_member(member: Member, members: Dict[int, Dict[str, Any]]) -> None:
    """
    Remove member information from the members dictionary.

    Args:
        member: Discord member to remove
        members: Dictionary storing member information

    Raises:
        KeyError: If member is not in the dictionary
    """
    try:
        del members[member.id]
        logging.debug(f"Removed member {member.name} (ID: {member.id}) from memory")
    except KeyError as e:
        logging.error(f"Failed to remove member {member.id}: Member not found")
        logging.error(f"Full error message: {str(e)}")
        raise


def remember_member_roles(member: Member, members: Dict[int, Dict[str, Any]]) -> None:
    """
    Update member roles, creating the member entry if it doesn't exist.

    Args:
        member: Discord member to update
        members: Dictionary storing member information

    Raises:
        AttributeError: If member attributes cannot be accessed
    """
    try:
        if member.id not in members:
            members[member.id] = _create_member_dict(member)
        else:
            members[member.id]['roles'] = member.roles
            members[member.id]['name'] = member.name  # Update name in case it changed
            members[member.id]['nick'] = member.nick  # Update nickname in case it changed
        logging.debug(f"Updated roles for member {member.name} (ID: {member.id})")
    except AttributeError as e:
        logging.error(f"Failed to access member attributes for {member.id}: {str(e)}")
        raise


@lru_cache(maxsize=1000)
async def check_known_player(discordid: int) -> bool:
    """
    Check if a player is known and approved.

    Args:
        discordid: Discord ID to check

    Returns:
        bool: True if player exists and is approved

    Raises:
        RuntimeError: If database query fails
    """
    logger = logging.getLogger(__name__)

    try:
        # Wrap query in sync_to_async
        is_known = await sync_to_async(
            lambda: KnownPlayer.objects.filter(
                discord_id=discordid,
                approved=True
            ).exists(),  # More efficient than count() > 0
            thread_sensitive=True
        )()

        logger.debug(f"Known player check for {discordid}: {is_known}")
        return is_known

    except Exception as e:
        logger.error(f"Database error checking known player {discordid}: {e}")
        raise RuntimeError(f"Failed to check known player status: {e}") from e


def set_known_member(member: Member, members: Dict[int, Dict[str, Any]]) -> None:
    """
    Mark a member as known in the members dictionary.

    Args:
        member: Discord member to mark as known
        members: Dictionary storing member information

    Raises:
        KeyError: If member is not in dictionary and cannot be created
        AttributeError: If member attributes cannot be accessed
    """
    logger = logging.getLogger(__name__)

    try:
        if member.id not in members:
            members[member.id] = _create_member_dict(member)

        members[member.id]['known'] = True
        logger.debug(f"Marked member {member.name} (ID: {member.id}) as known")

    except (KeyError, AttributeError) as e:
        logger.error(f"Failed to set known status for member {member.id}: {str(e)}")
        raise


async def get_player_id(discordid: int) -> Optional[List[int]]:
    """
    Get player IDs associated with a Discord ID.

    Args:
        discordid: Discord user ID to look up

    Returns:
        Optional[List[int]]: List of player IDs if found, None if not found

    Raises:
        RuntimeError: If database query fails
    """
    logger = logging.getLogger(__name__)

    try:
        # Wrap the entire query in sync_to_async
        playerids = await sync_to_async(
            lambda: list(
                KnownPlayer.objects.filter(discord_id=discordid)
                .values_list('ids__id', flat=True)
                .distinct()
            ),
            thread_sensitive=True
        )()

        if not playerids:
            logger.debug(f"No player IDs found for Discord ID: {discordid}")
            return None

        logger.debug(f"Found {len(playerids)} player IDs for Discord ID: {discordid}")
        return playerids

    except Exception as e:
        logger.error(f"Database error while fetching player IDs for {discordid}: {e}")
        raise RuntimeError(f"Failed to fetch player IDs: {e}") from e


class SuspicionStatus(Enum):
    """Enum for player suspicion status"""
    UNKNOWN = auto()  # Player not found
    CLEAR = auto()    # Player found, not suspicious
    SUSPICIOUS = auto()  # Player found, suspicious


@lru_cache(maxsize=1000)
def check_sus_player(discordid: int) -> SuspicionStatus:
    """
    Check if a player is marked as suspicious.

    Args:
        discordid: Discord ID of the player to check

    Returns:
        SuspicionStatus: Player's suspicion status

    Note:
        Results are cached for performance. Use invalidate_caches() to clear.
    """
    logger = logging.getLogger(__name__)

    try:
        playerid = get_player_id(discordid)
        if playerid is None:
            logger.debug(f"No known player found for Discord ID: {discordid}")
            return SuspicionStatus.UNKNOWN

        is_suspicious = SusPerson.objects.filter(
            sus=True,
            player_id__in=playerid
        ).exists()

        status = SuspicionStatus.SUSPICIOUS if is_suspicious else SuspicionStatus.CLEAR
        logger.debug(f"Suspicion check for {discordid}: {status.name}")
        return status

    except Exception as e:
        logger.error(f"Error checking suspicion status for {discordid}: {e}")
        return SuspicionStatus.UNKNOWN


async def get_latest_patch() -> Patch:
    """
    Fetch the most recent patch from database.

    Returns:
        Patch: Latest patch object

    Raises:
        ValueError: If no patches exist
        RuntimeError: If database query fails
    """
    try:
        # Use order_by for database-side sorting and limit for efficiency
        latest_patch = await sync_to_async(
            lambda: Patch.objects.order_by('-id').first(),
            thread_sensitive=True
        )()

        if latest_patch is None:
            logging.error("No patches found in database")
            raise ValueError("No patches available")

        logging.debug(f"Retrieved latest patch: {latest_patch}")
        return latest_patch

    except Exception as e:
        logging.error(f"Failed to fetch latest patch: {e}")
        raise RuntimeError(f"Database error while fetching latest patch: {e}") from e


"""Custom discord predicates"""


def is_allowed_channel(*default_channels: int, default_users=None, allow_anywhere=False):
    """
    Allow command in specific channels or anywhere for specific users:
        @is_allowed_channel(channel_id1, channel_id2, default_users=[user_id1, user_id2])

    Allow command in any channel for specified users:
        @is_allowed_channel(default_users=[user_id1, user_id2], allow_anywhere=True)
    """
    if default_users is None:
        default_users = []

    def decorator(func):
        @wraps(func)
        async def wrapper(ctx: Context, *args, **kwargs):
            command_name = ctx.command.name
            command_parent = ctx.command.parent
            full_command = f"{command_parent.name} {command_name}" if command_parent else command_name

            # Get command config or create default structure
            command_config = settings.COMMAND_CHANNEL_MAP.get(full_command, {
                "channels": {chan: list(default_users) for chan in default_channels},
                "default_users": list(default_users)
            })

            channel_id = ctx.channel.id
            user_id = ctx.author.id

            # Check channel authorization unless allow_anywhere is True
            if not allow_anywhere:
                allowed_channels = set(command_config["channels"].keys())
                if channel_id not in allowed_channels:
                    ctx.bot.logger.warning(
                        f"Command '{full_command}' blocked - wrong channel. "
                        f"User: {ctx.author} (ID: {ctx.author.id}), "
                        f"Channel: {ctx.channel} (ID: {ctx.channel.id})"
                    )
                    raise ChannelUnauthorized(ctx.channel)

            # Check user authorization
            channel_allowed_users = set(command_config["channels"].get(channel_id, []))
            default_allowed_users = set(command_config.get("default_users", []))

            if not (user_id in channel_allowed_users or user_id in default_allowed_users):
                ctx.bot.logger.warning(
                    f"Command '{full_command}' blocked - unauthorized user. "
                    f"User: {ctx.author} (ID: {ctx.author.id}), "
                    f"Channel: {ctx.channel} (ID: {ctx.channel.id})"
                )
                raise UserUnauthorized(ctx.author)

            # Execute wrapped function if all checks pass
            return await func(ctx, *args, **kwargs)

        return wrapper
    return decorator


def is_allowed_user(*users):
    """Check if the user id is in the list of allowed users."""
    async def predicate(ctx: Context):
        if ctx.author.id not in users:
            ctx.bot.logger.warning(f"Unauthorized user attempt: {ctx.author} (ID: {ctx.author.id})")
            raise UserUnauthorized(ctx.author)
        return True
    return check(predicate)


def is_guild_owner():
    """
    Check if the user is the guild owner.
    Must be used in guild context.

    Raises:
        CommandError: If used outside guild or author/owner not found
        UserUnauthorized: If user is not guild owner
        HTTPException: If Discord API request fails
    """
    async def predicate(ctx: Context):
        if not ctx.guild:
            raise commands.CommandError("This command can only be used in a guild")

        if not ctx.author:
            raise commands.CommandError("Could not determine command author")

        try:
            # Fetch guild to ensure we have latest owner info
            guild = await ctx.guild.fetch()

            if ctx.author != guild.owner:
                ctx.bot.logger.warning(
                    f"Non-owner command attempt: {ctx.author} "
                    f"(ID: {ctx.author.id})"
                )
                raise UserUnauthorized(ctx.author)

            return True

        except HTTPException as e:
            ctx.bot.logger.error(f"Failed to fetch guild info: {e}")
            raise commands.CommandError("Unable to verify guild ownership") from e

    return check(predicate)


def is_channel(channel, id_):
    """Check if the channel id is the same as the given id."""
    return channel.id == id_


is_top1_channel = partial(is_channel, id_=const.top1_channel_id)
is_top50_channel = partial(is_channel, id_=const.top50_channel_id)
is_meme_channel = partial(is_channel, id_=const.meme_channel_id)
is_testing_channel = partial(is_channel, id_=const.testing_channel_id)
is_helpers_channel = partial(is_channel, id_=const.helpers_channel_id)
is_player_id_please_channel = partial(is_channel, id_=const.verify_channel_id)


## Bot memory check utilities

def get_size(obj: Any, seen: Optional[Set[int]] = None, depth: int = 0, max_depth: int = 100) -> int:
    """
    Recursively finds size of objects with safety limits and circular reference handling.

    Args:
        obj: Object to measure
        seen: Set of seen object ids
        depth: Current recursion depth
        max_depth: Maximum recursion depth

    Returns:
        int: Total size in bytes
    """
    # Check recursion depth
    if depth >= max_depth:
        return 0

    # Initialize seen set
    if seen is None:
        seen = set()

    # Get base size
    try:
        size = sys.getsizeof(obj)
    except TypeError:
        return 0

    # Check for already seen objects
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    seen.add(obj_id)

    # Handle different types
    if isinstance(obj, dict):
        size += sum(get_size(v, seen, depth + 1, max_depth) for v in obj.values())
        size += sum(get_size(k, seen, depth + 1, max_depth) for k in obj.keys())
    elif hasattr(obj, '__dict__'):
        size += get_size(obj.__dict__, seen, depth + 1, max_depth)
    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes, bytearray)):
        try:
            size += sum(get_size(i, seen, depth + 1, max_depth) for i in obj)
        except (TypeError, AttributeError):
            pass

    return size


def convert_size(size_bytes: Union[int, float]) -> str:
    """
    Convert bytes to human readable string.

    Args:
        size_bytes: Number of bytes to convert

    Returns:
        str: Human readable size string (e.g., "1.23 MB")

    Raises:
        TypeError: If size_bytes is not a number
        ValueError: If size_bytes is infinite or NaN
    """
    if not isinstance(size_bytes, (int, float)):
        raise TypeError("size_bytes must be a number")

    if isinstance(size_bytes, float):
        if math.isnan(size_bytes) or math.isinf(size_bytes):
            raise ValueError("size_bytes cannot be NaN or infinite")

    # Handle negative values
    if size_bytes < 0:
        return f"-{convert_size(abs(size_bytes))}"

    if size_bytes == 0:
        return "0B"

    size_units = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")

    try:
        # Calculate magnitude using log, handle potential math domain error
        if size_bytes > 1:
            magnitude = min(math.floor(math.log(size_bytes, 1024)), len(size_units) - 1)
        else:
            magnitude = 0

        # Calculate divisor with safety check
        divisor = math.pow(1024, magnitude)
        if divisor == 0 or math.isinf(divisor):
            return f"{size_bytes}B"

        # Calculate final value with rounding
        value = size_bytes / divisor
        if value >= 1000:
            magnitude += 1
            value /= 1024.0

        # Format with proper precision
        if value < 10:
            formatted = f"{value:.2f}"
        elif value < 100:
            formatted = f"{value:.1f}"
        else:
            formatted = f"{int(round(value))}"

        return f"{formatted} {size_units[magnitude]}"

    except (ValueError, OverflowError, ZeroDivisionError):
        # Fallback for any calculation errors
        return f"{size_bytes}B"


class ChannelUnauthorized(commands.CommandError):
    """
    Exception raised when a channel is not authorized to use a command.

    Attributes:
        channel: The unauthorized Discord channel
        message: Optional custom error message
    """

    def __init__(self, channel: TextChannel, message: Optional[str] = None) -> None:
        self.channel = channel
        # Handle case where channel attributes might be inaccessible
        channel_name = getattr(channel, 'name', 'Unknown')
        self.message = message or f"Channel {channel_name} (ID: {channel.id}) is not authorized"
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class UserUnauthorized(commands.CommandError):
    """
    Exception raised when a user is not authorized to use a command.

    Attributes:
        user: The unauthorized Discord user/member
        message: Optional custom error message
    """

    def __init__(self, user: Union[Member, User], message: Optional[str] = None) -> None:
        self.user = user
        # Handle users without discriminator (Discord change)
        display_name = getattr(user, 'global_name', None) or user.name
        self.message = message or f"User {display_name} (ID: {user.id}) is not authorized"
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message
