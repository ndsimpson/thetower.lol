# Third-party imports
from discord.ext import commands
from asgiref.sync import sync_to_async

from thetower.backend.tourney_results.models import TourneyResult
from thetower.backend.tourney_results.tourney_utils import get_summary

from thetower.bot.util import send_paginated_message
from thetower.bot.basecog import BaseCog


class TourneyManagement(BaseCog, name="Tourney Management"):
    """Commands for managing tournament data and results.

    Provides functionality to view, publish, and manage tournament summaries.
    Allows staff to control which tournaments are publicly visible.
    """

    def __init__(self, bot):
        super().__init__(bot)

    @commands.group(name="tourney", invoke_without_command=True)
    async def tourney(self, ctx):
        """Tournament management commands.

        Available subcommands:
        - viewpending: View tournaments waiting for publication
        - view: View details of a specific tournament
        - publish: Make tournaments publicly visible
        - viewsummary: Display a tournament's summary
        - gensummary: Generate a new tournament summary
        """
        if ctx.invoked_subcommand is None:
            # List all available subcommands
            commands_list = [command.name for command in self.tourney.commands]
            await ctx.send(f"Available subcommands: {', '.join(commands_list)}")

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
        try:
            tourneysummary = 'Yes' if tournament.summary else 'No'
        except AttributeError:
            tourneysummary = 'No'
        # Create and send response
        response = (
            f"__**Tournament #{tournament.id}**__\n"
            f"Date: {tournament.date}\n"
            f"League: {tournament.league}\n"
            f"Participants: {rows_count}\n"
            f"Battle Conditions: {conditions_str}\n"
            f"Summary generated: {tourneysummary}\n"
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

    @tourney.command(name="viewsummary", description="Display the summary for a tournament")
    async def display_summary(self, ctx, id: int):
        """Display the summary for a specific tournament"""
        try:
            # Get the tournament
            tournament = await sync_to_async(TourneyResult.objects.get)(id=id)

            if not tournament.summary:
                raise AttributeError

            header = f"__**Summary for Tournament #{id}**__"
            await send_paginated_message(ctx, tournament.summary, header=header)

        except TourneyResult.DoesNotExist:
            await ctx.send(f"Error: Tournament #{id} not found!")
        except AttributeError:
            await ctx.send(f"No summary available for Tournament #{id}. Generate one using `{self.config.get('prefix', '')}tourney gensummary {id}`")
        except Exception as e:
            await ctx.send(f"Error displaying summary: {str(e)}")
            self.bot.logger.error(f"Summary display error: {e}", exc_info=True)

    @tourney.command(name="gensummary", description="Generate a summary for a tournament")
    async def generate_summary(self, ctx, id: int):
        """Generate and save a summary for a specific tournament"""
        try:
            # Get the tournament
            tournament = await sync_to_async(TourneyResult.objects.get)(id=id)

            # Generate the summary
            await ctx.send(f"Generating summary for Tournament #{id}...")
            summary = await sync_to_async(get_summary)(tournament.date)

            # Save the summary to the tournament
            tournament.overview = summary
            await sync_to_async(tournament.save)()

            await ctx.send(f"Summary generated for Tournament #{id}!")
            await send_paginated_message(ctx, summary)

        except TourneyResult.DoesNotExist:
            await ctx.send(f"Error: Tournament #{id} not found!")
        except Exception as e:
            await ctx.send(f"Error generating summary: {str(e)}")
            # Log the full error for debugging
            self.bot.logger.error(f"Summary generation error: {e}", exc_info=True)


async def setup(bot):
    await bot.add_cog(TourneyManagement(bot))
