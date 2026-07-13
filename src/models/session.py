"""
Session and application state models.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

from .game import Game, GameStats, FormatType
from .rank import Rank


class SessionStatus(str, Enum):
    """Session status states."""

    ACTIVE = "Active"
    PAUSED = "Paused"
    ENDED = "Ended"


class GameState(BaseModel):
    """Current live game state."""

    is_in_game: bool = False
    turn_number: Optional[int] = None
    player_life: Optional[int] = None
    opponent_life: Optional[int] = None
    player_cards_in_hand: Optional[int] = None
    opponent_cards_in_hand: Optional[int] = None
    game_start_time: Optional[datetime] = None


class Session(BaseModel):
    """Represents a tracking session."""

    session_id: str = Field(..., description="Unique session identifier")
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: SessionStatus = SessionStatus.ACTIVE
    format_type: FormatType

    # Starting rank for the session
    starting_rank: Rank
    current_rank: Rank

    # Games played in this session
    games: List[Game] = Field(default_factory=list)

    # Session statistics
    stats: GameStats = Field(default_factory=GameStats)

    # Notes and metadata
    notes: str = Field(default="")
    tags: List[str] = Field(default_factory=list)

    def add_game(self, game: Game) -> None:
        """Add a game to the session and update stats."""
        self.games.append(game)
        self.stats.update_with_game(game)

        # Update current rank if game has rank info
        if game.rank_after:
            self.current_rank = game.rank_after

    def end_session(self) -> None:
        """End the current session."""
        self.status = SessionStatus.ENDED
        self.end_time = datetime.now()

    def pause_session(self) -> None:
        """Pause the current session."""
        self.status = SessionStatus.PAUSED

    def resume_session(self) -> None:
        """Resume a paused session."""
        if self.status == SessionStatus.PAUSED:
            self.status = SessionStatus.ACTIVE

    def get_duration_minutes(self) -> int:
        """Get session duration in minutes."""
        end = self.end_time or datetime.now()
        delta = end - self.start_time
        return int(delta.total_seconds() / 60)

    def get_rank_change(self) -> str:
        """Get a string representation of rank change during session."""
        if self.starting_rank.tier != self.current_rank.tier:
            return f"{self.starting_rank.tier.value} → {self.current_rank.tier.value}"
        elif (
            self.starting_rank.division != self.current_rank.division
            and self.starting_rank.division
            and self.current_rank.division
        ):
            tier = self.current_rank.tier.value
            return f"{tier} T{self.starting_rank.division} → T{self.current_rank.division}"
        else:
            # Same tier and division, show pip change
            pip_change = self.current_rank.pips - self.starting_rank.pips
            if pip_change == 0:
                return "No change"
            elif pip_change > 0:
                return f"+{pip_change} pips"
            else:
                return f"{pip_change} pips"

    def get_session_filename(self) -> str:
        """Generate a filename for this session."""
        date_str = self.start_time.strftime("%Y-%m-%d_%H-%M-%S")
        format_str = self.format_type.value.lower()
        return f"{date_str}_{format_str}.json"


class AppState(BaseModel):
    """Application state for crash recovery."""

    current_session_id: Optional[str] = None
    active_session: Optional[Session] = None
    live_game_state: GameState = Field(default_factory=GameState)

    # UI state
    selected_panel: str = "main"
    scroll_position: int = 0

    # Last known MTGA log position
    last_log_position: int = 0
    last_log_file: Optional[str] = None

    # Temporary data that hasn't been committed
    uncommitted_games: List[Game] = Field(default_factory=list)

    def has_active_session(self) -> bool:
        """Check if there's an active session."""
        return (
            self.active_session is not None and self.active_session.status == SessionStatus.ACTIVE
        )

    def start_new_session(self, format_type: FormatType, starting_rank: Rank) -> Session:
        """Start a new tracking session."""
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        session = Session(
            session_id=session_id,
            format_type=format_type,
            starting_rank=starting_rank,
            current_rank=starting_rank.copy(),  # Start with same rank
        )

        self.active_session = session
        self.current_session_id = session_id
        return session

    def end_current_session(self) -> Optional[Session]:
        """End the current session and return it."""
        if self.active_session:
            self.active_session.end_session()
            ended_session = self.active_session
            self.active_session = None
            self.current_session_id = None
            return ended_session
        return None

    def add_game_to_session(self, game: Game) -> bool:
        """Add a game to the current session."""
        if self.has_active_session():
            self.active_session.add_game(game)
            return True
        return False

    def update_live_game_state(self, **kwargs) -> None:
        """Update the live game state."""
        for key, value in kwargs.items():
            if hasattr(self.live_game_state, key):
                setattr(self.live_game_state, key, value)
