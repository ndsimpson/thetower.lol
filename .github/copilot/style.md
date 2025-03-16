# Code Style Guidelines

## Python Standards
- Python 3.10+ required
- Follow PEP 8 conventions
- 88 character line limit (Black compatible)
- 4 spaces for indentation
- No trailing whitespace
- Two blank lines before top-level classes/functions
- One blank line before class methods
- One blank line at the end of files

## Naming Conventions
- snake_case for functions and variables
- PascalCase for classes
- UPPER_CASE for constants
- Prefix private attributes with underscore
- Descriptive names over abbreviations

## String Formatting
- Prefer f-strings for variable interpolation
- Use regular strings for static text
- Double quotes over single quotes
- Multi-line strings use triple double quotes

## Type Hints
- Required for all function parameters
- Required for function return values
- Use Optional[] for nullable types
- Use Union[] for multiple types
- Use collections.abc for container types

## Best Practices
- Avoid mutable default arguments
- Use `is`, `is not` for None comparisons
- Use `==`, `!=` for value comparisons
- Use `isinstance()` for type checking
- Use `if not x` for empty containers

## Clean Code
- Single responsibility principle
- Descriptive variable names
- No magic numbers
- Use list/dict comprehensions
- Maximum 3 levels of nesting
- Functions under 50 lines

## Design Principles
### SOLID
- Single Responsibility: Classes should have one reason to change
- Open/Closed: Open for extension, closed for modification
- Liskov Substitution: Derived classes must be substitutable for base classes
- Interface Segregation: Clients shouldn't depend on unused methods
- Dependency Inversion: Depend on abstractions, not implementations

### Composition Over Inheritance
- Prefer object composition to inheritance hierarchies
- Use mixins and decorators when appropriate
- Build complex behavior from simple components
- Keep inheritance depth to maximum of 2 levels

### Additional Guidelines
- KISS (Keep It Simple, Stupid)
  - Favor readability over cleverness
  - Simple solutions over complex ones
  - Break complex problems into smaller parts

- YAGNI (You Ain't Gonna Need It)
  - Only implement features when needed
  - Avoid speculative generalization
  - Remove unused code and features

- Law of Demeter
  - Objects should only talk to immediate friends
  - Avoid chaining method calls
  - Reduce coupling between classes