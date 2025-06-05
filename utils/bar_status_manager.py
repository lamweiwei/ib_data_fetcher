"""
Bar status management utilities for the IB Data Fetcher.

This module handles the bar_status.csv file management for tracking progress
of data fetching operations per symbol and date, following the principle of
avoiding code duplication and keeping files under 300 lines.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from utils.logging import get_logger
from utils.base import DataComponent


class BarStatus(Enum):
    """Bar status enumeration matching planning.md specifications."""
    COMPLETE = "COMPLETE"
    EARLY_CLOSE = "EARLY_CLOSE"
    HOLIDAY = "HOLIDAY"
    ERROR = "ERROR"
    PENDING = "PENDING"


@dataclass
class BarStatusRecord:
    """Represents a row in bar_status.csv."""
    date: datetime
    status: BarStatus
    expected_bars: int
    actual_bars: int
    last_timestamp: Optional[datetime]
    error_message: Optional[str] = None
    retry_count: int = 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for CSV writing."""
        return {
            'date': self.date.strftime('%Y-%m-%d'),
            'status': self.status.value,
            'expected_bars': self.expected_bars,
            'actual_bars': self.actual_bars,
            'last_timestamp': self.last_timestamp.isoformat() if self.last_timestamp else '',
            'error_message': self.error_message or '',
            'retry_count': self.retry_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'BarStatusRecord':
        """Create from dictionary (CSV row)."""
        return cls(
            date=datetime.strptime(data['date'], '%Y-%m-%d').replace(tzinfo=timezone.utc),
            status=BarStatus(data['status']),
            expected_bars=int(data['expected_bars']),
            actual_bars=int(data['actual_bars']),
            last_timestamp=datetime.fromisoformat(data['last_timestamp']) if data['last_timestamp'] else None,
            error_message=data.get('error_message') or None,
            retry_count=int(data.get('retry_count', 0))
        )


class BarStatusManager(DataComponent):
    """
    Manages bar status CSV files for tracking data fetching progress.
    
    Inherits from DataComponent which provides:
    - Automatic logger setup
    - Configuration loading
    - Data directory management
    - Symbol directory utilities
    """
    
    def __init__(self, data_dir: Optional[Path] = None, environment: Optional[str] = None):
        """
        Initialize the bar status manager.
        
        Args:
            data_dir: Directory where symbol data folders are stored (optional)
            environment: Environment to use ('dev', 'test', 'prod'). If None, auto-detects.
        """
        # Call parent constructor - handles all common setup automatically
        super().__init__(environment=environment, data_dir=data_dir)
    
    def load_bar_status(self, symbol: str) -> List[BarStatusRecord]:
        """
        Load bar status records for a symbol from CSV file.
        
        Args:
            symbol: The stock symbol
            
        Returns:
            List of BarStatusRecord objects
        """
        symbol_dir = self.get_symbol_dir(symbol)
        status_file = symbol_dir / "bar_status.csv"
        
        if not status_file.exists():
            self.logger.debug("No bar status file found for %s", symbol)
            return []
        
        records = []
        try:
            with open(status_file, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        record = BarStatusRecord.from_dict(row)
                        records.append(record)
                    except (ValueError, KeyError) as e:
                        self.logger.warning(
                            "Invalid bar status record for %s: %s - %s", 
                            symbol, row, e
                        )
                        continue
        except Exception as e:
            self.logger.error("Failed to load bar status for %s: %s", symbol, e)
            return []
        
        self.logger.debug("Loaded %d bar status records for %s", len(records), symbol)
        return records
    
    def update_bar_status(self, symbol: str, record: BarStatusRecord) -> None:
        """
        Update a single bar status record in the CSV file.
        
        Args:
            symbol: The stock symbol
            record: The BarStatusRecord to update
        """
        symbol_dir = self.get_symbol_dir(symbol)
        symbol_dir.mkdir(exist_ok=True)
        
        status_file = symbol_dir / "bar_status.csv"
        
        # Load existing records
        existing_records = self.load_bar_status(symbol)
        
        # Update or add the record
        record_updated = False
        for i, existing_record in enumerate(existing_records):
            if existing_record.date.date() == record.date.date():
                existing_records[i] = record
                record_updated = True
                break
        
        if not record_updated:
            existing_records.append(record)
        
        # Sort by date
        existing_records.sort(key=lambda r: r.date)
        
        # Write back to CSV
        try:
            with open(status_file, 'w', newline='') as f:
                if existing_records:
                    fieldnames = ['date', 'status', 'expected_bars', 'actual_bars', 
                                'last_timestamp', 'error_message', 'retry_count']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    
                    for existing_record in existing_records:
                        writer.writerow(existing_record.to_dict())
            
            self.logger.debug(
                "Updated bar status for %s on %s: %s", 
                symbol, 
                record.date.strftime('%Y-%m-%d'), 
                record.status.value
            )
            
        except Exception as e:
            self.logger.error("Failed to update bar status for %s: %s", symbol, e)
    
    def get_symbol_summary(self, symbol: str) -> Dict:
        """
        Get summary statistics for a symbol's progress.
        
        Args:
            symbol: The stock symbol
            
        Returns:
            Dictionary with summary statistics
        """
        records = self.load_bar_status(symbol)
        
        if not records:
            return {
                'symbol': symbol,
                'total_dates': 0,
                'completed': 0,
                'errors': 0,
                'success_rate': 0.0,
                'last_update': None
            }
        
        completed = sum(1 for r in records if r.status in [BarStatus.COMPLETE, BarStatus.EARLY_CLOSE])
        errors = sum(1 for r in records if r.status == BarStatus.ERROR)
        total_dates = len(records)
        
        # Calculate success rate
        attempted = completed + errors
        success_rate = (completed / attempted * 100.0) if attempted > 0 else 0.0
        
        # Find oldest successful date (since we're fetching newest to oldest)
        last_update = None
        if records:
            # Get only successful records (COMPLETE or EARLY_CLOSE)
            successful_records = [r for r in records if r.status in [BarStatus.COMPLETE, BarStatus.EARLY_CLOSE]]
            if successful_records:
                # Sort by date and get the oldest successful date
                sorted_successful_records = sorted(successful_records, key=lambda r: r.date)
                last_update = sorted_successful_records[0].date.strftime('%Y-%m-%d')
            else:
                # If no successful records, show the most recent attempted date
                sorted_records = sorted(records, key=lambda r: r.date, reverse=True)
                last_update = sorted_records[0].date.strftime('%Y-%m-%d')
        
        return {
            'symbol': symbol,
            'total_dates': total_dates,
            'completed': completed,
            'errors': errors,
            'success_rate': success_rate,
            'last_update': last_update
        }
    
    def get_completed_dates(self, symbol: str) -> set:
        """
        Get set of completed dates for a symbol.
        
        Args:
            symbol: The stock symbol
            
        Returns:
            Set of datetime objects for completed dates
        """
        records = self.load_bar_status(symbol)
        return {
            r.date.date() for r in records 
            if r.status in [BarStatus.COMPLETE, BarStatus.EARLY_CLOSE]
        }
    
    def get_error_dates(self, symbol: str) -> set:
        """
        Get set of error dates for a symbol.
        
        Args:
            symbol: The stock symbol
            
        Returns:
            Set of datetime objects for error dates
        """
        records = self.load_bar_status(symbol)
        return {
            r.date.date() for r in records 
            if r.status == BarStatus.ERROR
        }
    
    def get_consecutive_failures(self, symbol: str) -> int:
        """
        Get the count of consecutive failures from the most recent dates.
        
        This method looks at the most recent dates (sorted chronologically) and counts 
        how many consecutive dates have ERROR status from the end.
        
        Args:
            symbol: The stock symbol
            
        Returns:
            Number of consecutive failures from most recent dates
        """
        records = self.load_bar_status(symbol)
        if not records:
            return 0
        
        # Sort by date in descending order (most recent first)
        sorted_records = sorted(records, key=lambda r: r.date, reverse=True)
        
        consecutive_failures = 0
        for record in sorted_records:
            if record.status == BarStatus.ERROR:
                consecutive_failures += 1
            else:
                # Stop counting when we hit a non-error status
                break
        
        return consecutive_failures 