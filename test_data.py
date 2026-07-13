#!/usr/bin/env python3
"""
Test script for data persistence layer.
"""

import json
import tempfile
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import patch

from src.core.data_manager import DataManager
from src.models.session import Session, SessionStatus
from src.models.game import Game, GameResult, PlayOrder
from src.models.rank import Rank, RankTier, FormatType


@contextmanager
def isolated_home():
    """Patch Path.home() to a throwaway temp dir so the global config_manager
    singleton (eagerly read by DataManager.__init__) never touches the real
    ~/.config/mtga-tracker."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("pathlib.Path.home", return_value=Path(temp_dir)):
            yield Path(temp_dir)


def create_test_session(session_id: str, format_type: FormatType, days_ago: int = 0) -> Session:
    """Create a test session with sample data."""
    start_time = datetime.now() - timedelta(days=days_ago)

    starting_rank = Rank(tier=RankTier.GOLD, division=3, pips=2)
    session = Session(
        session_id=session_id,
        start_time=start_time,
        format_type=format_type,
        starting_rank=starting_rank,
        current_rank=starting_rank.model_copy(),
        status=SessionStatus.ENDED,
    )

    games = [
        Game(
            timestamp=start_time + timedelta(minutes=5),
            result=GameResult.WIN,
            play_order=PlayOrder.PLAY,
            format_type=format_type,
            player_deck="Esper Control",
            opponent_deck="Mono-Red Aggro",
            notes="Good control game",
            pips_gained=2,
        ),
        Game(
            timestamp=start_time + timedelta(minutes=25),
            result=GameResult.LOSS,
            play_order=PlayOrder.DRAW,
            format_type=format_type,
            player_deck="Esper Control",
            opponent_deck="Grixis Midrange",
            notes="Flooded out",
            pips_gained=-1,
        ),
        Game(
            timestamp=start_time + timedelta(minutes=45),
            result=GameResult.WIN,
            play_order=PlayOrder.PLAY,
            format_type=format_type,
            player_deck="Esper Control",
            opponent_deck="Domain Ramp",
            notes="Close game",
            pips_gained=1,
        ),
    ]

    for game in games:
        session.add_game(game)

    session.end_session()
    return session


def test_session_save_load():
    """Test saving and loading sessions."""
    with isolated_home():
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DataManager()
            manager.sessions_dir = Path(temp_dir) / "sessions"

            session = create_test_session("test_001", FormatType.CONSTRUCTED)
            saved_path = manager.save_session(session)
            assert saved_path.exists()

            loaded_session = manager.load_session(saved_path)
            assert loaded_session is not None
            assert loaded_session.session_id == "test_001"
            assert len(loaded_session.games) == 3
            assert loaded_session.stats.wins == 2
            assert loaded_session.stats.losses == 1
            assert loaded_session.format_type == FormatType.CONSTRUCTED


def test_session_listing_filtering():
    """Test listing and filtering sessions."""
    with isolated_home():
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DataManager()
            manager.sessions_dir = Path(temp_dir) / "sessions"

            sessions = [
                create_test_session("constructed_001", FormatType.CONSTRUCTED, 0),
                create_test_session("constructed_002", FormatType.CONSTRUCTED, 1),
                create_test_session("limited_001", FormatType.LIMITED, 1),
                create_test_session("limited_002", FormatType.LIMITED, 2),
            ]
            for session in sessions:
                manager.save_session(session)

            assert len(manager.list_sessions()) == 4
            assert len(manager.list_sessions(format_type=FormatType.CONSTRUCTED)) == 2
            assert len(manager.list_sessions(format_type=FormatType.LIMITED)) == 2

            today = date.today()
            yesterday = today - timedelta(days=1)
            recent_sessions = manager.list_sessions(date_range=(yesterday, today))
            assert len(recent_sessions) == 3


def test_session_summaries():
    """Test session summary generation."""
    with isolated_home():
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DataManager()
            manager.sessions_dir = Path(temp_dir) / "sessions"

            session = create_test_session("summary_test", FormatType.CONSTRUCTED)
            saved_path = manager.save_session(session)

            summary = manager.get_session_summary(saved_path)
            assert summary is not None
            assert summary["session_id"] == "summary_test"
            assert summary["format_type"] == "Constructed"
            assert summary["game_count"] == 3
            assert summary["wins"] == 2
            assert summary["losses"] == 1
            assert summary["status"] == "Ended"

            recent = manager.get_recent_sessions(limit=5)
            assert len(recent) == 1


def test_statistics_calculation():
    """Test overall statistics calculation."""
    with isolated_home():
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DataManager()
            manager.sessions_dir = Path(temp_dir) / "sessions"

            sessions = [
                create_test_session("stats_001", FormatType.CONSTRUCTED, 0),
                create_test_session("stats_002", FormatType.CONSTRUCTED, 1),
                create_test_session("stats_003", FormatType.LIMITED, 1),
            ]
            for session in sessions:
                manager.save_session(session)

            overall_stats = manager.get_overall_stats()
            assert overall_stats.total_games == 9
            assert overall_stats.wins == 6
            assert overall_stats.losses == 3
            assert round(overall_stats.win_rate(), 1) == 66.7
            assert overall_stats.play_games == 6
            assert overall_stats.draw_games == 3

            constructed_stats = manager.get_format_stats(FormatType.CONSTRUCTED)
            limited_stats = manager.get_format_stats(FormatType.LIMITED)
            assert constructed_stats.total_games == 6
            assert limited_stats.total_games == 3

            today = date.today()
            daily_stats = manager.get_daily_stats(today)
            assert daily_stats["sessions"] == 1
            assert daily_stats["stats"].total_games == 3
            assert daily_stats["duration_minutes"] >= 0


def test_data_export():
    """Test data export functionality."""
    with isolated_home():
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DataManager()
            manager.sessions_dir = Path(temp_dir) / "sessions"

            sessions = [
                create_test_session("export_001", FormatType.CONSTRUCTED),
                create_test_session("export_002", FormatType.LIMITED),
            ]
            for session in sessions:
                manager.save_session(session)

            export_file = Path(temp_dir) / "export" / "sessions_export.json"
            success = manager.export_session_data(export_file)
            assert success is True
            assert export_file.exists()
            assert export_file.stat().st_size > 0

            with open(export_file, "r") as f:
                export_data = json.load(f)
            assert len(export_data["sessions"]) == 2


def test_log_copying():
    """Test parsed log copying functionality."""
    with isolated_home():
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DataManager()
            manager.logs_dir = Path(temp_dir) / "logs"

            test_log_content = """
[2025-08-10 16:05:00.123] {"type": "Event_GameRoomEnter", "format": "Standard Ranked"}
[2025-08-10 16:05:01.456] {"type": "Event_MatchGameRoomStateChangedEvent", "gameResult": "Won"}
[2025-08-10 16:05:02.789] {"type": "Event_RankUpdated", "pipsGained": 2}
            """.strip()

            log_path = manager.copy_parsed_logs(test_log_content, "test_session_001")
            assert log_path is not None
            assert log_path.exists()

            with open(log_path, "r") as f:
                saved_content = f.read()
            assert test_log_content in saved_content


def main():
    """Run all data persistence tests."""
    test_session_save_load()
    test_session_listing_filtering()
    test_session_summaries()
    test_statistics_calculation()
    test_data_export()
    test_log_copying()
    print("All data persistence tests passed!")


if __name__ == "__main__":
    main()
