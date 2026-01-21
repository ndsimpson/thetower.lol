from typing import Optional, Union

from discord import Member, TextChannel, User
from discord.ext import commands


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
        channel_name = getattr(channel, "name", "Unknown")
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
        display_name = getattr(user, "global_name", None) or user.name
        self.message = message or f"User {display_name} (ID: {user.id}) is not authorized"
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class CogNotEnabled(commands.CommandError):
    """
    Exception raised when a cog is not enabled for a guild.

    Attributes:
        cog_name: The name of the disabled cog
        guild_id: The guild ID where the cog is not enabled
        message: Optional custom error message
    """

    def __init__(self, cog_name: str, guild_id: int, message: Optional[str] = None) -> None:
        self.cog_name = cog_name
        self.guild_id = guild_id
        self.message = message or f"The '{cog_name}' feature is not enabled for this server"
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message
