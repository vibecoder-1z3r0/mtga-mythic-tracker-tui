#!/usr/bin/env python3
"""
Test script for MTGA log parser.
"""

import tempfile
from datetime import datetime
from pathlib import Path

from src.parsers.mtga_parser import MTGALogParser, MTGALogEvent, create_mock_log_data
from src.models.game import GameResult, PlayOrder
from src.models.rank import RankTier


def test_log_line_parsing():
    """Test parsing individual log lines."""
    parser = MTGALogParser()

    # Real MTGA log lines are bare JSON objects, no bracketed timestamp prefix.
    test_line = '{"type": "Event_GameRoomEnter", "format": "Standard Ranked"}'
    event = parser._parse_log_line(test_line)

    assert event is not None
    assert event.event_type == "Event_GameRoomEnter"
    assert isinstance(event.timestamp, datetime)
    assert event.data.get("format") == "Standard Ranked"

    invalid_line = "This is not a valid log line"
    assert parser._parse_log_line(invalid_line) is None


def test_event_filtering():
    """Test event filtering for relevant events."""
    parser = MTGALogParser()

    relevant_events = [
        "Event_GameRoomEnter",
        "Event_MatchGameRoomStateChangedEvent",
        "Event_RankUpdated",
        "Event_PlayerLifeChanged",
    ]
    irrelevant_events = [
        "Event_SomeOtherEvent",
        "Event_UIUpdate",
        "Event_NetworkStatus",
    ]

    for event_type in relevant_events:
        assert parser._is_relevant_event(event_type), f"{event_type} should be relevant"

    for event_type in irrelevant_events:
        assert not parser._is_relevant_event(event_type), f"{event_type} should be filtered out"


def test_mock_log_parsing():
    """Test parsing mock log data end-to-end, including game extraction."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        for line in create_mock_log_data():
            f.write(line + "\n")
        temp_log_path = Path(f.name)

    try:
        parser = MTGALogParser()
        events = list(parser.parse_log_file(temp_log_path))
        assert len(events) == 10

        games = []
        current_game_events = []
        for event in events:
            current_game_events.append(event)
            if event.event_type in parser.GAME_END_EVENTS:
                game = parser.extract_game_from_events(current_game_events)
                if game:
                    games.append(game)
                current_game_events = []

        assert len(games) == 2

        assert games[0].result == GameResult.WIN
        assert games[0].play_order == PlayOrder.DRAW
        assert games[0].rank_change_str() == "+2 pips"
        assert games[0].player_deck == "Esper Control"
        assert games[0].opponent_deck == "Mono-Red Aggro"

        assert games[1].result == GameResult.LOSS
        assert games[1].play_order == PlayOrder.PLAY
        assert games[1].rank_change_str() == "-1 pips"
        assert games[1].opponent_deck == "Grixis Midrange"
    finally:
        temp_log_path.unlink()


def test_rank_parsing():
    """Test rank data parsing."""
    parser = MTGALogParser()

    gold_rank_data = {"tier": "Gold", "division": 2, "pips": 4}
    gold_rank = parser._parse_rank_data(gold_rank_data)
    assert gold_rank is not None
    assert gold_rank.tier == RankTier.GOLD
    assert gold_rank.division == 2
    assert gold_rank.pips == 4

    mythic_rank_data = {"tier": "Mythic", "percentage": 85.5}
    mythic_rank = parser._parse_rank_data(mythic_rank_data)
    assert mythic_rank is not None
    assert mythic_rank.tier == RankTier.MYTHIC
    assert mythic_rank.mythic_percentage == 85.5


def test_live_game_state_extraction():
    """Test live game state extraction."""
    parser = MTGALogParser()

    life_event = MTGALogEvent(
        timestamp=datetime.now(),
        event_type="Event_PlayerLifeChanged",
        data={"playerLife": 18, "opponentLife": 12},
    )
    life_state = parser.extract_live_game_state(life_event)
    assert life_state.get("player_life") == 18
    assert life_state.get("opponent_life") == 12

    turn_event = MTGALogEvent(
        timestamp=datetime.now(),
        event_type="Event_TurnChanged",
        data={"turnNumber": 7},
    )
    turn_state = parser.extract_live_game_state(turn_event)
    assert turn_state.get("turn_number") == 7

    game_event = MTGALogEvent(
        timestamp=datetime.now(),
        event_type="Event_GameRoomStateChangedEvent",
        data={"gameState": "Playing", "playerHandSize": 4, "opponentHandSize": 3},
    )
    game_state = parser.extract_live_game_state(game_event)
    assert game_state.get("is_in_game") is True
    assert game_state.get("player_cards_in_hand") == 4
    assert game_state.get("opponent_cards_in_hand") == 3


def main():
    """Run all parser tests."""
    test_log_line_parsing()
    test_event_filtering()
    test_mock_log_parsing()
    test_rank_parsing()
    test_live_game_state_extraction()
    print("All parser tests passed!")
    print("Note: Parser is ready for real MTGA log data;")
    print("replace mock logic in _extract_* methods with actual log parsing.")


if __name__ == "__main__":
    main()
