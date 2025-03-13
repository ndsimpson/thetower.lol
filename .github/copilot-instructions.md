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


# Standardized Settings and Info Command Patterns

## Settings Command
When implementing a `settings` command for a cog, follow these standardization patterns:

### Embed Structure
- **Title**: "{Feature Name} Settings"
- **Description**: "Current configuration for {feature description}"
- **Color**: `discord.Color.blue()`

### Settings Organization
Group settings into logical categories:
1. **Time Settings**: Format as `{hours}h {minutes}m {seconds}s ({total} seconds)`
   - Applies to intervals, durations, timeouts, etc.
2. **Display Settings**: User-facing configuration values
3. **Flag Settings**: Boolean settings with emoji indicators
   - `✅ Enabled` or `❌ Disabled`
4. **Threshold Settings**: Numerical limits or thresholds

### Status Information
- Include current operational status with appropriate emoji:
  - `✅ Ready` - System is fully operational
  - `⏳ Initializing` - System is loading
  - `🔄 Processing` - System is currently performing operations
  - `⏸️ Paused` - System is paused
  - `🔍 Dry Run Mode` - System is in test mode

### Time Representation
For timestamps and durations:
- Format absolute times as `YYYY-MM-DD HH:MM:SS`
- Format relative times as contextual strings:
  - `{n} seconds ago` (less than 1 minute)
  - `{n} minutes ago` (less than 1 hour)
  - `{n} hours ago` (1+ hour)

## Info Command
When implementing an `info` command for a cog:

### Core Elements
- **Title**: "{Feature Name} Information"
- **Description**: Brief explanation of the feature's purpose
- **Status Indicator**: Show current operational status with emoji
- **Last Updated**: When applicable, show last refresh time with relative time
- **Dependency Status**: If the feature relies on other cogs/services, show their status
- **Statistics**: Include relevant statistics about the feature's data/operations
- **Footer**: Optional usage hints or additional context

### Status & Warning Cases
- Use different embed colors to indicate status:
  - Blue (`discord.Color.blue()`) for normal operations
  - Orange (`discord.Color.orange()`) for warnings/initializing
  - Green (`discord.Color.green()`) for success messages
  - Red (`discord.Color.red()`) for errors

## Helper Methods
Consider implementing these utility methods in your cogs:
- `format_time_value(seconds)`: Formats seconds into hours, minutes, seconds
- `format_relative_time(timestamp)`: Shows time elapsed since a timestamp

## Multiple Embeds Pattern
For complex settings, consider using multiple embeds grouped by category:
1. Primary embed with core settings and status
2. Secondary embeds for detailed configuration groups

Remember that consistent formatting helps users quickly locate information across different bot features.