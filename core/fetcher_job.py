"""
Job management and scheduling for data fetching operations.

This module implements the job scheduling and management functionality with:
- Sequential processing of symbols from tickers.csv
- Progress tracking via bar_status.csv
- Error handling and recovery
- Status updates and resumability logic
- Graceful shutdown with signal handling

Job Processing Strategy:
- Sequential processing of symbols (no parallel processing)
- Simple sequential queue
- Progress tracking in bar_status.csv per symbol
- Resume from last incomplete date
- Skip completed dates
- Graceful exit allows current fetch job to complete before shutdown
"""

import asyncio
import csv
import logging
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum

import pandas as pd
import pytz
from ib_async import Contract

from core.fetcher import IBDataFetcher
from utils.contract import ContractManager
from utils.logging import get_logger
from utils.market_calendar import MarketCalendar
from utils.validation import DataValidator
from utils.config_manager import get_config_manager
from utils.bar_status_manager import BarStatusManager, BarStatus, BarStatusRecord
from utils.symbol_manager import SymbolManager
from utils.date_processor import DateProcessor
from utils.eta_calculator import ETACalculator
from utils.smart_retry_manager import SmartRetryManager, FailureType


class JobStatus(Enum):
    """Job status enumeration."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"
    PAUSED = "PAUSED"


@dataclass
class JobProgress:
    """Progress tracking for a symbol job."""
    symbol: str
    total_dates: int
    completed_dates: int
    error_dates: int
    current_date: Optional[datetime]
    start_time: Optional[datetime]
    last_update: Optional[datetime]
    status: JobStatus
    
    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage."""
        if self.total_dates == 0:
            return 0.0
        return (self.completed_dates / self.total_dates) * 100.0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate of completed attempts."""
        total_attempts = self.completed_dates + self.error_dates
        if total_attempts == 0:
            return 0.0
        return (self.completed_dates / total_attempts) * 100.0


class DataFetcherJob:
    """
    Main job manager for orchestrating data fetching operations.
    
    Handles sequential processing of symbols, progress tracking,
    and status management according to planning specifications.
    """
    
    def __init__(self, config_path: str = "config/settings.yaml", environment: Optional[str] = None):
        """
        Initialize the job manager.
        
        Args:
            config_path: Path to configuration file (for backward compatibility)
            environment: Environment to use ('dev', 'test', 'prod'). If None, auto-detects.
        """
        self.logger = get_logger(__name__)
        
        # Use centralized configuration manager
        config_dir = Path(config_path).parent if config_path else None
        config_manager = get_config_manager(environment, config_dir)
        self.config = config_manager.load_config()
        self.logger.info("Loaded configuration for environment: %s", 
                       config_manager.environment)
        
        # Initialize components with environment awareness
        self.fetcher = IBDataFetcher(config_path, environment)
        self.contract_manager = ContractManager()
        self.market_calendar = MarketCalendar()
        self.data_validator = DataValidator()
        self.symbol_manager = SymbolManager()
        
        # Initialize bar status manager
        self.data_dir = Path("data")
        self.bar_status_manager = BarStatusManager(self.data_dir)
        
        # Initialize date processor
        self.date_processor = DateProcessor(
            self.fetcher,
            self.market_calendar,
            self.bar_status_manager,
            self.data_dir
        )
        
        # Initialize new components for better error handling and progress tracking
        self.eta_calculator = ETACalculator()
        self.retry_manager = SmartRetryManager(
            max_consecutive_no_data_days=self.config.get('failure_handling', {}).get('max_consecutive_no_data_days', 10),
            max_retries_per_date=self.config.get('failure_handling', {}).get('max_retries_per_date', 3)
        )
        
        # Job state
        self.current_job: Optional[JobProgress] = None
        self.job_queue: List[str] = []
        self.is_running = False
        
        # Graceful shutdown state
        self.shutdown_requested = False
        self.shutdown_event = asyncio.Event()
        self.current_task_completed = False
        self.shutdown_reason = "Unknown"
        
        # Ensure data directory exists
        self.data_dir.mkdir(exist_ok=True)
        
        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()
        
        self.logger.info("DataFetcherJob initialized with graceful shutdown support")
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            """Handle shutdown signals gracefully."""
            signal_name = signal.Signals(signum).name
            self.shutdown_reason = f"Received {signal_name} signal"
            self.logger.info("Received %s signal, initiating graceful shutdown...", signal_name)
            self.shutdown_requested = True
            
            # If we're in an async context, set the shutdown event
            if hasattr(self, 'shutdown_event'):
                # Schedule the shutdown event to be set in the async event loop
                try:
                    loop = asyncio.get_running_loop()
                    loop.call_soon_threadsafe(self.shutdown_event.set)
                    # Also schedule a more aggressive shutdown if needed
                    loop.call_later(5.0, self._force_shutdown_if_needed)
                except RuntimeError:
                    # No running event loop, shutdown event will be checked synchronously
                    pass
        
        # Handle common shutdown signals
        for sig in [signal.SIGTERM, signal.SIGINT]:
            signal.signal(sig, signal_handler)
        
        self.logger.info("Signal handlers setup for graceful shutdown")
    
    def _force_shutdown_if_needed(self):
        """Force shutdown if graceful shutdown is taking too long."""
        if self.is_running and self.shutdown_requested:
            self.logger.warning("Forcing shutdown due to timeout")
            # Cancel all pending tasks
            try:
                loop = asyncio.get_running_loop()
                for task in asyncio.all_tasks(loop):
                    if not task.done():
                        task.cancel()
            except RuntimeError:
                pass
    
    async def start_jobs(self, symbols: Optional[List[str]] = None) -> None:
        """
        Start processing jobs for specified symbols or all symbols from tickers.csv.
        
        Args:
            symbols: Optional list of symbols to process. If None, processes all symbols from tickers.csv
        """
        if self.is_running:
            self.logger.warning("Jobs are already running")
            return
        
        try:
            # Reset shutdown state
            self.shutdown_requested = False
            self.shutdown_event.clear()
            self.current_task_completed = False
            
            # Load symbols to process
            if symbols is None:
                symbols = self.symbol_manager.load_symbols_from_tickers()
                self.logger.info("DEBUG: Loaded %d symbols from tickers.csv: %s", 
                               len(symbols), symbols[:5] if len(symbols) > 5 else symbols)
            else:
                symbols = self.symbol_manager.validate_symbols(symbols)
                self.logger.info("DEBUG: Using provided symbols: %s", symbols)
            
            self.job_queue = symbols.copy()
            self.is_running = True
            
            # Start overall ETA tracking
            self.eta_calculator.start_overall_timing()
            
            self.logger.info("Starting jobs for %d symbols: %s", len(symbols), symbols[:5] if len(symbols) > 5 else symbols)
            
            # Connect to IB
            if not await self.fetcher.connect():
                raise RuntimeError("Failed to connect to IB TWS")
            
            # Process each symbol sequentially
            symbols_completed = 0
            symbols_with_work = 0
            
            for symbol_index, symbol in enumerate(symbols):
                if self.shutdown_requested:
                    self.logger.info("Shutdown requested, stopping processing of remaining symbols")
                    break
                
                # Check if symbol should be skipped due to retry manager
                if self.retry_manager.should_skip_symbol(symbol):
                    self.logger.warning(
                        "Skipping symbol %s (%d/%d) due to retry manager decision", 
                        symbol, symbol_index + 1, len(symbols)
                    )
                    symbols_completed += 1
                    continue
                
                # Log overall progress with ETA
                overall_eta = self.eta_calculator.get_overall_eta(len(symbols), symbol_index)
                self.logger.info(
                    "Processing symbol %d/%d: %s | Overall Progress: %.1f%% | ETA: %s",
                    symbol_index + 1, len(symbols), symbol, 
                    overall_eta.get('completion_percentage', 0.0),
                    overall_eta.get('estimated_completion', 'Calculating...')
                )
                
                # Process the symbol (it will check if there are dates to process internally)
                had_work = await self._process_symbol(symbol)
                
                # Mark symbol as completed in ETA calculator
                if had_work:
                    symbols_with_work += 1
                    self.eta_calculator.complete_symbol(symbol)
                
                symbols_completed += 1
                
                # Check for shutdown request between symbols
                if self.shutdown_requested:
                    self.logger.info("Shutdown requested after completing symbol %s", symbol)
                    break
            
            if self.shutdown_requested:
                self.logger.warning("Jobs stopped due to shutdown request: %s", self.shutdown_reason)
                self.logger.info("Completed %d/%d symbols before shutdown (%d had work to do)", 
                               symbols_completed, len(symbols), symbols_with_work)
            else:
                self.logger.info("All jobs completed successfully - processed %d symbols (%d had work to do)", 
                               len(symbols), symbols_with_work)
            
        except Exception as e:
            self.logger.error("Error during job processing: %s", e)
            raise
        finally:
            self.is_running = False
            await self.fetcher.disconnect()
            self._log_final_shutdown_summary()
    
    async def stop_jobs(self) -> None:
        """Stop all running jobs gracefully."""
        if not self.is_running:
            self.logger.info("No jobs are currently running")
            return
        
        self.logger.info("Stopping jobs gracefully...")
        self.shutdown_requested = True
        self.shutdown_reason = "Manual stop requested"
        self.shutdown_event.set()
        
        # Update current job status if there's one running
        if self.current_job:
            self.current_job.status = JobStatus.PAUSED
            self.current_job.last_update = datetime.now(timezone.utc)
            self.logger.info("Current job for %s marked as paused", self.current_job.symbol)
        
        # Note: The actual stopping happens in the main loop which checks shutdown_requested
        # This allows the current date processing to complete before stopping
        self.logger.info("Graceful stop initiated - will complete current fetch operation")
    
    async def _process_symbol(self, symbol: str) -> bool:
        """
        Process a single symbol with enhanced error handling, retry logic, and ETA tracking.
        
        Args:
            symbol: Symbol to process
            
        Returns:
            bool: True if there were dates to process, False if no work was needed
        """
        self.logger.info("Starting processing for symbol: %s", symbol)
        
        # Check if symbol should be skipped due to smart retry manager
        if self.retry_manager.should_skip_symbol(symbol):
            retry_summary = self.retry_manager.get_symbol_summary(symbol)
            self.logger.warning(
                "Skipping symbol %s due to %d consecutive no-data days (limit: %d)",
                symbol, retry_summary['consecutive_no_data_days'], 
                self.retry_manager.max_consecutive_no_data_days
            )
            return False  # Skip this symbol
        
        try:
            # Create symbol directory if it doesn't exist
            self.date_processor.create_symbol_directories(symbol)
            
            # Load existing status and determine dates to process
            dates_to_process = await self.date_processor.get_dates_to_process(symbol)
            
            if not dates_to_process:
                self.logger.info("No dates to process for symbol %s", symbol)
                return False  # No work was needed
            
            # Start ETA tracking for this symbol
            self.eta_calculator.start_symbol_timing(symbol, len(dates_to_process))
            
            # Initialize job progress
            self.current_job = JobProgress(
                symbol=symbol,
                total_dates=len(dates_to_process),
                completed_dates=0,
                error_dates=0,
                current_date=None,
                start_time=datetime.now(timezone.utc),
                last_update=datetime.now(timezone.utc),
                status=JobStatus.RUNNING
            )
            
            self.logger.info("Processing %d dates for symbol %s", len(dates_to_process), symbol)
            
            # Process each date with enhanced retry logic
            for date in dates_to_process:
                # Check shutdown at the start of each iteration
                if self.shutdown_requested:
                    self.logger.info("Shutdown requested during %s processing - stopping after current date", symbol)
                    break
                
                # Check if we should skip this symbol due to retry manager
                if self.retry_manager.should_skip_symbol(symbol):
                    self.logger.warning(
                        "Skipping remaining dates for %s due to retry manager decision", symbol
                    )
                    break
                
                self.current_job.current_date = date
                self.current_job.last_update = datetime.now(timezone.utc)
                
                # Mark that we're starting a new task
                self.current_task_completed = False
                
                # Check if this date can be retried
                if not self.retry_manager.can_retry_date(symbol, date.date()):
                    self.logger.debug("Skipping %s for %s - retry limit reached", date.strftime('%Y-%m-%d'), symbol)
                    self.current_job.error_dates += 1
                    continue
                
                # Get retry info for logging
                retry_info = self.retry_manager.get_retry_info(symbol, date.date())
                retry_attempt = retry_info.retry_count + 1 if retry_info else 1
                
                self.logger.debug(
                    "Processing %s for %s (attempt %d/%d)", 
                    date.strftime('%Y-%m-%d'), symbol, retry_attempt, 
                    self.retry_manager.max_retries_per_date
                )
                
                # Add timeout to prevent hanging on individual fetch operations
                try:
                    success = await asyncio.wait_for(
                        self.date_processor.process_date(symbol, date, self.shutdown_requested), 
                        timeout=60.0  # 60 second timeout per date
                    )
                    error_message = ""
                except asyncio.TimeoutError:
                    self.logger.error("Timeout processing %s for %s - moving to next date", date.strftime('%Y-%m-%d'), symbol)
                    success = False
                    error_message = f"Timeout after 60 seconds"
                except asyncio.CancelledError:
                    self.logger.info("Operation cancelled for %s on %s", symbol, date.strftime('%Y-%m-%d'))
                    break
                except Exception as e:
                    success = False
                    error_message = str(e)
                
                # Mark current task as completed
                self.current_task_completed = True
                
                if success:
                    self.current_job.completed_dates += 1
                    # Record success in retry manager
                    self.retry_manager.record_success(symbol, date.date())
                    
                    # Update ETA calculator
                    self.eta_calculator.update_symbol_progress(
                        symbol, self.current_job.completed_dates, self.current_job.error_dates
                    )
                    
                    # Log progress with ETA
                    symbol_eta, completion_pct = self.eta_calculator.get_symbol_eta(symbol) or (timedelta(0), 0.0)
                    self.logger.info(
                        "✅ %s for %s (%d/%d - %.1f%%) | Symbol ETA: %s",
                        date.strftime('%Y-%m-%d'), symbol,
                        self.current_job.completed_dates, self.current_job.total_dates,
                        completion_pct, str(symbol_eta).split('.')[0]
                    )
                else:
                    self.current_job.error_dates += 1
                    
                    # Record failure in retry manager (it will determine failure type and handle retry logic)
                    failure_type = self.retry_manager.record_failure(
                        symbol, date.date(), error_message or "Processing failed", data_received=False
                    )
                    
                    # Update ETA calculator
                    self.eta_calculator.update_symbol_progress(
                        symbol, self.current_job.completed_dates, self.current_job.error_dates
                    )
                    
                    retry_summary = self.retry_manager.get_symbol_summary(symbol)
                    self.logger.warning(
                        "❌ %s for %s (attempt %d/%d, %s) | No-data streak: %d days",
                        date.strftime('%Y-%m-%d'), symbol, retry_attempt, 
                        self.retry_manager.max_retries_per_date, failure_type.value,
                        retry_summary['consecutive_no_data_days']
                    )
                
                # Check for shutdown request after completing the date
                if self.shutdown_requested:
                    self.logger.info("Shutdown requested - completed %s for %s before stopping", 
                                   date.strftime('%Y-%m-%d'), symbol)
                    break
            
            # Get final retry status from smart retry manager
            retry_summary = self.retry_manager.get_symbol_summary(symbol)
            skipped_due_to_no_data = retry_summary['should_skip']
            
            # Mark job complete or paused based on shutdown status
            if self.shutdown_requested:
                self.current_job.status = JobStatus.PAUSED
                self.logger.info(
                    "⏸️ Processing paused for %s due to shutdown: %d successful, %d errors (%.1f%% success rate) - %d dates remaining",
                    symbol,
                    self.current_job.completed_dates,
                    self.current_job.error_dates,
                    self.current_job.success_rate,
                    self.current_job.total_dates - self.current_job.completed_dates - self.current_job.error_dates
                )
            elif skipped_due_to_no_data:
                self.current_job.status = JobStatus.ERROR
                self.logger.warning(
                    "🚫 Processing stopped for %s due to %d consecutive no-data days: %d successful, %d errors (%.1f%% success rate) - SYMBOL SKIPPED",
                    symbol,
                    retry_summary['consecutive_no_data_days'],
                    self.current_job.completed_dates,
                    self.current_job.error_dates,
                    self.current_job.success_rate
                )
            else:
                self.current_job.status = JobStatus.COMPLETE
                # Get final performance summary
                symbol_eta, completion_pct = self.eta_calculator.get_symbol_eta(symbol) or (timedelta(0), 100.0)
                self.logger.info(
                    "✅ Completed processing for %s: %d successful, %d errors (%.1f%% success rate) - Final completion: %.1f%%",
                    symbol,
                    self.current_job.completed_dates,
                    self.current_job.error_dates,
                    self.current_job.success_rate,
                    completion_pct
                )
            
            self.current_job.current_date = None
            self.current_job.last_update = datetime.now(timezone.utc)
            
            return True  # There was work to do
            
        except Exception as e:
            self.logger.error("Error processing symbol %s: %s", symbol, e)
            if self.current_job:
                self.current_job.status = JobStatus.ERROR
                self.current_job.last_update = datetime.now(timezone.utc)
            return True  # There was work attempted
        finally:
            self.current_job = None
    
    
    
    def get_job_progress(self) -> Optional[JobProgress]:
        """Get current job progress."""
        return self.current_job
    
    def get_symbol_summary(self, symbol: str) -> Dict:
        """
        Get enhanced summary statistics for a symbol including retry and ETA information.
        
        Args:
            symbol: Symbol to get summary for
            
        Returns:
            Dictionary with enhanced summary statistics
        """
        # Get base summary from bar status manager
        base_summary = self.bar_status_manager.get_symbol_summary(symbol)
        
        # Get retry information
        retry_summary = self.retry_manager.get_symbol_summary(symbol)
        
        # Get ETA information if available
        eta_info = {}
        eta_result = self.eta_calculator.get_symbol_eta(symbol)
        if eta_result:
            symbol_eta, completion_pct = eta_result
            eta_info = {
                'estimated_remaining_time': str(symbol_eta).split('.')[0],
                'eta_completion_percentage': completion_pct
            }
        
        # Combine all information
        enhanced_summary = {
            **base_summary,
            **retry_summary,
            **eta_info
        }
        
        return enhanced_summary
    
    def get_overall_progress(self) -> Dict:
        """
        Get overall progress across all symbols with ETA information.
        
        Returns:
            Dictionary with overall progress and ETA statistics
        """
        if not hasattr(self, 'job_queue') or not self.job_queue:
            return {'error': 'No job queue available'}
        
        # Get overall ETA information
        current_symbol_index = 0
        if self.current_job:
            try:
                current_symbol_index = self.job_queue.index(self.current_job.symbol)
            except ValueError:
                current_symbol_index = 0
        
        overall_eta = self.eta_calculator.get_overall_eta(len(self.job_queue), current_symbol_index)
        
        # Get retry manager summary
        retry_summary = self.retry_manager.get_overall_summary()
        
        # Get performance summary
        performance_summary = self.eta_calculator.get_performance_summary()
        
        # Combine all information
        return {
            'overall_eta': overall_eta,
            'retry_statistics': retry_summary,
            'performance_metrics': performance_summary,
            'current_job': self.get_job_progress().__dict__ if self.current_job else None
        }

    def _log_final_shutdown_summary(self):
        """Log final shutdown summary with job completion details."""
        if self.current_job:
            self.logger.info(
                "Final job status for %s: %d/%d dates completed (%.1f%% complete, %.1f%% success rate)",
                self.current_job.symbol,
                self.current_job.completed_dates,
                self.current_job.total_dates,
                self.current_job.completion_percentage,
                self.current_job.success_rate
            )
        
        if self.shutdown_requested:
            self.logger.warning("Session ended due to: %s", self.shutdown_reason)
        else:
            self.logger.info("Session completed successfully")


# Convenience class for async context management
class AsyncDataFetcherJob:
    """Async context manager wrapper for DataFetcherJob."""
    
    def __init__(self, config_path: str = "config/settings.yaml", environment: Optional[str] = None):
        self.job = DataFetcherJob(config_path, environment)
    
    async def __aenter__(self):
        return self.job
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.job.is_running:
            await self.job.stop_jobs() 