# Project Structure Guide

## Directory Layout
```
thetower.lol/
├── .github/             # GitHub specific files
│   ├── copilot/        # Copilot documentation
│   └── prompts/        # Template prompts
├── .streamlit/         # Streamlit configuration
├── components/         # Streamlit UI components
│   ├── live/          # Live data components
│   └── static/        # Static assets
├── discord_bot/       # Legacy Discord bot
├── fish_bot/         # Main Discord bot
│   ├── fish_bot/     # Bot implementation
│   ├── tests/        # Bot tests
│   └── setup.py      # Package config
├── thetower/         # Django backend
│   └── dtower/      # Main Django project
│       ├── sus/     # Suspicious activity app
│       ├── tourney_results/ # Tournament data app
│       └── thetower/ # Django settings
├── uploads/         # Tournament data uploads
└── tests/          # Project-wide tests
```

## Component Organization
### Discord Bot
- One cog per feature
- Shared utilities in utils/
- Configuration in JSON format

### Django Apps
- Modular application structure
- REST API endpoints
- Database models

### Streamlit Pages
- One file per page
- Shared components
- Data visualization

## Testing Structure
- Tests parallel implementation
- Integration test suites
- Fixtures in conftest.py
