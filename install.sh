#!/usr/bin/env bash
# ccswap installer: puts `ccswap` on your PATH and wires it into Claude Code.
#
#   curl -fsSL https://raw.githubusercontent.com/alikkaz/ccswap/main/install.sh | bash
#
# Options (environment variables):
#   CCSWAP_BIN_DIR   where to install the command (default ~/.local/bin)
#   CCSWAP_REF       git branch or tag to install (default main)
#   CCSWAP_NO_WIRE=1 only install the command; don't touch ~/.claude/settings.json
set -euo pipefail

REPO="alikkaz/ccswap"
REF="${CCSWAP_REF:-main}"
BIN_DIR="${CCSWAP_BIN_DIR:-$HOME/.local/bin}"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

case "$(uname -s)" in
  Linux) ;;
  Darwin) die "macOS isn't supported yet: Claude Code keeps logins in the Keychain there, and ccswap needs them in ~/.claude/.credentials.json." ;;
  *) die "unsupported OS $(uname -s); ccswap runs on Linux and WSL." ;;
esac

command -v python3 >/dev/null || die "python3 is required (3.9 or newer)."
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || die "python3 is too old; 3.9 or newer is required."
command -v claude >/dev/null || die "Claude Code (the 'claude' command) is not on PATH. Install it first: https://code.claude.com"

mkdir -p "$BIN_DIR"
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$here" ] && [ -f "$here/bin/ccswap" ]; then
  say "Installing ccswap from $here"
  install -m 755 "$here/bin/ccswap" "$BIN_DIR/ccswap"
else
  say "Downloading ccswap ($REF)"
  url="https://raw.githubusercontent.com/$REPO/$REF/bin/ccswap"
  if command -v curl >/dev/null; then curl -fsSL "$url" -o "$BIN_DIR/ccswap.tmp"
  elif command -v wget >/dev/null; then wget -qO "$BIN_DIR/ccswap.tmp" "$url"
  else die "curl or wget is required."; fi
  chmod 755 "$BIN_DIR/ccswap.tmp" && mv "$BIN_DIR/ccswap.tmp" "$BIN_DIR/ccswap"
fi
say "Installed $BIN_DIR/ccswap ($("$BIN_DIR/ccswap" version))"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf '\nAdd %s to your PATH, e.g.\n  echo '\''export PATH="%s:$PATH"'\'' >> ~/.bashrc\n\n' "$BIN_DIR" "$BIN_DIR" ;;
esac

if [ "${CCSWAP_NO_WIRE:-}" != "1" ]; then
  "$BIN_DIR/ccswap" install
fi

