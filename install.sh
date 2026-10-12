#!/bin/sh
# llama-launcher installer for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.sh | sh
#
# What it does, and nothing else:
#   1. installs uv with Astral's official installer, if uv is not on PATH
#   2. finds the latest llama-launcher release on GitHub
#   3. installs it with `uv tool install` (uv fetches a suitable Python itself)
#
# No sudo. Run it again to update. Remove with:  uv tool uninstall llama-launcher
# Your config file is not touched by installing, updating or removing.
#
# Set LLAMA_LAUNCHER_SOURCE to a path or URL to install that instead of the
# latest release - which is how this script is tested.
#
# Everything is inside one function that is called on the last line, so a
# download that is cut off part-way defines nothing and runs nothing.

main() {
    set -eu
    repo="gabrieljakob/llama-server-launcher"

    say() { printf '%s\n' "$*"; }
    fail() { printf 'install: %s\n' "$*" >&2; exit 1; }
    have() { command -v "$1" >/dev/null 2>&1; }

    # Every download refuses to follow a redirect to plain HTTP.
    fetch() {
        if have curl; then
            curl --proto '=https' --tlsv1.2 -fsSL "$1"
        elif have wget; then
            wget --https-only -qO- "$1"
        else
            fail "curl or wget is required"
        fi
    }

    # The tag of the latest release, or nothing. .../releases/latest redirects
    # to .../releases/tag/<tag>. With no release it redirects to .../releases,
    # and for a repository that cannot be seen it is a 404.
    latest_tag() {
        url="https://github.com/$repo/releases/latest"
        final=""
        if have curl; then
            final=$(curl --proto '=https' --tlsv1.2 -fsSLI -o /dev/null \
                         -w '%{url_effective}' "$url" 2>/dev/null) || final=""
        elif have wget; then
            final=$(wget --https-only --max-redirect=0 -S --spider "$url" 2>&1 \
                    | sed -n 's/^ *[Ll]ocation: *\([^ ]*\).*/\1/p' \
                    | tr -d '\r' | tail -n 1) || final=""
        fi
        case "$final" in
            */releases/tag/*) printf '%s' "${final##*/releases/tag/}" ;;
        esac
    }

    if ! have uv; then
        say "uv not found - installing it with Astral's installer"
        fetch https://astral.sh/uv/install.sh | sh
        PATH="${XDG_BIN_HOME:-$HOME/.local/bin}:$PATH"
        export PATH
        have uv || fail "uv was installed but is not on PATH yet; open a new terminal and run this again"
    fi

    src="${LLAMA_LAUNCHER_SOURCE:-}"
    if [ -n "$src" ]; then
        say "installing llama-launcher from $src"
    else
        tag=$(latest_tag)
        [ -n "$tag" ] || fail "no published release of $repo was found"
        src="llama-launcher @ https://github.com/$repo/archive/refs/tags/$tag.tar.gz"
        say "installing llama-launcher $tag"
    fi

    # --force so that running this again is how you update.
    uv tool install --force --python '>=3.12' "$src"

    bin=$(uv tool dir --bin)
    say ""
    say "installed: $("$bin/llama-launcher" --version)"
    if have llama-launcher; then
        say "run it with:  llama-launcher"
    else
        say "llama-launcher is not on PATH in this shell yet."
        say "run:  uv tool update-shell   then open a new terminal and run:  llama-launcher"
    fi
}

main
