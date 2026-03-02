#!/usr/bin/env bash
# Rikugan installer for Binary Ninja (Linux/macOS)
# Usage: ./install_binaryninja.sh [BN_USER_DIR]
#   BN_USER_DIR  Optional path to Binary Ninja user directory

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { printf "${CYAN}[*]${NC} %s\n" "$*"; }
ok()    { printf "${GREEN}[+]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[!]${NC} %s\n" "$*"; }
err()   { printf "${RED}[-]${NC} %s\n" "$*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

find_bn_user_dir() {
    local candidates=()
    if [[ "$(uname)" == "Darwin" ]]; then
        candidates+=("$HOME/Library/Application Support/Binary Ninja" "$HOME/.binaryninja")
    else
        candidates+=("$HOME/.binaryninja")
    fi
    for dir in "${candidates[@]}"; do
        if [[ -d "$dir" ]]; then
            echo "$dir"
            return 0
        fi
    done
    return 1
}

if [[ $# -ge 1 ]]; then
    BN_USER_DIR="$1"
    if [[ ! -d "$BN_USER_DIR" ]]; then
        err "Provided Binary Ninja directory does not exist: $BN_USER_DIR"
        exit 1
    fi
    info "Using provided Binary Ninja directory: $BN_USER_DIR"
else
    if BN_USER_DIR="$(find_bn_user_dir)"; then
        info "Auto-detected Binary Ninja directory: $BN_USER_DIR"
    else
        BN_USER_DIR="$HOME/.binaryninja"
        warn "No Binary Ninja directory found, defaulting to $BN_USER_DIR"
    fi
fi

PLUGINS_DIR="$BN_USER_DIR/plugins"
CONFIG_DIR="$BN_USER_DIR/rikugan"
SKILLS_DIR="$CONFIG_DIR/skills"
PLUGIN_LINK="$PLUGINS_DIR/rikugan"

if [[ ! -f "$SCRIPT_DIR/rikugan_binaryninja.py" ]] || [[ ! -f "$SCRIPT_DIR/plugin.json" ]]; then
    err "Binary Ninja plugin files missing in $SCRIPT_DIR"
    exit 1
fi

install_requirements() {
    local req="$SCRIPT_DIR/requirements.txt"
    local candidates=()

    # Optional explicit override
    if [[ -n "${BN_PYTHON:-}" ]]; then
        candidates+=("\"$BN_PYTHON\" -m pip")
    fi

    # Common Binary Ninja bundled Python locations + fallbacks
    candidates+=(
        "\"/Applications/Binary Ninja.app/Contents/Resources/bundled-python3/bin/python3\" -m pip"
        "\"/opt/binaryninja/bundled-python/bin/python3\" -m pip"
        "\"$HOME/binaryninja/bundled-python/bin/python3\" -m pip"
        "python3 -m pip"
        "python -m pip"
        "pip3"
        "pip"
    )

    for cmd in "${candidates[@]}"; do
        if eval "$cmd --version" >/dev/null 2>&1; then
            info "Installing Python dependencies with: $cmd"
            if eval "$cmd install --break-system-packages -r \"$req\""; then
                ok "Dependencies installed successfully"
                return 0
            fi
            warn "Dependency install failed with: $cmd"
        fi
    done
    return 1
}

if ! install_requirements; then
    err "Failed to install Python dependencies from requirements.txt"
    exit 1
fi

mkdir -p "$PLUGINS_DIR"
mkdir -p "$SKILLS_DIR"

BUILTINS_SRC="$SCRIPT_DIR/rikugan/skills/builtins"
if [[ -d "$BUILTINS_SRC" ]]; then
    info "Installing built-in skills into $SKILLS_DIR..."
    for skill in "$BUILTINS_SRC"/*/; do
        slug="$(basename "$skill")"
        dst="$SKILLS_DIR/$slug"
        if [[ -d "$dst" ]]; then
            ok "/$slug already exists, skipping (user copy preserved)"
        else
            cp -R "$skill" "$dst"
            ok "/$slug"
        fi
    done
else
    warn "Built-in skills not found at $BUILTINS_SRC, skipping"
fi

if [[ -L "$PLUGIN_LINK" ]]; then
    existing="$(readlink "$PLUGIN_LINK")"
    if [[ "$existing" == "$SCRIPT_DIR" ]]; then
        ok "Plugin symlink already installed"
    else
        warn "Removing stale symlink: $PLUGIN_LINK -> $existing"
        rm "$PLUGIN_LINK"
        ln -s "$SCRIPT_DIR" "$PLUGIN_LINK"
        ok "Plugin symlink updated: $PLUGIN_LINK -> $SCRIPT_DIR"
    fi
elif [[ -e "$PLUGIN_LINK" ]]; then
    warn "Backing up existing plugin directory to ${PLUGIN_LINK}.bak"
    mv "$PLUGIN_LINK" "${PLUGIN_LINK}.bak"
    ln -s "$SCRIPT_DIR" "$PLUGIN_LINK"
    ok "Plugin symlink created: $PLUGIN_LINK -> $SCRIPT_DIR"
else
    ln -s "$SCRIPT_DIR" "$PLUGIN_LINK"
    ok "Plugin symlink created: $PLUGIN_LINK -> $SCRIPT_DIR"
fi

echo ""
ok "Rikugan Binary Ninja plugin installed successfully!"
info "Plugin: $PLUGIN_LINK"
info "Config: $CONFIG_DIR/"
info "Skills: $SKILLS_DIR/"
echo ""
info "Restart Binary Ninja. Open: Tools -> Rikugan -> Open Panel."
