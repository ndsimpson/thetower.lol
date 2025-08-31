# Bot TODO (short list)

This file is a short, prioritized checklist of small tasks we will work through.

- [ ] Finalize `ConfigManager` behavior
  - [ ] Ensure BOT_DATA_DIR handling and default config creation
  - [ ] Atomic saves + simple lock
  - [ ] Per-guild enabled/disabled cog lists

- [ ] Document and implement `PermissionManager` contract
  - [ ] JSON shape for `command_permissions`
  - [ ] Unit tests for permission resolution

- [ ] Implement `CogManager` features
  - [ ] Respect per-guild enablement via `ConfigManager`

- [ ] Move managers into `bot/managers/` and define interfaces
  - [ ] `ConfigStore` interface for easy swapping
  - [ ] `PermissionStore` interface

- [ ] Add management commands (config, cog, perm) for v2
  - [ ] Add per-guild cog enable/disable commands (`cog enable <cog>` / `cog disable <cog>`) that modify guild-specific lists


- [ ] Sync docs: add JSON schema snippets and small examples

Use this file as the working backlog; we'll add/remove items as we iterate.
