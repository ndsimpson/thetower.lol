"""
Command Helper Utilities

This module provides helper functions to create standardized commands
across all cogs, such as settings management commands.
"""

import inspect
import logging
from typing import Any, Callable, Union

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


def format_time_value(seconds: Union[int, float]) -> str:
    """
    Format a time value in seconds to a human-readable format.

    Args:
        seconds: Time value in seconds

    Returns:
        str: Formatted time string (e.g., "2h 30m 15s")
    """
    hours = int(seconds) // 3600
    minutes = (int(seconds) % 3600) // 60
    secs = int(seconds) % 60

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def is_time_setting(setting_name: str) -> bool:
    """
    Check if a setting name typically represents a time value.

    Args:
        setting_name: Name of the setting

    Returns:
        bool: True if the setting likely represents a time value
    """
    time_suffixes = ('_interval', '_threshold', '_timeout', '_delay', '_duration', '_rate', '_cooldown')
    return any(setting_name.endswith(suffix) for suffix in time_suffixes)


def convert_value_type(value: str) -> Any:
    """
    Convert a string value to its appropriate Python type.

    Args:
        value: String value to convert

    Returns:
        The converted value with appropriate type
    """
    # Try to infer the type and convert
    if value.lower() == 'true':
        return True
    elif value.lower() == 'false':
        return False
    elif value.lower() == 'none' or value.lower() == 'null':
        return None

    # Try numeric conversion
    try:
        if '.' in value:
            return float(value)
        else:
            return int(value)
    except ValueError:
        # If all else fails, keep it as a string
        return value


def create_settings_command(cog) -> Callable:
    """
    Create a standard settings display command for a cog.

    Args:
        cog: The cog instance to create the command for

    Returns:
        callable: The command function
    """
    async def settings_command(ctx):
        """Display current settings for this module"""
        settings = cog.get_all_settings()

        embed = discord.Embed(
            title=f"{cog.__class__.__name__} Settings",
            description=f"Current configuration for {cog.__class__.__name__.lower()} module",
            color=discord.Color.blue()
        )

        # No settings case
        if not settings:
            embed.add_field(name="No Settings", value="No configurable settings are available for this module.", inline=False)
            await ctx.send(embed=embed)
            return

        # Group settings by category if they follow naming convention (category_name)
        categories = {}
        uncategorized = []

        for name, value in settings.items():
            if '_' in name:
                category, setting_name = name.split('_', 1)
                if category not in categories:
                    categories[category] = []
                categories[category].append((name, value))
            else:
                uncategorized.append((name, value))

        # Add uncategorized settings first
        for name, value in uncategorized:
            # Format time values specially
            if is_time_setting(name) and isinstance(value, (int, float)):
                time_str = format_time_value(value)
                formatted_value = f"{value} seconds ({time_str})"
            else:
                formatted_value = str(value)

            embed.add_field(name=name, value=formatted_value, inline=False)

        # Add settings by category
        for category, settings_list in categories.items():
            category_text = []

            for name, value in settings_list:
                setting_name = name.split('_', 1)[1]  # Remove category prefix for display

                # Format time values specially
                if is_time_setting(name) and isinstance(value, (int, float)):
                    time_str = format_time_value(value)
                    formatted_value = f"{value} seconds ({time_str})"
                else:
                    formatted_value = str(value)

                category_text.append(f"**{setting_name}**: {formatted_value}")

            embed.add_field(name=f"{category.title()}", value="\n".join(category_text), inline=False)

        await ctx.send(embed=embed)

    # Update function metadata
    settings_command.__name__ = "settings"
    settings_command.__doc__ = f"Display current settings for {cog.__class__.__name__.lower()}"

    return settings_command


def create_set_command(cog, valid_settings=None, validators=None) -> Callable:
    """
    Create a standard command for changing settings.

    Args:
        cog: The cog instance to create the command for
        valid_settings: Optional list of valid setting names
        validators: Optional dict mapping setting names to validator functions

    Returns:
        callable: The command function
    """
    async def set_setting_command(ctx, setting_name: str, *, value: str = None):
        """Change a module setting"""
        # Handle case where value is None (i.e., user wants to see current value)
        if value is None:
            current_value = cog.get_setting(setting_name)
            if current_value is None:
                await ctx.send(f"Setting `{setting_name}` is not configured.")
            else:
                if is_time_setting(setting_name) and isinstance(current_value, (int, float)):
                    time_str = format_time_value(current_value)
                    await ctx.send(f"Current value of `{setting_name}` is {current_value} seconds ({time_str}).")
                else:
                    await ctx.send(f"Current value of `{setting_name}` is `{current_value}`.")
            return

        # Get allowed settings
        allowed_settings = valid_settings
        if allowed_settings is None:
            allowed_settings = list(cog.get_all_settings().keys())

        # Validate setting name
        if not allowed_settings:
            return await ctx.send("No configurable settings available for this module.")

        if setting_name not in allowed_settings:
            valid_settings_str = ", ".join(f"`{s}`" for s in allowed_settings)
            return await ctx.send(f"Invalid setting name. Valid options: {valid_settings_str}")

        # Convert value to appropriate type
        converted_value = convert_value_type(value)

        # Apply custom validator if one exists for this setting
        if validators and setting_name in validators:
            validator = validators[setting_name]
            validation_result = validator(converted_value)
            if validation_result is not True:
                return await ctx.send(f"Invalid value: {validation_result}")

        # Apply common validators for time-based settings
        if is_time_setting(setting_name) and isinstance(converted_value, (int, float)):
            if converted_value < 1:
                return await ctx.send(f"Value for `{setting_name}` must be positive.")
            if converted_value < 60 and '_interval' in setting_name:
                await ctx.send(f"⚠️ Warning: Setting `{setting_name}` to less than 60 seconds may cause performance issues.")

        # Update instance variables directly if they exist
        if hasattr(cog, setting_name):
            setattr(cog, setting_name, converted_value)

        # Save the setting
        cog.set_setting(setting_name, converted_value)

        # Format confirmation message
        if is_time_setting(setting_name) and isinstance(converted_value, (int, float)):
            time_str = format_time_value(converted_value)
            await ctx.send(f"✅ Set `{setting_name}` to {converted_value} seconds ({time_str})")
        else:
            await ctx.send(f"✅ Set `{setting_name}` to `{converted_value}`")

        # Log the change
        logger.info(f"Settings changed in {cog.__class__.__name__}: {setting_name} set to {converted_value} by {ctx.author}")

    # Update function metadata
    set_setting_command.__name__ = "set"
    set_setting_command.__doc__ = f"Change a setting for {cog.__class__.__name__.lower()}"

    return set_setting_command


def add_settings_commands(cog, group_command, valid_settings=None, validators=None) -> None:
    """
    Add both settings and set commands to a cog's command group.

    Args:
        cog: The cog instance
        group_command: The command group to add commands to
        valid_settings: Optional list of valid setting names
        validators: Optional dict mapping setting names to validator functions
    """
    # Create and add the settings command
    settings_cmd = create_settings_command(cog)
    group_command.command(name="settings")(settings_cmd)

    # Create and add the set command
    set_cmd = create_set_command(cog, valid_settings, validators)
    group_command.command(name="set")(set_cmd)


def register_settings_commands(cog, group_command_name,
                               valid_settings=None,
                               validators=None,
                               aliases=None) -> commands.Group:
    """
    Register a complete settings command group for a cog.

    Args:
        cog: The cog instance
        group_command_name: Name for the command group
        valid_settings: Optional list of valid setting names
        validators: Optional dict mapping setting names to validator functions
        aliases: Optional list of aliases for the command group

    Returns:
        The created command group
    """
    # Create the group command
    @commands.group(name=group_command_name, aliases=aliases or [], invoke_without_command=True)
    async def settings_group(ctx):
        """Settings management commands"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    # Register the group with the cog
    cog.__cog_commands__ = list(cog.__cog_commands__) + [settings_group]
    settings_group.cog = cog

    # Add settings and set subcommands
    add_settings_commands(cog, settings_group, valid_settings, validators)

    return settings_group


def command_with_help(name=None, brief=None, description=None, **attrs):
    """
    Decorator to create a command with improved help formatting.

    This adds proper argument descriptions from function annotations.

    Usage:
        @command_with_help(
            name="mycommand",
            brief="Short description",
            description="Longer description"
        )
        async def my_command(ctx, arg1: str, arg2: int = 5):
            '''Command docstring'''
            ...
    """
    def decorator(func):
        # Get the signature to analyze parameters
        sig = inspect.signature(func)

        # Create help text from annotations and defaults
        help_parts = []

        if description or func.__doc__:
            help_parts.append(description or func.__doc__.strip())
            help_parts.append("")

        # Add usage section
        help_parts.append("**Usage:**")
        params = []

        for param_name, param in list(sig.parameters.items())[1:]:  # Skip 'ctx'
            if param.annotation != inspect.Parameter.empty:
                type_name = param.annotation.__name__
            else:
                type_name = "value"

            if param.default != inspect.Parameter.empty:
                param_str = f"[{param_name}={param.default}]"
            else:
                param_str = f"<{param_name}>"

            params.append(param_str)

        help_parts.append(f"`{name or func.__name__} {' '.join(params)}`")
        help_parts.append("")

        # Add parameter descriptions
        param_descs = []
        for param_name, param in list(sig.parameters.items())[1:]:  # Skip 'ctx'
            if param.annotation != inspect.Parameter.empty:
                type_name = param.annotation.__name__
            else:
                type_name = "any"

            if param.default != inspect.Parameter.empty:
                default_str = f" (default: {param.default})"
            else:
                default_str = ""

            param_descs.append(f"• `{param_name}` ({type_name}){default_str}")

        if param_descs:
            help_parts.append("**Parameters:**")
            help_parts.extend(param_descs)

        # Join all parts of the help text
        help_text = "\n".join(help_parts)

        # Create the command
        return commands.command(
            name=name or func.__name__,
            help=help_text,
            brief=brief or (description or func.__doc__).split("\n")[0] if (description or func.__doc__) else None,
            **attrs
        )(func)

    return decorator


def add_standard_admin_commands(cog, group_name, aliases=None):
    """
    Add standard administrative commands to a cog.

    Args:
        cog: The cog to add commands to
        group_name: Name for the admin command group
        aliases: Optional aliases for the admin command group

    Returns:
        The created command group
    """
    # Create the admin group
    @commands.group(name=group_name, aliases=aliases or [], invoke_without_command=True)
    @commands.is_owner()  # Restrict to bot owner
    async def admin_group(ctx):
        """Administrative commands"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    # Add reload command
    @admin_group.command(name="reload")
    async def reload_command(ctx):
        """Reload configuration for this module"""
        try:
            if hasattr(cog, "reload_config"):
                await cog.reload_config()
            elif hasattr(cog, "reload_permissions"):
                cog.reload_permissions()

            await ctx.send(f"✅ Reloaded configuration for {cog.__class__.__name__}")
        except Exception as e:
            await ctx.send(f"❌ Error reloading configuration: {str(e)}")
            logger.error(f"Error reloading config for {cog.__class__.__name__}: {e}", exc_info=True)

    # Add debug info command
    @admin_group.command(name="info")
    async def info_command(ctx):
        """Show debug information for this module"""
        embed = discord.Embed(
            title=f"{cog.__class__.__name__} Debug Info",
            color=discord.Color.blue()
        )

        # Basic info about the cog
        cog_attrs = {
            "Class": cog.__class__.__name__,
            "Module": cog.__class__.__module__,
        }

        # Add commands count
        commands_list = [cmd.name for cmd in cog.get_commands()]
        cog_attrs["Commands"] = len(commands_list)

        # Add instance attributes that don't start with _ and aren't commands or listeners
        for attr_name, attr_value in cog.__dict__.items():
            # Skip private attributes, commands, and bot reference
            if (not attr_name.startswith('_') and
                attr_name not in ('bot', 'qualified_name') and
                    not callable(attr_value)):

                if isinstance(attr_value, (str, int, float, bool)) or attr_value is None:
                    cog_attrs[attr_name] = attr_value

        # Add basic attributes
        embed.add_field(
            name="Attributes",
            value="\n".join(f"**{k}:** {v}" for k, v in cog_attrs.items()),
            inline=False
        )

        # List commands
        embed.add_field(
            name="Commands",
            value=", ".join(f"`{cmd}`" for cmd in commands_list) or "No commands",
            inline=False
        )

        # Add any available status info
        if hasattr(cog, "get_status"):
            try:
                status = await cog.get_status()
                if status:
                    embed.add_field(
                        name="Status",
                        value="\n".join(f"**{k}:** {v}" for k, v in status.items()),
                        inline=False
                    )
            except Exception as e:
                embed.add_field(
                    name="Status Error",
                    value=f"Failed to get status: {str(e)}",
                    inline=False
                )

        await ctx.send(embed=embed)

    # Add the group to the cog
    cog.__cog_commands__ = list(cog.__cog_commands__) + [admin_group]
    admin_group.cog = cog

    return admin_group