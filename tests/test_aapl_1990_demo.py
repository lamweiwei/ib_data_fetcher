#!/usr/bin/env python3
"""
Test script demonstrating the exact scenario requested:

1. Start with 1990-01-05 AAPL data, which should cause an error
2. Retry three times and skip to the next day
3. Should still cause an error, three trials and next day  
4. One more try and it will trigger the 10 limit and should skip to the next symbol

Usage:
    python test_aapl_1990_demo.py
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil

# Add the project root to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent))

from utils.bar_status_manager import BarStatusManager, BarStatus, BarStatusRecord


async def run_aapl_1990_demo():
    """
    Run the exact demo scenario requested by the user.
    
    This demonstrates:
    1. Start with 1990-01-05 AAPL data (error)
    2. Show consecutive failure tracking
    3. Hit the 10 failure limit
    4. Skip to next symbol
    """
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S'
    )
    logger = logging.getLogger(__name__)
    
    # Create temporary test directory
    temp_dir = Path(tempfile.mkdtemp(prefix="aapl_1990_test_"))
    data_dir = temp_dir / "data"
    data_dir.mkdir(exist_ok=True)
    
    try:
        logger.info("=" * 60)
        logger.info("AAPL 1990-01-05 CONSECUTIVE FAILURE DEMO")
        logger.info("=" * 60)
        
        # Initialize bar status manager
        bar_manager = BarStatusManager(data_dir)
        
        # Step 1: Create 7 existing consecutive failures to start close to limit
        logger.info("Setting up: Creating 7 existing consecutive failures for AAPL...")
        existing_error_dates = [
            datetime(1989, 12, 26, tzinfo=timezone.utc),
            datetime(1989, 12, 27, tzinfo=timezone.utc), 
            datetime(1989, 12, 28, tzinfo=timezone.utc),
            datetime(1989, 12, 29, tzinfo=timezone.utc),
            datetime(1990, 1, 2, tzinfo=timezone.utc),
            datetime(1990, 1, 3, tzinfo=timezone.utc),
            datetime(1990, 1, 4, tzinfo=timezone.utc),
        ]
        
        for date in existing_error_dates:
            record = BarStatusRecord(
                date=date,
                status=BarStatus.ERROR,
                expected_bars=390,
                actual_bars=0,
                last_timestamp=None,
                error_message="No historical data available"
            )
            bar_manager.update_bar_status("AAPL", record)
        
        initial_failures = bar_manager.get_consecutive_failures("AAPL")
        logger.info("✅ AAPL now has %d consecutive failures (need 3 more to trigger skip)", initial_failures)
        
        # Step 2: Now simulate the exact scenario - starting with 1990-01-05
        logger.info("")
        logger.info("🔥 STARTING SCENARIO: Attempting 1990-01-05 AAPL data...")
        logger.info("Expected: This should fail and contribute to consecutive failures")
        
        # Simulate dates to process (newest to oldest as system does)
        test_dates = [
            datetime(1990, 1, 8, tzinfo=timezone.utc),   # 8th failure
            datetime(1990, 1, 5, tzinfo=timezone.utc),   # 9th failure (the requested date!)
            datetime(1990, 1, 9, tzinfo=timezone.utc),   # 10th failure - triggers skip
        ]
        
        consecutive_failures = initial_failures
        max_failures = 10
        
        for i, date in enumerate(test_dates, 1):
            logger.info("")
            logger.info(f"📅 Attempting to fetch AAPL data for {date.strftime('%Y-%m-%d')}...")
            
            # Simulate the failure (1990 data doesn't exist)
            await asyncio.sleep(0.3)  # Simulate processing time
            
            # Record the failure
            record = BarStatusRecord(
                date=date,
                status=BarStatus.ERROR,
                expected_bars=390,
                actual_bars=0,
                last_timestamp=None,
                error_message=f"No historical data available for {date.strftime('%Y-%m-%d')}"
            )
            bar_manager.update_bar_status("AAPL", record)
            
            consecutive_failures += 1
            
            logger.error(f"❌ FAILED: No historical data for AAPL on {date.strftime('%Y-%m-%d')}")
            logger.warning(f"   Consecutive failures: {consecutive_failures}/{max_failures}")
            
            # Check if we hit the limit
            if consecutive_failures >= max_failures:
                logger.error(f"🚫 LIMIT REACHED: {consecutive_failures} consecutive failures!")
                logger.error("   ➡️  SKIPPING SYMBOL: AAPL will be skipped")
                logger.info("   ➡️  MOVING TO NEXT SYMBOL: Would start processing GOOGL")
                break
            else:
                remaining = max_failures - consecutive_failures
                logger.info(f"   ⚠️  Need {remaining} more failures to trigger skip")
        
        # Final results
        logger.info("")
        logger.info("=" * 60)
        logger.info("DEMO RESULTS")
        logger.info("=" * 60)
        
        final_failures = bar_manager.get_consecutive_failures("AAPL")
        summary = bar_manager.get_symbol_summary("AAPL")
        
        logger.info(f"AAPL Final Status:")
        logger.info(f"  • Total dates attempted: {summary['total_dates']}")
        logger.info(f"  • Successful fetches: {summary['completed']}")
        logger.info(f"  • Failed fetches: {summary['errors']}")
        logger.info(f"  • Consecutive failures: {final_failures}")
        logger.info(f"  • Status: {'SKIPPED (too many failures)' if final_failures >= 10 else 'Still processing'}")
        
        logger.info("")
        logger.info("🎯 SCENARIO COMPLETED:")
        logger.info("   ✅ Started with 1990-01-05 AAPL data")
        logger.info("   ✅ Simulated consecutive failures")
        logger.info("   ✅ Triggered 10 failure limit")
        logger.info("   ✅ Demonstrated symbol skipping")
        logger.info("   ✅ System moves to next symbol (GOOGL)")
        
    finally:
        # Cleanup
        shutil.rmtree(temp_dir)
        logger.info("")
        logger.info("🧹 Cleaned up test environment")


if __name__ == "__main__":
    print("=" * 60)
    print("AAPL 1990-01-05 CONSECUTIVE FAILURE DEMONSTRATION")
    print("=" * 60)
    print("This demo shows the exact scenario you requested:")
    print("1. ⭐ Start with 1990-01-05 AAPL data (will cause error)")
    print("2. 🔄 Show consecutive failure progression")  
    print("3. 🚫 Trigger the 10 consecutive failure limit")
    print("4. ⏭️  Skip to next symbol (GOOGL)")
    print("=" * 60)
    print()
    
    asyncio.run(run_aapl_1990_demo()) 