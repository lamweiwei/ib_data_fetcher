# 🔥 Consecutive Failure Handling Feature

## Overview

The IB Data Fetcher now includes intelligent consecutive failure tracking that automatically skips problematic symbols after a configurable number of consecutive failures. This prevents the system from getting stuck on symbols that consistently fail and improves overall efficiency.

## Feature Details

### Key Components

1. **`get_consecutive_failures()` method** in `BarStatusManager`
   - Counts consecutive ERROR statuses from most recent dates
   - Works backward through dates until a non-error status is found
   - Returns 0 for symbols with no records or recent successes

2. **Pre-processing Check** in `DataFetcherJob._process_symbol()`
   - Checks consecutive failures before starting symbol processing
   - Skips symbol entirely if it exceeds the failure limit
   - Logs warning with current failure count and limit

3. **Runtime Monitoring** during date processing
   - Tracks consecutive failures during the processing session
   - Checks after each failed date and can exit early
   - Resets consecutive failure count on any success

4. **Configurable Settings** in `config/settings.yaml`
   - `max_consecutive_failures`: Number of failures before skipping (default: 10)
   - `reset_on_success`: Whether to reset count on success (default: true)

### Behavior

#### Before Symbol Processing
```bash
# Symbol with existing failures - will attempt
INFO | Symbol AAPL has 3 consecutive failures, will attempt processing (limit: 10)

# Symbol with too many failures - will skip
WARNING | Skipping symbol PROBLEMATIC due to 12 consecutive failures (exceeds limit of 10)
```

#### During Symbol Processing
```bash
# Successful fetch resets counter
INFO | Completed 2024-03-18 for AAPL (245/500 - 49.0%)

# Failed fetch increments counter
WARNING | Failed 2024-03-17 for PROBLEMATIC (5 errors in session, 8 total consecutive failures)

# Reaching limit triggers early exit
ERROR | Skipping remaining dates for PROBLEMATIC due to 10 consecutive failures (limit: 10)
```

#### Final Status Reporting
```bash
# Normal completion
INFO | Completed processing for AAPL: 245 successful, 5 errors (98.0% success rate)

# Skipped due to failures
WARNING | Processing stopped for PROBLEMATIC due to 10 consecutive failures: 10 successful, 20 errors (33.3% success rate) - SYMBOL SKIPPED
```

## Configuration

### Settings File
```yaml
# config/settings.yaml
failure_handling:
  max_consecutive_failures: 10  # Skip symbol after this many consecutive failures
  reset_on_success: true        # Reset consecutive failure count on any success
```

### Environment-Specific Overrides
Different environments can have different failure tolerances:

```yaml
# config/settings-dev.yaml (more tolerant for development)
failure_handling:
  max_consecutive_failures: 20

# config/settings-prod.yaml (less tolerant for production)
failure_handling:
  max_consecutive_failures: 5
```

## Implementation Details

### Consecutive Failure Detection Logic

The `get_consecutive_failures()` method:
1. Loads all bar status records for the symbol
2. Sorts records by date in descending order (newest first)
3. Counts consecutive ERROR statuses from the most recent dates
4. Stops counting when encountering any non-error status (COMPLETE, EARLY_CLOSE, HOLIDAY)

```python
def get_consecutive_failures(self, symbol: str) -> int:
    records = self.load_bar_status(symbol)
    if not records:
        return 0
    
    # Sort by date in descending order (most recent first)
    sorted_records = sorted(records, key=lambda r: r.date, reverse=True)
    
    consecutive_failures = 0
    for record in sorted_records:
        if record.status == BarStatus.ERROR:
            consecutive_failures += 1
        else:
            # Stop counting when we hit a non-error status
            break
    
    return consecutive_failures
```

### Processing Flow Integration

1. **Symbol Start**: Check existing consecutive failures
2. **Date Processing**: Monitor failures during session
3. **Success Handling**: Reset consecutive failure tracking
4. **Failure Handling**: Increment count and check limit
5. **Early Exit**: Stop processing if limit reached
6. **Status Reporting**: Log final outcome with skip reason

## Testing

### Test Coverage
The feature includes 9 comprehensive tests in `tests/test_consecutive_failures.py`:

- Empty symbol (no records)
- Symbol with only successes
- Symbol with only errors
- Mixed records with recent errors
- Mixed records with recent successes
- Exactly 10 consecutive failures
- More than 10 consecutive failures
- EARLY_CLOSE breaks error streak
- HOLIDAY breaks error streak

### Test Scenarios
```python
# Test exactly 10 consecutive failures
consecutive_failures = bar_status_manager.get_consecutive_failures("TEN_ERRORS")
assert consecutive_failures == 10

# Test that EARLY_CLOSE breaks consecutive errors
# (after adding EARLY_CLOSE status to a symbol with prior errors)
consecutive_failures = bar_status_manager.get_consecutive_failures("EARLY_CLOSE")
assert consecutive_failures == 0
```

## Benefits

### Efficiency Improvements
- **Prevents Infinite Loops**: Avoids spending time on consistently problematic symbols
- **Better Resource Utilization**: Focuses processing time on symbols likely to succeed
- **Faster Overall Completion**: Skips symbols that would cause repeated delays

### Operational Benefits
- **Configurable Thresholds**: Adjust failure tolerance based on data quality requirements
- **Resumable Processing**: Skipped symbols can be retried in future runs if issues are resolved
- **Clear Logging**: Provides visibility into why symbols were skipped
- **Graceful Degradation**: System continues processing other symbols despite individual failures

### Data Quality
- **Identifies Problem Symbols**: Highlights symbols with consistent data issues
- **Maintains Data Integrity**: Only saves complete, validated datasets
- **Status Tracking**: Records detailed failure information for later analysis

## Usage Examples

### Default Behavior (10 failures)
```bash
python main.py  # Uses default limit of 10 consecutive failures
```

### Custom Configuration
```bash
# Use development configuration with higher tolerance
python main.py --config dev

# Use production configuration with lower tolerance  
python main.py --config prod
```

### Monitoring Results
```bash
# Check which symbols were skipped
grep "SYMBOL SKIPPED" logs/daily/daily.log

# Check consecutive failure counts
grep "consecutive failures" logs/daily/daily.log

# Review error patterns
grep "ERROR.*consecutive" logs/errors/error.log
```

## Future Enhancements

Potential improvements for this feature:

1. **Exponential Backoff**: Increase delay between retries for failing symbols
2. **Symbol Health Scoring**: Track long-term success rates and prioritize accordingly
3. **Failure Pattern Analysis**: Detect and report common failure causes
4. **Auto-Recovery Detection**: Automatically retry skipped symbols after time periods
5. **Notification System**: Alert when symbols are consistently failing
6. **Configurable Reset Conditions**: More sophisticated reset logic beyond simple success

## Related Files

- `utils/bar_status_manager.py`: Core failure tracking logic
- `core/fetcher_job.py`: Integration with symbol processing
- `config/settings.yaml`: Configuration settings
- `tests/test_consecutive_failures.py`: Comprehensive test suite
- `README.md`: User documentation
- `IMPROVEMENTS.md`: Overall project improvements 