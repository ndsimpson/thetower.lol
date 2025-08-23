from typing import Optional, Union

from discord import TextChannel, Member, User
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
        channel_name = getattr(channel, 'name', 'Unknown')
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
        display_name = getattr(user, 'global_name', None) or user.name
        self.message = message or f"User {display_name} (ID: {user.id}) is not authorized"
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message
