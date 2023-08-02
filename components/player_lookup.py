import datetime
import glob
import os
from urllib.parse import urlencode

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from components.util import get_options
from dtower.sus.models import SusPerson
from dtower.tourney_results.constants import (
    Graph,
    Options,
    champ,
    colors_017,
    colors_018,
    league_to_folder,
    leagues,
    stratas_boundaries,
    stratas_boundaries_018,
)
from dtower.tourney_results.data import (
    get_banned_ids,
    get_id_lookup,
    get_patches,
    get_player_list,
    get_soft_banned_ids,
    get_sus_ids,
    load_tourney_results,
)
from dtower.tourney_results.formatting import color_position
from dtower.tourney_results.models import PatchNew as Patch

sus_ids = set(SusPerson.objects.filter(sus=True).values_list("player_id", flat=True))


def compute_player_lookup(df, options: Options):
    hidden_features = os.environ.get("HIDDEN_FEATURES")

    league_col, user_col = st.columns([1, 2])

    league = league_col.selectbox("League?", leagues)

    if league != champ:
        df = load_tourney_results(folder=league_to_folder[league])

    first_choices, all_real_names, all_tourney_names, all_user_ids, last_top_scorer = get_player_list(df)
    player_list = [""] + first_choices + sorted(all_real_names | all_tourney_names) + all_user_ids

    player_list = handle_initial_choices(hidden_features, options, player_list, sus_ids)

    user = user_col.selectbox("Which user would you like to lookup?", player_list)

    # lol
    if user == "Soelent":
        st.image("towerfans.jpg")

    if not user:
        return

    info_tab, graph_tab, raw_data_tab, patch_tab = st.tabs(["Info", "Tourney performance graph", "Results data", "Patch best"])

    id_mapping = get_id_lookup()

    df, player_df = find_user(all_real_names, all_tourney_names, all_user_ids, df, first_choices, id_mapping, user)

    # todo should be extracted
    if len(player_df.id.unique()) >= 2:
        potential_ids = player_df.id.unique().tolist()
        aggreg = player_df.groupby("id").count()
        most_common_id = aggreg[aggreg.tourney_name == aggreg.tourney_name.max()].index[0]
        user_ids = graph_tab.multiselect(
            "Since multiple players had the same username, please choose id. If you are confident the same user used multiple ids, you can select multiple. If it's different users, data below won't make much sense",
            potential_ids,
            default=most_common_id,
        )

        if not user_ids:
            return

        player_df = df[df.id.isin(user_ids)]
    else:
        player_df = df[df.id == player_df.iloc[0].id]

    player_df = player_df.sort_values("date", ascending=False)

    draw_info_tab(info_tab, user, player_df)

    patches_options = sorted([patch for patch in get_patches() if patch.version_minor], key=lambda patch: patch.start_date, reverse=True)
    graph_options = [options.default_graph.value] + [
        value for value in list(Graph.__members__.keys()) + patches_options if value != options.default_graph.value
    ]
    patch_col, average_col = graph_tab.columns([1, 1])
    patch = patch_col.selectbox("Limit results to a patch? (see side bar to change default)", graph_options)
    rolling_average = average_col.slider("Use rolling average for results from how many tourneys?", min_value=1, max_value=10, value=5)

    colors, patch_df, stratas = handle_colors_dependant_on_patch(df, patch, player_df)

    tbdf = patch_df.reset_index(drop=True)
    tbdf["average"] = tbdf.wave.rolling(rolling_average, min_periods=1, center=True).mean().astype(int)
    tbdf["position_average"] = tbdf.position.rolling(rolling_average, min_periods=1, center=True).mean().astype(int)

    if len(tbdf) > 1:
        pos_col, tweak_col = graph_tab.columns([1, 1])

        graph_position_instead = pos_col.checkbox("Graph position instead")
        average_foreground = tweak_col.checkbox("Average in the foreground?", value=True)
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        if not graph_position_instead:
            handle_not_graph_position_instead(average_foreground, colors, fig, rolling_average, stratas, tbdf)
        else:
            handle_is_graph_position(average_foreground, fig, rolling_average, tbdf)

        handle_start_date_loop(fig, graph_position_instead, tbdf)

        graph_tab.plotly_chart(fig)

    additional_column = ["league"] if "league" in tbdf.columns else []
    additional_format = [None] if "league" in tbdf.columns else []

    player_df["average"] = player_df.wave.rolling(rolling_average, min_periods=1, center=True).mean().astype(int)
    player_df = player_df.reset_index(drop=True)

    to_be_displayed = (
        player_df[["date", "tourney_name", "wave", "position", "average"] + additional_column]
        .style.apply(
            lambda row: [None, f"color: {player_df[player_df['date']==row.date].name_role_color.iloc[0]}", None, None, None] + additional_format,
            axis=1,
        )
        .apply(
            lambda row: [None, None, f"color: {player_df[player_df['date']==row.date].wave_role_color.iloc[0]}", None, None] + additional_format,
            axis=1,
        )
        .applymap(color_position, subset=["position"])
    )
    raw_data_tab.dataframe(to_be_displayed, use_container_width=True, height=800)

    write_for_each_patch(patch_tab, player_df)

    info_tab.write(f"User id(s) used: <b>{tbdf.raw_id.unique()}</b>", unsafe_allow_html=True)
    graph_tab.write(f"User id(s) used: <b>{tbdf.raw_id.unique()}</b>", unsafe_allow_html=True)
    raw_data_tab.write(f"User id(s) used: <b>{tbdf.raw_id.unique()}</b>", unsafe_allow_html=True)
    patch_tab.write(f"User id(s) used: <b>{tbdf.raw_id.unique()}</b>", unsafe_allow_html=True)


def draw_info_tab(info_tab, user, player_df):
    info_tab.code("https://thetower.lol/Player%20Lookup?" + urlencode({"player": user}, doseq=True))
    handle_sus_or_banned_ids(info_tab, player_df.iloc[0].id, sus_ids)

    real_name = player_df.iloc[0].real_name
    current_role_color = player_df.iloc[0].name_role.color
    patches_active = player_df.patch.unique()

    avatar_col, name_col, relic_col = info_tab.columns([1, 4, 1])

    if (avatar := player_df.iloc[0].avatar) != -1:
        avatar_col.image(glob.glob(f"Tower_Skins/{avatar}-*.png")[0], width=100)

    name_col.write(f"<div style='font-size: 30px; color: {current_role_color}'>{real_name}</div>", unsafe_allow_html=True)
    name_col.write(f"<div style='font-size: 15px'>ID: {player_df.iloc[0].id}</div>", unsafe_allow_html=True)

    if (relic := player_df.iloc[0].relic) != -1:
        relic_col.image(glob.glob(f"Tower_Relics/{relic}-*.png")[0], width=100)

    info_tab.write(
        f"Player <font color='{current_role_color}'>{real_name}</font> has been noted in tourney results during the following patches: {sorted([patch.version_minor for patch in patches_active])}. (0.17 counts as part of 0.16 since no roles were reset back then)",
        unsafe_allow_html=True,
    )


def write_for_each_patch(patch_tab, player_df):
    real_name = player_df.iloc[0].real_name

    for patch in player_df.patch.unique():
        patch_tab.subheader(
            f"Patch 0.{patch.version_minor if patch.version_minor != 16 else '16-17'}.{patch.version_patch}" + ("" if not patch.beta else " beta")
        )
        patch_df = player_df[player_df.patch == patch]

        patch_role_color = patch_df.iloc[-1].name_role.color

        max_wave = patch_df.wave.max()
        max_pos = patch_df.position.min()

        max_data = patch_df[patch_df.wave == max_wave].iloc[0]
        max_pos_data = patch_df[patch_df.position == max_pos].iloc[0]

        patch_tab.write(
            f"Max wave for <font color='{patch_role_color}'>{real_name}</font> in champ during patch 0.{patch.version_minor}: <font color='{patch_role_color}'>**{max_wave}**</font>, as {max_data.tourney_name} on {max_data.date}"
            f"<br>Best position for <font color='{patch_role_color}'>{real_name}</font> in champ during patch 0.{patch.version_minor}: <font color='{max_pos_data.position_role_color}'>**{max_pos}**</font>, as {max_pos_data.tourney_name} on {max_pos_data.date}",
            unsafe_allow_html=True,
        )


def handle_start_date_loop(fig, graph_position_instead, tbdf):
    for index, (start, version_minor, version_patch, beta) in enumerate(
        Patch.objects.all().values_list("start_date", "version_minor", "version_patch", "beta")
    ):
        name = f"0.{version_minor}.{version_patch}"
        beta = " beta" if beta else ""

        if start < tbdf.date.min() - datetime.timedelta(days=2) or start > tbdf.date.max() + datetime.timedelta(days=3):
            continue

        fig.add_vline(x=start, line_width=3, line_dash="dash", line_color="#888", opacity=0.4)
        fig.add_annotation(
            x=start,
            y=(tbdf.position.min() + 10 * (index % 2)) if graph_position_instead else (tbdf.wave.max() - 300 * (index % 2 + 1)),
            text=f"Patch {name}{beta} start",
            showarrow=True,
            arrowhead=1,
        )


def handle_is_graph_position(average_foreground, fig, rolling_average, tbdf):
    foreground_kwargs = {}
    # background_kwargs = dict(line_dash="dot", line_color="#888", opacity=0.6)
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
    fig.update_yaxes(secondary_y=True, range=[200, 0])


def handle_not_graph_position_instead(average_foreground, colors, fig, rolling_average, stratas, tbdf):
    foreground_kwargs = {}
    # background_kwargs = dict(line_dash="dot", line_color="#888", opacity=0.6)
    background_kwargs = dict(line_dash="dot", line_color="#FF4B4B", opacity=0.6)
    fig.add_trace(
        go.Scatter(
            x=tbdf.date,
            y=tbdf.wave,
            name="Wave (left axis)",
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
    min_ = min(tbdf.wave)
    max_ = max(tbdf.wave)
    for color_, strata in zip(colors, stratas):
        if max_ > strata > min_:
            fig.add_hline(y=strata, line_color=color_, line_dash="dash", opacity=0.4, line_width=3)


def handle_colors_dependant_on_patch(df, patch, player_df):
    if isinstance(patch, Patch):
        patch_df = player_df[player_df.patch == patch]

        if patch.version_minor >= 18:
            colors, stratas = colors_018, stratas_boundaries_018
        else:
            colors, stratas = colors_017, stratas_boundaries
    elif patch == Graph.last_16.value:
        patch_df = player_df[player_df.date.isin(df.date.unique()[-16:])]
        colors, stratas = colors_018, stratas_boundaries_018
    else:
        patch_df = player_df
        colors, stratas = colors_018, stratas_boundaries_018
    return colors, patch_df, stratas


def handle_sus_or_banned_ids(info_tab, id_, sus_ids):
    if id_ in get_banned_ids():
        info_tab.warning("This player is banned by the Support team.")
    if id_ in get_soft_banned_ids():
        info_tab.warning("This player is banned by Pog.")
    if id_ in sus_ids:
        info_tab.error("This player is considered sus.")


def find_user(all_real_names, all_tourney_names, all_user_ids, df, first_choices, id_mapping, user):
    def _find_user(all_real_names, all_tourney_names, all_user_ids, first_choices, user):
        if user in (set(first_choices) | all_real_names | all_tourney_names):
            player_df = df[(df.real_name == user) | (df.tourney_name == user)]
        elif user in all_user_ids:
            player_df = df[df.id == id_mapping.get(user, user)]
        else:
            player_df = None

        return player_df

    if (player_df := _find_user(all_real_names, all_tourney_names, all_user_ids, first_choices, user)) is not None:
        return df, player_df
    else:
        # expensive branch, maybe we gotta look in another league? Should only happen if the user is passed as query param

        for league in leagues:
            df = load_tourney_results(folder=league_to_folder[league])

            first_choices, all_real_names, all_tourney_names, all_user_ids, _ = get_player_list(df)

            if (player_df := _find_user(all_real_names, all_tourney_names, all_user_ids, first_choices, user)) is not None:
                return df, player_df

        raise ValueError(f"Could not find user {user}.")


def handle_initial_choices(hidden_features, options, player_list, sus_ids):
    if not hidden_features:
        sus_nicknames = set(SusPerson.objects.filter(sus=True).values_list("name", flat=True))
        player_list = [player for player in player_list if player not in sus_ids | sus_nicknames]
    if options.current_player is not None:
        player_list = [options.current_player] + player_list
    return player_list


if __name__ == "__main__":
    df = load_tourney_results("data")
    options = get_options(links=False)
    compute_player_lookup(df, options=options)
