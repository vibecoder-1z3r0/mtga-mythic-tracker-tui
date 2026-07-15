#!/usr/bin/env python3
"""
Test script for event-mode models (EventDefinition, EventRun, EventSession)
and the event state/data managers.
"""

import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from src.models.event import (
    EntryOption,
    EventGame,
    EventGameResult,
    EventRun,
    EventRunStatus,
    EventSession,
    default_catalog_path,
    load_event_catalog,
)


@contextmanager
def isolated_home():
    """Patch Path.home() to a throwaway temp dir so the global config_manager
    singleton never touches the real ~/.config/mtga-tracker."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("pathlib.Path.home", return_value=Path(temp_dir)):
            yield Path(temp_dir)


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
    assert event.prize_for_wins(3).packs == 2
    assert event.prize_for_wins(7).gems == 1500
    assert event.prize_for_wins(7).packs == 10
    # Wins beyond win_cap should clamp to the win_cap tier.
    assert event.prize_for_wins(99).gems == 1500


def test_milestones():
    """Test milestone threshold matching, cumulative and highest-label."""
    event = load_test_event()

    assert event.milestones_met(2) == []
    met_at_6 = {m.name for m in event.milestones_met(6)}
    assert met_at_6 == {"Winning Run", "Free Run", "Profit Run"}

    assert event.highest_milestone(2) is None
    assert event.highest_milestone(3).name == "Winning Run"
    assert event.highest_milestone(6).name == "Profit Run"
    assert event.highest_milestone(7).name == "Trophy"


def test_event_game_records_play_draw_and_opponent_deck():
    """Test that EventGame carries play/draw and opponent deck, defaulting
    to None (displayed as "Unknown") when not recorded."""
    game_unknown = EventGame(result=EventGameResult.WIN)
    assert game_unknown.play_draw is None
    assert game_unknown.opponent_deck is None

    game_known = EventGame(result=EventGameResult.LOSS, play_draw="Draw", opponent_deck="Mono Red")
    assert game_known.play_draw == "Draw"
    assert game_known.opponent_deck == "Mono Red"


def test_event_run_completes_at_win_cap():
    """Test that a run ends automatically once win_cap is reached."""
    event = load_test_event()
    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")

    for _ in range(6):
        added = run.add_game(EventGame(result=EventGameResult.WIN), event)
        assert added is True
        assert run.status == EventRunStatus.ACTIVE

    added = run.add_game(EventGame(result=EventGameResult.WIN), event)
    assert added is True
    assert run.wins == 7
    assert run.status == EventRunStatus.ENDED
    assert run.end_time is not None

    # No further games accepted once the run has ended.
    rejected = run.add_game(EventGame(result=EventGameResult.WIN), event)
    assert rejected is False
    assert run.wins == 7


def test_event_run_completes_at_loss_cap():
    """Test that a run ends automatically once loss_cap is reached."""
    event = load_test_event()
    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")

    run.add_game(EventGame(result=EventGameResult.WIN), event)
    run.add_game(EventGame(result=EventGameResult.LOSS), event)
    assert run.status == EventRunStatus.ACTIVE

    run.add_game(EventGame(result=EventGameResult.LOSS), event)
    assert run.wins == 1
    assert run.losses == 2
    assert run.status == EventRunStatus.ENDED


def test_event_run_prize_and_profit():
    """Test prize and net-profit calculation for a completed run."""
    event = load_test_event()
    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
    for _ in range(6):
        run.add_game(EventGame(result=EventGameResult.WIN), event)
    run.add_game(EventGame(result=EventGameResult.LOSS), event)
    run.add_game(EventGame(result=EventGameResult.LOSS), event)

    assert run.wins == 6
    assert run.losses == 2
    assert run.prize(event).gems == 1200
    assert run.prize(event).packs == 8
    # Entry cost in gems is 1000, so a 6-win run nets +200 gems.
    assert run.net_profit_gems(event) == 200
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
    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Jumpstart Token")
    for _ in range(3):
        run.add_game(EventGame(result=EventGameResult.WIN), event)
    run.add_game(EventGame(result=EventGameResult.LOSS), event)
    run.add_game(EventGame(result=EventGameResult.LOSS), event)

    assert run.wins == 3
    assert run.prize(event).gems == 500
    # Falls back to the event's Gems entry option (1000) as no explicit
    # gems_equivalent was set on the token option.
    assert run.net_profit_gems(event) == -500


def test_event_session_current_run_and_totals():
    """Test session-level run tracking, totals, and milestone tallying."""
    event = load_test_event()
    session = EventSession(session_id="s1", event_id=event.event_id)

    run1 = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
    session.start_run(run1)
    assert session.current_run() is run1

    for _ in range(7):
        run1.add_game(EventGame(result=EventGameResult.WIN), event)
    assert session.current_run() is None  # run1 ended at win_cap

    run2 = EventRun(run_id="r2", event_id=event.event_id, entry_currency="Gems")
    session.start_run(run2)
    run2.add_game(EventGame(result=EventGameResult.LOSS), event)
    run2.add_game(EventGame(result=EventGameResult.LOSS), event)

    assert session.total_wins() == 7
    assert session.total_losses() == 2
    assert len(session.completed_runs()) == 2

    total_prize = session.total_prize(event)
    assert total_prize.gems == 1500 + 100  # Trophy run + 0-win run
    assert total_prize.packs == 10 + 0

    counts = session.milestone_counts(event)
    assert counts["Trophy"] == 1
    assert counts["Winning Run"] == 1
    assert counts["Free Run"] == 1
    assert counts["Profit Run"] == 1


def test_event_state_manager_lifecycle():
    """Test EventStateManager session/run lifecycle and persistence."""
    with isolated_home():
        from src.core.event_state_manager import EventStateManager

        event = load_test_event()
        manager = EventStateManager()

        session = manager.start_session(event.event_id)
        assert session.status.value == "Active"

        run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
        assert manager.start_run(run) is True

        for _ in range(7):
            assert manager.add_game(EventGame(result=EventGameResult.WIN), event) is True

        assert run.status == EventRunStatus.ENDED
        # No active run left in the session; adding another game should fail.
        assert manager.add_game(EventGame(result=EventGameResult.WIN), event) is False

        ended_session = manager.end_session()
        assert ended_session.status.value == "Ended"
        assert len(ended_session.completed_runs()) == 1


def test_event_data_manager_overall_and_grand_total():
    """Test EventDataManager aggregation across saved sessions."""
    with isolated_home():
        from src.core.event_data_manager import EventDataManager
        from src.core.event_state_manager import EventStateManager

        event = load_test_event()

        # First sitting: a 7-win trophy run.
        manager = EventStateManager()
        manager.start_session(event.event_id)
        run1 = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
        manager.start_run(run1)
        for _ in range(7):
            manager.add_game(EventGame(result=EventGameResult.WIN), event)
        manager.end_session()

        # Second sitting: a 2-loss bust.
        manager2 = EventStateManager()
        manager2.start_session(event.event_id)
        run2 = EventRun(run_id="r2", event_id=event.event_id, entry_currency="Gems")
        manager2.start_run(run2)
        manager2.add_game(EventGame(result=EventGameResult.LOSS), event)
        manager2.add_game(EventGame(result=EventGameResult.LOSS), event)
        manager2.end_session()

        data_manager = EventDataManager()
        assert len(data_manager.list_sessions(event.event_id)) == 2

        stats = data_manager.get_overall_stats(event)
        assert stats["wins"] == 7
        assert stats["losses"] == 2
        assert stats["prize"].gems == 1500 + 100
        assert stats["runs_played"] == 2
        assert stats["milestone_counts"]["Trophy"] == 1

        grand_total = data_manager.get_grand_total([event])
        assert grand_total.gems == 1500 + 100


def main():
    """Run all event model tests."""
    test_load_event_catalog()
    test_prize_for_wins()
    test_milestones()
    test_event_game_records_play_draw_and_opponent_deck()
    test_event_run_completes_at_win_cap()
    test_event_run_completes_at_loss_cap()
    test_event_run_prize_and_profit()
    test_event_run_profit_when_paid_in_gold_uses_gems_price()
    test_event_run_profit_with_token_entry()
    test_event_session_current_run_and_totals()
    test_event_state_manager_lifecycle()
    test_event_data_manager_overall_and_grand_total()
    print("All event model tests passed!")


if __name__ == "__main__":
    main()
