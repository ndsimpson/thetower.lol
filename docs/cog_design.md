# Unified Advertise Cog: Design Architecture

## Executive Summary

The `unified_advertise` cog exemplifies a comprehensive architecture for complex Discord bot cogs that require rich user interfaces, multi-guild support, and sophisticated background processing. It serves as a reference implementation for building scalable, maintainable Discord bot features.

**Key Design Principles:**
- **Modular UI Architecture**: UI components separated by function and user role
- **Dual Settings Access**: Settings accessible via cog-specific commands and global bot settings
- **Multi-Guild Isolation**: Complete data and configuration isolation between Discord servers
- **Task-Based Processing**: Robust background task management with proper lifecycle handling

**When to Use This Pattern:**
- Complex cogs requiring rich, multi-step user interactions
- Features needing per-guild configuration and data isolation
- Systems requiring scheduled background processing
- Cogs expected to grow in complexity over time

## Core Architecture

### BaseCog Integration

The cog extends `BaseCog` to inherit standardized functionality:

```python
class UnifiedAdvertise(BaseCog, name="Unified Advertise"):
    """Combined cog for both guild and member advertisements."""

    # Settings view class for the cog manager
    settings_view_class = UnifiedAdvertiseSettingsView
```

**Inherited Capabilities:**
- Multi-guild settings management via `get_setting()`/`set_setting()`
- Data persistence with `load_data()`/`save_data_if_modified()`
- Task tracking with `task_tracker.task_context()`
- Error handling and logging infrastructure

### Dual Settings Access Pattern

The cog implements a **generic entry point** for settings that enables access through multiple pathways:

#### 1. Cog-Specific Access
```python
@app_commands.command(name="advertise", description="Manage your advertisements")
async def advertise_slash(self, interaction: discord.Interaction) -> None:
    # Direct access to advertisement management
    view = AdManagementView(self, user_id, guild_id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
```

#### 2. Global Settings Integration
```python
settings_view_class = UnifiedAdvertiseSettingsView
```

This `settings_view_class` attribute allows the cog to integrate with the bot's primary `/settings` command, providing a unified settings experience across all cogs.

**Benefits:**
- **Consistent UX**: Users can access settings through familiar global interface
- **Discoverability**: Settings appear in centralized location alongside other cog configurations
- **Maintenance**: Single implementation serves multiple access patterns

### UI Modularization by Function/Role

The UI is organized into logical modules based on **function and user role**:

```
unified_advertise/
├── ui/
│   ├── __init__.py      # Clean API exports
│   ├── core.py          # Core business logic (forms, constants)
│   ├── user.py          # User-facing interaction flows
│   ├── admin.py         # Administrative interfaces
│   └── settings.py      # Settings management views
```

#### Core Module (`core.py`)
- **Purpose**: Business logic and shared components
- **Contents**: Form modals, constants, reusable view components
- **Example**: `GuildAdvertisementForm`, `MemberAdvertisementForm`, `AdvertisementType`

#### User Module (`user.py`)
- **Purpose**: End-user interaction flows
- **Contents**: Views for regular users managing their own data
- **Example**: `AdManagementView` - main interface for users to create/manage ads

#### Admin Module (`admin.py`)
- **Purpose**: Administrative oversight and moderation
- **Contents**: Interfaces for administrators and moderators
- **Example**: `AdminAdManagementView` - admin tools for managing all advertisements

#### Settings Module (`settings.py`)
- **Purpose**: Configuration and setup interfaces
- **Contents**: Views for configuring cog behavior and preferences
- **Example**: `UnifiedAdvertiseSettingsView` - integrates with global settings system

**Modular Benefits:**
- **Separation of Concerns**: Each module has clear, focused responsibilities
- **Selective Implementation**: Not every cog needs all modules (e.g., simple cogs might only need `core` + `user`)
- **Team Development**: Multiple developers can work on different UI aspects simultaneously
- **Reusability**: Components can be imported independently for other cogs

## Component Breakdown

### Data Layer

**Multi-Guild Data Structures:**
```python
# Guild-specific cooldown tracking
self.cooldowns = {}  # {guild_id: {"users": {user_id: timestamp}, "guilds": {guild_id: timestamp}}}

# Global pending deletions with guild context
self.pending_deletions = []  # [(thread_id, deletion_time, author_id, notify, guild_id), ...]
```

**Settings-Based Persistence:**
- Uses BaseCog's settings system for configuration
- Guild-specific settings automatically isolated
- Data persistence handled by BaseCog infrastructure

### Task Layer

**Background Processing Tasks:**
```python
@tasks.loop(hours=1)
async def orphaned_post_scan(self) -> None:
    """Scan for orphaned advertisement posts."""

@tasks.loop(hours=168)  # Weekly
async def weekly_cleanup(self) -> None:
    """Clean up expired cooldowns."""

@tasks.loop(minutes=1)
async def check_deletions(self) -> None:
    """Process pending thread deletions."""
```

**Task Lifecycle Management:**
- Tasks started in `cog_initialize()`
- Proper cleanup in `cog_unload()`
- Error handling with `task_tracker.task_context()`

### UI Layer

**Modular Component Architecture:**
- Each UI module focuses on specific user roles/functions
- Clean imports through `__init__.py` with `__all__` declarations
- Consistent patterns for views, buttons, modals, and selects

**Interaction Patterns:**
- Ephemeral responses for user privacy
- Multi-step workflows (type selection → form → confirmation)
- Permission-based button visibility
- Timeout handling for abandoned interactions

### Command Layer

**Slash Command Integration:**
```python
@app_commands.command(name="advertise", description="Manage your advertisements")
@app_commands.guild_only()
async def advertise_slash(self, interaction: discord.Interaction) -> None:
    # Permission-based view selection
    if is_admin or is_bot_owner:
        view = AdminAdManagementView(self, guild_id)
    else:
        view = AdManagementView(self, user_id, guild_id)
```

**Permission Integration:**
- Role-based access control
- Bot owner privileges
- Guild-specific permissions
- Action-level permission checking

## Key Design Patterns

### Settings Integration Pattern

**Generic Settings Entry Point:**
```python
# In cog class
settings_view_class = UnifiedAdvertiseSettingsView

# Settings view integrates with global system
class UnifiedAdvertiseSettingsView(discord.ui.View):
    def __init__(self, guild_id: int):
        # Global settings interface
```

**Benefits:**
- **Unified Experience**: Settings accessible via `/settings` command
- **Consistency**: Same UI patterns across all cogs
- **Discoverability**: Centralized settings management

### UI Organization Pattern

**Function-Based Separation:**
```
# Core: Business logic, forms, constants
# - Shared across user types
# - Pure functionality, no permissions

# User: End-user interactions
# - Personal data management
# - Self-service workflows

# Admin: Administrative functions
# - Oversight and moderation
# - Bulk operations

# Settings: Configuration
# - Cog behavior setup
# - Global preferences
```

**Implementation Flexibility:**
- **Simple Cogs**: May only need `core` + `user` modules
- **Complex Cogs**: Can implement all modules as needed
- **Progressive Enhancement**: Start simple, add modules as complexity grows

### Data Management Pattern

**Guild Isolation:**
```python
def _ensure_guild_initialized(self, guild_id: int) -> None:
    """Ensure guild-specific data structures exist."""
    if guild_id:
        self.ensure_settings_initialized(guild_id=guild_id, default_settings=self.default_settings)
        if guild_id not in self.cooldowns:
            self.cooldowns[guild_id] = {"users": {}, "guilds": {}}
```

**Benefits:**
- **Complete Isolation**: No data leakage between servers
- **Scalability**: Supports hundreds of guilds efficiently
- **Flexibility**: Each guild can have different configurations

### Task Lifecycle Pattern

**Proper Task Management:**
```python
async def cog_initialize(self) -> None:
    # Start tasks
    if not self.background_task.is_running():
        self.background_task.start()

async def cog_unload(self) -> None:
    # Clean shutdown
    if hasattr(self, "background_task"):
        self.background_task.cancel()
```

**Benefits:**
- **Resource Management**: Prevents task leaks
- **Graceful Shutdown**: Proper cleanup on bot restart
- **Error Resilience**: Tasks can be restarted independently

## Implementation Guide

### For New Cogs

**1. Start with Core Structure:**
```python
class MyCog(BaseCog, name="My Cog"):
    settings_view_class = MySettingsView

    def __init__(self, bot):
        super().__init__(bot)
        self.default_settings = {
            "setting_name": "default_value"
        }
```

**2. Add UI Modules as Needed:**
```
my_cog/
├── ui/
│   ├── __init__.py
│   ├── core.py      # Forms, constants
│   └── user.py      # User interactions
└── cog.py
```

**3. Implement Essential Methods:**
- `cog_initialize()`: Start tasks, load data
- `cog_unload()`: Clean up resources
- `interaction_check()`: Permission validation

### Extensibility Points

**Adding New UI Components:**
- Create new modules in `ui/` directory
- Add exports to `__init__.py`
- Import in main cog file

**Adding New Settings:**
- Add to `default_settings` dict
- Create getter methods: `def _get_setting_name(self, guild_id: int)`
- Update settings view if needed

**Adding Background Tasks:**
- Define with `@tasks.loop()` decorator
- Start in `cog_initialize()`
- Cancel in `cog_unload()`

### Best Practices

**UI Design:**
- Use consistent naming patterns
- Implement timeout handling
- Provide clear user feedback
- Handle errors gracefully

**Data Management:**
- Always use guild isolation
- Leverage BaseCog's settings system
- Implement proper data validation

**Task Management:**
- Use `task_tracker.task_context()` for operations
- Handle exceptions within tasks
- Avoid blocking operations

**Code Organization:**
- Keep business logic in core modules
- Separate UI from data operations
- Use clear, descriptive names

## Common Pitfalls

**Avoid:**
- Mixing UI and business logic
- Global data without guild isolation
- Tasks without proper lifecycle management
- Inconsistent error handling

**Remember:**
- Always check `is_paused` in background tasks
- Use ephemeral responses for sensitive interactions
- Implement proper permission checking
- Test with multiple guilds

This architecture provides a solid foundation for building sophisticated Discord bot features while maintaining code organization and scalability.</content>
<parameter name="filePath">c:\Users\nicho\gitroot\thetower.lol\docs\unified_advertise_design.md