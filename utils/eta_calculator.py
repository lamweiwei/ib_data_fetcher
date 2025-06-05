"""
ETA calculation utilities for the IB Data Fetcher.

This module provides ETA calculation for individual symbols and overall progress,
taking into account the 10-second rate limit and historical performance data.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

from utils.logging import get_logger


def format_duration(td: timedelta) -> str:
    """
    Format a timedelta to show only hours, minutes, and seconds (no days).
    
    Args:
        td: Timedelta to format
        
    Returns:
        Formatted string in HH:MM:SS format
    """
    if td is None:
        return "0:00:00"
    
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        return "0:00:00"
    
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    return f"{hours}:{minutes:02d}:{seconds:02d}"


@dataclass
class SymbolTiming:
    """Timing data for a symbol."""
    symbol: str
    start_time: datetime
    end_time: Optional[datetime]
    total_dates: int
    completed_dates: int
    error_dates: int
    avg_seconds_per_date: float
    
    @property
    def completion_rate(self) -> float:
        """Completion percentage for this symbol."""
        if self.total_dates == 0:
            return 100.0
        return (self.completed_dates / self.total_dates) * 100.0
    
    @property
    def estimated_remaining_time(self) -> timedelta:
        """Estimated time to complete this symbol."""
        remaining_dates = self.total_dates - self.completed_dates - self.error_dates
        if remaining_dates <= 0:
            return timedelta(0)
        
        # Account for 10-second rate limit + processing overhead
        estimated_seconds = remaining_dates * max(10.0, self.avg_seconds_per_date)
        return timedelta(seconds=estimated_seconds)


class ETACalculator:
    """Calculates ETA for symbol processing and overall progress."""
    
    def __init__(self):
        """Initialize the ETA calculator."""
        self.logger = get_logger(__name__)
        self.symbol_timings: Dict[str, SymbolTiming] = {}
        self.overall_start_time: Optional[datetime] = None
        self.completed_symbols: List[str] = []
        
    def start_overall_timing(self) -> None:
        """Start timing for the overall job."""
        self.overall_start_time = datetime.now(timezone.utc)
        
    def start_symbol_timing(self, symbol: str, total_dates: int) -> None:
        """
        Start timing for a specific symbol.
        
        Args:
            symbol: Symbol to track
            total_dates: Total number of dates to process for this symbol
        """
        self.symbol_timings[symbol] = SymbolTiming(
            symbol=symbol,
            start_time=datetime.now(timezone.utc),
            end_time=None,
            total_dates=total_dates,
            completed_dates=0,
            error_dates=0,
            avg_seconds_per_date=10.0  # Start with rate limit as baseline
        )
        
        self.logger.debug("Started timing for %s (%d dates)", symbol, total_dates)
    
    def update_symbol_progress(self, symbol: str, completed_dates: int, error_dates: int) -> None:
        """
        Update progress for a symbol.
        
        Args:
            symbol: Symbol to update
            completed_dates: Number of dates completed
            error_dates: Number of dates with errors
        """
        if symbol not in self.symbol_timings:
            self.logger.warning("No timing data for symbol %s", symbol)
            return
            
        timing = self.symbol_timings[symbol]
        timing.completed_dates = completed_dates
        timing.error_dates = error_dates
        
        # Calculate average time per date
        elapsed_time = (datetime.now(timezone.utc) - timing.start_time).total_seconds()
        processed_dates = completed_dates + error_dates
        
        if processed_dates > 0:
            timing.avg_seconds_per_date = elapsed_time / processed_dates
        
    def complete_symbol(self, symbol: str) -> None:
        """
        Mark a symbol as completed.
        
        Args:
            symbol: Symbol that was completed
        """
        if symbol in self.symbol_timings:
            self.symbol_timings[symbol].end_time = datetime.now(timezone.utc)
            
        if symbol not in self.completed_symbols:
            self.completed_symbols.append(symbol)
            
        self.logger.debug("Completed timing for %s", symbol)
    
    def get_symbol_eta(self, symbol: str) -> Optional[Tuple[timedelta, float]]:
        """
        Get ETA for a specific symbol.
        
        Args:
            symbol: Symbol to get ETA for
            
        Returns:
            Tuple of (estimated_remaining_time, completion_percentage) or None if not found
        """
        if symbol not in self.symbol_timings:
            return None
            
        timing = self.symbol_timings[symbol]
        return timing.estimated_remaining_time, timing.completion_rate
    
    def get_overall_eta(self, total_symbols: int, current_symbol_index: int) -> Dict:
        """
        Calculate overall ETA for all symbols.
        
        Args:
            total_symbols: Total number of symbols to process
            current_symbol_index: Index of current symbol (0-based)
            
        Returns:
            Dictionary with ETA information
        """
        if not self.overall_start_time:
            return {
                'error': 'Overall timing not started',
                'eta': None,
                'completion_percentage': 0.0
            }
        
        completed_count = len(self.completed_symbols)
        elapsed_time = datetime.now(timezone.utc) - self.overall_start_time
        
        # Calculate average time per completed symbol
        if completed_count > 0:
            avg_time_per_symbol = elapsed_time.total_seconds() / completed_count
        else:
            # Estimate based on current symbol progress if available
            current_symbol = None
            for symbol, timing in self.symbol_timings.items():
                if timing.end_time is None:  # Currently processing
                    current_symbol = symbol
                    break
            
            if current_symbol and self.symbol_timings[current_symbol].completed_dates > 0:
                # Estimate based on current symbol's average
                symbol_timing = self.symbol_timings[current_symbol]
                symbol_elapsed = (datetime.now(timezone.utc) - symbol_timing.start_time).total_seconds()
                progress_ratio = symbol_timing.completed_dates / symbol_timing.total_dates
                if progress_ratio > 0:
                    estimated_symbol_time = symbol_elapsed / progress_ratio
                    avg_time_per_symbol = estimated_symbol_time
                else:
                    avg_time_per_symbol = 3600  # 1 hour default estimate
            else:
                avg_time_per_symbol = 3600  # 1 hour default estimate
        
        # Calculate remaining time
        remaining_symbols = total_symbols - completed_count
        
        # Account for current symbol progress
        current_symbol_eta = timedelta(0)
        if current_symbol_index < total_symbols:
            current_symbol = None
            for symbol, timing in self.symbol_timings.items():
                if timing.end_time is None:  # Currently processing
                    current_symbol_eta = timing.estimated_remaining_time
                    break
        
        remaining_time_seconds = (remaining_symbols - 1) * avg_time_per_symbol + current_symbol_eta.total_seconds()
        estimated_completion = datetime.now(timezone.utc) + timedelta(seconds=remaining_time_seconds)
        
        completion_percentage = (completed_count / total_symbols) * 100.0
        
        return {
            'total_symbols': total_symbols,
            'completed_symbols': completed_count,
            'remaining_symbols': remaining_symbols,
            'completion_percentage': completion_percentage,
            'elapsed_time': format_duration(elapsed_time),
            'estimated_remaining_time': format_duration(timedelta(seconds=remaining_time_seconds)),
            'estimated_completion': estimated_completion.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'avg_time_per_symbol': f"{avg_time_per_symbol/60:.1f} minutes",
            'current_symbol_eta': format_duration(current_symbol_eta)
        }
    
    def get_performance_summary(self) -> Dict:
        """
        Get performance summary for completed symbols.
        
        Returns:
            Dictionary with performance metrics
        """
        if not self.completed_symbols:
            return {'message': 'No symbols completed yet'}
        
        completed_timings = [
            timing for symbol, timing in self.symbol_timings.items() 
            if symbol in self.completed_symbols and timing.end_time
        ]
        
        if not completed_timings:
            return {'message': 'No timing data for completed symbols'}
        
        # Calculate statistics
        total_dates = sum(timing.total_dates for timing in completed_timings)
        total_completed = sum(timing.completed_dates for timing in completed_timings)
        total_errors = sum(timing.error_dates for timing in completed_timings)
        
        processing_times = [
            (timing.end_time - timing.start_time).total_seconds() 
            for timing in completed_timings
        ]
        
        avg_processing_time = sum(processing_times) / len(processing_times)
        min_processing_time = min(processing_times)
        max_processing_time = max(processing_times)
        
        return {
            'completed_symbols': len(self.completed_symbols),
            'total_dates_processed': total_dates,
            'successful_dates': total_completed,
            'error_dates': total_errors,
            'success_rate': (total_completed / (total_completed + total_errors)) * 100.0 if (total_completed + total_errors) > 0 else 0.0,
            'avg_processing_time_minutes': avg_processing_time / 60.0,
            'min_processing_time_minutes': min_processing_time / 60.0,
            'max_processing_time_minutes': max_processing_time / 60.0,
            'fastest_symbol': min(completed_timings, key=lambda t: (t.end_time - t.start_time).total_seconds()).symbol,
            'slowest_symbol': max(completed_timings, key=lambda t: (t.end_time - t.start_time).total_seconds()).symbol
        } 