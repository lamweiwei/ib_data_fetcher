"""
Logging system for IB Data Fetcher.

This module provides a centralized logging system that handles all application logs.
It's designed to be production-ready with features like log rotation, structured
logging, and multiple log levels.

Key concepts for junior developers:
- Logging is crucial for debugging and monitoring production applications
- We use multiple log files for different purposes (daily operations, errors, etc.)
- Log rotation prevents log files from growing too large
- Structured logging makes it easier to parse logs programmatically
"""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional
import yaml
from datetime import datetime


class IBDataLogger:
    """
    Centralized logging system for IB Data Fetcher.
    
    This class creates and manages multiple loggers for different purposes:
    - Main application logger: General operations and info
    - Error logger: Only errors, saved separately for easy monitoring
    - Debug logger: Detailed debugging information
    - Summary logger: Daily summary reports
    
    Why use a class instead of just functions?
    - State management: We can store configuration and logger instances
    - Consistency: All loggers follow the same format and settings
    - Flexibility: Easy to modify behavior for all loggers at once
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize logging system.
        
        Args:
            config_path: Path to settings.yaml file. If None, uses default location.
            
        The initialization process:
        1. Load configuration from YAML file
        2. Create an empty dictionary to store logger instances
        3. Set up log directories (create them if they don't exist)
        4. Set up all the different loggers we need
        """
        # Load configuration first - we need this for logger setup
        self.config = self._load_config(config_path)
        
        # Dictionary to store our logger instances
        # This allows us to reuse the same logger instead of creating new ones
        self.loggers = {}
        
        # Set up directories and loggers
        self._setup_directories()
        self._setup_loggers()
    
    def _load_config(self, config_path: Optional[str]) -> dict:
        """
        Load configuration from settings.yaml.
        
        Args:
            config_path: Path to config file, or None for default
            
        Returns:
            Dictionary containing all configuration settings
            
        Why use YAML for configuration?
        - Human readable and editable
        - Supports complex data structures (lists, dictionaries)
        - Easy to parse in Python
        - Industry standard for configuration files
        """
        if config_path is None:
            # Build path relative to this file's location
            # __file__ gives us the path to this Python file
            # .parent.parent goes up two directories (utils -> project root)
            config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        
        # Open and parse the YAML file
        # Using 'with' ensures the file is properly closed even if an error occurs
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def _setup_directories(self):
        """
        Create logging directories if they don't exist.
        
        Why separate directories for different log types?
        - Organization: Easy to find specific types of logs
        - Permissions: Can set different access levels if needed
        - Monitoring: Can monitor specific directories for alerts
        - Cleanup: Can apply different retention policies to different log types
        """
        # Get the base logs directory relative to this file
        base_path = Path(__file__).parent.parent / "logs"
        
        # Create subdirectories for different log types
        for subdir in ["daily", "errors", "summary"]:
            dir_path = base_path / subdir
            # parents=True: Create parent directories if they don't exist
            # exist_ok=True: Don't raise error if directory already exists
            dir_path.mkdir(parents=True, exist_ok=True)
    
    def _setup_loggers(self):
        """
        Setup all required loggers with proper formatting and handlers.
        
        A "handler" in Python logging determines where log messages go
        (console, file, network, etc.). A "formatter" determines how
        the messages look.
        
        We create multiple loggers for different purposes:
        - Separation of concerns: Different types of messages go to different places
        - Filtering: Can set different log levels for different purposes
        - Monitoring: Can monitor error logs separately from general logs
        """
        # Get logging configuration from our loaded config
        log_config = self.config.get("logging", {})
        
        # Convert string log level to Python logging constant
        # getattr gets an attribute from an object by name
        # logging.INFO, logging.DEBUG, etc. are integer constants
        log_level_name = log_config.get("level", "INFO")
        try:
            level = getattr(logging, log_level_name)
        except AttributeError:
            # Invalid log level provided, fall back to INFO
            level = logging.INFO
            print(f"Warning: Invalid log level '{log_level_name}', using INFO instead")
        
        # Main application logger - for general operations
        # console=True means it also prints to console (terminal)
        self._create_logger(
            "ib_fetcher", 
            level, 
            "logs/daily/daily.log",
            console=True
        )
        
        # Error-specific logger - only for errors
        # console=False means it only goes to file, not terminal
        # We use ERROR level so only error messages get logged here
        self._create_logger(
            "ib_fetcher.errors",
            logging.ERROR,
            "logs/errors/error.log",
            console=True
        )
        
        # Debug logger - for detailed debugging information
        # Usually only enabled during development or troubleshooting
        self._create_logger(
            "ib_fetcher.debug",
            logging.DEBUG,
            "logs/daily/debug.log",
            console=True
        )
        
        # Summary logger - for daily summary reports
        # Helps track overall performance and statistics
        self._create_logger(
            "ib_fetcher.summary",
            logging.INFO,
            "logs/summary/summary.log",
            console=True
        )
    
    def _create_logger(self, name: str, level: int, file_path: str, console: bool = False):
        """
        Create a logger with file and optional console handlers.
        
        Args:
            name: Logger name (used to retrieve it later)
            level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            file_path: Where to save the log file
            console: Whether to also print to console/terminal
            
        This is the core method that actually creates each individual logger.
        Each logger can have multiple "handlers" - destinations for log messages.
        """
        # Get or create a logger with the specified name
        # If it already exists, this returns the existing one
        logger = logging.getLogger(name)
        logger.setLevel(level)
        
        # Clear any existing handlers to avoid duplicates
        # This is important if the logger was previously configured
        logger.handlers.clear()
        
        # Create a formatter that determines how log messages look
        # This gives us: "2024-03-20 10:30:45 | INFO | ib_fetcher | Starting data fetch"
        formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Create a rotating file handler
        # This automatically creates new log files when the current one gets too big
        log_config = self.config.get("logging", {})
        
        # Safely get max_size_mb with type conversion and validation
        max_size_mb = log_config.get("max_size_mb", 10)
        try:
            max_size_mb = int(max_size_mb)
        except (ValueError, TypeError):
            max_size_mb = 10  # Default fallback
        
        # Safely get backup_count with type conversion and validation  
        backup_count = log_config.get("backup_count", 5)
        try:
            backup_count = int(backup_count)
        except (ValueError, TypeError):
            backup_count = 5  # Default fallback
        
        file_handler = logging.handlers.RotatingFileHandler(
            file_path,
            # Convert MB to bytes for maxBytes parameter
            maxBytes=max_size_mb * 1024 * 1024,
            # Keep this many backup files (old logs)
            backupCount=backup_count
        )
        
        # Apply our formatter to the file handler
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        
        # Add the file handler to our logger
        logger.addHandler(file_handler)
        
        # Optionally add console handler for terminal output
        if console:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            console_handler.setLevel(level)
            logger.addHandler(console_handler)
        
        # Store the logger in our dictionary for later retrieval
        # This prevents creating duplicate loggers
        self.loggers[name] = logger
        
        # Prevent log messages from bubbling up to parent loggers
        # This avoids duplicate messages if parent loggers also have handlers
        logger.propagate = False
    
    def get_logger(self, name: str = "ib_fetcher") -> logging.Logger:
        """
        Get a logger by name.
        
        Args:
            name: Logger name (default: main application logger)
            
        Returns:
            Logger instance ready to use
            
        This is how other parts of the application get access to loggers.
        Instead of creating new loggers everywhere, we reuse the ones
        we configured here.
        """
        # Return the logger from our dictionary, or fall back to Python's built-in
        return self.loggers.get(name, logging.getLogger(name))


# Global logger instance
# Using a global variable ensures we only create one logger system
# for the entire application, which is more efficient and consistent
_logger_instance: Optional[IBDataLogger] = None


def get_logger(name: str = "ib_fetcher") -> logging.Logger:
    """
    Get the global logger instance.
    
    Args:
        name: Logger name
        
    Returns:
        Logger instance ready to use
        
    This is the main function other parts of the application should use
    to get a logger. It implements the "singleton" pattern - ensuring
    we only have one logger system for the entire application.
    
    Why use a singleton pattern for logging?
    - Consistency: All parts of the app use the same logger configuration
    - Efficiency: Don't create multiple logger systems
    - State: The logger system maintains state (configuration, handlers)
    """
    global _logger_instance
    
    # Create the logger system if it doesn't exist yet
    if _logger_instance is None:
        _logger_instance = IBDataLogger()
    
    # Return the requested logger
    return _logger_instance.get_logger(name)


def setup_logging(config_path: Optional[str] = None) -> IBDataLogger:
    """
    Setup the global logging system.
    
    Args:
        config_path: Path to settings.yaml file
        
    Returns:
        IBDataLogger instance
        
    This function is typically called once at application startup
    to initialize the logging system. It allows specifying a custom
    configuration file path if needed.
    
    Why have a separate setup function?
    - Explicit initialization: Clear when logging is set up
    - Configuration: Allows passing custom config path
    - Testing: Can set up different logging for tests
    """
    global _logger_instance
    _logger_instance = IBDataLogger(config_path)
    return _logger_instance 