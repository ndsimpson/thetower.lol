# Project Copilot Context

## Project Overview
- Python-based application using Django, Streamlit, and Discord integration
- Repository: thetower.lol
- Focus on clean, maintainable code with comprehensive documentation

## Technologies
- Python 3.10+
- Django 4.x (backend framework)
- Streamlit (data visualization and UI)
- Discord.py (Discord bot integration)

## Code Style Preferences
- Follow PEP 8 conventions
- Use 4 spaces for indentation
- Maximum line length: 88 characters (Black formatter compatible)
- Use type hints for all function parameters and return values
- Prefer f-strings over other string formatting methods
- Use snake_case for variables and functions
- Use PascalCase for classes
- Prefer double quotes over single quotes
- Use `is`, `is not` for comparison to `None`
- Use `==`, `!=` for equality comparison
- Use `isinstance()` for type checking
- Use `if not x` for empty containers or None
- Avoid mutable default arguments

## Code Quality
- Follow clean code principles
- Aim for single responsibility principle
- Use descriptive variable and function names
- Avoid magic numbers, use constants instead
- Use list comprehensions and generator expressions where appropriate
- Avoid deeply nested code blocks
- Refactor long functions into smaller, reusable parts

## Git Conventions
- Use feature branches for new features and bug fixes
- Commit messages should be descriptive and follow the 50/72 rule
- Use imperative mood in commit messages
- Squash commits before merging into main branch

## Documentation
- Docstrings: Google style
- Each function should have a docstring describing purpose, parameters, and return values
- Include examples in docstrings for complex functions
- Each module should have a module-level docstring

## Project Structure Conventions
- Django apps in separate directories
- Streamlit pages in `streamlit/` directory
- Discord bot using cogs-based architecture:
  - Cogs organized in `bot/cogs/` directory
  - Each cog is a class that inherits from `commands.Cog`
  - Related commands are grouped within appropriate cogs
  - Common functionality implemented in a `BaseCog` class
- Utility functions in `utils/` directory
- Tests in `tests/` directory parallel to implementation

## Error Handling
- Use specific exception types, avoid bare `except:`
- Log errors with appropriate severity levels
- User-facing errors should be clear and actionable

## Testing
- Write unit tests for all business logic
- Integration tests for API endpoints
- Use pytest as testing framework
- Aim for >80% test coverage on core functionality

## Shorthand Prompts
- "Add typing": Add type hints to function
- "Docstring": Generate Google-style docstring
- "Test this": Generate pytest unit tests for selected function
- "Refactor": Apply clean code principles while maintaining functionality
- "Discord command": Create a new Discord bot command with error handling
- "Django view": Create a Django view with appropriate patterns
- "Streamlit component": Create a Streamlit UI component

## Project Specific Guidelines
- **Imports**:
  - Don't leave unused imports behind
  - Use absolute imports for Discord cogs

- **Configuration Management**:
  - The ConfigManager class (primarily used in bot.py and basecog.py) handles application settings
  - Configuration files store infrequently changed application parameters
  - The settings file is saved as json format.

- **Data Persistence**:
  - Cogs with frequently updated user/runtime data should use self.data_directory from BaseCog
  - Save files store dynamic data that changes during normal application usage
  - Use appropriate serialization methods based on data complexity and access patterns
  - Preferred file formats are pickle and json

- **Discord Command Security**:
  - Command permissions are handled via the PermissionManager utility
  - Individual cogs should not have command predicates within the cogs themselves
