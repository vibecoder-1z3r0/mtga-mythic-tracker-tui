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


@dataclass
class EntryOption:
    """One way to pay for entry into an event.

    `currency` is a free-form label rather than a closed enum, since entry
    can be paid with gold, gems, or event-specific tokens (Jumpstart
    Boosters, Draft tokens, etc.) that vary per event.
    """

    currency: str
    amount: int
    gems_equivalent: Optional[float] = None  # explicit gems-equivalent value, if not derivable


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
    entry_options: List[EntryOption] = field(default_factory=list)
    prize_table: List[PrizeTier] = field(default_factory=list)
    milestones: List[MilestoneDefinition] = field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    def get_entry_option(self, currency: str) -> Optional[EntryOption]:
        """Look up an entry option by currency name (case-insensitive)."""
        for option in self.entry_options:
            if option.currency.lower() == currency.lower():
                return option
        return None

    def gems_price(self) -> Optional[int]:
        """The amount of the 'Gems' entry option, if this event has one."""
        option = self.get_entry_option("Gems")
        return option.amount if option else None

    def gems_equivalent_for(self, currency: Optional[str]) -> Optional[float]:
        """Gems-equivalent value of paying entry with the given currency.

        Uses that option's explicit gems_equivalent if set, else its own
        amount if it *is* Gems, else falls back to this event's Gems entry
        option (assuming all entry options are priced as roughly equal
        value). Returns None if nothing is resolvable.
        """
        if not currency:
            return None
        option = self.get_entry_option(currency)
        if option is None:
            return None
        if option.gems_equivalent is not None:
            return option.gems_equivalent
        if option.currency.lower() == "gems":
            return option.amount
        return self.gems_price()

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
        entry_options = [EntryOption(**opt) for opt in entry.pop("entry_options", [])]
        events.append(
            EventDefinition(
                prize_table=prize_table,
                milestones=milestones,
                entry_options=entry_options,
                **entry,
            )
        )
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
    play_draw: Optional[str] = None  # "Play" or "Draw", None if unrecorded
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
    entry_currency: Optional[str] = None
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

    @property
    def plays(self) -> int:
        return sum(1 for g in self.games if g.play_draw == "Play")

    @property
    def draws(self) -> int:
        return sum(1 for g in self.games if g.play_draw == "Draw")

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
        """Net gems profit (prize gems minus entry cost, in gems-equivalent
        terms). Non-gems entries (gold, tokens) are converted via
        event.gems_equivalent_for(). Returns None if not resolvable.
        """
        entry_cost_gems_equiv = event.gems_equivalent_for(self.entry_currency)
        if entry_cost_gems_equiv is None:
            return None
        return round(self.prize(event).gems - entry_cost_gems_equiv)

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

    # A user-set target for the CURRENT run's wins, e.g. "reach 5 wins
    # this run." The target itself persists across new runs (mirrors
    # ranked's session_goal_tier, which isn't cleared by a session
    # reset either) - each new run's wins naturally starts back at 0
    # since EventRun.wins is computed live from that run's own games.
    run_goal_wins: Optional[int] = None

    # Every completed run ever played, in completion order. Both session
    # and all-time totals are computed from this rather than stored as
    # separate counters, so there's only one source of truth and nothing
    # to keep in sync (a stored counter added after some runs were already
    # played would otherwise miss them forever, which is exactly the bug
    # that motivated this - session_plays/session_draws were once stored
    # counters, and diverged from the computed alltime_plays/alltime_draws
    # even for a user on their very first, never-restarted session).
    recent_runs: List[EventRun] = field(default_factory=list)

    # Index into recent_runs marking where the current session began - runs
    # from this index onward belong to "this session". Starts at 0, so if
    # this is the only session ever played, session_* and alltime_* below
    # are identical by construction.
    session_start_run_count: int = 0

    def _session_runs(self) -> List[EventRun]:
        return self.recent_runs[self.session_start_run_count :]

    @property
    def session_runs_played(self) -> int:
        return len(self._session_runs())

    @property
    def session_wins(self) -> int:
        return sum(r.wins for r in self._session_runs())

    @property
    def session_losses(self) -> int:
        return sum(r.losses for r in self._session_runs())

    @property
    def session_plays(self) -> int:
        return sum(r.plays for r in self._session_runs())

    @property
    def session_draws(self) -> int:
        return sum(r.draws for r in self._session_runs())

    def session_prize(self, event: EventDefinition) -> PrizeTotal:
        """Total prize earned across runs completed this session."""
        total = PrizeTotal()
        for run in self._session_runs():
            prize = run.prize(event)
            total = total + PrizeTotal(gems=prize.gems, packs=prize.packs)
        return total

    def session_milestone_counts(self, event: EventDefinition) -> Dict[str, int]:
        """Cumulative milestone tally across runs completed this session."""
        counts: Dict[str, int] = {}
        for run in self._session_runs():
            for milestone in event.milestones_met(run.wins):
                counts[milestone.name] = counts.get(milestone.name, 0) + 1
        return counts

    @property
    def alltime_runs_played(self) -> int:
        return len(self.recent_runs)

    @property
    def alltime_wins(self) -> int:
        return sum(r.wins for r in self.recent_runs)

    @property
    def alltime_losses(self) -> int:
        return sum(r.losses for r in self.recent_runs)

    @property
    def alltime_plays(self) -> int:
        return sum(r.plays for r in self.recent_runs)

    @property
    def alltime_draws(self) -> int:
        return sum(r.draws for r in self.recent_runs)

    def alltime_prize(self, event: EventDefinition) -> PrizeTotal:
        """Total prize earned across every completed run."""
        total = PrizeTotal()
        for run in self.recent_runs:
            prize = run.prize(event)
            total = total + PrizeTotal(gems=prize.gems, packs=prize.packs)
        return total

    def alltime_milestone_counts(self, event: EventDefinition) -> Dict[str, int]:
        """Cumulative milestone tally across every completed run - a 7-win
        run counts toward "3+ wins", "5+ wins", etc. all at once."""
        counts: Dict[str, int] = {}
        for run in self.recent_runs:
            for milestone in event.milestones_met(run.wins):
                counts[milestone.name] = counts.get(milestone.name, 0) + 1
        return counts

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

    def concede_run(self, event: EventDefinition) -> bool:
        """End the current run early (before it naturally reaches win_cap
        or loss_cap) and fold its partial result into session/all-time
        totals, same as a natural completion. Returns False if there's no
        active run to concede."""
        if not self.current_run or self.current_run.status == EventRunStatus.ENDED:
            return False
        self.current_run.end_run()
        self._complete_run(self.current_run, event)
        return True

    def _complete_run(self, run: EventRun, event: EventDefinition) -> None:
        """Fold a just-completed run into the completed-run history. Both
        session and all-time totals are computed from recent_runs, not
        tracked here."""
        self.recent_runs.append(run)

    def restart_session(self) -> None:
        """Start a new session boundary: session_* stats (computed from
        recent_runs[session_start_run_count:]) read as zero going forward,
        since nothing's been completed since this new marker, while
        all-time totals (computed from the full recent_runs) are
        unaffected. Also discards any in-progress run, since a restarted
        session shouldn't keep showing a stale run's wins/losses."""
        self.current_run = None
        self.session_start_run_count = len(self.recent_runs)

    def wipe_alltime(self) -> None:
        """Wipe all-time totals permanently. Also discards any in-progress
        run and resets session totals, since an all-time wipe with a
        leftover run or session total wouldn't make sense."""
        self.current_run = None
        self.recent_runs = []
        self.session_start_run_count = 0
        self.run_goal_wins = None
