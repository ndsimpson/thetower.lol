# Standard library imports
from functools import partial
from typing import Optional, Tuple
import logging

# Third-party imports
import discord
from discord.ext import commands
import easyocr

# Local application imports
from fish_bot.basecog import BaseCog
from fish_bot.util import is_channel


def is_valid_hex(text: str) -> bool:
    """
    Check if string contains only hexadecimal characters.

    Args:
        text: The string to check

    Returns:
        bool: True if text contains only hex characters, False otherwise
    """
    try:
        int(text.strip(), 16)
        return True
    except ValueError:
        return False


def hamming_distance(s1: str, s2: str) -> float:
    """
    Calculate normalized Hamming distance between two strings.

    Args:
        s1: First string
        s2: Second string

    Returns:
        float: 0 if identical, 1 if completely different
    """
    # Handle unequal strings by padding the shorter one
    if len(s1) != len(s2):
        max_len = max(len(s1), len(s2))
        s1 = s1.ljust(max_len)
        s2 = s2.ljust(max_len)

    return sum(c1 != c2 for c1, c2 in zip(s1, s2)) / len(s1)


class Verification(BaseCog, name="Verification"):
    """
    Handles user verification by checking player ID submissions.

    Automatically reacts to messages in the verification channel with 👍🏼 or 👎🏼
    based on whether the message contains a valid player ID and an attachment.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.reader = easyocr.Reader(["en"])

    async def check_image(self, content: str, image_bytes: bytes) -> bool:
        """
        Verify that the provided image contains the player ID.

        Args:
            content: The player ID to verify
            image_bytes: The image data to analyze

        Returns:
            bool: True if the image contains the player ID, False otherwise
        """
        content = content.replace("O", "0")
        ocr_results = self.reader.readtext(image_bytes, allowlist="0123456789ABCDEFGINST")
        player_id_candidates = []

        # Check for required text in the OCR results
        raw_text = ' '.join([line for _, line, _ in ocr_results])
        has_id_prefix = "ID" in raw_text.upper()
        has_settings = "SETTINGS" in raw_text.upper()

        for _, line, _ in ocr_results:
            subresult = [item for item in line.split()]
            if subresult:
                player_id_candidates.extend(subresult)

        player_id_candidates = [candidate.replace("O", "0") for candidate in player_id_candidates]

        # Calculate distances for logging
        distances = [
            (candidate, hamming_distance(candidate, content))
            for candidate in player_id_candidates
            if len(candidate) == len(content)
        ]

        # Find best match
        best_match = min(distances, key=lambda x: x[1]) if distances else (None, 1.0)
        best_candidate, best_distance = best_match

        # Consider matches with less than 35% character difference
        passes_score = best_distance < 0.35 if best_candidate else False

        # Always log OCR detection results
        logging.info(
            f"OCR verification attempt:\n"
            f"Expected ID: {content}\n"
            f"Raw OCR text: {raw_text[:100]}...\n"  # Truncate if too long
            f"Candidates: {player_id_candidates}\n"
            f"Best match: {best_candidate} (distance: {best_distance:.3f})\n"
            f"ID prefix found: {has_id_prefix}\n"
            f"Settings found: {has_settings}\n"
            f"Verification passed: {passes_score and has_id_prefix and has_settings}"
        )

        return passes_score and has_id_prefix and has_settings

    async def validate_verification(self, message: discord.Message) -> Tuple[bool, Optional[str]]:
        """
        Validate a verification message.

        Args:
            message: The Discord message to validate

        Returns:
            Tuple[bool, Optional[str]]: (is_valid, error_message)
        """
        content = message.content.strip()

        if not message.attachments:
            return False, "You must include an attachment."

        if not (13 <= len(content) <= 16):
            return False, "Player ID must be between 13-16 characters."

        if not is_valid_hex(content):
            return False, "Player ID must contain only hexadecimal characters (0-9, a-f)."

        image_bytes = await message.attachments[0].read()

        if not (await self.check_image(content, image_bytes)):
            await message.add_reaction("🖼️")
            return False, "Typed player id must match the photo and photo must be a full screen screenshot."

        return True, None

    @commands.Cog.listener("on_message")
    async def check_verify_message(self, message: discord.Message) -> None:
        """
        Checks verification messages and adds appropriate reactions.

        Validates that the message contains a player ID (13-16 characters)
        and an attachment. Adds 👍🏼 if valid, 👎🏼 if invalid.
        """
        is_player_id_please_channel = partial(is_channel, id_=self.config.get_channel_id("verify"))

        # Ignore specific users and non-target channels
        ignored_ids = [
            self.config.get_user_id("pog"),
            self.config.get_user_id("susjite"),
            self.config.get_bot_id("towerbot")
        ]
        if message.author.id in ignored_ids or not is_player_id_please_channel(message.channel):
            return

        # Validate the message
        is_valid, error_msg = await self.validate_verification(message)

        if is_valid:
            await message.add_reaction("👍🏼")
        else:
            await message.add_reaction("👎🏼")
            if error_msg:
                try:
                    # Try to reply first
                    await message.reply(error_msg, delete_after=30)
                except Exception as e:
                    # Fall back to channel send if reply fails
                    logging.warning(f"Failed to reply to message: {e}")
                    await message.channel.send(
                        f"{message.author.mention} {error_msg}",
                        delete_after=30,
                        reference=message
                    )

    @commands.Cog.listener("on_message_edit")
    async def check_edited_verify_message(self, before: discord.Message, after: discord.Message) -> None:
        """
        Checks edited verification messages and updates reactions.

        Applies the same validation as for new messages.
        """
        # Remove previous reactions
        try:
            await after.clear_reactions()
        except Exception:
            pass  # Ignore errors if reactions don't exist

        # Process the edited message with the same validation logic
        await self.check_verify_message(after)


async def setup(bot) -> None:
    await bot.add_cog(Verification(bot))