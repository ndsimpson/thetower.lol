from functools import partial
from discord.ext import commands
from fish_bot.util import is_channel
from fish_bot.basecog import BaseCog


class Verification(BaseCog, name="Verification"):
    """Handles user verification by checking player ID submissions.

    Automatically reacts to messages in the verification channel with 👍🏼 or 👎🏼
    based on whether the message contains a valid player ID and an attachment.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot

    @commands.Cog.listener("on_message")
    async def check_verify_message(self, message):
        """Checks verification messages and adds appropriate reactions.

        Validates that the message contains a player ID (13-16 characters)
        and an attachment. Adds 👍🏼 if valid, 👎🏼 if invalid.
        """
        is_player_id_please_channel = partial(is_channel, id_=self.config.get_channel_id("helpers"))
        try:
            if is_player_id_please_channel(message.channel) and message.author.id != self.config.get_bot_id("towerbot"):
                if len(message.content) > 13 and len(message.content) < 17 and message.attachments:
                    await message.add_reaction("👍🏼")
                else:
                    await message.add_reaction("👎🏼")
        except Exception as exc:
            await message.channel.send(f"Something went terribly wrong, please debug me. \n\n {exc}")
            raise exc


async def setup(bot) -> None:
    await bot.add_cog(Verification(bot))
