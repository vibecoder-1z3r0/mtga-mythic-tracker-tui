"""
Event mode models: special limited-time MTGA events with a run-based
structure (win/loss caps and a fixed prize table) rather than the
ranked ladder's tiers/pips, e.g. the Historic Pauper Challenge.
"""

import json
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


class EntryCurrency(str, Enum):
    """Currency an event entry fee was paid with."""

    GOLD = "Gold"
    GEMS = "Gems"


class PrizeTier(BaseModel):
    """Prize awarded for reaching a specific win count."""

    wins: int = Field(..., ge=0)
    gems: int = 0
    packs: int = 0


class MilestoneDefinition(BaseModel):
    """A named win-count threshold, e.g. "Winning Run" at 3+ wins."""

    name: str
    min_wins: int = Field(..., ge=0)


class EventDefinition(BaseModel):
    """Configuration for a specific event (e.g. Historic Pauper Challenge).

    Event definitions are hand-edited in events.json rather than created
    through the app, so the same catalog file can describe several
    concurrently-running events with different structures.
    """

    event_id: str = Field(..., description="Unique id, e.g. 'historic_pauper_challenge_2026_07'")
    name: str
    format: str = "Best of One"
    win_cap: int = Field(..., ge=1)
    loss_cap: int = Field(..., ge=1)
    entry_cost_gold: Optional[int] = None
    entry_cost_gems: Optional[int] = None
    prize_table: List[PrizeTier] = Field(default_factory=list)
    milestones: List[MilestoneDefinition] = Field(default_factory=list)
    start_date: Optional[date] = None
    end_date: Optional[date] = None

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
    return [EventDefinition(**entry) for entry in data.get("events", [])]


def default_catalog_path() -> Path:
    """Default location of the hand-edited event catalog."""
    return Path(__file__).resolve().parent.parent.parent / "events.json"


class EventGameResult(str, Enum):
    """Result of a single game within an event run."""

    WIN = "Win"
    LOSS = "Loss"


class EventGame(BaseModel):
    """A single game played within an event run."""

    timestamp: datetime = Field(default_factory=datetime.now)
    result: EventGameResult
    opponent_deck: Optional[str] = None
    notes: str = ""


class EventRunStatus(str, Enum):
    """Status of a single event run."""

    ACTIVE = "Active"
    ENDED = "Ended"


class EventRun(BaseModel):
    """A single attempt at an event, ending at win_cap wins or loss_cap losses."""

    run_id: str
    event_id: str
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: EventRunStatus = EventRunStatus.ACTIVE
    player_deck: Optional[str] = None
    entry_currency: Optional[EntryCurrency] = None
    games: List[EventGame] = Field(default_factory=list)
    notes: str = ""

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


class PrizeTotal(BaseModel):
    """An aggregated prize total across multiple runs."""

    gems: int = 0
    packs: int = 0

    def __add__(self, other: "PrizeTotal") -> "PrizeTotal":
        return PrizeTotal(gems=self.gems + other.gems, packs=self.packs + other.packs)


class EventSessionStatus(str, Enum):
    """Status of an event tracking session."""

    ACTIVE = "Active"
    PAUSED = "Paused"
    ENDED = "Ended"


class EventSession(BaseModel):
    """A sitting containing one or more runs of a single event."""

    session_id: str
    event_id: str
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: EventSessionStatus = EventSessionStatus.ACTIVE
    runs: List[EventRun] = Field(default_factory=list)

    def start_run(self, run: EventRun) -> None:
        """Add a new run to this session."""
        self.runs.append(run)

    def current_run(self) -> Optional[EventRun]:
        """The most recently started run, if it hasn't ended yet."""
        if self.runs and self.runs[-1].status == EventRunStatus.ACTIVE:
            return self.runs[-1]
        return None

    def completed_runs(self) -> List[EventRun]:
        return [r for r in self.runs if r.status == EventRunStatus.ENDED]

    def total_wins(self) -> int:
        return sum(r.wins for r in self.runs)

    def total_losses(self) -> int:
        return sum(r.losses for r in self.runs)

    def total_prize(self, event: EventDefinition) -> PrizeTotal:
        """Sum of prizes from all completed runs in this session."""
        total = PrizeTotal()
        for run in self.completed_runs():
            total = total + PrizeTotal(gems=run.prize(event).gems, packs=run.prize(event).packs)
        return total

    def milestone_counts(self, event: EventDefinition) -> dict:
        """Cumulative tally: how many completed runs met each milestone."""
        counts = {m.name: 0 for m in event.milestones}
        for run in self.completed_runs():
            for m in event.milestones_met(run.wins):
                counts[m.name] += 1
        return counts

    def end_session(self) -> None:
        self.status = EventSessionStatus.ENDED
        self.end_time = datetime.now()

    def pause_session(self) -> None:
        self.status = EventSessionStatus.PAUSED

    def resume_session(self) -> None:
        if self.status == EventSessionStatus.PAUSED:
            self.status = EventSessionStatus.ACTIVE


class EventAppState(BaseModel):
    """Application state for event-mode crash recovery, parallel to AppState."""

    current_session_id: Optional[str] = None
    active_session: Optional[EventSession] = None

    def has_active_session(self) -> bool:
        return (
            self.active_session is not None
            and self.active_session.status == EventSessionStatus.ACTIVE
        )

    def start_new_session(self, event_id: str) -> EventSession:
        """Start a new event tracking session."""
        # Microsecond resolution avoids session_id collisions (and therefore
        # silently overwritten save files) when two sessions start within
        # the same second.
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        session = EventSession(session_id=session_id, event_id=event_id)
        self.active_session = session
        self.current_session_id = session_id
        return session

    def end_current_session(self) -> Optional[EventSession]:
        """End the current session and return it."""
        if self.active_session:
            self.active_session.end_session()
            ended_session = self.active_session
            self.active_session = None
            self.current_session_id = None
            return ended_session
        return None

    def start_new_run(self, run: EventRun) -> bool:
        """Add a new run to the current session."""
        if self.has_active_session():
            self.active_session.start_run(run)
            return True
        return False
