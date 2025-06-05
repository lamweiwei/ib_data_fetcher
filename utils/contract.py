"""
Contract management for IB Data Fetcher.

This module handles the creation and validation of Interactive Brokers (IB) contracts.
A "contract" in IB terms is a specification that uniquely identifies a financial instrument
(stock, future, option, etc.).

Key concepts for junior developers:
- Each financial instrument (stock, future, option) has different required fields
- IB requires specific contract formats to fetch data correctly
- We validate contracts before using them to catch errors early
- Centralized contract management ensures consistency across the application

What is a contract?
- It's like an address for a financial instrument
- Just like you need a complete address to send mail, you need a complete
  contract to request data from Interactive Brokers
- Different types of instruments need different information
"""

import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional, Union
from ib_async import Contract, Stock, Future, Option

from utils.logging import get_logger
from utils.config_manager import get_config_manager
from utils.contract_validators import (
    validate_fields, 
    validate_ticker_format, 
    validate_security_type,
    validate_numeric_field,
    validate_date_format
)


class ContractManager:
    """
    Manages IB contract creation and validation.
    
    This class is responsible for:
    1. Loading ticker definitions from CSV files
    2. Creating proper IB contract objects from ticker data
    3. Validating that contracts have all required fields
    4. Providing easy access to contracts by type or symbol
    
    Why use a dedicated class for contract management?
    - Separation of concerns: All contract logic in one place
    - Reusability: Can be used by different parts of the application
    - Validation: Ensures contracts are properly formed before use
    - Flexibility: Easy to add support for new security types
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize contract manager.
        
        Args:
            config_path: Path to settings.yaml file (deprecated, use config_manager)
            
        The initialization process:
        1. Set up logging for this module
        2. Load configuration settings using centralized config manager
        3. Initialize empty ticker storage
        """
        # Get a logger specific to contract management
        self.logger = get_logger("ib_fetcher.contract")
        
        # Use centralized configuration manager
        config_dir = Path(config_path).parent if config_path else None
        self.config_manager = get_config_manager(config_dir=config_dir)
        self.config = self.config_manager.load_config()
        
        # Storage for ticker data - will be populated when load_tickers() is called
        self.tickers_df: Optional[pd.DataFrame] = None
        

    
    def load_tickers(self, tickers_path: Optional[str] = None) -> pd.DataFrame:
        """
        Load ticker definitions from CSV.
        
        Args:
            tickers_path: Path to tickers.csv file, or None for default
            
        Returns:
            DataFrame with ticker definitions
            
        This method:
        1. Loads the CSV file into a pandas DataFrame
        2. Validates the format and required fields
        3. Stores the DataFrame for later use
        4. Returns the DataFrame for immediate use if needed
        
        Why use pandas DataFrame?
        - Efficient handling of tabular data
        - Easy filtering and manipulation
        - Built-in CSV reading and validation
        - Integration with other data analysis tools
        """
        if tickers_path is None:
            # Use default location
            tickers_path = Path(__file__).parent.parent / "config" / "tickers.csv"
        
        try:
            # Load CSV into DataFrame with specific dtypes to prevent auto-conversion
            # Keep date fields as strings to avoid float conversion
            dtype_dict = {
                'symbol': 'str',
                'secType': 'str', 
                'exchange': 'str',
                'currency': 'str',
                'lastTradeDateOrContractMonth': 'str',
                'strike': 'str',
                'right': 'str',
                'multiplier': 'str'
            }
            
            self.tickers_df = pd.read_csv(tickers_path, dtype=dtype_dict)
            
            # Log successful loading for monitoring
            self.logger.info(f"Loaded {len(self.tickers_df)} tickers from {tickers_path}")
            
            # Validate the loaded data before proceeding
            validate_ticker_format(self.tickers_df)
            
            return self.tickers_df
            
        except Exception as e:
            # Log error and re-raise for calling code to handle
            self.logger.error(f"Failed to load tickers from {tickers_path}: {e}")
            raise
    

    
    def create_contract(self, ticker_row: Union[pd.Series, Dict]) -> Union[Stock, Future, Option]:
        """
        Create IB contract from ticker row.
        
        Args:
            ticker_row: Row from tickers DataFrame or dict with ticker data
            
        Returns:
            IB Contract object ready to use for data requests (Stock, Future, or Option)
            
        This is the main method that converts our ticker data into IB contracts.
        It acts as a "factory" that creates the right type of contract based
        on the security type.
        
        Why use a factory pattern?
        - Single entry point: One method to create any type of contract
        - Type safety: Ensures we create the right contract type
        - Extensibility: Easy to add new security types
        - Error handling: Centralized error handling for contract creation
        """
        # Convert pandas Series to dictionary for easier handling
        if isinstance(ticker_row, pd.Series):
            ticker_data = ticker_row.to_dict()
        else:
            ticker_data = ticker_row
        
        # Get the security type to determine which contract type to create
        sec_type = ticker_data["secType"]
        
        try:
            # Route to appropriate contract creation method based on type
            if sec_type == "STK":
                return self._create_stock_contract(ticker_data)
            elif sec_type == "FUT":
                return self._create_future_contract(ticker_data)
            elif sec_type == "OPT":
                return self._create_option_contract(ticker_data)
            else:
                # This should be caught by validation, but adding safety check
                raise ValueError(f"Unsupported security type: {sec_type}")
                
        except Exception as e:
            # Add context to error message for easier debugging
            symbol = ticker_data.get("symbol", "UNKNOWN")
            self.logger.error(f"Failed to create contract for {symbol}: {e}")
            raise
    
    @validate_fields(["symbol", "exchange", "currency"], "STK")
    def _create_stock_contract(self, ticker_data: Dict) -> Stock:
        """
        Create stock contract.
        
        Args:
            ticker_data: Ticker information dict
            
        Returns:
            Stock contract object
            
        Stock contracts are the simplest - they only need:
        - symbol: The stock ticker (e.g., "AAPL")
        - exchange: Where it trades (e.g., "NASDAQ", "NYSE", "SMART")
        - currency: What currency it's priced in (e.g., "USD")
        
        Why these fields?
        - symbol: Identifies the specific company
        - exchange: Some stocks trade on multiple exchanges
        - currency: Some companies trade in multiple currencies
        """
        # Create the IB Stock contract object
        # ib_async provides these convenient classes that handle IB API details
        contract = Stock(
            symbol=ticker_data["symbol"],
            exchange=ticker_data["exchange"],
            currency=ticker_data["currency"]
        )
        
        # Log contract creation for debugging
        self.logger.debug(f"Created stock contract: {ticker_data['symbol']}")
        return contract
    
    @validate_fields(["symbol", "exchange", "currency", "lastTradeDateOrContractMonth"], "FUT")
    def _create_future_contract(self, ticker_data: Dict) -> Future:
        """
        Create future contract.
        
        Args:
            ticker_data: Ticker information dict
            
        Returns:
            Future contract object
            
        Future contracts are more complex than stocks because:
        - They have expiration dates (lastTradeDateOrContractMonth)
        - They may have multipliers (contract size)
        - Multiple contracts exist for the same underlying (different expirations)
        
        Example: ES (S&P 500 E-mini) futures have contracts for different months
        like ES December 2024 (ESZ4), ES March 2025 (ESH5), etc.
        """
        # Build contract arguments dictionary
        # We build this dynamically because some fields are optional
        contract_args = {
            "symbol": ticker_data["symbol"],
            "exchange": ticker_data["exchange"],
            "currency": ticker_data["currency"],
            "lastTradeDateOrContractMonth": ticker_data["lastTradeDateOrContractMonth"]
        }
        
        # Add multiplier if provided
        # multiplier determines contract size (e.g., ES futures = 50 * index value)
        # Check if multiplier exists and is not empty
        if ("multiplier" in ticker_data and 
            pd.notnull(ticker_data["multiplier"]) and 
            ticker_data["multiplier"].strip() != ""):
            # Convert to int because IB expects integer multipliers
            contract_args["multiplier"] = int(ticker_data["multiplier"])
        
        # Create the contract using unpacked arguments
        # **contract_args unpacks the dictionary into keyword arguments
        contract = Future(**contract_args)
        
        self.logger.debug(f"Created future contract: {ticker_data['symbol']}")
        return contract
    
    @validate_fields(["symbol", "exchange", "currency", "lastTradeDateOrContractMonth", "strike", "right"], "OPT")
    def _create_option_contract(self, ticker_data: Dict) -> Option:
        """
        Create option contract.
        
        Args:
            ticker_data: Ticker information dict
            
        Returns:
            Option contract object
            
        Option contracts are the most complex because they need:
        - All the basic fields (symbol, exchange, currency)
        - Expiration date (lastTradeDateOrContractMonth)
        - Strike price (the price at which the option can be exercised)
        - Right (C for Call, P for Put)
        - Multiplier (typically 100 for stock options)
        
        Example: AAPL Dec 2024 $150 Call option
        - symbol: AAPL
        - lastTradeDateOrContractMonth: 20241220
        - strike: 150.0
        - right: C
        - multiplier: 100
        """
        # Build contract arguments
        contract_args = {
            "symbol": ticker_data["symbol"],
            "exchange": ticker_data["exchange"],
            "currency": ticker_data["currency"],
            "lastTradeDateOrContractMonth": ticker_data["lastTradeDateOrContractMonth"],
            # Strike must be a float (decimal number)
            "strike": float(ticker_data["strike"]),
            # Right is "C" for Call or "P" for Put
            "right": ticker_data["right"]
        }
        
        # Add multiplier if provided (usually 100 for stock options)
        if ("multiplier" in ticker_data and 
            pd.notnull(ticker_data["multiplier"]) and 
            ticker_data["multiplier"].strip() != ""):
            contract_args["multiplier"] = int(ticker_data["multiplier"])
        
        contract = Option(**contract_args)
        
        self.logger.debug(f"Created option contract: {ticker_data['symbol']}")
        return contract
    

    
    def get_contract(self, symbol: str) -> Optional[Contract]:
        """
        Get contract for a specific symbol.
        
        Args:
            symbol: Symbol to get contract for
            
        Returns:
            IB Contract object or None if symbol not found
            
        This is the main method used by the fetching logic.
        It finds the symbol in our loaded tickers and creates
        the appropriate contract type.
        
        Why return Optional?
        - Not all symbols may be in our tickers file
        - Allows calling code to handle missing symbols gracefully
        - Prevents exceptions for invalid symbols
        """
        if self.tickers_df is None:
            raise ValueError("No tickers loaded. Call load_tickers() first.")
        
        # Find the symbol in our DataFrame
        # This uses pandas boolean indexing to find matching rows
        symbol_rows = self.tickers_df[self.tickers_df["symbol"] == symbol]
        
        if symbol_rows.empty:
            self.logger.warning(f"Symbol {symbol} not found in tickers")
            return None
        
        # Get the first (should be only) matching row
        # iloc[0] gets the first row by position
        ticker_row = symbol_rows.iloc[0]
        
        try:
            return self.create_contract(ticker_row)
        except Exception as e:
            self.logger.error(f"Failed to create contract for {symbol}: {e}")
            return None 