import asyncio
import logging
from collections import defaultdict
from math import ceil

import discord
from asgiref.sync import sync_to_async

from discord_bot import const
from discord_bot.util import get_all_members, get_tower, role_id_to_position
from dtower.sus.models import KnownPlayer, PlayerId, SusPerson
from dtower.tourney_results.constants import leagues, legend, champ, plat, gold, silver, copper, how_many_results_hidden_site
from dtower.tourney_results.data import get_results_for_patch, get_tourneys
from dtower.tourney_results.models import PatchNew as Patch


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


lower_roles = {
    copper: {
        1: const.copper1_id,
        50: const.copper50_id,
    },
    silver: {
        50: const.silver50_id,
        100: const.silver100_id,
    },
    gold: {
        100: const.gold100_id,
        250: const.gold250_id,
    },
    plat: {
        250: const.plat250_id,
        500: const.plat500_id,
    },
    champ: {
        500: const.champ500_id,
        1000: const.champ1000_id,
    },
}


async def handle_adding(
    client: discord.Client,
    limit: int | None,
    discord_ids: list[int] | None = None,
    channel: discord.TextChannel | None = None,
    debug_channel: discord.TextChannel | None = None,
    verbose: bool | None = None,
    info_only: bool = False,
) -> None:
    # Add info message at beginning
    if info_only and channel:
        await channel.send("**INFO MODE**: Showing what would happen without making changes 📊")

    discord_id_kwargs = {} if discord_ids is None else {"discord_id__in": discord_ids}

    skipped = 0
    unchanged = defaultdict(list)
    changed = defaultdict(list)
    removed_roles_count = defaultdict(int)

    if debug_channel is None:
        debug_channel = channel

    players = await sync_to_async(KnownPlayer.objects.filter, thread_sensitive=True)(approved=True, discord_id__isnull=False, **discord_id_kwargs)

    if verbose:
        await channel.send(f"Starting the processing of {players.count() if not limit else limit} users... :rocket:")

    patch = sorted(await sync_to_async(Patch.objects.all, thread_sensitive=True)())[-1]

    logging.info("loading dfs")

    dfs = {}

    dfs[leagues[0]] = get_tourneys(
        get_results_for_patch(patch=patch, league=leagues[0]),
        limit=how_many_results_hidden_site
    )  # Need to know everyone in legends to fallback to champ 500 in case they don't qualify for legends roles

    if verbose:
        await debug_channel.send(f"Loaded legends tourney data of {len(dfs[leagues[0]])} rows")

    for league in leagues[1:]:
        dfs[league] = get_tourneys(get_results_for_patch(patch=patch, league=league), limit=how_many_results_hidden_site)

        if verbose:
            await debug_channel.send(f"Loaded {league} tourney data of {len(dfs[league])} rows")

        await asyncio.sleep(0)

    sus_ids = {item.player_id for item in await sync_to_async(SusPerson.objects.filter, thread_sensitive=True)(sus=True)}
    dfs = {league: df[~df.id.isin(sus_ids)] for league, df in dfs.items()}
    logging.info("loaded dfs")

    tower = await get_tower(client)

    logging.info("fetching roles")
    roles = await tower.fetch_roles()
    position_roles = await filter_roles(roles, role_id_to_position)
    wave_roles_by_league = {}
    for league, wave_thresholds in lower_roles.items():
        wave_roles = {}
        for wave_threshold, role_id in wave_thresholds.items():
            for role in roles:
                if role.id == role_id:
                    wave_roles[wave_threshold] = role
                    break
        wave_roles_by_league[league] = wave_roles
    logging.info("fetched roles")

    logging.info("getting all members")
    members = await get_all_members(client)
    logging.info("got all members")

    if verbose:
        await debug_channel.send(f"Fetched all discord members {len(members)=}")

    member_lookup = {member.id: member for member in members}

    player_iter = players.order_by("-id")[:limit] if limit else players.order_by("-id")
    player_data = player_iter.values_list("id", "discord_id")
    total = player_iter.count()
    all_ids = await sync_to_async(PlayerId.objects.filter, thread_sensitive=True)(player__in=players)

    ids_by_player = defaultdict(set)

    for id in all_ids:
        ids_by_player[id.player.id].add(id.id)

    i = 0

    logging.info("iterating over players")
    async for player_id, player_discord_id in player_data:
        i += 1

        if i % 100 == 0:
            logging.info(f"Processed {i} players")
            await asyncio.sleep(0)

        if i % 1000 == 0 and verbose:
            await debug_channel.send(f"Processed {i} out of {total} players")

        ids = ids_by_player[player_id]

        discord_player = member_lookup.get(int(player_discord_id))

        if discord_player is None:
            skipped += 1
            continue

        for league in leagues:
            df = dfs[league]
            player_df = df[df["id"].isin(ids)]

            if not player_df.empty:
                if league == legend:
                    role_assigned = await handle_position_league(player_df, position_roles, discord_player, changed, unchanged, info_only)

                    if not role_assigned:  # doesn't qualify for legend role but has some results in legends
                        # Get the highest tier threshold for Champion league
                        next_wave_min = max(wave_roles_by_league[champ].keys())
                        role = wave_roles_by_league[champ][next_wave_min]

                        if role in discord_player.roles:
                            unchanged[legend].append((discord_player, role))
                            break

                        await remove_all_other_roles(discord_player, role, wave_roles_by_league, position_roles, removed_roles_count, info_only)
                        await add_wave_roles(changed, discord_player, champ, next_wave_min, role, info_only)
                        role_assigned = True

                    if role_assigned:
                        break
                else:
                    role_assigned = await handle_wave_league(player_df, wave_roles_by_league, position_roles, discord_player, league, changed, unchanged, removed_roles_count, info_only)

                    if role_assigned:
                        break
        else:
            # Fix: compile all wave roles from all leagues into a list
            all_wave_roles = [role for league_roles in wave_roles_by_league.values() for wave_threshold, role in league_roles.items()]
            for role in all_wave_roles + list(position_roles.values()):
                if role in discord_player.roles:
                    await discord_player.remove_roles(role)
            skipped += 1

        if discord_player is None:
            discord_player = member_lookup.get(int(player_discord_id))

            if discord_player is None:
                continue

        elif discord_player == "unknown":
            break

    logging.info(f"{skipped=}")

    unchanged_summary = {league: len(unchanged_data) for league, unchanged_data in unchanged.items()}

    if verbose:
        summary_message = f"""Successfully reviewed all players :tada: \n\n{skipped=} (no role eligible), \n{unchanged_summary=}, \n{changed=}."""
        await send_chunked_message(debug_channel, summary_message)
    else:
        total_players = skipped + sum(unchanged_summary.values()) + sum(len(values) for values in changed.values())

        league_data = {league: str(contents) for league, contents, in unchanged_summary.items()}

        for league, contents in changed.items():
            if len(contents):
                league_data[league] += f"+{len(contents)}"

        league_updates = ", ".join(f"{league}: {league_count}" for league, league_count in league_data.items())
        await debug_channel.send(f"""Bot hourly update: total players: {total_players}, {league_updates}""")

    added_roles = [f"{name}: {league}" for league, contents in changed.items() for name, league in contents]

    chunk_by = 10

    try:
        for chunk in range(ceil(len(added_roles) / chunk_by)):
            added_roles_message = "\n".join(added_roles[chunk * chunk_by : (chunk + 1) * chunk_by])
            await send_chunked_message(channel, added_roles_message)

            if channel != debug_channel:
                await send_chunked_message(debug_channel, added_roles_message)

            await asyncio.sleep(1)
    except Exception as e:
        logging.error(f"Error sending role updates: {e}")

    if removed_roles_count:
        logging.info(f"{'Would remove' if info_only else 'Removed'} roles statistics: {dict(removed_roles_count)}")
        if verbose:
            removed_roles_summary = ", ".join(f"{league}: {count}" for league, count in removed_roles_count.items())
            await debug_channel.send(f"{'Would remove' if info_only else 'Roles removed'}: {removed_roles_summary}")

    logging.info("**********Done**********")


async def filter_roles(roles, role_id_to_wave):
    """
    Maps role IDs to role objects, when roles have a 1:1 mapping
    Used for position roles (league positions)
    """
    return {role_id_to_wave[role.id]: role for role in roles if role.id in role_id_to_wave}


async def handle_position_league(
    df,
    position_roles,
    discord_player,
    changed,
    unchanged,
    info_only: bool = False,
) -> bool:
    logging.debug(f"{discord_player=} {df.position=}")

    if df.sort_values("date", ascending=False).iloc[0].position == 1:  # special logic for the winner
        rightful_role = position_roles[1]

        if rightful_role in discord_player.roles:
            unchanged[legend].append((discord_player, rightful_role))
            return True  # Don't actually do anything if the player already has the role

        # Only remove other position roles, not the rightful one
        position_roles_to_remove = [role for role in discord_player.roles
                                    if role.id in role_id_to_position and role != rightful_role]

        if position_roles_to_remove and not info_only:
            await discord_player.remove_roles(*position_roles_to_remove)

        if not info_only:
            await discord_player.add_roles(rightful_role)
        logging.info(f"{'Would add' if info_only else 'Added'} champ top1 role to {discord_player=}")
        changed[legend].append((discord_player.name, rightful_role.name))
        return True

    # current_df = df[df["date"].isin(dates_this_event)]
    current_df = df
    best_position_in_event = current_df.position.min() if not current_df.empty else 100000

    for pos, role in sorted(tuple(position_roles.items()))[1:]:
        if best_position_in_event <= pos:
            rightful_role = role

            if rightful_role in discord_player.roles:
                unchanged[legend].append((discord_player, rightful_role))
                return True  # Don't actually do anything if the player already has the role

            # Only remove other position roles, not the rightful one
            position_roles_to_remove = [role for role in discord_player.roles
                                        if role.id in role_id_to_position and role != rightful_role]

            if position_roles_to_remove and not info_only:
                await discord_player.remove_roles(*position_roles_to_remove)

            if not info_only:
                await discord_player.add_roles(rightful_role)
            logging.info(f"Added {role=} to {discord_player=}")
            changed[legend].append((discord_player.name, rightful_role.name))
            return True
    else:
        for role in [role for role in discord_player.roles if role.id in role_id_to_position]:
            if not info_only:
                await discord_player.remove_roles(role)

    return False


async def handle_wave_league(df, wave_roles_by_league, position_roles, discord_player, league, changed, unchanged, removed_roles_count=None, info_only: bool = False):  # New parameter
    wave_roles = wave_roles_by_league[league]
    player_waves = df.wave.tolist() if not df.empty else []
    player_max_wave = max(player_waves) if player_waves else 0

    # Sort wave thresholds from highest to lowest to check highest tier first
    for wave_min in sorted(wave_roles.keys(), reverse=True):
        role = wave_roles[wave_min]

        # Check if player qualifies for this tier
        if any(wave >= wave_min for wave in player_waves):
            # Player qualifies for this tier
            if role in discord_player.roles:
                unchanged[league].append((discord_player, role))
                return True

            await remove_all_other_roles(discord_player, role, wave_roles_by_league, position_roles, removed_roles_count, info_only)
            await add_wave_roles(changed, discord_player, league, wave_min, role, info_only)
            return wave_min

    # Player doesn't qualify for any tier in this league, check the next league down
    if leagues.index(league) + 1 < len(leagues):
        next_league = leagues[leagues.index(league) + 1]
        next_wave_roles = wave_roles_by_league[next_league]

        # Check each tier in next league, from highest to lowest
        for next_wave_min in sorted(next_wave_roles.keys(), reverse=True):
            # Only assign if player actually meets this wave requirement
            if player_max_wave >= next_wave_min:
                next_role = next_wave_roles[next_wave_min]

                if next_role in discord_player.roles:
                    unchanged[next_league].append((discord_player, next_role))
                    return True

                await remove_all_other_roles(discord_player, next_role, wave_roles_by_league, position_roles, removed_roles_count, info_only)
                await add_wave_roles(changed, discord_player, next_league, next_wave_min, next_role, info_only)
                return next_wave_min

        # If they don't meet any tier in the next league, recursively check the league below
        # This is optional - remove if you want to stop checking after one league down
        return await handle_wave_league(df, wave_roles_by_league, position_roles, discord_player, next_league, changed, unchanged, removed_roles_count, info_only)

    return False


async def add_wave_roles(changed, discord_player, league, wave_min, role, info_only=False):
    if not info_only:
        await discord_player.add_roles(role)
    changed[league].append((discord_player.name, f"{league}: {wave_min}"))
    logging.info(f"{'Would add' if info_only else 'Added'} {league=}, {wave_min=} to {discord_player=}")


async def remove_all_other_roles(discord_player, keep_role, wave_roles_by_league, position_roles, removed_roles_count=None, info_only=False):
    """Remove all league roles except the one to keep"""
    # Get all wave roles from all leagues with their league info
    all_wave_roles_with_info = []
    for league, league_roles in wave_roles_by_league.items():
        for wave_threshold, role in league_roles.items():
            all_wave_roles_with_info.append((role, league))

    # Create lookup dict for quick league identification
    role_to_league = {role: league for role, league in all_wave_roles_with_info}
    all_wave_roles = [role for role, _ in all_wave_roles_with_info]

    # Get all position roles
    all_position_roles = list(position_roles.values())

    # Combined list of all roles that should be removed if they're not the one to keep
    all_roles_to_check = all_wave_roles + all_position_roles

    # Remove all roles except the one to keep
    roles_to_remove = [role for role in all_roles_to_check if role != keep_role and role in discord_player.roles]

    if roles_to_remove:
        # Count removed roles by type if counter is provided
        if removed_roles_count is not None:
            for role in roles_to_remove:
                if role in all_position_roles:
                    removed_roles_count["Legend"] += 1
                elif role in all_wave_roles:
                    league = role_to_league[role]
                    removed_roles_count[league] += 1

        # Only actually remove roles if not in info mode
        if not info_only:
            await discord_player.remove_roles(*roles_to_remove)

        role_names = [role.name for role in roles_to_remove]
        logging.debug(f"{'Would remove' if info_only else 'Removed'} {len(roles_to_remove)} roles from {discord_player}: {role_names}")

    return roles_to_remove


async def send_chunked_message(channel, content, chunk_size=1900):
    """Send a message in chunks if it's too long for Discord's character limit."""
    if not content:
        return

    if len(content) <= chunk_size:
        await channel.send(content)
    else:
        # Split into smaller chunks
        chunks = [content[i:i + chunk_size] for i in range(0, len(content), chunk_size)]
        for chunk in chunks:
            await channel.send(chunk)
            await asyncio.sleep(0.5)
