import discord
from discord.ext import commands
from fish_bot import const, settings
import json


class CommandPermissionEditor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        """Allow fishy to use any command from anywhere, and restrict others to admin users"""
        if ctx.author.id == const.id_fishy:
            return True
        return ctx.author.id in [const.id_pog]  # Only other admins need channel restrictions

    @commands.group(name="channelmap")
    async def channel_map(self, ctx):
        """Command group for managing channel mappings"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Available subcommands: show, update")

    @channel_map.command(name="show")
    async def show_channel_map(self, ctx):
        """Display the current channel map configuration with usernames"""
        readable_map = {}

        for command, data in settings.COMMAND_CHANNEL_MAP.items():
            readable_map[command] = {
                "channels": {},
                "default_users": []
            }

            # Convert channel IDs and user IDs to names
            for channel_id, user_ids in data["channels"].items():
                channel = self.bot.get_channel(channel_id)
                channel_name = channel.name if channel else f"Unknown Channel ({channel_id})"

                user_names = []
                for user_id in user_ids:
                    user = await self.bot.fetch_user(user_id)
                    user_names.append(user.name if user else f"Unknown User ({user_id})")

                readable_map[command]["channels"][channel_name] = user_names

            # Convert default user IDs to names
            for user_id in data["default_users"]:
                user = await self.bot.fetch_user(user_id)
                readable_map[command]["default_users"].append(
                    user.name if user else f"Unknown User ({user_id})"
                )

        formatted_map = json.dumps(readable_map, indent=2)
        await ctx.send(f"Current channel permission map:\n```json\n{formatted_map}\n```")

    @channel_map.command(name="update")
    async def update_channel_map(self, ctx, command: str, channel: discord.TextChannel, *users: discord.Member):
        """
        Update channel permissions for a command
        Usage: $channelmap update <command> #channel @user1 @user2 ...
        """
        if command not in settings.COMMAND_CHANNEL_MAP:
            await ctx.send(f"Error: Command '{command}' not found in channel map")
            return

        try:
            # Convert mentioned users to their IDs
            user_ids = [user.id for user in users]

            # Update the channel mapping
            if channel.id not in settings.COMMAND_CHANNEL_MAP[command]["channels"]:
                settings.COMMAND_CHANNEL_MAP[command]["channels"][channel.id] = []

            settings.COMMAND_CHANNEL_MAP[command]["channels"][channel.id] = user_ids

            # Get user names for confirmation message
            user_names = [user.name for user in users]

            # Confirm the update
            await ctx.send(f"Updated channel #{channel.name} permissions for command '{command}'\n"
                           f"Authorized users: {', '.join(user_names)}")

        except Exception as e:
            await ctx.send(f"Error updating channel map: {str(e)}")

    @channel_map.command(name="add_default")
    async def add_default_user(self, ctx, command: str, *users: discord.Member):
        """
        Add users to the default_users list for a command
        Usage: $channelmap add_default <command> @user1 @user2 ...
        """
        if command not in settings.COMMAND_CHANNEL_MAP:
            await ctx.send(f"Error: Command '{command}' not found in channel map")
            return

        try:
            # Convert mentioned users to their IDs
            user_ids = [user.id for user in users]

            # Add users to default_users list if not already present
            for user_id in user_ids:
                if user_id not in settings.COMMAND_CHANNEL_MAP[command]["default_users"]:
                    settings.COMMAND_CHANNEL_MAP[command]["default_users"].append(user_id)

            # Get user names for confirmation message
            user_names = [user.name for user in users]

            await ctx.send(f"Added default users for command '{command}'\n"
                           f"Users added: {', '.join(user_names)}")

        except Exception as e:
            await ctx.send(f"Error adding default users: {str(e)}")

    @channel_map.command(name="remove_default")
    async def remove_default_user(self, ctx, command: str, *users: discord.Member):
        """
        Remove users from the default_users list for a command
        Usage: $channelmap remove_default <command> @user1 @user2 ...
        """
        if command not in settings.COMMAND_CHANNEL_MAP:
            await ctx.send(f"Error: Command '{command}' not found in channel map")
            return

        try:
            # Convert mentioned users to their IDs
            user_ids = [user.id for user in users]

            # Remove users from default_users list
            for user_id in user_ids:
                if user_id in settings.COMMAND_CHANNEL_MAP[command]["default_users"]:
                    settings.COMMAND_CHANNEL_MAP[command]["default_users"].remove(user_id)

            # Get user names for confirmation message
            user_names = [user.name for user in users]

            await ctx.send(f"Removed default users for command '{command}'\n"
                           f"Users removed: {', '.join(user_names)}")

        except Exception as e:
            await ctx.send(f"Error removing default users: {str(e)}")


async def setup(bot):
    await bot.add_cog(CommandPermissionEditor(bot))