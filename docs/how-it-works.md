# How ccswap works

## The pieces

```
                       ┌──────────────────────── ~/.ccswap ────────────────────────┐
                       │  work/config/.credentials.json      (saved logins)        │
                       │  personal/config/.credentials.json                        │
                       │  state/<account>.json               (usage, learned rates)│
  ccswap (watcher) ──▶ │  slots/1/config/                    (CLAUDE_CONFIG_DIR)   │
     │                 │     .credentials.json ──symlink──▶ work/…/.credentials    │
     │ spawns          │     settings.json, projects/, skills/, … ──▶ ~/.claude/…  │
     ▼                 └───────────────────────────────────────────────────────────┘
  claude  ── each request reads .credentials.json ──▶ Anthropic
     │
     ├─ status line: `ccswap _statusline`  (rate_limits of the current account, every reply)
     └─ StopFailure hook: `ccswap _hook`   (a turn failed: re-check usage now)
```

- **Accounts.** `ccswap add <name>` creates `~/.ccswap/<name>/config` and runs Claude
  Code with `CLAUDE_CONFIG_DIR` pointing there, so `/login` saves that account's
  credentials in its own folder. Shared items (settings, `CLAUDE.md`, skills, agents,
  plugins, hooks, projects/memory, history) are symlinks into `~/.claude`.
- **Slots.** Every `ccswap` session gets a slot, `~/.ccswap/slots/N/config`, which is
  used as its `CLAUDE_CONFIG_DIR`. The slot's `.credentials.json` is a symlink to the
  current account's saved login. The slot has its own `.claude.json`, seeded with the
  account's onboarding state, MCP servers and your folder-trust settings. Slots are
  reused once their session exits.
- **Watcher.** The `ccswap` process starts `claude`, then wakes every second to
  1. repair or save credentials (see below),
  2. start a usage poll for any account whose data is more than 3 minutes old (in the
     background, at most every 30 s),
  3. switch immediately if the current account is spent,
  4. once a minute (and at most once every `CCSWAP_REBALANCE_MIN` minutes), check
     whether another account is clearly more urgent.

## Why a live switch works

Claude Code re-reads its credentials file before it makes a request. That's how several
sessions stay in sync when one of them refreshes a token. Re-pointing the slot's symlink
therefore changes the account for the **next** request, with no restart. Each request
is independent, so the switch can even happen in the middle of a multi-step turn. The
only cost is that the prompt cache is per account, so the first request after a switch
writes the context to the cache again on the new account.

## Where usage numbers come from

| Source | When | What |
|---|---|---|
| Usage endpoint (`/api/oauth/usage`) | Every ~3 min per account, at start-up, after a failed turn, and on `ccswap ls` | Authoritative 5-hour and weekly utilisation and reset times, per-model weekly limits, and whether extra usage is on. Works for idle accounts too, while their access token is valid. |
| Status line `rate_limits` | Every reply, current account only | Near-real-time 5-hour and weekly percentages |

Status-line numbers are merged carefully:

- **Usage only goes up within a window.** Windows are identified by their reset time.
  A lower number with the same reset (from another session that hasn't caught up) is
  ignored, and so is a report from an older window.
- **Numbers that belong to another account are dropped.** Right after a switch, Claude
  Code still reports the previous account's numbers until the next reply. If a report's
  reset times match another account's windows, and not this one's, it's not recorded.

## Scheduling

Every account holds two pools of allowance. Both are measured in **% of that account's
week** so they can be compared:

- **Session pool** = what's left of the running 5-hour window, converted to weekly %
  and capped by the weekly allowance left:
  `min((100 − session%) × k, cap − week%)`. It's lost when the 5-hour window resets. An
  idle window has no session pool that expires.
- **Weekly pool** = `cap − week%`. It's lost when the weekly window resets.

`k` is how much of the week 1% of a session costs on that account's plan. It's learned
from the status line: the weekly % change divided by the session % change, within the
same windows. It starts at a guess of 0.10.

**Urgency** is the most allowance you'd lose per hour by not using the account:

```
urgency = min( max(session_pool / hours_to_session_reset,
                   weekly_pool  / hours_to_weekly_reset),
               your_pace × k )
```

The cap at `your_pace × k` matters. An account whose window resets in 20 minutes with
60% left looks extremely urgent, but you can't use that much in 20 minutes. Your pace
(session % per hour while you're actively working) is learned from the status line, and
starts at 40%/h. When several accounts hit that cap, the one with the higher uncapped
urgency (the sooner or bigger loss) wins.

**Rules**

1. An account is **spent** at `CCSWAP_THRESHOLD` (99%) of its 5-hour window, at its
   weekly cap (the threshold, unless capped), or at a per-model weekly limit for the
   model you're using.
2. If a **default account** is set and it isn't spent, use it. Always.
3. Otherwise, use the non-spent account with the highest urgency.
4. While running:
   - switch **immediately** when the current account is spent;
   - switch **back to the default** once it frees up;
   - otherwise switch only if another account is clearly more urgent
     (`> 1.25 × current + 0.2`, or tied at the pace cap with a 1.5× sooner loss), has at
     least 1 weekly-% of session room, and at least `CCSWAP_REBALANCE_MIN` minutes have
     passed since the last switch. Each switch costs a fresh prompt-cache write, so
     ccswap avoids switching back and forth.

The result is "earliest deadline first": whatever would expire first gets used first.
That's what keeps you from sitting idle waiting for a reset while another account's
allowance goes unused.

## Credentials

When Claude Code refreshes an OAuth token, or saves an MCP server login, it writes a
new `.credentials.json` **over** the symlink. The watcher notices within a second:

- If the file holds a valid token, ccswap asks `/api/oauth/profile` who owns it and
  saves the file to **that** account's login. A refresh that finishes just after a switch
  therefore can't be saved to the wrong account. If the profile call fails, the file is
  only trusted when no switch happened in the last two minutes.
- If the file is empty or expired (a failed refresh writes empty tokens), it's thrown
  away. The account's saved login is never overwritten with it.
- Then the symlink is restored.

ccswap never refreshes tokens itself and never sends them anywhere except Anthropic's
own API.

## Failed turns

The `StopFailure` hook runs when a turn ends with an API error. ccswap logs it and
immediately polls that account's real usage. If the account really is spent, the
watcher switches within a second. A temporary rate-limit error (`429`) on an account
with room left doesn't block it. If the poll can't be made, and the error message looks
like a usage limit, the account is blocked until its 5-hour reset (or for 15 minutes
if that isn't known). The next successful poll clears the block.

## Edge cases handled

- Two sessions on the same account: usage never goes backwards, and both follow token
  refreshes through the shared saved login.
- Two sessions on different accounts: each has its own slot and switches on its own.
- Windows that have already reset count as fresh, even before new data arrives.
- An account that has never been used is still ranked from polled data. Without a
  valid token it's ranked as a fresh account.
- Accounts with extra usage (pay-as-you-go overage) turned on are flagged in
  `ccswap ls`.
- Two accounts that are the same login are flagged by `ccswap add` and `ccswap doctor`.
- An existing status line is kept (run after ccswap's, on the next line) and restored
  by `ccswap uninstall`.
- `settings.json` is backed up before every `ccswap install`. Broken JSON is refused,
  not overwritten.
- Ctrl-C goes to Claude Code, not the watcher.
- A crash in the watcher's bookkeeping is logged to `~/.ccswap/state/errors.log` and
  never takes the session down.

## Files

| Path | Contents |
|---|---|
| `~/.ccswap/<account>/config/` | That account's login (`.credentials.json`, mode 600) and `.claude.json` |
| `~/.ccswap/slots/N/` | Slot config dir, current account, last switch time, owning PID |
| `~/.ccswap/state/<account>.json` | Last known usage, learned `k`, block state |
| `~/.ccswap/state/_pace.json` | Learned working pace |
| `~/.ccswap/state/stopfailure.log`, `errors.log` | Failed turns and watcher errors |
| `~/.ccswap/config.json` | Default account, caps, chained status line |
