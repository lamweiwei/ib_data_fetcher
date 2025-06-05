"""
Symbol management utilities for the IB Data Fetcher.

This module provides symbol loading and management functionality that was previously
embedded in core/fetcher_job.py, following the principle of keeping files under 300 lines
and avoiding code duplication.
"""

import logging
from pathlib import Path
from typing import List

import pandas as pd

from utils.logging import get_logger


class SymbolManager:
    """Handles symbol loading and management operations."""
    
    def __init__(self, tickers_file_path: str = "config/tickers.csv"):
        """
        Initialize the symbol manager.
        
        Args:
            tickers_file_path: Path to the tickers CSV file
        """
        self.tickers_file_path = Path(tickers_file_path)
        self.logger = get_logger(__name__)
    
    def load_symbols_from_tickers(self) -> List[str]:
        """
        Load symbols from tickers.csv file.
        
        Returns:
            List of stock symbols
            
        Raises:
            FileNotFoundError: If tickers.csv file is not found
            ValueError: If tickers.csv file is malformed
        """
        try:
            if not self.tickers_file_path.exists():
                raise FileNotFoundError(f"Tickers file not found: {self.tickers_file_path}")
            
            df = pd.read_csv(self.tickers_file_path)
            
            # Validate that the required column exists
            if 'symbol' not in df.columns:
                raise ValueError(f"Tickers file must contain a 'symbol' column. Found columns: {list(df.columns)}")
            
            symbols = df['symbol'].tolist()
            
            # Remove any NaN or empty values
            symbols = [sym for sym in symbols if pd.notna(sym) and str(sym).strip()]
            
            if not symbols:
                raise ValueError(f"No valid symbols found in {self.tickers_file_path}")
            
            self.logger.info("Loaded %d symbols from %s", len(symbols), self.tickers_file_path)
            return symbols
            
        except pd.errors.EmptyDataError:
            raise ValueError(f"Tickers file is empty: {self.tickers_file_path}")
        except pd.errors.ParserError as e:
            raise ValueError(f"Failed to parse tickers file {self.tickers_file_path}: {e}")
        except Exception as e:
            self.logger.error("Failed to load symbols from %s: %s", self.tickers_file_path, e)
            raise
    
    def validate_symbols(self, symbols: List[str]) -> List[str]:
        """
        Validate and clean a list of symbols.
        
        Args:
            symbols: List of symbols to validate
            
        Returns:
            List of valid, cleaned symbols
        """
        if not symbols:
            return []
        
        valid_symbols = []
        for symbol in symbols:
            if not symbol or not isinstance(symbol, str):
                self.logger.warning("Skipping invalid symbol: %s", symbol)
                continue
            
            # Clean the symbol (remove whitespace, convert to uppercase)
            clean_symbol = str(symbol).strip().upper()
            
            if not clean_symbol:
                self.logger.warning("Skipping empty symbol after cleaning: %s", symbol)
                continue
            
            # Basic validation (alphanumeric and dots allowed for some symbols)
            if not clean_symbol.replace('.', '').replace('-', '').isalnum():
                self.logger.warning("Skipping symbol with invalid characters: %s", clean_symbol)
                continue
            
            valid_symbols.append(clean_symbol)
        
        self.logger.info("Validated %d symbols out of %d provided", len(valid_symbols), len(symbols))
        return valid_symbols
    
    def get_symbols_for_processing(self, requested_symbols: List[str] = None) -> List[str]:
        """
        Get symbols for processing, either from the provided list or from tickers.csv.
        
        Args:
            requested_symbols: Optional list of specific symbols to process
            
        Returns:
            List of symbols ready for processing
        """
        if requested_symbols:
            # Use provided symbols, but validate them first
            validated_symbols = self.validate_symbols(requested_symbols)
            self.logger.info("Using provided symbols: %s", validated_symbols)
            return validated_symbols
        else:
            # Load all symbols from tickers.csv
            symbols = self.load_symbols_from_tickers()
            validated_symbols = self.validate_symbols(symbols)
            self.logger.info("Loaded symbols from tickers.csv: %s", 
                           validated_symbols[:5] if len(validated_symbols) > 5 else validated_symbols)
            return validated_symbols 