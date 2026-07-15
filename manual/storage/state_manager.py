"""
State manager for MTGA Manual TUI Tracker.

Handles saving and loading application state to/from JSON files.
"""

import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import asdict, fields

from models import FormatType, RankTier, ManualRank, CompletedSession, SessionStats, AppData
from models import (
    EventGame,
    EventGameResult,
    EventRun,
    EventRunStatus,
    EventStats,
)


def _known_fields(cls, data: dict) -> dict:
    """Drop any keys in `data` that aren't real fields of dataclass `cls`.

    A renamed or removed field in a newer app version would otherwise
    raise TypeError on `cls(**data)`, which load_state()'s broad except
    catches by silently discarding the ENTIRE saved state (ranks,
    sessions, event history - everything), not just the one stale field.
    Dropping unknown keys here means old saves degrade gracefully (that
    one field resets to its default) instead of nuking the whole file.
    """
    valid = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in valid}


class StateManager:
    """Handles saving/loading application state."""
    
    def __init__(self, data_dir: Optional[Path] = None, save_enabled: bool = True):
        self.save_enabled = save_enabled
        
        if data_dir:
            self.data_dir = data_dir
        else:
            # Default location
            home = Path.home()
            if os.name == 'nt':  # Windows
                self.data_dir = home / "AppData" / "Roaming" / "mtga-manual-tracker"
            else:  # Linux/Mac
                self.data_dir = home / ".local" / "share" / "mtga-manual-tracker"
        
        if self.save_enabled:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.state_file = self.data_dir / "tracker_state.json"
    
    def load_state(self) -> AppData:
        """Load application state from file or create default."""
        if not self.save_enabled or not self.state_file.exists():
            return self._create_default_state()
        
        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)
            
            # Convert datetime strings back to objects
            self._deserialize_datetimes(data)
            self._deserialize_enums(data)
            
            # Migrate old format values to new BO1/BO3 system
            self._migrate_format_values(data)
            
            # Reconstruct objects
            constructed_rank = ManualRank(**_known_fields(ManualRank, data['constructed_rank']))
            limited_rank = ManualRank(**_known_fields(ManualRank, data['limited_rank']))

            # Handle SessionStats with potential missing fields
            stats_data = data['stats']

            # Reconstruct CompletedSession objects from session_history
            if 'session_history' in stats_data and stats_data['session_history']:
                session_history = []
                for session_dict in stats_data['session_history']:
                    session_history.append(CompletedSession(**_known_fields(CompletedSession, session_dict)))
                stats_data['session_history'] = session_history

            # Reconstruct ManualRank objects for season_start_rank and season_highest_rank
            if 'season_start_rank' in stats_data and isinstance(stats_data['season_start_rank'], dict):
                stats_data['season_start_rank'] = ManualRank(**_known_fields(ManualRank, stats_data['season_start_rank']))

            if 'season_highest_rank' in stats_data and isinstance(stats_data['season_highest_rank'], dict):
                stats_data['season_highest_rank'] = ManualRank(**_known_fields(ManualRank, stats_data['season_highest_rank']))

            stats = SessionStats(**_known_fields(SessionStats, stats_data))
            
            event_stats_data = data.get('event_stats')
            event_stats = (
                self._reconstruct_event_stats(event_stats_data) if event_stats_data else EventStats()
            )

            return AppData(
                constructed_rank=constructed_rank,
                limited_rank=limited_rank,
                current_format=FormatType(data['current_format']),
                stats=stats,
                show_mythic_progress=data.get('show_mythic_progress', True),
                collapsed_tiers=[RankTier(t) for t in data.get('collapsed_tiers', [])],
                hidden_tiers=[RankTier(t) for t in data.get('hidden_tiers', [])],
                auto_collapse_mode=data.get('auto_collapse_mode', False),
                auto_hide_mode=data.get('auto_hide_mode', False),
                event_stats=event_stats,
                view_mode=data.get('view_mode', 'ranked')
            )
            
        except Exception as e:
            print(f"Error loading state: {e}")
            self._backup_unreadable_state()
            return self._create_default_state()

    def _backup_unreadable_state(self) -> None:
        """Preserve a state file that failed to load by copying it aside,
        so a bug in reconstruction (e.g. a renamed field) makes the data
        need manual recovery instead of silently destroying it - the
        very next autosave would otherwise overwrite it with a blank
        default state within seconds."""
        try:
            if self.state_file.exists():
                backup_path = self.state_file.with_name(
                    f"tracker_state.corrupted-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                )
                shutil.copy2(self.state_file, backup_path)
                print(f"Backed up unreadable state to {backup_path}")
        except Exception:
            pass
    
    def save_state(self, app_data: AppData):
        """Save application state to file."""
        if not self.save_enabled:
            return
        
        try:
            # Convert to serializable format
            data = {
                'constructed_rank': asdict(app_data.constructed_rank),
                'limited_rank': asdict(app_data.limited_rank),
                'current_format': app_data.current_format.value,
                'stats': asdict(app_data.stats),
                'show_mythic_progress': app_data.show_mythic_progress,
                'collapsed_tiers': [t.value for t in app_data.collapsed_tiers],
                'hidden_tiers': [t.value for t in app_data.hidden_tiers],
                'auto_collapse_mode': app_data.auto_collapse_mode,
                'auto_hide_mode': app_data.auto_hide_mode,
                'event_stats': asdict(app_data.event_stats),
                'view_mode': app_data.view_mode
            }
            
            # Serialize datetime objects
            self._serialize_datetimes(data)
            self._serialize_enums(data)
            
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
                
        except Exception as e:
            print(f"Error saving state: {e}")
    
    def _create_default_state(self) -> AppData:
        """Create default application state."""
        default_date = datetime.now() + timedelta(days=30)  # 30 days from now
        
        return AppData(
            constructed_rank=ManualRank(
                tier=RankTier.BRONZE,
                division=4,
                pips=0,
                format_type=FormatType.CONSTRUCTED_BO1
            ),
            limited_rank=ManualRank(
                tier=RankTier.BRONZE,
                division=4, 
                pips=0,
                format_type=FormatType.LIMITED
            ),
            current_format=FormatType.CONSTRUCTED_BO1,
            stats=SessionStats(
                session_start_time=datetime.now(),
                season_end_date=default_date
            )
        )
    
    def _serialize_datetimes(self, data: dict):
        """Convert datetime objects to ISO strings for JSON serialization."""
        def convert_datetime(obj):
            if isinstance(obj, dict):
                return {k: convert_datetime(v) for k, v in obj.items()}
            elif isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, list):
                return [convert_datetime(item) for item in obj]
            else:
                return obj
        
        # Update the data in place
        for key, value in data.items():
            data[key] = convert_datetime(value)
    
    def _serialize_enums(self, data: dict):
        """Convert enum objects to string values for JSON serialization."""
        def convert_enum(obj):
            if isinstance(obj, dict):
                return {k: convert_enum(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_enum(item) for item in obj]
            elif hasattr(obj, 'value'):  # It's an enum
                return obj.value
            else:
                return obj
        
        # Update the data in place
        for key, value in data.items():
            data[key] = convert_enum(value)
    
    def _deserialize_datetimes(self, data: dict):
        """Convert ISO strings back to datetime objects."""
        datetime_fields = [
            'session_start_time', 'season_end_date', 'last_result_time',
            'pause_start_time', 'game_start_time',  # Timer datetime fields
            'start_time', 'end_time',  # For CompletedSession objects
            'timestamp'  # For game_notes timestamps
        ]
        
        def convert_iso_string(obj, parent_key=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    obj[k] = convert_iso_string(v, k)
                return obj
            elif isinstance(obj, str) and parent_key in datetime_fields:
                try:
                    return datetime.fromisoformat(obj)
                except:
                    return None
            return obj
        
        for key, value in data.items():
            data[key] = convert_iso_string(value, key)
    
    def _deserialize_enums(self, data: dict):
        """Convert string values back to enum objects."""
        # Handle session_goal_tier
        if 'session_goal_tier' in data and isinstance(data['session_goal_tier'], str):
            try:
                data['session_goal_tier'] = RankTier(data['session_goal_tier'])
            except (ValueError, TypeError):
                data['session_goal_tier'] = None
        
        # Handle current_format 
        if 'current_format' in data and isinstance(data['current_format'], str):
            try:
                data['current_format'] = FormatType(data['current_format'])
            except (ValueError, TypeError):
                data['current_format'] = FormatType.CONSTRUCTED_BO1
    
    def _migrate_format_values(self, data):
        """Migrate old format enum values to new BO1/BO3 system."""
        # Migrate current_format
        if data.get('current_format') == 'Constructed':
            data['current_format'] = 'Constructed BO1'

        # Migrate rank format_type fields
        for rank_key in ['constructed_rank', 'limited_rank']:
            if rank_key in data and 'format_type' in data[rank_key]:
                if data[rank_key]['format_type'] == 'Constructed':
                    data[rank_key]['format_type'] = 'Constructed BO1'

    def _reconstruct_event_game(self, game_dict: dict) -> EventGame:
        """Rebuild an EventGame from its serialized dict form."""
        game_dict = dict(game_dict)
        game_dict['result'] = EventGameResult(game_dict['result'])
        return EventGame(**_known_fields(EventGame, game_dict))

    def _reconstruct_event_run(self, run_dict: dict) -> EventRun:
        """Rebuild an EventRun (and its nested games) from serialized form."""
        run_dict = dict(run_dict)
        run_dict['games'] = [self._reconstruct_event_game(g) for g in run_dict.get('games', [])]
        run_dict['status'] = EventRunStatus(run_dict['status'])
        # entry_currency is now a plain free-form string (gold/gems/tokens),
        # no enum reconstruction needed.
        return EventRun(**_known_fields(EventRun, run_dict))

    def _reconstruct_event_stats(self, stats_dict: dict) -> EventStats:
        """Rebuild EventStats (and its nested runs) from serialized form."""
        stats_dict = dict(stats_dict)
        if stats_dict.get('current_run'):
            stats_dict['current_run'] = self._reconstruct_event_run(stats_dict['current_run'])
        stats_dict['recent_runs'] = [
            self._reconstruct_event_run(r) for r in stats_dict.get('recent_runs', [])
        ]
        return EventStats(**_known_fields(EventStats, stats_dict))