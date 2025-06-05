"""
Progress monitoring utilities for the IB Data Fetcher.

This module provides progress monitoring functionality that was previously
embedded in main.py, following the principle of keeping files under 300 lines
and avoiding duplication.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from utils.logging import get_logger

if TYPE_CHECKING:
    from core.fetcher_job import AsyncDataFetcherJob


class ProgressMonitor:
    """Handles progress monitoring and reporting for data fetching jobs."""
    
    def __init__(self, update_interval: int = 30):
        """
        Initialize the progress monitor.
        
        Args:
            update_interval: Seconds between progress updates
        """
        self.update_interval = update_interval
        self.logger = get_logger("monitor")
        self._is_running = False
        self._monitor_task: asyncio.Task = None
    
    async def start_monitoring(self, job_manager: 'AsyncDataFetcherJob') -> None:
        """
        Start monitoring progress for the given job manager.
        
        Args:
            job_manager: The job manager instance to monitor
        """
        if self._is_running:
            self.logger.warning("Progress monitoring is already running")
            return
        
        self._is_running = True
        self._monitor_task = asyncio.create_task(
            self._monitor_progress(job_manager)
        )
    
    async def stop_monitoring(self) -> None:
        """Stop progress monitoring."""
        self._is_running = False
        
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
    
    async def _monitor_progress(self, job_manager: 'AsyncDataFetcherJob') -> None:
        """
        Monitor and display job progress periodically.
        
        Args:
            job_manager: The job manager instance
        """
        try:
            while (self._is_running and 
                   job_manager.is_running and 
                   not job_manager.shutdown_requested):
                
                progress = job_manager.get_job_progress()
                
                if progress:
                    # Get ETA information if available
                    eta_info = ""
                    if hasattr(job_manager, 'eta_calculator') and job_manager.eta_calculator:
                        symbol_eta_result = job_manager.eta_calculator.get_symbol_eta(progress.symbol)
                        if symbol_eta_result:
                            symbol_eta, completion_pct = symbol_eta_result
                            eta_info = f" | Symbol ETA: {str(symbol_eta).split('.')[0]}"
                    
                    self.logger.info(
                        "Progress for %s: %d/%d dates (%.1f%% complete, %.1f%% success rate) - Current: %s%s",
                        progress.symbol,
                        progress.completed_dates,
                        progress.total_dates,
                        progress.completion_percentage,
                        progress.success_rate,
                        progress.current_date.strftime('%Y-%m-%d') if progress.current_date else "None",
                        eta_info
                    )
                
                # Check shutdown more frequently during sleep
                for _ in range(self.update_interval):
                    if (not self._is_running or 
                        not job_manager.is_running or 
                        job_manager.shutdown_requested):
                        return
                    
                    try:
                        await asyncio.sleep(1)  # Sleep 1 second at a time for responsiveness
                    except asyncio.CancelledError:
                        return
        except asyncio.CancelledError:
            self.logger.debug("Progress monitoring cancelled")
        except Exception as e:
            self.logger.error("Error in progress monitoring: %s", e)
        finally:
            self.logger.debug("Progress monitoring stopped") 