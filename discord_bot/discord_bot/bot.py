import asyncio
import logging
import os
from datetime import datetime

import discord
import django
from discord.ext import tasks

from discord_bot import const

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
django.setup()

from discord_bot.add_roles import handle_adding
from discord_bot.util import get_tower, is_testing_channel

semaphore = asyncio.Semaphore(1)

intents = discord.Intents.default()
intents.presences = True
intents.message_content = True
intents.members = True

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    logging.info(f"We have logged in as {client.user}")

    if not quarter_hour_tasks.is_running():
        quarter_hour_tasks.start()


@client.event
async def on_message(message: discord.Message) -> None:
    try:
        if is_testing_channel(message.channel) and message.content.startswith("!add_roles"):
            try:
                command, argument = message.content.split()

                if len(argument) < 10:
                    discord_ids = None
                    limit = int(argument)
                else:
                    discord_ids = [int(argument)]
                    limit = None
            except Exception:
                limit = None
                discord_ids = None

            async with semaphore:
                await handle_adding(
                    client,
                    limit=limit,
                    discord_ids=discord_ids,
                    channel=message.channel,
                    debug_channel=message.channel,
                    verbose=True,
                )

    except discord.DiscordException as exc:
        await message.channel.send(f"😱😱😱 Discord API error occurred: {exc}")
        raise exc
    except Exception as exc:
        await message.channel.send(f"😱😱😱 Unexpected error occurred: {exc}")
        logger.exception("Unexpected error in message handler")
        raise exc


@tasks.loop(minutes=1)
async def quarter_hour_tasks():
    logging.debug(datetime.now())
    minute = datetime.now().minute
    # seconds = datetime.now().second
    # wait = 59 - seconds
    wait = 0  # skip waiting for now

    if minute == 15:
        logging.info("running handle_roles_scheduled()")
        await handle_roles_scheduled()

    if wait > 0 & wait < 60:
        logging.debug(f"waiting {wait} seconds")
        await asyncio.sleep(wait)
    else:
        logging.debug("We're at 0 so no wait needed.")
    logging.debug(f"Minute: {minute}")


@quarter_hour_tasks.before_loop
async def quarter_hour_tasks_scheduled():
    now = datetime.now()
    logging.info(f"Started role bot at {now}")
    future = datetime(now.year, now.month, now.day, now.hour, now.minute + 1)
    delta = (future - now).total_seconds()
    logging.info(f"Syncing up the quarter hour tasks loop.  Sleeping {delta} seconds.")
    await asyncio.sleep(delta)


async def handle_roles_scheduled():
    logging.info(f"Started role application at {datetime.now()}")
    async with semaphore:
        try:
            tower = await get_tower(client)
            channel = await client.fetch_channel(const.role_log_channel_id)
            test_channel = await tower.fetch_channel(const.testing_channel_id)

            try:
                await handle_adding(client, limit=None, channel=channel, debug_channel=test_channel, verbose=False)
            except Exception as e:
                await test_channel.send(f"😱😱😱 \n\n {e}")
                logging.exception(e)
        except Exception as e:
            print("Top level exception")
            logging.exception(e)


client.run(os.getenv("DISCORD_TOKEN"), log_level=logging.INFO)
