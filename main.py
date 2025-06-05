#!/usr/bin/env python3
"""
Main entry point for IB Data Fetcher with graceful shutdown support.

This script provides a simple interface to start the data fetching process
with comprehensive signal handling for graceful shutdown.

Features:
- Graceful shutdown on SIGTERM, SIGINT (Ctrl+C)
- Completion of current fetch operation before shutdown
- Progress monitoring and status reporting
- Automatic resume capability
- Environment-aware configuration

Usage:
    python main.py [symbol1] [symbol2] ...
    
If no symbols provided, will process all symbols from config/tickers.csv

Examples:
    python main.py                    # Process all symbols
    python main.py AAPL MSFT         # Process specific symbols
    python main.py --dry-run          # Show what would be processed
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

from core.fetcher_job import AsyncDataFetcherJob
from utils.logging import get_logger
from utils.progress_monitor import ProgressMonitor
from utils.config_manager import get_config_manager


async def main():
    """Main entry point for the IB data fetcher."""
    parser = argparse.ArgumentParser(
        description="IB Data Fetcher with graceful shutdown support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main.py                    # Process all symbols from tickers.csv
    python main.py AAPL MSFT         # Process specific symbols only
    python main.py --dry-run          # Show what would be processed
    python main.py --config dev       # Use dev environment configuration
        """
    )
    parser.add_argument(
        "symbols", 
        nargs="*", 
        help="Symbols to fetch (if not provided, uses all symbols from tickers.csv)"
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="Path to configuration file or environment name (dev/test/prod)"
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=30,
        help="Progress update interval in seconds (default: 30)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without actually fetching data"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce logging output (only show warnings and errors)"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logger = get_logger(__name__)
    log_level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Determine if config is an environment name or file path
    environment = None
    config_path = args.config
    if args.config in ['dev', 'test', 'prod']:
        environment = args.config
        config_path = "config/settings.yaml"
    
    logger.info("=== IB Data Fetcher Starting ===")
    logger.info("Configuration: %s", args.config)
    logger.info("Symbols to process: %s", args.symbols if args.symbols else "All from tickers.csv")
    logger.info("Graceful shutdown: Enabled (Ctrl+C to stop gracefully)")
    
    try:
        # Initialize job manager with graceful shutdown support
        async with AsyncDataFetcherJob(config_path, environment) as job_manager:
            
            if args.dry_run:
                # Show what would be processed
                symbols = job_manager.symbol_manager.get_symbols_for_processing(args.symbols)
                logger.info("=== DRY RUN MODE ===")
                logger.info("Would process %d symbols: %s", len(symbols), symbols)
                
                for symbol in symbols:
                    summary = job_manager.get_symbol_summary(symbol)
                    logger.info(
                        "Symbol %s: %d total dates, %d completed, %d errors (%.1f%% success) - Oldest Success: %s",
                        summary['symbol'],
                        summary['total_dates'],
                        summary['completed'],
                        summary['errors'],
                        summary['success_rate'],
                        summary['last_update'] or "Never"
                    )
                
                logger.info("=== DRY RUN COMPLETE ===")
                return 0
            
            # Start progress monitoring
            progress_monitor = ProgressMonitor(args.progress_interval)
            await progress_monitor.start_monitoring(job_manager)
            
            try:
                # Start the jobs with graceful shutdown support
                # Convert empty list to None for proper symbol loading from tickers.csv
                symbols_to_process = args.symbols if args.symbols else None
                await job_manager.start_jobs(symbols_to_process)
                
                # Check if we completed normally or due to shutdown
                if job_manager.shutdown_requested:
                    logger.warning("=== SESSION STOPPED GRACEFULLY ===")
                    logger.info("Reason: %s", job_manager.shutdown_reason)
                else:
                    logger.info("=== ALL JOBS COMPLETED SUCCESSFULLY ===")
                
                # Show final summaries
                symbols = job_manager.symbol_manager.get_symbols_for_processing(args.symbols)
                logger.info("Final Summary:")
                total_completed = 0
                total_errors = 0
                total_dates = 0
                
                for symbol in symbols:
                    summary = job_manager.get_symbol_summary(symbol)
                    logger.info(
                        "%s: %d completed, %d errors (%.1f%% success) - Oldest Success: %s",
                        summary['symbol'],
                        summary['completed'],
                        summary['errors'],
                        summary['success_rate'],
                        summary['last_update'] or "Never"
                    )
                    total_completed += summary['completed']
                    total_errors += summary['errors']
                    total_dates += summary['total_dates']
                
                logger.info("Overall: %d/%d dates completed, %d errors", 
                          total_completed, total_dates, total_errors)
                
                if job_manager.shutdown_requested:
                    logger.info("To resume processing, run the same command again")
                    return 0  # Graceful shutdown is success
                    
            except KeyboardInterrupt:
                logger.info("=== GRACEFUL SHUTDOWN INITIATED ===")
                logger.info("Allowing current fetch operation to complete...")
                logger.info("Press Ctrl+C again to force immediate exit (not recommended)")
                
                try:
                    # Give a short timeout for graceful shutdown
                    await asyncio.wait_for(job_manager.stop_jobs(), timeout=10.0)
                    # Give a moment for final operations to complete
                    await asyncio.sleep(2)
                    logger.info("=== SHUTDOWN COMPLETED GRACEFULLY ===")
                except asyncio.TimeoutError:
                    logger.warning("=== GRACEFUL SHUTDOWN TIMEOUT ===")
                    logger.warning("Forcing immediate shutdown")
                    # Cancel all tasks
                    tasks = [task for task in asyncio.all_tasks() if not task.done()]
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                except KeyboardInterrupt:
                    logger.warning("=== FORCED SHUTDOWN ===")
                    logger.warning("Current operation may be incomplete!")
                    # Cancel all tasks immediately
                    tasks = [task for task in asyncio.all_tasks() if not task.done()]
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    return 1
                
                # Show what was completed
                symbols = job_manager.symbol_manager.get_symbols_for_processing(args.symbols)
                logger.info("Summary at shutdown:")
                for symbol in symbols:
                    summary = job_manager.get_symbol_summary(symbol)
                    logger.info(
                        "%s: %d completed, %d errors (%.1f%% success)",
                        summary['symbol'],
                        summary['completed'],
                        summary['errors'],
                        summary['success_rate']
                    )
                
                logger.info("To resume processing, run the same command again")
                return 0  # Graceful shutdown is success
                
            finally:
                # Stop monitoring
                await progress_monitor.stop_monitoring()
                    
    except Exception as e:
        logger.error("=== ERROR ===")
        logger.error("Failed to run data fetcher: %s", e)
        return 1
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nForced exit - current operation may be incomplete!")
        sys.exit(1) 