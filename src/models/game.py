"""
MTG Arena game tracking models.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

from .rank import FormatType, Rank


class GameResult(str, Enum):
    """Game result outcomes."""

    WIN = "Win"
    LOSS = "Loss"
    DRAW = "Draw"  # Rare but possible


class PlayOrder(str, Enum):
    """Whether player went first or second."""

    PLAY = "Play"  # Went first
    DRAW = "Draw"  # Went second


class Game(BaseModel):
    """Represents a single MTG Arena game."""

    timestamp: datetime = Field(default_factory=datetime.now)
    result: GameResult
    play_order: PlayOrder
    format_type: FormatType

    # Deck information
    player_deck: Optional[str] = None
    opponent_deck: Optional[str] = None

    # Game details
    notes: str = Field(default="")
    duration_minutes: Optional[int] = None

    # Rank changes
    rank_before: Optional[Rank] = None
    rank_after: Optional[Rank] = None
    pips_gained: int = 0  # Can be negative for losses

    def rank_change_str(self) -> str:
        """Get a string representation of rank change."""
        if self.pips_gained == 0:
            return "No change"
        elif self.pips_gained > 0:
            return f"+{self.pips_gained} pips"
        else:
            return f"{self.pips_gained} pips"

    def was_promotion(self) -> bool:
        """Check if this game resulted in a promotion."""
        if not self.rank_before or not self.rank_after:
            return False

        # Check tier promotion
        tier_order = ["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Mythic"]
        before_idx = tier_order.index(self.rank_before.tier.value)
        after_idx = tier_order.index(self.rank_after.tier.value)

        if after_idx > before_idx:
            return True

        # Check division promotion within tier
        if (
            self.rank_before.tier == self.rank_after.tier
            and self.rank_before.division
            and self.rank_after.division
            and self.rank_after.division < self.rank_before.division
        ):
            return True

        return False

    def was_demotion(self) -> bool:
        """Check if this game resulted in a demotion."""
        if not self.rank_before or not self.rank_after:
            return False

        # Check tier demotion
        tier_order = ["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Mythic"]
        before_idx = tier_order.index(self.rank_before.tier.value)
        after_idx = tier_order.index(self.rank_after.tier.value)

        if after_idx < before_idx:
            return True

        # Check division demotion within tier
        if (
            self.rank_before.tier == self.rank_after.tier
            and self.rank_before.division
            and self.rank_after.division
            and self.rank_after.division > self.rank_before.division
        ):
            return True

        return False


class GameStats(BaseModel):
    """Statistics for a collection of games."""

    total_games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0

    play_games: int = 0  # Games where player went first
    draw_games: int = 0  # Games where player went second

    play_wins: int = 0
    draw_wins: int = 0

    def win_rate(self) -> float:
        """Calculate overall win rate."""
        if self.total_games == 0:
            return 0.0
        return (self.wins / self.total_games) * 100

    def play_win_rate(self) -> float:
        """Calculate win rate when going first."""
        if self.play_games == 0:
            return 0.0
        return (self.play_wins / self.play_games) * 100

    def draw_win_rate(self) -> float:
        """Calculate win rate when going second."""
        if self.draw_games == 0:
            return 0.0
        return (self.draw_wins / self.draw_games) * 100

    def update_with_game(self, game: Game) -> None:
        """Update stats with a new game."""
        self.total_games += 1

        if game.result == GameResult.WIN:
            self.wins += 1
        elif game.result == GameResult.LOSS:
            self.losses += 1
        else:
            self.draws += 1

        if game.play_order == PlayOrder.PLAY:
            self.play_games += 1
            if game.result == GameResult.WIN:
                self.play_wins += 1
        else:
            self.draw_games += 1
            if game.result == GameResult.WIN:
                self.draw_wins += 1
