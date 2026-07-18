#!/usr/bin/env python3
"""
Test script for the manual TUI's event-mode models (EventDefinition,
EventRun, EventStats) and StateManager persistence round-trip.
"""
import json
import tempfile
from datetime import datetime, timedelta
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

# manual_tui imports Textual (needed only for this one UI-logic test below,
# _run_result_emoji - everything else in this file is model-layer only).
from manual_tui import _run_result_emoji


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
    # 1200 gems + 8 packs * 200 gems/pack - 1000 entry = 1800
    assert run.net_profit_gems(event) == 1800
    assert run.highest_milestone(event).name == "Profit Run"


def test_run_result_emoji_matches_real_prize_table():
    """Test _run_result_emoji() against the actual Historic Pauper
    Challenge prize table (win_cap=7, 1000 Gems entry) - this locks in
    the exact win-count boundaries agreed after several rounds of
    back-and-forth, since the money-bag ("free run") tier in particular
    depends on real prize numbers (gems alone, packs excluded, first
    reach the entry cost), not a fixed percentage of win_cap."""
    event = load_test_event()
    expected = {
        0: "💀",
        1: "😢",
        2: "😐",
        3: "😐",
        4: "✅",
        5: "💰",  # prize.gems == 1000 == entry cost: breakeven
        6: "🔥",
        7: "🏆",
    }
    for wins, emoji in expected.items():
        run = EventRun(run_id=f"r{wins}", event_id=event.event_id, entry_currency="Gems")
        for _ in range(wins):
            run.add_game(EventGame(result=EventGameResult.WIN), event)
        for _ in range(event.loss_cap if wins < event.win_cap else 0):
            run.add_game(EventGame(result=EventGameResult.LOSS), event)
        assert _run_result_emoji(run, event) == emoji, f"{wins} wins"


def test_event_run_profit_when_paid_in_gold_uses_gems_price():
    """Test that a gold-paid entry falls back to the event's Gems price for
    net-profit calc, since gold has no fixed gems conversion rate of its own."""
    event = load_test_event()
    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gold")
    for _ in range(7):
        run.add_game(EventGame(result=EventGameResult.WIN), event)
    # Falls back to the event's Gems entry option (1000) as no explicit
    # gems_equivalent was set on the Gold option.
    # 1500 gems + 10 packs * 200 gems/pack - 1000 entry = 2500
    assert run.net_profit_gems(event) == 2500


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
    # 500 gems + 2 packs * 200 gems/pack - 1000 entry = -100
    assert run.net_profit_gems(event) == -100


def test_event_stats_session_and_alltime_net_gems():
    """Test session_net_gems()/alltime_net_gems(): sum of each run's own
    net_profit_gems() (prize gems + packs-as-gems minus that run's entry
    cost). Motivated by a real user report: with N finished runs at a
    fixed gems entry cost each, and packs converted to gems at
    event.pack_gems_value (200, MTGA's real pack price), net gems should
    equal total prize gems + total prize packs * 200 - total entry spent."""
    event = load_test_event()
    stats = EventStats()

    win_counts = [0, 0, 1, 1, 2, 2, 3, 4, 5, 7]
    expected_gems = 0
    expected_packs = 0
    for wins in win_counts:
        run = EventRun(run_id=f"r{wins}", event_id=event.event_id, entry_currency="Gems")
        stats.start_run(run)
        for _ in range(wins):
            stats.record_game(EventGame(result=EventGameResult.WIN), event)
        # Finish the run off with losses if it didn't already hit win_cap.
        while stats.current_run.status != EventRunStatus.ENDED:
            stats.record_game(EventGame(result=EventGameResult.LOSS), event)
        prize = run.prize(event)
        expected_gems += prize.gems
        expected_packs += prize.packs

    assert len(stats.recent_runs) == len(win_counts)
    assert stats.alltime_prize(event).gems == expected_gems
    assert stats.alltime_prize(event).packs == expected_packs

    entry_spent = len(win_counts) * 1000  # every run entered with 1000 Gems
    expected_net = expected_gems + expected_packs * event.pack_gems_value - entry_spent
    assert stats.alltime_net_gems(event) == expected_net

    # All runs are still within the only-ever session, so session and
    # all-time net gems must match exactly.
    assert stats.session_net_gems(event) == stats.alltime_net_gems(event) == expected_net

    # After restarting the session, session_net_gems reads 0 (nothing
    # completed since the new marker) while all-time is untouched.
    stats.restart_session()
    assert stats.session_net_gems(event) == 0
    assert stats.alltime_net_gems(event) == expected_net


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
    assert stats.session_prize(event).gems == 1500
    assert stats.alltime_wins == 7
    assert stats.session_milestone_counts(event)["Trophy"] == 1

    run2 = EventRun(run_id="r2", event_id=event.event_id, entry_currency="Gems")
    stats.start_run(run2)
    stats.record_game(EventGame(result=EventGameResult.LOSS), event)
    stats.record_game(EventGame(result=EventGameResult.LOSS), event)

    assert stats.session_runs_played == 2
    assert stats.session_wins == 7  # unchanged, run2 had 0 wins
    assert stats.session_losses == 2
    assert stats.alltime_prize(event).gems == 1500 + 100  # trophy + 0-win run

    # Restarting the session clears session_* but keeps alltime_* (which is
    # computed from recent_runs, untouched by restart_session()).
    stats.restart_session()
    assert stats.session_runs_played == 0
    assert stats.session_wins == 0
    assert stats.alltime_wins == 7  # unchanged
    assert stats.alltime_prize(event).gems == 1600  # unchanged


def test_event_stats_tracks_play_draw_cumulatively():
    """Test that alltime_plays/alltime_draws are computed across every
    completed run in recent_runs (which is NOT capped - a "last N runs"
    list can't answer an "overall" percentage correctly once you've
    played more than N runs, which is why it holds full history)."""
    event = load_test_event()
    stats = EventStats()

    for i in range(6):
        run = EventRun(run_id=f"r{i}", event_id=event.event_id, entry_currency="Gems")
        stats.start_run(run)
        stats.record_game(EventGame(result=EventGameResult.LOSS, play_draw="Play"), event)
        stats.record_game(EventGame(result=EventGameResult.LOSS, play_draw="Draw"), event)

    # 6 completed runs, each 1 Play + 1 Draw, and none evicted.
    assert len(stats.recent_runs) == 6
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
    assert stats.alltime_plays == 6  # unchanged, still derived from recent_runs

    stats.wipe_alltime()
    assert stats.alltime_plays == 0
    assert stats.alltime_draws == 0


def test_event_stats_restart_session_preserves_active_run():
    """Regression test for a real data-loss incident: restart_session()
    used to discard the in-progress run entirely, silently throwing away
    real, already-played games with no way to recover them. A session
    restart should only reset session-scoped totals/timer - an active run
    keeps playing across the boundary and correctly counts toward the
    *new* session once it completes."""
    event = load_test_event()
    stats = EventStats()

    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
    stats.start_run(run)
    stats.record_game(EventGame(result=EventGameResult.WIN), event)

    assert stats.current_run is run
    assert stats.current_run.status == EventRunStatus.ACTIVE

    stats.restart_session()
    assert stats.current_run is run
    assert stats.current_run.status == EventRunStatus.ACTIVE
    assert stats.current_run.wins == 1

    # Finish the run off after the restart - it should fold into the NEW
    # session's totals, not be lost or misattributed to the old one.
    for _ in range(event.loss_cap):
        stats.record_game(EventGame(result=EventGameResult.LOSS), event)
    assert stats.current_run.status == EventRunStatus.ENDED
    assert stats.session_wins == 1
    assert stats.session_losses == event.loss_cap
    assert stats.session_runs_played == 1


def test_event_stats_session_start_time_resets_on_restart_and_wipe():
    """Test that session_start_time defaults to "now" on a fresh EventStats
    (so a brand-new session's duration starts at ~0, not some huge/invalid
    value), and gets reset again on restart_session()/wipe_alltime() -
    otherwise the session timer would keep counting from the very first
    session ever, not the current one."""
    stats = EventStats()
    initial_start = stats.session_start_time
    assert initial_start is not None
    assert stats.session_duration().total_seconds() < 1

    # Simulate time passing by backdating session_start_time directly.
    stats.session_start_time = initial_start - timedelta(hours=2)
    assert stats.session_duration().total_seconds() >= 2 * 3600 - 1

    stats.restart_session()
    assert stats.session_start_time > initial_start
    assert stats.session_duration().total_seconds() < 1

    stats.session_start_time = stats.session_start_time - timedelta(hours=3)
    before_wipe = stats.session_start_time
    stats.wipe_alltime()
    assert stats.session_start_time > before_wipe
    assert stats.session_duration().total_seconds() < 1


def test_event_stats_pause_resume_excludes_paused_time_from_duration():
    """Test that pause_session()/resume_session() work like ranked mode's
    equivalent: pausing freezes session_duration() in place, and resuming
    subtracts the paused interval from all future duration readings
    rather than including it."""
    stats = EventStats()
    stats.session_start_time = datetime.now() - timedelta(seconds=10)
    assert not stats.session_paused

    stats.pause_session()
    assert stats.session_paused
    assert stats.pause_start_time is not None

    # Backdate the pause start to simulate 5 real seconds having passed
    # while paused, without needing an actual sleep() in the test.
    stats.pause_start_time = datetime.now() - timedelta(seconds=5)
    duration_while_paused = stats.session_duration()
    # ~5s elapsed (10s total - 5s currently-paused), regardless of how
    # long this assertion takes to run, since pause freezes the clock.
    assert 4 <= duration_while_paused.total_seconds() <= 6

    # Calling session_duration() again immediately shouldn't have moved
    # (beyond sub-millisecond float rounding from the two now() calls),
    # confirming it's truly frozen rather than just coincidentally equal.
    redelta = abs((stats.session_duration() - duration_while_paused).total_seconds())
    assert redelta < 0.01

    stats.resume_session()
    assert not stats.session_paused
    assert stats.pause_start_time is None
    assert stats.total_paused_time >= 5

    # After resuming, duration should still read ~5s (10s wall-clock minus
    # the ~5s that was paused), not the full ~10s.
    duration_after_resume = stats.session_duration()
    assert 4 <= duration_after_resume.total_seconds() <= 6

    # A no-op pause/resume on an already-paused/already-running stats
    # object shouldn't do anything destructive.
    stats.resume_session()  # already resumed - no-op
    assert stats.total_paused_time >= 5


def test_event_stats_run_goal_wins_persists_across_restart():
    """Test that a run win goal survives restart_session() (mirrors
    ranked's session_goal_tier, which also isn't cleared on reset) - only
    wipe_alltime() should clear it. Also confirms restart_session() zeroes
    session_wins (via the session_start_run_count marker) while leaving
    alltime_wins (computed from the full recent_runs) untouched."""
    event = load_test_event()
    stats = EventStats()
    stats.run_goal_wins = 5

    run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
    stats.start_run(run)
    for _ in range(7):
        stats.record_game(EventGame(result=EventGameResult.WIN), event)
    assert stats.session_wins == 7

    stats.restart_session()
    assert stats.run_goal_wins == 5
    assert stats.session_wins == 0
    assert stats.alltime_wins == 7  # unchanged

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
    assert stats.alltime_prize(event).gems == 0
    assert stats.alltime_prize(event).packs == 0
    assert stats.alltime_milestone_counts(event) == {}
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
    assert stats.alltime_prize(event).gems == 150  # 1-win prize tier

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
        assert loaded.event_stats.alltime_prize(event).gems == 1200
        assert loaded.event_stats.current_run.status == EventRunStatus.ENDED
        assert len(loaded.event_stats.recent_runs) == 1
        assert len(loaded.event_stats.recent_runs[0].games) == 8
        assert loaded.event_stats.recent_runs[0].games[0].result == EventGameResult.WIN


def test_state_manager_round_trips_session_start_time():
    """Test that session_start_time survives a save/load round trip as a
    real datetime (not a string), and that a save file from before this
    field existed falls back to session_start_time defaulting to "now"
    rather than crashing or leaving it unset."""
    with tempfile.TemporaryDirectory() as temp_dir:
        from datetime import datetime as dt

        sm = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        app_data = sm.load_state()
        app_data.event_stats.session_start_time = dt(2026, 1, 1, 12, 0, 0)
        sm.save_state(app_data)

        sm2 = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        loaded = sm2.load_state()
        assert isinstance(loaded.event_stats.session_start_time, dt)
        assert loaded.event_stats.session_start_time == dt(2026, 1, 1, 12, 0, 0)

        # Simulate a save from before session_start_time existed.
        state_file = Path(temp_dir) / "tracker_state.json"
        data = json.loads(state_file.read_text())
        del data["event_stats"]["session_start_time"]
        state_file.write_text(json.dumps(data, indent=2))

        sm3 = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        reloaded = sm3.load_state()
        assert isinstance(reloaded.event_stats.session_start_time, dt)
        assert reloaded.event_stats.session_duration().total_seconds() < 5


def test_state_manager_survives_renamed_field_in_saved_file():
    """Regression test: a saved file containing a field name that no
    longer exists on the dataclass (e.g. from a version before a field
    was renamed) must not wipe the rest of the user's data. This
    reproduces a real incident: renaming EventStats.session_goal_wins to
    run_goal_wins broke loading for anyone who'd already saved with the
    old name, and the broad except in load_state() silently discarded
    the ENTIRE save file (ranks, sessions, event history) in response."""
    with tempfile.TemporaryDirectory() as temp_dir:
        event = load_test_event()

        sm = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        app_data = sm.load_state()
        app_data.event_stats.event_id = event.event_id
        run = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
        app_data.event_stats.start_run(run)
        for _ in range(7):
            app_data.event_stats.record_game(EventGame(result=EventGameResult.WIN), event)
        sm.save_state(app_data)

        state_file = Path(temp_dir) / "tracker_state.json"
        data = json.loads(state_file.read_text())
        # Simulate a field that existed in an older version and no longer
        # matches any current EventStats field.
        data["event_stats"]["some_field_that_no_longer_exists"] = "stale value"
        state_file.write_text(json.dumps(data, indent=2))

        sm2 = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        loaded = sm2.load_state()

        assert loaded.event_stats.alltime_wins == 7
        assert loaded.event_stats.event_id == event.event_id


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
        for _ in range(7):
            app_data.event_stats.record_game(EventGame(result=EventGameResult.WIN), event)

        export_path = sm.export_state(app_data)
        assert export_path.exists()

        imported = sm.import_state(export_path)
        assert imported.event_stats.alltime_wins == 7
        assert imported.event_stats.recent_runs[0].games[0].result == EventGameResult.WIN

        # export_state() must not have touched the live (unrelated) state file.
        assert not sm.state_file.exists()


def test_state_manager_recomputes_alltime_from_stale_stored_counters():
    """Regression test: a save file written by an older version that still
    stored alltime_wins/losses/gems/packs/plays/draws/milestone_counts as
    plain fields (before they became computed from recent_runs) has all of
    those stale keys in its JSON. Loading must not crash on them (they're
    dropped by _known_fields() same as any other now-unrecognized field),
    and the computed properties must reflect the real recent_runs history
    rather than the stale stored numbers."""
    with tempfile.TemporaryDirectory() as temp_dir:
        event = load_test_event()

        sm = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        app_data = sm.load_state()

        run1 = EventRun(run_id="r1", event_id=event.event_id, entry_currency="Gems")
        app_data.event_stats.start_run(run1)
        app_data.event_stats.record_game(
            EventGame(result=EventGameResult.WIN, play_draw="Play"), event
        )
        app_data.event_stats.record_game(
            EventGame(result=EventGameResult.LOSS, play_draw="Draw"), event
        )
        app_data.event_stats.record_game(
            EventGame(result=EventGameResult.LOSS, play_draw="Play"), event
        )
        # loss_cap is 2: this completed the run at 1 win, 2 losses.
        assert len(app_data.event_stats.recent_runs) == 1
        sm.save_state(app_data)

        state_file = Path(temp_dir) / "tracker_state.json"
        data = json.loads(state_file.read_text())
        # Simulate a save from before these became computed properties -
        # deliberately wrong numbers, to prove they get ignored on load.
        data["event_stats"]["alltime_wins"] = 999
        data["event_stats"]["alltime_losses"] = 999
        data["event_stats"]["alltime_gems"] = 999
        data["event_stats"]["alltime_packs"] = 999
        data["event_stats"]["alltime_plays"] = 999
        data["event_stats"]["alltime_draws"] = 999
        data["event_stats"]["alltime_milestone_counts"] = {"stale": 999}
        state_file.write_text(json.dumps(data, indent=2))

        sm2 = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        reloaded = sm2.load_state()

        assert reloaded.event_stats.alltime_wins == 1
        assert reloaded.event_stats.alltime_losses == 2
        assert reloaded.event_stats.alltime_plays == 2
        assert reloaded.event_stats.alltime_draws == 1
        assert reloaded.event_stats.alltime_milestone_counts(event) == {}


def test_state_manager_legacy_save_treats_all_history_as_current_session():
    """Regression test for a real user report: a save file written before
    session_* became computed from recent_runs (and before
    session_start_run_count existed at all) has stale session_wins/losses/
    gems/packs/plays/draws/milestone_counts fields and no
    session_start_run_count key. On load, the stale fields must be dropped
    (same as any other unrecognized field) and session_start_run_count must
    default to 0 - meaning every run in recent_runs counts as "this
    session," so session_* exactly equals alltime_* whenever this is the
    only session that's ever been played. That equality is exactly what
    broke before this fix: session_plays/session_draws were separately
    stored counters that could only reflect runs completed after they
    started being tracked, while alltime_plays/alltime_draws are computed
    from the complete history - so the two diverged even for a user who'd
    never once called restart_session()."""
    with tempfile.TemporaryDirectory() as temp_dir:
        event = load_test_event()

        sm = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        app_data = sm.load_state()

        for i in range(3):
            run = EventRun(run_id=f"r{i}", event_id=event.event_id, entry_currency="Gems")
            app_data.event_stats.start_run(run)
            app_data.event_stats.record_game(
                EventGame(result=EventGameResult.LOSS, play_draw="Play"), event
            )
            app_data.event_stats.record_game(
                EventGame(result=EventGameResult.LOSS, play_draw="Draw"), event
            )
        sm.save_state(app_data)

        state_file = Path(temp_dir) / "tracker_state.json"
        data = json.loads(state_file.read_text())
        # Simulate a save from before session_* was computed: stale stored
        # counters that under-count relative to the real history, and no
        # session_start_run_count key at all.
        data["event_stats"]["session_wins"] = 0
        data["event_stats"]["session_losses"] = 0
        data["event_stats"]["session_plays"] = 0
        data["event_stats"]["session_draws"] = 0
        data["event_stats"].pop("session_start_run_count", None)
        state_file.write_text(json.dumps(data, indent=2))

        sm2 = StateManager(data_dir=Path(temp_dir), save_enabled=True)
        reloaded = sm2.load_state()

        assert reloaded.event_stats.session_start_run_count == 0
        assert reloaded.event_stats.session_plays == reloaded.event_stats.alltime_plays == 3
        assert reloaded.event_stats.session_draws == reloaded.event_stats.alltime_draws == 3
        assert reloaded.event_stats.session_losses == reloaded.event_stats.alltime_losses == 6


def main():
    """Run all event model tests."""
    test_load_event_catalog()
    test_prize_for_wins()
    test_milestones()
    test_event_game_records_play_draw_and_opponent_deck()
    test_event_run_completes_at_caps()
    test_event_run_prize_and_profit()
    test_run_result_emoji_matches_real_prize_table()
    test_event_run_profit_when_paid_in_gold_uses_gems_price()
    test_event_run_profit_with_token_entry()
    test_event_stats_session_and_alltime_net_gems()
    test_event_stats_session_and_alltime_aggregation()
    test_event_stats_tracks_play_draw_cumulatively()
    test_event_stats_restart_session_preserves_active_run()
    test_event_stats_session_start_time_resets_on_restart_and_wipe()
    test_event_stats_pause_resume_excludes_paused_time_from_duration()
    test_event_stats_run_goal_wins_persists_across_restart()
    test_event_stats_wipe_alltime_clears_everything()
    test_event_stats_rejects_game_with_no_active_run()
    test_event_stats_concede_run_folds_partial_record()
    test_state_manager_persists_event_stats()
    test_state_manager_round_trips_session_start_time()
    test_state_manager_survives_renamed_field_in_saved_file()
    test_state_manager_deserializes_datetimes_nested_in_lists()
    test_state_manager_export_import_round_trip()
    test_state_manager_recomputes_alltime_from_stale_stored_counters()
    test_state_manager_legacy_save_treats_all_history_as_current_session()
    print("All manual-TUI event model tests passed!")


if __name__ == "__main__":
    main()
