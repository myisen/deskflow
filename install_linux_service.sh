#!/usr/bin/env bash
# install_linux_service.sh - run clipshare as a systemd service.
#
# Works on Fedora, UOS and any other systemd-based Linux distribution.
#
# For a clipboard-sharing daemon the RECOMMENDED setup is a per-user service:
# it runs inside your graphical session, so it can read/write the X11 or
# Wayland clipboard without extra DISPLAY/XAUTHORITY plumbing.
#
# Usage:
#   ./install_linux_service.sh install            # user service (recommended)
#   ./install_linux_service.sh status             # show service status
#   ./install_linux_service.sh uninstall          # stop + remove the service
#   sudo ./install_linux_service.sh install --system   # system-wide (before login)
#
# Logs:   journalctl --user -u clipshare -f
#         journalctl -u clipshare -f               (system mode)
set -euo pipefail

CLIPSHARE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(command -v python3 || echo /usr/bin/python3)"
ACTION="${1:-install}"
MODE="user"
if [[ "${2:-}" == "--system" ]]; then MODE="system"; fi

# Session environment that a graphical clipboard backend needs (used for
# system-wide mode; a user service inherits this from your session already).
SESSION_ENV=()
if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
    SESSION_ENV+=("Environment=WAYLAND_DISPLAY=$WAYLAND_DISPLAY")
    SESSION_ENV+=("Environment=XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}")
elif [[ -n "${DISPLAY:-}" ]]; then
    SESSION_ENV+=("Environment=DISPLAY=$DISPLAY")
    SESSION_ENV+=("Environment=XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}")
    [[ -n "${XAUTHORITY:-}" ]] && SESSION_ENV+=("Environment=XAUTHORITY=$XAUTHORITY")
fi

if [[ "$MODE" == "user" ]]; then
    DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/clipshare.service"
    CTRL=("systemctl" "--user")
    WANTED="default.target"
    UNIT_EXTRA=$'After=graphical-session.target\nWants=graphical-session.target'
else
    DEST="/etc/systemd/system/clipshare.service"
    CTRL=("systemctl")
    WANTED="multi-user.target"
    UNIT_EXTRA=""
fi

write_unit() {
    mkdir -p "$(dirname "$DEST")"
    cat > "$DEST" <<EOF
[Unit]
Description=clipshare - LAN clipboard sharing
After=network.target
${UNIT_EXTRA}

[Service]
Type=simple
ExecStart=$PYTHON $CLIPSHARE_DIR/clipshare.py
WorkingDirectory=$CLIPSHARE_DIR
$(printf '%s\n' "${SESSION_ENV[@]}")
# Stream stdout line-by-line so journalctl shows logs in real time.
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=${WANTED}
EOF
    echo "[*] Wrote $DEST"
}

case "$ACTION" in
    install)
        if ! command -v systemctl >/dev/null 2>&1; then
            echo "[!] systemctl not found - this system may not use systemd." >&2
            exit 1
        fi
        if [[ "$MODE" == "user" ]]; then
            # A user unit needs a running systemd user manager (normal in a GUI session).
            if ! "${CTRL[@]}" is-system-running >/dev/null 2>&1 \
               && ! "${CTRL[@]}" --version >/dev/null 2>&1; then :; fi
            "${CTRL[@]}" show-environment >/dev/null 2>&1 \
                || echo "[!] 'systemctl --user' is not responding. Are you in a graphical session?"
        fi
        write_unit
        "${CTRL[@]}" daemon-reload
        "${CTRL[@]}" enable --now clipshare
        echo "[*] clipshare service installed and started (${MODE} mode)."
        echo "[*] Check: ${CTRL[*]} status clipshare   | Logs: ${CTRL[*]} status clipshare"
        ;;
    status)
        "${CTRL[@]}" status clipshare --no-pager 2>&1 | head -30 || true
        ;;
    uninstall)
        "${CTRL[@]}" disable --now clipshare 2>/dev/null || true
        rm -f "$DEST"
        "${CTRL[@]}" daemon-reload
        echo "[*] clipshare service removed (${MODE} mode)."
        ;;
    *)
        echo "Usage: $0 {install|status|uninstall} [--system]" >&2
        exit 1
        ;;
esac
