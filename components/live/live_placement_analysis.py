import logging
import pandas as pd
import plotly.express as px
import streamlit as st
from time import perf_counter

from components.live.ui_components import setup_common_ui
from components.live.data_ops import (
    get_placement_analysis_data,
    analyze_wave_placement,
    require_tournament_data
)


@require_tournament_data
def live_score():
    st.markdown("# Live Placement Analysis")
    logging.info("Starting live placement analysis")
    t2_start = perf_counter()

    # Use common UI setup
    options, league, is_mobile = setup_common_ui()

    # Get placement analysis data
    df, latest_time, bracket_creation_times = get_placement_analysis_data(league)

    # Player selection
    selected_player = st.selectbox(
        "Select player",
        [""] + sorted(df["real_name"].unique()),
        key=f"player_selector_{league}"
    )
    if not selected_player:
        return

    # Get the player's highest wave
    wave_to_analyze = df[df.real_name == selected_player].wave.max()
    st.write(f"Analyzing placement for {selected_player}'s highest wave: {wave_to_analyze}")

    # Analyze placements
    results = analyze_wave_placement(df, wave_to_analyze, latest_time)

    # Process results for display
    results_df = pd.DataFrame(results)
    results_df["Creation Time"] = results_df["Bracket"].map(bracket_creation_times)
    # Add numeric position column for sorting
    results_df["Position"] = results_df["Would Place"].str.split("/").str[0].astype(int)
    # Sort by creation time initially
    results_df = results_df.sort_values("Creation Time")

    st.write(f"Analysis for wave {wave_to_analyze} (ordered by bracket creation time):")
    # Display dataframe with custom sorting
    st.dataframe(
        results_df.drop(["Creation Time", "Position"], axis=1),
        hide_index=True,
        column_config={
            "Would Place": st.column_config.TextColumn(
                "Would Place",
                help="Player placement in bracket"
            )
        }
    )

    # Calculate player's actual position
    player_bracket = df[df["real_name"] == selected_player]["bracket"].iloc[0]
    player_creation_time = bracket_creation_times[player_bracket]
    player_position = (
        df[(df["bracket"] == player_bracket) & (df["datetime"] == latest_time)]
        .sort_values("wave", ascending=False)
        .index.get_loc(df[(df["bracket"] == player_bracket) & (df["datetime"] == latest_time) & (df["real_name"] == selected_player)].index[0])
        + 1
    )

    # Create plot data
    plot_df = pd.DataFrame({
        "Creation Time": [bracket_creation_times[b] for b in results_df["Bracket"]],
        "Placement": [int(p.split("/")[0]) for p in results_df["Would Place"]],
    })

    # Create placement timeline plot
    fig = px.scatter(
        plot_df,
        x="Creation Time",
        y="Placement",
        title=f"Placement Timeline for {wave_to_analyze} waves",
        labels={"Creation Time": "Bracket Creation Time", "Placement": "Would Place Position"},
        trendline="lowess",
        trendline_options=dict(frac=0.2),
    )

    # Add player's actual position marker
    fig.add_scatter(
        x=[player_creation_time],
        y=[player_position],
        mode="markers",
        marker=dict(symbol="x", size=15, color="red"),
        name="Actual Position",
        showlegend=False,
    )

    # Update plot layout
    fig.update_layout(
        yaxis_title="Position",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    fig.update_yaxes(autorange="reversed")

    st.plotly_chart(fig, use_container_width=True)

    # Log execution time
    t2_stop = perf_counter()
    logging.info(f"Full live_placement_analysis for {league} took {t2_stop - t2_start}")


live_score()
