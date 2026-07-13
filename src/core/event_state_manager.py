"""
Event-mode application state management with persistence, parallel to
StateManager but for event runs (win/loss-cap events like the Historic
Pauper Challenge) instead of the ranked ladder.
"""

import json
from pathlib import Path
from typing import Optional

from ..config.settings import config_manager
from ..models.event import EventAppState, EventDefinition, EventGame, EventRun, EventSession
from .serialization import deserialize_datetimes, serialize_datetimes


class EventStateManager:
    """Manages event-mode application state with automatic persistence."""

    def __init__(self):
        self._state: Optional[EventAppState] = None
        self._auto_save_enabled = True

    @property
    def state(self) -> EventAppState:
        """Get the current event app state, loading if needed."""
        if self._state is None:
            self._state = self.load_state()
        return self._state

    def load_state(self) -> EventAppState:
        """Load event app state from file or create new."""
        state_file = config_manager.config.get_event_state_file()

        if state_file.exists():
            try:
                with open(state_file, "r") as f:
                    data = json.load(f)
                deserialize_datetimes(data)
                return EventAppState(**data)
            except Exception as e:
                print(f"Error loading event state from {state_file}: {e}")
                print("Starting with fresh event state")

        return EventAppState()

    def save_state(self) -> None:
        """Save current event app state to file."""
        if not self._auto_save_enabled or self._state is None:
            return

        state_file = config_manager.config.get_event_state_file()

        try:
            data = self._state.dict()
            serialize_datetimes(data)
            state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(state_file, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            print(f"Error saving event state to {state_file}: {e}")

    def start_session(self, event_id: str) -> EventSession:
        """Start a new event tracking session."""
        session = self.state.start_new_session(event_id)
        self.save_state()
        return session

    def end_session(self) -> Optional[EventSession]:
        """End the current session and save it."""
        session = self.state.end_current_session()
        if session:
            self.save_session(session)
        self.save_state()
        return session

    def pause_session(self) -> None:
        """Pause the current session."""
        if self.state.active_session:
            self.state.active_session.pause_session()
            self.save_state()

    def resume_session(self) -> None:
        """Resume the current session."""
        if self.state.active_session:
            self.state.active_session.resume_session()
            self.save_state()

    def start_run(self, run: EventRun) -> bool:
        """Start a new run within the current session."""
        started = self.state.start_new_run(run)
        if started:
            self.save_state()
        return started

    def add_game(self, game: EventGame, event: EventDefinition) -> bool:
        """Add a game to the current run of the current session."""
        session = self.state.active_session
        if not session:
            return False
        run = session.current_run()
        if not run:
            return False
        added = run.add_game(game, event)
        if added:
            self.save_state()
        return added

    def save_session(self, session: EventSession) -> None:
        """Save a session to its own file."""
        events_dir = config_manager.config.get_events_dir()
        session_file = events_dir / f"{session.session_id}_{session.event_id}.json"

        try:
            events_dir.mkdir(parents=True, exist_ok=True)
            data = session.dict()
            serialize_datetimes(data)
            with open(session_file, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            print(f"Error saving event session to {session_file}: {e}")

    def load_session(self, session_file: Path) -> Optional[EventSession]:
        """Load a session from file."""
        try:
            with open(session_file, "r") as f:
                data = json.load(f)
            deserialize_datetimes(data)
            return EventSession(**data)
        except Exception as e:
            print(f"Error loading event session from {session_file}: {e}")
            return None

    def disable_auto_save(self) -> None:
        """Disable automatic state saving."""
        self._auto_save_enabled = False

    def enable_auto_save(self) -> None:
        """Enable automatic state saving."""
        self._auto_save_enabled = True
        self.save_state()


# Global event state manager instance
event_state_manager = EventStateManager()
