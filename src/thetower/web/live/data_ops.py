import datetime
import logging
import os
from functools import wraps
from pathlib import Path

import pandas as pd
import streamlit as st

from thetower.backend.tourney_results.tourney_utils import get_full_brackets, get_live_df, get_time, include_shun_enabled

# Cache configuration
CACHE_TTL_SECONDS = 300  # 5 minutes cache duration


def is_caching_disabled():
    """Check if caching should be disabled by looking for the control file."""
    root_dir = Path(__file__).parent.parent.parent
    return (root_dir / "live_cache_disabled").exists()


def cache_data_if_enabled(**cache_args):
    """Decorator that only applies st.cache_data if caching is enabled."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            is_disabled = is_caching_disabled()
            logging.info(f"Cache {'disabled' if is_disabled else 'enabled'} for {func.__name__}")
            if is_disabled:
                return func(*args, **kwargs)
            return st.cache_data(**cache_args)(func)(*args, **kwargs)

        return wrapper

    return decorator


@cache_data_if_enabled(ttl=CACHE_TTL_SECONDS)
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


@cache_data_if_enabled(ttl=CACHE_TTL_SECONDS)
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


@cache_data_if_enabled(ttl=CACHE_TTL_SECONDS)
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
    return get_full_brackets(df)


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
        result.loc[mask, "display_name"] = result.loc[mask, "real_name"] + " (" + result.loc[mask, "player_id"].astype(str) + ")"

    return result


@cache_data_if_enabled(ttl=CACHE_TTL_SECONDS)
def get_placement_analysis_data(league: str):
    """
    Get processed data specifically for placement analysis.

    Args:
        league: League identifier

    Returns:
        Tuple containing:
        - DataFrame
        - Latest time
        - Bracket creation times dict
    """
    # Respect filesystem flag: if include_shun file exists, include shunned players.
    include_shun = include_shun_enabled()
    df = get_live_data(league, include_shun)

    # Use the shared bracket filtering logic
    _, fullish_brackets = get_full_brackets(df)
    df = df[df.bracket.isin(fullish_brackets)]

    # Cast real_name to string
    df["real_name"] = df["real_name"].astype("str")

    # Get latest time point
    latest_time = df["datetime"].max()

    # Get bracket creation times
    bracket_creation_times = {bracket: df[df["bracket"] == bracket]["datetime"].min() for bracket in df["bracket"].unique()}

    return df, latest_time, bracket_creation_times


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

        results.append(
            {
                "Bracket": bracket,
                "Would Place": f"{rank}/{total}",
                "Top Wave": last_bracket_df["wave"].max(),
                "Median Wave": int(last_bracket_df["wave"].median()),
                "Players Above": better_or_equal,
                "Start Time": start_time,
            }
        )

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
        "lowest_median": group_by_bracket.median().sort_values(ascending=True).index[0],
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


@cache_data_if_enabled(ttl=CACHE_TTL_SECONDS)
def get_cached_plot_data(df):
    """Process dataframe for plotting, with better error handling."""
    plot_data = df.copy()

    # Only convert datetime if the column exists
    if "datetime" in plot_data.columns:
        plot_data["datetime"] = pd.to_datetime(plot_data["datetime"])

    return plot_data


def initialize_bracket_state(bracket_order, league):
    """Initialize or update bracket navigation state"""
    bracket_key = f"current_bracket_idx_{league}"
    if bracket_key not in st.session_state:
        st.session_state[bracket_key] = 0

    return st.session_state[bracket_key]


def update_bracket_index(new_index, max_index, league):
    """Update bracket navigation index with bounds checking"""
    bracket_key = f"current_bracket_idx_{league}"
    st.session_state[bracket_key] = max(0, min(new_index, max_index))


def clear_cache():
    """Clear all cached data in Streamlit"""
    st.cache_data.clear()


def _parse_timestamp_from_filename(file_path: Path) -> datetime.datetime:
    """
    Parse datetime from filename without Django dependencies.

    Args:
        file_path: Path object containing timestamp in filename

    Returns:
        Parsed datetime object (timezone-naive, UTC)
    """
    return datetime.datetime.strptime(str(file_path.stem), "%Y-%m-%d__%H_%M")


@cache_data_if_enabled(ttl=CACHE_TTL_SECONDS)
def get_data_refresh_timestamp(league: str) -> datetime.datetime | None:
    """
    Get the timestamp of the most recent data refresh for the given league.

    This represents when the data was last fetched from the external source,
    taking into account both caching and the actual data file timestamps.

    Args:
        league: League identifier

    Returns:
        datetime object representing when data was last refreshed, or None if no data
    """
    try:
        home = Path(os.getenv("HOME"))
        live_path = home / "tourney" / "results_cache" / f"{league}_live"
        
        all_files = list(live_path.glob("*.csv"))
        
        # Filter out empty files
        non_empty_files = [f for f in all_files if f.stat().st_size > 0]
        
        if not non_empty_files:
            return None
        
        # Sort by timestamp in filename (not alphabetically)
        def get_file_timestamp(file_path):
            try:
                return get_time(file_path)
            except Exception:
                # If we can't parse the timestamp, put it at the beginning
                return datetime.datetime.min
        
        sorted_files = sorted(non_empty_files, key=get_file_timestamp)
        
        # Get the most recent file (chronologically latest)
        last_file = sorted_files[-1]
        
        # Extract timestamp from filename
        timestamp = get_time(last_file)
        return timestamp

    except Exception as e:
        logging.warning(f"Failed to get data refresh timestamp for {league}: {e}")
        return None


def format_time_ago(timestamp: datetime.datetime) -> str:
    """
    Format a timestamp as a human-readable "time ago" string.

    Args:
        timestamp: datetime object to format (assumed to be UTC if timezone-naive)

    Returns:
        Human-readable string like "5 minutes ago", "2 hours ago", etc.
    """
    if not timestamp:
        return "Unknown"

    # Get current time in UTC
    now = datetime.datetime.now(datetime.timezone.utc)

    # If timestamp is timezone-naive, assume it's UTC
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)

    # Calculate time difference
    time_diff = now - timestamp

    if time_diff.days > 0:
        if time_diff.days == 1:
            return "1 day ago"
        return f"{time_diff.days} days ago"
    elif time_diff.seconds >= 3600:
        hours = time_diff.seconds // 3600
        if hours == 1:
            return "1 hour ago"
        return f"{hours} hours ago"
    elif time_diff.seconds >= 60:
        minutes = time_diff.seconds // 60
        if minutes == 1:
            return "1 minute ago"
        return f"{minutes} minutes ago"
    else:
        return "Just now"
