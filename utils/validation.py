"""
Data validation for IB Data Fetcher.

This module provides comprehensive data validation functionality for historical
bar data fetched from Interactive Brokers. It ensures data integrity and quality
before storage.

Key concepts for junior developers:
- Data validation is crucial for maintaining data quality in financial applications
- We validate both individual bars and complete datasets
- Market calendar integration ensures we validate against actual trading hours
- Different validation rules apply to different market conditions (regular, early close, holiday)

Why validate data?
- Financial data errors can be costly
- Early detection of data issues saves time in analysis
- Consistent validation rules ensure data reliability
- Proper validation helps identify API or connection issues
"""

import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional, Union, Tuple
from datetime import datetime, date
import pandas_market_calendars as mcal
import pytz

from utils.logging import get_logger
from utils.market_calendar import MarketCalendar
from utils.bar_validator import ValidationResult, BarValidator
from utils.config_manager import get_config_manager
from utils.base import ValidatorComponent

class DataValidator(ValidatorComponent):
    """
    Comprehensive data validation for IB historical bar data.
    
    This class handles all aspects of data validation:
    1. Individual bar validation (price relationships, volume checks)
    2. Dataset validation (bar counts, time sequences)
    3. Market calendar integration (trading hours, holidays)
    4. Data quality checks (missing values, zero prices)
    
    Inherits from ValidatorComponent which provides:
    - Automatic logger setup
    - Configuration loading
    - Environment handling
    - Common validation patterns
    """
    
    def __init__(self, environment: Optional[str] = None):
        """
        Initialize data validator.
        
        Args:
            environment: Environment to use ('dev', 'test', 'prod'). If None, auto-detects.
        """
        # Call parent constructor - this handles all the common setup:
        # - Logger initialization
        # - Config loading
        # - Validation configuration
        # - Expected bars setup
        super().__init__(environment)
        
        # Initialize components specific to data validation
        self.market_calendar = MarketCalendar(environment=environment)
        self.bar_validator = BarValidator()

    def validate_bar_data(self, bar_data: pd.DataFrame, symbol: str, date_str: str) -> ValidationResult:
        """
        Comprehensive validation of historical bar data.
        
        Args:
            bar_data: DataFrame containing OHLCV bar data
            symbol: Stock symbol for logging and context
            date_str: Date string (YYYY-MM-DD) for market calendar validation
            
        Returns:
            ValidationResult with detailed validation outcome
            
        This is the main validation method that orchestrates all validation checks:
        1. Basic data structure validation
        2. Individual bar validation (price/volume relationships)
        3. Time sequence validation
        4. Market calendar validation (expected bar count)
        5. Data quality checks
        """
        self.logger.info(f"Starting validation for {symbol} on {date_str}")
        
        try:
            # 1. Basic structure validation
            structure_result = self.bar_validator.validate_data_structure(bar_data)
            if not structure_result.is_valid:
                return structure_result
            
            # 2. Individual bar validation
            bar_result = self.bar_validator.validate_individual_bars(bar_data)
            if not bar_result.is_valid:
                return ValidationResult(
                    is_valid=False,
                    message=f"Bar validation failed: {bar_result.message}",
                    error_details=bar_result.error_details,
                    validated_bars=len(bar_data)
                )
            
            # 3. Time sequence validation
            time_result = self._validate_time_sequence(bar_data)
            if not time_result.is_valid:
                return ValidationResult(
                    is_valid=False,
                    message=f"Time sequence validation failed: {time_result.message}",
                    error_details=time_result.error_details,
                    validated_bars=len(bar_data)
                )
            
            # 4. Market calendar validation using dedicated module
            calendar_result = self._validate_market_calendar(bar_data, date_str)
            if not calendar_result.is_valid:
                return ValidationResult(
                    is_valid=False,
                    message=f"Market calendar validation failed: {calendar_result.message}",
                    error_details=calendar_result.error_details,
                    validated_bars=len(bar_data),
                    expected_bars=calendar_result.expected_bars
                )
            
            # 5. Data quality validation
            quality_result = self.bar_validator.validate_data_quality(bar_data)
            if not quality_result.is_valid:
                return ValidationResult(
                    is_valid=False,
                    message=f"Data quality validation failed: {quality_result.message}",
                    error_details=quality_result.error_details,
                    validated_bars=len(bar_data)
                )
            
            # All validations passed
            self.logger.info(f"All validations passed for {symbol} on {date_str}")
            return ValidationResult(
                is_valid=True,
                message="All validations passed",
                validated_bars=len(bar_data),
                expected_bars=calendar_result.expected_bars
            )
            
        except Exception as e:
            self.logger.error(f"Validation error for {symbol} on {date_str}: {e}")
            return ValidationResult(
                is_valid=False,
                message=f"Validation error: {str(e)}",
                error_details={"exception": str(e)},
                validated_bars=len(bar_data) if bar_data is not None else 0
            )
    
    
    
    def _validate_time_sequence(self, bar_data: pd.DataFrame) -> ValidationResult:
        """
        Validate time sequence and timestamps.
        
        Args:
            bar_data: DataFrame containing bar data with date column
            
        Returns:
            ValidationResult with validation outcome
            
        This method checks:
        - Timestamps are in proper sequence
        - No missing time intervals
        - Timestamps are within expected trading hours
        """
        try:
            # Convert date column to datetime if it's not already
            if not pd.api.types.is_datetime64_any_dtype(bar_data['date']):
                dates = pd.to_datetime(bar_data['date'])
            else:
                dates = bar_data['date']
            
            # Check for duplicate timestamps
            duplicates = dates.duplicated().sum()
            if duplicates > 0:
                return ValidationResult(
                    is_valid=False,
                    message=f"Found {duplicates} duplicate timestamps",
                    error_details={"duplicate_timestamps": duplicates}
                )
            
            # Check if timestamps are in ascending order
            if not dates.is_monotonic_increasing:
                return ValidationResult(
                    is_valid=False,
                    message="Timestamps are not in ascending order",
                    error_details={"issue": "non_sequential_timestamps"}
                )
            
            # Check for expected 1-minute intervals
            if len(dates) > 1:
                time_diffs = dates.diff().dropna()
                expected_diff = pd.Timedelta(minutes=1)
                
                # Allow for some tolerance in time differences (market gaps, etc.)
                irregular_intervals = (time_diffs != expected_diff).sum()
                if irregular_intervals > 0:
                    # This might be acceptable for market gaps, so we log it but don't fail
                    self.logger.warning(f"Found {irregular_intervals} irregular time intervals")
            
            return ValidationResult(
                is_valid=True,
                message="Time sequence validation passed"
            )
            
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                message=f"Time sequence validation error: {str(e)}",
                error_details={"exception": str(e)}
            )
    
    def _validate_market_calendar(self, bar_data: pd.DataFrame, date_str: str) -> ValidationResult:
        """
        Validate bar count against market calendar expectations.
        
        Args:
            bar_data: DataFrame containing bar data
            date_str: Date string (YYYY-MM-DD) for calendar lookup
            
        Returns:
            ValidationResult with validation outcome including expected bar count
            
        This method:
        - Determines if the date is a trading day, holiday, or early close
        - Calculates expected bar count based on market schedule
        - Validates actual bar count against expected count
        """
        try:
            # Use the new market calendar module
            schedule = self.market_calendar.get_market_schedule(date_str)
            actual_bars = len(bar_data)
            expected_bars = schedule.expected_bars
            
            # Validate bar count
            if actual_bars == expected_bars:
                return ValidationResult(
                    is_valid=True,
                    message=f"Bar count validation passed: {actual_bars} bars ({schedule.day_type.value})",
                    expected_bars=expected_bars
                )
            else:
                # Check if it matches any of the acceptable early close counts
                early_close_counts = self.expected_bars.get("early_close", [360, 210])
                if isinstance(early_close_counts, list) and actual_bars in early_close_counts:
                    return ValidationResult(
                        is_valid=True,
                        message=f"Bar count validation passed: {actual_bars} bars (early_close)",
                        expected_bars=actual_bars
                    )
                else:
                    return ValidationResult(
                        is_valid=False,
                        message=f"Bar count mismatch: expected {expected_bars}, got {actual_bars} ({schedule.day_type.value})",
                        error_details={
                            "expected_bars": expected_bars,
                            "actual_bars": actual_bars,
                            "market_type": schedule.day_type.value
                        },
                        expected_bars=expected_bars
                    )
        
        except Exception as e:
            self.logger.error(f"Market calendar validation error for {date_str}: {e}")
            return ValidationResult(
                is_valid=False,
                message=f"Market calendar validation error: {str(e)}",
                error_details={"exception": str(e)}
            )
    

    
    def get_expected_bar_count(self, date_str: str) -> int:
        """
        Get expected bar count for a specific date.
        
        Args:
            date_str: Date string (YYYY-MM-DD)
            
        Returns:
            Expected number of bars for the date
            
        This is a utility method that can be used by other parts of the system
        to determine expected bar counts without running full validation.
        """
        try:
            return self.market_calendar.get_expected_bar_count(date_str)
        except Exception as e:
            self.logger.error(f"Error calculating expected bar count for {date_str}: {e}")
            return self.expected_bars["regular_day"]
    
    def is_trading_day(self, date_str: str) -> bool:
        """
        Check if a date is a trading day.
        
        Args:
            date_str: Date string (YYYY-MM-DD)
            
        Returns:
            True if it's a trading day, False if holiday
            
        Utility method for determining if data should be expected for a given date.
        """
        try:
            return self.market_calendar.is_trading_day(date_str)
        except Exception as e:
            self.logger.error(f"Error checking trading day for {date_str}: {e}")
            return True  # Default to trading day if error 