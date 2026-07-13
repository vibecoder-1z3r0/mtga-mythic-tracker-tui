#!/usr/bin/env python3
"""
Test script for the manual TUI's event-mode models (EventDefinition,
EventRun, EventStats) and StateManager persistence round-trip.
"""
import tempfile
from pathlib import Path

from models.event import (
    EntryCurrency,
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
    assert event.entry_cost_gold == 5000
    assert event.entry_cost_gems == 1000
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


def test_event_run_completes_at_caps():
    """Test that a run ends automatically at win_cap or loss_cap."""
    event = load_test_event()

    win_run = EventRun(run_id="r1", event_id=event.event_id, entry_currency=EntryCurrency.GEMS)
    for _ in range(7):
        win_run.add_game(EventGame(result=EventGameResult.WIN), event)
    assert win_run.status == EventRunStatus.ENDED
    assert win_run.wins == 7
    # No further games accepted once ended.
    assert win_run.add_game(EventGame(result=EventGameResult.WIN), event) is False

    loss_run = EventRun(run_id="r2", event_id=event.event_id, entry_currency=EntryCurrency.GEMS)
    loss_run.add_game(EventGame(result=EventGameResult.LOSS), event)
    loss_run.add_game(EventGame(result=EventGameResult.LOSS), event)
    assert loss_run.status == EventRunStatus.ENDED
    assert loss_run.losses == 2


def test_event_run_prize_and_profit():
    """Test prize and net-profit calculation for a completed run."""
    event = load_test_event()
    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency=EntryCurrency.GEMS)
    for _ in range(6):
        run.add_game(EventGame(result=EventGameResult.WIN), event)
    run.add_game(EventGame(result=EventGameResult.LOSS), event)
    run.add_game(EventGame(result=EventGameResult.LOSS), event)

    assert run.prize(event).gems == 1200
    assert run.prize(event).packs == 8
    assert run.net_profit_gems(event) == 200  # 1200 - 1000 entry
    assert run.highest_milestone(event).name == "Profit Run"


def test_event_run_profit_none_when_paid_in_gold():
    """Test that net profit is undefined when the entry was paid in gold."""
    event = load_test_event()
    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency=EntryCurrency.GOLD)
    for _ in range(7):
        run.add_game(EventGame(result=EventGameResult.WIN), event)
    assert run.net_profit_gems(event) is None


def test_event_stats_session_and_alltime_aggregation():
    """Test EventStats folding completed runs into session/all-time totals."""
    event = load_test_event()
    stats = EventStats()

    run1 = EventRun(run_id="r1", event_id=event.event_id, entry_currency=EntryCurrency.GEMS)
    stats.start_run(run1)
    for _ in range(7):
        stats.record_game(EventGame(result=EventGameResult.WIN), event)

    assert run1.status == EventRunStatus.ENDED
    assert stats.session_runs_played == 1
    assert stats.session_wins == 7
    assert stats.session_gems == 1500
    assert stats.alltime_wins == 7
    assert stats.session_milestone_counts["Trophy"] == 1

    run2 = EventRun(run_id="r2", event_id=event.event_id, entry_currency=EntryCurrency.GEMS)
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


def test_event_stats_rejects_game_with_no_active_run():
    """Test that recording a game with no active run is a safe no-op."""
    event = load_test_event()
    stats = EventStats()
    assert stats.record_game(EventGame(result=EventGameResult.WIN), event) is False


def test_state_manager_persists_event_stats():
    """Test that EventStats (including nested runs) survives a save/load round trip."""
    with tempfile.TemporaryDirectory() as temp_dir:
        event = load_test_event()

        sm = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        app_data = sm.load_state()

        run = EventRun(run_id="r1", event_id=event.event_id, entry_currency=EntryCurrency.GEMS)
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


def main():
    """Run all event model tests."""
    test_load_event_catalog()
    test_prize_for_wins()
    test_milestones()
    test_event_run_completes_at_caps()
    test_event_run_prize_and_profit()
    test_event_run_profit_none_when_paid_in_gold()
    test_event_stats_session_and_alltime_aggregation()
    test_event_stats_rejects_game_with_no_active_run()
    test_state_manager_persists_event_stats()
    print("All manual-TUI event model tests passed!")


if __name__ == "__main__":
    main()
