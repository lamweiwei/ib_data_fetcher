"""
Contract validation utilities for IB Data Fetcher.

This module contains validation logic extracted from the main ContractManager
to improve modularity and maintainability.
"""

from typing import List, Dict, Any
from functools import wraps
from utils.logging import get_logger


logger = get_logger(__name__)


def validate_fields(required_fields: List[str], sec_type: str):
    """
    Decorator to validate required fields before contract creation.
    
    Args:
        required_fields: List of required field names
        sec_type: Security type for error messages
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, ticker_data: Dict):
            # Validate required fields before calling the actual method
            validate_required_fields(ticker_data, required_fields, sec_type)
            return func(self, ticker_data)
        return wrapper
    return decorator


def validate_required_fields(ticker_data: Dict, required_fields: List[str], sec_type: str):
    """
    Validate that all required fields are present and not empty.
    
    Args:
        ticker_data: Dictionary containing ticker information
        required_fields: List of required field names
        sec_type: Security type for error messages
        
    Raises:
        ValueError: If any required field is missing or empty
    """
    missing_fields = []
    empty_fields = []
    
    for field in required_fields:
        if field not in ticker_data:
            missing_fields.append(field)
        elif not ticker_data[field] or str(ticker_data[field]).strip() == '':
            empty_fields.append(field)
    
    if missing_fields:
        raise ValueError(
            f"Missing required fields for {sec_type} contract: {missing_fields}. "
            f"Available fields: {list(ticker_data.keys())}"
        )
    
    if empty_fields:
        raise ValueError(
            f"Empty values in required fields for {sec_type} contract: {empty_fields}"
        )


def validate_ticker_format(tickers_df) -> None:
    """
    Validate ticker CSV format and required fields.
    
    Args:
        tickers_df: DataFrame containing ticker data
        
    Raises:
        ValueError: If validation fails with specific error message
    """
    if tickers_df is None:
        raise ValueError("No tickers loaded")
    
    # Define required columns that every ticker must have
    required_fields = ["symbol", "secType", "exchange", "currency"]
    
    # Check that all required columns exist in the CSV
    for field in required_fields:
        if field not in tickers_df.columns:
            raise ValueError(f"Required field '{field}' missing from tickers.csv")
    
    # Check for empty values in required fields
    for field in required_fields:
        if tickers_df[field].isna().any():
            raise ValueError(f"Empty values found in required field '{field}'")
    
    # Validate security types are supported
    supported_sec_types = {"STK", "FUT", "OPT"}
    unique_sec_types = set(tickers_df["secType"].unique())
    unsupported_types = unique_sec_types - supported_sec_types
    
    if unsupported_types:
        raise ValueError(
            f"Unsupported security types found: {unsupported_types}. "
            f"Supported types: {supported_sec_types}"
        )
    
    logger.info(f"Ticker validation passed: {len(tickers_df)} tickers, types: {unique_sec_types}")


def validate_security_type(sec_type: str) -> None:
    """
    Validate that security type is supported.
    
    Args:
        sec_type: Security type to validate
        
    Raises:
        ValueError: If security type is not supported
    """
    supported_types = {"STK", "FUT", "OPT"}
    if sec_type not in supported_types:
        raise ValueError(f"Unsupported security type: {sec_type}. Supported: {supported_types}")


def validate_numeric_field(value: Any, field_name: str, allow_none: bool = False) -> None:
    """
    Validate that a field contains a valid numeric value.
    
    Args:
        value: Value to validate
        field_name: Name of the field for error messages
        allow_none: Whether None/empty values are allowed
        
    Raises:
        ValueError: If value is not numeric when required
    """
    if allow_none and (value is None or str(value).strip() == ''):
        return
    
    try:
        float(value)
    except (ValueError, TypeError):
        raise ValueError(f"Field '{field_name}' must be numeric, got: {value}")


def validate_date_format(date_str: str, field_name: str) -> None:
    """
    Validate date format for futures and options.
    
    Args:
        date_str: Date string to validate
        field_name: Name of the field for error messages
        
    Raises:
        ValueError: If date format is invalid
    """
    if not date_str or str(date_str).strip() == '':
        raise ValueError(f"Field '{field_name}' cannot be empty")
    
    # IB accepts various date formats, but YYYYMMDD is most reliable
    date_str = str(date_str).strip()
    if len(date_str) != 8 or not date_str.isdigit():
        logger.warning(
            f"Date format '{date_str}' may not be optimal. "
            f"Consider using YYYYMMDD format for field '{field_name}'"
        ) 