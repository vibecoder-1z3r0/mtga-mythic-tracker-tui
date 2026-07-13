#!/usr/bin/env python3
"""
Test script for parsing real MTGA logs.
"""

from pathlib import Path
from src.parsers.mtga_parser import MTGALogParser


def test_real_log_parsing():
    """Test parsing real MTGA log files."""
    print("=== Testing Real MTGA Log Parsing ===")

    log_file = Path("mtga-test-logs/Player.log")

    if not log_file.exists():
        print("❌ No real log file found at mtga-test-logs/Player.log")
        return

    parser = MTGALogParser()
    events = []

    # Parse first 1000 lines to avoid overwhelming output
    try:
        for event in parser.parse_log_file(log_file):
            events.append(event)
            if len(events) >= 20:  # Limit for testing
                break

        print(f"✅ Parsed {len(events)} events from real logs")

        # Show event breakdown
        event_types = {}
        for event in events:
            event_types[event.event_type] = event_types.get(event.event_type, 0) + 1

        print("\n📊 Event types found:")
        for event_type, count in sorted(event_types.items()):
            print(f"  {event_type}: {count}")

        # Show sample events
        if events:
            print("\n📋 Sample events:")
            for i, event in enumerate(events[:5]):
                print(f"  {i+1}. {event.event_type} at {event.timestamp}")
                # Show some data keys (first level only)
                data_keys = list(event.data.keys())[:5]
                print(f"     Data keys: {data_keys}")

    except Exception as e:
        print(f"❌ Error parsing real logs: {e}")
        import traceback

        traceback.print_exc()

    print()


def test_game_state_extraction():
    """Test extracting game state from real logs."""
    print("=== Testing Game State Extraction from Real Logs ===")

    log_file = Path("mtga-test-logs/Player.log")

    if not log_file.exists():
        print("❌ No real log file found")
        return

    parser = MTGALogParser()
    game_state_events = []

    try:
        for event in parser.parse_log_file(log_file):
            if event.event_type in parser.GAME_STATE_EVENTS:
                game_state_events.append(event)

            if len(game_state_events) >= 5:  # Limit for testing
                break

        print(f"✅ Found {len(game_state_events)} game state events")

        for i, event in enumerate(game_state_events):
            print(f"\n🎮 Game State Event {i+1}:")
            print(f"   Type: {event.event_type}")
            print(f"   Time: {event.timestamp}")

            # Try to extract live game state
            live_state = parser.extract_live_game_state(event)
            if live_state:
                print(f"   Live state extracted: {live_state}")

            # Show some relevant data structure
            if "greToClientEvent" in event.data:
                gre_msgs = event.data["greToClientEvent"].get("greToClientMessages", [])
                if gre_msgs:
                    msg = gre_msgs[0]
                    msg_type = msg.get("type", "Unknown")
                    print(f"   GRE Message: {msg_type}")

                    # Look for game state info
                    if "gameStateMessage" in msg:
                        game_info = msg["gameStateMessage"].get("gameInfo", {})
                        if game_info:
                            stage = game_info.get("stage", "Unknown")
                            match_state = game_info.get("matchState", "Unknown")
                            print(f"   Game Stage: {stage}")
                            print(f"   Match State: {match_state}")

                        # Look for player info
                        players = msg["gameStateMessage"].get("players", [])
                        if players:
                            for player in players[:2]:  # Show first 2 players
                                seat = player.get("systemSeatNumber", "?")
                                life = player.get("lifeTotal", "?")
                                status = player.get("status", "Unknown")
                                print(f"   Player {seat}: {life} life, {status}")

    except Exception as e:
        print(f"❌ Error extracting game state: {e}")
        import traceback

        traceback.print_exc()

    print()


def test_log_structure_analysis():
    """Analyze the structure of real MTGA logs."""
    print("=== Analyzing Real Log Structure ===")

    log_file = Path("mtga-test-logs/Player.log")

    if not log_file.exists():
        print("❌ No real log file found")
        return

    json_lines = 0
    unity_lines = 0
    other_lines = 0

    try:
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= 1000:  # Analyze first 1000 lines
                    break

                line = line.strip()
                if line.startswith("{"):
                    json_lines += 1
                elif "[UnityCrossThreadLogger]" in line:
                    unity_lines += 1
                else:
                    other_lines += 1

        total = json_lines + unity_lines + other_lines
        print("📈 Log structure analysis (first 1000 lines):")
        print(f"  JSON lines: {json_lines} ({json_lines/total*100:.1f}%)")
        print(f"  Unity logger lines: {unity_lines} ({unity_lines/total*100:.1f}%)")
        print(f"  Other lines: {other_lines} ({other_lines/total*100:.1f}%)")

        # Show sample of each type
        print("\n📝 Sample lines:")
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            lines_shown = {"json": 0, "unity": 0, "other": 0}
            for line in f:
                line = line.strip()
                if line.startswith("{") and lines_shown["json"] < 1:
                    print(f"  JSON: {line[:100]}...")
                    lines_shown["json"] += 1
                elif "[UnityCrossThreadLogger]" in line and lines_shown["unity"] < 1:
                    print(f"  Unity: {line[:100]}...")
                    lines_shown["unity"] += 1
                elif lines_shown["other"] < 1 and line and not line.startswith("{"):
                    print(f"  Other: {line[:100]}...")
                    lines_shown["other"] += 1

                if all(v > 0 for v in lines_shown.values()):
                    break

    except Exception as e:
        print(f"❌ Error analyzing log structure: {e}")

    print()


def main():
    """Run all real log tests."""
    print("MTG Arena Tracker - Real Log Testing")
    print("=" * 45)

    try:
        test_log_structure_analysis()
        test_real_log_parsing()
        test_game_state_extraction()

        print("✅ Real log testing completed!")
        print("\n💡 Next steps:")
        print("   - Update parser logic based on real event structures")
        print("   - Implement game state extraction for life totals, turns")
        print("   - Add rank update parsing when rank events are found")

    except Exception as e:
        print(f"❌ Real log test failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
