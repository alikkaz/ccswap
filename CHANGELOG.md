# Changelog

## Unreleased

- Make uninstall fail safely when Claude's settings are malformed, preserve the full
  pre-existing status-line configuration, and leave wiring untouched when `--purge`
  is refused because a ccswap session is still running.
- Stay on an account until it is spent. The watcher no longer moves a running session to
  another account just because that account's allowance expires sooner; urgency now only
  picks the next account. Returning to the default account once it has room is unchanged.
- `install` sets the status line's `refreshInterval` (30s). Claude Code only redraws the
  status line on conversation events, so an idle session kept showing its first usage numbers

## 0.1.0 — 2026-09-27

First release.

- Live account switching for running Claude Code sessions (no restart)
- Expiry-aware scheduling across 5-hour and weekly windows, with a learned pace and a learned per-plan cost ratio
- Default account and weekly caps
- Authoritative usage polling for every account
- Status line, `StopFailure` hook, desktop notifications
- `add`, `rm`, `use`, `ls`, `default`, `cap`, `unblock`, `install`, `uninstall`, `doctor`
