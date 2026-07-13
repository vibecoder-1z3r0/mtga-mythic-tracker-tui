"""
Data persistence and session history management.
"""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, date

from ..config.settings import config_manager
from ..models.session import Session
from ..models.game import GameStats
from ..models.rank import FormatType


class DataManager:
    """Manages session data persistence and history."""

    def __init__(self):
        self.sessions_dir = config_manager.config.get_sessions_dir()
        self.logs_dir = config_manager.config.get_logs_dir()

    def save_session(self, session: Session) -> Path:
        """Save a session to file and return the file path."""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        filename = session.get_session_filename()
        file_path = self.sessions_dir / filename

        try:
            # Convert to dict and handle datetime serialization
            data = session.dict()
            self._serialize_datetimes(data)

            with open(file_path, "w") as f:
                json.dump(data, f, indent=2, default=str)

            print(f"Session saved: {file_path}")
            return file_path

        except Exception as e:
            print(f"Error saving session {filename}: {e}")
            raise

    def load_session(self, file_path: Path) -> Optional[Session]:
        """Load a session from file."""
        if not file_path.exists():
            return None

        try:
            with open(file_path, "r") as f:
                data = json.load(f)

            self._deserialize_datetimes(data)
            return Session(**data)

        except Exception as e:
            print(f"Error loading session {file_path}: {e}")
            return None

    def list_sessions(
        self,
        format_type: Optional[FormatType] = None,
        date_range: Optional[tuple] = None,
    ) -> List[Path]:
        """List session files with optional filtering."""
        if not self.sessions_dir.exists():
            return []

        session_files = list(self.sessions_dir.glob("*.json"))

        # Filter by format if specified
        if format_type:
            format_str = format_type.value.lower()
            session_files = [f for f in session_files if format_str in f.name]

        # Filter by date range if specified
        if date_range:
            start_date, end_date = date_range
            filtered_files = []

            for file_path in session_files:
                session_date = self._extract_date_from_filename(file_path.name)
                if session_date and start_date <= session_date <= end_date:
                    filtered_files.append(file_path)

            session_files = filtered_files

        # Sort by modification time (newest first)
        session_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return session_files

    def get_session_summary(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Get a summary of a session without loading the full data."""
        try:
            with open(file_path, "r") as f:
                data = json.load(f)

            # Extract key summary info
            summary = {
                "session_id": data.get("session_id"),
                "start_time": data.get("start_time"),
                "end_time": data.get("end_time"),
                "status": data.get("status"),
                "format_type": data.get("format_type"),
                "game_count": len(data.get("games", [])),
                "wins": data.get("stats", {}).get("wins", 0),
                "losses": data.get("stats", {}).get("losses", 0),
                "starting_rank": data.get("starting_rank", {}),
                "current_rank": data.get("current_rank", {}),
                "file_path": file_path,
            }

            return summary

        except Exception as e:
            print(f"Error reading session summary {file_path}: {e}")
            return None

    def get_recent_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get summaries of recent sessions."""
        session_files = self.list_sessions()
        summaries = []

        for file_path in session_files[:limit]:
            summary = self.get_session_summary(file_path)
            if summary:
                summaries.append(summary)

        return summaries

    def get_overall_stats(self) -> GameStats:
        """Calculate overall statistics across all sessions."""
        session_files = self.list_sessions()
        overall_stats = GameStats()

        for file_path in session_files:
            session = self.load_session(file_path)
            if session and session.games:
                for game in session.games:
                    overall_stats.update_with_game(game)

        return overall_stats

    def get_format_stats(self, format_type: FormatType) -> GameStats:
        """Get statistics for a specific format."""
        session_files = self.list_sessions(format_type=format_type)
        format_stats = GameStats()

        for file_path in session_files:
            session = self.load_session(file_path)
            if session and session.games:
                for game in session.games:
                    format_stats.update_with_game(game)

        return format_stats

    def get_daily_stats(self, target_date: date) -> Dict[str, Any]:
        """Get statistics for a specific day."""
        date_range = (target_date, target_date)
        session_files = self.list_sessions(date_range=date_range)

        daily_stats = GameStats()
        session_count = 0
        total_duration = 0

        for file_path in session_files:
            session = self.load_session(file_path)
            if session:
                session_count += 1
                total_duration += session.get_duration_minutes()

                for game in session.games:
                    daily_stats.update_with_game(game)

        return {
            "date": target_date,
            "sessions": session_count,
            "duration_minutes": total_duration,
            "stats": daily_stats,
        }

    def delete_session(self, file_path: Path) -> bool:
        """Delete a session file."""
        try:
            if file_path.exists():
                file_path.unlink()
                print(f"Deleted session: {file_path}")
                return True
            return False
        except Exception as e:
            print(f"Error deleting session {file_path}: {e}")
            return False

    def export_session_data(
        self,
        output_file: Path,
        format_type: Optional[FormatType] = None,
        date_range: Optional[tuple] = None,
    ) -> bool:
        """Export session data to a single file."""
        try:
            session_files = self.list_sessions(format_type, date_range)
            export_data = {
                "export_date": datetime.now().isoformat(),
                "filter_format": format_type.value if format_type else None,
                "filter_date_range": ([d.isoformat() for d in date_range] if date_range else None),
                "sessions": [],
            }

            for file_path in session_files:
                session = self.load_session(file_path)
                if session:
                    session_data = session.dict()
                    self._serialize_datetimes(session_data)
                    export_data["sessions"].append(session_data)

            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w") as f:
                json.dump(export_data, f, indent=2, default=str)

            print(f"Exported {len(export_data['sessions'])} sessions to {output_file}")
            return True

        except Exception as e:
            print(f"Error exporting session data: {e}")
            return False

    def copy_parsed_logs(self, source_content: str, session_id: str) -> Optional[Path]:
        """Save parsed log content for a session."""
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_filename = f"{timestamp}_{session_id}_parsed.log"
        log_path = self.logs_dir / log_filename

        try:
            with open(log_path, "w") as f:
                f.write(source_content)

            print(f"Parsed logs saved: {log_path}")
            return log_path

        except Exception as e:
            print(f"Error saving parsed logs: {e}")
            return None

    def _serialize_datetimes(self, data: Dict[str, Any]) -> None:
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

    def _deserialize_datetimes(self, data: Dict[str, Any]) -> None:
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

    def _extract_date_from_filename(self, filename: str) -> Optional[date]:
        """Extract date from session filename."""
        try:
            # Format: "2025-08-10_15-30-42_constructed.json"
            date_part = filename.split("_")[0]
            return datetime.strptime(date_part, "%Y-%m-%d").date()
        except (ValueError, IndexError):
            return None


# Global data manager instance
data_manager = DataManager()
