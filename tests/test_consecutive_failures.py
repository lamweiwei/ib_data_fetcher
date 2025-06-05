"""
Tests for consecutive failure handling functionality.

This module tests the new feature that skips symbols after 10 consecutive failures.
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil

from utils.bar_status_manager import BarStatusManager, BarStatus, BarStatusRecord


class TestConsecutiveFailures:
    """Test consecutive failure tracking and skipping functionality."""
    
    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def bar_status_manager(self, temp_data_dir):
        """Create a bar status manager instance for testing."""
        return BarStatusManager(temp_data_dir)
    
    def test_consecutive_failures_empty_symbol(self, bar_status_manager):
        """Test consecutive failures for symbol with no records."""
        consecutive_failures = bar_status_manager.get_consecutive_failures("EMPTY")
        assert consecutive_failures == 0
    
    def test_consecutive_failures_no_errors(self, bar_status_manager):
        """Test consecutive failures for symbol with only successful records."""
        symbol = "SUCCESS"
        
        # Add successful records
        for day in range(1, 6):
            date = datetime(2024, 1, day, tzinfo=timezone.utc)
            record = BarStatusRecord(
                date=date,
                status=BarStatus.COMPLETE,
                expected_bars=390,
                actual_bars=390,
                last_timestamp=None
            )
            bar_status_manager.update_bar_status(symbol, record)
        
        consecutive_failures = bar_status_manager.get_consecutive_failures(symbol)
        assert consecutive_failures == 0
    
    def test_consecutive_failures_only_errors(self, bar_status_manager):
        """Test consecutive failures for symbol with only error records."""
        symbol = "ERRORS"
        
        # Add error records
        for day in range(1, 6):
            date = datetime(2024, 1, day, tzinfo=timezone.utc)
            record = BarStatusRecord(
                date=date,
                status=BarStatus.ERROR,
                expected_bars=390,
                actual_bars=0,
                last_timestamp=None,
                error_message="Test error"
            )
            bar_status_manager.update_bar_status(symbol, record)
        
        consecutive_failures = bar_status_manager.get_consecutive_failures(symbol)
        assert consecutive_failures == 5
    
    def test_consecutive_failures_mixed_recent_errors(self, bar_status_manager):
        """Test consecutive failures with mixed records - recent errors."""
        symbol = "MIXED"
        
        # Add successful records first
        for day in range(1, 4):
            date = datetime(2024, 1, day, tzinfo=timezone.utc)
            record = BarStatusRecord(
                date=date,
                status=BarStatus.COMPLETE,
                expected_bars=390,
                actual_bars=390,
                last_timestamp=None
            )
            bar_status_manager.update_bar_status(symbol, record)
        
        # Add recent error records
        for day in range(4, 7):
            date = datetime(2024, 1, day, tzinfo=timezone.utc)
            record = BarStatusRecord(
                date=date,
                status=BarStatus.ERROR,
                expected_bars=390,
                actual_bars=0,
                last_timestamp=None,
                error_message="Test error"
            )
            bar_status_manager.update_bar_status(symbol, record)
        
        consecutive_failures = bar_status_manager.get_consecutive_failures(symbol)
        assert consecutive_failures == 3
    
    def test_consecutive_failures_mixed_recent_success(self, bar_status_manager):
        """Test consecutive failures with mixed records - recent success."""
        symbol = "RECOVERY"
        
        # Add error records first
        for day in range(1, 4):
            date = datetime(2024, 1, day, tzinfo=timezone.utc)
            record = BarStatusRecord(
                date=date,
                status=BarStatus.ERROR,
                expected_bars=390,
                actual_bars=0,
                last_timestamp=None,
                error_message="Test error"
            )
            bar_status_manager.update_bar_status(symbol, record)
        
        # Add recent successful records
        for day in range(4, 7):
            date = datetime(2024, 1, day, tzinfo=timezone.utc)
            record = BarStatusRecord(
                date=date,
                status=BarStatus.COMPLETE,
                expected_bars=390,
                actual_bars=390,
                last_timestamp=None
            )
            bar_status_manager.update_bar_status(symbol, record)
        
        consecutive_failures = bar_status_manager.get_consecutive_failures(symbol)
        assert consecutive_failures == 0
    
    def test_consecutive_failures_exactly_ten(self, bar_status_manager):
        """Test consecutive failures with exactly 10 consecutive errors."""
        symbol = "TEN_ERRORS"
        
        # Add exactly 10 error records
        for day in range(1, 11):
            date = datetime(2024, 1, day, tzinfo=timezone.utc)
            record = BarStatusRecord(
                date=date,
                status=BarStatus.ERROR,
                expected_bars=390,
                actual_bars=0,
                last_timestamp=None,
                error_message="Test error"
            )
            bar_status_manager.update_bar_status(symbol, record)
        
        consecutive_failures = bar_status_manager.get_consecutive_failures(symbol)
        assert consecutive_failures == 10
    
    def test_consecutive_failures_more_than_ten(self, bar_status_manager):
        """Test consecutive failures with more than 10 consecutive errors."""
        symbol = "MANY_ERRORS"
        
        # Add 15 error records
        for day in range(1, 16):
            date = datetime(2024, 1, day, tzinfo=timezone.utc)
            record = BarStatusRecord(
                date=date,
                status=BarStatus.ERROR,
                expected_bars=390,
                actual_bars=0,
                last_timestamp=None,
                error_message="Test error"
            )
            bar_status_manager.update_bar_status(symbol, record)
        
        consecutive_failures = bar_status_manager.get_consecutive_failures(symbol)
        assert consecutive_failures == 15
    
    def test_consecutive_failures_early_close_not_error(self, bar_status_manager):
        """Test that EARLY_CLOSE status breaks consecutive error count."""
        symbol = "EARLY_CLOSE"
        
        # Add error records
        for day in range(1, 4):
            date = datetime(2024, 1, day, tzinfo=timezone.utc)
            record = BarStatusRecord(
                date=date,
                status=BarStatus.ERROR,
                expected_bars=390,
                actual_bars=0,
                last_timestamp=None,
                error_message="Test error"
            )
            bar_status_manager.update_bar_status(symbol, record)
        
        # Add early close record (should break consecutive errors)
        date = datetime(2024, 1, 4, tzinfo=timezone.utc)
        record = BarStatusRecord(
            date=date,
            status=BarStatus.EARLY_CLOSE,
            expected_bars=390,
            actual_bars=200,
            last_timestamp=None
        )
        bar_status_manager.update_bar_status(symbol, record)
        
        consecutive_failures = bar_status_manager.get_consecutive_failures(symbol)
        assert consecutive_failures == 0
    
    def test_consecutive_failures_holiday_not_error(self, bar_status_manager):
        """Test that HOLIDAY status breaks consecutive error count."""
        symbol = "HOLIDAY"
        
        # Add error records
        for day in range(1, 4):
            date = datetime(2024, 1, day, tzinfo=timezone.utc)
            record = BarStatusRecord(
                date=date,
                status=BarStatus.ERROR,
                expected_bars=390,
                actual_bars=0,
                last_timestamp=None,
                error_message="Test error"
            )
            bar_status_manager.update_bar_status(symbol, record)
        
        # Add holiday record (should break consecutive errors)
        date = datetime(2024, 1, 4, tzinfo=timezone.utc)
        record = BarStatusRecord(
            date=date,
            status=BarStatus.HOLIDAY,
            expected_bars=0,
            actual_bars=0,
            last_timestamp=None
        )
        bar_status_manager.update_bar_status(symbol, record)
        
        consecutive_failures = bar_status_manager.get_consecutive_failures(symbol)
        assert consecutive_failures == 0 