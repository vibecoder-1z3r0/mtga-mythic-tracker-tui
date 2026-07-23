#!/usr/bin/env python3
"""
Convert event-mode data (a Ctrl+E export, or the live tracker_state.json)
into a CSV of individual games, one row per game, for external
archetype/matchup analysis tools.

Usage:
    python3 export_matchup_csv.py <state.json> [--reporting-player NAME] [--output out.csv]

Columns:
    Time             game timestamp, "YYYY-MM-DD HH:MM"
    ReportingPlayer  --reporting-player value (default: Tyraziel)
    Opponent         opponent's MTGA username, if recorded (blank otherwise -
                     this wasn't tracked until opponent_name was added, so
                     older games will always be blank here)
    Archetype1       your deck for that run (EventRun.player_deck)
    Archetype2       opponent's deck for that game (EventGame.opponent_deck)
    GameType         always 0
    PlayDrawKnown    1 if you were on the play, 2 if on the draw, blank if
                     unrecorded
    Winner(1|2)      1 if you won, 2 if you lost
    ArchetypeWinner  Archetype1 if you won, else Archetype2
"""
import argparse
import csv
from pathlib import Path

from models.event import EventGameResult
from storage.state_manager import StateManager

FIELDNAMES = [
    "Time",
    "ReportingPlayer",
    "Opponent",
    "Archetype1",
    "Archetype2",
    "GameType",
    "PlayDrawKnown",
    "Winner(1|2)",
    "ArchetypeWinner",
]


def _play_draw_known(play_draw):
    if play_draw == "Play":
        return 1
    if play_draw == "Draw":
        return 2
    return ""


def build_rows(app_data, reporting_player: str) -> list:
    """One row per game across every run (completed and, if any, the
    current in-progress one - its finished games are just as real)."""
    stats = app_data.event_stats
    runs = list(stats.recent_runs)
    if stats.current_run:
        runs.append(stats.current_run)

    rows = []
    for run in runs:
        archetype1 = run.player_deck or "Unknown"
        for game in run.games:
            archetype2 = game.opponent_deck or "Unknown"
            winner = 1 if game.result == EventGameResult.WIN else 2
            rows.append(
                {
                    "Time": game.timestamp.strftime("%Y-%m-%d %H:%M"),
                    "ReportingPlayer": reporting_player,
                    "Opponent": game.opponent_name or "",
                    "Archetype1": archetype1,
                    "Archetype2": archetype2,
                    "GameType": 0,
                    "PlayDrawKnown": _play_draw_known(game.play_draw),
                    "Winner(1|2)": winner,
                    "ArchetypeWinner": archetype1 if winner == 1 else archetype2,
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "input", type=Path, help="Path to an exported state JSON (Ctrl+E) or the live tracker_state.json"
    )
    parser.add_argument("--reporting-player", default="Tyraziel", help="Value for the ReportingPlayer column")
    parser.add_argument("--output", type=Path, default=None, help="Output CSV path (default: <input>.csv)")
    args = parser.parse_args()

    state_manager = StateManager(save_enabled=False)
    app_data = state_manager.import_state(args.input)

    rows = build_rows(app_data, args.reporting_player)

    output = args.output or args.input.with_suffix(".csv")
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} games to {output}")


if __name__ == "__main__":
    main()
