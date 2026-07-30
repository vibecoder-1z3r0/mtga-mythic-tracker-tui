"""
Mid Week Magic mode models for MTGA Manual TUI Tracker.

Mid Week Magic (MWM) is a free-to-enter weekly event with no win/loss cap
and no runs - you just keep playing games in whatever the week's format is
(e.g. "Historic Pauper", best of one) for as long as you want. That makes
it a much closer match to plain game/session tracking than to the
win/loss-capped run system in event.py: there's no EventRun-equivalent
wrapper here, games are recorded directly against MWMStats.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Optional


@dataclass
class MWMFormatDefinition:
    """Configuration for a specific week's Mid Week Magic format."""

    format_id: str
    name: str
    format: str = "Best of One"
    start_date: Optional[str] = None
    end_date: Optional[str] = None


def load_mwm_catalog(path: Path) -> List[MWMFormatDefinition]:
    """Load MWM format definitions from a JSON catalog file."""
    if not path.exists():
        return []
    with open(path, "r") as f:
        data = json.load(f)
    return [MWMFormatDefinition(**entry) for entry in data.get("formats", [])]


def default_mwm_catalog_path() -> Path:
    """Default location of the hand-edited MWM catalog (this app's own copy)."""
    return Path(__file__).resolve().parent.parent / "mwm_formats.json"


def current_mwm_format(catalog: List[MWMFormatDefinition]) -> Optional[MWMFormatDefinition]:
    """The format to treat as "this week's" - the last entry in the
    catalog, since a new week's format is appended to the end rather than
    replacing old entries (mirrors events.json's hand-edited, append-only
    convention)."""
    return catalog[-1] if catalog else None


class MWMGameResult(str, Enum):
    """Result of a single Mid Week Magic game."""

    WIN = "Win"
    LOSS = "Loss"


@dataclass
class MWMGame:
    """A single Mid Week Magic game."""

    result: MWMGameResult
    timestamp: datetime = field(default_factory=datetime.now)
    player_deck: Optional[str] = None  # prefilled from MWMStats.current_deck, editable per-game
    opponent_deck: Optional[str] = None
    opponent_name: Optional[str] = None
    play_draw: Optional[str] = None  # "Play" or "Draw", None if unrecorded
    notes: str = ""


@dataclass
class MWMStats:
    """Mid Week Magic stats: current session and all-time totals.

    Mirrors EventStats' session/all-time timer and "boundary index into a
    list" pattern, but the list is games directly rather than runs - there's
    no win/loss cap to group them into runs.
    """

    format_id: Optional[str] = None

    # The deck currently being played, set at the session level (e.g. via a
    # "set deck" keybinding) and used to prefill new games' player_deck -
    # each game can still override it individually, since a user may swap
    # decks mid-session.
    current_deck: Optional[str] = None

    session_start_time: datetime = field(default_factory=datetime.now)
    session_paused: bool = False
    pause_start_time: Optional[datetime] = None
    total_paused_time: float = 0.0  # seconds, accumulated across all pauses this session

    # Every game ever played, in play order. Both session and all-time
    # totals are computed from this rather than stored as separate
    # counters (same reasoning as EventStats.recent_runs - one source of
    # truth, nothing to keep in sync).
    games: List[MWMGame] = field(default_factory=list)

    # Index into games marking where the current session began.
    session_start_game_count: int = 0

    def _session_games(self) -> List[MWMGame]:
        return self.games[self.session_start_game_count :]

    @property
    def session_games_played(self) -> int:
        return len(self._session_games())

    @property
    def session_wins(self) -> int:
        return sum(1 for g in self._session_games() if g.result == MWMGameResult.WIN)

    @property
    def session_losses(self) -> int:
        return sum(1 for g in self._session_games() if g.result == MWMGameResult.LOSS)

    @property
    def session_plays(self) -> int:
        return sum(1 for g in self._session_games() if g.play_draw == "Play")

    @property
    def session_draws(self) -> int:
        return sum(1 for g in self._session_games() if g.play_draw == "Draw")

    def session_duration(self) -> timedelta:
        """Time since the current session began, excluding any paused time
        (mirrors EventStats.session_duration())."""
        elapsed = (datetime.now() - self.session_start_time).total_seconds()
        current_pause = 0.0
        if self.session_paused and self.pause_start_time:
            current_pause = (datetime.now() - self.pause_start_time).total_seconds()
        active = elapsed - self.total_paused_time - current_pause
        return timedelta(seconds=max(0, active))

    def pause_session(self) -> None:
        """Pause the session timer."""
        if not self.session_paused:
            self.session_paused = True
            self.pause_start_time = datetime.now()

    def resume_session(self) -> None:
        """Resume the session timer, folding the just-finished pause into
        total_paused_time so session_duration() keeps excluding it."""
        if self.session_paused and self.pause_start_time:
            self.total_paused_time += (datetime.now() - self.pause_start_time).total_seconds()
            self.session_paused = False
            self.pause_start_time = None

    @property
    def alltime_games_played(self) -> int:
        return len(self.games)

    @property
    def alltime_wins(self) -> int:
        return sum(1 for g in self.games if g.result == MWMGameResult.WIN)

    @property
    def alltime_losses(self) -> int:
        return sum(1 for g in self.games if g.result == MWMGameResult.LOSS)

    @property
    def alltime_plays(self) -> int:
        return sum(1 for g in self.games if g.play_draw == "Play")

    @property
    def alltime_draws(self) -> int:
        return sum(1 for g in self.games if g.play_draw == "Draw")

    def record_game(self, game: MWMGame) -> None:
        """Record a completed game."""
        self.games.append(game)

    def backfill(self, wins: int, losses: int) -> None:
        """Add `wins` win-games and `losses` loss-games with no opponent
        detail, for correcting/backfilling all-time totals to reflect
        games played before this tracker was used - there's no real
        per-game info to enter for those.

        Inserted BEFORE the current session boundary (not appended), with
        session_start_game_count shifted forward by the same count, so
        they land in alltime_* immediately without also being counted as
        part of the current session - games[session_start_game_count:]
        (the actual definition of "this session") is left pointing at
        exactly the same real games as before the insert.
        """
        added = [
            MWMGame(result=MWMGameResult.WIN, notes="Backfilled historical result")
            for _ in range(wins)
        ]
        added += [
            MWMGame(result=MWMGameResult.LOSS, notes="Backfilled historical result")
            for _ in range(losses)
        ]
        insert_at = self.session_start_game_count
        self.games[insert_at:insert_at] = added
        self.session_start_game_count += len(added)

    def restart_session(self) -> None:
        """Start a new session boundary: session_* stats (computed from
        games[session_start_game_count:]) read as zero going forward,
        while all-time totals (computed from the full games list) are
        unaffected."""
        self.session_start_game_count = len(self.games)
        self.session_start_time = datetime.now()
        self.session_paused = False
        self.pause_start_time = None
        self.total_paused_time = 0.0

    def wipe_alltime(self) -> None:
        """Wipe all-time totals permanently, including the current deck
        and session totals - an all-time wipe with leftover state
        wouldn't make sense."""
        self.games = []
        self.session_start_game_count = 0
        self.session_start_time = datetime.now()
        self.session_paused = False
        self.pause_start_time = None
        self.total_paused_time = 0.0
        self.current_deck = None
