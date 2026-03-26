"""League promotion/relegation rules.

This module provides a single source of truth for bracket mechanics so that
multiple pages (live placement analysis, regression trends, etc.) all apply the
same rules. When game mechanics change in a future patch, update ``_DEFAULT_RULES``
(and optionally add per-patch overrides in ``get_league_rules``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class LeagueRules:
    """Promotion/relegation rules for a league in a given patch era."""

    promote_cutoff: Optional[int]
    """Last place that earns promotion (None = top tier, no promotion possible)."""

    relegate_cutoff: Optional[int]
    """First place that triggers relegation (None = protected tier, no demotion)."""

    bracket_size: int = 30
    """Standard number of players per bracket."""

    reward_boundaries: tuple[float, ...] = field(default_factory=tuple)
    """Reward tier boundary positions (used for histogram rendering)."""

    @property
    def last_safe(self) -> Optional[int]:
        """Last place that is safe from relegation, or None if no relegation."""
        return self.relegate_cutoff - 1 if self.relegate_cutoff is not None else None

    @property
    def median_place(self) -> int:
        """Approximate median bracket position (middle of bracket_size)."""
        return self.bracket_size // 2

    def key_places(self) -> list[int]:
        """Signature placement positions for trend analysis.

        Returns the promote cutoff (if applicable), the median position, and
        the last safe position (if applicable), in ascending order.
        """
        places: list[int] = []
        if self.promote_cutoff is not None:
            places.append(self.promote_cutoff)
        places.append(self.median_place)
        if self.last_safe is not None:
            places.append(self.last_safe)
        return places

    def place_label(self, place: int) -> str:
        """Human-readable label describing a place's bracket significance."""
        if place == self.promote_cutoff:
            return f"#{place} (last promote)"
        if place == self.relegate_cutoff:
            return f"#{place} (first relegate)"
        if place == self.last_safe:
            return f"#{place} (last safe)"
        if place == self.median_place:
            return f"#{place} (median)"
        return f"#{place}"


# ---------------------------------------------------------------------------
# Current rules — valid for patch v25 onwards (30-player brackets).
# ---------------------------------------------------------------------------
_DEFAULT_RULES: dict[str, LeagueRules] = {
    "Copper": LeagueRules(
        promote_cutoff=4,
        relegate_cutoff=None,
        reward_boundaries=(1.5, 2.5, 4.5, 6.5, 8.5, 10.5, 12.5, 15.5, 22.5),
    ),
    "Silver": LeagueRules(
        promote_cutoff=4,
        relegate_cutoff=None,
        reward_boundaries=(1.5, 2.5, 4.5, 6.5, 8.5, 10.5, 12.5, 15.5, 22.5),
    ),
    "Gold": LeagueRules(
        promote_cutoff=4,
        relegate_cutoff=None,
        reward_boundaries=(1.5, 2.5, 4.5, 6.5, 8.5, 10.5, 12.5, 15.5, 22.5),
    ),
    "Platinum": LeagueRules(
        promote_cutoff=4,
        relegate_cutoff=25,
        reward_boundaries=(1.5, 2.5, 4.5, 6.5, 8.5, 10.5, 12.5, 15.5, 24.5),
    ),
    "Champion": LeagueRules(
        promote_cutoff=4,
        relegate_cutoff=25,
        reward_boundaries=(1.5, 2.5, 4.5, 6.5, 8.5, 10.5, 12.5, 15.5, 24.5),
    ),
    "Legend": LeagueRules(
        promote_cutoff=None,
        relegate_cutoff=25,
        reward_boundaries=(1.5, 2.5, 4.5, 6.5, 8.5, 10.5, 12.5, 15.5, 24.5),
    ),
}


def get_league_rules(league: str, patch=None) -> LeagueRules:
    """Return promotion/relegation rules for a league.

    Args:
        league: League name (e.g. ``"Legend"``, ``"Champion"``).
        patch:  Optional ``PatchNew`` instance. Reserved for future patch-specific
                rule overrides — currently all patches share the same rules.

    Returns:
        :class:`LeagueRules` for the given league, defaulting to Legend rules
        if the league name is not recognised.
    """
    # Future hook: when game mechanics change, inspect ``patch`` here and
    # return different LeagueRules for older/newer patches, e.g.:
    #   if patch and patch.version_minor < 30:
    #       return _V30_RULES.get(league, _V30_RULES["Legend"])
    return _DEFAULT_RULES.get(league, _DEFAULT_RULES["Legend"])
