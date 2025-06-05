#!/usr/bin/env python3
"""
Test script to demonstrate consecutive failure handling functionality.

This script tests the consecutive failure feature by:
1. Starting with 1990-01-05 AAPL data which should cause errors
2. Retrying multiple times and moving to next days
3. Eventually triggering the 10 consecutive failure limit
4. Demonstrating symbol skipping to the next symbol

Usage:
    python test_consecutive_failures_demo.py
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import shutil

# Add the project root to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent))

from core.fetcher_job import DataFetcherJob
from utils.logging import get_logger
from utils.config_manager import get_config_manager
from utils.bar_status_manager import BarStatusManager, BarStatus, BarStatusRecord


class ConsecutiveFailureDemo:
    """Demo class to test consecutive failure handling."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.temp_dir = None
        self.original_data_dir = None
    
    def setup_test_environment(self):
        """Set up a temporary test environment."""
        # Create temporary directory for test data
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ib_data_test_"))
        self.original_data_dir = Path("data")
        
        # Create test data directory structure
        (self.temp_dir / "data").mkdir(exist_ok=True)
        
        self.logger.info("Created temporary test environment: %s", self.temp_dir)
        
        # Create test configuration with normal 10 failure limit
        test_config = {
            'ib': {
                'host': '127.0.0.1',
                'port': 7497,
                'client_id': 999  # Use different client ID for test
            },
            'failure_handling': {
                'max_consecutive_failures': 10,  # Original limit as requested
                'reset_on_success': True
            },
            'rate_limit': {
                'requests_per_second': 0.5  # Faster for demo
            },
            'validation': {
                'expected_bars': {
                    'regular_day': 390,
                    'early_close': [360, 210],
                    'holiday': 0
                }
            }
        }
        
        return test_config
    
    def cleanup_test_environment(self):
        """Clean up test environment."""
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            self.logger.info("Cleaned up test environment")
    
    def create_initial_error_records(self, symbol: str):
        """Create initial error records to start closer to the limit."""
        bar_status_manager = BarStatusManager(self.temp_dir / "data")
        
        # Create 7 existing error records to start closer to the 10 limit
        # Use Dec 1989 and early Jan 1990 dates (before Jan 5)
        error_dates = [
            datetime(1989, 12, 26, tzinfo=timezone.utc),  # Dec 26, 1989
            datetime(1989, 12, 27, tzinfo=timezone.utc),  # Dec 27, 1989
            datetime(1989, 12, 28, tzinfo=timezone.utc),  # Dec 28, 1989
            datetime(1989, 12, 29, tzinfo=timezone.utc),  # Dec 29, 1989
            datetime(1990, 1, 2, tzinfo=timezone.utc),    # Jan 2, 1990
            datetime(1990, 1, 3, tzinfo=timezone.utc),    # Jan 3, 1990
            datetime(1990, 1, 4, tzinfo=timezone.utc),    # Jan 4, 1990
        ]
        
        for date in error_dates:
            record = BarStatusRecord(
                date=date,
                status=BarStatus.ERROR,
                expected_bars=390,
                actual_bars=0,
                last_timestamp=None,
                error_message="Historical data not available for late 1989/early 1990"
            )
            bar_status_manager.update_bar_status(symbol, record)
        
        self.logger.info("Created 7 existing error records for %s (starting closer to limit)", symbol)
        return bar_status_manager
    
    async def run_demo(self):
        """Run the consecutive failure demonstration."""
        self.logger.info("=" * 70)
        self.logger.info("CONSECUTIVE FAILURE HANDLING DEMO - EXACT SCENARIO")
        self.logger.info("=" * 70)
        self.logger.info("Scenario: Start with 1990-01-05 AAPL data (should cause errors)")
        self.logger.info("Expected: Retry 3 times, move to next day, eventually hit 10 limit")
        self.logger.info("=" * 70)
        
        try:
            # Set up test environment
            test_config = self.setup_test_environment()
            
            # Create test symbols - AAPL (will fail) and GOOGL (next symbol)
            test_symbols = ["AAPL", "GOOGL"]
            
            # Create some existing failures for AAPL to start with 7 consecutive failures
            bar_status_manager = self.create_initial_error_records("AAPL")
            
            # Check initial consecutive failures
            initial_failures = bar_status_manager.get_consecutive_failures("AAPL")
            self.logger.info("AAPL starts with %d consecutive failures", initial_failures)
            
            # Mock the fetcher to always fail for old dates
            job = MockDataFetcherJob(test_config, self.temp_dir)
            
            self.logger.info("Testing symbols: %s", test_symbols)
            self.logger.info("Failure limit set to: %d", test_config['failure_handling']['max_consecutive_failures'])
            self.logger.info("Need %d more failures to trigger skip", 
                           test_config['failure_handling']['max_consecutive_failures'] - initial_failures)
            
            # Start the demo
            await job.start_jobs(test_symbols)
            
            # Show final results
            self.logger.info("=" * 70)
            self.logger.info("DEMO COMPLETED - FINAL RESULTS")
            self.logger.info("=" * 70)
            
            for symbol in test_symbols:
                summary = job.get_symbol_summary(symbol)
                consecutive_failures = bar_status_manager.get_consecutive_failures(symbol)
                self.logger.info(
                    "%s: %d completed, %d errors, %d consecutive failures %s",
                    symbol, summary['completed'], summary['errors'], consecutive_failures,
                    "(SKIPPED)" if consecutive_failures >= 10 else ""
                )
            
        except Exception as e:
            self.logger.error("Demo failed: %s", e)
            raise
        finally:
            self.cleanup_test_environment()


class MockDataFetcherJob(DataFetcherJob):
    """Mock job that simulates failures for old dates."""
    
    def __init__(self, config, temp_dir):
        # Don't call super().__init__ to avoid IB connection
        self.config = config
        self.temp_dir = temp_dir
        self.logger = get_logger(__name__)
        self.is_running = False
        self.shutdown_requested = False
        self.current_job = None
        
        # Create mock components
        from utils.market_calendar import MarketCalendar
        from utils.date_processor import DateProcessor
        from utils.symbol_manager import SymbolManager
        
        self.market_calendar = MarketCalendar()
        self.bar_status_manager = BarStatusManager(temp_dir / "data")
        self.symbol_manager = SymbolManager()
        
        # Mock date processor that always fails
        self.date_processor = MockDateProcessor(
            None,  # No real fetcher
            self.market_calendar,
            self.bar_status_manager,
            temp_dir / "data"
        )
    
    async def start_jobs(self, symbols):
        """Override to avoid IB connection."""
        if self.is_running:
            self.logger.warning("Jobs are already running")
            return
        
        try:
            self.shutdown_requested = False
            self.is_running = True
            
            self.logger.info("Starting demo jobs for %d symbols: %s", len(symbols), symbols)
            
            # Process each symbol sequentially
            for symbol in symbols:
                if self.shutdown_requested:
                    break
                
                self.logger.info("=" * 50)
                self.logger.info("PROCESSING SYMBOL: %s", symbol)
                self.logger.info("=" * 50)
                had_work = await self._process_symbol(symbol)
                
                if not had_work:
                    self.logger.info("No work for %s or symbol was skipped", symbol)
                
        except Exception as e:
            self.logger.error("Error during demo job processing: %s", e)
            raise
        finally:
            self.is_running = False


class MockDateProcessor:
    """Mock date processor that simulates failures."""
    
    def __init__(self, fetcher, market_calendar, bar_status_manager, data_dir):
        self.market_calendar = market_calendar
        self.bar_status_manager = bar_status_manager
        self.data_dir = data_dir
        self.logger = get_logger(__name__)
    
    async def get_dates_to_process(self, symbol: str):
        """Return test dates starting from 1990-01-05 as requested."""
        # Start with Jan 5, 1990 as requested, then subsequent days
        dates = []
        start_date = datetime(1990, 1, 5, tzinfo=timezone.utc)
        
        # Generate 10 days starting from Jan 5, 1990
        for i in range(10):
            date = start_date + timedelta(days=i)
            # Skip weekends
            if date.weekday() < 5:  # Monday=0, Friday=4
                dates.append(date)
        
        # Filter out already completed dates
        completed_dates = self.bar_status_manager.get_completed_dates(symbol)
        dates_to_process = [d for d in dates if d.date() not in completed_dates]
        
        # Sort newest to oldest as per system design
        dates_to_process.sort(reverse=True)
        
        if symbol == "AAPL":
            self.logger.info(
                "Symbol %s: %d dates to process starting from 1990-01-05 (will all fail)",
                symbol, len(dates_to_process)
            )
            if dates_to_process:
                self.logger.info("First date to process: %s", dates_to_process[0].strftime('%Y-%m-%d'))
                self.logger.info("Last date to process: %s", dates_to_process[-1].strftime('%Y-%m-%d'))
        else:
            self.logger.info(
                "Symbol %s: %d dates to process (1990 dates - will also fail)",
                symbol, len(dates_to_process)
            )
        
        return dates_to_process
    
    async def process_date(self, symbol: str, date: datetime, shutdown_requested: bool = False):
        """Simulate processing that always fails for old dates."""
        if shutdown_requested:
            return False
        
        # Simulate some processing time
        await asyncio.sleep(0.2)
        
        # Always fail for 1990 dates (simulate no data available)
        self.logger.error("FAILED: %s on %s - Historical data not available for 1990", 
                         symbol, date.strftime('%Y-%m-%d'))
        
        # Record the error
        record = BarStatusRecord(
            date=date,
            status=BarStatus.ERROR,
            expected_bars=390,
            actual_bars=0,
            last_timestamp=None,
            error_message=f"Simulated error: No historical data for {date.strftime('%Y-%m-%d')}"
        )
        
        self.bar_status_manager.update_bar_status(symbol, record)
        return False  # Always fail
    
    def create_symbol_directories(self, symbol: str):
        """Create directories for symbol."""
        symbol_dir = self.data_dir / symbol
        symbol_dir.mkdir(exist_ok=True)
        (symbol_dir / "raw").mkdir(exist_ok=True)


async def main():
    """Main demo function."""
    # Set up logging for demo
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    demo = ConsecutiveFailureDemo()
    await demo.run_demo()


if __name__ == "__main__":
    print("=" * 70)
    print("CONSECUTIVE FAILURE HANDLING DEMO - EXACT USER SCENARIO")
    print("=" * 70)
    print("This demo demonstrates:")
    print("1. Start with 1990-01-05 AAPL data (which should cause an error)")
    print("2. Retry three times and skip to the next day")
    print("3. Should still cause an error, three trials and next day")
    print("4. One more try and it will trigger the 10 limit")
    print("5. Should skip to the next symbol (GOOGL)")
    print("=" * 70)
    print()
    
    asyncio.run(main()) 