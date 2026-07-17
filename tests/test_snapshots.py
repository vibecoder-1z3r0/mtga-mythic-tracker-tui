#!/usr/bin/env python3
"""
Visual regression tests using pytest-textual-snapshot.

Each test renders the app to an SVG and compares it against a committed
"golden" snapshot under __snapshots__/test_snapshots/. A mismatch (layout,
color, text) fails the test. To intentionally update a snapshot after a
real visual change, run: pytest test_snapshots.py --snapshot-update
"""

import tempfile
from pathlib import Path
from unittest.mock import patch


def _make_app():
    from main_tui import MTGASessionTrackerApp

    return MTGASessionTrackerApp()


def test_main_screen_empty_state(snap_compare):
    """Main screen before any session has been started."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("pathlib.Path.home", return_value=Path(temp_dir)):
            app = _make_app()
            assert snap_compare(app, terminal_size=(80, 24))


def test_main_screen_active_session(snap_compare):
    """Main screen with a ranked session in progress."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("pathlib.Path.home", return_value=Path(temp_dir)):
            app = _make_app()
            assert snap_compare(app, press=["s"], terminal_size=(80, 24))


def test_event_screen_mid_run(snap_compare):
    """Event mode screen partway through a run (3 wins, 1 loss)."""

    async def play_partial_run(pilot):
        await pilot.press("v")
        await pilot.pause(0.1)
        await pilot.click("#start-run-btn")
        await pilot.pause(0.1)
        for _ in range(3):
            await pilot.click("#win-btn")
            await pilot.pause(0.1)
        await pilot.click("#loss-btn")
        await pilot.pause(0.1)

    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("pathlib.Path.home", return_value=Path(temp_dir)):
            app = _make_app()
            assert snap_compare(app, run_before=play_partial_run, terminal_size=(80, 24))
