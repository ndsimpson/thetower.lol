import datetime
import os
import re
from pathlib import Path
from typing import Optional

import streamlit as st

from components.util import get_options, get_league_selection, escape_df_html

from dtower.tourney_results.constants import (
    Graph,
    Options,
    all_relics,
    how_many_results_hidden_site,
    how_many_results_public_site,
    sus_person,
)
from dtower.tourney_results.data import get_results_for_patch, get_sus_ids, get_tourneys
from dtower.tourney_results.formatting import am_i_sus, color_position__top, make_player_url, strike
from dtower.tourney_results.models import PatchNew as Patch
from dtower.tourney_results.models import TourneyResult


class Results:
    def __init__(self, options: Options, league: Optional[str] = None) -> None:
        self.league = league
        self.options = options
        self.hidden_features = os.environ.get("HIDDEN_FEATURES")
        self.sus_ids = get_sus_ids()
        self.show_hist: Optional[bool] = None  # self.congrats_toggle = False

    def _make_sus_link(self, id, name):
        return f"<a href='https://admin.thetower.lol/admin/sus/susperson/add/?player_id={id}&name={name}' target='_blank'>🔗 sus</a>"

    def _styler(self):
        with open("style.css", "r") as infile:
            table_styling = f"<style>{infile.read()}</style>"

        # with open("funny.css", "r") as infile:
        #     funny_styling = f"<style>{infile.read()}</style>"

        st.write(table_styling, unsafe_allow_html=True)
        # st.write(funny_styling, unsafe_allow_html=True)

    def top_of_results(self) -> str:
        patch_col, tourney_col, self.results_col, self.results_col_page = st.columns([1.0, 2, 1, 1.2])

        # Store selected patch in session state for league selection
        patch = patch_col.selectbox("Patch:", Patch.objects.all().order_by("-start_date"), index=0)
        st.session_state.selected_patch = patch

        possible_results = get_results_for_patch(patch, league=self.league)
        self.dates = possible_results.values_list("date", flat=True)
        bcs = [res.conditions.all() for res in possible_results]

        date_to_bc = dict(zip(self.dates, bcs))
        tourneys = sorted(self.dates, reverse=True)
        tourney_titles = [date if not date_to_bc[date] else f"{date}: {', '.join(item.shortcut for item in date_to_bc[date])}" for date in tourneys]
        tourney_title = tourney_col.selectbox("Select tournament:", tourney_titles)

        chosen_tourney = tourneys[tourney_titles.index(tourney_title)]

        if bcs := date_to_bc[chosen_tourney]:
            st.write(f"Battle Conditions: {', '.join(item.name for item in bcs)}")

        return chosen_tourney

    def prepare_data(self, current_page: int, step: int, date: datetime.date):
        begin = (current_page - 1) * step

        public = {"public": True} if not self.hidden_features else {}

        qs = TourneyResult.objects.filter(league=self.league, date=date, **public)

        if qs and qs[0].overview:
            with st.expander("Writeup..."):
                st.write(qs[0].overview)

        self.df = get_tourneys(qs, offset=begin, limit=step)
        self.df = self.df.reset_index(drop=True)

        if self.df.empty:
            return None

        if not self.hidden_features:
            to_be_displayed = self.df[~self.df.id.isin(get_sus_ids())]
        else:
            to_be_displayed = self.df

        to_be_displayed = to_be_displayed.reset_index(drop=True)

        # Early escape/sanitize names to prevent XSS
        to_be_displayed = escape_df_html(to_be_displayed, ['real_name', 'tourney_name'])

        if current_page == 1:
            for position, medal in zip([1, 2, 3], [" 🥇", " 🥈", " 🥉"]):
                if not to_be_displayed[to_be_displayed.position == position].empty:
                    to_be_displayed.loc[to_be_displayed[to_be_displayed.position == position].index[0], "real_name"] = (
                        to_be_displayed.loc[to_be_displayed[to_be_displayed.position == position].index[0], "real_name"] + medal
                    )

        def make_avatar(avatar_id):
            all_avatars = {int(re.findall(r"\d+", item.name.split(".")[0])[0]) for item in (Path("components") / "static" / "Tower_Skins").glob("*.*")}

            if avatar_id == -1 or avatar_id not in all_avatars:
                return ""

            if avatar_id in [35, 36, 39, 42, 44, 45, 46]:
                extension = "webp"
            else:
                extension = "png"

            return f"<img src='./app/static/Tower_Skins/{avatar_id}.{extension}' style='width:32px; height:32px; object-fit:contain'>"

        def make_relic(relic_id):
            if relic_id == -1 or relic_id not in all_relics:
                return ""

            return f"<img src='./app/static/Tower_Relics/{all_relics[relic_id][1]}' width='32' title='{all_relics[relic_id][0]}, {all_relics[relic_id][2]} {all_relics[relic_id][3]}'>"

        to_be_displayed["real_name"] = [sus_person if id_ in self.sus_ids else name for id_, name in zip(to_be_displayed.id, to_be_displayed.real_name)]

        to_be_displayed["tourney_name"] = [strike(name) if id_ in self.sus_ids else name for id_, name in zip(to_be_displayed.id, to_be_displayed.tourney_name)]
        to_be_displayed["avatar"] = to_be_displayed.avatar.map(make_avatar)
        to_be_displayed["relic"] = to_be_displayed.relic.map(make_relic)

        to_be_displayed = to_be_displayed.rename(columns={"position": "#", "verified": "✓", "avatar": "⬡"})
        to_be_displayed["real_name"] = [make_player_url(name, id=id_) for name, id_ in zip(to_be_displayed.real_name, to_be_displayed.id)]
        return to_be_displayed

    def show_hist_preparation(self, to_be_displayed, date: str):
        to_be_displayed = to_be_displayed[["id", "#", "tourney_name", "real_name", "wave", "✓"]]
        to_be_displayed = to_be_displayed.rename({"wave": date}, axis=1)

        common_data = list(self.dates)

        current_date_index = common_data.index(date)
        previous_4_dates = common_data[current_date_index - 4 : current_date_index][::-1]

        prev_dfs = {date: self.df[self.df["date"] == date].reset_index(drop=True) for date in previous_4_dates}

        for date_iter, prev_df in prev_dfs.items():
            to_be_displayed[date_iter] = [mini_df.iloc[0].wave if not (mini_df := prev_df[prev_df.id == id_]).empty else 0 for id_ in to_be_displayed.id]

        indices = ["#", "tourney_name", "real_name", *[date, *previous_4_dates], "✓", "id"]

        if self.hidden_features:
            to_be_displayed["sus_me"] = [self._make_sus_link(id, name) for id, name in zip(to_be_displayed.id, to_be_displayed.tourney_name)]
            indices += ["sus_me"]

        to_be_displayed = (
            to_be_displayed[indices]
            .style.apply(
                lambda row: [
                    None,
                    None,
                    f"color: {self.df[self.df['position'] == row['#']].name_role_color.iloc[0]}",
                    f"color: {self.df[self.df['position'] == row['#']].wave_role_color.iloc[0]}",
                    *[
                        f"color: {mini_df.wave_role_color.iloc[0] if not (mini_df := prev_df[prev_df.id == row.id]).empty else '#FFF'}"
                        for prev_df in prev_dfs.values()
                    ],
                    None,
                    None,
                ],
                axis=1,
            )
            .map(color_position__top, subset=["#"])
            .map(am_i_sus, subset=["real_name"])
        )

        return to_be_displayed

    def regular_preparation(self, to_be_displayed):
        indices = ["#", "⬡", "tourney_name", "real_name", "relic", "wave", "✓"]
        styling = lambda row: [
            None,
            None,
            None,  # f"color: {filtered_df[filtered_df['position']==row['#']].name_role_color.iloc[0]}",
            None,
            None,
            f"color: {self.df[self.df['position'] == row['#']].wave_role_color.iloc[0]}",
            None,
        ]

        if self.hidden_features:
            indices += ["id", "sus_me"]
            styling = lambda row: [
                None,
                None,
                None,  # f"color: {filtered_df[filtered_df['position']==row['#']].name_role_color.iloc[0]}",
                None,
                None,
                f"color: {self.df[self.df['position'] == row['#']].wave_role_color.iloc[0]}",
                None,
                None,
                None,
            ]

        if self.hidden_features:
            to_be_displayed["sus_me"] = [self._make_sus_link(id, name) for id, name in zip(to_be_displayed.id, to_be_displayed.tourney_name)]

        to_be_displayed = to_be_displayed[indices].style.apply(styling, axis=1).map(color_position__top, subset=["#"]).map(am_i_sus, subset=["real_name"])

        return to_be_displayed

    def compute_results(self) -> None:
        date = self.top_of_results()

        step = 100
        total_results = how_many_results_hidden_site if self.hidden_features else how_many_results_public_site

        step = self.results_col_page.number_input("Results per page", min_value=100, max_value=max(total_results, 100), step=100)
        total_pages = total_results // step if total_results // step == total_results / step else total_results // step + 1
        current_page = self.results_col.number_input("Page", min_value=1, max_value=total_pages, step=1)

        to_be_displayed = self.prepare_data(current_page=current_page, step=step, date=date)

        if to_be_displayed is None:
            st.warning("Failed to display results, likely loss of data.")
            return None

        if self.show_hist:
            to_be_displayed_styler = self.show_hist_preparation(to_be_displayed, date)
        else:
            self._styler()
            to_be_displayed_styler = self.regular_preparation(to_be_displayed)

        st.write(to_be_displayed_styler.hide(axis="index").to_html(escape=False), unsafe_allow_html=True)


def compute_results(options: Options):
    print("results")
    options = get_options(links=False)

    # Get currently selected patch from session state or default to latest
    patch = None
    if 'selected_patch' in st.session_state:
        patch = st.session_state.selected_patch

    # Use patch-aware league selection
    league = get_league_selection(options, patch=patch)

    Results(options, league=league).compute_results()


options = Options(links_toggle=True, default_graph=Graph.last_16.value, average_foreground=True)
compute_results(options)
