#!/usr/bin/env python3
"""
Test script for configuration system.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from src.config.settings import Config, ConfigManager, MTGAConfig, UIConfig


def assert_raises_validation_error(fn) -> None:
    """Assert that calling fn() raises a pydantic ValidationError."""
    try:
        fn()
    except ValidationError:
        return
    raise AssertionError(f"Expected ValidationError from {fn!r}, none was raised")


def test_default_config():
    """Test default configuration creation and path generation."""
    config = Config()

    assert config.ui.theme == "dark"
    assert config.ui.default_format == "Constructed"
    assert config.ui.demotion_threshold == 3
    assert len(config.tracking.common_decks) == 9
    assert config.directories.sessions == "sessions"

    data_dir = config.get_data_dir()
    assert data_dir == Path.home() / config.directories.config
    assert config.get_sessions_dir() == data_dir / "sessions"
    assert config.get_logs_dir() == data_dir / "logs"
    assert config.get_config_file() == data_dir / "config.json"


def test_config_validation():
    """Test configuration validation."""
    ui_config = UIConfig(theme="dark", demotion_threshold=3)
    assert ui_config.theme == "dark"
    assert ui_config.demotion_threshold == 3

    # demotion_threshold has ge=2 constraint.
    assert_raises_validation_error(lambda: UIConfig(demotion_threshold=1))

    # log_file_path must exist on disk if provided.
    assert_raises_validation_error(lambda: MTGAConfig(log_file_path="/nonexistent/path.log"))


def test_config_manager():
    """Test configuration manager save/load round-trip, isolated to a temp home dir."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("pathlib.Path.home", return_value=Path(temp_dir)):
            test_config = Config()
            test_config.ui.theme = "light"
            test_config.ui.demotion_threshold = 4

            manager = ConfigManager()
            manager._config = test_config
            manager.save()

            config_file = test_config.get_config_file()
            assert config_file.exists()

            new_manager = ConfigManager()
            loaded_config = new_manager.load()
            assert loaded_config.ui.theme == "light"
            assert loaded_config.ui.demotion_threshold == 4


def test_config_updates():
    """Test in-memory configuration updates."""
    config = Config()
    assert config.ui.theme == "dark"
    assert config.ui.demotion_threshold == 3

    config.ui.theme = "custom"
    config.ui.demotion_threshold = 5
    assert config.ui.theme == "custom"
    assert config.ui.demotion_threshold == 5

    original_count = len(config.tracking.common_decks)
    config.tracking.common_decks.append("Custom Brew")
    assert len(config.tracking.common_decks) == original_count + 1
    assert config.tracking.common_decks[-1] == "Custom Brew"


def test_directory_creation():
    """Test directory creation, isolated to a temp home dir."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("pathlib.Path.home", return_value=Path(temp_dir)):
            config = Config()
            config.ensure_directories()

            assert config.get_data_dir().exists()
            assert config.get_sessions_dir().exists()
            assert config.get_logs_dir().exists()


def main():
    """Run all configuration tests."""
    test_default_config()
    test_config_validation()
    test_config_manager()
    test_config_updates()
    test_directory_creation()
    print("All configuration tests passed!")


if __name__ == "__main__":
    main()
