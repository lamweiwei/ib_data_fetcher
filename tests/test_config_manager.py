"""
Unit tests for the configuration manager.
"""

import pytest
import tempfile
import yaml
import os
from pathlib import Path
from unittest.mock import patch, mock_open

from utils.config_manager import ConfigManager, get_config_manager, load_config


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory with test files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        config_dir = Path(temp_dir)
        
        # Create base config
        base_config = {
            'ib': {
                'host': 'localhost',
                'port': 7497,
                'client_id': 1
            },
            'logging': {
                'level': 'INFO'
            }
        }
        
        with open(config_dir / 'settings.yaml', 'w') as f:
            yaml.dump(base_config, f)
        
        # Create dev config
        dev_config = {
            'ib': {
                'host': 'dev-host',
                'port': 7498,
                'client_id': 2
            },
            'development': {
                'environment': 'dev'
            }
        }
        
        with open(config_dir / 'settings-dev.yaml', 'w') as f:
            yaml.dump(dev_config, f)
        
        yield config_dir


class TestConfigManager:
    """Test cases for ConfigManager class."""
    
    def test_init_with_environment(self, temp_config_dir):
        """Test initialization with specific environment."""
        manager = ConfigManager(environment='dev', config_dir=temp_config_dir)
        assert manager.environment == 'dev'
        assert manager.config_dir == temp_config_dir
    
    def test_init_without_environment(self, temp_config_dir):
        """Test initialization without environment (should auto-detect)."""
        with patch.dict(os.environ, {}, clear=True):
            manager = ConfigManager(config_dir=temp_config_dir)
            assert manager.environment == 'dev'  # default
    
    @patch.dict(os.environ, {'IBD_ENVIRONMENT': 'test'})
    def test_environment_detection_ibd_env(self):
        """Test environment detection from IBD_ENVIRONMENT."""
        manager = ConfigManager()
        assert manager.environment == 'test'
    
    @patch.dict(os.environ, {'ENVIRONMENT': 'prod'})
    def test_environment_detection_env(self):
        """Test environment detection from ENVIRONMENT."""
        manager = ConfigManager()
        assert manager.environment == 'prod'
    
    def test_load_environment_specific_config(self, temp_config_dir):
        """Test loading environment-specific config."""
        manager = ConfigManager(environment='dev', config_dir=temp_config_dir)
        config = manager.load_config()
        
        assert config['ib']['host'] == 'dev-host'
        assert config['ib']['port'] == 7498
        assert config['development']['environment'] == 'dev'
    
    def test_load_base_config_fallback(self, temp_config_dir):
        """Test fallback to base config when env-specific doesn't exist."""
        manager = ConfigManager(environment='prod', config_dir=temp_config_dir)
        config = manager.load_config()
        
        assert config['ib']['host'] == 'localhost'
        assert config['ib']['port'] == 7497
    
    @patch.dict(os.environ, {'IBD_HOST': 'override-host', 'IBD_PORT': '9999'})
    def test_environment_variable_overrides(self, temp_config_dir):
        """Test environment variable overrides."""
        manager = ConfigManager(environment='dev', config_dir=temp_config_dir)
        config = manager.load_config()
        
        assert config['ib']['host'] == 'override-host'
        assert config['ib']['port'] == 9999
    
    def test_get_with_dot_notation(self, temp_config_dir):
        """Test getting config values with dot notation."""
        manager = ConfigManager(environment='dev', config_dir=temp_config_dir)
        
        assert manager.get('ib.host') == 'dev-host'
        assert manager.get('ib.port') == 7498
        assert manager.get('nonexistent.key', 'default') == 'default'
    
    def test_config_property(self, temp_config_dir):
        """Test config property access."""
        manager = ConfigManager(environment='dev', config_dir=temp_config_dir)
        config = manager.config
        
        assert isinstance(config, dict)
        assert 'ib' in config
    
    def test_config_loading_error(self):
        """Test error handling when config file doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ConfigManager(config_dir=Path(temp_dir))
            
            with pytest.raises(RuntimeError, match="Configuration loading failed"):
                manager.load_config()
    
    def test_caching(self, temp_config_dir):
        """Test that config is cached after first load."""
        manager = ConfigManager(environment='dev', config_dir=temp_config_dir)
        
        # First load
        config1 = manager.load_config()
        
        # Second load should return cached version
        config2 = manager.load_config()
        
        assert config1 is config2


class TestGlobalFunctions:
    """Test global configuration functions."""
    
    def test_get_config_manager_singleton(self, temp_config_dir):
        """Test that get_config_manager returns singleton."""
        # Clear singleton
        import utils.config_manager
        utils.config_manager._config_manager = None
        
        manager1 = get_config_manager(environment='dev', config_dir=temp_config_dir)
        manager2 = get_config_manager()
        
        assert manager1 is manager2
    
    def test_load_config_convenience(self, temp_config_dir):
        """Test convenience function for loading config."""
        config = load_config(environment='dev', config_dir=temp_config_dir)
        
        assert isinstance(config, dict)
        assert 'ib' in config


@pytest.fixture(autouse=True)
def clear_singleton():
    """Clear singleton before each test."""
    import utils.config_manager
    utils.config_manager._config_manager = None
    yield
    utils.config_manager._config_manager = None 