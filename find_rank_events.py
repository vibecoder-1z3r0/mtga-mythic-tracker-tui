#!/usr/bin/env python3
"""
Quick script to find rank progression events in MTGA logs.
"""

from pathlib import Path


def find_rank_events():
    """Find and display rank-related events."""
    log_file = Path("mtga-test-logs/Player.log")

    print("🔍 Searching for rank events...")

    rank_events = []
    line_num = 0

    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_num += 1
            line = line.strip()

            # Look for rank-related keywords
            rank_keywords = [
                "rank",
                "tier",
                "platinum",
                "plat",
                "gold",
                "mythic",
                "diamond",
                "bronze",
            ]
            line_lower = line.lower()

            if any(keyword in line_lower for keyword in rank_keywords):
                rank_events.append(
                    {
                        "line": line_num,
                        "content": line[:300] + "..." if len(line) > 300 else line,
                    }
                )

    print(f"Found {len(rank_events)} potential rank events:")
    print("=" * 80)

    for i, event in enumerate(rank_events[:20]):  # Show first 20
        print(f"{i+1:2d}. Line {event['line']:4d}: {event['content']}")
        print()

    if len(rank_events) > 20:
        print(f"... and {len(rank_events) - 20} more events")


if __name__ == "__main__":
    find_rank_events()
