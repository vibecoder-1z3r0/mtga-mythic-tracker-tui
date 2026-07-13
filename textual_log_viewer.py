#!/usr/bin/env python3
"""
Textual-based MTGA Log Viewer - Professional TUI interface
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header,
    Footer,
    DataTable,
    Input,
    Button,
    Label,
    Pretty,
)
from textual.containers import ScrollableContainer
from textual.reactive import reactive
from textual.binding import Binding

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from src.config.settings import config_manager
except ImportError:
    config_manager = None


class LogEvent:
    """Represents a parsed MTGA log event."""

    def __init__(
        self,
        line_num: int,
        timestamp: datetime,
        event_type: str,
        content: str,
        raw_data: str,
        is_rank_event: bool = False,
    ):
        self.line_num = line_num
        self.timestamp = timestamp
        self.event_type = event_type
        self.content = content
        self.raw_data = raw_data
        self.is_rank_event = is_rank_event


class MTGALogParser:
    """Enhanced MTGA log parser with real log insights."""

    def __init__(self):
        self.events: List[LogEvent] = []
        self.stats = {
            "total_lines": 0,
            "parsed_events": 0,
            "skipped_lines": 0,
            "event_types": {},
            "errors": [],
        }

    def parse_file(self, log_file: Path) -> List[LogEvent]:
        """Parse MTGA log file with enhanced understanding."""
        events = []
        self.stats["total_lines"] = 0
        self.stats["parsed_events"] = 0
        self.stats["skipped_lines"] = 0
        self.stats["event_types"] = {}
        self.stats["errors"] = []

        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    self.stats["total_lines"] += 1
                    line = line.strip()

                    if not line:
                        self.stats["skipped_lines"] += 1
                        continue

                    try:
                        event = self._parse_line(line, self.stats["total_lines"])
                        if event:
                            events.append(event)
                            self.stats["parsed_events"] += 1
                            # Track event types
                            event_type = event.event_type
                            self.stats["event_types"][event_type] = (
                                self.stats["event_types"].get(event_type, 0) + 1
                            )
                        else:
                            self.stats["skipped_lines"] += 1
                    except Exception as e:
                        error_msg = f"Line {self.stats['total_lines']}: {str(e)}"
                        self.stats["errors"].append(error_msg)
                        self.stats["skipped_lines"] += 1
                        # Continue parsing instead of failing completely
                        continue

        except Exception as e:
            error_msg = f"Failed to read log file: {str(e)}"
            self.stats["errors"].append(error_msg)
            raise

        self.events = events
        return events

    def _parse_line(self, line: str, line_num: int) -> Optional[LogEvent]:
        """Parse a single log line with enhanced logic."""
        timestamp = datetime.now()
        event_type = "Unknown"
        content = ""
        is_rank_event = False

        # Parse JSON lines (most MTGA events)
        if line.startswith("{"):
            try:
                data = json.loads(line)

                # Extract timestamp if available
                if "timestamp" in data:
                    try:
                        ts_value = int(data["timestamp"])

                        # Handle different timestamp formats
                        if ts_value > 635000000000000000:  # .NET ticks (started 2001-01-01)
                            # .NET ticks: 100-nanosecond intervals since January 1, 0001 UTC
                            # Convert to Unix epoch (ticks since 1970-01-01)
                            unix_epoch_ticks = 621355968000000000
                            unix_ticks = ts_value - unix_epoch_ticks
                            timestamp = datetime.fromtimestamp(unix_ticks / 10000000)
                        else:
                            # Unix milliseconds
                            timestamp = datetime.fromtimestamp(ts_value / 1000)
                    except (ValueError, OSError):
                        pass

                # Determine event type and extract meaningful content
                event_type, content, is_rank_event = self._analyze_json_event(data)

            except json.JSONDecodeError:
                event_type = "InvalidJSON"
                content = line[:100] + "..." if len(line) > 100 else line

        # Parse Unity logger lines
        elif "[UnityCrossThreadLogger]" in line:
            event_type, content = self._parse_unity_log(line)
            # Check if it's a rank-related Unity event
            if any(term in line.lower() for term in ["rank", "season", "tier"]):
                is_rank_event = True

        # Parse other significant lines
        elif any(
            keyword in line.lower()
            for keyword in [
                "rank",
                "match",
                "game",
                "platinum",
                "gold",
                "mythic",
                "diamond",
                "win",
                "loss",
                "victory",
                "defeat",
            ]
        ):
            event_type = "Other"
            content = line[:200] + "..." if len(line) > 200 else line
            is_rank_event = "rank" in line.lower()
            # Check for match results in non-JSON lines
            if any(term in line.lower() for term in ["victory", "win", "won"]):
                event_type = "LineResult_Win"
                content = f"🏆 {content}"
            elif any(term in line.lower() for term in ["defeat", "loss", "lost"]):
                event_type = "LineResult_Loss"
                content = f"💀 {content}"

        else:
            # Skip uninteresting lines
            return None

        return LogEvent(
            line_num=line_num,
            timestamp=timestamp,
            event_type=event_type,
            content=content,
            raw_data=line,
            is_rank_event=is_rank_event,
        )

    def _analyze_json_event(self, data: Dict[str, Any]) -> Tuple[str, str, bool]:
        """Analyze JSON event with enhanced understanding."""
        event_type = "Unknown"
        content = ""
        is_rank_event = False

        # GRE (Game Rules Engine) Events
        if "greToClientEvent" in data:
            gre_messages = data["greToClientEvent"].get("greToClientMessages", [])
            if gre_messages:
                first_msg = gre_messages[0]
                msg_type = first_msg.get("type", "GREEvent")
                event_type = f"GRE_{msg_type}"

                if msg_type == "GREMessageType_GameStateMessage":
                    content = self._extract_game_state_info(first_msg)
                    # Check for game end states
                    game_state = first_msg.get("gameStateMessage", {})
                    game_info = game_state.get("gameInfo", {})
                    if game_info.get("stage") == "GameStage_GameOver":
                        result = game_info.get("results", [])
                        if result:
                            content = f"🎯 GAME OVER: {content}"
                            event_type = "GameResult"
                elif msg_type == "GREMessageType_DieRollResultsResp":
                    content = self._extract_die_roll_info(first_msg)
                else:
                    content = f"GRE Message: {msg_type}"

        # Direct rank information (CRITICAL!)
        elif "constructedClass" in data:
            event_type = "RankInfo_Constructed"
            tier = data.get("constructedClass", "Unknown")
            level = data.get("constructedLevel", "?")
            step = data.get("constructedStep", "?")
            wins = data.get("constructedMatchesWon", "?")
            losses = data.get("constructedMatchesLost", "?")
            content = f"🎯 {tier} Tier {level} ({step}/6 pips) | {wins}W-{losses}L"
            is_rank_event = True

        elif "limitedClass" in data:
            event_type = "RankInfo_Limited"
            tier = data.get("limitedClass", "Unknown")
            level = data.get("limitedLevel", "?")
            content = f"🎯 Limited: {tier} Tier {level}"
            is_rank_event = True

        # Match completion events
        elif "matchCompleted" in json.dumps(data).lower() or "finalMatchResult" in data:
            event_type = "MatchResult"
            # Look for win/loss indicators
            data_str = json.dumps(data).lower()
            if "win" in data_str and ("you" in data_str or "player" in data_str):
                content = "🏆 MATCH WON"
                event_type = "MatchResult_Win"
            elif "loss" in data_str or "lose" in data_str:
                content = "💀 MATCH LOST"
                event_type = "MatchResult_Loss"
            else:
                content = "Match completed"

        # Match game room events
        elif "matchGameRoomStateChangedEvent" in data:
            event_type = "MatchRoomEvent"
            room_info = data["matchGameRoomStateChangedEvent"]
            game_room_info = room_info.get("gameRoomInfo", {})
            state_type = game_room_info.get("stateType", "")

            # Check for match results in room state
            if "completed" in state_type.lower():
                final_results = game_room_info.get("finalMatchResult", {})
                if final_results:
                    content = "🎯 Match completed with results"
                    event_type = "MatchResult_Completed"
                else:
                    content = f"Match completed ({state_type})"
            else:
                content = f"Match room: {state_type or 'state change'}"

        # Transaction events
        elif "transactionId" in data:
            event_type = "Transaction"
            tx_id = data.get("transactionId", "")[:8]
            content = f"Transaction: {tx_id}..."

        # Inventory/Collection updates
        elif "InventoryInfo" in data:
            event_type = "InventoryUpdate"
            inv = data["InventoryInfo"]
            gems = inv.get("Gems", "?")
            gold = inv.get("Gold", "?")
            wildcards = f"R:{inv.get('WildCardRares', 0)} M:{inv.get('WildCardMythics', 0)}"
            content = f"💰 Inventory: {gems} gems, {gold} gold, WCs: {wildcards}"

        # Player Decks Collection
        elif "Decks" in data:
            event_type = "DeckCollection"
            decks = data["Decks"]
            deck_count = (
                len(decks)
                if isinstance(decks, dict)
                else len(decks) if isinstance(decks, list) else 0
            )
            content = f"🃏 Deck Collection: {deck_count} decks loaded"

        # Match History
        elif "MatchesV3" in data:
            event_type = "MatchHistory"
            matches = data["MatchesV3"]
            match_count = len(matches) if isinstance(matches, list) else 0
            content = f"⚔️ Match History: {match_count} recent matches"

        # Quest System
        elif "quests" in data:
            event_type = "QuestUpdate"
            quests = data["quests"]
            if isinstance(quests, list):
                active_quests = len([q for q in quests if not q.get("isComplete", True)])
                completed_quests = len([q for q in quests if q.get("isComplete", False)])
                content = f"🎯 Quests: {active_quests} active, {completed_quests} completed"
            else:
                content = "🎯 Quest system update"

        # Periodic Rewards (Daily/Weekly)
        elif "ClientPeriodicRewards" in data:
            event_type = "PeriodicRewards"
            rewards = data["ClientPeriodicRewards"]
            daily_info = rewards.get("_dailyRewardChestDescriptions", [])
            weekly_info = rewards.get("_weeklyRewardChestDescriptions", [])
            content = f"🎁 Rewards: {len(daily_info)} daily, {len(weekly_info)} weekly chests"

        # Progress Tracking
        elif "NodeStates" in data:
            event_type = "ProgressNodes"
            nodes = data["NodeStates"]
            node_count = len(nodes) if isinstance(nodes, dict) else 0
            content = f"🗺️ Progress Nodes: {node_count} tracked"

        elif "MilestoneStates" in data:
            event_type = "MilestoneProgress"
            milestones = data["MilestoneStates"]
            milestone_count = len(milestones) if isinstance(milestones, dict) else 0
            content = f"🏆 Milestones: {milestone_count} tracked"

        # Check for rank-related keywords in any JSON
        json_str = json.dumps(data).lower()
        if not is_rank_event and any(
            term in json_str
            for term in [
                "rank",
                "tier",
                "platinum",
                "gold",
                "mythic",
                "diamond",
                "bronze",
                "silver",
            ]
        ):
            is_rank_event = True
            event_type += "_[RANK?]"

        # Default fallback for unhandled JSON events
        if event_type == "Unknown" and content == "":
            # Try to identify by top-level keys
            top_keys = list(data.keys())[:3]
            event_type = "JSON_Event"
            content = f"Event with keys: {', '.join(top_keys)}"

        return event_type, content, is_rank_event

    def get_parsing_summary(self) -> str:
        """Get comprehensive parsing statistics."""
        stats = self.stats
        total = stats["total_lines"]
        parsed = stats["parsed_events"]
        skipped = stats["skipped_lines"]
        parse_rate = (parsed / total * 100) if total > 0 else 0

        errors = stats.get("errors", [])
        error_count = len(errors)
        error_indicator = f" | ⚠️ {error_count} errors" if error_count > 0 else ""

        summary = f"""📊 PARSING STATISTICS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total lines processed: {total:,}
Parsed events: {parsed:,} ({parse_rate:.1f}%)
Skipped lines: {skipped:,}{error_indicator}

🏷️  EVENT TYPE BREAKDOWN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

        # Sort event types by count
        sorted_types = sorted(stats["event_types"].items(), key=lambda x: x[1], reverse=True)

        for event_type, count in sorted_types:
            percentage = (count / parsed * 100) if parsed > 0 else 0
            summary += f"\n{event_type:<25} {count:>6,} ({percentage:>5.1f}%)"

        # Add error details if present
        if errors:
            summary += f"\n\n❌ PARSING ERRORS ({error_count})"
            summary += "\n" + "━" * 40
            for i, error in enumerate(errors[:10]):  # Show first 10 errors
                summary += f"\n{i+1:2d}. {error}"
            if error_count > 10:
                summary += f"\n... and {error_count - 10} more errors"

        return summary

    def _extract_game_state_info(self, message: Dict[str, Any]) -> str:
        """Extract meaningful info from game state messages."""
        game_state = message.get("gameStateMessage", {})

        # Game info
        game_info = game_state.get("gameInfo", {})
        if game_info:
            stage = game_info.get("stage", "")
            match_state = game_info.get("matchState", "")
            info_parts = [f"Stage: {stage}", f"Match: {match_state}"]
        else:
            info_parts = ["Game state update"]

        # Player life totals
        players = game_state.get("players", [])
        if players:
            life_info = []
            for player in players[:2]:
                seat = player.get("systemSeatNumber", "?")
                life = player.get("lifeTotal", "?")
                life_info.append(f"P{seat}:{life}♥")
            if life_info:
                info_parts.append(" vs ".join(life_info))

        return " | ".join(info_parts)

    def _extract_die_roll_info(self, message: Dict[str, Any]) -> str:
        """Extract die roll results."""
        die_results = message.get("dieRollResultsResp", {}).get("playerDieRolls", [])
        if die_results:
            rolls = [str(roll.get("rollValue", "?")) for roll in die_results]
            return f"🎲 Die roll: {' vs '.join(rolls)}"
        return "🎲 Die roll results"

    def _parse_unity_log(self, line: str) -> Tuple[str, str]:
        """Parse Unity logger line."""
        if "==>" in line:
            # Extract event name
            import re

            event_match = re.search(r"==> (\w+)", line)
            if event_match:
                event_name = event_match.group(1)
                event_type = f"Unity_{event_name}"

                # Special handling for rank events
                if "Rank" in event_name:
                    return event_type, f"🎯 Unity rank event: {event_name}"
                else:
                    return event_type, f"Unity: {event_name}"

        return "Unity_Log", line[:100] + "..." if len(line) > 100 else line


class LogViewerApp(App):
    """Textual-based MTGA Log Viewer Application."""

    CSS = """
    .rank-event {
        background: $secondary-background;
        color: $warning;
    }

    .gre-event {
        color: $accent;
    }

    .unity-event {
        color: $primary;
    }

    #main-container {
        height: 1fr;
    }

    #filter-container {
        height: 3;
        margin-bottom: 1;
    }

    #content-container {
        height: 1fr;
    }

    #detail-view {
        width: 50%;
        border: solid $primary;
    }

    #events-container {
        width: 50%;
    }

    #events-table {
        height: 1fr;
    }

    #detail-content {
        height: auto;
    }

    #filter-input {
        width: 50%;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+f", "focus_filter", "Filter"),
        Binding("ctrl+r", "filter_rank", "Rank Events"),
        Binding("ctrl+c", "clear_filter", "Clear Filter"),
        Binding("f1", "help", "Help"),
    ]

    TITLE = "MTGA Mythic TUI Session Tracker - Log Viewer"

    current_filter = reactive("")

    def __init__(self, log_file: Path):
        super().__init__()
        self.log_file = log_file
        self.parser = MTGALogParser()
        self.all_events: List[LogEvent] = []
        self.filtered_events: List[LogEvent] = []

    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        yield Header()

        with Container(id="main-container"):
            with Horizontal(id="filter-container"):
                yield Label("Filter:", id="filter-label")
                yield Input(placeholder="Filter events...", id="filter-input")
                yield Button("Rank Events", id="rank-button", variant="primary")
                yield Button("Clear", id="clear-button")

            with Horizontal(id="content-container"):
                with Vertical(id="events-container"):
                    yield Label(f"📁 {self.log_file}", id="file-label")
                    yield DataTable(id="events-table")

                with Vertical(id="detail-view"):
                    yield Label("Event Details", id="detail-title")
                    with ScrollableContainer():
                        yield Pretty("Select an event to view details", id="detail-content")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize the app after mounting."""
        self.load_log_file()
        self.setup_table()
        self.populate_table()

    def load_log_file(self) -> None:
        """Load and parse the log file."""
        self.show_loading_message()

        try:
            self.all_events = self.parser.parse_file(self.log_file)
            self.filtered_events = self.all_events.copy()

            rank_events = len([e for e in self.all_events if e.is_rank_event])
            error_count = len(self.parser.stats.get("errors", []))

            self.show_loaded_message(len(self.all_events), rank_events, error_count)

        except Exception as e:
            error_msg = f"Fatal parsing error: {str(e)}"
            if hasattr(self.parser, "stats") and self.parser.stats.get("errors"):
                error_msg += f" (Plus {len(self.parser.stats['errors'])} line-level errors)"
            self.show_error_message(error_msg)

    def show_loading_message(self) -> None:
        """Show loading message."""
        file_label = self.query_one("#file-label", Label)
        file_label.update(f"📖 Loading {self.log_file}...")

    def show_loaded_message(
        self, total_events: int, rank_events: int, error_count: int = 0
    ) -> None:
        """Show loaded message with detailed stats."""
        file_label = self.query_one("#file-label", Label)
        stats = self.parser.stats

        # Get top 3 event types
        top_types = sorted(stats["event_types"].items(), key=lambda x: x[1], reverse=True)[:3]
        type_summary = ", ".join([f"{t}({c})" for t, c in top_types])

        # Add error indicator if needed
        error_indicator = f" | ⚠️ {error_count} errors" if error_count > 0 else ""

        file_label.update(
            f"📁 {self.log_file.name} | {stats['total_lines']} lines → "
            f"{total_events} events | {rank_events} rank{error_indicator} | "
            f"Top: {type_summary}"
        )

    def show_error_message(self, error: str) -> None:
        """Show error message."""
        file_label = self.query_one("#file-label", Label)
        file_label.update(f"❌ Error loading {self.log_file}: {error}")

    def setup_table(self) -> None:
        """Set up the events table."""
        table = self.query_one("#events-table", DataTable)
        table.add_column("Line", width=6)
        table.add_column("Time", width=8)
        table.add_column("Type", width=20)
        table.add_column("Content", width=50)
        table.cursor_type = "row"

    def populate_table(self) -> None:
        """Populate the table with events."""
        table = self.query_one("#events-table", DataTable)
        table.clear()

        # Add stats row first
        table.add_row("📊", "STATS", "Parsing Statistics & Event Type Breakdown")

        for event in self.filtered_events:
            time_str = event.timestamp.strftime("%H:%M:%S")

            # Add visual indicators for event types
            event_type_display = event.event_type
            if event.is_rank_event:
                event_type_display = f"🎯 {event.event_type}"
            elif "GRE_" in event.event_type:
                event_type_display = f"🔮 {event.event_type}"
            elif "Unity_" in event.event_type:
                event_type_display = f"🔧 {event.event_type}"
            elif "DeckCollection" in event.event_type:
                event_type_display = f"🃏 {event.event_type}"
            elif "MatchHistory" in event.event_type:
                event_type_display = f"⚔️ {event.event_type}"
            elif "QuestUpdate" in event.event_type:
                event_type_display = f"🎯 {event.event_type}"
            elif "Rewards" in event.event_type:
                event_type_display = f"🎁 {event.event_type}"
            elif "Progress" in event.event_type or "Milestone" in event.event_type:
                event_type_display = f"🏆 {event.event_type}"

            table.add_row(str(event.line_num), time_str, event_type_display, event.content)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle table row selection (Enter/click)."""
        self._update_details_for_row(event.cursor_row)

    def on_key(self, event) -> None:
        """Handle key presses for real-time details update."""
        # Check if we're in the table and arrow keys were pressed
        if event.key in ["up", "down", "page_up", "page_down", "home", "end"]:
            # Small delay to ensure cursor has moved, then update details
            self.call_after_refresh(self._update_current_details)

    def _update_current_details(self) -> None:
        """Update details based on current cursor position."""
        table = self.query_one("#events-table", DataTable)
        if table.cursor_row is not None:
            self._update_details_for_row(table.cursor_row)

    def _update_details_for_row(self, row_index: int) -> None:
        """Update detail panel for the given row index."""
        # Row 0 is the stats row, rows 1+ are actual events
        if row_index == 0:
            # Show parsing statistics
            detail_content = self.query_one("#detail-content", Pretty)
            detail_content.update(self.parser.get_parsing_summary())
        elif row_index - 1 < len(self.filtered_events):
            # Show event details (subtract 1 to account for stats row)
            selected_event = self.filtered_events[row_index - 1]
            self.show_event_details(selected_event)

    def show_event_details(self, event: LogEvent) -> None:
        """Show detailed view of selected event."""
        detail_content = self.query_one("#detail-content", Pretty)

        details = {
            "Line": event.line_num,
            "Timestamp": event.timestamp.isoformat(),
            "Type": event.event_type,
            "Content": event.content,
            "Is Rank Event": event.is_rank_event,
            "Raw Data": event.raw_data,
        }

        detail_content.update(details)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle filter input changes."""
        if event.input.id == "filter-input":
            self.apply_filter(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "rank-button":
            self.action_filter_rank()
        elif event.button.id == "clear-button":
            self.action_clear_filter()

    def apply_filter(self, filter_term: str) -> None:
        """Apply filter to events."""
        self.current_filter = filter_term.lower()

        if not filter_term:
            self.filtered_events = self.all_events.copy()
        else:
            self.filtered_events = []
            for event in self.all_events:
                search_text = f"{event.event_type} {event.content} {event.raw_data}".lower()
                if filter_term.lower() in search_text:
                    self.filtered_events.append(event)

        self.populate_table()
        self.update_file_label()

    def update_file_label(self) -> None:
        """Update file label with current filter status."""
        file_label = self.query_one("#file-label", Label)
        base_text = f"📁 {self.log_file} | {len(self.all_events)} total events"

        if self.current_filter:
            base_text += f" | Filtered: {len(self.filtered_events)} events"
            rank_filtered = len([e for e in self.filtered_events if e.is_rank_event])
            base_text += f" | {rank_filtered} rank events"
        else:
            rank_total = len([e for e in self.all_events if e.is_rank_event])
            base_text += f" | {rank_total} rank events"

        file_label.update(base_text)

    def action_focus_filter(self) -> None:
        """Focus the filter input."""
        self.query_one("#filter-input", Input).focus()

    def action_filter_rank(self) -> None:
        """Filter for rank events only."""
        filter_input = self.query_one("#filter-input", Input)
        filter_input.value = "rank"
        self.apply_filter("rank")

    def action_clear_filter(self) -> None:
        """Clear the current filter."""
        filter_input = self.query_one("#filter-input", Input)
        filter_input.value = ""
        self.apply_filter("")

    def action_help(self) -> None:
        """Show help information."""
        # Could implement a help modal here
        pass


def get_log_file_path() -> Path:
    """Get MTGA log file path from various sources."""
    # Try command-line argument first
    if len(sys.argv) > 1:
        return Path(sys.argv[1])

    # Try configuration system
    if config_manager:
        try:
            config = config_manager.config
            if config.mtga.log_file_path:
                return Path(config.mtga.log_file_path)

            # Try auto-detection
            common_paths = config_manager.get_mtga_log_paths()
            if common_paths:
                return Path(common_paths[0])
        except Exception:
            pass

    # Fall back to test logs
    return Path("mtga-test-logs/Player.log")


def main():
    """Main entry point."""
    log_file = get_log_file_path()

    if not log_file.exists():
        print(f"❌ Log file not found: {log_file}")
        print("\n💡 Options:")
        print("1. python3 textual_log_viewer.py /path/to/MTGArena/logs/Player.log")
        print("2. Configure log path: python3 configure_log_path.py")
        print("3. Place test logs in mtga-test-logs/Player.log")
        sys.exit(1)

    app = LogViewerApp(log_file)
    app.run()


if __name__ == "__main__":
    main()
