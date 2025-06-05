"""
Main data fetching logic for Interactive Brokers historical data.

This module implements the core fetching functionality with:
- IB API connection management with watchdog
- Rate limiting (10-second intervals)
- Data validation and bar count verification
- Error handling and retry logic
- Status tracking and resumability

Rate Limit Strategy:
- 10-second wait between requests using asyncio.sleep(10)
- Wait starts after each request completes
- Log each request timestamp for monitoring

Connection Management Strategy:
- Persistent connection using ib_async
- Connection watchdog monitors health every 30 seconds
- Auto-reconnects if lost with exponential backoff
- Heartbeat mechanism pings every 15 seconds
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import pytz
from ib_async import IB, Contract, BarData, util

from utils.contract import ContractManager
from utils.logging import get_logger
from utils.market_calendar import MarketCalendar
from utils.validation import DataValidator
from utils.config_manager import get_config_manager
from utils.ib_connection_manager import IBConnectionManager


class IBDataFetcher:
    """
    Main data fetcher for Interactive Brokers historical data.
    
    Implements rate limiting, connection management, and data validation
    according to the planning specifications.
    """
    
    def __init__(self, config_path: str = "config/settings.yaml", environment: Optional[str] = None):
        """
        Initialize the data fetcher with configuration.
        
        Args:
            config_path: Path to configuration file (for backward compatibility)
            environment: Environment to use ('dev', 'test', 'prod'). If None, auto-detects.
        """
        # Use centralized configuration manager
        self.logger = get_logger(__name__)
        config_dir = Path(config_path).parent if config_path else None
        config_manager = get_config_manager(environment, config_dir)
        self.config = config_manager.load_config()
        self.logger.info("Loaded configuration for environment: %s", 
                       config_manager.environment)
        
        # Initialize connection manager
        self.connection_manager = IBConnectionManager(self.config)
        self.ib = self.connection_manager.get_ib_client()
        
        # Initialize components
        self.contract_manager = ContractManager()
        self.market_calendar = MarketCalendar()
        self.data_validator = DataValidator()
        
        # Load tickers for contract management
        try:
            self.contract_manager.load_tickers()
            self.logger.info("Loaded tickers for contract management")
        except Exception as e:
            self.logger.warning("Could not load tickers: %s", e)
        
        # Rate limiting
        self.last_request_time = 0
        self.rate_limit_wait = 10  # 10 seconds between requests
        
        self.logger.info("IBDataFetcher initialized")
    

    
    async def connect(self) -> bool:
        """
        Establish connection to IB TWS/Gateway with error handling.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        return await self.connection_manager.connect()
    
    async def disconnect(self):
        """Disconnect from IB TWS and cleanup tasks."""
        await self.connection_manager.disconnect()
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to IB."""
        return self.connection_manager.is_connected

    async def _enforce_rate_limit(self):
        """Enforce 10-second rate limit between requests."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.rate_limit_wait:
            wait_time = self.rate_limit_wait - time_since_last
            self.logger.debug("Rate limiting: waiting %.2fs", wait_time)
            await asyncio.sleep(wait_time)
        
        self.last_request_time = time.time()
    
    async def fetch_historical_data(
        self,
        contract: Contract,
        end_date: datetime,
        duration: str = "1 D",
        bar_size: str = "1 min",
        what_to_show: str = "TRADES",
        use_rth: bool = True
    ) -> Optional[List[BarData]]:
        """
        Fetch historical data for a single day.
        
        Args:
            contract: IB contract object
            end_date: Date to fetch data for (not ending date)
            duration: Duration string (default "1 D")
            bar_size: Bar size setting (default "1 min")
            what_to_show: Data type to fetch (default "TRADES")
            use_rth: Use regular trading hours only (default True)
            
        Returns:
            List of BarData objects or None if failed
            
        Note:
            The end_date parameter represents the date we want data FOR, not the ending date.
            We adjust it to ensure we get data for the correct trading day.
        """
        if not self.is_connected:
            self.logger.error("Not connected to IB TWS")
            return None
        
        try:
            # Enforce rate limiting
            await self._enforce_rate_limit()
            
            # Convert end_date to UTC if not already timezone-aware
            if end_date.tzinfo is None:
                # Assume naive datetime is in UTC
                end_date_utc = end_date.replace(tzinfo=timezone.utc)
            elif end_date.tzinfo != timezone.utc:
                # Convert to UTC
                end_date_utc = end_date.astimezone(timezone.utc)
            else:
                end_date_utc = end_date
            
            # To get data FOR a specific date, we need to request data ending at the close of that day
            # Set time to end of trading day (market close is typically 4:00 PM ET = 21:00 UTC)
            market_close_utc = end_date_utc.replace(hour=21, minute=0, second=0, microsecond=0)
            
            # Format end date for IB API (using UTC timezone)
            end_date_str = market_close_utc.strftime("%Y%m%d %H:%M:%S") + " UTC"
            
            self.logger.info(
                "Requesting historical data: %s %s %s ending %s (for date %s)",
                contract.symbol,
                duration,
                bar_size,
                end_date_str,
                end_date.strftime("%Y-%m-%d")
            )
            
            # Make the request with retry logic
            bars = await self._request_with_retry(
                contract, end_date_str, duration, bar_size, what_to_show, use_rth
            )
            
            if bars:
                # Validate that we got data for the correct date
                if not self._validate_data_date(bars, end_date):
                    self.logger.warning(
                        "Date validation failed for %s on %s - data may be for wrong date",
                        contract.symbol,
                        end_date.strftime("%Y-%m-%d")
                    )
                
                self.logger.info(
                    "Successfully fetched %d bars for %s on %s",
                    len(bars),
                    contract.symbol,
                    end_date.strftime("%Y-%m-%d")
                )
                return bars
            else:
                self.logger.warning(
                    "No data returned for %s on %s",
                    contract.symbol,
                    end_date.strftime("%Y-%m-%d")
                )
                return None
                
        except Exception as e:
            self.logger.error(
                "Error fetching historical data for %s on %s: %s",
                contract.symbol,
                end_date.strftime("%Y-%m-%d"),
                e
            )
            return None
    
    async def _request_with_retry(
        self,
        contract: Contract,
        end_date_str: str,
        duration: str,
        bar_size: str,
        what_to_show: str,
        use_rth: bool
    ) -> Optional[List[BarData]]:
        """
        Make historical data request with retry logic.
        
        Returns:
            List of BarData objects or None if all retries failed
        """
        max_attempts = self.config['retry']['max_attempts']
        wait_seconds = self.config['retry']['wait_seconds']
        
        for attempt in range(1, max_attempts + 1):
            try:
                bars = await self.ib.reqHistoricalDataAsync(
                    contract=contract,
                    endDateTime=end_date_str,
                    durationStr=duration,
                    barSizeSetting=bar_size,
                    whatToShow=what_to_show,
                    useRTH=use_rth,
                    formatDate=1
                )
                
                # Check if the result is valid
                if bars is None:
                    self.logger.warning("Request returned None for %s", contract.symbol)
                    return None
                
                # Check if the result is an error string (sometimes IB returns error strings)
                if isinstance(bars, str):
                    self.logger.error("IB API returned error string for %s: %s", contract.symbol, bars)
                    return None
                
                # Convert to list if successful and is a valid iterable
                if hasattr(bars, '__iter__'):
                    result = list(bars)
                    self.logger.debug("Successfully received %d bars for %s", len(result), contract.symbol)
                    return result
                else:
                    self.logger.error("Invalid response type for %s: %s", contract.symbol, type(bars))
                    return None
                
            except Exception as e:
                self.logger.warning(
                    "Request attempt %d/%d failed for %s: %s",
                    attempt,
                    max_attempts,
                    contract.symbol,
                    e
                )
                
                if attempt < max_attempts:
                    self.logger.info("Waiting %ds before retry", wait_seconds)
                    await asyncio.sleep(wait_seconds)
                else:
                    self.logger.error(
                        "All %d attempts failed for %s",
                        max_attempts,
                        contract.symbol
                    )
        
        return None
    
    def _validate_data_date(self, bars: List[BarData], expected_date: datetime) -> bool:
        """
        Validate that the returned bars are for the expected date.
        
        Args:
            bars: List of BarData objects
            expected_date: Date we expected to receive data for
            
        Returns:
            True if data is for the correct date, False otherwise
        """
        if not bars:
            return True  # Empty data is valid (could be holiday)
        
        try:
            # Get the date from the first bar
            first_bar_date = pd.to_datetime(bars[0].date).date()
            expected_date_only = expected_date.date()
            
            # Check if the data is for the expected date
            if first_bar_date == expected_date_only:
                return True
            else:
                self.logger.warning(
                    "Date mismatch: Expected %s, got data for %s",
                    expected_date_only,
                    first_bar_date
                )
                return False
                
        except Exception as e:
            self.logger.error("Error validating data date: %s", e)
            return False
    
    async def fetch_and_validate_day(
        self,
        symbol: str,
        date: datetime
    ) -> Tuple[bool, Optional[pd.DataFrame], str]:
        """
        Fetch and validate data for a single day.
        
        Args:
            symbol: Stock symbol
            date: Date to fetch data for
            
        Returns:
            Tuple of (success, dataframe, status_message)
        """
        try:
            # Get contract for symbol
            contract = self.contract_manager.get_contract(symbol)
            if not contract:
                return False, None, f"Failed to create contract for {symbol}"
            
            # Check if trading day
            if not self.market_calendar.is_trading_day(date):
                self.logger.info(
                    "Non-trading day for %s on %s",
                    symbol,
                    date.strftime("%Y-%m-%d")
                )
                return True, pd.DataFrame(), "HOLIDAY"
            
            # Fetch historical data
            bars = await self.fetch_historical_data(contract, date)
            
            if bars is None:
                return False, None, "Failed to fetch data"
            
            # Convert to DataFrame
            if not bars:
                # Empty result - might be holiday
                self.logger.info(
                    "No bars returned for %s on %s - treating as holiday",
                    symbol,
                    date.strftime("%Y-%m-%d")
                )
                return True, pd.DataFrame(), "HOLIDAY"
            
            # Check if bars is actually a list of BarData objects
            # Sometimes IB API returns error strings instead of BarData
            if isinstance(bars, str):
                error_msg = f"IB API returned error: {bars}"
                self.logger.error(error_msg)
                return False, None, f"ERROR: {error_msg}"
            
            if not isinstance(bars, (list, tuple)) or not bars:
                error_msg = f"Invalid bars format: {type(bars)} - {bars}"
                self.logger.error(error_msg)
                return False, None, f"ERROR: {error_msg}"
            
            # Validate each bar is actually a BarData object
            for i, bar in enumerate(bars):
                if not hasattr(bar, 'date') or not hasattr(bar, 'open') or not hasattr(bar, 'high') or not hasattr(bar, 'low') or not hasattr(bar, 'close'):
                    error_msg = f"Invalid bar data at index {i}: {type(bar)} - {bar}"
                    self.logger.error(error_msg)
                    return False, None, f"ERROR: {error_msg}"
            
            df = util.df(bars)
            
            # Validate that the data is for the correct date before proceeding
            if len(df) > 0:
                first_bar_date = pd.to_datetime(df.iloc[0]['date']).date()
                expected_date_only = date.date()
                
                if first_bar_date != expected_date_only:
                    error_msg = f"Date mismatch: Expected {expected_date_only}, got {first_bar_date}"
                    self.logger.error(error_msg)
                    return False, None, f"ERROR: {error_msg}"
            
            # Validate data
            validation_result = self.data_validator.validate_bar_data(df, symbol, date.strftime('%Y-%m-%d'))
            
            if validation_result.is_valid:
                status = self._determine_status(len(df), date)
                self.logger.info(
                    "Data validation successful for %s on %s: %d bars (%s)",
                    symbol,
                    date.strftime("%Y-%m-%d"),
                    len(df),
                    status
                )
                return True, df, status
            else:
                error_message = validation_result.message
                if validation_result.error_details:
                    error_message += f" (Details: {validation_result.error_details})"
                
                self.logger.error(
                    "Data validation failed for %s on %s: %s",
                    symbol,
                    date.strftime("%Y-%m-%d"),
                    error_message
                )
                return False, None, f"ERROR: {error_message}"
                
        except Exception as e:
            self.logger.error(
                "Error fetching/validating data for %s on %s: %s",
                symbol,
                date.strftime("%Y-%m-%d"),
                e
            )
            return False, None, f"ERROR: {str(e)}"
    
    def _determine_status(self, bar_count: int, date: datetime) -> str:
        """
        Determine status based on bar count and market calendar.
        
        Args:
            bar_count: Number of bars received
            date: Date of the data
            
        Returns:
            Status string (COMPLETE, EARLY_CLOSE, HOLIDAY, or ERROR)
        """
        expected_bars = self.config['validation']['expected_bars']
        
        if bar_count == 0:
            return "HOLIDAY"
        elif bar_count == expected_bars['regular_day']:
            return "COMPLETE"
        elif bar_count in expected_bars['early_close']:
            # Verify this is actually an early close day using the correct API
            date_str = date.strftime('%Y-%m-%d')
            day_type = self.market_calendar.get_day_type(date_str)
            from utils.market_calendar import MarketDayType
            if day_type in [MarketDayType.EARLY_CLOSE_SHORT, MarketDayType.EARLY_CLOSE_REGULAR]:
                return "EARLY_CLOSE"
            else:
                return "ERROR"
        else:
            return "ERROR"
    
    async def get_earliest_data_date(self, symbol: str) -> Optional[datetime]:
        """
        Get the earliest available data date for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Earliest available date or None if failed
        """
        try:
            contract = self.contract_manager.get_contract(symbol)
            if not contract:
                self.logger.error("Failed to create contract for %s", symbol)
                return None
            
            # Enforce rate limiting
            await self._enforce_rate_limit()
            
            self.logger.info("Getting earliest data date for %s", symbol)
            
            # Request head timestamp
            head_timestamp = await self.ib.reqHeadTimeStampAsync(
                contract, whatToShow="TRADES", useRTH=True, formatDate=2
            )
            
            if head_timestamp:
                # Parse the timestamp
                earliest_date = pd.to_datetime(head_timestamp).date()
                self.logger.info(
                    "Earliest data date for %s: %s",
                    symbol,
                    earliest_date
                )
                return datetime.combine(earliest_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            else:
                self.logger.warning("No head timestamp received for %s", symbol)
                return None
                
        except Exception as e:
            self.logger.error(
                "Error getting earliest data date for %s: %s",
                symbol,
                e
            )
            return None


# Async context manager for easy usage
class AsyncIBDataFetcher:
    """Async context manager wrapper for IBDataFetcher."""
    
    def __init__(self, config_path: str = "config/settings.yaml", environment: Optional[str] = None):
        self.fetcher = IBDataFetcher(config_path, environment)
    
    async def __aenter__(self):
        await self.fetcher.connect()
        return self.fetcher
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.fetcher.disconnect() 