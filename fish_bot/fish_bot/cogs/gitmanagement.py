import subprocess
from discord.ext import commands
from discord.ext.commands import Context
from fish_bot.basecog import BaseCog


class GitManagement(BaseCog, name="Git Management"):
    """Commands for managing Git repository operations.

    Provides functionality to perform Git operations like pulling updates
    from the repository with optional rebase support.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot

    @commands.group(name="git", invoke_without_command=True)
    async def git(self, ctx):
        """Git repository management commands.

        Available subcommands:
        - pull: Pull latest changes from git repository
        """
        if ctx.invoked_subcommand is None:
            # List all available subcommands
            commands_list = [command.name for command in self.git.commands]
            await ctx.send(f"Available subcommands: {', '.join(commands_list)}")

    @git.command(name="pull")
    async def pull_git(self, ctx: Context, method: str = None):
        """Pull latest changes from git repository."""
        await ctx.send("Attempting pull...")
        try:
            if method == "rebase":
                await ctx.send("Rebasing...")
                response = subprocess.check_output(
                    ["git", "pull", "--recurse-submodules", "--rebase"],
                    cwd="/tourney"
                )
            else:
                response = subprocess.check_output(
                    ["git", "pull", "--recurse-submodules"],
                    cwd="/tourney"
                )
            await ctx.send(response.decode("utf-8"))
        except subprocess.CalledProcessError as e:
            await ctx.send(f"Git pull failed: {e.output.decode('utf-8')}")
        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}")


async def setup(bot) -> None:
    await bot.add_cog(GitManagement(bot))
