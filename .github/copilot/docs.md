# Documentation Standards

## Docstrings
### Google Style Format
```python
def function(arg1: str, arg2: int) -> bool:
    """Short description.

    Detailed description of function behavior.

    Args:
        arg1: Description of arg1
        arg2: Description of arg2

    Returns:
        Description of return value

    Raises:
        ValueError: Description of when this error occurs
    """
```

## Module Documentation
- Module-level docstring
- Purpose description
- Usage examples
- Dependencies list

## Code Comments
- Explain "why" not "what"
- Document complex algorithms
- Note potential issues
- Avoid obvious comments

## API Documentation
- Endpoint descriptions
- Request/response formats
- Authentication requirements
- Error responses
