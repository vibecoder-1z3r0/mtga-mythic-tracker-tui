#!/usr/bin/env python3
"""
Analyze rank progression events in MTGA logs.
"""

import json
from pathlib import Path
from datetime import datetime


def analyze_rank_progression():
    """Find and analyze rank progression events."""
    log_file = Path("mtga-test-logs/Player.log")

    print("🎯 Analyzing Rank Progression...")
    print("=" * 60)

    rank_events = []
    line_num = 0

    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_num += 1
            line = line.strip()

            if not line.startswith("{"):
                continue

            try:
                data = json.loads(line)

                # Look for rank info in various formats
                rank_info = None
                event_type = "Unknown"
                timestamp = None

                # Extract timestamp if available
                if "timestamp" in data:
                    try:
                        ts_ms = int(data["timestamp"])
                        timestamp = datetime.fromtimestamp(ts_ms / 1000)
                    except (ValueError, OSError):
                        pass

                # Check for constructed rank details
                if "constructedClass" in data:
                    rank_info = {
                        "format": "Constructed",
                        "class": data.get("constructedClass", ""),
                        "level": data.get("constructedLevel", ""),
                        "step": data.get("constructedStep", ""),
                        "matches_won": data.get("constructedMatchesWon", ""),
                        "matches_lost": data.get("constructedMatchesLost", ""),
                    }
                    event_type = "RankInfo"

                # Check for limited rank details
                elif "limitedClass" in data:
                    rank_info = {
                        "format": "Limited",
                        "class": data.get("limitedClass", ""),
                        "level": data.get("limitedLevel", ""),
                        "step": data.get("limitedStep", ""),
                    }
                    event_type = "RankInfo"

                # Check for rank update events
                elif any(key in data for key in ["rankUpdateDelta", "newRank", "oldRank"]):
                    rank_info = data
                    event_type = "RankUpdate"

                # Check for match completion with rank changes
                elif "matchGameRoomStateChangedEvent" in data:
                    room_info = data["matchGameRoomStateChangedEvent"]
                    if any(key in str(room_info) for key in ["rank", "tier", "progression"]):
                        rank_info = room_info
                        event_type = "MatchWithRank"

                if rank_info:
                    rank_events.append(
                        {
                            "line": line_num,
                            "type": event_type,
                            "timestamp": timestamp,
                            "rank_info": rank_info,
                            "raw_data": data,
                        }
                    )

            except json.JSONDecodeError:
                continue

    print(f"Found {len(rank_events)} rank-related events:")
    print()

    # Display rank progression
    for i, event in enumerate(rank_events):
        time_str = event["timestamp"].strftime("%H:%M:%S") if event["timestamp"] else "Unknown"

        print(f"🔸 Event {i+1} - Line {event['line']} [{time_str}] - {event['type']}")

        if event["type"] == "RankInfo":
            info = event["rank_info"]
            if info.get("format") == "Constructed":
                tier = info.get("class", "Unknown")
                level = info.get("level", "?")
                step = info.get("step", "?")
                won = info.get("matches_won", "?")
                lost = info.get("matches_lost", "?")

                print(f"   📊 Constructed: {tier} Tier {level} ({step}/6 pips)")
                print(f"   🎮 Record: {won}W-{lost}L")

                # Check for the progression you mentioned
                if tier == "Platinum" and level in [3, 4]:
                    print(f"   🎯 FOUND PLAT {level} - This matches your progression!")

            elif info.get("format") == "Limited":
                tier = info.get("class", "Unknown")
                level = info.get("level", "?")
                print(f"   📊 Limited: {tier} Tier {level}")

        elif event["type"] == "RankUpdate":
            print(f"   📈 Rank Update: {list(event['rank_info'].keys())}")

        elif event["type"] == "MatchWithRank":
            print("   🎮 Match with rank data")

        print()

    # Summary
    if rank_events:
        print("=" * 60)
        print("🎯 RANK PROGRESSION SUMMARY")
        print("=" * 60)

        constructed_events = [
            e for e in rank_events if e["rank_info"].get("format") == "Constructed"
        ]
        if constructed_events:
            print("Constructed Progression:")
            for event in constructed_events:
                info = event["rank_info"]
                tier = info.get("class", "Unknown")
                level = info.get("level", "?")
                step = info.get("step", "?")
                time_str = (
                    event["timestamp"].strftime("%H:%M:%S") if event["timestamp"] else "Unknown"
                )
                print(f"  {time_str}: {tier} Tier {level} ({step}/6 pips)")

        print("\n🎉 This should show your Plat 3→4→3 progression!")


if __name__ == "__main__":
    analyze_rank_progression()
