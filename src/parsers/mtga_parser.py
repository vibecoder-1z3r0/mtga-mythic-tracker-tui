"""
MTGA log file parser for extracting game data.
"""

import json
import re
from datetime import datetime
from typing import Optional, Dict, Any, List, Generator, Tuple
from pathlib import Path

from ..models.game import Game, GameResult, PlayOrder, FormatType
from ..models.rank import Rank, RankTier


class MTGALogEvent:
    """Represents a parsed MTGA log event."""

    def __init__(self, timestamp: datetime, event_type: str, data: Dict[Any, Any]):
        self.timestamp = timestamp
        self.event_type = event_type
        self.data = data

    def __repr__(self) -> str:
        return f"MTGALogEvent({self.event_type} at {self.timestamp})"


class MTGALogParser:
    """Parser for MTGA log files."""

    # Event types we care about (based on real MTGA logs)
    GAME_START_EVENTS = [
        "GREMessageType_GameStateMessage",
        "EventJoin",
        "GREMessageType_DieRollResultsResp",
    ]

    GAME_END_EVENTS = [
        "GREMessageType_GameStateMessage",
        "Event_MatchCompleted",
        "Event_GameEnd",
    ]

    RANK_UPDATE_EVENTS = [
        "Event_RankUpdated",
        "Event_ConstructedRankUpdated",
        "Event_LimitedRankUpdated",
        "Event_SeasonAndRankDetail",
    ]

    GAME_STATE_EVENTS = [
        "GREMessageType_GameStateMessage",
        "GREMessageType_SetSettingsResp",
        "Event_PlayerLifeChanged",
        "Event_TurnChanged",
    ]

    def __init__(self):
        self.current_game_state = {}
        self.last_processed_line = 0

    def parse_log_file(
        self, log_file: Path, start_from: int = 0
    ) -> Generator[MTGALogEvent, None, None]:
        """Parse MTGA log file and yield relevant events."""
        if not log_file.exists():
            return

        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                # Skip to start position
                for _ in range(start_from):
                    f.readline()

                line_number = start_from
                for line in f:
                    line_number += 1
                    event = self._parse_log_line(line.strip())
                    if event:
                        yield event

                self.last_processed_line = line_number

        except Exception as e:
            print(f"Error parsing log file {log_file}: {e}")

    def _parse_log_line(self, line: str) -> Optional[MTGALogEvent]:
        """Parse a single log line into an event with enhanced real log understanding."""
        line = line.strip()
        if not line:
            return None

        try:
            # Handle JSON lines (most MTGA events)
            if line.startswith("{"):
                data = json.loads(line)

                # Extract timestamp from various possible locations
                timestamp = datetime.now()  # Default fallback

                if "timestamp" in data:
                    try:
                        # Convert MTGA timestamp (milliseconds since epoch)
                        ts_ms = int(data["timestamp"])
                        timestamp = datetime.fromtimestamp(ts_ms / 1000)
                    except (ValueError, OSError):
                        pass

                # Determine event type and detect rank events
                event_type, is_rank_event = self._analyze_json_event(data)

                # Return all rank events and other relevant events
                if is_rank_event or self._is_relevant_event(event_type):
                    return MTGALogEvent(timestamp, event_type, data)

            # Handle Unity logger events
            elif "[UnityCrossThreadLogger]" in line:
                # Extract event type from Unity logger format
                if "==>" in line:
                    event_match = re.search(r"==> (\w+)", line)
                    event_type = event_match.group(1) if event_match else "UnityLog"
                else:
                    event_type = "UnityLog"

                # Check if Unity event is rank-related
                is_rank_event = any(term in line.lower() for term in ["rank", "season", "tier"])

                # Create synthetic JSON for Unity events
                data = {
                    "unity_log": line,
                    "event_type": event_type,
                    "is_rank_event": is_rank_event,
                }

                if is_rank_event or self._is_relevant_event(event_type):
                    return MTGALogEvent(datetime.now(), event_type, data)

        except (json.JSONDecodeError, ValueError):
            # Skip malformed lines
            pass

        return None

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse MTGA timestamp string to datetime."""
        # MTGA uses format like "2025-08-10 16:30:45.123"
        try:
            # Handle various timestamp formats
            formats = [
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%m/%d/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
            ]

            for fmt in formats:
                try:
                    return datetime.strptime(timestamp_str, fmt)
                except ValueError:
                    continue

            # Fallback to current time if parsing fails
            return datetime.now()

        except Exception:
            return datetime.now()

    def _analyze_json_event(self, data: Dict[str, Any]) -> Tuple[str, bool]:
        """Analyze JSON event with enhanced understanding from real logs."""
        event_type = "Unknown"
        is_rank_event = False

        # Direct rank information (CRITICAL!)
        if "constructedClass" in data:
            event_type = "RankInfo_Constructed"
            is_rank_event = True
        elif "limitedClass" in data:
            event_type = "RankInfo_Limited"
            is_rank_event = True

        # GRE (Game Rules Engine) Events
        elif "greToClientEvent" in data:
            gre_messages = data["greToClientEvent"].get("greToClientMessages", [])
            if gre_messages:
                first_msg = gre_messages[0]
                msg_type = first_msg.get("type", "GREEvent")
                event_type = f"GRE_{msg_type}"
            else:
                event_type = "GREEvent"

        # Transaction events
        elif "transactionId" in data:
            event_type = "Transaction"

        # Match game room events
        elif "matchGameRoomStateChangedEvent" in data:
            event_type = "MatchRoomEvent"

        # Inventory/Collection updates
        elif "InventoryInfo" in data:
            event_type = "InventoryUpdate"

        # Check for direct event types
        elif "type" in data:
            event_type = data["type"]

        # Check for rank-related keywords in any JSON that didn't already
        # resolve to a concrete event type, so we don't corrupt exact-match
        # dispatch (e.g. in _process_event_for_game) for events we already
        # identified.
        if not is_rank_event and event_type == "Unknown":
            json_str = json.dumps(data).lower()
            if any(
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

        return event_type, is_rank_event

    def _is_relevant_event(self, event_type: str) -> bool:
        """Check if an event type is relevant for tracking."""
        # Enhanced relevance check
        if any(
            keyword in event_type.lower()
            for keyword in ["gre_", "rank", "match", "game", "transaction", "inventory"]
        ):
            return True

        # Original event lists
        relevant_events = (
            self.GAME_START_EVENTS
            + self.GAME_END_EVENTS
            + self.RANK_UPDATE_EVENTS
            + self.GAME_STATE_EVENTS
        )
        return event_type in relevant_events

    def extract_game_from_events(self, events: List[MTGALogEvent]) -> Optional[Game]:
        """Extract a complete game from a sequence of events."""
        if not events:
            return None

        game_data = {
            "timestamp": events[0].timestamp,
            "result": None,
            "play_order": None,
            "format_type": FormatType.CONSTRUCTED,  # Default
            "player_deck": None,
            "opponent_deck": None,
            "notes": "",
            "rank_before": None,
            "rank_after": None,
            "pips_gained": 0,
        }

        # Process events to extract game data
        for event in events:
            self._process_event_for_game(event, game_data)

        # Only create game if we have essential data
        if game_data["result"] is not None:
            return Game(**game_data)

        return None

    def _process_event_for_game(self, event: MTGALogEvent, game_data: Dict[str, Any]) -> None:
        """Process a single event to update game data."""
        if event.event_type in self.GAME_END_EVENTS:
            self._extract_game_result(event, game_data)
        elif event.event_type in self.RANK_UPDATE_EVENTS:
            self._extract_rank_data(event, game_data)
        elif event.event_type in self.GAME_START_EVENTS:
            self._extract_game_start_data(event, game_data)

    def _extract_game_result(self, event: MTGALogEvent, game_data: Dict[str, Any]) -> None:
        """Extract game result from event."""
        data = event.data

        # Mock logic - replace with real parsing
        if "gameResult" in data:
            result = data["gameResult"]
            if result == "Won":
                game_data["result"] = GameResult.WIN
            elif result == "Lost":
                game_data["result"] = GameResult.LOSS
            else:
                game_data["result"] = GameResult.DRAW

        # Extract play/draw information
        if "playFirst" in data:
            game_data["play_order"] = PlayOrder.PLAY if data["playFirst"] else PlayOrder.DRAW

    def _extract_rank_data(self, event: MTGALogEvent, game_data: Dict[str, Any]) -> None:
        """Extract rank change data from event using real MTGA log format."""
        data = event.data

        # Real MTGA rank format discovered from logs
        if "constructedClass" in data:
            rank = self._parse_real_rank_data(data, "constructed")
            if rank:
                # Use as either before or after rank based on context
                if not game_data.get("rank_before"):
                    game_data["rank_before"] = rank
                else:
                    game_data["rank_after"] = rank

        elif "limitedClass" in data:
            rank = self._parse_real_rank_data(data, "limited")
            if rank:
                if not game_data.get("rank_before"):
                    game_data["rank_before"] = rank
                else:
                    game_data["rank_after"] = rank

        # Legacy format support
        if "rankBefore" in data:
            game_data["rank_before"] = self._parse_rank_data(data["rankBefore"])
        if "rankAfter" in data:
            game_data["rank_after"] = self._parse_rank_data(data["rankAfter"])
        if "pipsGained" in data:
            game_data["pips_gained"] = data["pipsGained"]

    def _extract_game_start_data(self, event: MTGALogEvent, game_data: Dict[str, Any]) -> None:
        """Extract game start data from event."""
        data = event.data

        # Extract format type
        if "format" in data:
            format_str = data["format"].lower()
            if "draft" in format_str or "sealed" in format_str:
                game_data["format_type"] = FormatType.LIMITED
            else:
                game_data["format_type"] = FormatType.CONSTRUCTED

        # Extract deck information (placeholder)
        if "playerDeck" in data:
            game_data["player_deck"] = data["playerDeck"]
        if "opponentDeck" in data:
            game_data["opponent_deck"] = data["opponentDeck"]

    def _parse_real_rank_data(self, data: Dict[str, Any], format_type: str) -> Optional[Rank]:
        """Parse rank data from real MTGA log format."""
        try:
            prefix = format_type  # 'constructed' or 'limited'
            tier_name = data.get(f"{prefix}Class", "").title()

            if not tier_name:
                return None

            # Map MTGA tier names to our enum
            tier_mapping = {
                "Bronze": RankTier.BRONZE,
                "Silver": RankTier.SILVER,
                "Gold": RankTier.GOLD,
                "Platinum": RankTier.PLATINUM,
                "Diamond": RankTier.DIAMOND,
                "Mythic": RankTier.MYTHIC,
            }

            tier = tier_mapping.get(tier_name, RankTier.BRONZE)

            if tier == RankTier.MYTHIC:
                # For Mythic, we might have percentage data
                percentage = data.get(f"{prefix}Percentage", 95.0)
                return Rank(tier=tier, mythic_percentage=percentage)
            else:
                # Use real field names: constructedLevel = division, constructedStep = pips
                division = data.get(f"{prefix}Level", 4)
                pips = data.get(f"{prefix}Step", 0)
                return Rank(tier=tier, division=division, pips=pips)

        except Exception:
            return None

    def _parse_rank_data(self, rank_data: Dict[str, Any]) -> Optional[Rank]:
        """Parse rank data from legacy event format."""
        try:
            tier_name = rank_data.get("tier", "").title()
            tier = (
                RankTier(tier_name) if tier_name in [t.value for t in RankTier] else RankTier.BRONZE
            )

            if tier == RankTier.MYTHIC:
                percentage = rank_data.get("percentage", 95.0)
                return Rank(tier=tier, mythic_percentage=percentage)
            else:
                division = rank_data.get("division", 4)
                pips = rank_data.get("pips", 0)
                return Rank(tier=tier, division=division, pips=pips)

        except Exception:
            return None

    def extract_live_game_state(self, event: MTGALogEvent) -> Dict[str, Any]:
        """Extract live game state from event."""
        state = {}
        data = event.data

        if event.event_type == "Event_PlayerLifeChanged":
            state["player_life"] = data.get("playerLife")
            state["opponent_life"] = data.get("opponentLife")
        elif event.event_type == "Event_TurnChanged":
            state["turn_number"] = data.get("turnNumber")
        elif event.event_type == "Event_GameRoomStateChangedEvent":
            state["is_in_game"] = data.get("gameState") == "Playing"
            state["player_cards_in_hand"] = data.get("playerHandSize")
            state["opponent_cards_in_hand"] = data.get("opponentHandSize")

        return state


def create_mock_log_data() -> List[str]:
    """Create mock MTGA log data for testing.

    Lines are bare JSON objects (no bracketed timestamp prefix) matching the
    real MTGA log format, and use event types that match GAME_START_EVENTS /
    GAME_END_EVENTS / RANK_UPDATE_EVENTS exactly so extract_game_from_events
    can actually assemble complete games from them.
    """
    mock_lines = [
        # First game - a win, on the draw
        '{"timestamp": 1723305900123, "type": "EventJoin", "format": "Standard Ranked", "playerDeck": "Esper Control", "opponentDeck": "Mono-Red Aggro"}',
        '{"timestamp": 1723305902789, "type": "Event_PlayerLifeChanged", "playerLife": 20, "opponentLife": 20}',
        '{"timestamp": 1723305930123, "type": "Event_TurnChanged", "turnNumber": 5}',
        '{"timestamp": 1723305931456, "type": "Event_PlayerLifeChanged", "playerLife": 18, "opponentLife": 12}',
        '{"timestamp": 1723306246123, "type": "Event_RankUpdated", "rankBefore": {"tier": "Gold", "division": 2, "pips": 4}, "rankAfter": {"tier": "Gold", "division": 2, "pips": 6}, "pipsGained": 2}',
        '{"timestamp": 1723306245789, "type": "Event_GameEnd", "gameResult": "Won", "playFirst": false}',
        # Second game - a loss, on the play
        '{"timestamp": 1723306500789, "type": "EventJoin", "format": "Standard Ranked", "playerDeck": "Esper Control", "opponentDeck": "Grixis Midrange"}',
        '{"timestamp": 1723306501123, "type": "Event_PlayerLifeChanged", "playerLife": 20, "opponentLife": 20}',
        '{"timestamp": 1723306711789, "type": "Event_RankUpdated", "rankBefore": {"tier": "Gold", "division": 2, "pips": 6}, "rankAfter": {"tier": "Gold", "division": 2, "pips": 5}, "pipsGained": -1}',
        '{"timestamp": 1723306710456, "type": "Event_GameEnd", "gameResult": "Lost", "playFirst": true}',
    ]
    return mock_lines
