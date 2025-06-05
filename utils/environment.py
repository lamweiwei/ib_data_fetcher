"""
Environment-specific configuration loader for IB Data Fetcher.

This module provides functionality to load configuration based on the current
environment (dev/test/prod). It supports:
- Automatic environment detection
- Environment variable overrides
- Fallback to default configuration
- Validation of environment-specific settings

Key concepts for environment management:
- Different environments need different settings (timeouts, logging levels, etc.)
- Production should be more conservative and robust
- Development should prioritize fast feedback and debugging
- Testing should use minimal resources and predictable behavior
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
import logging


class EnvironmentConfigLoader:
    """
    Environment-aware configuration loader.
    
    This class handles loading configuration files based on the current environment.
    It provides a clean interface for getting environment-specific configurations
    while maintaining backward compatibility with the existing system.
    
    Environment detection priority:
    1. IBD_ENVIRONMENT environment variable
    2. ENVIRONMENT environment variable 
    3. Config file's development.environment setting
    4. Default to 'dev'
    """
    
    VALID_ENVIRONMENTS = {'dev', 'test', 'prod'}
    DEFAULT_ENVIRONMENT = 'dev'
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize the environment configuration loader.
        
        Args:
            config_dir: Directory containing configuration files. 
                       If None, uses default config/ directory.
        """
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        
        self.config_dir = Path(config_dir)
        self.logger = logging.getLogger(__name__)
        
    def detect_environment(self) -> str:
        """
        Detect the current environment.
        
        Returns:
            Environment string ('dev', 'test', or 'prod')
            
        Environment detection logic:
        1. Check IBD_ENVIRONMENT environment variable (specific to our app)
        2. Check ENVIRONMENT environment variable (general)
        3. Try to read from base settings file
        4. Default to 'dev' if nothing found
        """
        # First priority: specific environment variable
        env = os.getenv('IBD_ENVIRONMENT')
        if env and env.lower() in self.VALID_ENVIRONMENTS:
            self.logger.debug(f"Environment detected from IBD_ENVIRONMENT: {env}")
            return env.lower()
        
        # Second priority: general environment variable
        env = os.getenv('ENVIRONMENT') 
        if env and env.lower() in self.VALID_ENVIRONMENTS:
            self.logger.debug(f"Environment detected from ENVIRONMENT: {env}")
            return env.lower()
        
        # Third priority: read from base settings.yaml
        try:
            base_config_path = self.config_dir / "settings.yaml"
            if base_config_path.exists():
                with open(base_config_path, 'r') as f:
                    config = yaml.safe_load(f)
                    if config and 'development' in config:
                        env = config['development'].get('environment')
                        if env and env.lower() in self.VALID_ENVIRONMENTS:
                            self.logger.debug(f"Environment detected from settings.yaml: {env}")
                            return env.lower()
        except Exception as e:
            self.logger.warning(f"Could not read environment from settings.yaml: {e}")
        
        # Default fallback
        self.logger.debug(f"Using default environment: {self.DEFAULT_ENVIRONMENT}")
        return self.DEFAULT_ENVIRONMENT
    
    def get_config_path(self, environment: Optional[str] = None) -> Path:
        """
        Get the configuration file path for an environment.
        
        Args:
            environment: Environment name. If None, auto-detects.
            
        Returns:
            Path to the appropriate configuration file
        """
        if environment is None:
            environment = self.detect_environment()
        
        # Validate environment
        if environment not in self.VALID_ENVIRONMENTS:
            self.logger.warning(f"Invalid environment '{environment}', using default")
            environment = self.DEFAULT_ENVIRONMENT
        
        # Try environment-specific config first
        env_config_path = self.config_dir / f"settings-{environment}.yaml"
        if env_config_path.exists():
            return env_config_path
        
        # Fallback to base config
        base_config_path = self.config_dir / "settings.yaml"
        if base_config_path.exists():
            self.logger.warning(f"Environment-specific config not found, using base config")
            return base_config_path
        
        # This should not happen in normal operation
        raise FileNotFoundError(f"No configuration file found for environment '{environment}'")
    
    def load_config(self, environment: Optional[str] = None) -> Dict[str, Any]:
        """
        Load configuration for the specified environment.
        
        Args:
            environment: Environment name. If None, auto-detects.
            
        Returns:
            Configuration dictionary
            
        This method:
        1. Detects or uses the specified environment
        2. Loads the appropriate configuration file
        3. Applies any environment variable overrides
        4. Validates the configuration
        """
        if environment is None:
            environment = self.detect_environment()
        
        config_path = self.get_config_path(environment)
        
        self.logger.info(f"Loading configuration for environment '{environment}' from {config_path}")
        
        # Load base configuration
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Apply environment variable overrides
        config = self._apply_env_overrides(config)
        
        # Validate configuration
        self._validate_config(config, environment)
        
        return config
    
    def _apply_env_overrides(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply environment variable overrides to configuration.
        
        Args:
            config: Base configuration dictionary
            
        Returns:
            Configuration with environment variable overrides applied
            
        Supported environment variables:
        - IBD_HOST: Override connection.host
        - IBD_PORT: Override connection.port  
        - IBD_CLIENT_ID: Override connection.client_id
        - IBD_LOG_LEVEL: Override logging.level
        """
        # Connection overrides
        if os.getenv('IBD_HOST'):
            config.setdefault('connection', {})['host'] = os.getenv('IBD_HOST')
            self.logger.info(f"Overriding connection.host from environment")
        
        if os.getenv('IBD_PORT'):
            try:
                port = int(os.getenv('IBD_PORT'))
                config.setdefault('connection', {})['port'] = port
                self.logger.info(f"Overriding connection.port from environment")
            except ValueError:
                self.logger.warning("Invalid IBD_PORT value, ignoring")
        
        if os.getenv('IBD_CLIENT_ID'):
            try:
                client_id = int(os.getenv('IBD_CLIENT_ID'))
                config.setdefault('connection', {})['client_id'] = client_id
                self.logger.info(f"Overriding connection.client_id from environment")
            except ValueError:
                self.logger.warning("Invalid IBD_CLIENT_ID value, ignoring")
        
        # Logging overrides
        if os.getenv('IBD_LOG_LEVEL'):
            log_level = os.getenv('IBD_LOG_LEVEL').upper()
            if log_level in ['DEBUG', 'INFO', 'WARNING', 'ERROR']:
                config.setdefault('logging', {})['level'] = log_level
                self.logger.info(f"Overriding logging.level from environment")
            else:
                self.logger.warning("Invalid IBD_LOG_LEVEL value, ignoring")
        
        return config
    
    def _validate_config(self, config: Dict[str, Any], environment: str) -> None:
        """
        Validate configuration for the environment.
        
        Args:
            config: Configuration dictionary to validate
            environment: Environment name
            
        Raises:
            ValueError: If configuration is invalid for the environment
        """
        # Check if config is None or empty (from empty YAML files)
        if config is None:
            raise ValueError("Configuration is empty or could not be loaded")
        
        if not isinstance(config, dict):
            raise ValueError("Configuration must be a dictionary")
        
        # Basic validation - ensure required sections exist
        required_sections = ['connection', 'rate_limit', 'retry', 'data_fetching', 'validation', 'logging']
        
        for section in required_sections:
            if section not in config:
                raise ValueError(f"Missing required configuration section: {section}")
        
        # Environment-specific validation
        if environment == 'prod':
            # Production-specific validations
            if config.get('development', {}).get('mock_api_for_tests', False):
                self.logger.warning("Mock API enabled in production - this should be disabled")
            
            if config.get('logging', {}).get('level') == 'DEBUG':
                self.logger.warning("DEBUG logging in production - consider using INFO or WARNING")
        
        elif environment == 'test':
            # Test-specific validations
            if not config.get('development', {}).get('mock_api_for_tests', True):
                self.logger.info("Mock API disabled in test environment - ensure this is intentional")


def load_environment_config(environment: Optional[str] = None, 
                          config_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration for the specified environment.
    
    Args:
        environment: Environment name ('dev', 'test', 'prod'). If None, auto-detects.
        config_dir: Directory containing configuration files
        
    Returns:
        Configuration dictionary
        
    This is the main entry point for loading environment-specific configuration.
    It provides a simple interface for getting the right config based on environment.
    """
    loader = EnvironmentConfigLoader(config_dir)
    return loader.load_config(environment) 