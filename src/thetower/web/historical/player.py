import datetime
import os
from html import escape
from urllib.parse import urlencode

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from natsort import natsorted
from plotly.subplots import make_subplots
from pathlib import Path

from thetower.web.historical.search import compute_search
from thetower.web.util import get_options, escape_df_html
from thetower.backend.sus.models import PlayerId
from thetower.backend.tourney_results.constants import (
    Graph,
    all_relics,
    colors_017,
    colors_018,
    how_many_results_public_site,
    leagues,
    stratas_boundaries,
    stratas_boundaries_018,
)
from thetower.backend.tourney_results.data import (
    get_details,
    get_id_lookup,
    get_patches,
    is_under_review,
    is_shun,
    is_sus,
    is_support_flagged,
)
from thetower.backend.tourney_results.formatting import BASE_URL, color_position
from thetower.backend.tourney_results.models import PatchNew as Patch
from thetower.backend.tourney_results.models import TourneyRow
from thetower.backend.tourney_results.tourney_utils import check_all_live_entry

id_mapping = get_id_lookup()
hidden_features = os.environ.get("HIDDEN_FEATURES")


def compute_player_lookup():
    print("player")
    options = get_options(links=False)
    hidden_features = os.environ.get("HIDDEN_FEATURES")

    def search_for_new():
        if "player_id" in st.session_state:
            st.session_state.pop("player_id")

    css_path = Path(__file__).parent.parent / "static" / "styles" / "style.css"
    with open(css_path, "r") as infile:
        table_styling = f"<style>{infile.read()}</style>"

    st.write(table_styling, unsafe_allow_html=True)

    if player_id := st.session_state.get("player_id"):
        options.current_player = player_id

    if options.current_player is not None:
        st.button("Search for another player?", on_click=search_for_new)

    if options.current_player is None:
        compute_search(player=True, comparison=False)
        exit()

    info_tab, graph_tab, raw_data_tab, patch_tab = st.tabs(["Info", "Tourney performance graph", "Full results data", "Patch best"])

    player_ids = PlayerId.objects.filter(id=options.current_player)
    print(f"{player_ids=} {options.current_player=}")

    hidden_query = {} if hidden_features else {"result__public": True, "position__lt": how_many_results_public_site}

    if player_ids:
        player_id = player_ids[0]
        print(f"{player_ids=} {player_id=}")
        rows = TourneyRow.objects.filter(
            player_id__in=player_id.player.ids.all().values_list("id", flat=True),
            **hidden_query,
        )
    else:
        print(f"{player_id=} {options.current_player=}")
        player_id = options.current_player
        rows = TourneyRow.objects.filter(
            player_id=player_id,
            **hidden_query,
        )

    if not rows:
        st.error(f"No results found for the player {player_id}.")
        return

    if (is_sus(player_id) or is_support_flagged(player_id)) and not hidden_features:
        st.error(f"No results found for the player {player_id}.")
        return

    player_df = get_details(rows)

    if player_df.empty:
        st.error(f"No results found for the player {player_id}.")
        return

    player_df = player_df.sort_values("date", ascending=False)
    user = player_df["real_name"][0]

    # Apply HTML escaping before styling or displaying
    player_df = escape_df_html(player_df, ['real_name', 'tourney_name'])

    draw_info_tab(info_tab, user, player_id, player_df, hidden_features)

    patches_options = sorted([patch for patch in get_patches() if patch.version_minor], key=lambda patch: patch.start_date, reverse=True)
    graph_options = [options.default_graph.value] + [
        value for value in list(Graph.__members__.keys()) + patches_options if value != options.default_graph.value
    ]
    patch_col, average_col = graph_tab.columns([1, 1])
    patch = patch_col.selectbox("Limit results to a patch? (see side bar to change default)", graph_options)
    filter_bcs = patch_col.multiselect("Filter by battle conditions?", sorted({bc for bcs in player_df.bcs for bc in bcs}, key=lambda bc: bc.shortcut))
    rolling_average = average_col.slider("Use rolling average for results from how many tourneys?", min_value=1, max_value=10, value=5)

    colors, patch_df, stratas = handle_colors_dependant_on_patch(patch, player_df)

    if filter_bcs:
        sbcs = set(filter_bcs)
        patch_df = patch_df[patch_df.bcs.map(lambda table_bcs: sbcs & set(table_bcs) == sbcs)]
        player_df = player_df[player_df.bcs.map(lambda table_bcs: sbcs & set(table_bcs) == sbcs)]

    tbdf = patch_df.reset_index(drop=True)
    tbdf = filter_lower_leagues(tbdf)
    tbdf["average"] = tbdf.wave.rolling(rolling_average, min_periods=1, center=True).mean().astype(int)
    tbdf["position_average"] = tbdf.position.rolling(rolling_average, min_periods=1, center=True).mean().astype(int)
    tbdf["bcs"] = tbdf.bcs.map(lambda bc_qs: " / ".join([bc.shortcut for bc in bc_qs]))

    if len(tbdf) > 1:
        pos_col, tweak_col = graph_tab.columns([1, 1])

        graph_position_instead = pos_col.checkbox("Graph position instead")
        average_foreground = tweak_col.checkbox("Average in the foreground?", value=False)
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        if not graph_position_instead:
            handle_not_graph_position_instead(average_foreground, colors, fig, rolling_average, stratas, tbdf)
        else:
            handle_is_graph_position(average_foreground, fig, rolling_average, tbdf)

        handle_start_date_loop(fig, graph_position_instead, tbdf)
        fig.update_layout(hovermode="x unified")

        graph_tab.plotly_chart(fig)

    additional_column = ["league"] if "league" in tbdf.columns else []
    additional_format = [None] if "league" in tbdf.columns else []

    player_df["average"] = player_df.wave.rolling(rolling_average, min_periods=1, center=True).mean().astype(int)
    player_df = player_df.reset_index(drop=True)
    player_df["battle"] = [" / ".join([bc.shortcut for bc in bcs]) for bcs in player_df.bcs]

    def dataframe_styler(player_df):
        df_copy = player_df.copy()
        # Convert patch objects to strings
        df_copy['patch'] = df_copy['patch'].apply(str)
        return (
            df_copy[["name", "wave", "#", "date", "patch", "battle"] + additional_column]
            .style.apply(
                lambda row: [
                    None,
                    f"color: {player_df[player_df['date'] == row.date].wave_role_color.iloc[0]}",
                    None,
                    None,
                    None,
                    None,
                ]
                + additional_format,
                axis=1,
            )
            .map(color_position, subset=["#"])
        )

    player_df = player_df.rename({"tourney_name": "name", "position": "#"}, axis=1)
    raw_data_tab.dataframe(dataframe_styler(player_df), use_container_width=True, height=800)

    small_df = player_df.loc[:9]
    info_tab.write(
        '<div style="overflow-x:auto;">' + dataframe_styler(small_df).to_html(escape=False) + "</div>",
        unsafe_allow_html=True,
    )

    write_for_each_patch(patch_tab, player_df)

    player_id = player_df.iloc[0].id


def filter_lower_leagues(df):
    leagues_in = set(df.league)

    for league in leagues:
        if league in leagues_in:
            break

    df = df[df.league == league]
    return df


def draw_info_tab(info_tab, user, player_id, player_df, hidden_features):
    # Create a container for all link-related content
    link_container = info_tab.container()

    # Generate URLs
    player_url = f"https://{BASE_URL}/player?" + urlencode({"player": player_id}, doseq=True)
    bracket_url = f"https://{BASE_URL}/livebracketview?" + urlencode({"player_id": player_id}, doseq=True)
    comparison_url = f"https://{BASE_URL}/comparison?bracket_player={player_id}"

    # Create three columns for the links
    link1_col, link2_col, link3_col = link_container.columns(3)

    # Display links in columns (side by side)
    link1_col.write(f'<a href="{player_url}">🔗 Player Profile</a>', unsafe_allow_html=True)
    link2_col.write(f'<a href="{bracket_url}">🔗 Live Bracket View</a>', unsafe_allow_html=True)
    link3_col.write(f'<a href="{comparison_url}">🔗 Live Bracket Player Comparison</a>', unsafe_allow_html=True)

    # Show the raw URLs for copying in an expander
    with st.expander("Copy URLs"):
        st.code(player_url, language="text")
        st.code(bracket_url, language="text")
        st.code(comparison_url, language="text")

    # Continue with the rest of the info tab content
    handle_sus_or_banned_ids(info_tab, player_id)

    # Escape real_name when used directly in HTML
    real_name = escape(player_df.iloc[0].real_name)

    if hidden_features:
        info_tab.write(
            f"<a href='https://admin.thetower.lol/admin/sus/susperson/add/?player_id={player_df.iloc[0].id}&name={escape(real_name)}' target='_blank'>🔗 sus me</a>",
            unsafe_allow_html=True,
        )

    avatar = player_df.iloc[0].avatar
    relic = player_df.iloc[0].relic

    if avatar in [35, 36, 39, 42, 44, 45, 46]:
        extension = "webp"
    else:
        extension = "png"

    avatar_string = f"<img src='./app/static/Tower_Skins/{avatar}.{extension}' width=100>" if avatar > 0 else ""

    # Check if the relic exists in all_relics dictionary to avoid KeyError
    if relic in all_relics:
        title = f"title='{all_relics[relic][0]}, {all_relics[relic][2]} {all_relics[relic][3]}'"
        relic_url = f"<img src='./app/static/Tower_Relics/{all_relics[relic][1]}' width=100, {title}>" if relic >= 0 else ""
    else:
        # Handle missing relic gracefully
        relic_url = ""

    tourney_join = "✅" if check_all_live_entry(player_df.iloc[0].id) else "⛔"

    # Get creator code from KnownPlayer model
    creator_code = ""
    try:
        # Look up the player by their player ID
        player_id_value = player_df.iloc[0].id

        player_ids = PlayerId.objects.filter(id=player_id_value)
        if player_ids.exists():
            known_player = player_ids.first().player
            if known_player.creator_code:
                creator_code = f"<div style='font-size: 15px'>Creator code: <span style='color:#cd4b3d; font-weight:bold;'>{known_player.creator_code}</span> <a href='https://store.techtreegames.com/thetower/' target='_blank' style='text-decoration: none;'>🏪</a></div>"
    except Exception:
        # Silently fail if there's any issue looking up the creator code
        pass

    info_tab.write(
        f"<table class='top'><tr><td>{avatar_string}</td><td><div style='font-size: 30px'><span style='vertical-align: middle;'>{real_name}</span></div><div style='font-size: 15px'>ID: {player_df.iloc[0].id}</div><div style='font-size: 15px'>Joined the recent tourney {tourney_join}</div>{creator_code}</td><td>{relic_url}</td></tr></table>",
        unsafe_allow_html=True,
    )


def write_for_each_patch(patch_tab, player_df):
    wave_data = []
    position_data = []

    for patch, patch_df in player_df.groupby("patch"):
        max_wave = patch_df.wave.max()
        max_wave_data = patch_df[patch_df.wave == max_wave].iloc[0]

        max_pos = patch_df["#"].min()
        max_pos_data = patch_df[patch_df["#"] == max_pos].iloc[0]

        # Convert patch to string using its __str__ method
        patch_str = str(patch)

        wave_data.append(
            {
                "patch": patch_str,
                "max_wave": max_wave,
                "tourney_name": max_wave_data["name"],
                "date": max_wave_data.date,
                "battle_conditions": ", ".join(max_wave_data.bcs.values_list("shortcut", flat=True)),
            }
        )

        position_data.append(
            {
                "patch": patch_str,
                "max_position": max_pos,
                "tourney_name": max_pos_data["name"],
                "date": max_pos_data.date,
                "battle_conditions": ", ".join(max_pos_data.bcs.values_list("shortcut", flat=True)),
            }
        )

    wave_data = natsorted(wave_data, key=lambda x: x["patch"], reverse=True)
    position_data = natsorted(position_data, key=lambda x: x["patch"], reverse=True)

    wave_df = pd.DataFrame(wave_data).reset_index(drop=True)
    position_df = pd.DataFrame(position_data).reset_index(drop=True)

    wave_tbdf = wave_df[["patch", "max_wave", "tourney_name", "date", "battle_conditions"]].style.apply(
        lambda row: [
            None,
            None,
            None,
            None,
            None,
        ],
        axis=1,
    )

    position_tbdf = position_df[["patch", "max_position", "tourney_name", "date", "battle_conditions"]].style.apply(
        lambda row: [
            None,
            None,
            None,
            None,
            None,
        ],
        axis=1,
    )

    patch_tab.write("Best wave per patch")
    patch_tab.dataframe(wave_tbdf)

    patch_tab.write("Best position per patch")
    patch_tab.dataframe(position_tbdf)


def handle_start_date_loop(fig, graph_position_instead, tbdf):
    for index, (start, version_minor, version_patch, interim) in enumerate(
        Patch.objects.all().values_list("start_date", "version_minor", "version_patch", "interim")
    ):
        name = f"0.{version_minor}.{version_patch}"
        interim = " interim" if interim else ""

        if start < tbdf.date.min() - datetime.timedelta(days=2) or start > tbdf.date.max() + datetime.timedelta(days=3):
            continue

        fig.add_vline(x=start, line_width=3, line_dash="dash", line_color="#888", opacity=0.4)
        fig.add_annotation(
            x=start,
            y=(tbdf.position.min() + 10 * (index % 5)) if graph_position_instead else (tbdf.wave.max() - 150 * (index % 5 + 1)),
            text=f"Patch {name}{interim} start",
            showarrow=True,
            arrowhead=1,
        )


def handle_is_graph_position(average_foreground, fig, rolling_average, tbdf):
    foreground_kwargs = {}
    background_kwargs = dict(line_dash="dot", line_color="#FF4B4B", opacity=0.6)
    fig.add_trace(
        go.Scatter(
            x=tbdf.date,
            y=tbdf.position,
            name="Tourney position",
            **foreground_kwargs if not average_foreground else background_kwargs,
        ),
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(
            x=tbdf.date,
            y=tbdf.position_average,
            name=f"{rolling_average} tourney moving average",
            **foreground_kwargs if average_foreground else background_kwargs,
        ),
        secondary_y=True,
    )
    fig.update_yaxes(secondary_y=True, range=[tbdf.position.max() + 20, 0])


def handle_not_graph_position_instead(average_foreground, colors, fig, rolling_average, stratas, tbdf):
    foreground_kwargs = {}
    background_kwargs = dict(line_dash="dot", line_color="#888", opacity=0.6)
    fig.add_trace(
        go.Scatter(
            x=tbdf.date,
            y=tbdf.wave,
            name="Wave (left axis)",
            customdata=tbdf.bcs,
            hovertemplate="%{y}, BC: %{customdata}",
            marker=dict(size=7, opacity=1),
            line=dict(width=2, color="#FF4B4B"),
            **foreground_kwargs if not average_foreground else background_kwargs,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=tbdf.date,
            y=tbdf.average,
            name=f"{rolling_average} tourney moving average",
            **foreground_kwargs if average_foreground else background_kwargs,
        )
    )

    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))


def handle_colors_dependant_on_patch(patch, player_df):
    if isinstance(patch, Patch):
        patch_df = player_df[player_df.patch == patch]

        if patch.version_minor >= 18:
            colors, stratas = colors_018, stratas_boundaries_018
        else:
            colors, stratas = colors_017, stratas_boundaries
    elif patch == Graph.last_16.value:
        patch_df = player_df[player_df.date.isin(sorted(player_df.date.unique())[-16:])]
        colors, stratas = colors_018, stratas_boundaries_018
    else:
        patch_df = player_df
        colors, stratas = colors_018, stratas_boundaries_018
    return colors, patch_df, stratas


def handle_sus_or_banned_ids(info_tab, player_id):
    if hidden_features:
        if is_support_flagged(player_id):
            info_tab.warning("This player is currently (soft/hard) banned.")
        elif is_sus(player_id):
            info_tab.warning("This player is currently sussed.")
        elif is_shun(player_id):
            info_tab.warning("This player is currently shunned.")
        elif is_under_review(player_id):
            info_tab.warning("This player is under review.")


compute_player_lookup()
