"""
Bar validation utilities for the IB Data Fetcher.

This module provides bar-level validation functionality that was previously
embedded in utils/validation.py, following the principle of keeping files under 300 lines
and avoiding code duplication.

This handles:
- Individual bar price/volume validation
- Data quality checks
- Basic data structure validation
"""

import pandas as pd
from typing import Dict, Optional
from dataclasses import dataclass

from utils.logging import get_logger


@dataclass
class ValidationResult:
    """
    Result of a validation operation.
    
    This class encapsulates the result of any validation check, providing
    both the success/failure status and detailed information about what
    was validated and any issues found.
    """
    is_valid: bool
    message: str
    error_details: Optional[Dict] = None
    validated_bars: Optional[int] = None
    expected_bars: Optional[int] = None


class BarValidator:
    """Handles individual bar and data quality validation."""
    
    def __init__(self):
        """Initialize the bar validator."""
        self.logger = get_logger("ib_fetcher.bar_validation")
    
    def validate_data_structure(self, bar_data: pd.DataFrame) -> ValidationResult:
        """
        Validate basic data structure and required columns.
        
        Args:
            bar_data: DataFrame containing bar data
            
        Returns:
            ValidationResult with validation outcome
        """
        # Check if DataFrame is empty
        if bar_data.empty:
            return ValidationResult(
                is_valid=True,  # Empty data might be valid for holidays
                message="Empty dataset (possible holiday)",
                validated_bars=0
            )
        
        # Check for required columns
        required_columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'barCount']
        missing_columns = [col for col in required_columns if col not in bar_data.columns]
        
        if missing_columns:
            return ValidationResult(
                is_valid=False,
                message=f"Missing required columns: {missing_columns}",
                error_details={"missing_columns": missing_columns}
            )
        
        # Check for basic data types
        numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'barCount']
        type_errors = []
        
        for col in numeric_columns:
            if not pd.api.types.is_numeric_dtype(bar_data[col]):
                type_errors.append(f"{col} is not numeric")
        
        if type_errors:
            return ValidationResult(
                is_valid=False,
                message=f"Data type errors: {'; '.join(type_errors)}",
                error_details={"type_errors": type_errors}
            )
        
        return ValidationResult(
            is_valid=True,
            message="Data structure validation passed",
            validated_bars=len(bar_data)
        )
    
    def validate_individual_bars(self, bar_data: pd.DataFrame) -> ValidationResult:
        """
        Validate individual bar price and volume relationships.
        
        Args:
            bar_data: DataFrame containing bar data
            
        Returns:
            ValidationResult with validation outcome
            
        This method implements the core bar validation rules:
        - Price relationship validation (High ≥ Open/Close, Low ≤ Open/Close)
        - No negative prices
        - Non-negative volume and barCount
        """
        if bar_data.empty:
            return ValidationResult(
                is_valid=True,
                message="No bars to validate",
                validated_bars=0
            )
        
        errors = []
        
        # Price relationship validation
        high_low_errors = (bar_data['high'] < bar_data['low']).sum()
        if high_low_errors > 0:
            errors.append(f"High < Low in {high_low_errors} bars")
        
        high_open_errors = (bar_data['high'] < bar_data['open']).sum()
        if high_open_errors > 0:
            errors.append(f"High < Open in {high_open_errors} bars")
        
        high_close_errors = (bar_data['high'] < bar_data['close']).sum()
        if high_close_errors > 0:
            errors.append(f"High < Close in {high_close_errors} bars")
        
        low_open_errors = (bar_data['low'] > bar_data['open']).sum()
        if low_open_errors > 0:
            errors.append(f"Low > Open in {low_open_errors} bars")
        
        low_close_errors = (bar_data['low'] > bar_data['close']).sum()
        if low_close_errors > 0:
            errors.append(f"Low > Close in {low_close_errors} bars")
        
        # Check for negative prices
        negative_prices = ((bar_data[['open', 'high', 'low', 'close']] < 0).any(axis=1)).sum()
        if negative_prices > 0:
            errors.append(f"Negative prices in {negative_prices} bars")
        
        # Check for zero prices (unusual but not necessarily invalid)
        zero_prices = ((bar_data[['open', 'high', 'low', 'close']] == 0).any(axis=1)).sum()
        if zero_prices > 0:
            # This is a warning, not an error, as zero prices might be valid in some cases
            self.logger.warning(f"Zero prices found in {zero_prices} bars")
        
        # Volume validation
        negative_volume = (bar_data['volume'] < 0).sum()
        if negative_volume > 0:
            errors.append(f"Negative volume in {negative_volume} bars")
        
        negative_bar_count = (bar_data['barCount'] < 0).sum()
        if negative_bar_count > 0:
            errors.append(f"Negative barCount in {negative_bar_count} bars")
        
        if errors:
            return ValidationResult(
                is_valid=False,
                message=f"Bar validation errors: {'; '.join(errors)}",
                error_details={"validation_errors": errors}
            )
        
        return ValidationResult(
            is_valid=True,
            message="Individual bar validation passed",
            validated_bars=len(bar_data)
        )
    
    def validate_data_quality(self, bar_data: pd.DataFrame) -> ValidationResult:
        """
        Validate data quality and completeness.
        
        Args:
            bar_data: DataFrame containing bar data
            
        Returns:
            ValidationResult with validation outcome
        """
        if bar_data.empty:
            return ValidationResult(
                is_valid=True,
                message="No data to validate quality",
                validated_bars=0
            )
        
        quality_issues = []
        
        # Check for missing values
        missing_data = bar_data.isnull().sum()
        for column, missing_count in missing_data.items():
            if missing_count > 0:
                quality_issues.append(f"{missing_count} missing values in {column}")
        
        # Check for extreme price movements (potential data errors)
        # Calculate bar-to-bar price changes
        if len(bar_data) > 1:
            close_prices = bar_data['close']
            price_changes = close_prices.pct_change().dropna()
            
            # Flag extreme movements (more than 50% in a single bar)
            extreme_moves = (abs(price_changes) > 0.5).sum()
            if extreme_moves > 0:
                quality_issues.append(f"{extreme_moves} bars with extreme price movements (>50%)")
        
        # Check for suspicious volume patterns
        if 'volume' in bar_data.columns:
            # Check for zero volume bars (suspicious but not always invalid)
            zero_volume_bars = (bar_data['volume'] == 0).sum()
            if zero_volume_bars > 0:
                self.logger.warning(f"Found {zero_volume_bars} bars with zero volume")
            
            # Check for extremely high volume bars compared to median
            if len(bar_data) > 10:  # Need sufficient data for meaningful comparison
                median_volume = bar_data['volume'].median()
                if median_volume > 0:
                    high_volume_bars = (bar_data['volume'] > median_volume * 100).sum()
                    if high_volume_bars > 0:
                        quality_issues.append(f"{high_volume_bars} bars with extremely high volume (>100x median)")
        
        # Check for identical consecutive bars (potential data duplication)
        if len(bar_data) > 1:
            price_cols = ['open', 'high', 'low', 'close']
            duplicate_bars = 0
            for i in range(1, len(bar_data)):
                if (bar_data.iloc[i][price_cols] == bar_data.iloc[i-1][price_cols]).all():
                    duplicate_bars += 1
            
            if duplicate_bars > 0:
                quality_issues.append(f"{duplicate_bars} bars with identical price data to previous bar")
        
        if quality_issues:
            # Data quality issues are warnings, not necessarily validation failures
            self.logger.warning(f"Data quality issues found: {'; '.join(quality_issues)}")
            
            # Only fail validation for critical issues (missing data)
            critical_issues = [issue for issue in quality_issues if "missing values" in issue]
            if critical_issues:
                return ValidationResult(
                    is_valid=False,
                    message=f"Critical data quality issues: {'; '.join(critical_issues)}",
                    error_details={"quality_issues": quality_issues}
                )
        
        return ValidationResult(
            is_valid=True,
            message="Data quality validation passed",
            validated_bars=len(bar_data)
        ) 