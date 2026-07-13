"""Shared datetime (de)serialization helpers for JSON persistence."""

from datetime import datetime
from typing import Any, Dict

DATETIME_FIELDS = ["start_time", "end_time", "timestamp", "game_start_time"]


def serialize_datetimes(data: Dict[str, Any]) -> None:
    """Convert datetime objects to ISO strings for JSON serialization, in place."""
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
            elif isinstance(value, dict):
                serialize_datetimes(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        serialize_datetimes(item)


def deserialize_datetimes(data: Dict[str, Any]) -> None:
    """Convert ISO strings back to datetime objects, in place."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key in DATETIME_FIELDS and isinstance(value, str):
                try:
                    data[key] = datetime.fromisoformat(value)
                except ValueError:
                    pass
            elif isinstance(value, dict):
                deserialize_datetimes(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        deserialize_datetimes(item)
