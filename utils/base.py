"""
Base classes for IB Data Fetcher components.

This module provides base classes that eliminate code duplication and provide
consistent interfaces across all components. Every component that needs
configuration, logging, or environment awareness should inherit from these bases.

Benefits:
- Eliminates 50+ lines of duplicate initialization code
- Provides consistent constructor signatures
- Single place to update common functionality
- Easier testing and debugging
"""

from abc import ABC
from pathlib import Path
from typing import Optional, Dict, Any
import asyncio

from utils.config_manager import get_config_manager
from utils.logging import get_logger


class ConfigurableComponent(ABC):
    """
    Base class for all components that need configuration and logging.
    
    This eliminates the repeated pattern of:
    - Logger initialization
    - Config manager setup
    - Environment handling
    - Configuration loading
    
    All components should inherit from this instead of duplicating the setup logic.
    """
    
    def __init__(self, environment: Optional[str] = None, config_dir: Optional[Path] = None):
        """
        Initialize the configurable component.
        
        Args:
            environment: Environment to use ('dev', 'test', 'prod'). If None, auto-detects.
            config_dir: Directory containing config files (optional)
        """
        # Setup logger using the actual class name (not base class)
        self.logger = get_logger(self.__class__.__module__)
        
        # Load configuration using centralized manager
        self.config_manager = get_config_manager(environment, config_dir)
        self.config = self.config_manager.load_config()
        self.environment = self.config_manager.environment
        
        # Log initialization
        self.logger.debug(
            "%s initialized with environment: %s", 
            self.__class__.__name__, 
            self.environment
        )
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value with dot notation support.
        
        Args:
            key: Configuration key (supports 'section.subsection.key')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        return self.config_manager.get(key, default)


class AsyncConfigurableComponent(ConfigurableComponent):
    """
    Base class for async components that need configuration and connection management.
    
    Extends ConfigurableComponent with async lifecycle management including:
    - Async initialization
    - Connection management
    - Graceful shutdown
    - Resource cleanup
    """
    
    def __init__(self, environment: Optional[str] = None, config_dir: Optional[Path] = None):
        """Initialize async configurable component."""
        super().__init__(environment, config_dir)
        self._is_initialized = False
        self._is_connected = False
        self._cleanup_tasks = []
    
    async def initialize(self) -> None:
        """
        Async initialization method.
        Override this in subclasses for async setup logic.
        """
        if self._is_initialized:
            self.logger.warning("%s already initialized", self.__class__.__name__)
            return
        
        self.logger.info("Initializing %s", self.__class__.__name__)
        await self._async_initialize()
        self._is_initialized = True
        self.logger.info("%s initialization complete", self.__class__.__name__)
    
    async def _async_initialize(self) -> None:
        """Override this method for specific async initialization logic."""
        pass
    
    async def connect(self) -> bool:
        """
        Establish connections.
        Override this in subclasses for connection logic.
        
        Returns:
            True if connection successful, False otherwise
        """
        if not self._is_initialized:
            await self.initialize()
        
        if self._is_connected:
            self.logger.debug("%s already connected", self.__class__.__name__)
            return True
        
        self.logger.info("Connecting %s", self.__class__.__name__)
        success = await self._async_connect()
        self._is_connected = success
        
        if success:
            self.logger.info("%s connected successfully", self.__class__.__name__)
        else:
            self.logger.error("%s connection failed", self.__class__.__name__)
        
        return success
    
    async def _async_connect(self) -> bool:
        """Override this method for specific connection logic."""
        return True
    
    async def disconnect(self) -> None:
        """
        Disconnect and cleanup resources.
        Override this in subclasses for cleanup logic.
        """
        if not self._is_connected:
            self.logger.debug("%s not connected, skipping disconnect", self.__class__.__name__)
            return
        
        self.logger.info("Disconnecting %s", self.__class__.__name__)
        
        # Cancel cleanup tasks
        for task in self._cleanup_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        await self._async_disconnect()
        self._is_connected = False
        self.logger.info("%s disconnected", self.__class__.__name__)
    
    async def _async_disconnect(self) -> None:
        """Override this method for specific disconnection logic."""
        pass
    
    @property
    def is_connected(self) -> bool:
        """Check if component is connected."""
        return self._is_connected
    
    @property
    def is_initialized(self) -> bool:
        """Check if component is initialized."""
        return self._is_initialized
    
    def add_cleanup_task(self, task: asyncio.Task) -> None:
        """Add a task to be cancelled during cleanup."""
        self._cleanup_tasks.append(task)
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()


class DataComponent(ConfigurableComponent):
    """
    Base class for components that handle data operations.
    
    Provides common functionality for:
    - Data directory management
    - File path resolution
    - Data validation patterns
    """
    
    def __init__(self, environment: Optional[str] = None, config_dir: Optional[Path] = None, data_dir: Optional[Path] = None):
        """
        Initialize data component.
        
        Args:
            environment: Environment to use
            config_dir: Configuration directory
            data_dir: Data directory (defaults to ./data)
        """
        super().__init__(environment, config_dir)
        self.data_dir = data_dir or Path("data")
        self.data_dir.mkdir(exist_ok=True)
        
        self.logger.debug("Data directory: %s", self.data_dir.absolute())
    
    def get_symbol_dir(self, symbol: str) -> Path:
        """Get directory path for a symbol."""
        return self.data_dir / symbol
    
    def ensure_symbol_dirs(self, symbol: str) -> None:
        """Ensure all necessary directories exist for a symbol."""
        symbol_dir = self.get_symbol_dir(symbol)
        symbol_dir.mkdir(exist_ok=True)
        (symbol_dir / "raw").mkdir(exist_ok=True)
    
    def get_data_file_path(self, symbol: str, date_str: str, subdir: str = "raw") -> Path:
        """Get file path for symbol data."""
        return self.get_symbol_dir(symbol) / subdir / f"{date_str}.csv"


class ValidatorComponent(ConfigurableComponent):
    """
    Base class for validation components.
    
    Provides common validation patterns and error handling.
    """
    
    def __init__(self, environment: Optional[str] = None, config_dir: Optional[Path] = None):
        """Initialize validator component."""
        super().__init__(environment, config_dir)
        
        # Get validation configuration
        self.validation_config = self.get_config_value("validation", {})
        self.expected_bars = self.validation_config.get("expected_bars", {
            "regular_day": 390,
            "early_close": [360, 210],
            "holiday": 0
        })
    
    def log_validation_result(self, result: bool, message: str, details: Optional[Dict] = None) -> None:
        """Log validation result with appropriate level."""
        if result:
            self.logger.info("✓ %s", message)
        else:
            self.logger.error("✗ %s", message)
            if details:
                self.logger.error("Details: %s", details) 