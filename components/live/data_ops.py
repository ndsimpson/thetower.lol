from functools import wraps

import pandas as pd
import streamlit as st

from dtower.tourney_results.tourney_utils import get_live_df, get_shun_ids

# Cache configuration
CACHE_TTL_SECONDS = 3600  # 60 minutes cache duration


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_live_data(league: str, shun: bool = False) -> pd.DataFrame:
    """
    Get and cache live tournament data.

    Args:
        league: League identifier
        shun: Whether to include shunned players

    Returns:
        DataFrame containing live tournament data
    """
    return get_live_df(league, shun)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_processed_data(league: str, shun: bool = False):
    """
    Get processed tournament data with common transformations.

    Args:
        league: League identifier
        shun: Whether to include shunned players

    Returns:
        Tuple containing:
        - Complete DataFrame
        - Top 25 players DataFrame
        - Latest data DataFrame
        - First moment datetime
        - Last moment datetime
    """
    df = get_live_data(league, shun)

    # Common data processing
    group_by_id = df.groupby("player_id")
    top_25 = group_by_id.wave.max().sort_values(ascending=False).index[:25]
    tdf = df[df.player_id.isin(top_25)]

    first_moment = tdf.datetime.iloc[-1]
    last_moment = tdf.datetime.iloc[0]
    ldf = df[df.datetime == last_moment].copy()
    ldf.index = ldf.index + 1

    return df, tdf, ldf, first_moment, last_moment


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_bracket_data(df: pd.DataFrame):
    """
    Process bracket-specific data.

    Args:
        df: DataFrame containing tournament data

    Returns:
        Tuple containing:
        - bracket_order: List of brackets ordered by creation time
        - fullish_brackets: List of brackets with >= 28 players
    """
    df["datetime"] = pd.to_datetime(df["datetime"])
    bracket_order = df.groupby("bracket")["datetime"].min().sort_values().index.tolist()

    bracket_counts = dict(df.groupby("bracket").player_id.unique().map(lambda player_ids: len(player_ids)))
    fullish_brackets = [bracket for bracket, count in bracket_counts.items() if count >= 28]

    return bracket_order, fullish_brackets


def process_display_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Process display names by adding player_id to duplicated names.

    Args:
        df: DataFrame containing player data

    Returns:
        DataFrame with processed display names
    """
    # Create a copy to avoid warnings
    result = df.copy()

    # Calculate name duplicates
    name_counts = result.groupby("real_name")["player_id"].nunique()
    duplicate_names = name_counts[name_counts > 1].index

    # Create display_name column using loc
    result.loc[:, "display_name"] = result["real_name"]

    if len(duplicate_names) > 0:
        # Add player_id to duplicated names
        mask = result["real_name"].isin(duplicate_names)
        result.loc[mask, "display_name"] = (
            result.loc[mask, "real_name"] +
            " (" +
            result.loc[mask, "player_id"].astype(str) +
            ")"
        )

    return result


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_placement_analysis_data(league: str):
    """
    Get processed data specifically for placement analysis.

    Args:
        league: League identifier

    Returns:
        Tuple containing:
        - Clean DataFrame
        - Latest time
        - Bracket creation times dict
    """
    df = get_live_data(league, True)

    # Filter for fullish brackets
    bracket_counts = dict(df.groupby("bracket").player_id.unique().map(lambda player_ids: len(player_ids)))
    fullish_brackets = [bracket for bracket, count in bracket_counts.items() if count >= 28]
    df = df[df.bracket.isin(fullish_brackets)]

    # Cast real_name to string
    df["real_name"] = df["real_name"].astype("str")

    # Get latest time point
    latest_time = df["datetime"].max()

    # Get bracket creation times
    bracket_creation_times = {
        bracket: df[df["bracket"] == bracket]["datetime"].min()
        for bracket in df["bracket"].unique()
    }

    # Remove shunned players
    sus_ids = get_shun_ids()
    clean_df = df[~df.player_id.isin(sus_ids)].copy()

    return clean_df, latest_time, bracket_creation_times


def analyze_wave_placement(df, wave_to_analyze, latest_time):
    """
    Analyze placement of a specific wave across all brackets.

    Args:
        df: DataFrame containing tournament data
        wave_to_analyze: Wave number to analyze
        latest_time: Latest time point in the data

    Returns:
        List of dictionaries containing placement analysis results
    """
    results = []
    for bracket in sorted(df["bracket"].unique()):
        bracket_df = df[df["bracket"] == bracket]
        start_time = bracket_df["datetime"].min()
        last_bracket_df = bracket_df[bracket_df["datetime"] == latest_time].sort_values("wave", ascending=False)

        better_or_equal = last_bracket_df[last_bracket_df["wave"] > wave_to_analyze].shape[0]
        total = last_bracket_df.shape[0]
        rank = better_or_equal + 1

        results.append({
            "Bracket": bracket,
            "Would Place": f"{rank}/{total}",
            "Top Wave": last_bracket_df["wave"].max(),
            "Median Wave": int(last_bracket_df["wave"].median()),
            "Players Above": better_or_equal,
            "Start Time": start_time,
        })

    return results


def process_bracket_selection(df, selected_real_name, selected_player_id, selected_bracket, bracket_order):
    """
    Process bracket selection logic from different input methods.

    Args:
        df: DataFrame containing tournament data
        selected_real_name: Selected player name
        selected_player_id: Selected player ID
        selected_bracket: Directly selected bracket
        bracket_order: List of brackets in order

    Returns:
        Tuple containing:
        - bracket_id: Selected bracket ID
        - tdf: DataFrame filtered for selected bracket
        - selected_real_name: Resolved player name
        - bracket_index: Index of bracket in bracket_order
    """
    try:
        if selected_bracket:
            bracket_id = selected_bracket
            tdf = df[df.bracket == bracket_id]
            selected_real_name = tdf.real_name.iloc[0]
            bracket_index = bracket_order.index(bracket_id)
        elif selected_player_id:
            selected_real_name = df[df.player_id == selected_player_id].real_name.iloc[0]
            sdf = df[df.real_name == selected_real_name]
            bracket_id = sdf.bracket.iloc[0]
            tdf = df[df.bracket == bracket_id]
            bracket_index = bracket_order.index(bracket_id)
        elif selected_real_name:
            sdf = df[df.real_name == selected_real_name]
            bracket_id = sdf.bracket.iloc[0]
            tdf = df[df.bracket == bracket_id]
            bracket_index = bracket_order.index(bracket_id)
        return bracket_id, tdf, selected_real_name, bracket_index
    except Exception as e:
        raise ValueError(f"Selection not found: {str(e)}")


def get_bracket_stats(df):
    """
    Calculate bracket statistics.

    Args:
        df: DataFrame containing tournament data

    Returns:
        Dictionary containing bracket statistics
    """
    group_by_bracket = df.groupby("bracket").wave
    return {
        "total_brackets": df.groupby("bracket").ngroups,
        "highest_total": group_by_bracket.sum().sort_values(ascending=False).index[0],
        "highest_median": group_by_bracket.median().sort_values(ascending=False).index[0],
        "lowest_total": group_by_bracket.sum().sort_values(ascending=True).index[0],
        "lowest_median": group_by_bracket.median().sort_values(ascending=True).index[0]
    }


def handle_no_data():
    """Standard handler for when no tournament data is available"""
    st.info("No current data, wait until the tourney day")
    return None


def require_tournament_data(func):
    """Decorator to handle cases where tournament data is not available"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (IndexError, ValueError):
            return handle_no_data()
    return wrapper


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_cached_plot_data(df):
    """Process dataframe for plotting, with better error handling."""
    plot_data = df.copy()

    # Only convert datetime if the column exists
    if 'datetime' in plot_data.columns:
        plot_data["datetime"] = pd.to_datetime(plot_data["datetime"])

    return plot_data


def initialize_bracket_state(bracket_order):
    """Initialize or update bracket navigation state"""
    if "current_bracket_idx" not in st.session_state:
        st.session_state.current_bracket_idx = 0

    return st.session_state.current_bracket_idx


def update_bracket_index(new_index, max_index):
    """Update bracket navigation index with bounds checking"""
    st.session_state.current_bracket_idx = max(0, min(new_index, max_index))


def clear_cache():
    """Clear all cached data in Streamlit"""
    st.cache_data.clear()
