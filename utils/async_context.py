"""
Generic async context manager utilities.

This module provides reusable async context manager patterns to eliminate
duplication across the codebase.
"""

from typing import TypeVar, Generic, Callable, Any, Optional
import asyncio

T = TypeVar('T')


class AsyncContextWrapper(Generic[T]):
    """
    Generic async context manager wrapper.
    
    This eliminates the duplication of identical async context manager patterns
    across multiple classes in the codebase.
    """
    
    def __init__(
        self, 
        wrapped_object: T,
        enter_method: Optional[str] = None,
        exit_method: Optional[str] = None,
        *args, **kwargs
    ):
        """
        Initialize the async wrapper.
        
        Args:
            wrapped_object: The object to wrap
            enter_method: Method name to call on enter (optional)
            exit_method: Method name to call on exit (optional)
            *args, **kwargs: Arguments to pass to the wrapped object constructor
        """
        self.wrapped_object = wrapped_object
        self.enter_method = enter_method
        self.exit_method = exit_method
    
    async def __aenter__(self) -> T:
        """Async enter - optionally call enter method on wrapped object."""
        if self.enter_method and hasattr(self.wrapped_object, self.enter_method):
            method = getattr(self.wrapped_object, self.enter_method)
            if asyncio.iscoroutinefunction(method):
                await method()
            else:
                method()
        return self.wrapped_object
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async exit - optionally call exit method on wrapped object."""
        if self.exit_method and hasattr(self.wrapped_object, self.exit_method):
            method = getattr(self.wrapped_object, self.exit_method)
            if asyncio.iscoroutinefunction(method):
                await method()
            else:
                method()


def create_async_wrapper(cls: type, enter_method: Optional[str] = None, exit_method: Optional[str] = None):
    """
    Factory function to create async wrapper classes.
    
    Args:
        cls: Class to wrap
        enter_method: Method name to call on enter
        exit_method: Method name to call on exit
        
    Returns:
        Async wrapper class
    """
    class AsyncWrapper:
        def __init__(self, *args, **kwargs):
            self.wrapped = cls(*args, **kwargs)
            self.enter_method = enter_method
            self.exit_method = exit_method
        
        async def __aenter__(self):
            if self.enter_method and hasattr(self.wrapped, self.enter_method):
                method = getattr(self.wrapped, self.enter_method)
                if asyncio.iscoroutinefunction(method):
                    await method()
                else:
                    method()
            return self.wrapped
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            if self.exit_method and hasattr(self.wrapped, self.exit_method):
                method = getattr(self.wrapped, self.exit_method)
                if asyncio.iscoroutinefunction(method):
                    await method()
                else:
                    method()
    
    return AsyncWrapper 