"""
Application state management with persistence.
"""

import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from ..config.settings import config_manager
from ..models.session import AppState, Session
from ..models.game import Game
from ..models.rank import Rank, FormatType


class StateManager:
    """Manages application state with automatic persistence."""

    def __init__(self):
        self._state: Optional[AppState] = None
        self._auto_save_enabled = True

    @property
    def state(self) -> AppState:
        """Get the current application state, loading if needed."""
        if self._state is None:
            self._state = self.load_state()
        return self._state

    def load_state(self) -> AppState:
        """Load application state from file or create new."""
        state_file = config_manager.config.get_state_file()

        if state_file.exists():
            try:
                with open(state_file, "r") as f:
                    data = json.load(f)

                # Convert datetime strings back to datetime objects
                self._deserialize_datetimes(data)

                state = AppState(**data)
                print(f"Loaded application state from {state_file}")

                # Check if we have an active session to resume
                if state.has_active_session():
                    duration = state.active_session.get_duration_minutes()
                    print(f"Resuming active session: {duration} minutes old")

                return state

            except Exception as e:
                print(f"Error loading state from {state_file}: {e}")
                print("Starting with fresh application state")

        return AppState()

    def save_state(self) -> None:
        """Save current application state to file."""
        if not self._auto_save_enabled or self._state is None:
            return

        state_file = config_manager.config.get_state_file()

        try:
            # Convert datetime objects to strings for JSON serialization
            data = self._state.dict()
            self._serialize_datetimes(data)

            # Ensure parent directory exists
            state_file.parent.mkdir(parents=True, exist_ok=True)

            with open(state_file, "w") as f:
                json.dump(data, f, indent=2, default=str)

            print(f"Application state saved to {state_file}")

        except Exception as e:
            print(f"Error saving state to {state_file}: {e}")

    def _serialize_datetimes(self, data: dict) -> None:
        """Convert datetime objects to ISO strings for JSON serialization."""
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, datetime):
                    data[key] = value.isoformat()
                elif isinstance(value, dict):
                    self._serialize_datetimes(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            self._serialize_datetimes(item)

    def _deserialize_datetimes(self, data: dict) -> None:
        """Convert ISO strings back to datetime objects."""
        datetime_fields = ["start_time", "end_time", "timestamp", "game_start_time"]

        if isinstance(data, dict):
            for key, value in data.items():
                if key in datetime_fields and isinstance(value, str):
                    try:
                        data[key] = datetime.fromisoformat(value)
                    except ValueError:
                        pass  # Keep as string if parsing fails
                elif isinstance(value, dict):
                    self._deserialize_datetimes(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            self._deserialize_datetimes(item)

    def start_session(self, format_type: FormatType, starting_rank: Rank) -> Session:
        """Start a new tracking session."""
        session = self.state.start_new_session(format_type, starting_rank)
        self.save_state()
        return session

    def end_session(self) -> Optional[Session]:
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

    def add_game(self, game: Game) -> bool:
        """Add a game to the current session."""
        if self.state.add_game_to_session(game):
            self.save_state()
            return True
        return False

    def update_live_game_state(self, **kwargs) -> None:
        """Update live game state."""
        self.state.update_live_game_state(**kwargs)
        # Don't auto-save for live updates (too frequent)

    def update_log_position(self, position: int, log_file: str) -> None:
        """Update the last processed log position."""
        self.state.last_log_position = position
        self.state.last_log_file = log_file
        # Don't auto-save for log position updates (too frequent)

    def save_session(self, session: Session) -> None:
        """Save a session to its own file."""
        sessions_dir = config_manager.config.get_sessions_dir()
        session_file = sessions_dir / session.get_session_filename()

        try:
            # Ensure sessions directory exists
            sessions_dir.mkdir(parents=True, exist_ok=True)

            # Convert to dict and serialize datetimes
            data = session.dict()
            self._serialize_datetimes(data)

            with open(session_file, "w") as f:
                json.dump(data, f, indent=2, default=str)

            print(f"Session saved to {session_file}")

        except Exception as e:
            print(f"Error saving session to {session_file}: {e}")

    def load_session(self, session_file: Path) -> Optional[Session]:
        """Load a session from file."""
        try:
            with open(session_file, "r") as f:
                data = json.load(f)

            self._deserialize_datetimes(data)
            return Session(**data)

        except Exception as e:
            print(f"Error loading session from {session_file}: {e}")
            return None

    def list_sessions(self) -> list[Path]:
        """List all saved session files."""
        sessions_dir = config_manager.config.get_sessions_dir()
        if sessions_dir.exists():
            return list(sessions_dir.glob("*.json"))
        return []

    def clear_state(self) -> None:
        """Clear application state (for testing or reset)."""
        self._state = AppState()
        self.save_state()

    def disable_auto_save(self) -> None:
        """Disable automatic state saving."""
        self._auto_save_enabled = False

    def enable_auto_save(self) -> None:
        """Enable automatic state saving."""
        self._auto_save_enabled = True
        self.save_state()  # Save current state immediately


# Global state manager instance
state_manager = StateManager()
