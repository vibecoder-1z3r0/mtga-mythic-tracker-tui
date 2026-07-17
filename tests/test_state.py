#!/usr/bin/env python3
"""
Test script for application state management.
"""

import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.core.state_manager import StateManager
from src.models.game import Game, GameResult, PlayOrder
from src.models.rank import Rank, RankTier, FormatType


@contextmanager
def isolated_home():
    """Patch Path.home() to a throwaway temp dir so config/state files
    written by the global config_manager singleton never touch the real
    ~/.config/mtga-tracker."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("pathlib.Path.home", return_value=Path(temp_dir)):
            yield Path(temp_dir)


def test_basic_state_operations():
    """Test basic state management operations."""
    with isolated_home():
        manager = StateManager()
        manager.disable_auto_save()  # Prevent file I/O during testing

        state = manager.state
        assert state.has_active_session() is False
        assert state.current_session_id is None

        starting_rank = Rank(tier=RankTier.GOLD, division=2, pips=3)
        session = manager.start_session(FormatType.CONSTRUCTED, starting_rank)

        assert session.format_type == FormatType.CONSTRUCTED
        assert session.starting_rank == starting_rank
        assert state.has_active_session() is True


def test_game_tracking():
    """Test game tracking within sessions."""
    with isolated_home():
        manager = StateManager()
        manager.disable_auto_save()

        starting_rank = Rank(tier=RankTier.PLATINUM, division=3, pips=2)
        session = manager.start_session(FormatType.CONSTRUCTED, starting_rank)

        rank_after_win = starting_rank.add_pips(2)
        game1 = Game(
            result=GameResult.WIN,
            play_order=PlayOrder.PLAY,
            format_type=FormatType.CONSTRUCTED,
            player_deck="Esper Control",
            opponent_deck="Mono-Red Aggro",
            notes="Good mulligan, stabilized early",
            rank_before=starting_rank,
            rank_after=rank_after_win,
            pips_gained=2,
        )

        rank_after_loss = rank_after_win.remove_pips(1)
        game2 = Game(
            result=GameResult.LOSS,
            play_order=PlayOrder.DRAW,
            format_type=FormatType.CONSTRUCTED,
            player_deck="Esper Control",
            opponent_deck="Grixis Midrange",
            notes="Flooded out, drew 6 lands",
            rank_before=rank_after_win,
            rank_after=rank_after_loss,
            pips_gained=-1,
        )

        assert manager.add_game(game1) is True
        assert manager.add_game(game2) is True

        assert len(session.games) == 2
        assert session.stats.wins == 1
        assert session.stats.losses == 1
        assert session.stats.win_rate() == 50.0
        assert session.get_rank_change() == "+1 pips"


def test_session_lifecycle():
    """Test complete session lifecycle."""
    with isolated_home():
        manager = StateManager()

        starting_rank = Rank(tier=RankTier.DIAMOND, division=1, pips=5)
        session = manager.start_session(FormatType.LIMITED, starting_rank)
        assert session.status.value == "Active"

        manager.pause_session()
        assert session.status.value == "Paused"

        manager.resume_session()
        assert session.status.value == "Active"

        ended_session = manager.end_session()
        assert ended_session.status.value == "Ended"
        assert ended_session.end_time is not None
        assert ended_session.get_duration_minutes() >= 0
        assert manager.state.has_active_session() is False


def test_live_game_state():
    """Test live game state tracking."""
    with isolated_home():
        manager = StateManager()
        manager.disable_auto_save()

        manager.update_live_game_state(
            is_in_game=True,
            turn_number=5,
            player_life=18,
            opponent_life=12,
            player_cards_in_hand=4,
            opponent_cards_in_hand=3,
            game_start_time=datetime.now(),
        )

        game_state = manager.state.live_game_state
        assert game_state.is_in_game is True
        assert game_state.turn_number == 5
        assert game_state.player_life == 18
        assert game_state.opponent_life == 12
        assert game_state.player_cards_in_hand == 4
        assert game_state.opponent_cards_in_hand == 3

        manager.update_live_game_state(is_in_game=False)
        assert game_state.is_in_game is False


def test_persistence():
    """Test state persistence and recovery."""
    with isolated_home():
        manager1 = StateManager()

        starting_rank = Rank(tier=RankTier.GOLD, division=4, pips=1)
        session = manager1.start_session(FormatType.CONSTRUCTED, starting_rank)

        game = Game(
            result=GameResult.WIN,
            play_order=PlayOrder.DRAW,
            format_type=FormatType.CONSTRUCTED,
            notes="Test game for persistence",
        )
        manager1.add_game(game)
        manager1.enable_auto_save()  # Forces an immediate save

        manager2 = StateManager()
        loaded_state = manager2.load_state()

        assert loaded_state.has_active_session() is True
        assert loaded_state.active_session.session_id == session.session_id
        assert len(loaded_state.active_session.games) == 1
        assert loaded_state.active_session.games[0].notes == "Test game for persistence"


def main():
    """Run all state management tests."""
    test_basic_state_operations()
    test_game_tracking()
    test_session_lifecycle()
    test_live_game_state()
    test_persistence()
    print("All state management tests passed!")


if __name__ == "__main__":
    main()
