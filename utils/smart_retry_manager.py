"""
Smart retry management for handling data fetching failures.

This module implements improved retry logic that distinguishes between
"no data available" and other types of errors, with specific handling
for consecutive no-data trading days.
"""

from datetime import datetime, date, timezone
from typing import Dict, Set, Optional, Tuple
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict

from utils.logging import get_logger


class FailureType(Enum):
    """Types of failures that can occur during data fetching."""
    NO_DATA = "no_data"              # IB returns no data for the date
    NETWORK_ERROR = "network_error"  # Connection or timeout issues
    API_ERROR = "api_error"          # IB API specific errors
    VALIDATION_ERROR = "validation_error"  # Data validation failures
    UNKNOWN = "unknown"              # Unclassified errors


@dataclass
class DateRetryInfo:
    """Retry information for a specific date."""
    date: date
    symbol: str
    retry_count: int = 0
    failure_type: Optional[FailureType] = None
    last_attempt: Optional[datetime] = None
    error_message: str = ""
    
    def can_retry(self, max_retries: int = 3) -> bool:
        """Check if this date can be retried."""
        return self.retry_count < max_retries


@dataclass 
class SymbolRetryState:
    """Retry state tracking for a symbol."""
    symbol: str
    consecutive_no_data_days: int = 0
    date_retries: Dict[date, DateRetryInfo] = field(default_factory=dict)
    should_skip: bool = False
    last_update: Optional[datetime] = None
    
    def get_no_data_streak(self) -> int:
        """Get current streak of consecutive no-data trading days."""
        return self.consecutive_no_data_days


class SmartRetryManager:
    """
    Manages intelligent retry logic for data fetching operations.
    
    Key improvements over simple consecutive failure counting:
    - Distinguishes between no-data vs other error types
    - Allows multiple retries per date (default: 3)
    - Only counts consecutive no-data trading days for skipping
    - Provides better visibility into retry patterns
    """
    
    def __init__(self, max_consecutive_no_data_days: int = 10, max_retries_per_date: int = 3):
        """
        Initialize the smart retry manager.
        
        Args:
            max_consecutive_no_data_days: Skip symbol after this many consecutive no-data days
            max_retries_per_date: Maximum retries per date before marking as failed
        """
        self.logger = get_logger(__name__)
        self.max_consecutive_no_data_days = max_consecutive_no_data_days
        self.max_retries_per_date = max_retries_per_date
        
        # Track retry state per symbol
        self.symbol_states: Dict[str, SymbolRetryState] = defaultdict(
            lambda: SymbolRetryState(symbol="")
        )
        
        self.logger.info(
            "SmartRetryManager initialized: max_no_data_days=%d, max_retries_per_date=%d",
            max_consecutive_no_data_days, max_retries_per_date
        )
    
    def classify_failure(self, error_message: str, data_received: bool = False) -> FailureType:
        """
        Classify the type of failure based on error message and context.
        
        Args:
            error_message: Error message from the failed request
            data_received: Whether any data was received (empty vs no response)
            
        Returns:
            FailureType enum value
        """
        error_lower = error_message.lower()
        
        # No data classification
        if not data_received or any(phrase in error_lower for phrase in [
            "no data", "empty", "zero bars", "no bars returned", 
            "no historical data", "data not available"
        ]):
            return FailureType.NO_DATA
        
        # Network/connection errors
        if any(phrase in error_lower for phrase in [
            "timeout", "connection", "network", "socket", "disconnected",
            "cannot connect", "connection lost", "timed out"
        ]):
            return FailureType.NETWORK_ERROR
        
        # API specific errors
        if any(phrase in error_lower for phrase in [
            "api error", "request limit", "rate limit", "invalid contract",
            "market data", "permission", "subscription"
        ]):
            return FailureType.API_ERROR
        
        # Data validation errors
        if any(phrase in error_lower for phrase in [
            "validation", "invalid data", "corrupt", "malformed",
            "unexpected format", "data quality"
        ]):
            return FailureType.VALIDATION_ERROR
        
        return FailureType.UNKNOWN
    
    def record_failure(self, symbol: str, target_date: date, error_message: str, 
                      data_received: bool = False) -> FailureType:
        """
        Record a failure for a specific symbol and date.
        
        Args:
            symbol: Symbol that failed
            target_date: Date that failed
            error_message: Error message from the failure
            data_received: Whether any data was received
            
        Returns:
            The classified failure type
        """
        failure_type = self.classify_failure(error_message, data_received)
        
        # Get or create symbol state
        if symbol not in self.symbol_states:
            self.symbol_states[symbol] = SymbolRetryState(symbol=symbol)
        
        state = self.symbol_states[symbol]
        state.last_update = datetime.now(timezone.utc)
        
        # Update date retry info
        if target_date not in state.date_retries:
            state.date_retries[target_date] = DateRetryInfo(
                date=target_date,
                symbol=symbol
            )
        
        retry_info = state.date_retries[target_date]
        retry_info.retry_count += 1
        retry_info.failure_type = failure_type
        retry_info.last_attempt = datetime.now(timezone.utc)
        retry_info.error_message = error_message
        
        # Update consecutive no-data tracking
        if failure_type == FailureType.NO_DATA:
            # Check if this extends a consecutive streak
            if retry_info.retry_count >= self.max_retries_per_date:
                # This date is now exhausted, increment consecutive no-data days
                state.consecutive_no_data_days += 1
                
                self.logger.warning(
                    "%s: Date %s exhausted after %d retries (no data) - consecutive no-data days: %d",
                    symbol, target_date, retry_info.retry_count, state.consecutive_no_data_days
                )
                
                # Check if we should skip this symbol
                if state.consecutive_no_data_days >= self.max_consecutive_no_data_days:
                    state.should_skip = True
                    self.logger.error(
                        "%s: Marking for skip after %d consecutive no-data days (limit: %d)",
                        symbol, state.consecutive_no_data_days, self.max_consecutive_no_data_days
                    )
        else:
            # Non-no-data failures don't count toward consecutive days
            # but we still track the retry attempts for the specific date
            self.logger.warning(
                "%s: Date %s failed with %s (attempt %d/%d) - not counting toward consecutive no-data",
                symbol, target_date, failure_type.value, 
                retry_info.retry_count, self.max_retries_per_date
            )
        
        return failure_type
    
    def record_success(self, symbol: str, target_date: date) -> None:
        """
        Record a successful fetch for a symbol and date.
        
        Args:
            symbol: Symbol that succeeded
            target_date: Date that succeeded
        """
        if symbol not in self.symbol_states:
            self.symbol_states[symbol] = SymbolRetryState(symbol=symbol)
        
        state = self.symbol_states[symbol]
        state.last_update = datetime.now(timezone.utc)
        
        # Reset consecutive no-data days on any success
        if state.consecutive_no_data_days > 0:
            self.logger.info(
                "%s: Success on %s resets consecutive no-data streak (was %d days)",
                symbol, target_date, state.consecutive_no_data_days
            )
            state.consecutive_no_data_days = 0
        
        # Remove from retry tracking if it was there
        if target_date in state.date_retries:
            del state.date_retries[target_date]
    
    def should_skip_symbol(self, symbol: str) -> bool:
        """
        Check if a symbol should be skipped due to too many consecutive no-data days.
        
        Args:
            symbol: Symbol to check
            
        Returns:
            True if symbol should be skipped
        """
        if symbol not in self.symbol_states:
            return False
        
        return self.symbol_states[symbol].should_skip
    
    def can_retry_date(self, symbol: str, target_date: date) -> bool:
        """
        Check if a specific date can be retried.
        
        Args:
            symbol: Symbol to check
            target_date: Date to check
            
        Returns:
            True if the date can be retried
        """
        if symbol not in self.symbol_states:
            return True  # No previous failures
        
        state = self.symbol_states[symbol]
        
        if target_date not in state.date_retries:
            return True  # No previous failures for this date
        
        retry_info = state.date_retries[target_date]
        return retry_info.can_retry(self.max_retries_per_date)
    
    def get_retry_info(self, symbol: str, target_date: date) -> Optional[DateRetryInfo]:
        """
        Get retry information for a specific symbol and date.
        
        Args:
            symbol: Symbol to check
            target_date: Date to check
            
        Returns:
            DateRetryInfo if available, None otherwise
        """
        if symbol not in self.symbol_states:
            return None
        
        state = self.symbol_states[symbol]
        return state.date_retries.get(target_date)
    
    def get_symbol_summary(self, symbol: str) -> Dict:
        """
        Get retry summary for a symbol.
        
        Args:
            symbol: Symbol to get summary for
            
        Returns:
            Dictionary with retry statistics
        """
        if symbol not in self.symbol_states:
            return {
                'symbol': symbol,
                'consecutive_no_data_days': 0,
                'should_skip': False,
                'total_failed_dates': 0,
                'retryable_dates': 0,
                'exhausted_dates': 0
            }
        
        state = self.symbol_states[symbol]
        
        retryable_dates = sum(
            1 for retry_info in state.date_retries.values()
            if retry_info.can_retry(self.max_retries_per_date)
        )
        
        exhausted_dates = len(state.date_retries) - retryable_dates
        
        return {
            'symbol': symbol,
            'consecutive_no_data_days': state.consecutive_no_data_days,
            'should_skip': state.should_skip,
            'total_failed_dates': len(state.date_retries),
            'retryable_dates': retryable_dates,
            'exhausted_dates': exhausted_dates,
            'last_update': state.last_update.isoformat() if state.last_update else None
        }
    
    def get_overall_summary(self) -> Dict:
        """
        Get overall retry statistics across all symbols.
        
        Returns:
            Dictionary with overall statistics
        """
        total_symbols = len(self.symbol_states)
        skipped_symbols = sum(1 for state in self.symbol_states.values() if state.should_skip)
        
        total_failed_dates = sum(len(state.date_retries) for state in self.symbol_states.values())
        
        no_data_failures = sum(
            1 for state in self.symbol_states.values()
            for retry_info in state.date_retries.values()
            if retry_info.failure_type == FailureType.NO_DATA
        )
        
        return {
            'total_symbols_tracked': total_symbols,
            'symbols_skipped': skipped_symbols,
            'total_failed_dates': total_failed_dates,
            'no_data_failures': no_data_failures,
            'network_failures': total_failed_dates - no_data_failures,  # Approximation
            'max_consecutive_no_data_days': self.max_consecutive_no_data_days,
            'max_retries_per_date': self.max_retries_per_date
        } 