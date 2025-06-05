"""
Unit tests for contract validation utilities.
"""

import pytest
import pandas as pd
from unittest.mock import patch

from utils.contract_validators import (
    validate_fields,
    validate_required_fields,
    validate_ticker_format,
    validate_security_type,
    validate_numeric_field,
    validate_date_format
)


class TestValidateRequiredFields:
    """Test cases for validate_required_fields function."""
    
    def test_valid_data(self):
        """Test validation with valid data."""
        ticker_data = {
            'symbol': 'AAPL',
            'exchange': 'NASDAQ',
            'currency': 'USD'
        }
        required_fields = ['symbol', 'exchange', 'currency']
        
        # Should not raise any exception
        validate_required_fields(ticker_data, required_fields, 'STK')
    
    def test_missing_field(self):
        """Test validation with missing required field."""
        ticker_data = {
            'symbol': 'AAPL',
            'exchange': 'NASDAQ'
            # currency is missing
        }
        required_fields = ['symbol', 'exchange', 'currency']
        
        with pytest.raises(ValueError, match="Missing required fields for STK"):
            validate_required_fields(ticker_data, required_fields, 'STK')
    
    def test_empty_field(self):
        """Test validation with empty field."""
        ticker_data = {
            'symbol': 'AAPL',
            'exchange': '',
            'currency': 'USD'
        }
        required_fields = ['symbol', 'exchange', 'currency']
        
        with pytest.raises(ValueError, match="Empty values in required fields for STK"):
            validate_required_fields(ticker_data, required_fields, 'STK')
    
    def test_whitespace_only_field(self):
        """Test validation with whitespace-only field."""
        ticker_data = {
            'symbol': 'AAPL',
            'exchange': '   ',
            'currency': 'USD'
        }
        required_fields = ['symbol', 'exchange', 'currency']
        
        with pytest.raises(ValueError, match="Empty values in required fields for STK"):
            validate_required_fields(ticker_data, required_fields, 'STK')


class TestValidateTickerFormat:
    """Test cases for validate_ticker_format function."""
    
    def test_valid_dataframe(self):
        """Test validation with valid DataFrame."""
        df = pd.DataFrame({
            'symbol': ['AAPL', 'MSFT'],
            'secType': ['STK', 'STK'],
            'exchange': ['NASDAQ', 'NASDAQ'],
            'currency': ['USD', 'USD']
        })
        
        # Should not raise any exception
        validate_ticker_format(df)
    
    def test_none_dataframe(self):
        """Test validation with None DataFrame."""
        with pytest.raises(ValueError, match="No tickers loaded"):
            validate_ticker_format(None)
    
    def test_missing_required_column(self):
        """Test validation with missing required column."""
        df = pd.DataFrame({
            'symbol': ['AAPL', 'MSFT'],
            'secType': ['STK', 'STK'],
            'exchange': ['NASDAQ', 'NASDAQ']
            # currency column is missing
        })
        
        with pytest.raises(ValueError, match="Required field 'currency' missing"):
            validate_ticker_format(df)
    
    def test_empty_values_in_required_field(self):
        """Test validation with empty values in required field."""
        df = pd.DataFrame({
            'symbol': ['AAPL', None],
            'secType': ['STK', 'STK'],
            'exchange': ['NASDAQ', 'NASDAQ'],
            'currency': ['USD', 'USD']
        })
        
        with pytest.raises(ValueError, match="Empty values found in required field 'symbol'"):
            validate_ticker_format(df)
    
    def test_unsupported_security_type(self):
        """Test validation with unsupported security type."""
        df = pd.DataFrame({
            'symbol': ['AAPL', 'MSFT'],
            'secType': ['STK', 'BOND'],  # BOND is not supported
            'exchange': ['NASDAQ', 'NASDAQ'],
            'currency': ['USD', 'USD']
        })
        
        with pytest.raises(ValueError, match="Unsupported security types found"):
            validate_ticker_format(df)


class TestValidateSecurityType:
    """Test cases for validate_security_type function."""
    
    def test_valid_security_types(self):
        """Test validation with valid security types."""
        for sec_type in ['STK', 'FUT', 'OPT']:
            validate_security_type(sec_type)  # Should not raise
    
    def test_invalid_security_type(self):
        """Test validation with invalid security type."""
        with pytest.raises(ValueError, match="Unsupported security type: BOND"):
            validate_security_type('BOND')


class TestValidateNumericField:
    """Test cases for validate_numeric_field function."""
    
    def test_valid_numeric_values(self):
        """Test validation with valid numeric values."""
        for value in [1, 1.5, '2', '3.14', '0']:
            validate_numeric_field(value, 'test_field')  # Should not raise
    
    def test_invalid_numeric_values(self):
        """Test validation with invalid numeric values."""
        with pytest.raises(ValueError, match="Field 'test_field' must be numeric"):
            validate_numeric_field('abc', 'test_field')
    
    def test_none_value_not_allowed(self):
        """Test validation with None when not allowed."""
        with pytest.raises(ValueError, match="Field 'test_field' must be numeric"):
            validate_numeric_field(None, 'test_field', allow_none=False)
    
    def test_none_value_allowed(self):
        """Test validation with None when allowed."""
        validate_numeric_field(None, 'test_field', allow_none=True)  # Should not raise
    
    def test_empty_string_allowed(self):
        """Test validation with empty string when None allowed."""
        validate_numeric_field('', 'test_field', allow_none=True)  # Should not raise
        validate_numeric_field('   ', 'test_field', allow_none=True)  # Should not raise


class TestValidateDateFormat:
    """Test cases for validate_date_format function."""
    
    def test_valid_date_format(self):
        """Test validation with valid date format."""
        validate_date_format('20241220', 'expiry_date')  # Should not raise
    
    def test_empty_date(self):
        """Test validation with empty date."""
        with pytest.raises(ValueError, match="Field 'expiry_date' cannot be empty"):
            validate_date_format('', 'expiry_date')
    
    def test_none_date(self):
        """Test validation with None date."""
        with pytest.raises(ValueError, match="Field 'expiry_date' cannot be empty"):
            validate_date_format(None, 'expiry_date')
    
    @patch('utils.contract_validators.logger')
    def test_suboptimal_date_format_warning(self, mock_logger):
        """Test warning for suboptimal date format."""
        validate_date_format('2024-12-20', 'expiry_date')
        mock_logger.warning.assert_called_once()
        assert "may not be optimal" in mock_logger.warning.call_args[0][0]


class TestValidateFieldsDecorator:
    """Test cases for validate_fields decorator."""
    
    def test_decorator_success(self):
        """Test decorator with valid data."""
        @validate_fields(['symbol', 'exchange'], 'STK')
        def dummy_method(self, ticker_data):
            return f"Created contract for {ticker_data['symbol']}"
        
        class DummyClass:
            pass
        
        instance = DummyClass()
        ticker_data = {
            'symbol': 'AAPL',
            'exchange': 'NASDAQ'
        }
        
        result = dummy_method(instance, ticker_data)
        assert result == "Created contract for AAPL"
    
    def test_decorator_validation_failure(self):
        """Test decorator with invalid data."""
        @validate_fields(['symbol', 'exchange'], 'STK')
        def dummy_method(self, ticker_data):
            return f"Created contract for {ticker_data['symbol']}"
        
        class DummyClass:
            pass
        
        instance = DummyClass()
        ticker_data = {
            'symbol': 'AAPL'
            # exchange is missing
        }
        
        with pytest.raises(ValueError, match="Missing required fields for STK"):
            dummy_method(instance, ticker_data) 