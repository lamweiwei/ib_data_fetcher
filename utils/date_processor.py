"""
Date processing utilities for the IB Data Fetcher.

This module provides date processing functionality that was previously
embedded in core/fetcher_job.py, following the principle of keeping files under 300 lines
and avoiding code duplication.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple, Optional, TYPE_CHECKING

import pandas as pd

from utils.logging import get_logger
from utils.bar_status_manager import BarStatusManager, BarStatus, BarStatusRecord

if TYPE_CHECKING:
    from core.fetcher import IBDataFetcher
    from utils.market_calendar import MarketCalendar


class DateProcessor:
    """Handles date processing and data saving operations."""
    
    def __init__(
        self, 
        fetcher: 'IBDataFetcher',
        market_calendar: 'MarketCalendar',
        bar_status_manager: BarStatusManager,
        data_dir: Path
    ):
        """
        Initialize the date processor.
        
        Args:
            fetcher: The data fetcher instance
            market_calendar: The market calendar instance
            bar_status_manager: The bar status manager instance
            data_dir: Base data directory path
        """
        self.fetcher = fetcher
        self.market_calendar = market_calendar
        self.bar_status_manager = bar_status_manager
        self.data_dir = data_dir
        self.logger = get_logger(__name__)
    
    async def get_dates_to_process(self, symbol: str) -> List[datetime]:
        """
        Get list of dates that need to be processed for a symbol.
        
        Args:
            symbol: Symbol to get dates for
            
        Returns:
            List of dates to process (skips completed dates), sorted from newest to oldest
        """
        try:
            # Get the earliest available data date
            earliest_date = await self.fetcher.get_earliest_data_date(symbol)
            if not earliest_date:
                self.logger.warning("Could not determine earliest data date for %s", symbol)
                return []
            
            # Get all trading dates from earliest to yesterday
            yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
            trading_dates = self.market_calendar.get_trading_dates(earliest_date.date(), yesterday)
            
            # Load existing status records to skip completed dates
            completed_dates = self.bar_status_manager.get_completed_dates(symbol)
            
            # Filter out completed dates
            dates_to_process = []
            for date in trading_dates:
                if date not in completed_dates:
                    dates_to_process.append(datetime.combine(date, datetime.min.time()).replace(tzinfo=timezone.utc))
            
            # Sort from newest to oldest (per planning specifications)
            dates_to_process.sort(reverse=True)
            
            self.logger.info(
                "Symbol %s: %d total trading dates, %d completed, %d remaining to process",
                symbol, 
                len(trading_dates), 
                len(completed_dates), 
                len(dates_to_process)
            )
            
            return dates_to_process
            
        except Exception as e:
            self.logger.error("Error getting dates to process for %s: %s", symbol, e)
            return []
    
    async def process_date(self, symbol: str, date: datetime, shutdown_requested: bool = False) -> bool:
        """
        Process a single date for a symbol.
        
        Args:
            symbol: Symbol to process
            date: Date to process
            shutdown_requested: Whether shutdown has been requested
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.logger.debug("Processing %s for %s", date.strftime('%Y-%m-%d'), symbol)
            
            # Check for shutdown request
            if shutdown_requested:
                self.logger.info("Shutdown requested, stopping processing")
                return False
            
            # Attempt to fetch and validate data
            success, data_df, status = await self.fetcher.fetch_and_validate_day(symbol, date)
            
            if success and data_df is not None:
                # Save the data
                self.save_daily_data(symbol, date, data_df)
                
                # Record successful completion
                bar_count = len(data_df)
                last_timestamp = data_df.iloc[-1]['date'] if not data_df.empty else None
                expected_bars = self.market_calendar.get_expected_bar_count(date.strftime('%Y-%m-%d'))
                
                # Determine status based on bar count
                if bar_count == expected_bars:
                    final_status = BarStatus.COMPLETE
                elif bar_count > 0:
                    final_status = BarStatus.EARLY_CLOSE
                else:
                    final_status = BarStatus.HOLIDAY
                
                status_record = BarStatusRecord(
                    date=date,
                    status=final_status,
                    expected_bars=expected_bars,
                    actual_bars=bar_count,
                    last_timestamp=last_timestamp
                )
                
                self.bar_status_manager.update_bar_status(symbol, status_record)
                return True
            else:
                # Record error
                expected_bars = self.market_calendar.get_expected_bar_count(date.strftime('%Y-%m-%d'))
                status_record = BarStatusRecord(
                    date=date,
                    status=BarStatus.ERROR,
                    expected_bars=expected_bars,
                    actual_bars=0,
                    last_timestamp=None,
                    error_message=f"Fetch failed: {status}"
                )
                
                self.bar_status_manager.update_bar_status(symbol, status_record)
                return False
                
        except Exception as e:
            self.logger.error("Error processing %s for %s: %s", date.strftime('%Y-%m-%d'), symbol, e)
            
            # Record error
            expected_bars = self.market_calendar.get_expected_bar_count(date.strftime('%Y-%m-%d'))
            status_record = BarStatusRecord(
                date=date,
                status=BarStatus.ERROR,
                expected_bars=expected_bars,
                actual_bars=0,
                last_timestamp=None,
                error_message=str(e)
            )
            
            self.bar_status_manager.update_bar_status(symbol, status_record)
            return False
    
    def save_daily_data(self, symbol: str, date: datetime, data_df: pd.DataFrame) -> None:
        """
        Save daily data to CSV file.
        
        Args:
            symbol: Symbol
            date: Date of data
            data_df: DataFrame containing the data
        """
        try:
            # Ensure directory exists
            symbol_dir = self.data_dir / symbol / "raw"
            symbol_dir.mkdir(parents=True, exist_ok=True)
            
            file_path = symbol_dir / f"{date.strftime('%Y-%m-%d')}.csv"
            data_df.to_csv(file_path, index=False)
            self.logger.debug("Saved data for %s %s to %s", symbol, date.strftime('%Y-%m-%d'), file_path)
        except Exception as e:
            self.logger.error("Error saving data for %s %s: %s", symbol, date.strftime('%Y-%m-%d'), e)
            raise
    
    def create_symbol_directories(self, symbol: str) -> None:
        """
        Create necessary directories for a symbol.
        
        Args:
            symbol: Symbol to create directories for
        """
        try:
            symbol_dir = self.data_dir / symbol
            symbol_dir.mkdir(exist_ok=True)
            (symbol_dir / "raw").mkdir(exist_ok=True)
            self.logger.debug("Ensured directories exist for symbol %s", symbol)
        except Exception as e:
            self.logger.error("Error creating directories for symbol %s: %s", symbol, e)
            raise 