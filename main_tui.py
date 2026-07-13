#!/usr/bin/env python3
"""
MTGA Mythic TUI Session Tracker - Main Application
Professional terminal interface for tracking MTG Arena ranked sessions.
"""

import sys
import argparse
from pathlib import Path
from typing import Optional, List

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header,
    Footer,
    Static,
    Button,
    Label,
    DataTable,
    Input,
    Select,
)
from textual.screen import ModalScreen, Screen
from textual.binding import Binding

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from src.config.settings import config_manager
    from src.core.state_manager import StateManager
    from src.core.event_state_manager import EventStateManager
    from src.core.event_data_manager import EventDataManager
    from src.models.session import Session, SessionStatus  # Changed from SessionTracker
    from src.models.rank import Rank, FormatType
    from src.models.game import Game, GameResult
    from src.models.event import (
        EntryCurrency,
        EventDefinition,
        EventGame,
        EventGameResult,
        EventRun,
        EventRunStatus,
        default_catalog_path,
        load_event_catalog,
    )
    from textual_log_viewer import MTGALogParser as EnhancedLogParser
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure all components are properly installed")
    sys.exit(1)


class CurrentGameWidget(Static):
    """Widget displaying current game information."""

    def __init__(self):
        super().__init__()
        self.game_data = {
            "turn": "?",
            "your_life": "20",
            "opp_life": "20",
            "your_cards": "7",
            "opp_cards": "7",
            "status": "Waiting for game...",
        }

    def compose(self) -> ComposeResult:
        yield Label("Current Game", classes="section-title")
        yield Static(self._format_game_display(), id="game-display")

    def _format_game_display(self) -> str:
        return f"""Turn: {self.game_data['turn']}
You: {self.game_data['your_life']} ♥  │  Opp: {self.game_data['opp_life']} ♥
Cards: {self.game_data['your_cards']}   │  Cards: {self.game_data['opp_cards']}

Status: {self.game_data['status']}"""

    def update_game_data(self, **kwargs):
        """Update game display data."""
        self.game_data.update(kwargs)
        game_display = self.query_one("#game-display", Static)
        game_display.update(self._format_game_display())


class RankProgressWidget(Static):
    """Widget displaying rank progression with ASCII visualization."""

    def __init__(self, current_rank: Optional[Rank] = None):
        super().__init__()
        self.current_rank = current_rank or Rank(tier="Bronze", division=1, pips=0)

    def compose(self) -> ComposeResult:
        yield Label("Rank Progress", classes="section-title")
        yield Static(self._format_rank_display(), id="rank-display")

    def _format_rank_display(self) -> str:
        """Create ASCII rank visualization."""
        rank = self.current_rank

        # Boss fight indicator
        boss_fight_msg = ""
        if hasattr(rank, "is_boss_fight") and rank.is_boss_fight():
            next_tier = rank.next_tier() if hasattr(rank, "next_tier") else "Next Tier"
            boss_fight_msg = f"🔥 BOSS FIGHT! Next win → {next_tier}! 🔥\n"

        # Tier progression
        tiers = ["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Mythic"]
        current_tier_idx = next((i for i, tier in enumerate(tiers) if tier == rank.tier), 0)

        # Build tier display
        tier_display = []
        for i, tier in enumerate(tiers):
            if i < current_tier_idx:
                # Completed tier
                tier_display.append(f"{tier:<8} [████][████][████][████]")
            elif i == current_tier_idx:
                # Current tier with pip progress
                pips_display = self._format_pips(rank.division, rank.pips)

                # Add boss fight styling to current tier
                if hasattr(rank, "is_boss_fight") and rank.is_boss_fight():
                    tier_display.append(f"{tier:<8} {pips_display} ⚔️ BOSS TIER!")
                else:
                    tier_display.append(f"{tier:<8} {pips_display}")
            else:
                # Future tier
                tier_display.append(f"{tier:<8} [    ][    ][    ][    ]")

        # Special handling for Mythic
        if rank.tier == "Mythic":
            percentage = getattr(rank, "mythic_percentage", None)
            if percentage:
                tier_display[-1] = f"Mythic   {percentage:.1f}% (Top Mythic)"

        return boss_fight_msg + "\n".join(tier_display)

    def _format_pips(self, division: int, pips: int) -> str:
        """Format pips for current division."""
        # 4 divisions per tier, 6 pips per division
        pip_displays = []
        for div in range(4, 0, -1):  # 4, 3, 2, 1
            if div > division:
                # Completed division
                pip_displays.append("[████]")
            elif div == division:
                # Current division with pip progress
                filled = "█" * pips
                pip_displays.append(f"[{filled:<6}]".replace(" ", "░"))
            else:
                # Future division
                pip_displays.append("[    ]")
        return "".join(pip_displays)

    def update_rank(self, new_rank: Optional[Rank]):
        """Update rank display."""
        self.current_rank = new_rank or Rank(tier="Bronze", division=1, pips=0)
        rank_display = self.query_one("#rank-display", Static)
        rank_display.update(self._format_rank_display())


class GameHistoryWidget(Static):
    """Widget displaying recent game history."""

    def __init__(self):
        super().__init__()
        self.games: List[Game] = []

    def compose(self) -> ComposeResult:
        yield Label("Game History", classes="section-title")
        yield DataTable(id="history-table")

    def on_mount(self):
        """Setup the history table."""
        table = self.query_one("#history-table", DataTable)
        table.add_columns("Time", "Result", "Details")
        table.cursor_type = "row"

    def add_game(self, game: Game):
        """Add a new game to history."""
        self.games.insert(0, game)  # Most recent first
        self._refresh_table()

    def _refresh_table(self):
        """Refresh the history table display."""
        table = self.query_one("#history-table", DataTable)
        table.clear()

        for game in self.games[:20]:  # Show last 20 games
            time_str = game.timestamp.strftime("%H:%M")
            result_str = "🏆 W" if game.result == GameResult.WIN else "💀 L"
            details = f"{game.play_order.value} vs {game.opponent_deck or 'Unknown'}"
            if game.notes:
                details += f" - {game.notes[:30]}"

            table.add_row(time_str, result_str, details)


class SessionStatsWidget(Static):
    """Widget displaying session statistics."""

    def __init__(self):
        super().__init__()
        self.session: Optional[Session] = None

    def compose(self) -> ComposeResult:
        yield Label("Session Stats", classes="section-title")
        yield Static(self._format_stats(), id="stats-display")

    def _format_stats(self) -> str:
        if not self.session:
            return "No active session"

        stats = self.session.stats
        duration = self.session.get_duration_minutes()
        games_per_hour = (stats.total_games / (duration / 60)) if duration > 0 else 0.0

        return f"""Record: {stats.wins}W - {stats.losses}L
Win Rate: {stats.win_rate():.1f}%
Duration: {duration} min
Games/Hour: {games_per_hour:.1f}

Starting Rank: {self.session.starting_rank}
Current Rank: {self.session.current_rank}"""

    def update_session(self, session: Optional[Session]):
        """Update session display."""
        self.session = session
        stats_display = self.query_one("#stats-display", Static)
        stats_display.update(self._format_stats())


class ConfigurationScreen(ModalScreen):
    """Configuration modal screen."""

    BINDINGS = [
        Binding("escape", "cancel_config", "Cancel"),
    ]

    CSS = """
    ConfigurationScreen {
        align: center middle;
    }

    #config-dialog {
        width: 90%;
        height: 70%;
        border: thick $primary;
        background: $surface;
        padding: 2;
    }

    .config-columns {
        width: 1fr;
        height: 1fr;
    }

    .config-column {
        width: 50%;
        padding: 0 1;
    }

    .config-row {
        height: 3;
        margin: 1 0;
    }

    .config-label {
        width: 20;
        content-align: right middle;
    }

    .config-input {
        width: 1fr;
        margin-left: 1;
    }
    """

    def __init__(self, current_config):
        super().__init__()
        self.config = current_config

    def compose(self) -> ComposeResult:
        with Container(id="config-dialog"):
            yield Label("Configuration Settings", classes="section-title")

            # Two-column layout
            with Horizontal(classes="config-columns"):
                # Left Column
                with Vertical(classes="config-column"):
                    # MTGA Log File Path
                    with Horizontal(classes="config-row"):
                        yield Label("Log Path:", classes="config-label")
                        yield Input(
                            value=str(self.config.mtga.log_file_path or ""),
                            placeholder="Path to Player.log",
                            id="log-path-input",
                            classes="config-input",
                        )

                    # Default Format
                    with Horizontal(classes="config-row"):
                        yield Label("Format:", classes="config-label")
                        yield Select(
                            [
                                ("Constructed", "Constructed"),
                                ("Standard", "Standard"),
                                ("Alchemy", "Alchemy"),
                                ("Historic", "Historic"),
                                ("Explorer", "Explorer"),
                                ("Limited", "Limited"),
                            ],
                            value=self.config.ui.default_format,
                            id="format-select",
                            classes="config-input",
                        )

                # Right Column
                with Vertical(classes="config-column"):
                    # Theme Selection
                    with Horizontal(classes="config-row"):
                        yield Label("Theme:", classes="config-label")
                        yield Select(
                            ["dark", "light", "auto"],
                            value=self.config.ui.theme,
                            id="theme-select",
                            classes="config-input",
                        )

                    # Demotion Threshold
                    with Horizontal(classes="config-row"):
                        yield Label("Demotion:", classes="config-label")
                        yield Input(
                            value=str(self.config.ui.demotion_threshold),
                            placeholder="3",
                            id="demotion-input",
                            classes="config-input",
                        )

                    # Auto-save Sessions
                    with Horizontal(classes="config-row"):
                        yield Label("Auto-save:", classes="config-label")
                        yield Select(
                            [("Enabled", "Enabled"), ("Disabled", "Disabled")],
                            value=(
                                "Enabled" if self.config.ui.auto_save_interval > 0 else "Disabled"
                            ),
                            id="autosave-select",
                            classes="config-input",
                        )

            # Buttons at bottom
            with Horizontal(classes="config-row"):
                yield Button("Save", id="save-btn", variant="success")
                yield Button("Cancel", id="cancel-btn", variant="default")
                yield Button("Reset Defaults", id="reset-btn", variant="error")

    def action_cancel_config(self) -> None:
        """Cancel configuration and close screen."""
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._save_config()
        elif event.button.id == "cancel-btn":
            self.app.pop_screen()
        elif event.button.id == "reset-btn":
            self._reset_to_defaults()

    def _save_config(self):
        """Save configuration changes."""
        # Update config with form values
        log_path = self.query_one("#log-path-input", Input).value
        format_val = self.query_one("#format-select", Select).value
        theme_val = self.query_one("#theme-select", Select).value
        demotion_val = self.query_one("#demotion-input", Input).value
        autosave_val = self.query_one("#autosave-select", Select).value

        # Update config structure
        if "mtga" not in self.config:
            self.config["mtga"] = {}
        if "tracking" not in self.config:
            self.config["tracking"] = {}
        if "ui" not in self.config:
            self.config["ui"] = {}

        self.config["mtga"]["log_file_path"] = log_path
        self.config["tracking"]["default_format"] = format_val
        self.config["ui"]["theme"] = theme_val
        self.config["ui"]["demotion_threshold"] = int(demotion_val) if demotion_val.isdigit() else 3
        self.config["tracking"]["auto_save"] = autosave_val

        # Save to config manager
        try:
            config_manager.update_config(self.config)
            self.app.notify("Configuration saved!", severity="success")
        except Exception as e:
            self.app.notify(f"Error saving config: {e}", severity="error")

        self.app.pop_screen()

    def _reset_to_defaults(self):
        """Reset all settings to defaults."""
        # Update form fields
        self.query_one("#log-path-input", Input).value = ""
        self.query_one("#format-select", Select).value = "Standard"
        self.query_one("#theme-select", Select).value = "dark"
        self.query_one("#demotion-input", Input).value = "3"
        self.query_one("#autosave-select", Select).value = "Enabled"


class EventRunPanel(Static):
    """Widget displaying the current event run: win/loss pips, deck, prize."""

    def __init__(self, event: EventDefinition):
        super().__init__()
        self.event = event
        self.run: Optional[EventRun] = None

    def compose(self) -> ComposeResult:
        yield Label("Current Run", classes="section-title")
        yield Static(self._build_display(), id="run-display")

    def _build_display(self) -> Text:
        text = Text()
        if not self.run:
            text.append("No active run. Press [N] to start a new run.")
            return text

        text.append(f"Deck: {self.run.player_deck or 'Unknown'}\n")

        text.append("Wins:   ")
        for i in range(self.event.win_cap):
            if i < self.run.wins:
                text.append("[██]", style="bold gold1")
            else:
                text.append("[  ]", style="dim")
        text.append("\n")

        text.append("Losses: ")
        for i in range(self.event.loss_cap):
            if i < self.run.losses:
                text.append("[xx]", style="bold red")
            else:
                text.append("[  ]", style="dim")
        text.append("\n\n")

        text.append(f"Record: {self.run.wins}-{self.run.losses}\n")
        prize = self.run.prize(self.event)
        text.append(f"Prize so far: {prize.gems} gems, {prize.packs} packs\n")

        profit = self.run.net_profit_gems(self.event)
        if profit is not None:
            sign = "+" if profit >= 0 else ""
            text.append(f"Net profit: {sign}{profit} gems\n")

        milestone = self.run.highest_milestone(self.event)
        text.append(f"Milestone: {milestone.name if milestone else 'None yet'}\n")

        if self.run.status == EventRunStatus.ENDED:
            text.append("Run complete!\n", style="bold green")

        return text

    def update_run(self, run: Optional[EventRun]) -> None:
        self.run = run
        display = self.query_one("#run-display", Static)
        display.update(self._build_display())


class EventSessionPanel(Static):
    """Widget displaying current-session event totals."""

    def __init__(self, event: EventDefinition):
        super().__init__()
        self.event = event
        self.session = None

    def compose(self) -> ComposeResult:
        yield Label("Session Totals", classes="section-title")
        yield Static(self._format_display(), id="event-session-display")

    def _format_display(self) -> str:
        if not self.session:
            return "No active session"

        prize = self.session.total_prize(self.event)
        counts = self.session.milestone_counts(self.event)
        counts_str = ", ".join(f"{name}: {count}" for name, count in counts.items())

        return (
            f"Runs played: {len(self.session.completed_runs())}\n"
            f"Record: {self.session.total_wins()}-{self.session.total_losses()}\n"
            f"Prize: {prize.gems} gems, {prize.packs} packs\n"
            f"Milestones: {counts_str}"
        )

    def update_session(self, session) -> None:
        self.session = session
        display = self.query_one("#event-session-display", Static)
        display.update(self._format_display())


class EventOverallPanel(Static):
    """Widget displaying lifetime totals for this event plus a grand total
    across every event ever played."""

    def __init__(self, event: EventDefinition):
        super().__init__()
        self.event = event
        self.stats = None
        self.grand_total = None

    def compose(self) -> ComposeResult:
        yield Label("Overall Totals", classes="section-title")
        yield Static(self._format_display(), id="event-overall-display")

    def _format_display(self) -> str:
        if not self.stats:
            return "No history yet"

        counts_str = ", ".join(
            f"{name}: {count}" for name, count in self.stats["milestone_counts"].items()
        )
        grand = self.grand_total
        grand_str = f"{grand.gems} gems, {grand.packs} packs" if grand else "0 gems, 0 packs"

        return (
            f"Lifetime ({self.event.name}):\n"
            f"  Runs played: {self.stats['runs_played']}\n"
            f"  Record: {self.stats['wins']}-{self.stats['losses']}\n"
            f"  Prize: {self.stats['prize'].gems} gems, {self.stats['prize'].packs} packs\n"
            f"  Milestones: {counts_str}\n\n"
            f"Grand total (all events): {grand_str}"
        )

    def update_stats(self, stats, grand_total) -> None:
        self.stats = stats
        self.grand_total = grand_total
        display = self.query_one("#event-overall-display", Static)
        display.update(self._format_display())


class EventScreen(Screen):
    """Event mode screen: tracks run-based events like the Historic Pauper
    Challenge (win/loss caps and a fixed prize table) alongside the ranked
    ladder tracking on the main screen."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("n", "start_run", "New Run"),
        Binding("w", "record_win", "Win"),
        Binding("l", "record_loss", "Loss"),
        Binding("ctrl+e", "end_event_session", "End Session"),
    ]

    CSS = """
    EventScreen #event-left-panel {
        width: 1fr;
        border: solid $primary;
        margin-right: 1;
    }

    EventScreen #event-right-panel {
        width: 1fr;
        border: solid $primary;
    }

    EventScreen #event-run-widget {
        height: 1fr;
        border: solid $secondary;
        margin-bottom: 1;
    }

    EventScreen #event-inputs {
        height: 5;
        border: solid $secondary;
    }

    EventScreen #event-controls {
        height: 3;
        margin-bottom: 1;
    }

    EventScreen #event-session-widget {
        height: 1fr;
        border: solid $secondary;
        margin-bottom: 1;
    }

    EventScreen #event-overall-widget {
        height: 1fr;
        border: solid $secondary;
    }
    """

    def __init__(self):
        super().__init__()
        self.catalog: List[EventDefinition] = load_event_catalog(default_catalog_path())
        self.event: Optional[EventDefinition] = self.catalog[0] if self.catalog else None
        self.event_state_manager = EventStateManager()
        self.event_data_manager = EventDataManager()

    def compose(self) -> ComposeResult:
        yield Header()

        if not self.event:
            yield Static("No events configured. Add an entry to events.json.")
            yield Footer()
            return

        with Container():
            with Horizontal():
                with Vertical(id="event-left-panel"):
                    yield EventRunPanel(self.event).add_class("event-run-widget").add_class(
                        "run-panel"
                    )
                    with Horizontal(id="event-inputs"):
                        yield Input(placeholder="Opponent deck", id="opponent-deck-input")
                        yield Input(placeholder="Notes", id="notes-input")

                with Vertical(id="event-right-panel"):
                    yield EventSessionPanel(self.event).add_class("event-session-widget")
                    yield EventOverallPanel(self.event).add_class("event-overall-widget")

            with Horizontal(id="event-controls"):
                yield Button("New Run", id="start-run-btn", variant="primary")
                yield Button("Win", id="win-btn", variant="success")
                yield Button("Loss", id="loss-btn", variant="error")
                yield Button("End Session", id="end-event-session-btn", variant="warning")
                yield Button("Back", id="event-back-btn", variant="default")

        yield Footer()

    def on_mount(self) -> None:
        """Start a session for this event on mount and refresh displays."""
        if not self.event:
            return
        self.session = self.event_state_manager.start_session(self.event.event_id)
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Buttons mirror the keybindings, since a focused Input widget
        swallows single-letter keystrokes as text instead of triggering
        bindings."""
        if event.button.id == "start-run-btn":
            self.action_start_run()
        elif event.button.id == "win-btn":
            self.action_record_win()
        elif event.button.id == "loss-btn":
            self.action_record_loss()
        elif event.button.id == "end-event-session-btn":
            self.action_end_event_session()
        elif event.button.id == "event-back-btn":
            self.action_back()

    def action_back(self) -> None:
        """Return to the main ranked-tracking screen."""
        self.app.pop_screen()

    def action_start_run(self) -> None:
        """Start a new run within the current session."""
        if not self.event:
            return
        if self.session.current_run() is not None:
            self.notify("Current run hasn't ended yet!", severity="warning")
            return

        deck_input = self.query_one("#opponent-deck-input", Input)
        run = EventRun(
            run_id=f"run_{len(self.session.runs) + 1}",
            event_id=self.event.event_id,
            entry_currency=EntryCurrency.GEMS,
        )
        self.event_state_manager.start_run(run)
        deck_input.value = ""
        self._refresh()
        self.notify("New run started!", severity="success")

    def action_record_win(self) -> None:
        self._record_result(EventGameResult.WIN)

    def action_record_loss(self) -> None:
        self._record_result(EventGameResult.LOSS)

    def _record_result(self, result: EventGameResult) -> None:
        if not self.event:
            return
        if not self.session.current_run():
            self.notify("No active run! Press [N] to start one.", severity="warning")
            return

        opponent_deck = self.query_one("#opponent-deck-input", Input).value
        notes = self.query_one("#notes-input", Input).value

        game = EventGame(result=result, opponent_deck=opponent_deck or None, notes=notes)
        self.event_state_manager.add_game(game, self.event)

        self.query_one("#notes-input", Input).value = ""
        self._refresh()

    def action_end_event_session(self) -> None:
        """End the current event session."""
        if not self.event:
            return
        self.event_state_manager.end_session()
        self.session = self.event_state_manager.start_session(self.event.event_id)
        self._refresh()
        self.notify("Session ended!", severity="success")

    def _refresh(self) -> None:
        """Refresh all display panels."""
        if not self.event:
            return

        run_panel = self.query_one(EventRunPanel)
        run_panel.update_run(self.session.current_run())

        session_panel = self.query_one(EventSessionPanel)
        session_panel.update_session(self.session)

        overall_panel = self.query_one(EventOverallPanel)
        stats = self.event_data_manager.get_overall_stats(self.event)
        grand_total = self.event_data_manager.get_grand_total(self.catalog)
        overall_panel.update_stats(stats, grand_total)


class MTGASessionTrackerApp(App):
    """Main MTGA Session Tracker Application."""

    CSS = """
    .section-title {
        background: $primary;
        color: $text;
        padding: 0 1;
        margin-bottom: 1;
    }

    #left-panel {
        width: 1fr;
        border: solid $primary;
        margin-right: 1;
    }

    #right-panel {
        width: 1fr;
        border: solid $primary;
    }

    #game-widget {
        height: 8;
        border: solid $secondary;
        margin-bottom: 1;
    }

    #rank-widget {
        height: 1fr;
        border: solid $secondary;
        margin-bottom: 1;
    }

    #history-widget {
        height: 1fr;
        border: solid $secondary;
    }

    #stats-widget {
        height: 12;
        border: solid $secondary;
        margin-bottom: 1;
    }

    #controls-widget {
        height: 6;
        border: solid $secondary;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("s", "start_session", "Start Session"),
        Binding("e", "end_session", "End Session"),
        Binding("p", "pause_session", "Pause Session"),
        Binding("n", "add_note", "Add Note"),
        Binding("f1", "show_help", "Help"),
        Binding("ctrl+l", "show_logs", "Show Logs"),
        Binding("c", "show_settings", "Settings"),
        Binding("v", "show_event_mode", "Event Mode"),
    ]

    TITLE = "MTGA Mythic TUI Session Tracker"

    # Add help text for keybindings
    HELP_TEXT = """
🎯 MTGA Mythic TUI Session Tracker

⌨️  KEYBINDINGS:
  S           Start new session
  E           End current session
  P           Pause/resume session
  N           Add note to current game
  Ctrl+L      Show log viewer
  C           Open settings
  V           Event mode (Historic Pauper Challenge, etc.)
  F1          Show this help
  Ctrl+Q      Quit

📁 CONFIGURATION:
  • Settings screen: C
  • Config file: ~/.config/mtga-tracker/config.json
  • Command line: --help for options

🎮 USAGE:
  1. Configure MTGA log path in settings
  2. Start a session (S)
  3. Play ranked games - they'll be tracked automatically
  4. View progress in real-time
    """

    def __init__(self):
        super().__init__()
        self.state_manager = StateManager()
        self.config = config_manager.config
        self.log_parser = EnhancedLogParser()
        self.session: Optional[Session] = None

        # StateManager.state lazily loads (and falls back to a fresh AppState
        # on any error), so resuming a crashed/interrupted session is just a
        # matter of checking it here. Note: has_active_session() specifically
        # means "status == ACTIVE", so a paused session needs a plain
        # existence check to be resumed correctly too.
        if self.state_manager.state.active_session is not None:
            self.session = self.state_manager.state.active_session

    def compose(self) -> ComposeResult:
        """Create the main UI layout."""
        yield Header()

        with Container():
            with Horizontal():
                # Left Panel
                with Vertical(id="left-panel"):
                    yield CurrentGameWidget().add_class("game-widget")
                    yield RankProgressWidget(
                        self.session.current_rank if self.session else None
                    ).add_class("rank-widget")

                # Right Panel
                with Vertical(id="right-panel"):
                    yield SessionStatsWidget().add_class("stats-widget")
                    yield GameHistoryWidget().add_class("history-widget")
                    yield Static("Session Controls: [S]tart [E]nd [P]ause", id="controls-widget")

        yield Footer()

    def _create_controls_widget(self) -> Container:
        """Create session control buttons."""
        controls = Container(id="controls-widget")
        controls._add_children(
            [
                Label("Session Controls", classes="section-title"),
                Horizontal(
                    Button("Start", id="start-btn", variant="success"),
                    Button("Pause", id="pause-btn", variant="warning"),
                    Button("End", id="end-btn", variant="error"),
                ),
                Horizontal(
                    Button("Add Note", id="note-btn", variant="primary"),
                    Button("View Logs", id="logs-btn", variant="default"),
                ),
            ]
        )
        return controls

    def on_mount(self):
        """Initialize the application."""
        self._update_displays()
        self._start_log_monitoring()

    def action_start_session(self):
        """Start a new tracking session."""
        if self.state_manager.state.active_session is not None:
            self.notify("Session already active!", severity="warning")
            return

        current_rank = self._get_current_rank_from_logs()
        format_type = self._resolve_format_type(self.config.ui.default_format)
        self.session = self.state_manager.start_session(format_type, current_rank)

        self._update_displays()
        self.notify("Session started!", severity="success")

    def action_end_session(self):
        """End the current session."""
        if self.state_manager.state.active_session is None:
            self.notify("No active session!", severity="warning")
            return

        self.state_manager.end_session()
        self.session = None

        self._update_displays()
        self.notify("Session ended!", severity="success")

    def action_pause_session(self):
        """Pause or resume the current session."""
        session = self.state_manager.state.active_session
        if session is None:
            self.notify("No active session!", severity="warning")
            return

        if session.status == SessionStatus.PAUSED:
            self.state_manager.resume_session()
            self.notify("Session resumed!", severity="success")
        else:
            self.state_manager.pause_session()
            self.notify("Session paused!", severity="success")

    def action_add_note(self):
        """Add a note to the current game."""
        # TODO: Implement note input (needs a text input modal)
        self.notify("Add note - TODO: Implement note input", severity="info")

    def action_show_logs(self):
        """Show the log viewer."""
        # TODO: Launch log viewer as modal or separate screen
        self.notify("Log viewer - TODO: Implement modal", severity="info")

    def action_show_settings(self):
        """Show configuration screen."""
        config_screen = ConfigurationScreen(self.config)
        self.push_screen(config_screen)

    def action_show_event_mode(self):
        """Show the event-mode tracking screen."""
        self.push_screen(EventScreen())

    def action_show_help(self):
        """Show help information."""
        from textual.widgets import Markdown

        class HelpScreen(ModalScreen):
            def compose(self) -> ComposeResult:
                with Container(id="help-dialog"):
                    yield Markdown(self.app.HELP_TEXT)
                    yield Button("Close", id="close-btn")

            def on_button_pressed(self, event: Button.Pressed) -> None:
                self.app.pop_screen()

        help_screen = HelpScreen()
        self.push_screen(help_screen)

    def _get_current_rank_from_logs(self) -> Rank:
        """Extract current rank from latest log data."""
        # TODO: Parse most recent rank from logs
        return Rank(tier="Platinum", division=4, pips=3)  # Placeholder

    @staticmethod
    def _resolve_format_type(format_name: str) -> FormatType:
        """Map a user-facing MTGA format name (Standard/Alchemy/Historic/
        Explorer/Limited/...) to the internal Constructed-vs-Limited
        category used for session/game stats."""
        if format_name and format_name.lower() in ("limited", "draft", "sealed"):
            return FormatType.LIMITED
        return FormatType.CONSTRUCTED

    def _update_displays(self):
        """Update all display widgets."""
        stats_widget = self.query_one(SessionStatsWidget)
        stats_widget.update_session(self.session)

        rank_widget = self.query_one(RankProgressWidget)
        rank_widget.update_rank(self.session.current_rank if self.session else None)

    def _start_log_monitoring(self):
        """Start monitoring MTGA log file for real-time updates."""
        # TODO: Implement real-time log file monitoring
        # This would watch the log file and parse new events
        pass


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="MTGA Mythic TUI Session Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Configuration:
  Settings can be configured via:
  1. Command line options (highest priority)
  2. Configuration screen (Ctrl+,)
  3. Config file (~/.config/mtga-tracker/config.json)
  4. Environment variables
  5. Defaults (lowest priority)

Examples:
  %(prog)s                          # Run with default settings
  %(prog)s --log-path ~/Player.log  # Specify log file
  %(prog)s --format Historic        # Set default format
  %(prog)s --theme light            # Use light theme""",
    )

    parser.add_argument("--log-path", "-l", help="Path to MTGA Player.log file")
    parser.add_argument(
        "--format",
        "-f",
        choices=["Standard", "Alchemy", "Historic", "Explorer", "Limited"],
        help="Default game format for sessions",
    )
    parser.add_argument("--theme", "-t", choices=["dark", "light", "auto"], help="UI theme")
    parser.add_argument(
        "--demotion-threshold",
        "-d",
        type=int,
        help="Number of losses needed for demotion (default: 3)",
    )
    parser.add_argument(
        "--no-auto-save", action="store_true", help="Disable automatic session saving"
    )
    parser.add_argument("--config-dir", help="Custom configuration directory")
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode with verbose logging"
    )
    parser.add_argument("--version", action="version", version="MTGA Mythic TUI v1.0.0")

    return parser.parse_args()


def apply_cli_config(args, config):
    """Apply command line arguments to configuration.

    `config` is the pydantic Config instance (config_manager.config), not a
    dict, so overrides go through normal attribute access.
    """
    if args.log_path:
        config.mtga.log_file_path = args.log_path
    if args.format:
        config.ui.default_format = args.format
    if args.theme:
        config.ui.theme = args.theme
    if args.demotion_threshold:
        config.ui.demotion_threshold = args.demotion_threshold
    if args.no_auto_save:
        config.ui.auto_save_interval = 0

    return config


def main():
    """Run the main application."""
    args = parse_arguments()

    # Override config directory if specified
    if args.config_dir:
        import os

        os.environ["MTGA_TRACKER_CONFIG_DIR"] = args.config_dir

    try:
        app = MTGASessionTrackerApp()

        # Apply CLI overrides
        app.config = apply_cli_config(args, app.config)

        # Enable debug mode if requested
        if args.debug:
            app.notify("Debug mode enabled", severity="info")

        app.run()
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Error starting application: {e}")
        if args.debug:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
