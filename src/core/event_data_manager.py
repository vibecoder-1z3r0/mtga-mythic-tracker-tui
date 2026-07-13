"""
Event-mode historical data persistence and aggregation, parallel to
DataManager but scoped to event sessions/runs.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from ..config.settings import config_manager
from ..models.event import (
    EventDefinition,
    EventSession,
    PrizeTotal,
    default_catalog_path,
    load_event_catalog,
)
from .serialization import deserialize_datetimes


class EventDataManager:
    """Manages event session history and cross-session/cross-event aggregation."""

    def __init__(self):
        self.events_dir = config_manager.config.get_events_dir()

    def list_sessions(self, event_id: Optional[str] = None) -> List[Path]:
        """List saved event session files, optionally filtered to one event."""
        if not self.events_dir.exists():
            return []

        files = list(self.events_dir.glob("*.json"))
        if event_id:
            files = [f for f in files if f.name.endswith(f"_{event_id}.json")]

        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return files

    def load_session(self, file_path: Path) -> Optional[EventSession]:
        """Load an event session from file."""
        if not file_path.exists():
            return None

        try:
            with open(file_path, "r") as f:
                data = json.load(f)
            deserialize_datetimes(data)
            return EventSession(**data)
        except Exception as e:
            print(f"Error loading event session {file_path}: {e}")
            return None

    def get_overall_stats(self, event: EventDefinition) -> Dict:
        """Lifetime totals for a single event across all saved sessions."""
        sessions = [s for s in self._load_all(event.event_id) if s is not None]

        prize = PrizeTotal()
        milestone_counts = {m.name: 0 for m in event.milestones}
        wins = 0
        losses = 0
        runs_played = 0

        for session in sessions:
            wins += session.total_wins()
            losses += session.total_losses()
            prize = prize + session.total_prize(event)
            runs_played += len(session.completed_runs())
            for name, count in session.milestone_counts(event).items():
                milestone_counts[name] += count

        return {
            "wins": wins,
            "losses": losses,
            "prize": prize,
            "milestone_counts": milestone_counts,
            "runs_played": runs_played,
        }

    def get_grand_total(self, catalog: Optional[List[EventDefinition]] = None) -> PrizeTotal:
        """Grand total prize across every event ever played."""
        if catalog is None:
            catalog = load_event_catalog(default_catalog_path())
        events_by_id = {e.event_id: e for e in catalog}

        total = PrizeTotal()
        for session in self._load_all():
            if session is None:
                continue
            event = events_by_id.get(session.event_id)
            if event is None:
                continue
            total = total + session.total_prize(event)
        return total

    def _load_all(self, event_id: Optional[str] = None) -> List[Optional[EventSession]]:
        return [self.load_session(f) for f in self.list_sessions(event_id=event_id)]


# Global event data manager instance
event_data_manager = EventDataManager()
