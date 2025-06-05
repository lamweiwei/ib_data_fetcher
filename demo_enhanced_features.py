#!/usr/bin/env python3
"""
Demonstration of Enhanced Features: Smart Retry Logic and ETA Tracking

This script demonstrates the improved error handling and progress tracking
capabilities of the enhanced IB Data Fetcher.

Features demonstrated:
1. Smart retry logic with failure type classification
2. Real-time ETA calculation for symbols and overall progress
3. Enhanced progress monitoring with detailed logging
4. Improved symbol skipping based on no-data patterns

Run this script to see the enhanced features in action.
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from core.fetcher_job import AsyncDataFetcherJob
from utils.logging import get_logger
from utils.smart_retry_manager import SmartRetryManager, FailureType
from utils.eta_calculator import ETACalculator


def setup_demo_logging():
    """Setup logging for the demonstration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


async def demonstrate_smart_retry_logic():
    """Demonstrate the smart retry manager capabilities."""
    logger = get_logger("retry_demo")
    logger.info("=== SMART RETRY LOGIC DEMONSTRATION ===")
    
    # Create retry manager
    retry_manager = SmartRetryManager(
        max_consecutive_no_data_days=3,  # Lower for demo
        max_retries_per_date=2  # Lower for demo
    )
    
    demo_dates = [
        datetime(2023, 1, 3).date(),  # Tuesday
        datetime(2023, 1, 4).date(),  # Wednesday  
        datetime(2023, 1, 5).date(),  # Thursday
        datetime(2023, 1, 6).date(),  # Friday
        datetime(2023, 1, 9).date(),  # Monday
    ]
    
    symbol = "DEMO"
    
    logger.info("Simulating failures for symbol %s", symbol)
    
    # Simulate various failure scenarios
    scenarios = [
        ("Network error", False),  # Network issue - doesn't count toward no-data streak
        ("No data available", False),  # No data - counts toward streak
        ("No data available", False),  # No data - counts toward streak  
        ("Connection timeout", False),  # Network issue - doesn't count
        ("No data available", False),  # No data - counts toward streak (3rd consecutive)
    ]
    
    for date, (error_msg, data_received) in zip(demo_dates, scenarios):
        logger.info("\n--- Processing date %s ---", date)
        
        # Check if date can be retried
        can_retry = retry_manager.can_retry_date(symbol, date)
        logger.info("Can retry %s: %s", date, can_retry)
        
        if can_retry:
            # Simulate multiple retry attempts
            for attempt in range(2):  # 2 attempts per date
                failure_type = retry_manager.record_failure(symbol, date, error_msg, data_received)
                logger.info("Attempt %d for %s: %s (%s)", attempt + 1, date, error_msg, failure_type.value)
                
                # Check if symbol should be skipped
                if retry_manager.should_skip_symbol(symbol):
                    logger.warning("Symbol %s marked for skipping!", symbol)
                    break
        
        # Show current retry summary
        summary = retry_manager.get_symbol_summary(symbol)
        logger.info("Current state: %d consecutive no-data days, should_skip: %s", 
                   summary['consecutive_no_data_days'], summary['should_skip'])
        
        if summary['should_skip']:
            logger.error("Symbol %s skipped after %d consecutive no-data days", 
                        symbol, summary['consecutive_no_data_days'])
            break
    
    # Show final summary
    logger.info("\n=== FINAL RETRY SUMMARY ===")
    final_summary = retry_manager.get_symbol_summary(symbol)
    for key, value in final_summary.items():
        logger.info("%s: %s", key, value)


async def demonstrate_eta_calculator():
    """Demonstrate the ETA calculator capabilities."""
    logger = get_logger("eta_demo")
    logger.info("\n=== ETA CALCULATOR DEMONSTRATION ===")
    
    # Create ETA calculator
    eta_calc = ETACalculator()
    eta_calc.start_overall_timing()
    
    # Simulate processing multiple symbols
    symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"]
    
    for i, symbol in enumerate(symbols):
        logger.info("\n--- Processing symbol %d/%d: %s ---", i + 1, len(symbols), symbol)
        
        # Start symbol timing
        total_dates = 100 + (i * 50)  # Varying workload
        eta_calc.start_symbol_timing(symbol, total_dates)
        
        # Simulate processing dates with varying success rates
        completed = 0
        errors = 0
        
        for batch in range(5):  # 5 batches per symbol
            # Simulate some work
            await asyncio.sleep(0.1)  # Simulate processing time
            
            batch_completed = 15 + (batch * 2)
            batch_errors = 2 if batch % 2 == 0 else 0
            
            completed += batch_completed
            errors += batch_errors
            
            # Update progress
            eta_calc.update_symbol_progress(symbol, completed, errors)
            
            # Show progress with ETA
            eta_result = eta_calc.get_symbol_eta(symbol)
            if eta_result:
                remaining_time, completion_pct = eta_result
                logger.info("  %s: %.1f%% complete | ETA: %s", 
                           symbol, completion_pct, str(remaining_time).split('.')[0])
            
            # Show overall progress
            overall_eta = eta_calc.get_overall_eta(len(symbols), i)
            logger.info("  Overall: %.1f%% complete | ETA: %s", 
                       overall_eta.get('completion_percentage', 0),
                       overall_eta.get('estimated_completion', 'Calculating...'))
        
        # Complete the symbol
        eta_calc.complete_symbol(symbol)
        logger.info("✅ Completed %s", symbol)
    
    # Show final performance summary
    logger.info("\n=== FINAL PERFORMANCE SUMMARY ===")
    performance = eta_calc.get_performance_summary()
    for key, value in performance.items():
        logger.info("%s: %s", key, value)


async def demonstrate_enhanced_job_manager():
    """Demonstrate the enhanced job manager with actual integration."""
    logger = get_logger("job_demo")
    logger.info("\n=== ENHANCED JOB MANAGER DEMONSTRATION ===")
    
    try:
        # Use a few test symbols for demo
        test_symbols = ["AAPL", "MSFT"]
        
        async with AsyncDataFetcherJob("config/settings.yaml", "dev") as job_manager:
            logger.info("Initialized enhanced job manager")
            
            # Show initial overall progress
            progress = job_manager.get_overall_progress()
            logger.info("Initial progress structure: %s", list(progress.keys()))
            
            # Show enhanced symbol summaries
            for symbol in test_symbols:
                summary = job_manager.get_symbol_summary(symbol)
                logger.info("Enhanced summary for %s:", symbol)
                for key, value in summary.items():
                    logger.info("  %s: %s", key, value)
            
            logger.info("Enhanced job manager demonstration complete")
            
    except Exception as e:
        logger.error("Error in enhanced job manager demo: %s", e)
        logger.info("This is expected if IB TWS is not running")


async def main():
    """Run all demonstrations."""
    setup_demo_logging()
    logger = get_logger("main")
    
    logger.info("🚀 Starting Enhanced Features Demonstration")
    logger.info("=" * 60)
    
    # Run demonstrations
    await demonstrate_smart_retry_logic()
    await demonstrate_eta_calculator()
    await demonstrate_enhanced_job_manager()
    
    logger.info("=" * 60)
    logger.info("✅ Enhanced Features Demonstration Complete!")
    logger.info("\nKey Improvements Demonstrated:")
    logger.info("1. ✅ Smart retry logic with failure type classification")
    logger.info("2. ✅ Real-time ETA calculation for symbols and overall progress")
    logger.info("3. ✅ Enhanced progress monitoring with detailed logging")
    logger.info("4. ✅ Improved symbol skipping based on no-data patterns")
    logger.info("\nTo see these features in action with real data:")
    logger.info("python main.py AAPL MSFT --config dev")


if __name__ == "__main__":
    asyncio.run(main()) 