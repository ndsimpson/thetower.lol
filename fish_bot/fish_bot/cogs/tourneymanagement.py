# Standard library imports
import os

# Third-party imports
import django
from discord.ext import commands
from asgiref.sync import sync_to_async

from dtower.tourney_results.models import TourneyResult, BattleCondition

# Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
django.setup()


class TourneyManagement(commands.Cog):
    """Tournament management commands and functionality"""

    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="tourney", description="Tournament management commands")
    async def tourney(self, ctx):
        """Command group for managing tournament data"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Available subcommands: ")

    @tourney.command(name="viewpending",
                     description="View the pending tournaments waiting for publication"
                     )
    async def view_pending(self, ctx):
        """View the pending tournaments waiting for publication"""
        pending = await sync_to_async(list)(TourneyResult.objects.filter(public=False))
        if not pending:
            await ctx.send("No pending tournaments")
            return

        await ctx.send("Tournaments awaiting publiction:")
        for tournament in pending:
            await ctx.send(f"{tournament.id}) {tournament.date} {tournament.league}")

    @tourney.command(name="view", description="View a particular tournament by id")
    async def view(self, ctx, id: int):
        """View a particular tournament by id"""
        # Get tournament and related data
        tournament = await sync_to_async(TourneyResult.objects.get)(id=id)
        rows_count = await sync_to_async(tournament.rows.count)()
        conditions = await sync_to_async(list)(tournament.conditions.all())

        # Format conditions into string
        conditions_str = ", ".join([c.name for c in conditions]) if conditions else "None"

        # Create and send response
        response = (
            f"__**Tournament #{tournament.id}**__\n"
            f"Date: {tournament.date}\n"
            f"League: {tournament.league}\n"
            f"Participants: {rows_count}\n"
            f"Battle Conditions: {conditions_str}\n"
            f"Public: {'Yes' if tournament.public else 'No'}"
        )
        await ctx.send(response)

    @tourney.command(name="publish", description="Publish a tournament by id or 'all' to publish all pending tournaments")
    async def publish(self, ctx, id_or_all: str):
        """Publish a tournament by id or 'all' to publish all pending tournaments"""
        if id_or_all.lower() == "all":
            # Get all unpublished tournaments
            pending = await sync_to_async(list)(TourneyResult.objects.filter(public=False))
            if not pending:
                await ctx.send("No pending tournaments to publish")
                return

            # Publish all pending tournaments
            count = 0
            for tournament in pending:
                tournament.public = True
                await sync_to_async(tournament.save)()
                count += 1

            await ctx.send(f"Published {count} tournament(s) successfully!")
        else:
            try:
                # Convert input to integer for specific ID
                id = int(id_or_all)
                tournament = await sync_to_async(TourneyResult.objects.get)(id=id)
                tournament.public = True
                await sync_to_async(tournament.save)()

                await ctx.send(f"Tournament #{id} has been published successfully!")
            except ValueError:
                await ctx.send("Error: Please provide a valid tournament ID or 'all'")
            except TourneyResult.DoesNotExist:
                await ctx.send(f"Error: Tournament #{id} not found!")


async def setup(bot):
    await bot.add_cog(TourneyManagement(bot))