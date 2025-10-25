# GitHub Copilot Instructions for thetower.lol

## Python Coding Standards

### PEP 8 Compliance

-   Follow PEP 8 style guidelines strictly
-   Use 4 spaces for indentation (never tabs)
-   Keep line length to 79 characters maximum for code, 72 for comments
-   Use lowercase with underscores for function and variable names (`my_function`)
-   Use CamelCase for class names (`MyClass`)
-   Use UPPER_CASE for constants (`MAX_SIZE`)
-   Organize imports: standard library first, third-party second, local imports last

### DRY Principles (Don't Repeat Yourself)

-   Extract common functionality into reusable functions or classes
-   Avoid code duplication by creating shared utilities
-   Use configuration files or constants for repeated values
-   Refactor similar code patterns into generic solutions

### SOLID Principles

-   **Single Responsibility**: Each class/function should have one reason to change
-   **Open/Closed**: Open for extension, closed for modification
-   **Liskov Substitution**: Derived classes must be substitutable for base classes
-   **Interface Segregation**: Many specific interfaces are better than one general-purpose interface
-   **Dependency Inversion**: Depend on abstractions, not concretions

### Virtual Environments

-   Always use virtual environments for dependency isolation
-   Document virtual environment setup in README.md
-   Keep requirements.txt updated with exact versions
-   Use `.venv` directory name for consistency

### Version Control Best Practices

-   Make small, focused commits with clear messages
-   Use conventional commit format when possible
-   Keep commits atomic (one logical change per commit)
-   Write descriptive commit messages explaining the "why" not just the "what"
-   Use feature branches for new development
-   Ensure code is tested before committing

## Project-Specific Guidelines

### Code Structure

-   Follow the existing project structure in `components/` directory
-   Keep related functionality grouped together
-   Use descriptive module and file names
-   Maintain consistency with existing code patterns

### Error Handling

-   Use specific exception types rather than generic `Exception`
-   Include proper logging for debugging
-   Handle edge cases gracefully
-   Provide meaningful error messages

### Documentation

-   Write docstrings for all public functions and classes
-   Include type hints for function parameters and return values
-   Keep README.md updated with setup and usage instructions
-   Document any configuration requirements

### Testing

-   Write unit tests for new functionality
-   Follow existing test patterns in the project
-   Ensure tests are isolated and repeatable
-   Include both positive and negative test cases

## Development Environment

-   Development is conducted on Windows using PowerShell as the terminal
-   When generating terminal commands, format them appropriately for PowerShell
-   Use the `;` character to join multiple commands on a single line if needed
