"""
Centralized error handling utilities for IB Data Fetcher.

This module provides consistent error handling patterns and utilities
across the application.
"""

import functools
import traceback
from typing import Type, Callable, Any, Optional, Union, Tuple
from enum import Enum

from utils.logging import get_logger


class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DataFetcherError(Exception):
    """Base exception class for data fetcher errors."""
    
    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.MEDIUM, 
                 details: Optional[dict] = None):
        super().__init__(message)
        self.severity = severity
        self.details = details or {}


class ConfigurationError(DataFetcherError):
    """Raised when configuration is invalid or missing."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, ErrorSeverity.CRITICAL, details)


class ConnectionError(DataFetcherError):
    """Raised when IB connection fails."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, ErrorSeverity.HIGH, details)


class ValidationError(DataFetcherError):
    """Raised when data validation fails."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, ErrorSeverity.MEDIUM, details)


class DataFetchError(DataFetcherError):
    """Raised when data fetching fails."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, ErrorSeverity.MEDIUM, details)


def handle_exceptions(
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception,
    default_return: Any = None,
    log_level: str = "ERROR",
    reraise: bool = False
):
    """
    Decorator to handle exceptions with logging and optional re-raising.
    
    Args:
        exceptions: Exception type(s) to catch
        default_return: Value to return if exception is caught
        log_level: Logging level for the exception
        reraise: Whether to re-raise the exception after logging
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                # Log the exception with context
                error_msg = f"Error in {func.__name__}: {str(e)}"
                
                if hasattr(e, 'details') and e.details:
                    error_msg += f" | Details: {e.details}"
                
                # Log with appropriate level
                log_method = getattr(logger, log_level.lower(), logger.error)
                log_method(error_msg)
                
                # Log traceback at debug level
                logger.debug(f"Traceback for {func.__name__}:\n{traceback.format_exc()}")
                
                if reraise:
                    raise
                
                return default_return
        
        return wrapper
    return decorator


def retry_on_exception(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception
):
    """
    Decorator to retry function on exception with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries (seconds)
        backoff_factor: Multiplier for delay after each retry
        exceptions: Exception type(s) to retry on
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            import asyncio
            
            logger = get_logger(func.__module__)
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(f"Function {func.__name__} failed after {max_retries} retries: {e}")
                        raise
                    
                    logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. "
                                 f"Retrying in {current_delay:.1f}s...")
                    
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff_factor
            
            raise last_exception
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            import time
            
            logger = get_logger(func.__module__)
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(f"Function {func.__name__} failed after {max_retries} retries: {e}")
                        raise
                    
                    logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. "
                                 f"Retrying in {current_delay:.1f}s...")
                    
                    time.sleep(current_delay)
                    current_delay *= backoff_factor
            
            raise last_exception
        
        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def log_function_call(include_args: bool = False, include_result: bool = False):
    """
    Decorator to log function calls with optional arguments and results.
    
    Args:
        include_args: Whether to log function arguments
        include_result: Whether to log function return value
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            
            # Log function entry
            log_msg = f"Calling {func.__name__}"
            if include_args:
                log_msg += f" with args={args}, kwargs={kwargs}"
            
            logger.debug(log_msg)
            
            try:
                result = func(*args, **kwargs)
                
                # Log successful completion
                log_msg = f"Completed {func.__name__}"
                if include_result:
                    log_msg += f" -> {result}"
                
                logger.debug(log_msg)
                
                return result
            
            except Exception as e:
                logger.error(f"Exception in {func.__name__}: {e}")
                raise
        
        return wrapper
    return decorator


class ErrorContext:
    """Context manager for enhanced error handling."""
    
    def __init__(self, operation: str, logger_name: Optional[str] = None):
        self.operation = operation
        self.logger = get_logger(logger_name or __name__)
    
    def __enter__(self):
        self.logger.debug(f"Starting operation: {self.operation}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.logger.debug(f"Completed operation: {self.operation}")
            return False
        
        # Log the exception with context
        self.logger.error(f"Operation '{self.operation}' failed: {exc_val}")
        self.logger.debug(f"Traceback:\n{traceback.format_exc()}")
        
        # Don't suppress the exception
        return False


def validate_type(value: Any, expected_type: Type, param_name: str) -> None:
    """
    Validate that a value is of the expected type.
    
    Args:
        value: Value to validate
        expected_type: Expected type
        param_name: Parameter name for error messages
        
    Raises:
        ValidationError: If type validation fails
    """
    if not isinstance(value, expected_type):
        raise ValidationError(
            f"Parameter '{param_name}' must be of type {expected_type.__name__}, "
            f"got {type(value).__name__}",
            details={'expected_type': expected_type.__name__, 'actual_type': type(value).__name__}
        )


def validate_not_none(value: Any, param_name: str) -> None:
    """
    Validate that a value is not None.
    
    Args:
        value: Value to validate
        param_name: Parameter name for error messages
        
    Raises:
        ValidationError: If value is None
    """
    if value is None:
        raise ValidationError(
            f"Parameter '{param_name}' cannot be None",
            details={'parameter': param_name}
        )


def safe_execute(func: Callable, *args, default=None, **kwargs) -> Any:
    """
    Safely execute a function, returning default on any exception.
    
    Args:
        func: Function to execute
        *args: Function arguments
        default: Default value to return on exception
        **kwargs: Function keyword arguments
        
    Returns:
        Function result or default value
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger = get_logger(__name__)
        logger.debug(f"Safe execution of {func.__name__} failed: {e}")
        return default 