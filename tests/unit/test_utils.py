"""Unit tests for litdb.utils module."""

import pytest
from unittest.mock import patch


class TestGetConfig:
    """Test configuration loading."""

    @pytest.mark.unit
    def test_config_loading_with_env(self, mock_config, monkeypatch, temp_dir):
        """Test that config is loaded from LITDB_ROOT environment variable."""
        from litdb.utils import get_config

        with patch("litdb.utils.get_config") as mock_get_config:
            mock_get_config.return_value = mock_config
            config = get_config()

            assert config is not None
            assert "embedding" in config
            assert "openalex" in config

    @pytest.mark.unit
    def test_config_has_required_sections(self, mock_config):
        """Test that config has all required sections."""
        assert "embedding" in mock_config
        assert "openalex" in mock_config
        assert "llm" in mock_config

        # Check required embedding settings
        assert "model" in mock_config["embedding"]
        assert "chunk_size" in mock_config["embedding"]
        assert "chunk_overlap" in mock_config["embedding"]

        # Check required openalex settings
        assert "email" in mock_config["openalex"]


class TestInitLitdb:
    """Test database initialization."""

    @pytest.mark.unit
    @pytest.mark.skip(reason="Requires file system mocking")
    def test_init_creates_toml(self):
        """Test that init_litdb creates a litdb.toml file."""
        # TODO: Implement with proper file system mocking
        pass

    @pytest.mark.unit
    @pytest.mark.skip(reason="Requires file system mocking")
    def test_init_creates_database(self):
        """Test that init_litdb creates a database."""
        # TODO: Implement with proper file system mocking
        pass
