import pandas as pd
import plotly.express as px
import streamlit as st

from components.util import get_league_filter, get_options

from dtower.tourney_results.constants import leagues
from dtower.tourney_results.tourney_utils import get_live_df


@st.cache_data(ttl=300)
def get_data(league):
    return get_live_df(league)


def bracket_analysis():
    print("livebracketanalysis")
    options = get_options(links=False)
    with st.sidebar:
        league_index = get_league_filter(options.current_league)
        league = st.radio("League", leagues, league_index)

    with st.sidebar:
        # Check if mobile view
        is_mobile = st.session_state.get("mobile_view", False)
        st.checkbox("Mobile view", value=is_mobile, key="mobile_view")

    try:
        df = get_data(league)
    except (IndexError, ValueError):
        st.info("No current data, wait until the tourney day")
        return

    # Get data
    group_by_id = df.groupby("player_id")
    top_25 = group_by_id.wave.max().sort_values(ascending=False).index[:25]
    tdf = df[df.player_id.isin(top_25)]

    last_moment = tdf.datetime.iloc[0]
    ldf = df[df.datetime == last_moment]
    ldf.index = ldf.index + 1

    group_by_bracket = ldf.groupby("bracket").wave
    bracket_from_hell = group_by_bracket.sum().sort_values(ascending=False).index[0]
    bracket_from_hell_by_median = group_by_bracket.median().sort_values(ascending=False).index[0]
    bracket_from_heaven = group_by_bracket.sum().sort_values(ascending=True).index[0]
    bracket_from_heaven_by_median = group_by_bracket.median().sort_values(ascending=True).index[0]

    st.write(f"Total closed brackets until now: {ldf.groupby('bracket').ngroups}")

    # Create combined histogram for median and mean waves
    # Calculate top positions for each bracket
    def get_top_n(group, n):
        return group.nlargest(n).iloc[-1] if len(group) >= n else None

    stats_df = pd.DataFrame({
        "Top 1": group_by_bracket.apply(lambda x: get_top_n(x, 1)),
        "Top 4": group_by_bracket.apply(lambda x: get_top_n(x, 4)),
        "Top 10": group_by_bracket.apply(lambda x: get_top_n(x, 10)),
        "Top 15": group_by_bracket.apply(lambda x: get_top_n(x, 15)),
    }).melt()

    # Create histogram
    fig1 = px.histogram(
        stats_df,
        x="value",
        color="variable",
        barmode="overlay",
        opacity=0.7,
        title="Distribution of Top Positions per Bracket",
        labels={"value": "Waves", "count": "Number of Brackets", "variable": "Position"},
        height=300,
    )

    fig1.update_layout(
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99)
    )
    st.plotly_chart(fig1, use_container_width=True)

    cols = st.columns(2 if not is_mobile else 1)

    with cols[0]:
        st.write(f"Highest total waves: {bracket_from_hell}")
        st.dataframe(ldf[ldf.bracket == bracket_from_hell][["real_name", "wave", "datetime"]])

        st.write(f"Lowest total waves: {bracket_from_heaven}")
        st.dataframe(ldf[ldf.bracket == bracket_from_heaven][["real_name", "wave", "datetime"]])

    with cols[1]:
        st.write(f"Highest median waves: {bracket_from_hell_by_median}")
        st.dataframe(ldf[ldf.bracket == bracket_from_hell_by_median][["real_name", "wave", "datetime"]])

        st.write(f"Lowest median waves: {bracket_from_heaven_by_median}")
        st.dataframe(ldf[ldf.bracket == bracket_from_heaven_by_median][["real_name", "wave", "datetime"]])


bracket_analysis()
