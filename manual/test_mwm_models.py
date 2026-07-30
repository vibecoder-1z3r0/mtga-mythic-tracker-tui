#!/usr/bin/env python3
"""
Test script for the manual TUI's Mid Week Magic models (MWMFormatDefinition,
MWMGame, MWMStats) and StateManager persistence round-trip.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

from models.mwm import (
    MWMGame,
    MWMGameResult,
    MWMStats,
    current_mwm_format,
    default_mwm_catalog_path,
    load_mwm_catalog,
)
from storage.state_manager import StateManager


def load_test_catalog():
    """Load the checked-in mwm_formats.json catalog."""
    return load_mwm_catalog(default_mwm_catalog_path())


def test_load_mwm_catalog():
    """Test that the checked-in mwm_formats.json catalog loads correctly."""
    catalog = load_test_catalog()
    assert len(catalog) >= 1
    assert catalog[0].format_id == "historic_pauper"
    assert catalog[0].name == "Historic Pauper"
    assert catalog[0].format == "Best of One"


def test_current_mwm_format_uses_last_catalog_entry():
    """current_mwm_format() should treat the LAST catalog entry as "this
    week's" format, since a new week's entry is appended rather than
    replacing old ones."""
    from models.mwm import MWMFormatDefinition

    catalog = [
        MWMFormatDefinition(format_id="old_week", name="Old Week"),
        MWMFormatDefinition(format_id="new_week", name="New Week"),
    ]
    assert current_mwm_format(catalog).format_id == "new_week"
    assert current_mwm_format([]) is None


def test_mwm_game_records_fields():
    """Test that MWMGame records deck/opponent/play-draw/notes fields, with
    sensible defaults when unrecorded."""
    game = MWMGame(result=MWMGameResult.WIN)
    assert game.player_deck is None
    assert game.opponent_deck is None
    assert game.opponent_name is None
    assert game.play_draw is None
    assert game.notes == ""

    game2 = MWMGame(
        result=MWMGameResult.LOSS,
        player_deck="Mono Black Pauper",
        opponent_deck="UW Control",
        opponent_name="endlessnumber",
        play_draw="Draw",
        notes="Flooded out",
    )
    assert game2.player_deck == "Mono Black Pauper"
    assert game2.opponent_deck == "UW Control"
    assert game2.opponent_name == "endlessnumber"
    assert game2.play_draw == "Draw"
    assert game2.notes == "Flooded out"


def test_mwm_stats_session_and_alltime_aggregation():
    """Test that session_* and alltime_* wins/losses/plays/draws are
    computed correctly from the flat games list."""
    stats = MWMStats()
    stats.record_game(MWMGame(result=MWMGameResult.WIN, play_draw="Play"))
    stats.record_game(MWMGame(result=MWMGameResult.WIN, play_draw="Draw"))
    stats.record_game(MWMGame(result=MWMGameResult.LOSS, play_draw="Play"))

    assert stats.session_wins == 2
    assert stats.session_losses == 1
    assert stats.session_plays == 2
    assert stats.session_draws == 1
    assert stats.session_games_played == 3

    assert stats.alltime_wins == 2
    assert stats.alltime_losses == 1
    assert stats.alltime_plays == 2
    assert stats.alltime_draws == 1
    assert stats.alltime_games_played == 3


def test_mwm_stats_restart_session_preserves_alltime():
    """Test that restart_session() zeroes session totals going forward
    while leaving all-time totals (and every already-recorded game)
    untouched."""
    stats = MWMStats()
    stats.record_game(MWMGame(result=MWMGameResult.WIN))
    stats.record_game(MWMGame(result=MWMGameResult.WIN))

    stats.restart_session()
    assert stats.session_wins == 0
    assert stats.session_losses == 0
    assert stats.alltime_wins == 2

    stats.record_game(MWMGame(result=MWMGameResult.LOSS))
    assert stats.session_wins == 0
    assert stats.session_losses == 1
    assert stats.alltime_wins == 2
    assert stats.alltime_losses == 1


def test_mwm_stats_backfill_only_affects_alltime():
    """Test that backfill() bumps alltime_* by the given amounts without
    changing session_* at all, regardless of whether it's called before
    or after real games have been recorded this session."""
    stats = MWMStats()
    stats.record_game(MWMGame(result=MWMGameResult.WIN))
    stats.record_game(MWMGame(result=MWMGameResult.LOSS))
    assert stats.session_wins == 1 and stats.session_losses == 1
    assert stats.alltime_wins == 1 and stats.alltime_losses == 1

    stats.backfill(wins=5, losses=2)
    # Session totals must be exactly what they were before the backfill.
    assert stats.session_wins == 1
    assert stats.session_losses == 1
    # All-time gains the backfilled amount on top of the real games.
    assert stats.alltime_wins == 6
    assert stats.alltime_losses == 3

    # A second backfill after a session restart should still only ever
    # touch all-time, never the new session's own totals.
    stats.restart_session()
    stats.record_game(MWMGame(result=MWMGameResult.WIN))
    stats.backfill(wins=1, losses=1)
    assert stats.session_wins == 1
    assert stats.session_losses == 0
    assert stats.alltime_wins == 8
    assert stats.alltime_losses == 4


def test_mwm_stats_pause_resume_excludes_paused_time_from_duration():
    """Test that time spent paused doesn't count toward session_duration()."""
    stats = MWMStats()
    stats.session_start_time = datetime.now()

    stats.pause_session()
    assert stats.session_paused
    stats.total_paused_time += 5.0  # simulate 5 paused seconds having elapsed
    stats.resume_session()
    assert not stats.session_paused

    duration = stats.session_duration()
    # Duration should be small (test runs fast) and never negative despite
    # the simulated paused time being subtracted.
    assert duration.total_seconds() >= 0
    assert duration.total_seconds() < 5


def test_mwm_stats_wipe_alltime_clears_everything():
    """Test that wipe_alltime() clears games, session boundary, and the
    current deck."""
    stats = MWMStats()
    stats.current_deck = "Mono Black Pauper"
    stats.record_game(MWMGame(result=MWMGameResult.WIN))
    stats.restart_session()
    stats.record_game(MWMGame(result=MWMGameResult.LOSS))

    stats.wipe_alltime()
    assert stats.games == []
    assert stats.session_start_game_count == 0
    assert stats.current_deck is None
    assert stats.alltime_wins == 0
    assert stats.session_wins == 0


def test_state_manager_persists_mwm_stats():
    """Test that MWMStats (including nested games) survives a save/load
    round trip."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sm = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        app_data = sm.load_state()

        app_data.mwm_stats.current_deck = "Mono Black Pauper"
        app_data.mwm_stats.record_game(
            MWMGame(result=MWMGameResult.WIN, opponent_deck="UW Control", opponent_name="Foe")
        )
        app_data.mwm_stats.record_game(MWMGame(result=MWMGameResult.LOSS))

        sm.save_state(app_data)

        sm2 = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        loaded = sm2.load_state()

        assert loaded.mwm_stats.current_deck == "Mono Black Pauper"
        assert loaded.mwm_stats.alltime_wins == 1
        assert loaded.mwm_stats.alltime_losses == 1
        assert len(loaded.mwm_stats.games) == 2
        assert loaded.mwm_stats.games[0].result == MWMGameResult.WIN
        assert loaded.mwm_stats.games[0].opponent_deck == "UW Control"
        assert loaded.mwm_stats.games[0].opponent_name == "Foe"
        assert isinstance(loaded.mwm_stats.games[0].timestamp, datetime)
        assert isinstance(loaded.mwm_stats.session_start_time, datetime)


def test_state_manager_handles_save_without_mwm_stats():
    """Regression-style test: a save file from before Mid Week Magic
    existed has no 'mwm_stats' key at all - loading it must not crash,
    and should just start MWMStats fresh."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sm = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        app_data = sm.load_state()
        sm.save_state(app_data)

        state_file = Path(temp_dir) / "tracker_state.json"
        data = json.loads(state_file.read_text())
        del data["mwm_stats"]
        state_file.write_text(json.dumps(data, indent=2))

        sm2 = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        loaded = sm2.load_state()
        assert loaded.mwm_stats.games == []
        assert loaded.mwm_stats.alltime_wins == 0


def main():
    test_load_mwm_catalog()
    test_current_mwm_format_uses_last_catalog_entry()
    test_mwm_game_records_fields()
    test_mwm_stats_session_and_alltime_aggregation()
    test_mwm_stats_restart_session_preserves_alltime()
    test_mwm_stats_backfill_only_affects_alltime()
    test_mwm_stats_pause_resume_excludes_paused_time_from_duration()
    test_mwm_stats_wipe_alltime_clears_everything()
    test_state_manager_persists_mwm_stats()
    test_state_manager_handles_save_without_mwm_stats()
    print("All Mid Week Magic model tests passed!")


if __name__ == "__main__":
    main()
