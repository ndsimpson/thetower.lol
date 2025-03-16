# Error Handling & Logging

## Exception Handling
- Use specific exception types
- Avoid bare except
- Handle errors at appropriate level
- Provide meaningful error messages

## Logging Standards
### Log Levels
- DEBUG: Detailed debugging
- INFO: General information
- WARNING: Unexpected but handled
- ERROR: Failed operations
- CRITICAL: System failure

### Logging Pattern
```python
# Use BaseCog logger
self.logger.error(
    f"Operation failed: {error}",
    exc_info=True
)
```

## Task Tracking
- Use TaskTracker for operations
- Monitor task status
- Record performance metrics
- Handle task failures

## User Feedback
- Clear error messages
- Actionable instructions
- Appropriate error codes
- Status indicators
