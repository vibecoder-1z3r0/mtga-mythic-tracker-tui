"""
Event-mode models for MTGA Manual TUI Tracker.

Standalone dataclass versions of the run-based event tracker (win/loss
caps and a fixed prize table, e.g. the Historic Pauper Challenge) that
exists in the parent project's src/models/event.py. Kept independent
(no imports from src/) to match this app's standalone design.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class EntryCurrency(str, Enum):
    """Currency an event entry fee was paid with."""

    GOLD = "Gold"
    GEMS = "Gems"


@dataclass
class PrizeTier:
    """Prize awarded for reaching a specific win count."""

    wins: int
    gems: int = 0
    packs: int = 0


@dataclass
class MilestoneDefinition:
    """A named win-count threshold, e.g. "Winning Run" at 3+ wins."""

    name: str
    min_wins: int


@dataclass
class EventDefinition:
    """Configuration for a specific event (e.g. Historic Pauper Challenge)."""

    event_id: str
    name: str
    format: str = "Best of One"
    win_cap: int = 7
    loss_cap: int = 2
    entry_cost_gold: Optional[int] = None
    entry_cost_gems: Optional[int] = None
    prize_table: List[PrizeTier] = field(default_factory=list)
    milestones: List[MilestoneDefinition] = field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    def prize_for_wins(self, wins: int) -> PrizeTier:
        """Get the prize for a given number of wins (clamped to win_cap)."""
        capped = min(wins, self.win_cap)
        for tier in self.prize_table:
            if tier.wins == capped:
                return tier
        return PrizeTier(wins=capped)

    def milestones_met(self, wins: int) -> List[MilestoneDefinition]:
        """All milestones whose threshold is met by this win count."""
        return [m for m in self.milestones if wins >= m.min_wins]

    def highest_milestone(self, wins: int) -> Optional[MilestoneDefinition]:
        """The single highest-threshold milestone met by this win count."""
        met = self.milestones_met(wins)
        if not met:
            return None
        return max(met, key=lambda m: m.min_wins)


def load_event_catalog(path: Path) -> List[EventDefinition]:
    """Load event definitions from a JSON catalog file."""
    if not path.exists():
        return []
    with open(path, "r") as f:
        data = json.load(f)

    events = []
    for entry in data.get("events", []):
        entry = dict(entry)
        prize_table = [PrizeTier(**tier) for tier in entry.pop("prize_table", [])]
        milestones = [MilestoneDefinition(**m) for m in entry.pop("milestones", [])]
        events.append(EventDefinition(prize_table=prize_table, milestones=milestones, **entry))
    return events


def default_catalog_path() -> Path:
    """Default location of the hand-edited event catalog (this app's own copy)."""
    return Path(__file__).resolve().parent.parent / "events.json"


class EventGameResult(str, Enum):
    """Result of a single game within an event run."""

    WIN = "Win"
    LOSS = "Loss"


@dataclass
class EventGame:
    """A single game played within an event run."""

    result: EventGameResult
    timestamp: datetime = field(default_factory=datetime.now)
    opponent_deck: Optional[str] = None
    notes: str = ""


class EventRunStatus(str, Enum):
    """Status of a single event run."""

    ACTIVE = "Active"
    ENDED = "Ended"


@dataclass
class EventRun:
    """A single attempt at an event, ending at win_cap wins or loss_cap losses."""

    run_id: str
    event_id: str
    entry_currency: EntryCurrency = EntryCurrency.GEMS
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: EventRunStatus = EventRunStatus.ACTIVE
    player_deck: Optional[str] = None
    games: List[EventGame] = field(default_factory=list)

    @property
    def wins(self) -> int:
        return sum(1 for g in self.games if g.result == EventGameResult.WIN)

    @property
    def losses(self) -> int:
        return sum(1 for g in self.games if g.result == EventGameResult.LOSS)

    def is_complete(self, event: EventDefinition) -> bool:
        """Check if this run has reached the event's win or loss cap."""
        return self.wins >= event.win_cap or self.losses >= event.loss_cap

    def add_game(self, game: EventGame, event: EventDefinition) -> bool:
        """Add a game to this run. Returns False if the run already ended."""
        if self.status == EventRunStatus.ENDED:
            return False
        self.games.append(game)
        if self.is_complete(event):
            self.end_run()
        return True

    def end_run(self) -> None:
        """Mark this run as ended."""
        self.status = EventRunStatus.ENDED
        self.end_time = datetime.now()

    def prize(self, event: EventDefinition) -> PrizeTier:
        """The prize this run has earned so far, based on current wins."""
        return event.prize_for_wins(self.wins)

    def net_profit_gems(self, event: EventDefinition) -> Optional[int]:
        """Net gems profit (prize gems minus entry cost).

        Only meaningful when the entry fee was paid in gems, since gold has
        no fixed conversion rate to gems. Returns None otherwise.
        """
        if self.entry_currency != EntryCurrency.GEMS or event.entry_cost_gems is None:
            return None
        return self.prize(event).gems - event.entry_cost_gems

    def highest_milestone(self, event: EventDefinition) -> Optional[MilestoneDefinition]:
        """The highest-threshold milestone this run has reached so far."""
        return event.highest_milestone(self.wins)


@dataclass
class PrizeTotal:
    """An aggregated prize total across multiple runs."""

    gems: int = 0
    packs: int = 0

    def __add__(self, other: "PrizeTotal") -> "PrizeTotal":
        return PrizeTotal(gems=self.gems + other.gems, packs=self.packs + other.packs)


@dataclass
class EventStats:
    """Event-mode stats: current run, current session, and all-time totals.

    Mirrors the shape of SessionStats (session_* vs season_* counters) but
    for event runs instead of ranked games.
    """

    event_id: Optional[str] = None
    current_run: Optional[EventRun] = None

    session_runs_played: int = 0
    session_wins: int = 0
    session_losses: int = 0
    session_gems: int = 0
    session_packs: int = 0
    session_milestone_counts: Dict[str, int] = field(default_factory=dict)

    alltime_runs_played: int = 0
    alltime_wins: int = 0
    alltime_losses: int = 0
    alltime_gems: int = 0
    alltime_packs: int = 0
    alltime_milestone_counts: Dict[str, int] = field(default_factory=dict)

    recent_runs: List[EventRun] = field(default_factory=list)

    def start_run(self, run: EventRun) -> None:
        """Start a new run, replacing any existing (presumably ended) one."""
        self.current_run = run
        self.event_id = run.event_id

    def record_game(self, game: EventGame, event: EventDefinition) -> bool:
        """Record a game result against the current run."""
        if not self.current_run:
            return False
        added = self.current_run.add_game(game, event)
        if added and self.current_run.status == EventRunStatus.ENDED:
            self._complete_run(self.current_run, event)
        return added

    def _complete_run(self, run: EventRun, event: EventDefinition) -> None:
        """Fold a just-completed run's results into session/all-time totals."""
        prize = run.prize(event)

        self.session_runs_played += 1
        self.session_wins += run.wins
        self.session_losses += run.losses
        self.session_gems += prize.gems
        self.session_packs += prize.packs

        self.alltime_runs_played += 1
        self.alltime_wins += run.wins
        self.alltime_losses += run.losses
        self.alltime_gems += prize.gems
        self.alltime_packs += prize.packs

        for milestone in event.milestones_met(run.wins):
            self.session_milestone_counts[milestone.name] = (
                self.session_milestone_counts.get(milestone.name, 0) + 1
            )
            self.alltime_milestone_counts[milestone.name] = (
                self.alltime_milestone_counts.get(milestone.name, 0) + 1
            )

        self.recent_runs.append(run)
        if len(self.recent_runs) > 5:
            self.recent_runs = self.recent_runs[-5:]

    def restart_session(self) -> None:
        """Reset session-scoped counters but keep all-time totals (mirrors
        SessionStats.reset_session)."""
        self.session_runs_played = 0
        self.session_wins = 0
        self.session_losses = 0
        self.session_gems = 0
        self.session_packs = 0
        self.session_milestone_counts = {}
