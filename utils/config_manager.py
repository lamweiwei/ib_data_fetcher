"""
Centralized configuration management for IB Data Fetcher.

This module provides a single point of configuration loading and management,
eliminating duplication across the codebase.
"""

from pathlib import Path
from typing import Dict, Optional, Any
import yaml
import os

from utils.logging import get_logger


class ConfigManager:
    """
    Centralized configuration manager for the application.
    
    Handles environment-aware configuration loading with proper fallbacks
    and validation.
    """
    
    def __init__(self, environment: Optional[str] = None, config_dir: Optional[Path] = None):
        """
        Initialize configuration manager.
        
        Args:
            environment: Target environment (dev/test/prod)
            config_dir: Directory containing config files
        """
        self.logger = get_logger(__name__)
        self.environment = environment or self._detect_environment()
        self.config_dir = config_dir or Path(__file__).parent.parent / "config"
        self._config: Optional[Dict[str, Any]] = None
    
    def _detect_environment(self) -> str:
        """
        Detect environment from environment variables or default to 'dev'.
        
        Priority:
        1. IBD_ENVIRONMENT
        2. ENVIRONMENT
        3. Default to 'dev'
        """
        return (
            os.environ.get('IBD_ENVIRONMENT') or
            os.environ.get('ENVIRONMENT') or
            'dev'
        )
    
    def load_config(self) -> Dict[str, Any]:
        """
        Load environment-specific configuration.
        
        Returns:
            Configuration dictionary
        """
        if self._config is not None:
            return self._config
        
        try:
            # Try environment-specific config first
            env_config_path = self.config_dir / f"settings-{self.environment}.yaml"
            if env_config_path.exists():
                with open(env_config_path, 'r') as f:
                    self._config = yaml.safe_load(f)
                self.logger.info(f"Loaded configuration from {env_config_path}")
            else:
                # Fallback to base config
                base_config_path = self.config_dir / "settings.yaml"
                with open(base_config_path, 'r') as f:
                    self._config = yaml.safe_load(f)
                self.logger.info(f"Loaded base configuration from {base_config_path}")
            
            # Apply environment variable overrides
            self._apply_env_overrides()
            
            return self._config
        
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            raise RuntimeError(f"Configuration loading failed: {e}")
    
    def _apply_env_overrides(self):
        """Apply environment variable overrides to configuration."""
        if not self._config:
            return
        
        # Environment variable mappings
        env_mappings = {
            'IBD_HOST': ['ib', 'host'],
            'IBD_PORT': ['ib', 'port'],
            'IBD_CLIENT_ID': ['ib', 'client_id']
        }
        
        for env_var, config_path in env_mappings.items():
            env_value = os.environ.get(env_var)
            if env_value:
                # Navigate to nested dict
                current = self._config
                for key in config_path[:-1]:
                    current = current.setdefault(key, {})
                
                # Set the value with proper type conversion
                final_key = config_path[-1]
                if final_key == 'port' or final_key == 'client_id':
                    current[final_key] = int(env_value)
                else:
                    current[final_key] = env_value
                
                self.logger.info(f"Applied environment override: {env_var} -> {'.'.join(config_path)}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by key.
        
        Args:
            key: Configuration key (supports dot notation like 'ib.host')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        config = self.load_config()
        
        # Support dot notation for nested keys
        keys = key.split('.')
        current = config
        
        try:
            for k in keys:
                current = current[k]
            return current
        except (KeyError, TypeError):
            return default
    
    @property
    def config(self) -> Dict[str, Any]:
        """Get the full configuration dictionary."""
        return self.load_config()


# Singleton instance for global access
_config_manager: Optional[ConfigManager] = None


def get_config_manager(environment: Optional[str] = None, config_dir: Optional[Path] = None) -> ConfigManager:
    """
    Get singleton configuration manager instance.
    
    Args:
        environment: Target environment (only used on first call)
        config_dir: Config directory (only used on first call)
        
    Returns:
        ConfigManager instance
    """
    global _config_manager
    
    if _config_manager is None:
        _config_manager = ConfigManager(environment, config_dir)
    
    return _config_manager


def load_config(environment: Optional[str] = None, config_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Convenience function to load configuration.
    
    Args:
        environment: Target environment
        config_dir: Config directory
        
    Returns:
        Configuration dictionary
    """
    return get_config_manager(environment, config_dir).load_config() 