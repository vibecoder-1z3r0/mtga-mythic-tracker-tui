#!/usr/bin/env python3
"""
MTGA Mythic TUI Session Tracker - Main Application
Professional terminal interface for tracking MTG Arena ranked sessions.
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, List

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
from textual.screen import ModalScreen
from textual.binding import Binding

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from src.config.settings import config_manager
    from src.core.state_manager import StateManager
    from src.models.session import Session  # Changed from SessionTracker
    from src.models.rank import Rank
    from src.models.game import Game, GameResult
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

    def update_rank(self, new_rank: Rank):
        """Update rank display."""
        self.current_rank = new_rank
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
            details = f"{game.play_draw} vs {game.opponent_deck or 'Unknown'}"
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

        stats = self.session.get_statistics()
        duration = self.session.get_session_duration()

        return f"""Record: {stats['wins']}W - {stats['losses']}L
Win Rate: {stats['win_rate']:.1f}%
Duration: {duration}
Games/Hour: {stats.get('games_per_hour', 0):.1f}

Starting Rank: {self.session.starting_rank}
Current Rank: {self.session.current_rank}"""

    def update_session(self, session: Session):
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

        # Load state - create simple state object for now
        try:
            self.app_state = self.state_manager.load_state()
            if hasattr(self.app_state, "current_session") and self.app_state.current_session:
                self.session = self.app_state.current_session
        except Exception:
            # Create simple state object if loading fails
            from types import SimpleNamespace

            self.app_state = SimpleNamespace(current_session=None)

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
        if self.session and self.session.end_time is None:
            self.notify("Session already active!", severity="warning")
            return

        # Create new session
        current_rank = self._get_current_rank_from_logs()
        self.session = Session(
            format_type="Standard",  # TODO: Make configurable
            starting_rank=current_rank,
            start_time=datetime.now(),
        )

        self.app_state.current_session = self.session
        try:
            self.state_manager.save_state(self.app_state)
        except Exception:
            pass  # Ignore save errors for now

        self._update_displays()
        self.notify("Session started!", severity="success")

    def action_end_session(self):
        """End the current session."""
        if not self.session or self.session.end_time is not None:
            self.notify("No active session!", severity="warning")
            return

        self.session.end_time = datetime.now()

        # Save session data
        # TODO: Implement session persistence

        self.app_state.current_session = None
        try:
            self.state_manager.save_state(self.app_state)
        except Exception:
            pass  # Ignore save errors for now

        self._update_displays()
        self.notify("Session ended!", severity="success")

    def action_show_logs(self):
        """Show the log viewer."""
        # TODO: Launch log viewer as modal or separate screen
        self.notify("Log viewer - TODO: Implement modal", severity="info")

    def action_show_settings(self):
        """Show configuration screen."""
        config_screen = ConfigurationScreen(self.config)
        self.push_screen(config_screen)

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

    def _update_displays(self):
        """Update all display widgets."""
        if self.session:
            # Update stats widget
            stats_widget = self.query_one(SessionStatsWidget)
            stats_widget.update_session(self.session)

            # Update rank widget
            rank_widget = self.query_one(RankProgressWidget)
            rank_widget.update_rank(self.session.current_rank)

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
    """Apply command line arguments to configuration."""
    if args.log_path:
        config.setdefault("mtga", {})["log_file_path"] = args.log_path
    if args.format:
        config.setdefault("tracking", {})["default_format"] = args.format
    if args.theme:
        config.setdefault("ui", {})["theme"] = args.theme
    if args.demotion_threshold:
        config.setdefault("ui", {})["demotion_threshold"] = args.demotion_threshold
    if args.no_auto_save:
        config.setdefault("tracking", {})["auto_save"] = False
    if args.debug:
        config.setdefault("debug", {})["enabled"] = True

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
