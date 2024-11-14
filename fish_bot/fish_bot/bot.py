import logging
import os
import sys
import json
from collections import defaultdict

import discord
from discord.ext import commands
from discord.ext.commands import check, Context

from fish_bot import const


intents = discord.Intents.default()
intents.presences = True
intents.message_content = True
intents.members = True

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DiscordBot(commands.Bot):
    loaded_cogs = []
    unloaded_cogs = []
    config = defaultdict(list)

    def __init__(self) -> None:
        super().__init__(
            command_prefix='$$',
            intents=intents,
        )
        """
        This creates custom bot variables so that we can access these variables in cogs more easily.

        For example, The config is available using the following code:
        - self.config # In this class
        - bot.config # In this file
        - self.bot.config # In cogs
        """
        self.logger = logger

    async def load_cogs(self) -> None:
        """
        The code in this function is executed whenever the bot will start.
        """
        for file in os.listdir(f"{os.path.realpath(os.path.dirname(__file__))}/cogs"):
            if file.endswith(".py"):
                extension = file[:-3]
                try:
                    await self.load_extension(f"cogs.{extension}")
                    self.loaded_cogs.append(extension)
                    self.logger.info(f"Loaded extension '{extension}'")
                except Exception as e:
                    exception = f"{type(e).__name__}: {e}"
                    self.logger.error(
                        f"Failed to load extension {extension}\n{exception}"
                    )

    async def setup_hook(self) -> None:
        """
        This will just be executed when the bot starts the first time.
        """
        self.logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        self.logger.info("------")
        await self.load_cogs()

    async def on_command_error(self, context: Context, error) -> None:
        if isinstance(error, commands.NotOwner):
            embed = discord.Embed(
                description="You are not the owner of the bot!", color=0xE02B2B
            )
            await context.send(embed=embed)
            if context.guild:
                self.logger.warning(
                    f"{context.author} (ID: {context.author.id}) tried to execute an owner only command in the guild {context.guild.name} (ID: {context.guild.id}), but the user is not an owner of the bot."
                )
            else:
                self.logger.warning(
                    f"{context.author} (ID: {context.author.id}) tried to execute an owner only command in the bot's DMs, but the user is not an owner of the bot."
                )
        elif isinstance(error, commands.MissingPermissions):
            embed = discord.Embed(
                description="You are missing the permission(s) `"
                + ", ".join(error.missing_permissions)
                + "` to execute this command!",
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        elif isinstance(error, UserUnauthorized):
            embed = discord.Embed(
                description="You are not allowed to execute this command!",
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        elif isinstance(error, commands.BotMissingPermissions):
            embed = discord.Embed(
                description="I am missing the permission(s) `"
                + ", ".join(error.missing_permissions)
                + "` to fully perform this command!",
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                title="Error!",
                # We need to capitalize because the command arguments have no capital letter in the code and they are the first word in the error message.
                description=str(error).capitalize(),
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        else:
            raise error


bot = DiscordBot()


class UserUnauthorized(commands.CommandError):
    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)


"""Custom predicates"""


def in_any_channel(*channels):
    async def predicate(ctx: Context):
        return ctx.channel.id in channels
    return check(predicate)


def allowed_ids(*users):
    async def predicate(ctx: Context):
        if ctx.author.id not in users:
            raise UserUnauthorized(ctx.message.author)
        else:
            return True
    return check(predicate)


def guild_owner_only():
    async def predicate(ctx):
        return ctx.author == ctx.guild.owner  # checks if author is the owner
    return commands.check(predicate)


"""Module functions"""


@bot.command()
@in_any_channel(const.helpers_channel_id, const.testing_channel_id)
@allowed_ids(const.id_pog)
async def list_modules(ctx):
    '''Lists all cogs and their status of loading.'''
    cog_list = commands.Paginator(prefix='', suffix='')
    cog_list.add_line('**✅ Succesfully loaded:**')
    for cog in bot.loaded_cogs:
        cog_list.add_line('- ' + cog)
    cog_list.add_line('**❌ Not loaded:**')
    for cog in bot.unloaded_cogs:
        cog_list.add_line('- ' + cog)
    for page in cog_list.pages:
        await ctx.send(page)


@bot.command()
@in_any_channel(const.helpers_channel_id, const.testing_channel_id)
@allowed_ids(const.id_pog, const.id_fishy)
async def load(ctx, cog):
    '''Try and load the selected cog.'''
    if cog not in bot.unloaded_cogs:
        await ctx.send('⚠ WARNING: Module appears not to be found in the available modules list. Will try loading anyway.')
    if cog in bot.loaded_cogs:
        return await ctx.send('Cog already loaded.')
    try:
        await bot.load_extension('cogs.{}'.format(cog))
    except Exception as e:
        await ctx.send('**💢 Could not load module: An exception was raised. For your convenience, the exception will be printed below:**')
        await ctx.send('```{}\n{}```'.format(type(e).__name__, e))
    else:
        bot.loaded_cogs.append(cog)
        bot.unloaded_cogs.remove(cog)
        await ctx.send('✅ Module succesfully loaded.')


@bot.command()
@in_any_channel(const.helpers_channel_id, const.testing_channel_id)
@allowed_ids(const.id_pog, const.id_fishy)
async def unload(ctx, cog):
    if cog not in bot.loaded_cogs:
        return await ctx.send('💢 Module not loaded.')
    await bot.unload_extension('cogs.{}'.format((cog)))
    bot.loaded_cogs.remove(cog)
    bot.unloaded_cogs.append(cog)
    await ctx.send('✅ Module succesfully unloaded.')


@bot.command()
@in_any_channel(const.helpers_channel_id, const.testing_channel_id)
@allowed_ids(const.id_pog, const.id_fishy)
async def reload(ctx, cog):
    await unload(ctx, cog)
    await load(ctx, cog)


"""Settings functions"""


@bot.command()
async def load_settings(ctx):
    if not os.path.isfile(f"{os.path.realpath(os.path.dirname(__file__))}/config.json"):
        sys.exit("'config.json' not found! Please add it and try again.")
    else:
        with open(f"{os.path.realpath(os.path.dirname(__file__))}/config.json") as file:
            bot.config = json.load(file)


@bot.command()
async def save_settings(ctx):
    with open(f"{os.path.realpath(os.path.dirname(__file__))}/config.json") as file:
        json.dump(bot.config, file)


@bot.command()
async def print_settings(ctx):
    print(bot.config)


bot.run(os.getenv("DISCORD_TOKEN"), log_level=logging.INFO)