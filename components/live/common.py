import pandas as pd
import streamlit as st
from dtower.tourney_results.tourney_utils import get_live_df
from dtower.tourney_results.constants import champ
from dtower.tourney_results.models import TourneyResult
from dtower.tourney_results.data import get_tourneys


@st.cache_data(ttl=300)
def get_live_data(league: str, shun: bool = False):
    """Central cached function for getting live tournament data"""
    return get_live_df(league, shun)


@st.cache_data(ttl=300)
def get_reference_tournament_data(league: str):
    """Central cached function for getting reference tournament data"""
    qs = (TourneyResult.objects
          .filter(league=league, public=True)
          .order_by("-date")
          .first() or
          TourneyResult.objects
          .filter(league=champ, public=True)
          .order_by("-date")
          .first())

    return get_tourneys([qs]) if qs else None


@st.cache_data(ttl=300)
def process_top_n_players(df: pd.DataFrame, n: int = 25):
    """Central cached function for processing top N players"""
    top_n = (df.groupby("player_id")['wave']
             .max()
             .nlargest(n)
             .index)

    tdf = df[df.player_id.isin(top_n)].copy()
    tdf["datetime"] = pd.to_datetime(tdf["datetime"])

    return tdf


@st.cache_data(ttl=300)
def process_bracket_data(df):
    """Central cached function for bracket analysis"""
    bracket_counts = df.groupby("bracket").player_id.nunique()
    fullish_brackets = bracket_counts[bracket_counts >= 28].index
    filtered_df = df[df.bracket.isin(fullish_brackets)].copy()
    filtered_df["datetime"] = pd.to_datetime(filtered_df["datetime"])
    return filtered_df