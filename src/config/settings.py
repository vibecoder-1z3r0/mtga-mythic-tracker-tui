"""
Configuration management for MTG Arena Tracker.
"""

import json
import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field, validator


class DirectoryConfig(BaseModel):
    """Directory configuration settings."""

    sessions: str = Field(default="sessions", description="Directory for session data files")
    logs: str = Field(default="logs", description="Directory for parsed MTGA logs")
    config: str = Field(default=".config/mtga-tracker", description="Configuration directory")


class MTGAConfig(BaseModel):
    """MTGA-specific configuration."""

    log_file_path: Optional[str] = Field(None, description="Path to MTGA log file")
    auto_detect_logs: bool = Field(True, description="Auto-detect MTGA log file location")
    watch_logs: bool = Field(True, description="Monitor log file for real-time updates")

    @validator("log_file_path")
    def validate_log_path(cls, v):
        """Validate log file path exists if provided."""
        if v and not os.path.exists(v):
            raise ValueError(f"MTGA log file not found: {v}")
        return v


class UIConfig(BaseModel):
    """User interface configuration."""

    theme: str = Field("dark", description="UI theme name")
    default_format: str = Field("Constructed", description="Default game format")
    show_live_game: bool = Field(True, description="Show live game state")
    auto_save_interval: int = Field(30, ge=5, description="Auto-save interval in seconds")
    demotion_threshold: int = Field(3, ge=2, le=5, description="Losses needed for demotion")


class TrackingConfig(BaseModel):
    """Game tracking configuration."""

    track_deck_names: bool = Field(True, description="Track player and opponent deck names")
    track_notes: bool = Field(True, description="Enable note-taking for games")
    auto_detect_decks: bool = Field(True, description="Auto-detect deck types from logs")
    common_decks: List[str] = Field(
        default_factory=lambda: [
            "Mono-Red Aggro",
            "Esper Control",
            "Grixis Midrange",
            "Domain Ramp",
            "Rakdos Midrange",
            "Azorius Control",
            "Selesnya Angels",
            "Dimir Control",
            "Temur Ramp",
        ],
        description="Common deck archetypes for quick selection",
    )


class Config(BaseModel):
    """Main configuration class."""

    directories: DirectoryConfig = Field(default_factory=DirectoryConfig)
    mtga: MTGAConfig = Field(default_factory=MTGAConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)

    def get_data_dir(self) -> Path:
        """Get the main data directory path."""
        home = Path.home()
        return home / self.directories.config

    def get_sessions_dir(self) -> Path:
        """Get the sessions directory path."""
        return self.get_data_dir() / self.directories.sessions

    def get_logs_dir(self) -> Path:
        """Get the logs directory path."""
        return self.get_data_dir() / self.directories.logs

    def get_config_file(self) -> Path:
        """Get the config file path."""
        return self.get_data_dir() / "config.json"

    def get_state_file(self) -> Path:
        """Get the application state file path."""
        return self.get_data_dir() / "state.json"

    def ensure_directories(self) -> None:
        """Create all required directories."""
        dirs_to_create = [
            self.get_data_dir(),
            self.get_sessions_dir(),
            self.get_logs_dir(),
        ]

        for directory in dirs_to_create:
            directory.mkdir(parents=True, exist_ok=True)


class ConfigManager:
    """Manages loading, saving, and updating configuration."""

    def __init__(self):
        self._config: Optional[Config] = None

    @property
    def config(self) -> Config:
        """Get the current configuration, loading if needed."""
        if self._config is None:
            self._config = self.load()
        return self._config

    def load(self) -> Config:
        """Load configuration from file or create default."""
        # Try to load from default location first
        config = Config()
        config_file = config.get_config_file()

        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    data = json.load(f)
                    config = Config(**data)
                    print(f"Loaded configuration from {config_file}")
            except Exception as e:
                print(f"Error loading config from {config_file}: {e}")
                print("Using default configuration")
        else:
            print("No configuration file found, using defaults")

        # Ensure directories exist
        config.ensure_directories()
        return config

    def save(self, config: Optional[Config] = None) -> None:
        """Save configuration to file."""
        if config is None:
            config = self.config

        config.ensure_directories()
        config_file = config.get_config_file()

        try:
            with open(config_file, "w") as f:
                json.dump(config.dict(), f, indent=2)
            print(f"Configuration saved to {config_file}")
        except Exception as e:
            print(f"Error saving config to {config_file}: {e}")

    def update(self, **kwargs) -> None:
        """Update configuration values and save."""
        config_dict = self.config.dict()

        # Update nested values using dot notation
        for key, value in kwargs.items():
            keys = key.split(".")
            current = config_dict

            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]

            current[keys[-1]] = value

        # Create new config and save
        self._config = Config(**config_dict)
        self.save()

    def reset_to_defaults(self) -> None:
        """Reset configuration to defaults."""
        self._config = Config()
        self.save()

    def get_mtga_log_paths(self) -> List[str]:
        """Get common MTGA log file locations."""
        common_paths = []

        if os.name == "nt":  # Windows
            appdata = os.environ.get("LOCALAPPDATA", "")
            if appdata:
                common_paths.extend(
                    [
                        os.path.join(appdata, "Temp", "MTGArena_Data", "Logs", "UTR_Data.log"),
                        os.path.join(
                            appdata,
                            "Programs",
                            "MTGArena",
                            "MTGArena_Data",
                            "Logs",
                            "UTR_Data.log",
                        ),
                    ]
                )
        else:  # macOS/Linux
            home = os.path.expanduser("~")
            common_paths.extend(
                [
                    os.path.join(home, "Library", "Logs", "MTGArena", "UTR_Data.log"),  # macOS
                    os.path.join(
                        home,
                        ".wine",
                        "drive_c",
                        "users",
                        os.getenv("USER", "user"),
                        "Local Settings",
                        "Application Data",
                        "Temp",
                        "MTGArena_Data",
                        "Logs",
                        "UTR_Data.log",
                    ),  # Wine
                ]
            )

        # Return existing paths only
        return [path for path in common_paths if os.path.exists(path)]


# Global config manager instance
config_manager = ConfigManager()
