import sys
import math
import os
import logging
from typing import Dict, Any, Optional, List, Set, Union

from functools import partial, wraps
from asyncstdlib.functools import lru_cache
from asgiref.sync import sync_to_async

from discord import Client, Guild, Role, Member, NotFound, HTTPException
from discord.ext.commands import check, Context
from discord.ext import commands
# https://discordpy.readthedocs.io/en/stable/api.html

from asyncio import sleep

import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
django.setup()

from dtower.sus.models import KnownPlayer, SusPerson
from dtower.tourney_results.models import PatchNew as Patch

from fish_bot import const, settings


@lru_cache(maxsize=1)  # Changed decorator
async def get_tower(client: Client) -> Guild:
    """We only want to fetch the server once."""
    try:
        return await client.fetch_guild(const.guild_id)
    except NotFound:
        raise RuntimeError(f"Could not find guild with ID {const.guild_id}")


@lru_cache(maxsize=1)  # Changed decorator
async def get_verified_role(client: Client) -> Role:
    """We only want to fetch the verified role."""
    guild = await get_tower(client)
    role = guild.get_role(const.verified_role_id)
    if role is None:
        raise RuntimeError(f"Could not find verified role with ID {const.verified_role_id}")
    return role


# Function to invalidate caches if needed
async def invalidate_caches():
    get_tower.cache_clear()
    get_verified_role.cache_clear()


async def get_all_members(client: Client, members: Dict[int, Dict[str, Any]],
                          verbose: bool = False, retry_attempts: int = 3) -> None:
    """
    Fetch all guild members with error handling and progress tracking.

    Args:
        client: Discord client instance
        members: Dictionary to store member information
        verbose: Whether to print progress messages
        retry_attempts: Number of retry attempts for failed fetches
    """
    guild = await get_tower(client)
    total_members = guild.member_count
    processed = 0

    if verbose:
        print(f"Fetching {total_members} members...")

    try:
        async for member in guild.fetch_members(limit=settings.memberlimit):
            for attempt in range(retry_attempts):
                try:
                    remember_member(member, members)
                    processed += 1

                    if verbose and processed % 100 == 0:  # Progress update every 100 members
                        print(f"Processed {processed}/{total_members} members...")
                    break

                except Exception as e:
                    if attempt == retry_attempts - 1:  # Last attempt
                        logging.error(f"Failed to process member {member.id}: {str(e)}")
                    else:
                        await sleep(1)  # Wait before retry
                        continue

    except HTTPException as e:
        logging.error(f"HTTP error while fetching members: {str(e)}")
        raise
    except Exception as e:
        logging.error(f"Unexpected error while fetching members: {str(e)}")
        raise

    if verbose:
        print(f"Completed processing {processed}/{total_members} members")


def remember_member(member: Member, members: Dict[int, Dict[str, Any]]) -> None:
    """Store member information in the members dictionary."""
    try:
        members[member.id] = {
            'name': member.name,
            'nick': member.nick,
            'roles': member.roles,
            'joined_at': member.joined_at
        }
    except AttributeError as e:
        logging.error(f"Failed to access member attributes for {member.id}: {str(e)}")
        raise


def forget_member(member: Member, members: Dict[int, Dict[str, Any]]) -> None:
    del members[member.id]


def remember_member_roles(member: Member, members: Dict[int, Dict[str, Any]]) -> None:
    """Update member roles, creating the member entry if it doesn't exist."""
    if member.id not in members:
        members[member.id] = {'name': member.name, 'nick': member.nick, 'roles': member.roles}
    else:
        members[member.id]['roles'] = member.roles


def check_known_player(discordid: int) -> bool:
    knownplayer = KnownPlayer.objects.filter(discord_id=discordid, approved=True)
    return knownplayer.count() > 0


def set_known_member(member: Member, members: Dict[int, Dict[str, Any]]) -> None:
    members[member.id]['known'] = True


def get_player_id(discordid: int) -> Optional[List[int]]:
    try:
        b = KnownPlayer.objects.get(discord_id=discordid)
        playerids = list(b.ids.all().values_list('id', flat=True))
    except KnownPlayer.DoesNotExist:
        playerids = None
    return playerids


def check_sus_player(discordid: int) -> Union[str, bool]:
    playerid = get_player_id(discordid)
    if playerid is None:
        return "N/A"
    susplayer = SusPerson.objects.filter(sus=True, player_id__in=playerid)
    return susplayer.count() > 0


async def get_latest_patch():
    patch = sorted(await sync_to_async(Patch.objects.all, thread_sensitive=True)())[-1]
    return patch


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
    """Exception raised when a channel is not authorized to use a command."""

    def __init__(self, channel, message: Optional[str] = None) -> None:
        self.channel = channel
        self.message = message or f"Channel {channel.name} (ID: {channel.id}) is not authorized"
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class UserUnauthorized(commands.CommandError):
    """Exception raised when a user is not authorized to use a command."""

    def __init__(self, user, message: Optional[str] = None) -> None:
        self.user = user
        self.message = message or f"User {user.name}#{user.discriminator} (ID: {user.id}) is not authorized"
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message
