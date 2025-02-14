import sys
import math
import os

from functools import partial
from asyncstdlib.functools import lru_cache
from asgiref.sync import sync_to_async

from discord.ext.commands import check, Context
from discord.ext import commands
# https://discordpy.readthedocs.io/en/stable/api.html

import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
django.setup()

from dtower.sus.models import KnownPlayer, SusPerson
from dtower.tourney_results.models import PatchNew as Patch

from fish_bot import const, settings


@lru_cache
async def get_tower(client):
    """We only want to fetch the server once."""
    return await client.fetch_guild(const.guild_id)


@lru_cache
async def get_verified_role(client):
    """We only want to fetch the verified role."""
    return (await get_tower(client)).get_role(const.verified_role_id)


async def get_all_members(client, members):
    guild = await get_tower(client)
    print("Getting all members")
    async for member in guild.fetch_members(limit=settings.memberlimit):
        remember_member(member, members)
    print("Got all members")


def remember_member(member, members):
    members[member.id] = {'name' : member.name, 'nick' : member.nick, 'roles' : member.roles}


def forget_member(member, members):
    del members[member.id]


def remember_member_roles(member, members):
    members[member.id]['roles'] = member.roles


def check_known_player(discordid):
    knownplayer = KnownPlayer.objects.filter(discord_id=discordid, approved=True)
    return True if knownplayer.count() > 0 else False


def set_known_member(member, members):
    members[member.id]['known'] = True


def get_player_id(discordid):
    try:
        b = KnownPlayer.objects.get(discord_id=discordid)
        playerids = list(b.ids.all().values_list('id', flat=True))
    except KnownPlayer.DoesNotExist:
        playerids = None
    return playerids


def check_sus_player(discordid):
    playerid = get_player_id(discordid)
    if playerid is None:
        return "N/A"
    else:
        susplayer = SusPerson.objects.filter(sus=True, player_id__in=playerid)
    return True if susplayer.count() > 0 else False


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
            print("User not in authorized list.")
            # await ctx.send("User is unauthorized for this command.")
            raise UserUnauthorized(ctx.message.author)
        else:
            return True
    return check(predicate)


def is_guild_owner():
    """Check if the user id is the guild owner."""
    async def predicate(ctx: Context):
        if ctx.author == ctx.guild.owner:   # checks if author is the owner
            print("User is not the guild owner.")
            # await ctx.send("User is unauthorized for this command.")
            raise UserUnauthorized(ctx.message.author)
        else:
            return True
    return commands.check(predicate)


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

def get_size(obj, seen=None):
    """Recursively finds size of objects"""
    size = sys.getsizeof(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    # Important mark as seen *before* entering recursion to gracefully handle
    # self-referential objects
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum([get_size(v, seen) for v in obj.values()])
        size += sum([get_size(k, seen) for k in obj.keys()])
    elif hasattr(obj, '__dict__'):
        size += get_size(obj.__dict__, seen)
    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes, bytearray)):
        size += sum([get_size(i, seen) for i in obj])
    return size


def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


class ChannelUnauthorized(commands.CommandError):
    """Exception raised when a channel is not authorized to use a command."""
    def __init__(self, channel, *args, **kwargs):
        self.channel = channel
        super().__init__(*args, **kwargs)


class UserUnauthorized(commands.CommandError):
    """Exception raised when a user is not authorized to use a command."""
    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)