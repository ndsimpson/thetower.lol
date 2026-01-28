# Pre-Migration Model Reference

**Date:** January 22, 2026
**Purpose:** Document the BEFORE state of KnownPlayer/PlayerId models prior to LinkedAccount/GameInstance migration

---

## Current Model Structure (BEFORE Migration)

### KnownPlayer Model

**File:** `src/thetower/backend/sus/models.py`

```python
class KnownPlayer(models.Model):
    name = models.CharField(max_length=100, blank=True, null=True)
    discord_id = models.CharField(max_length=50, blank=True, null=True)  # SINGLE discord account
    creator_code = models.CharField(max_length=50, blank=True, null=True)
    approved = models.BooleanField(blank=False, null=False, default=True)
    django_user = models.OneToOneField(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="known_player")
    history = HistoricalRecords()
```

**Key Points:**

- `discord_id` is a single CharField - one player = one Discord account
- `approved` controls whether player is validated
- `django_user` links to Django auth system (optional)
- Has `simple_history` tracking

**Methods:**

```python
def __str__(self):
    # Returns: "Name (primary_id) (django_username)"
    user_info = f" ({self.django_user.username})" if self.django_user else ""
    return f"{self.name} ({self.ids.filter(primary=True).first().id if self.ids.filter(primary=True).first() else ''}){user_info}"

@property
def is_linked_to_django_user(self):
    return self.django_user is not None
```

---

### PlayerId Model

**File:** `src/thetower/backend/sus/models.py`

```python
class PlayerId(models.Model):
    id = models.CharField(max_length=32, primary_key=True)  # Tower ID is the PK
    player = models.ForeignKey(KnownPlayer, null=False, blank=False, related_name="ids", on_delete=models.CASCADE)
    primary = models.BooleanField(default=False)  # Which ID to display for this player
    notes = models.TextField(null=True, blank=True, max_length=1000)
    history = HistoricalRecords()
```

**Key Points:**

- Direct FK to `KnownPlayer` via `player` field
- `related_name="ids"` - access via `known_player.ids.all()`
- `primary=True` indicates which ID to display when player has multiple (due to bugs/ID changes)
- Tower ID stored uppercase automatically

**Methods:**

```python
def save(self, *args, **kwargs):
    self.id = self.id.upper()  # Always uppercase
    super().save(*args, **kwargs)

def save_base(self, *args, force_insert=False, **kwargs):
    if force_insert and self.primary:
        # Ensure only one primary ID per player
        self.player.ids.filter(~Q(id=self.id), primary=True).update(primary=False)
    return super().save_base(*args, **kwargs)
```

---

## Current Relationships

```
KnownPlayer
├── discord_id (CharField) - stored directly on model
├── django_user (OneToOneField → User)
└── ids (reverse FK) → PlayerId
    └── player (ForeignKey → KnownPlayer)
```

**Cardinality:**

- 1 KnownPlayer : 1 discord_id (string field, not a relation)
- 1 KnownPlayer : N PlayerId (one-to-many via `player` FK)
- 1 KnownPlayer : 0-1 django_user (optional one-to-one)

---

## Common Query Patterns (BEFORE Migration)

### Pattern 1: Get player by Discord ID

```python
# Direct lookup
player = KnownPlayer.objects.get(discord_id="123456789")

# With error handling
try:
    player = KnownPlayer.objects.get(discord_id=discord_id_str)
except KnownPlayer.DoesNotExist:
    player = None

# Filter verified players with discord
players = KnownPlayer.objects.filter(
    discord_id__isnull=False
).exclude(
    discord_id=""
).filter(
    approved=True
)
```

**Locations:**

- `src/thetower/bot/cogs/validation/cog.py` (lines 59, 110, 340, 395, 435, etc.)
- `src/thetower/bot/cogs/validation/ui/settings.py` (line 146)
- `src/thetower/bot/cogs/validation/ui/core.py` (line 330)

### Pattern 2: Get player's Tower IDs

```python
# Get all IDs for a player
player_ids = player.ids.all()

# Get primary ID
primary_id = player.ids.filter(primary=True).first()

# Get all ID values as list
player_tower_ids = [pid.id for pid in player.ids.all()]

# Get primary ID value
primary_id_value = player.ids.filter(primary=True).first().id if player.ids.filter(primary=True).first() else None
```

**Locations:**

- `src/thetower/bot/cogs/validation/cog.py` (lines 186, 437, 682, 736)
- `src/thetower/web/historical/player.py` (line 80)
- `src/thetower/web/historical/namechangers.py` (line 20)

### Pattern 3: Check if Tower ID is already linked

```python
# Get PlayerId and check its player's discord
existing_player_id = PlayerId.objects.filter(id=player_id).select_related("player").first()
if existing_player_id and existing_player_id.player.discord_id != discord_id_str:
    # Already linked to different discord account
    pass

# Access player from PlayerId
player = player_id_obj.player
discord_id = player_id_obj.player.discord_id
```

**Locations:**

- `src/thetower/bot/cogs/validation/cog.py` (lines 50-51, 1063-1064)

### Pattern 4: Create/update player and IDs

```python
# Get or create player by discord_id
player, created = KnownPlayer.objects.get_or_create(
    discord_id=discord_id_str,
    defaults=dict(approved=True, name=author_name)
)

# Set all existing IDs to non-primary
PlayerId.objects.filter(player_id=player.id).update(primary=False)

# Create/update specific ID as primary
player_id_obj, created = PlayerId.objects.update_or_create(
    id=player_id,
    player_id=player.id,
    defaults=dict(primary=True)
)
```

**Locations:**

- `src/thetower/bot/cogs/validation/cog.py` (lines 59, 67, 70)

### Pattern 5: Get all players with Tower IDs

```python
# Get players and prefetch their IDs
players = KnownPlayer.objects.filter(
    discord_id__isnull=False
).exclude(
    discord_id=""
).select_related().prefetch_related("ids")

# Iterate and use IDs
for player in players:
    player_ids = list(player.ids.all())
    # Use player_ids...
```

**Locations:**

- `src/thetower/bot/cogs/validation/cog.py` (lines 183, 186)

### Pattern 6: Filter by primary IDs only

```python
# Get primary IDs matching conditions
PlayerId.objects.filter(
    <conditions> & Q(primary=True)
)
```

**Locations:**

- `src/thetower/web/historical/search.py` (lines 93, 144)

### Pattern 7: Get KnownPlayers from PlayerIds

```python
# Get PlayerIds, then get their players
player_ids = PlayerId.objects.filter(id__in=users)
known_players = KnownPlayer.objects.filter(ids__in=player_ids)

# Get all PlayerIds for those players
all_player_ids = PlayerId.objects.filter(player__in=known_players)
```

**Locations:**

- `src/thetower/web/historical/comparison.py` (lines 102, 104, 105)

### Pattern 8: Access in **str** methods

```python
# KnownPlayer.__str__ accesses primary ID
def __str__(self):
    return f"{self.name} ({self.ids.filter(primary=True).first().id if self.ids.filter(primary=True).first() else ''})"
```

**Locations:**

- `src/thetower/backend/sus/models.py` (line 50)

---

## Files That Query These Models

### Bot Code (High Priority)

- `src/thetower/bot/cogs/validation/cog.py` - **1000+ lines, many queries**
- `src/thetower/bot/cogs/validation/ui/core.py` - Player lookup modals
- `src/thetower/bot/cogs/validation/ui/settings.py` - Settings interfaces
- `src/thetower/bot/cogs/tourney_roles/cog.py` - Role assignment based on IDs
- `src/thetower/bot/cogs/player_lookup/cog.py` - Player stat lookups
- `src/thetower/bot/cogs/manage_sus/cog.py` - Moderation system

### Streamlit Web (Medium Priority)

- `src/thetower/web/historical/player.py` - Player detail pages
- `src/thetower/web/historical/search.py` - Player search
- `src/thetower/web/historical/comparison.py` - Player comparisons
- `src/thetower/web/historical/namechangers.py` - Players with multiple IDs
- `src/thetower/web/admin/` - Admin interfaces

### Background Services (Low Priority)

- `src/thetower/backend/tourney_results/import/` - CSV imports
- `src/thetower/backend/tourney_results/management/` - Management commands

### Scripts (Low Priority)

- `src/thetower/scripts/migrate_sus_to_moderation_records.py`
- `src/thetower/scripts/fix_sus_ban_conflicts.py`

---

## Django Admin Configuration

**File:** `src/thetower/backend/sus/admin.py`

```python
class KnownPlayerAdmin(SimpleHistoryAdmin):
    # Shows player list with customization
    # Has inline for PlayerId objects
```

**Key Points:**

- Uses `SimpleHistoryAdmin` for audit trail
- Likely has `PlayerId` as inline
- Will need to add `LinkedAccount` and `GameInstance` inlines after migration

---

## Migration Impact Summary

### HIGH IMPACT (Must Update)

1. **Validation Cog** - 40+ direct usages of `discord_id` and `player.ids`
2. **Role Assignment** - Needs to query primary game instance
3. **Admin Interface** - New inlines for LinkedAccount/GameInstance

### MEDIUM IMPACT (Should Update)

1. **Streamlit Pages** - Display logic for multiple instances
2. **Player Lookup** - Show all instances separately
3. **Comparison Tools** - Handle instance separation

### LOW IMPACT (Can Update Later)

1. **Scripts** - One-time migrations, rarely run
2. **Background Services** - Mostly read-only or write new data

---

## Key Behavioral Changes After Migration

### Before Migration:

```python
# Single player lookup
player = KnownPlayer.objects.get(discord_id="123456")
primary_id = player.ids.filter(primary=True).first()
```

### After Migration:

```python
# Multi-step lookup
linked_account = LinkedAccount.objects.get(platform='discord', account_id="123456")
player = linked_account.player
primary_instance = player.game_instances.filter(primary=True).first()
primary_id = primary_instance.player_ids.filter(primary=True).first()
```

### Before Migration:

```python
# All IDs for a player (same game instance)
all_ids = player.ids.all()
```

### After Migration:

```python
# Need to specify which instance or get all
primary_instance_ids = player.game_instances.filter(primary=True).first().player_ids.all()
# Or get ALL IDs across all instances
all_ids = PlayerId.objects.filter(game_instance__player=player)
```

---

## Helper Methods to Add for Backward Compatibility

```python
# On KnownPlayer model
@classmethod
def get_by_discord_id(cls, discord_id):
    """Backward compat: lookup by discord ID."""
    linked_account = LinkedAccount.objects.filter(
        platform=LinkedAccount.Platform.DISCORD,
        account_id=str(discord_id)
    ).first()
    return linked_account.player if linked_account else None

def get_primary_game_instance(self):
    """Get the primary game instance (determines roles)."""
    return self.game_instances.filter(primary=True).first()

def get_all_player_ids(self):
    """Get ALL PlayerIds across all game instances."""
    return PlayerId.objects.filter(game_instance__player=self)

def get_primary_player_id(self):
    """Get primary PlayerId from primary GameInstance."""
    primary_instance = self.get_primary_game_instance()
    if primary_instance:
        return primary_instance.player_ids.filter(primary=True).first()
    return None
```

---

## Testing Strategy

1. **Export current queries** - Save examples of current query outputs
2. **Run migration on dev copy** - Test data migration
3. **Update validation cog first** - Most critical code path
4. **Verify role assignment** - Ensure Discord roles still work
5. **Test Streamlit pages** - Check display logic
6. **Check admin interface** - Ensure usability maintained

---

**END OF REFERENCE DOCUMENT**

This document should be preserved as-is during migration to serve as reference for updating all query patterns across the codebase.
