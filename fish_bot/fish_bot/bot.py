import logging
import os
import sys
import subprocess
import json
from collections import defaultdict

import discord
from discord.ext import commands
from discord.ext.commands import Context

from fish_bot import const, settings
from fish_bot.util import is_allowed_channel, is_allowed_user, UserUnauthorized, ChannelUnauthorized


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
            command_prefix=settings.prefix,
            intents=intents,
            case_insensitive=True,
        )
        """
        This creates custom bot variables so that we can access these variables in cogs more easily.

        For example, the config is available using the following code:
        - self.config # In this class
        - bot.config # In this file
        - self.bot.config # In cogs
        """
        self.logger = logger

    async def load_cogs(self) -> None:
        """
        The code in this function is executed whenever the bot starts.
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
        elif isinstance(error, ChannelUnauthorized):
            embed = discord.Embed(
                description="This channel isn't allowed to run this command!",
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

    async def async_cleanup(self):
        print("Cleaning up!")

    async def close(self):
        await self.async_cleanup()
        await super().close()

    async def on_ready(self):
        print("on_ready")

    async def on_connect(self):
        print("on_connect")

    async def on_resume(self):
        print("on_resume")

    async def on_disconnect(self):
        print("on_disconnect")


bot = DiscordBot()


"""Module functions"""


@bot.command()
@is_allowed_channel(const.helpers_channel_id, const.testing_channel_id, const.tourney_bot_channel_id)
@is_allowed_user(const.id_pog, const.id_fishy)
async def list_modules(ctx: Context):
    """Lists all cogs and their status of loading."""
    cog_list = commands.Paginator(prefix='', suffix='')
    cog_list.add_line('**✅ Succesfully loaded:**')
    for cog in bot.loaded_cogs:
        cog_list.add_line('- ' + cog)
    cog_list.add_line('**❌ Not loaded:**')
    for cog in bot.unloaded_cogs:
        cog_list.add_line('- ' + cog)
    for page in cog_list.pages:
        print(page)
        await ctx.send(page)


@bot.command()
@is_allowed_channel(const.helpers_channel_id, const.testing_channel_id, const.tourney_bot_channel_id)
@is_allowed_user(const.id_pog, const.id_fishy)
async def load(ctx: Context, cog):
    """Try and load the selected cog."""
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
        try:
            bot.unloaded_cogs.remove(cog)
        except ValueError:
            pass
        await ctx.send('✅ Module succesfully loaded.')


@bot.command()
@is_allowed_channel(const.helpers_channel_id, const.testing_channel_id, const.tourney_bot_channel_id)
@is_allowed_user(const.id_pog, const.id_fishy)
async def unload(ctx: Context, cog):
    if cog not in bot.loaded_cogs:
        return await ctx.send('💢 Module not loaded.')
    await bot.unload_extension('cogs.{}'.format((cog)))
    bot.loaded_cogs.remove(cog)
    bot.unloaded_cogs.append(cog)
    await ctx.send('✅ Module succesfully unloaded.')


@bot.command()
@is_allowed_channel(const.helpers_channel_id, const.testing_channel_id, const.tourney_bot_channel_id)
@is_allowed_user(const.id_pog, const.id_fishy)
async def reload(ctx: Context, cog):
    await unload(ctx, cog)
    await load(ctx, cog)


@bot.command()
@is_allowed_user(const.id_pog, const.id_fishy)
async def restart(ctx: Context, method: str = None):
    """Restart the bot service."""
    await ctx.send("Restarting service...")
    subprocess.run(["systemctl", "restart", "fish_bot"])


@bot.command()
@is_allowed_channel(const.helpers_channel_id, const.testing_channel_id, const.tourney_bot_channel_id)
async def stop(ctx: Context):
    """Stop the bot service."""
    await ctx.send(f"{ctx.author} requested a stop.  Stopping service...")
    user = await bot.get_user_info(const.id_fishy)
    await bot.send_message(user, f"Emergency stop command received by {ctx.author}.  Stopping service...")
    subprocess.run(["systemctl", "stop", "fish_bot"])


@bot.command()
@commands.is_owner()
async def pull_git(ctx: Context, method: str = None):
    await ctx.send("Attempting pull...")
    if method == "rebase":
        response = subprocess.check_output(["git", "pull", "thetower.lol", "main", "rebase"], cwd="/tourney", )
    else:
        response = subprocess.check_output(["git", "pull", "thetower.lol", "main"], cwd="/tourney", )
    await ctx.send(response.decode("utf-8"))


@bot.command()
@commands.is_owner()
async def say(ctx: Context, channelid: int, *, message: str):
    channel = bot.get_channel(channelid)
    await channel.send(message)


"""Settings functions"""


@bot.command()
@commands.is_owner()
async def load_settings(ctx: Context = None):
    if not os.path.isfile(f"{os.path.realpath(os.path.dirname(__file__))}/config.json"):
        sys.exit("'config.json' not found! Please add it and try again.")
    else:
        with open(f"{os.path.realpath(os.path.dirname(__file__))}/config.json") as file:
            if ctx:
                await ctx.send("Reading settings.")
            print("Reading settings.")
            bot.config = json.load(file)


@bot.command()
@commands.is_owner()
async def save_settings(ctx: Context = None):
    with open(f"{os.path.realpath(os.path.dirname(__file__))}/config.json", 'w+') as file:
        if ctx:
            await ctx.send("Saving settings.")
        print("Saving settings.")
        json.dump(bot.config, file)


@bot.command()
@commands.is_owner()
async def print_settings(ctx: Context = None):
    if ctx:
        await ctx.send(bot.config)
    print(bot.config)


bot.run(os.getenv("DISCORD_TOKEN"), log_level=logging.INFO)