#!/usr/bin/env python3
"""
Test script for the manual TUI's event-mode models (EventDefinition,
EventRun, EventStats) and StateManager persistence round-trip.
"""
import json
import tempfile
from pathlib import Path

from models.event import (
    EntryOption,
    EventGame,
    EventGameResult,
    EventRun,
    EventRunStatus,
    EventStats,
    default_catalog_path,
    load_event_catalog,
)
from storage.state_manager import StateManager


def load_test_event():
    """Load the Historic Pauper Challenge definition from the real catalog."""
    catalog = load_event_catalog(default_catalog_path())
    return next(e for e in catalog if e.event_id == "historic_pauper_challenge")


def test_load_event_catalog():
    """Test that the checked-in events.json catalog loads correctly."""
    event = load_test_event()
    assert event.name == "Historic Pauper Challenge"
    assert event.win_cap == 7
    assert event.loss_cap == 2
    gold_option = event.get_entry_option("Gold")
    gems_option = event.get_entry_option("Gems")
    assert gold_option.amount == 5000
    assert gems_option.amount == 1000
    assert event.gems_price() == 1000
    assert len(event.prize_table) == 8
    assert len(event.milestones) == 4


def test_prize_for_wins():
    """Test prize table lookup, including capping above win_cap."""
    event = load_test_event()

    assert event.prize_for_wins(0).gems == 100
    assert event.prize_for_wins(3).gems == 500
    assert event.prize_for_wins(7).gems == 1500
    assert event.prize_for_wins(99).gems == 1500  # clamps to win_cap


def test_milestones():
    """Test milestone threshold matching, cumulative and highest-label."""
    event = load_test_event()

    assert event.milestones_met(2) == []
    met_at_6 = {m.name for m in event.milestones_met(6)}
    assert met_at_6 == {"Winning Run", "Free Run", "Profit Run"}
    assert event.highest_milestone(6).name == "Profit Run"
    assert event.highest_milestone(7).name == "Trophy"
    assert event.highest_milestone(2) is None


def test_event_game_records_play_draw_and_opponent_deck():
    """Test that EventGame carries play/draw and opponent deck, defaulting
    to None (displayed as "Unknown") when not recorded."""
    game_unknown = EventGame(result=EventGameResult.WIN)
    assert game_unknown.play_draw is None
    assert game_unknown.opponent_deck is None

    game_known = EventGame(result=EventGameResult.LOSS, play_draw="Draw", opponent_deck="Mono Red")
    assert game_known.play_draw == "Draw"
    assert game_known.opponent_deck == "Mono Red"


def test_event_run_completes_at_caps():
    """Test that a run ends automatically at win_cap or loss_cap."""
    event = load_test_event()

    win_run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
    for _ in range(7):
        win_run.add_game(EventGame(result=EventGameResult.WIN), event)
    assert win_run.status == EventRunStatus.ENDED
    assert win_run.wins == 7
    # No further games accepted once ended.
    assert win_run.add_game(EventGame(result=EventGameResult.WIN), event) is False

    loss_run = EventRun(run_id="r2", event_id=event.event_id, entry_currency="Gems")
    loss_run.add_game(EventGame(result=EventGameResult.LOSS), event)
    loss_run.add_game(EventGame(result=EventGameResult.LOSS), event)
    assert loss_run.status == EventRunStatus.ENDED
    assert loss_run.losses == 2


def test_event_run_prize_and_profit():
    """Test prize and net-profit calculation for a completed run."""
    event = load_test_event()
    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
    for _ in range(6):
        run.add_game(EventGame(result=EventGameResult.WIN), event)
    run.add_game(EventGame(result=EventGameResult.LOSS), event)
    run.add_game(EventGame(result=EventGameResult.LOSS), event)

    assert run.prize(event).gems == 1200
    assert run.prize(event).packs == 8
    assert run.net_profit_gems(event) == 200  # 1200 - 1000 entry
    assert run.highest_milestone(event).name == "Profit Run"


def test_event_run_profit_when_paid_in_gold_uses_gems_price():
    """Test that a gold-paid entry falls back to the event's Gems price for
    net-profit calc, since gold has no fixed gems conversion rate of its own."""
    event = load_test_event()
    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gold")
    for _ in range(7):
        run.add_game(EventGame(result=EventGameResult.WIN), event)
    # Falls back to the event's Gems entry option (1000) as no explicit
    # gems_equivalent was set on the Gold option.
    assert run.net_profit_gems(event) == 500


def test_event_run_profit_with_token_entry():
    """Test that a token-based entry option falls back to the event's Gems
    price for net-profit calc when it has no explicit gems_equivalent."""
    event = load_test_event()
    event.entry_options.append(EntryOption(currency="Jumpstart Token", amount=1))
    run = EventRun(
        run_id="r1", event_id=event.event_id, entry_currency="Jumpstart Token"
    )
    for _ in range(3):
        run.add_game(EventGame(result=EventGameResult.WIN), event)
    run.add_game(EventGame(result=EventGameResult.LOSS), event)
    run.add_game(EventGame(result=EventGameResult.LOSS), event)

    assert run.wins == 3
    assert run.prize(event).gems == 500
    assert run.net_profit_gems(event) == -500


def test_event_stats_session_and_alltime_aggregation():
    """Test EventStats folding completed runs into session/all-time totals."""
    event = load_test_event()
    stats = EventStats()

    run1 = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
    stats.start_run(run1)
    for _ in range(7):
        stats.record_game(EventGame(result=EventGameResult.WIN), event)

    assert run1.status == EventRunStatus.ENDED
    assert stats.session_runs_played == 1
    assert stats.session_wins == 7
    assert stats.session_gems == 1500
    assert stats.alltime_wins == 7
    assert stats.session_milestone_counts["Trophy"] == 1

    run2 = EventRun(run_id="r2", event_id=event.event_id, entry_currency="Gems")
    stats.start_run(run2)
    stats.record_game(EventGame(result=EventGameResult.LOSS), event)
    stats.record_game(EventGame(result=EventGameResult.LOSS), event)

    assert stats.session_runs_played == 2
    assert stats.session_wins == 7  # unchanged, run2 had 0 wins
    assert stats.session_losses == 2
    assert stats.alltime_gems == 1500 + 100  # trophy + 0-win run

    # Restarting the session clears session_* but keeps alltime_*.
    stats.restart_session()
    assert stats.session_runs_played == 0
    assert stats.session_wins == 0
    assert stats.alltime_wins == 7  # unchanged
    assert stats.alltime_gems == 1600  # unchanged


def test_event_stats_tracks_play_draw_cumulatively():
    """Test that alltime_plays/alltime_draws are true running counters,
    not derived from recent_runs (which is capped to the last 5
    completed runs and would silently under-count an "overall"
    percentage once more runs than that have been played)."""
    event = load_test_event()
    stats = EventStats()

    for i in range(6):
        run = EventRun(run_id=f"r{i}", event_id=event.event_id, entry_currency="Gems")
        stats.start_run(run)
        stats.record_game(EventGame(result=EventGameResult.LOSS, play_draw="Play"), event)
        stats.record_game(EventGame(result=EventGameResult.LOSS, play_draw="Draw"), event)

    # 6 completed runs, each 1 Play + 1 Draw, but recent_runs only keeps the last 5.
    assert len(stats.recent_runs) == 5
    assert stats.alltime_plays == 6
    assert stats.alltime_draws == 6

    # EventRun.plays/draws are computed live for an in-progress run.
    run = EventRun(run_id="r_active", event_id=event.event_id, entry_currency="Gems")
    stats.start_run(run)
    stats.record_game(EventGame(result=EventGameResult.WIN, play_draw="Play"), event)
    assert run.plays == 1
    assert run.draws == 0

    stats.restart_session()
    assert stats.session_plays == 0
    assert stats.session_draws == 0
    assert stats.alltime_plays == 6  # unchanged

    stats.wipe_alltime()
    assert stats.alltime_plays == 0
    assert stats.alltime_draws == 0


def test_event_stats_restart_session_discards_active_run():
    """Test that restarting the session discards an in-progress run, rather
    than leaving its stale wins/losses displayed after the reset."""
    event = load_test_event()
    stats = EventStats()

    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
    stats.start_run(run)
    stats.record_game(EventGame(result=EventGameResult.WIN), event)

    assert stats.current_run is run
    assert stats.current_run.status == EventRunStatus.ACTIVE

    stats.restart_session()
    assert stats.current_run is None


def test_event_stats_run_goal_wins_persists_across_restart():
    """Test that a run win goal survives restart_session() (mirrors
    ranked's session_goal_tier, which also isn't cleared on reset) - only
    wipe_alltime() should clear it."""
    stats = EventStats()
    stats.run_goal_wins = 5
    stats.session_wins = 5

    stats.restart_session()
    assert stats.run_goal_wins == 5
    assert stats.session_wins == 0

    stats.wipe_alltime()
    assert stats.run_goal_wins is None


def test_event_stats_wipe_alltime_clears_everything():
    """Test that wiping all-time totals also clears session totals, the
    current run, and recent-runs history (unlike restart_session, which
    keeps all-time totals)."""
    event = load_test_event()
    stats = EventStats()

    run1 = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
    stats.start_run(run1)
    for _ in range(7):
        stats.record_game(EventGame(result=EventGameResult.WIN), event)

    run2 = EventRun(run_id="r2", event_id=event.event_id, entry_currency="Gems")
    stats.start_run(run2)
    stats.record_game(EventGame(result=EventGameResult.WIN), event)

    assert stats.alltime_wins == 7  # run2 is still active, not yet folded in
    assert stats.current_run is run2
    assert len(stats.recent_runs) == 1

    stats.wipe_alltime()

    assert stats.current_run is None
    assert stats.session_runs_played == 0
    assert stats.session_wins == 0
    assert stats.alltime_runs_played == 0
    assert stats.alltime_wins == 0
    assert stats.alltime_losses == 0
    assert stats.alltime_gems == 0
    assert stats.alltime_packs == 0
    assert stats.alltime_milestone_counts == {}
    assert stats.recent_runs == []


def test_event_stats_rejects_game_with_no_active_run():
    """Test that recording a game with no active run is a safe no-op."""
    event = load_test_event()
    stats = EventStats()
    assert stats.record_game(EventGame(result=EventGameResult.WIN), event) is False


def test_event_stats_concede_run_folds_partial_record():
    """Test that conceding a run early ends it and folds its partial
    record into session/all-time totals, same as a natural completion -
    a run previously could only end by reaching win_cap/loss_cap."""
    event = load_test_event()
    stats = EventStats()

    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
    stats.start_run(run)
    stats.record_game(EventGame(result=EventGameResult.WIN), event)

    assert run.status == EventRunStatus.ACTIVE
    assert stats.concede_run(event) is True
    assert run.status == EventRunStatus.ENDED
    assert stats.session_runs_played == 1
    assert stats.session_wins == 1
    assert stats.alltime_runs_played == 1
    assert stats.alltime_gems == 150  # 1-win prize tier

    # Conceding again (no active run) is a safe no-op.
    assert stats.concede_run(event) is False


def test_state_manager_persists_event_stats():
    """Test that EventStats (including nested runs) survives a save/load round trip."""
    with tempfile.TemporaryDirectory() as temp_dir:
        event = load_test_event()

        sm = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        app_data = sm.load_state()

        run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
        app_data.event_stats.start_run(run)
        for _ in range(6):
            app_data.event_stats.record_game(EventGame(result=EventGameResult.WIN), event)
        app_data.event_stats.record_game(EventGame(result=EventGameResult.LOSS), event)
        app_data.event_stats.record_game(EventGame(result=EventGameResult.LOSS), event)

        sm.save_state(app_data)

        sm2 = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        loaded = sm2.load_state()

        assert loaded.event_stats.event_id == event.event_id
        assert loaded.event_stats.session_wins == 6
        assert loaded.event_stats.session_losses == 2
        assert loaded.event_stats.alltime_gems == 1200
        assert loaded.event_stats.current_run.status == EventRunStatus.ENDED
        assert len(loaded.event_stats.recent_runs) == 1
        assert len(loaded.event_stats.recent_runs[0].games) == 8
        assert loaded.event_stats.recent_runs[0].games[0].result == EventGameResult.WIN


def test_state_manager_survives_renamed_field_in_saved_file():
    """Regression test: a saved file containing a field name that no
    longer exists on the dataclass (e.g. from a version before a field
    was renamed) must not wipe the rest of the user's data. This
    reproduces a real incident: renaming EventStats.session_goal_wins to
    run_goal_wins broke loading for anyone who'd already saved with the
    old name, and the broad except in load_state() silently discarded
    the ENTIRE save file (ranks, sessions, event history) in response."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sm = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        app_data = sm.load_state()
        app_data.event_stats.event_id = "historic_pauper_challenge"
        app_data.event_stats.alltime_wins = 42
        sm.save_state(app_data)

        state_file = Path(temp_dir) / "tracker_state.json"
        data = json.loads(state_file.read_text())
        # Simulate a field that existed in an older version and no longer
        # matches any current EventStats field.
        data["event_stats"]["some_field_that_no_longer_exists"] = "stale value"
        state_file.write_text(json.dumps(data, indent=2))

        sm2 = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        loaded = sm2.load_state()

        assert loaded.event_stats.alltime_wins == 42
        assert loaded.event_stats.event_id == "historic_pauper_challenge"


def test_state_manager_deserializes_datetimes_nested_in_lists():
    """Regression test: EventGame.timestamp and EventRun.start_time/
    end_time live inside lists (current_run.games, recent_runs), and the
    datetime-deserialization walk only recursed into dicts, not lists -
    so these came back as plain ISO strings instead of datetime objects
    after every reload."""
    with tempfile.TemporaryDirectory() as temp_dir:
        event = load_test_event()

        sm = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        app_data = sm.load_state()

        run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
        app_data.event_stats.start_run(run)
        app_data.event_stats.record_game(EventGame(result=EventGameResult.WIN), event)
        sm.save_state(app_data)

        sm2 = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        loaded = sm2.load_state()

        from datetime import datetime as dt

        assert isinstance(loaded.event_stats.current_run.start_time, dt)
        assert isinstance(loaded.event_stats.current_run.games[0].timestamp, dt)


def test_state_manager_export_import_round_trip():
    """Test that export_state()/import_state() round-trip event data
    correctly, and that import_state() doesn't touch the live state file
    (it's a separate, standalone backup file)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        event = load_test_event()

        sm = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        app_data = sm.load_state()
        run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
        app_data.event_stats.start_run(run)
        app_data.event_stats.record_game(EventGame(result=EventGameResult.WIN), event)
        app_data.event_stats.alltime_wins = 5

        export_path = sm.export_state(app_data)
        assert export_path.exists()

        imported = sm.import_state(export_path)
        assert imported.event_stats.alltime_wins == 5
        assert imported.event_stats.current_run.games[0].result == EventGameResult.WIN

        # export_state() must not have touched the live (unrelated) state file.
        assert not sm.state_file.exists()


def main():
    """Run all event model tests."""
    test_load_event_catalog()
    test_prize_for_wins()
    test_milestones()
    test_event_game_records_play_draw_and_opponent_deck()
    test_event_run_completes_at_caps()
    test_event_run_prize_and_profit()
    test_event_run_profit_when_paid_in_gold_uses_gems_price()
    test_event_run_profit_with_token_entry()
    test_event_stats_session_and_alltime_aggregation()
    test_event_stats_tracks_play_draw_cumulatively()
    test_event_stats_restart_session_discards_active_run()
    test_event_stats_run_goal_wins_persists_across_restart()
    test_event_stats_wipe_alltime_clears_everything()
    test_event_stats_rejects_game_with_no_active_run()
    test_event_stats_concede_run_folds_partial_record()
    test_state_manager_persists_event_stats()
    test_state_manager_survives_renamed_field_in_saved_file()
    test_state_manager_deserializes_datetimes_nested_in_lists()
    test_state_manager_export_import_round_trip()
    print("All manual-TUI event model tests passed!")


if __name__ == "__main__":
    main()
