import functools

from discord.ext import commands


def flexible_command(name=None, **kwargs):
    """Create a command that can function as prefix, slash, or both based on settings."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            return await func(self, ctx, *args, **kwargs)

        # Create a regular command
        command = commands.command(name=name, **kwargs)(wrapper)

        # Store the original function for potential slash command registration
        command._flex_command_func = func
        command._flex_command_name = name or func.__name__
        command._flex_command_kwargs = kwargs

        return command
    return decorator


def flexible_group(name=None, **kwargs):
    """Create a command group that can function as prefix, slash, or both based on settings."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            return await func(self, ctx, *args, **kwargs)

        # Create a regular group
        group = commands.group(name=name, **kwargs)(wrapper)

        # Store the original function for potential slash command registration
        group._flex_command_func = func
        group._flex_command_name = name or func.__name__
        group._flex_command_kwargs = kwargs

        return group
    return decorator


def hybrid_ready(cls):
    """Decorator to add hybrid command support to a cog class.

    This adds command() and group() methods to the class that use flexible commands.
    """
    # Add class methods for command and group creation
    cls.command = classmethod(lambda cls, *args, **kwargs: flexible_command(*args, **kwargs))
    cls.group = classmethod(lambda cls, *args, **kwargs: flexible_group(*args, **kwargs))

    # Return the modified class
    return cls