#!/usr/bin/env python3
"""
Simple MTGA Log Viewer - Terminal-based log browser
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class MTGALogViewer:
    """Simple terminal-based MTGA log viewer."""

    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.current_line = 0
        self.filtered_lines = []
        self.all_events = []
        self.filter_term = ""

    def load_logs(self) -> None:
        """Load and parse MTGA log file."""
        print("📖 Loading MTGA logs...")

        if not self.log_file.exists():
            print(f"❌ Log file not found: {self.log_file}")
            return

        events = []
        line_num = 0

        try:
            with open(self.log_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_num += 1
                    line = line.strip()

                    if not line:
                        continue

                    # Try to parse JSON lines
                    if line.startswith("{"):
                        try:
                            data = json.loads(line)
                            event = self.parse_event(data, line_num)
                            if event:
                                events.append(event)
                        except json.JSONDecodeError:
                            # Keep as raw text
                            events.append(
                                {
                                    "line": line_num,
                                    "type": "Raw",
                                    "timestamp": datetime.now(),
                                    "content": (line[:200] + "..." if len(line) > 200 else line),
                                    "raw_data": line,
                                }
                            )

                    # Parse Unity logger lines
                    elif "[UnityCrossThreadLogger]" in line:
                        event = self.parse_unity_log(line, line_num)
                        if event:
                            events.append(event)

                    # Other log lines
                    elif any(
                        keyword in line.lower() for keyword in ["rank", "match", "game", "event"]
                    ):
                        events.append(
                            {
                                "line": line_num,
                                "type": "Other",
                                "timestamp": datetime.now(),
                                "content": (line[:200] + "..." if len(line) > 200 else line),
                                "raw_data": line,
                            }
                        )

        except Exception as e:
            print(f"❌ Error loading logs: {e}")
            return

        self.all_events = events
        self.filtered_lines = events.copy()
        print(f"✅ Loaded {len(events)} events from {line_num} lines")

    def parse_event(self, data: Dict[str, Any], line_num: int) -> Optional[Dict[str, Any]]:
        """Parse a JSON event from the logs."""
        event_type = "Unknown"
        timestamp = datetime.now()
        content = ""

        # Extract timestamp
        if "timestamp" in data:
            try:
                ts_ms = int(data["timestamp"])
                timestamp = datetime.fromtimestamp(ts_ms / 1000)
            except (ValueError, OSError):
                pass

        # Determine event type and content
        if "greToClientEvent" in data:
            gre_messages = data["greToClientEvent"].get("greToClientMessages", [])
            if gre_messages:
                first_msg = gre_messages[0]
                event_type = first_msg.get("type", "GREEvent")

                # Extract meaningful content
                if event_type == "GREMessageType_GameStateMessage":
                    game_state = first_msg.get("gameStateMessage", {})
                    game_info = game_state.get("gameInfo", {})
                    if game_info:
                        stage = game_info.get("stage", "")
                        match_state = game_info.get("matchState", "")
                        content = f"Game: {stage}, Match: {match_state}"

                    # Look for player info
                    players = game_state.get("players", [])
                    if players:
                        life_info = []
                        for player in players[:2]:
                            seat = player.get("systemSeatNumber", "?")
                            life = player.get("lifeTotal", "?")
                            life_info.append(f"P{seat}:{life}")
                        if life_info:
                            content += f" | {' vs '.join(life_info)} life"

                elif event_type == "GREMessageType_DieRollResultsResp":
                    die_rolls = first_msg.get("dieRollResultsResp", {}).get("playerDieRolls", [])
                    if die_rolls:
                        rolls = [str(roll.get("rollValue", "?")) for roll in die_rolls]
                        content = f"Die roll: {' vs '.join(rolls)}"
            else:
                event_type = "GREEvent"

        elif "transactionId" in data:
            event_type = "Transaction"
            content = f"ID: {data.get('transactionId', 'Unknown')[:8]}..."

        # Look for other event types
        elif "type" in data:
            event_type = data["type"]

        # Check for rank-related content
        content_lower = json.dumps(data).lower()
        if any(term in content_lower for term in ["rank", "tier", "platinum", "gold", "mythic"]):
            event_type += " [RANK?]"

        return {
            "line": line_num,
            "type": event_type,
            "timestamp": timestamp,
            "content": content or f"Data keys: {list(data.keys())[:5]}",
            "raw_data": (
                json.dumps(data, indent=2)
                if len(str(data)) < 5000
                else json.dumps(data)[:5000] + "..."
            ),
        }

    def parse_unity_log(self, line: str, line_num: int) -> Optional[Dict[str, Any]]:
        """Parse Unity logger line."""
        event_type = "UnityLog"
        content = line

        # Extract event type from Unity format
        if "==>" in line:
            event_match = re.search(r"==> (\w+)", line)
            if event_match:
                event_type = f"Unity_{event_match.group(1)}"

        # Look for JSON in Unity log
        json_start = line.find("{")
        if json_start != -1:
            try:
                json_str = line[json_start:]
                json_data = json.loads(json_str)
                content = f"Unity event with data: {list(json_data.keys())[:3]}"
            except json.JSONDecodeError:
                pass

        return {
            "line": line_num,
            "type": event_type,
            "timestamp": datetime.now(),
            "content": content[:200] + "..." if len(content) > 200 else content,
            "raw_data": line,
        }

    def display_events(self, start: int = 0, count: int = 20) -> None:
        """Display events in terminal."""
        os.system("clear" if os.name == "posix" else "cls")

        print("=" * 80)
        print("🎯 MTGA LOG VIEWER")
        print(f"📁 File: {self.log_file}")
        print(f"📊 Events: {len(self.filtered_lines)} / {len(self.all_events)}")
        if self.filter_term:
            print(f"🔍 Filter: '{self.filter_term}'")
        print("=" * 80)

        end = min(start + count, len(self.filtered_lines))

        for i in range(start, end):
            event = self.filtered_lines[i]
            timestamp = event["timestamp"].strftime("%H:%M:%S")

            # Color coding
            color = ""
            if "RANK" in event["type"]:
                color = "🟡"  # Yellow for potential rank events
            elif "GameState" in event["type"]:
                color = "🟢"  # Green for game state
            elif "Unity" in event["type"]:
                color = "🔵"  # Blue for Unity events
            elif "GRE" in event["type"]:
                color = "🟣"  # Purple for GRE events

            print(f"{color} {i+1:3d} [{timestamp}] {event['type'][:20]:20} | {event['content']}")

        print("=" * 80)
        print(f"📍 Showing {start+1}-{end} of {len(self.filtered_lines)} events")
        print("Commands: [n]ext, [p]rev, [f]ilter, [d]etail, [q]uit, [r]ank")

    def filter_events(self, term: str) -> None:
        """Filter events by search term."""
        if not term:
            self.filtered_lines = self.all_events.copy()
            self.filter_term = ""
            return

        self.filter_term = term.lower()
        self.filtered_lines = []

        for event in self.all_events:
            # Search in type, content, and raw data
            search_text = f"{event['type']} {event['content']} {event.get('raw_data', '')}".lower()
            if term.lower() in search_text:
                self.filtered_lines.append(event)

    def show_detail(self, index: int) -> None:
        """Show detailed view of an event."""
        if 0 <= index < len(self.filtered_lines):
            event = self.filtered_lines[index]

            os.system("clear" if os.name == "posix" else "cls")
            print("=" * 80)
            print(f"🔍 EVENT DETAIL - #{index + 1}")
            print("=" * 80)
            print(f"Line: {event['line']}")
            print(f"Type: {event['type']}")
            print(f"Time: {event['timestamp']}")
            print(f"Content: {event['content']}")
            print("-" * 80)
            print("Raw Data:")
            print(event.get("raw_data", "No raw data"))
            print("=" * 80)
            input("Press Enter to continue...")

    def run(self) -> None:
        """Main viewer loop."""
        self.load_logs()

        if not self.all_events:
            print("No events to display")
            return

        current_pos = 0
        page_size = 20

        while True:
            self.display_events(current_pos, page_size)

            try:
                cmd = input("\nEnter command: ").strip().lower()

                if cmd in ["q", "quit", "exit"]:
                    break
                elif cmd in ["n", "next"]:
                    if current_pos + page_size < len(self.filtered_lines):
                        current_pos += page_size
                elif cmd in ["p", "prev", "previous"]:
                    current_pos = max(0, current_pos - page_size)
                elif cmd in ["f", "filter"]:
                    filter_term = input("Enter filter term (or empty to clear): ").strip()
                    self.filter_events(filter_term)
                    current_pos = 0
                elif cmd in ["r", "rank"]:
                    # Quick filter for rank-related events
                    self.filter_events("rank")
                    current_pos = 0
                elif cmd in ["d", "detail"]:
                    try:
                        idx = int(input("Enter event number: ")) - 1
                        self.show_detail(idx)
                    except (ValueError, IndexError):
                        input("Invalid event number. Press Enter...")
                elif cmd.isdigit():
                    # Jump to specific event
                    target = int(cmd) - 1
                    if 0 <= target < len(self.filtered_lines):
                        current_pos = (target // page_size) * page_size
                elif cmd == "help":
                    print("\nCommands:")
                    print("  n/next - Next page")
                    print("  p/prev - Previous page")
                    print("  f/filter - Filter events")
                    print("  r/rank - Filter for rank events")
                    print("  d/detail - Show event detail")
                    print("  <number> - Jump to event")
                    print("  q/quit - Exit")
                    input("\nPress Enter...")
                else:
                    print("Unknown command. Type 'help' for commands.")
                    time.sleep(1)

            except KeyboardInterrupt:
                break
            except EOFError:
                break

        print("\n👋 Thanks for using MTGA Log Viewer!")


def main():
    """Main entry point."""
    # Try command-line argument first
    if len(sys.argv) > 1:
        log_file = Path(sys.argv[1])
    else:
        # Try to use configured log file path
        try:
            # Lazy import to avoid dependency issues
            sys.path.insert(0, str(Path(__file__).parent))
            from src.config.settings import config_manager

            config = config_manager.config

            # Use configured MTGA log path
            if config.mtga.log_file_path:
                log_file = Path(config.mtga.log_file_path)
                print(f"📁 Using configured log file: {log_file}")
            else:
                # Try auto-detection
                common_paths = config_manager.get_mtga_log_paths()
                if common_paths:
                    log_file = Path(common_paths[0])
                    print(f"🔍 Auto-detected log file: {log_file}")
                else:
                    # Fall back to test logs
                    log_file = Path("mtga-test-logs/Player.log")
                    print(f"🧪 Using test log file: {log_file}")

        except Exception as e:
            print(f"⚠️ Config system error: {e}")
            print("📁 Falling back to test logs")
            log_file = Path("mtga-test-logs/Player.log")

    if not log_file.exists():
        print(f"❌ Log file not found: {log_file}")
        print("\n💡 Options:")
        print("1. python3 log_viewer.py /path/to/MTGArena/logs/Player.log")
        print("2. Configure log path in application settings")
        print("3. Place logs in mtga-test-logs/Player.log for testing")
        sys.exit(1)

    viewer = MTGALogViewer(log_file)
    viewer.run()


if __name__ == "__main__":
    main()
