import asyncio
import logging
import os
import sys

import django
import discord
from discord.ext import commands

from discord_bot import const
from discord_bot.add_roles import handle_adding
from discord_bot.util import in_any_channel

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
django.setup()

semaphore = asyncio.Semaphore(1)

intents = discord.Intents.default()
intents.presences = True
intents.message_content = True
intents.members = True

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


bot = commands.Bot(command_prefix='$$', intents=intents)


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')


@bot.command(name="add_roles", help="Manually apply roles to one or more discord ids.")
@commands.has_any_role(const.jrmods_role_id, const.mods_role_id, const.headmods_role_id)
@in_any_channel(const.helpers_channel_id)
async def add_roles(ctx, *, discordid: str = commands.parameter(description="One or more discord ids seperated by spaces OR 'all'")):
    print(ctx.channel)
    allowed_IDs = [const.id_pog]
    if ctx.author.id not in allowed_IDs:
        ctx.send("I'm afraid I can't do that, Dave.")
        print("Unauthorized user")
        return

    if discordid == "all":
        discordids = None
        print("All ids")
    else:
        discordids = discordid.split()
        print(discordid.split())

    async with semaphore:
        await handle_adding(
            bot,
            limit=None,
            discord_ids=discordids,
            channel=ctx.channel,
            debug_channel=ctx.channel,
            verbose=True,
        )


@add_roles.error
async def add_roles_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        print("Invalid Channel")


bot.run(os.getenv("DISCORD_TOKEN"), log_level=logging.INFO)
