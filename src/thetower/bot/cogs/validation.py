
import logging
from discord.ext import commands
from functools import partial
try:
    from ..utils import is_channel
except ImportError:
    def is_channel(channel, id_):
        return getattr(channel, 'id', None) == id_
from thetower.backend.sus.models import KnownPlayer, PlayerId
from thetower.backend.tourney_results.models import Injection
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


class ValidationCog(commands.Cog):

    def _create_or_update_player(self, discord_id, author_name, player_id):
        try:
            player, created = KnownPlayer.objects.get_or_create(
                discord_id=discord_id, defaults=dict(approved=True, name=author_name)
            )

            # First, set all existing PlayerIds for this player to non-primary
            PlayerId.objects.filter(player_id=player.id).update(primary=False)

            # Then create/update the new PlayerID as primary
            player_id_obj, player_id_created = PlayerId.objects.update_or_create(
                id=player_id, player_id=player.id, defaults=dict(primary=True)
            )

            # Return simple values instead of Django model instances to avoid lazy evaluation
            return {
                'player_id': player.id,
                'player_name': player.name,
                'discord_id': player.discord_id,
                'created': created
            }
        except Exception as exc:
            raise exc

    def _create_injection(self, text, user_id):
        return Injection.objects.create(text=text, user=user_id)

    def __init__(self, bot):
        self.bot = bot
        self.config = getattr(bot, 'config', None)

    @staticmethod
    def only_made_of_hex(text: str) -> bool:
        hex_digits = set("0123456789abcdef")
        contents = set(text.strip().lower())
        return contents | hex_digits == hex_digits

    @staticmethod
    def hamming_distance(s1: str, s2: str) -> float:
        if len(s1) != len(s2):
            return 1.0
        return sum(c1 != c2 for c1, c2 in zip(s1, s2)) / len(s1)

    async def validate_player_id(self, message):
        # Ignore certain users (configurable)
        ignored_ids = [
            self.config.get_user_id("pog") if self.config else None,
            self.config.get_user_id("susjite") if self.config else None,
            self.config.get_bot_id("fishy") if self.config else None,
            self.config.get_bot_id("towerbot") if self.config else None,
        ]
        if message.author.id in ignored_ids:
            return

        try:
            is_hex = self.only_made_of_hex(message.content)
            content_len = len(message.content)
            has_attachments = bool(message.attachments)
            if 13 < content_len < 17 and has_attachments and is_hex:
                image_bytes = await message.attachments[0].read()
                # Optionally, add OCR check here
                # if not (await self.check_image(message.content, image_bytes)):
                #     await message.add_reaction("⁉️")
                #     await asyncio.sleep(1)
                #     await message.add_reaction("🖼️")
                #     print("[validate_player_id] OCR check failed.")
                #     return

                discord_id = message.author.id
                try:
                    result = await sync_to_async(self._create_or_update_player, thread_sensitive=True)(
                        discord_id, message.author.name, message.content.upper()
                    )

                    # Assign verified role
                    verified_role_id = self.config.get_role_id("verified") if self.config else None
                    if verified_role_id:
                        guild = message.guild
                        member = message.author
                        role = guild.get_role(verified_role_id)
                        if role and role not in member.roles:
                            await member.add_roles(role)

                    await message.add_reaction("✅")
                except Exception as db_exc:
                    await message.add_reaction("❌")
                    await message.channel.send(f"Database error during validation: {db_exc}")
                    return
            else:
                await message.add_reaction("⁉️")
        except Exception as exc:
            await message.channel.send(f"Validation error: {exc}")
            raise exc

    @commands.Cog.listener()
    async def on_ready(self):
        pass

    def _get_player_info(self, discord_id):
        players = list(KnownPlayer.objects.filter(approved=True, discord_id=discord_id))
        if players:
            player = players[0]
            ids = list(player.ids.all().values("id", "primary"))
            return player.discord_id, ids
        return None, None

    def _get_player_id_info(self, player_id):
        player_ids = list(PlayerId.objects.filter(id=player_id))
        results = []
        for player_id_obj in player_ids:
            results.append({
                'discord_id': player_id_obj.player.discord_id,
                'id': player_id_obj.id,
                'primary': player_id_obj.primary
            })
        return results

    async def check_id(self, message):
        _, *potential_ids = message.content.split()
        for potential_id in potential_ids:
            discord_id, ids = await sync_to_async(self._get_player_info, thread_sensitive=True)(potential_id)
            if discord_id:
                await message.channel.send(f"discord_id={discord_id}, ids={ids}")

            player_id_results = await sync_to_async(self._get_player_id_info, thread_sensitive=True)(potential_id)
            for result in player_id_results:
                await message.channel.send(f"player_id.player.discord_id={result['discord_id']}, player_id.id={result['id']}, player_id.primary={result['primary']}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        try:
            # Channel checkers using config
            is_player_id_please_channel = partial(is_channel, id_=self.config.get_channel_id("verify")) if self.config else lambda c: False
            is_top50_channel = partial(is_channel, id_=self.config.get_channel_id("top50")) if self.config else lambda c: False
            is_testing_channel = partial(is_channel, id_=self.config.get_channel_id("testing")) if self.config else lambda c: False

            id_rolebot = self.config.get_bot_id("rolebot") if self.config else None
            id_fishy = self.config.get_bot_id("fishy") if self.config else None
            top1_id = self.config.get_role_id("top1") if self.config else None

            if is_player_id_please_channel(message.channel) and message.author.id != id_rolebot:
                logger.info(message.channel)
                await self.validate_player_id(message)
            elif message.author.id == id_fishy and message.content.startswith("!inject"):
                injection = message.content.split(" ", 1)[1]
                author = message.author.name
                channel = message.channel
                await sync_to_async(self._create_injection, thread_sensitive=True)(injection, message.author.id)
                await channel.send(f"🔥 Stored the prompt injection for AI summary from {author}: {injection[:7]}... 🔥")
                await message.delete()
            elif is_testing_channel(message.channel) and message.content.startswith("!check_id"):
                try:
                    await self.check_id(message)
                except Exception as exc:
                    logger.exception(exc)
            elif is_top50_channel(message.channel) and message.content.startswith("!inject"):
                if top1_id and top1_id in {role.id for role in getattr(message.author, 'roles', [])}:
                    injection = message.content.split(" ", 1)[1]
                    author = message.author.name
                    channel = message.channel
                    await sync_to_async(self._create_injection, thread_sensitive=True)(injection, message.author.id)
                    await channel.send(f"🔥 Stored the prompt injection for AI summary from {author}: {injection[:7]}... 🔥")
                    await message.delete()
        except Exception as exc:
            print(f"[on_message] Exception: {exc}")


async def setup(bot):
    await bot.add_cog(ValidationCog(bot))
