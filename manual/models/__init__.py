"""
Models package for MTGA Manual TUI Tracker.

Contains all data models and enums used throughout the application.
"""

from .rank import FormatType, RankTier, ManualRank
from .session import CompletedSession, SessionStats
from .app_data import AppData
from .event import (
    EntryOption,
    EventDefinition,
    EventGame,
    EventGameResult,
    EventRun,
    EventRunStatus,
    EventStats,
    MilestoneDefinition,
    PrizeTier,
    PrizeTotal,
    default_catalog_path,
    load_event_catalog,
)
from .mwm import (
    MWMFormatDefinition,
    MWMGame,
    MWMGameResult,
    MWMStats,
    current_mwm_format,
    default_mwm_catalog_path,
    load_mwm_catalog,
)

__all__ = [
    'FormatType',
    'RankTier',
    'ManualRank',
    'CompletedSession',
    'SessionStats',
    'AppData',
    'EntryOption',
    'EventDefinition',
    'EventGame',
    'EventGameResult',
    'EventRun',
    'EventRunStatus',
    'EventStats',
    'MilestoneDefinition',
    'PrizeTier',
    'PrizeTotal',
    'default_catalog_path',
    'load_event_catalog',
    'MWMFormatDefinition',
    'MWMGame',
    'MWMGameResult',
    'MWMStats',
    'current_mwm_format',
    'default_mwm_catalog_path',
    'load_mwm_catalog',
]
