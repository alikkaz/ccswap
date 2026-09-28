# ccswap

**Keep coding when a Claude Code account hits its limit.** ccswap runs Claude Code on
several subscription accounts and moves a *running* session to another account the
moment the current one is used up. There's no restart, no `/login`, and you don't lose
your context.

```
● work  │  session ━━━━━━━━━━ 97% resets in 1h 12m  │  week ━━━━━━━━── 81% resets Mon 22:00  │  Opus 5.5
                                    … one reply later …
● personal  │  session ━───────── 6% resets in 4h 51m  │  week ━━━━───── 38%/90% resets Fri 00:00  │  Opus 5.5
```

It looks at **both** the 5-hour session window and the weekly window of every account.
That urgency ranking chooses the best account to start with and which one comes next; a
running session stays on its current account until it is spent, avoiding needless prompt-
cache rewrites.

> ccswap is an independent tool. It isn't affiliated with or endorsed by Anthropic.
> See [Is this allowed?](#is-this-allowed) before using it.

---

## Features

- **Live switching.** Claude Code re-reads its login before every request. ccswap swaps
  that login under the running process, so the conversation, background tasks, shell
  state and open files all carry on.
- **Automatic recovery.** When a limit aborts a turn, ccswap switches to an available
  account and submits `continue`. If every account is spent, it waits for the earliest
  reset, selects the newly usable account and resumes the same chat automatically.
- **Expiry-aware scheduling.** Each account is ranked by how much allowance you would
  lose per hour by not using it. This combines the 5-hour and weekly reset times into
  one number ([details](docs/how-it-works.md#scheduling)).
- **Real usage data.** ccswap reads each account's usage from Anthropic (the same numbers
  `/usage` shows) every few minutes. That includes idle accounts, and use on claude.ai or
  other machines.
- **Default account.** Pick the account to use first. The others fill in only while it
  is spent, and ccswap moves back to it once it frees up.
- **Weekly caps.** Stop at, say, 90% of the weekly limit on accounts you share or
  also use elsewhere, so there's always room left on them.
- **Learns your pace.** It learns how fast you use a session and how much weekly allowance
  a session costs on each plan, so its choices get better as you work.
- **Status line** with the current account, both limits, reset countdowns and caps. An
  existing status line is kept and shown underneath.
- **Desktop notifications** on every switch, if `notify-send` is installed.
- **One file, no dependencies:** a single Python 3 script using only the standard library.

## Requirements

- **Linux or WSL.** macOS isn't supported yet, because Claude Code keeps logins in the
  macOS Keychain there instead of `~/.claude/.credentials.json`.
- **Claude Code** (`claude`) on your PATH, signed in with Claude subscriptions
  (Pro / Max / Team / Enterprise seats). API-key billing has no session limits to manage.
- **Python 3.9+**
- Two or more Claude accounts that you're allowed to use.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/alikkaz/ccswap/main/install.sh | bash
```

or from a clone:

```bash
git clone https://github.com/alikkaz/ccswap && cd ccswap && ./install.sh
```

The installer copies `ccswap` to `~/.local/bin` and runs `ccswap install`. That adds a
status line plus `StopFailure` and quota-notification hooks to
`~/.claude/settings.json`, after making a timestamped backup. Set `CCSWAP_NO_WIRE=1` to skip that step and run `ccswap install`
yourself later.

## Quick start

```bash
ccswap add work        # Claude Code opens: run /login with the work account, then /exit
ccswap add personal    # repeat for each account
ccswap doctor          # check the setup
ccswap ls              # see every account's usage and the pick order
ccswap                 # start Claude Code, exactly like `claude`
```

Every argument is passed through to Claude Code, so `ccswap --resume`, `ccswap -p "…"`,
`ccswap --model sonnet` and so on work as usual. Start sessions with `ccswap` instead of
`claude` whenever you want switching.

Your settings, `CLAUDE.md`, skills, agents, plugins, hooks, memory and conversation
history are **shared** by all accounts, because they stay in `~/.claude`. Only the
login differs.

## Commands

| Command | What it does |
|---|---|
| `ccswap [claude args…]` | Start Claude Code on the best account and switch live as limits run out |
| `ccswap use <name> [args…]` | Start on a specific account (it still switches when that one runs out) |
| `ccswap add <name>` | Add an account (opens Claude Code so you can `/login`) |
| `ccswap rm <name>` | Remove an account and its saved login |
| `ccswap ls` | Usage, caps, reset times, pick order and running sessions |
| `ccswap default [<name>\|none]` | Show or set the default account |
| `ccswap cap` | Show weekly caps |
| `ccswap cap <name> <pct\|reset>` | Cap one account's weekly use |
| `ccswap cap --others <pct\|reset>` | Cap every account except the default |
| `ccswap unblock <name>` | Clear a limit block that was set by a failed request |
| `ccswap doctor` | Check platform, Claude Code, wiring and logins |
| `ccswap install` / `uninstall [--purge]` | Wire into or unwire from `~/.claude/settings.json` (`--purge` also deletes saved logins) |

`ccswap ls` looks like this:

```
  account   email                  5h resets        7d   cap resets      status
★ work      me@company.com        100% 16:59      100%   99% Thu 20:59   spent until Thu 20:59
  personal  me@gmail.com            0% 17:19       17%   90% Fri 00:00   ok
  side      me@side-project.dev    34% 16:59       79%   90% Mon 21:59   ok

Pick order (default first, then most urgent):
  1. personal  [2.27 wk%/h] session 100% left, lost in 4.4h; week 73% left before the 90% cap, lost in 4.5d
  2. side      [1.62 wk%/h] session 66% left, lost in 4.1h; week 11% left before the 90% cap, lost in 1.4d
```

## Configuration

**Default account.** `ccswap default work`: this account is always used while it has
room. The others are only used while it is spent, and ccswap switches back when it frees
up.

**Weekly caps.** `ccswap cap --others 90` stops at 90% of the weekly limit on every
account except the default. `ccswap cap side 70` sets one account's cap. Caps only
apply to the weekly window. The 5-hour window always goes to the threshold below.

**Environment variables**

| Variable | Default | Meaning |
|---|---|---|
| `CCSWAP_THRESHOLD` | `99` | % of a window at which an account counts as spent |
| `CCSWAP_REBALANCE_MIN` | `10` | Minimum minutes between a switch and returning to the default |
| `CCSWAP_AUTO_CONTINUE` | `1` | Submit `continue` after a limit switch/reset; set to `0` to disable |
| `CCSWAP_HOME` | `~/.ccswap` | Where saved logins, slots and state live |
| `CCSWAP_CLAUDE_DIR` | `~/.claude` | The Claude config directory shared by all accounts |

## How it works (short version)

1. Every account has its own login in `~/.ccswap/<name>/config/.credentials.json`.
2. Each `ccswap` session runs Claude Code with `CLAUDE_CONFIG_DIR` set to a *slot*, a
   folder whose `.credentials.json` is a **symlink** to one account's login. Everything
   else in the slot is a symlink into `~/.claude`.
3. A watcher checks every second. When the account is spent (or the default account
   has room again), it re-points the symlink. The next request Claude Code makes goes
   out as the other account.
4. For an interactive launch, ccswap relays terminal input through a PTY. That lets the
   watcher submit `continue` after a failed turn, without restarting Claude Code.
5. Usage comes from Anthropic's usage endpoint (polled every few minutes for all
   accounts) and from the status line (on every reply for the current one).
6. When Claude Code refreshes a token it writes a new file over the symlink. ccswap asks
   Anthropic which account that token belongs to, saves it to that account and restores
   the symlink.

See **[docs/how-it-works.md](docs/how-it-works.md)** for the scheduling maths, the
edge cases handled, and the Claude Code behaviour ccswap relies on.

## Limitations

- **A single request can cross 100%.** If one large request pushes an account from under
  the threshold to over its limit, the request can still fail. In an interactive `ccswap`
  session, ccswap switches and submits `continue` automatically; typing anything while it
  waits cancels that queued submit.
- **Automatic submit is interactive-only.** Piped/print-mode launches have no terminal
  prompt to resume. Set `CCSWAP_AUTO_CONTINUE=0` to use manual `continue` instead.
- **Idle accounts' data can get stale.** ccswap never refreshes logins itself. Once an
  idle account's access token expires, its usage stays at the last known value (shown as
  "as of HH:MM") until you use it again. Reset times are still honoured.
- **Only `ccswap` sessions switch.** Sessions started with plain `claude` are unaffected.
- **The watcher must stay running.** If the `ccswap` process is killed while Claude Code
  keeps running, that session stops switching.
- **`/status` may show the first account's email** after a switch. Requests really do go
  out as the account shown in the status line.
- **Relies on current Claude Code behaviour.** It was tested with Claude Code 2.1.283. It
  depends on Claude Code re-reading `.credentials.json`, and on the status line's
  `rate_limits` field. A future release could change either. `ccswap doctor` helps
  diagnose problems.

## Is this allowed?

That depends on your plan's terms, so **read them first**. ccswap only automates what you
could do by hand with `/login`. It's meant for accounts that are genuinely yours to use,
for example a personal subscription plus a work seat assigned to you. Don't use it to
share one person's login among several people, or to get around limits in ways your
agreement with Anthropic forbids. Weekly caps help you leave room on accounts you
also use elsewhere. You're responsible for how you use it.

## Uninstall

```bash
ccswap uninstall            # remove the status line and hooks (restores your old status line)
ccswap uninstall --purge    # …and delete ~/.ccswap (saved logins and state)
rm ~/.local/bin/ccswap
```

## Development

```bash
python3 -m unittest discover -s tests -v
```

The tests cover scheduling, automatic reset recovery, default and cap rules, usage
bookkeeping, credential handling and install/uninstall. They use temporary directories and never touch your
real `~/.claude`.

## License

[MIT](LICENSE) © 2026 Ali Muhammed
