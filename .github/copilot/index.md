# Project Copilot Guidelines

Core development guidelines for thetower.lol project.

## Quick Reference Guides
- [Code Style](style.md)
- [Discord Bot Patterns](discord.md)
- [Project Structure](structure.md)
- [Documentation Standards](docs.md)
- [Error Handling](errors.md)

## Core Style Guidelines
- Python 3.10+, Django 4.x, Discord.py
- Follow PEP 8 conventions
- 88 character line limit (Black compatible)
- Type hints required
- Use f-strings (except for static strings)
- snake_case for variables/functions
- PascalCase for classes
- Double quotes preferred

## Common Patterns
- Inherit from `BaseCog` for Discord commands
- Use `self.logger` from BaseCog for logging
- Store data using BaseCog's data utilities
- Follow ready state pattern for initialization
