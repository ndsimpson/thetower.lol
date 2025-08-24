"""Utility functions for The Tower Bot."""

import discord
from discord.ext import commands
from typing import Union


def is_channel(channel, id_):
    """
    Check if a channel has the specified ID.

    Args:
        channel: Discord channel object
        id_: The channel ID to check against

    Returns:
        bool: True if the channel ID matches, False otherwise
    """
    return getattr(channel, 'id', None) == id_


async def send_paginated_message(ctx: Union[commands.Context, discord.Interaction], content: str, header: str = "", max_length: int = 2000):
    """
    Send a message that might be too long for Discord's character limit by splitting it into multiple messages.

    Args:
        ctx: Discord context or interaction object
        content: The content to send
        header: Optional header to add to each message
        max_length: Maximum length per message (default 2000)
    """
    if not content:
        if isinstance(ctx, discord.Interaction):
            await ctx.response.send_message("No content to display.")
        else:
            await ctx.send("No content to display.")
        return

    # Combine header and content
    full_content = f"{header}\n{content}" if header else content

    # If the content fits in one message, send it directly
    if len(full_content) <= max_length:
        if isinstance(ctx, discord.Interaction):
            if ctx.response.is_done():
                await ctx.followup.send(full_content)
            else:
                await ctx.response.send_message(full_content)
        else:
            await ctx.send(full_content)
        return

    # Split the content into chunks
    lines = full_content.split('\n')
    current_chunk = header if header else ""

    for line in lines:
        # Skip the header line if it was already added
        if line == header and current_chunk.startswith(header):
            continue

        # Check if adding this line would exceed the limit
        test_chunk = f"{current_chunk}\n{line}" if current_chunk else line

        if len(test_chunk) <= max_length:
            current_chunk = test_chunk
        else:
            # Send the current chunk if it has content
            if current_chunk:
                if isinstance(ctx, discord.Interaction):
                    if ctx.response.is_done():
                        await ctx.followup.send(current_chunk)
                    else:
                        await ctx.response.send_message(current_chunk)
                        # Subsequent messages use followup
                        ctx.response._responded = True
                else:
                    await ctx.send(current_chunk)

            # Start a new chunk with the current line
            current_chunk = line

    # Send any remaining content
    if current_chunk:
        if isinstance(ctx, discord.Interaction):
            if ctx.response.is_done():
                await ctx.followup.send(current_chunk)
            else:
                await ctx.response.send_message(current_chunk)
        else:
            await ctx.send(current_chunk)
