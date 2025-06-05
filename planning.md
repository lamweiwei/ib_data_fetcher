# 📘 Data Fetcher System Design

## 📌 Overview

A robust, production-ready tool for fetching 1-minute OHLCV historical stock data from the Interactive Brokers TWS API using `ib_async`. The system emphasizes:
- Data integrity
- Resumability
- Modularity
- Comprehensive logging

## 🏗️ Script Overview & Logic

### **Main Application Entry Point**

#### **`main.py` - Application Orchestrator**

**Purpose**: The main entry point that provides a command-line interface for the data fetching system.

**Process Flow**:
1. **Argument Parsing**: Handles command-line arguments (symbols, config, dry-run mode, etc.)
2. **Environment Setup**: Configures logging and determines environment (dev/test/prod)
3. **Job Management**: Initializes and manages the `AsyncDataFetcherJob`
4. **Progress Monitoring**: Runs a background task to monitor and report progress every 30 seconds
5. **Graceful Shutdown**: Handles Ctrl+C and SIGTERM signals gracefully

**Key Logic**:
- Can process all symbols from `tickers.csv` or specific symbols passed as arguments
- Supports dry-run mode to show what would be processed without actually fetching
- Implements graceful shutdown that allows current operations to complete
- Shows comprehensive progress and summary reports
- Provides automatic resume capability for interrupted sessions

**Command Line Interface**:
```bash
python main.py                    # Process all symbols from tickers.csv
python main.py AAPL MSFT         # Process specific symbols only
python main.py --dry-run          # Show what would be processed
python main.py --config dev       # Use dev environment configuration
```

---

### **Core Processing Modules**

#### **`core/fetcher_job.py` - Job Management & Orchestration**

**Purpose**: Manages the sequential processing of symbols and coordinates all data fetching operations.

**Process Flow**:
1. **Sequential Processing**: Processes one symbol at a time from the queue
2. **Progress Tracking**: Maintains detailed progress in `bar_status.csv` for each symbol
3. **Date Management**: Determines which dates need processing and manages resumability
4. **Status Management**: Tracks completion, errors, and current state
5. **Graceful Shutdown**: Responds to shutdown signals and completes current operations

**Key Logic**:
- **Resume Capability**: Can resume from where it left off using status files
- **Date Range Calculation**: Uses market calendar to determine valid trading dates
- **Error Handling**: Continues processing even if individual dates fail
- **Progress Monitoring**: Real-time tracking of completion percentages and success rates

**Status Tracking System**:
- Creates individual `bar_status.csv` files for each symbol in `data/{symbol}/` directories
- Records per-date status: `COMPLETE`, `EARLY_CLOSE`, `HOLIDAY`, `ERROR`, `PENDING`
- Tracks: date, status, expected_bars, actual_bars, last_timestamp, error_message, retry_count
- Enables precise resumability and detailed progress monitoring

**Job Processing Strategy**:
- Sequential processing of symbols from tickers.csv
- No parallel processing to respect API rate limits
- Simple sequential queue with robust error handling
- Progress tracking in bar_status.csv for each symbol

#### **`core/fetcher.py` - Core Data Fetching Engine**

**Purpose**: Handles the actual communication with Interactive Brokers API to fetch historical data.

**Process Flow**:
1. **Connection Management**: Establishes and maintains persistent connection to IB TWS/Gateway
2. **Rate Limiting**: Enforces 10-second intervals between requests
3. **Data Fetching**: Requests 1-minute bar data for specific dates
4. **Data Validation**: Validates received data before returning it
5. **Error Handling**: Implements retry logic and connection recovery

**Connection Management Strategy**:
- **Persistent Connection**: Maintains single connection throughout session
- **Connection Watchdog**: Monitors connection health every 30 seconds and auto-reconnects
- **Heartbeat Monitor**: Pings IB every 15 seconds to maintain connection
- **Auto-Recovery**: Implements exponential backoff for reconnection attempts
- **State Preservation**: Maintains job state through connection issues

**Rate Limiting Implementation**:
- **10-Second Intervals**: Uses `asyncio.sleep(10)` between requests
- **Request Logging**: Logs each request timestamp for monitoring
- **API Compliance**: Respects IB API limits to prevent account restrictions

**Data Fetching Logic**:
- **Single Day Requests**: Fetches exactly one day of data per request
- **UTC Timezone**: All requests use UTC timezone formatting
- **Retry Logic**: Up to 3 attempts for failed requests with exponential backoff
- **Data Validation**: Checks data dates and bar counts before accepting data

---

### **Utility Modules**

#### **`utils/contract.py` - IB Contract Management**

**Purpose**: Creates and manages Interactive Brokers contract objects for different security types.

**Contract Creation Logic**:
- **Stock Contracts (STK)**: Requires symbol, exchange, currency
- **Future Contracts (FUT)**: Requires additional expiration date and multiplier
- **Option Contracts (OPT)**: Requires strike price, expiration, call/put designation, multiplier
- **Field Validation**: Ensures all required fields are present before contract creation
- **CSV Integration**: Loads ticker definitions from `config/tickers.csv`

**Validation Strategy**:
- **Pre-Creation Validation**: Validates required fields using decorators
- **Security Type Handling**: Different validation rules for STK, FUT, OPT
- **Error Reporting**: Clear error messages for missing or invalid fields
- **Centralized Management**: Single source of truth for all contract creation

#### **`utils/environment.py` - Environment Configuration Management**

**Purpose**: Manages environment-specific configurations (dev/test/prod) with automatic detection and overrides.

**Environment Detection Logic**:
1. **Priority 1**: `IBD_ENVIRONMENT` environment variable (app-specific)
2. **Priority 2**: `ENVIRONMENT` environment variable (general)
3. **Priority 3**: Configuration file's development.environment setting
4. **Priority 4**: Default to 'dev' environment

**Configuration Loading Process**:
- **Environment-Specific Files**: `settings-dev.yaml`, `settings-test.yaml`, `settings-prod.yaml`
- **Fallback Strategy**: Falls back to base `settings.yaml` if environment-specific not found
- **Environment Variable Overrides**: Supports `IBD_HOST`, `IBD_PORT`, `IBD_CLIENT_ID` overrides
- **Validation**: Ensures configuration is valid for the target environment

#### **`utils/market_calendar.py` - Trading Calendar Management**

**Purpose**: Determines trading days, holidays, and expected bar counts using market calendars.

**Market Calendar Logic**:
- **Trading Day Detection**: Uses `pandas_market_calendars` to identify valid trading days
- **Market Hours Calculation**: Determines actual trading hours for each day
- **Day Type Classification**: Categorizes days as regular, early close, or holiday

**Expected Bar Count Calculation**:
- **Regular Trading Days**: 390 bars (9:30 AM - 4:00 PM ET = 6.5 hours × 60 minutes)
- **Early Close Days**: 
  - Short early close: 210 bars (3.5 hours)
  - Regular early close: 360 bars (6 hours)
- **Market Holidays**: 0 bars

**Market Schedule Information**:
- Provides comprehensive `MarketSchedule` objects with:
  - Trading day status
  - Market open/close times
  - Expected bar count
  - Day type classification
  - Trading minutes calculation

#### **`utils/validation.py` - Data Quality Validation Engine**

**Purpose**: Comprehensive validation of fetched data to ensure quality and integrity.

**Multi-Level Validation Process**:
1. **Structure Validation**: Ensures required columns (Open, High, Low, Close, Volume) exist
2. **Individual Bar Validation**: Validates price relationships and volume constraints
3. **Time Sequence Validation**: Ensures bars are in chronological order without gaps
4. **Market Calendar Validation**: Verifies bar count matches expected for the day type
5. **Data Quality Validation**: Checks for missing values, anomalies, and data consistency

**Price Relationship Validation**:
- **High Price Constraints**: High ≥ Open, High ≥ Close, High ≥ Low
- **Low Price Constraints**: Low ≤ Open, Low ≤ Close, Low ≤ High
- **Non-Negative Prices**: All prices must be positive
- **Volume Validation**: Non-negative volume, logical volume patterns

**Market Calendar Integration**:
- **Expected Bar Count Verification**: Compares actual bars with market calendar expectations
- **Trading Hours Validation**: Ensures data falls within valid trading hours
- **Holiday Handling**: Properly handles market holidays and early closures

#### **`utils/logging.py` - Centralized Logging System**

**Purpose**: Provides structured logging with rotation, multiple log levels, and organized output.

**Multi-Logger Architecture**:
- **Main Application Logger**: General operations and info (`logs/daily/daily.log`)
- **Error Logger**: Error-only logs for monitoring (`logs/errors/error.log`)
- **Debug Logger**: Detailed debugging information (`logs/daily/debug.log`)
- **Summary Logger**: Daily summary reports (`logs/summary/summary.log`)

**Logging Features**:
- **Structured Format**: Consistent timestamp, level, module, and message format
- **Log Rotation**: Prevents files from growing too large with automatic rotation
- **Console & File Output**: Configurable output to both console and files
- **Directory Organization**: Separate directories for different log types

**Log Format Structure**:
```
2024-03-20 10:30:45 | INFO | ib_fetcher.fetcher | AAPL | 2024-03-19 | Fetching data
```

---

### **Configuration System Architecture**

#### **Environment-Aware Configuration**
- **Base Configuration**: `config/settings.yaml` - Default settings and fallbacks
- **Environment-Specific**: 
  - `config/settings-dev.yaml` - Development environment settings
  - `config/settings-test.yaml` - Testing environment settings  
  - `config/settings-prod.yaml` - Production environment settings
- **Ticker Definitions**: `config/tickers.csv` - Symbol definitions and contract parameters

#### **Configuration Categories**:

**Connection Settings**:
- IB TWS/Gateway host, port, client ID
- Connection timeout and retry parameters
- Account type (paper/live) specification

**Rate Limiting Configuration**:
- Request intervals and timing
- Maximum requests per time period
- API compliance parameters

**Validation Rules**:
- Expected bar counts for different market conditions
- Price relationship validation parameters
- Data quality thresholds

**Logging Configuration**:
- Log levels for different components
- File rotation and retention policies
- Output formatting and destinations

**Retry and Error Handling**:
- Maximum retry attempts
- Backoff strategies and wait times
- Error escalation thresholds

---

## 🔄 Complete Data Flow Process

### **1. System Initialization Phase**
- Load environment-aware configuration
- Establish IB TWS/Gateway connection with watchdog
- Initialize logging system with structured output
- Load ticker definitions and validate contracts
- Set up signal handlers for graceful shutdown

### **2. Symbol Processing Queue**
- Build processing queue from `tickers.csv` or command-line arguments
- Initialize progress tracking structures
- Create data directories for each symbol
- Load existing progress from `bar_status.csv` files

### **3. Date Range Calculation**
- Use market calendar to determine valid trading dates
- Calculate date ranges from earliest available data to present
- Filter out already completed dates from status files
- Prioritize newest-to-oldest processing strategy

### **4. Sequential Data Fetching**
- Process one symbol at a time to respect rate limits
- For each symbol, process one date at a time
- Enforce 10-second intervals between API requests
- Log all request timestamps for monitoring

### **5. Data Request & Validation Pipeline**
- Create IB contract from ticker definition
- Format request with UTC timezone specifications
- Fetch exactly one day of 1-minute bar data
- Validate data integrity using comprehensive checks
- Verify bar count against market calendar expectations

### **6. Data Storage & Status Updates**
- Save validated data to organized CSV files (`data/{symbol}/{date}.csv`)
- Update `bar_status.csv` with processing results
- Record success, failure, or partial completion status
- Log detailed results for monitoring and debugging

### **7. Error Handling & Recovery**
- Implement retry logic with exponential backoff
- Continue processing remaining dates/symbols after errors
- Maintain detailed error logs for troubleshooting
- Preserve partial progress for resumability

### **8. Progress Monitoring & Reporting**
- Real-time progress updates every 30 seconds
- Completion percentage and success rate calculations
- Current processing status and ETA estimates
- Comprehensive final summary reports

### **9. Graceful Shutdown & Resumability**
- Handle shutdown signals (Ctrl+C, SIGTERM) gracefully
- Complete current operation before stopping
- Save all progress and status information
- Enable seamless resume from interruption point

---

## 🔧 Key Design Principles

### **1. Resilience & Reliability**
- Handles connection failures, API errors, and network issues
- Implements comprehensive retry logic with intelligent backoff
- Maintains data integrity through validation at multiple levels
- Provides robust error logging and monitoring capabilities

### **2. Resumability & State Management**
- Can resume from any interruption point using detailed status files
- Preserves processing state across connection failures
- Enables incremental data collection over extended periods
- Supports partial completion and intelligent restart logic

### **3. API Compliance & Rate Limiting**
- Strict adherence to IB API rate limits to prevent account restrictions
- Intelligent request spacing with monitoring and logging
- Graceful handling of API errors and temporary failures
- Connection management optimized for long-running operations

### **4. Data Quality & Integrity**
- Multi-level validation ensuring data accuracy and completeness
- Market calendar integration for realistic expectations
- Comprehensive price and volume validation rules
- Detailed quality reporting and error tracking

### **5. Monitoring & Observability**
- Structured logging with multiple output streams
- Real-time progress monitoring and reporting
- Comprehensive error tracking and debugging information
- Performance metrics and operational insights

### **6. Environment Awareness & Flexibility**
- Different behavior and settings for dev/test/prod environments
- Environment variable overrides for deployment flexibility
- Configurable parameters for different operational needs
- Support for both paper and live trading accounts

### **7. Operational Excellence**
- Clean startup, operation, and shutdown procedures
- Graceful handling of interruptions and system signals
- Comprehensive status reporting and progress tracking
- Production-ready logging and monitoring capabilities

This architecture ensures the system is production-ready for long-running data collection operations while maintaining the highest standards for data quality, system reliability, and operational monitoring.

## 📊 Data Specifications

### Contract Management
**Ticker Configuration (tickers.csv)**
- Stock-only configuration
- Required fields for stocks:
    * symbol: Stock symbol (e.g., AAPL)
    * secType: Always "STK"
    * exchange: Trading exchange (e.g., SMART)
    * currency: Currency code (e.g., USD)
- CSV format with headers matching required fields
- Example:
    ```
    symbol,secType,exchange,currency
    AAPL,STK,SMART,USD
    MSFT,STK,SMART,USD
    GOOGL,STK,SMART,USD
    ```

**Scope Limitation:**
- Initial version: stocks only
- Futures and options support: future versions
- Simplified contract management for stocks

**Trading Hours Strategy:**
- Use useRTH=True for all data fetching
- Rely on pandas_market_calendars for validation
- Market hours determined by exchange

### Data Format
**IB Historical Data Bars (1-minute)**
- BarData object fields:
    * date (str): ISO-like timestamp string (local time)
    * open (float): Opening price
    * high (float): Highest price
    * low (float): Lowest price
    * close (float): Closing price
    * volume (int): Total volume
    * barCount (int): Number of trades
    * average (float): Volume-weighted average price (VWAP)

**Storage Format:**
- Save data exactly as received from IB API
- No additional metadata or formatting
- Simple CSV with original headers
- Keep original timestamp format

**Data Processing Strategy:**
- Minimal Processing:
  * Convert IB BarData to pandas DataFrame
  * Keep all original fields
  * No data transformation
  * No data cleaning
- Save Process:
  * Direct save to CSV
  * Use pandas to_csv()
  * Keep original column names
  * No additional formatting

Example CSV row:
    ```
    timestamp,open,high,low,close,volume,barCount,average
    2024-03-20 09:30:00,150.25,150.30,150.20,150.28,1000,50,150.26
    ```

### Status Tracking
**Per-Symbol Status File**
- Each symbol has its own bar_status.csv
- Format:
    ```
    date,status,expected_bars,actual_bars,last_timestamp
    2024-03-20,COMPLETE,390,390,2024-03-20 16:00:00
    2024-03-21,EARLY_CLOSE,360,360,2024-03-21 13:00:00
    2024-03-22,ERROR,390,385,2024-03-22 15:45:00
    ```
- Status determination:
    * COMPLETE: expected_bars == actual_bars
    * EARLY_CLOSE: expected_bars == actual_bars (360 or 210)
    * ERROR: expected_bars != actual_bars

**Progress Tracking Strategy:**
- Status File Management:
  * Update bar_status.csv after each day's fetch
  * Append new status row for each attempt
  * Keep history of all attempts
- Resumption Logic:
  * Start from earliest ERROR or missing date
  * Skip COMPLETE dates
  * Retry ERROR dates
- Progress Updates:
  * Update status immediately after fetch
  * Record actual bar count
  * Store last timestamp
- Partial Progress:
  * No partial saves
  * Mark as ERROR if incomplete
  * Retry on next run

## ⚙️ System Configuration

### Project Structure
```
ib_data_fetcher/
├── config/                # Configuration files
│   ├── tickers.csv       # All ticker definitions
│   └── settings.yaml     # General settings
├── core/                 # Core functionality
│   ├── fetcher.py        # Main data fetching logic
│   └── fetcher_job.py    # Job management and scheduling
├── utils/                # Utility functions
│   ├── contract.py       # Contract management
│   ├── validation.py     # Data validation
│   └── logging.py        # Logging setup
├── data/                 # Data storage
│   └── {symbol}/        # One folder per symbol
│       ├── raw/         # Raw data files
│       │   └── YYYY-MM-DD.csv  # Daily data files
│       └── bar_status.csv      # Symbol-specific status tracking
├── logs/                 # Logging directory
│   ├── daily/           # Daily operation logs
│   ├── errors/          # Error logs
│   └── summary/         # Daily summary logs
├── requirements.txt      # Project dependencies
└── README.md            # Project documentation
```

### Configuration (settings.yaml)
```yaml
# IB TWS Connection Settings
connection:
  host: "127.0.0.1"
  port: 7497  # TWS paper trading port
  client_id: 1
  account_type: "paper"  # Paper trading account
  timeout: 30  # Connection timeout in seconds

rate_limit:
  requests_per_second: 0.1  # 1 request per 10 seconds
  max_requests_per_10min: 60

retry:
  max_attempts: 3
  wait_seconds: 10

# Data fetching strategy
data_fetching:
  direction: "newest_to_oldest"  # Fetch from newest to oldest data
  use_head_timestamp: true      # Use reqHeadTimeStamp to find earliest available data
  max_history_days: null        # Fetch maximum available data (no limit)

validation:
  expected_bars:
    regular_day: 390
    early_close: [360, 210]
    holiday: 0

logging:
  level: INFO  # DEBUG, INFO, WARNING, ERROR
  daily_rotation: true
  max_size_mb: 10
  backup_count: 5

# Development and Testing
development:
  test_each_feature: true       # Test each feature when implemented
  environment: "dev"            # dev, test, prod
  mock_api_for_tests: true      # Use mocked IB API for unit tests
```

## 🛠️ Tech Stack

### Core Dependencies
- **Python**: 3.11+
- **IB API**: 
  * `ib_async` (latest stable)
  * `ibapi` (for contract definitions)

### Data Processing
- **pandas**: 2.0.0+
  * Data manipulation and validation
  * CSV file handling
- **pandas_market_calendars**: 4.0.0+
  * Market calendar validation
  * Trading day detection
- **pytz**: 2023.3+
  * UTC timezone handling

### Configuration & Storage
- **PyYAML**: 6.0.1+
  * YAML config file parsing
- **python-dateutil**: 2.8.2+
  * Date parsing and manipulation
- **pathlib**: (built-in)
  * File path handling

### Logging & Monitoring
- **Python logging**: (built-in)
  * Structured logging
  * Log rotation
- **rich**: 13.0.0+
  * Enhanced console output
  * Progress bars
  * Error formatting

### Development Tools
- **pytest**: 7.0.0+
  * Unit testing
- **black**: 23.0.0+
  * Code formatting
- **isort**: 5.12.0+
  * Import sorting
- **mypy**: 1.0.0+
  * Type checking

## ⛓️ Constraints

- Only 1 request every 10 seconds
- Cannot fetch >1 day per request
- All API timestamps must be in UTC timezone format
- No retry queue; resume based on `bar_status.csv`
- Must handle early close days and market holidays
- Maximum 60 requests per 10 minutes
- Bar count requirements:
  * Regular day: 390 bars
  * Early close: 360 or 210 bars
  * Holiday: 0 bars

## 🧭 Design Principles

### Data Validation & Storage
- **Complete Data Only**
  * Save data only when fetched bar count matches expected count
  * Expected counts:
    * Regular trading day: 390 bars
    * Early close: 360 or 210 bars
    * Holiday: 0 bars
  * Reject and log incomplete data
  * Update bar_status.csv with appropriate status:
    * COMPLETE: All bars received
    * EARLY_CLOSE: Early close day with correct bar count
    * HOLIDAY: No trading day
    * ERROR: Incomplete or invalid data

### Resumability
- **Status-Based Resumption**
  * Read bar_status.csv to identify:
    * Missing dates
    * Incomplete data (ERROR status)
    * Early close days that need verification
  * Resume from last incomplete date
  * Skip already completed dates
  * Verify early close days against market calendar

### Storage Organization
- **Simple Storage Structure**
  * One CSV per day per symbol
  * Clear file naming convention: YYYY-MM-DD.csv
  * Organized by symbol folders
  * Status tracking per symbol

**File Organization Strategy:**
- Directory Structure:
  * /data/{symbol}/raw/YYYY-MM-DD.csv
  * /data/{symbol}/bar_status.csv
- File Naming:
  * Daily data: YYYY-MM-DD.csv
  * Status file: bar_status.csv
- File Handling:
  * Read-only for data files
  * Append-only for status file
  * No file locking needed (sequential writes)
- Permissions:
  * 644 for data files
  * 664 for status file
  
**Storage Strategy:**
- Store raw CSV files without compression
- Keep original data format as received from IB API
- Future Plan: Migrate to TimescaleDB for better time-series data management
- No backup strategy implemented in initial version

### Error Handling
- **Robust Error Management**
  * Clear error categorization
  * Detailed error logging
  * Maximum 3 retry attempts
  * 10-second wait between retries
  * Error status in bar_status.csv

**IB API Error Handling Strategy:**
- Log all IB API errors with their error codes and messages
- Simple retry strategy: retry all errors 3 times with 10s wait
- No special handling per error type - keep it simple
- Record error details in bar_status.csv for failed days
- Log format: "IB Error {code}: {message} - Symbol: {symbol}, Date: {date}"

### Logging
- **Comprehensive Logging**
  * Operation status
  * Error details
  * Performance metrics
  * Data validation results

### Code Organization
- **Modular Design**
  * Clear separation of concerns
  * Reusable components
  * Easy to maintain and extend
  * Well-documented code

---

> ⚠️ Use this planning file as the reference for all future tasks and implementations. Any conversation with the LLM about architecture, design, or purpose should begin by reviewing this `PLANNING.md` file.
