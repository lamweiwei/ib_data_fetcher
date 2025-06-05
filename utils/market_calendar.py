"""
Market Calendar Utilities for IB Data Fetcher.

This module provides market calendar functionality using pandas_market_calendars
to determine trading days, holidays, and expected bar counts for different market
conditions.

Key functionality:
- Determine if a date is a trading day
- Get expected bar counts for regular, early close, and holiday dates
- Market schedule validation
- Trading hours calculation

Why separate market calendar module?
- Clean separation of concerns from validation logic
- Reusable across different parts of the system
- Easier to test market calendar logic independently
- Centralized market calendar configuration
"""

import pandas as pd
import pandas_market_calendars as mcal
from datetime import datetime, date
from typing import Dict, Optional, Tuple
import pytz
from pathlib import Path

from utils.logging import get_logger
from dataclasses import dataclass
from enum import Enum
from utils.config_manager import get_config_manager


class MarketDayType(Enum):
    """Types of market days with their expected characteristics."""
    REGULAR_DAY = "regular_day"
    EARLY_CLOSE_SHORT = "early_close_short"  # 3.5 hours (210 bars)
    EARLY_CLOSE_REGULAR = "early_close_regular"  # 6 hours (360 bars)
    HOLIDAY = "holiday"


@dataclass
class MarketSchedule:
    """
    Market schedule information for a specific date.
    
    Contains all relevant information about a trading day including
    whether it's a trading day, the type of day, expected bar count,
    and actual market open/close times.
    """
    date: str
    is_trading_day: bool
    day_type: MarketDayType
    expected_bars: int
    market_open: Optional[pd.Timestamp] = None
    market_close: Optional[pd.Timestamp] = None
    trading_minutes: Optional[int] = None


class MarketCalendar:
    """
    Market calendar manager for determining trading schedules and bar expectations.
    
    This class provides a centralized interface for all market calendar operations,
    including determining trading days, calculating expected bar counts, and
    providing market schedule information.
    
    The class handles different types of market days:
    - Regular trading days: 9:30 AM - 4:00 PM ET (390 bars)
    - Early close days: Various shortened schedules (210 or 360 bars)
    - Market holidays: No trading (0 bars)
    """
    
    def __init__(self, exchange: str = "NYSE", environment: Optional[str] = None):
        """
        Initialize market calendar.
        
        Args:
            exchange: Exchange name for market calendar (default: NYSE)
            environment: Environment to use ('dev', 'test', 'prod'). If None, auto-detects.
        """
        self.logger = get_logger("ib_fetcher.market_calendar")
        self.exchange = exchange
        
        # Use centralized configuration manager
        config_manager = get_config_manager(environment)
        self.config = config_manager.load_config()
        
        # Get expected bars configuration
        self.expected_bars_config = self.config.get("validation", {}).get("expected_bars", {
            "regular_day": 390,
            "early_close": [360, 210],
            "holiday": 0
        })
        
        # Initialize market calendar
        try:
            self.market_calendar = mcal.get_calendar(exchange)
            self.logger.info(f"Market calendar initialized for {exchange}")
        except Exception as e:
            self.logger.error(f"Failed to initialize market calendar for {exchange}: {e}")
            self.market_calendar = None
    
    def get_market_schedule(self, date_str: str) -> MarketSchedule:
        """
        Get comprehensive market schedule information for a date.
        
        Args:
            date_str: Date string in YYYY-MM-DD format
            
        Returns:
            MarketSchedule object with all relevant information
            
        This is the main method for getting market information. It determines:
        - Whether the date is a trading day
        - What type of trading day it is
        - Expected bar count for the day
        - Actual market open/close times if available
        """
        if self.market_calendar is None:
            # Fallback when market calendar is not available
            return MarketSchedule(
                date=date_str,
                is_trading_day=True,  # Conservative assumption
                day_type=MarketDayType.REGULAR_DAY,
                expected_bars=self.expected_bars_config["regular_day"]
            )
        
        try:
            target_date = pd.to_datetime(date_str).date()
            
            # Get market schedule for the date
            schedule = self.market_calendar.schedule(
                start_date=target_date,
                end_date=target_date
            )
            
            if schedule.empty:
                # Holiday - no trading
                return MarketSchedule(
                    date=date_str,
                    is_trading_day=False,
                    day_type=MarketDayType.HOLIDAY,
                    expected_bars=self.expected_bars_config["holiday"]
                )
            
            # Trading day - get schedule details
            market_open = schedule.iloc[0]['market_open']
            market_close = schedule.iloc[0]['market_close']
            trading_minutes = int((market_close - market_open).total_seconds() / 60)
            
            # Determine day type and expected bars based on trading duration
            if trading_minutes <= 210:  # 3.5 hours or less
                day_type = MarketDayType.EARLY_CLOSE_SHORT
                expected_bars = 210
            elif trading_minutes <= 360:  # 6 hours or less
                day_type = MarketDayType.EARLY_CLOSE_REGULAR
                expected_bars = 360
            else:  # Regular trading day
                day_type = MarketDayType.REGULAR_DAY
                expected_bars = self.expected_bars_config["regular_day"]
            
            return MarketSchedule(
                date=date_str,
                is_trading_day=True,
                day_type=day_type,
                expected_bars=expected_bars,
                market_open=market_open,
                market_close=market_close,
                trading_minutes=trading_minutes
            )
            
        except Exception as e:
            self.logger.error(f"Error getting market schedule for {date_str}: {e}")
            # Return safe default
            return MarketSchedule(
                date=date_str,
                is_trading_day=True,
                day_type=MarketDayType.REGULAR_DAY,
                expected_bars=self.expected_bars_config["regular_day"]
            )
    
    def is_trading_day(self, date_str: str) -> bool:
        """
        Check if a date is a trading day.
        
        Args:
            date_str: Date string in YYYY-MM-DD format
            
        Returns:
            True if it's a trading day, False if holiday
        """
        schedule = self.get_market_schedule(date_str)
        return schedule.is_trading_day
    
    def get_expected_bar_count(self, date_str: str) -> int:
        """
        Get expected bar count for a specific date.
        
        Args:
            date_str: Date string in YYYY-MM-DD format
            
        Returns:
            Expected number of 1-minute bars for the date
        """
        schedule = self.get_market_schedule(date_str)
        return schedule.expected_bars
    
    def get_day_type(self, date_str: str) -> MarketDayType:
        """
        Get the type of market day.
        
        Args:
            date_str: Date string in YYYY-MM-DD format
            
        Returns:
            MarketDayType enum indicating the type of day
        """
        schedule = self.get_market_schedule(date_str)
        return schedule.day_type
    
    def validate_bar_count(self, date_str: str, actual_bars: int) -> bool:
        """
        Validate if actual bar count matches expected for the date.
        
        Args:
            date_str: Date string in YYYY-MM-DD format
            actual_bars: Actual number of bars received
            
        Returns:
            True if bar count is valid for the date
        """
        expected_bars = self.get_expected_bar_count(date_str)
        
        # Direct match
        if actual_bars == expected_bars:
            return True
        
        # Check if it matches any acceptable early close count
        early_close_counts = self.expected_bars_config.get("early_close", [360, 210])
        if isinstance(early_close_counts, list) and actual_bars in early_close_counts:
            return True
        
        return False

    def get_trading_dates(self, start_date, end_date):
        """
        Get list of trading dates between start_date and end_date.
        
        Args:
            start_date: Start date (datetime object)
            end_date: End date (datetime object)
            
        Returns:
            List of trading dates as datetime objects
        """
        if self.market_calendar is None:
            # Fallback: generate business days if market calendar unavailable
            date_range = pd.date_range(start_date, end_date, freq='B')  # Business days
            return [d.to_pydatetime().date() for d in date_range]
        
        try:
            # Get valid trading sessions for the date range
            valid_sessions = self.market_calendar.valid_days(start_date, end_date)
            # Convert to list of datetime.date objects (if they aren't already)
            trading_dates = []
            for d in valid_sessions:
                if hasattr(d, 'date'):
                    trading_dates.append(d.date())
                else:
                    trading_dates.append(d)
            return trading_dates
        except Exception as e:
            self.logger.error(f"Error getting trading dates from {start_date} to {end_date}: {e}")
            # Fallback to business days
            date_range = pd.date_range(start_date, end_date, freq='B')
            return [d.to_pydatetime().date() for d in date_range] 