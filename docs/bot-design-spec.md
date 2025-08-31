# Discord Bot Design Specification (Implementation-Agnostic)

This document specifies the design of a modular Discord bot intended to be (re)implemented by an LLM or developer without relying on existing source code. It defines goals, architecture, data shapes, commands, behaviors, lifecycle, and acceptance criteria.

## Goals and Scope

-   Provide a modular Discord bot with:
    -   Cog-based feature modules that can be loaded/unloaded/reloaded at runtime.
    -   Centralized permissions per command and channel, supporting public vs restricted use.
    -   Configurable command invocation types (prefix/slash/both/none), at global and per-command levels.
    -   Friendly error UX and structured logging.
    -   Optional initialization of a Django backend at startup.

Non-goals

-   Implementing business-specific feature cogs beyond management/operations.
-   Defining a database schema beyond configuration/permissions (default is file-based storage).

## Architecture Overview

-   Bot Core

    -   Initializes Discord intents and application identity (token, application ID).
    -   Optionally boots a Django environment before any bot initialization.
    -   Registers global command checks and lifecycle event listeners.
    -   Composes managers: Config Manager, Permission Manager, Command Type Manager, Cog Manager, File Monitor.

-   Managers

    -   Config Manager: persistent key-value and structured configuration; file-backed by default.
    -   Permission Manager: evaluates policy for commands/channels/users; supports wildcard rules.
    -   Command Type Manager: determines how commands are exposed (prefix/slash/both/none) and orchestrates slash command sync.
    -   Cog Manager: discovery, list, enable/disable, load/unload/reload with autostart and autoreload integration.

-   File Monitor

    -   Observes filesystem for changes to cogs and triggers safe reloads (debounced). Supports pause/resume.

-   Logging and Error UX
    -   UTC timestamps, configurable log level.
    -   User-facing embeds for common errors; optional channel logging for unknown command attempts and failures.

## Key Data Models (Storage-Agnostic)

-   Bot Configuration

    -   prefix: string (e.g., "$")
    -   error_log_channel: string (Discord channel ID) | null
    -   load_all_cogs: boolean
    -   enabled_cogs: string[]
    -   disabled_cogs: string[]
    -   auto_sync_commands: boolean
    -   command_type_mode: enum {prefix|slash|both|none} (default mode)
    -   command_types: map<string commandQualifiedName, enum> (per-command override)
    -   permission_owner_bypass: boolean
    -   permission_strict_channel: boolean
    -   permission_log_denied: boolean

-   Permissions Policy
    -   commands: map<string commandNameOrWildcard, CommandPermission>
    -   CommandPermission
        -   channels: map<string channelIdOrWildcard, ChannelPermission>
    -   ChannelPermission
        -   public: boolean
        -   authorized_users: string[] (user IDs), optional

Notes

-   Wildcards: command "_" applies to all commands; channel "_" applies to all channels. Specific entries override wildcard rules.
-   Qualified command names reflect subcommand paths (e.g., "group sub").

## Command Invocation Modes

-   Modes: prefix, slash, both, none.
-   Default mode is set globally; per-command overrides take precedence when present.
-   Slash Command Sync
    -   Rebuilds application command tree from registered commands where mode ∈ {slash, both}.
    -   Supports global and per-guild sync strategies.

## Command Catalog (Management and Operations)

-   settings

    -   Purpose: Display bot configuration and status (prefix, error channel, cog counts, intents, uptime, latency, servers).
    -   Output: An embed with well-structured sections.

-   config group

    -   prefix [new_prefix?]: view or set bot prefix (validate maximum length).
    -   error_channel [channel?]: view or set logging channel for command errors.
    -   toggle <setting> [bool?]: toggle recognized settings (e.g., debug_mode, verbose_logging).

-   command_type group

    -   set_default <mode>: set default command invocation mode.
    -   set <command> <mode>: set per-command mode override.
    -   reset <command>: remove per-command override (revert to default mode).
    -   sync: sync slash commands with Discord.

-   cog group

    -   list: list all cogs with status (loaded, enabled/disabled).
    -   enable <cog>: mark enabled and persist in configuration.
    -   disable <cog>: mark disabled and persist in configuration.
    -   load <cog>: load now.
    -   unload <cog>: unload now.
    -   reload <cog>: reload now.
    -   reload_all: reload all currently loaded cogs; report per-cog results.
    -   pause [bool?]: pause/resume the file watcher for autoreload.
    -   autoreload
        -   toggle: toggle global auto-reload behavior.
        -   toggle_cog <cog>: toggle per-cog auto-reload.
    -   toggle_autostart <cog>: toggle autostart flag for a cog.

-   perm group
    -   list [command?]: show permissions for a specific command or an overview.
    -   add_channel <command> <channel> [public=false]: allow command in channel; set public or restricted.
    -   remove_channel <command> <channel>: remove channel allowance for the command.
    -   add_user <command> <channel> <user>: authorize user for restricted channel.
    -   remove_user <command> <channel> <user>: remove authorization.
    -   set_public <command> <channel> <bool>: mark channel as public/restricted for the command.
    -   reload: reload permissions from configuration storage.
    -   alias_info [command?]: show alias mappings and permission summary.

Permissions for management commands

-   Restrict config/cog/perm administration to bot owners/admins; allow read-only views more broadly if desired (configurable).

## Global Permission Check (Contract)

Inputs

-   Command context (user, channel, guild, command qualified name).

Decision Steps

1. If owner bypass is enabled and the invoker is an owner → allow.
2. Determine command policy:

-   If a command-specific policy exists, use it.
-   Else, if wildcard command policy ("\*") exists, use it.
-   Else, default allow unless strict_channel is enabled.

3. Evaluate channel rule:

-   If channel policy exists (specific or wildcard):
    -   If public → allow.
    -   Else if user is in authorized_users → allow.
    -   Else → deny with typed exception.
-   Else if strict_channel enabled → deny; otherwise allow.

Outputs

-   Allow execution or raise a typed exception used by the error handler.

## Error Handling UX

-   NotOwner: Informative embed; log attempt with context.
-   CommandNotFound: Log unknown command; optionally post an embed to error_log_channel with user, channel, content, timestamp.
-   MissingPermissions (user/bot): Embed with missing permissions.
-   MissingRequiredArgument: Embed with usage line and first paragraph of help; include examples if available.
-   Unauthorized (custom typed exceptions): Channel message explaining the block; if the invoker is an owner, DM a summary of allowed channels/users for the command.

## Lifecycle and Events

-   Startup

    -   Set Django settings (if used) and initialize Django.
    -   Load configuration; initialize managers.
    -   Register global command check and lifecycle events.
    -   Start file monitor for cogs.
    -   Optionally auto-sync slash commands.

-   Ready

    -   Log bot identity and readiness.
    -   Load cogs if not already loaded; log loaded set.

-   Connect/Resume/Disconnect

    -   Log each lifecycle event for observability.

-   Shutdown
    -   Stop file monitor and perform cleanup.

## Discord Intents and Identity

-   Intents: message_content, members, presences (ensure they’re enabled in the developer portal as needed).
-   Environment variables
    -   DISCORD_TOKEN: required.
    -   DISCORD_APPLICATION_ID: required for slash commands support.
    -   LOG_LEVEL: optional (e.g., INFO, DEBUG).

## Observability

-   Logging

    -   UTC timestamps; per-module loggers; configurable level; avoid logging secrets.
    -   Log command attempts, errors, reload outcomes, and (optionally) denied permission checks.

-   Diagnostics
    -   The settings command returns a concise health summary (prefix, error channel, cog counts, intents, uptime, latency, servers).
    -   reload_all aggregates successes/failures in a single report.

## Non-Functional Requirements

-   Reliability: Handle transient Discord API errors; bound retries for slash sync.
-   Performance: Constant-time permission lookups; efficient, debounced file watch.
-   Security: Least-privilege Discord permissions; restrict management commands; no secret leakage in logs.
-   Extensibility: Cogs are drop-in; configuration backends can be swapped via an interface.
-   Testability: Managers decoupled from Discord runtime; support dependency injection for tests.

## Testing Strategy

-   Unit Tests

    -   Permission Manager: owner bypass, wildcard rules, public vs restricted, strict_channel behavior.
    -   Command Type Manager: default vs override; slash visibility calculations.
    -   Cog Manager: load/unload/reload flows; autostart flags; state persistence.
    -   Config Manager: read/write, defaults, and validation.

-   Integration Tests

    -   Global command check across contexts (DM vs guild, public vs restricted channel).
    -   Error handling surfaces (missing args; unknown command path).

-   Smoke Tests
    -   settings renders expected sections.
    -   command_type sync runs without modifying state when no slash-enabled commands exist.

## Acceptance Criteria

-   Startup initializes Django (if configured), configuration, managers, and file monitor without error.
-   Global check enforces permissions with owner bypass and strict modes; errors are user-friendly.
-   Cog operations work at runtime with correct feedback; file changes trigger reload when enabled.
-   Command type settings (default and per-command) govern slash/prefix exposure; sync applies without exceptions.
-   The management command catalog (settings, config, command_type, cog, perm) behaves as specified.
-   Logs include UTC timestamps, lifecycle events, errors, and optional denial logs; no secrets are logged.
-   Administration is restricted to owners/admins as configured.

## Extensibility Hooks

-   Config Store: allow swapping file-based storage for DB/API by injecting an interface.
-   Permission Resolution: add role-based or external policy layers as an extension point.
-   Slash Sync Strategy: support per-guild development vs global production sync.

## Glossary

-   Cog: Modular feature package (commands, listeners).
-   Public channel: Anyone can invoke the command in the channel.
-   Restricted channel: Only listed users can invoke the command in the channel.
-   Wildcard: Default rule applying broadly ("\*" for command or channel).
