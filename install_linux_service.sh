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
#   ./install_linux_service.sh install                  # user service (recommended)
#   ./install_linux_service.sh status                   # show service status
#   ./install_linux_service.sh restart                  # restart the service
#   ./install_linux_service.sh uninstall                # stop + remove the service
#   ./install_linux_service.sh preview [--system]       # print the unit without installing
#   sudo ./install_linux_service.sh install --system    # system-wide (before login)
#
# System-wide options (used with --system):
#   --user <name>    run the service as this OS user (default: auto-detect the
#                    user owning the graphical desktop session; fallback: the
#                    user who invoked sudo)
#   --log-dir <dir>  where logs are written (default: /var/log/clipshare;
#                    falls back to <repo>/logs when not writable)
#   --recv-dir <dir> where received files are stored (default: <repo>/clipshare_recv)
#
# In system mode the graphical session environment (WAYLAND_DISPLAY / DISPLAY /
# XAUTHORITY / XDG_RUNTIME_DIR / DBUS_SESSION_BUS_ADDRESS) is detected from the
# target user's running desktop processes, so the unit works even when installed
# over SSH.
#
# Logs:   journalctl --user -u clipshare -f     (user mode)
#         journalctl -u clipshare -f            (system mode)
set -euo pipefail

CLIPSHARE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(command -v python3 || echo /usr/bin/python3)"
ACTION="${1:-install}"

# ---- parse options: [--system] [--user NAME] [--log-dir DIR] [--recv-dir DIR] ----
MODE="user"
RUN_AS_USER=""
LOG_DIR=""
RECV_DIR=""
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
    case "${args[$i]}" in
        --system)     MODE="system" ;;
        --user)       RUN_AS_USER="${args[$((i+1))]:-}"; ((i++)) ;;
        --log-dir)    LOG_DIR="${args[$((i+1))]:-}"; ((i++)) ;;
        --recv-dir)   RECV_DIR="${args[$((i+1))]:-}"; ((i++)) ;;
        --user=*)     RUN_AS_USER="${args[$i]#*=}" ;;
        --log-dir=*)  LOG_DIR="${args[$i]#*=}" ;;
        --recv-dir=*) RECV_DIR="${args[$i]#*=}" ;;
    esac
done

# ---- which OS user should own the service (used for system mode) ------------ #
detect_desktop_user() {
    [[ -n "$RUN_AS_USER" ]] && { echo "$RUN_AS_USER"; return; }
    [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]] && { echo "$SUDO_USER"; return; }
    local pid uid name
    for pid in $(pgrep -f 'plasma|kwin|gnome-shell|xfce4-session|mate-session|dde-session|Xorg|Xwayland' 2>/dev/null || true); do
        uid=$(stat -c '%u' "/proc/$pid" 2>/dev/null || true)
        [[ "$uid" =~ ^[0-9]+$ && "$uid" != "0" ]] || continue
        name=$(getent passwd "$uid" | cut -d: -f1)
        [[ -n "$name" && "$name" != "nobody" && "$name" != "nfsnobody" ]] || continue
        # prefer users with a real login shell
        shell=$(getent passwd "$uid" | cut -d: -f7)
        [[ "$shell" != "/usr/sbin/nologin" && "$shell" != "/bin/false" && "$shell" != "/sbin/nologin" ]] || continue
        echo "$name"; return
    done
    echo "$(id -un)"
}

if [[ "$MODE" == "system" ]]; then
    SERVICE_USER="$(detect_desktop_user)"
else
    SERVICE_USER="$(id -un)"
fi
SERVICE_UID="$(id -u "$SERVICE_USER" 2>/dev/null || echo 1000)"
SERVICE_GROUP="$(id -gn "$SERVICE_USER" 2>/dev/null || echo nogroup)"

# ---- detect graphical session env from the target user's desktop processes -- #
detect_session_env() {
    local user="${1:-$SERVICE_USER}" uid pid line
    uid=$(id -u "$user" 2>/dev/null || echo 0)
    for pid in $(pgrep -u "$uid" -f 'plasma|kwin|gnome-shell|xfce4-session|mate-session|dde-session|Xorg|Xwayland' 2>/dev/null || true); do
        line=$(cat "/proc/$pid/environ" 2>/dev/null | tr '\0' '\n' || true)
        [[ -n "${WAYLAND_DISPLAY:-}" ]] || WAYLAND_DISPLAY=$(printf '%s\n' "$line" | sed -n 's/^WAYLAND_DISPLAY=//p' | head -1)
        [[ -n "${DISPLAY:-}" ]] || DISPLAY=$(printf '%s\n' "$line" | sed -n 's/^DISPLAY=//p' | head -1)
        [[ -n "${XDG_RUNTIME_DIR:-}" ]] || XDG_RUNTIME_DIR=$(printf '%s\n' "$line" | sed -n 's/^XDG_RUNTIME_DIR=//p' | head -1)
        [[ -n "${XAUTHORITY:-}" ]] || XAUTHORITY=$(printf '%s\n' "$line" | sed -n 's/^XAUTHORITY=//p' | head -1)
        [[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]] || DBUS_SESSION_BUS_ADDRESS=$(printf '%s\n' "$line" | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p' | head -1)
        [[ -n "${WAYLAND_DISPLAY:-}" || -n "${DISPLAY:-}" ]] && break
    done
}
detect_session_env "$SERVICE_USER"

SESSION_ENV=()
if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
    SESSION_ENV+=("Environment=WAYLAND_DISPLAY=$WAYLAND_DISPLAY")
    SESSION_ENV+=("Environment=XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$SERVICE_UID}")
    [[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]] && SESSION_ENV+=("Environment=DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS")
elif [[ -n "${DISPLAY:-}" ]]; then
    SESSION_ENV+=("Environment=DISPLAY=$DISPLAY")
    SESSION_ENV+=("Environment=XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$SERVICE_UID}")
    [[ -n "${XAUTHORITY:-}" ]] && SESSION_ENV+=("Environment=XAUTHORITY=$XAUTHORITY")
fi

# ---- directories: logs & received files -------------------------------------- #
LOG_DIR="${LOG_DIR:-/var/log/clipshare}"
RECV_DIR="${RECV_DIR:-$CLIPSHARE_DIR/clipshare_recv}"
# In user mode the default /var/log/clipshare usually needs root to create;
# fall back to a repo-local dir so a plain (non-root) install still works.
if [[ "$MODE" == "user" && "$ACTION" == "install" && ! -d "$LOG_DIR" ]] \
   && ! mkdir -p "$LOG_DIR" 2>/dev/null; then
    LOG_DIR="$CLIPSHARE_DIR/logs"
    echo "[!] /var/log/clipshare not writable; logs will go to $LOG_DIR" >&2
fi

# ---- mode-specific unit settings --------------------------------------------- #
if [[ "$MODE" == "user" ]]; then
    DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/clipshare.service"
    CTRL=("systemctl" "--user")
    WANTED="default.target"
    UNIT_EXTRA=$'After=graphical-session.target\nWants=graphical-session.target'
    UNIT_USER=""
    RUN_ARGS="--log-dir \"$LOG_DIR\""
else
    DEST="/etc/systemd/system/clipshare.service"
    CTRL=("systemctl")
    WANTED="multi-user.target"
    UNIT_EXTRA=""
    UNIT_USER="User=$SERVICE_USER"
    RUN_ARGS="--log-dir \"$LOG_DIR\" --recv-dir \"$RECV_DIR\""
fi

write_unit() {
    local target="${1:-file}" content
    content=$(cat <<EOF
[Unit]
Description=clipshare - LAN clipboard sharing
After=network.target
${UNIT_EXTRA}

[Service]
Type=simple
${UNIT_USER}
ExecStart=$PYTHON $CLIPSHARE_DIR/clipshare.py${RUN_ARGS:+ $RUN_ARGS}
WorkingDirectory=$CLIPSHARE_DIR
$(printf '%s\n' "${SESSION_ENV[@]}")
# Stream stdout line-by-line so journalctl shows logs in real time.
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=${WANTED}
EOF
)
    if [[ "$target" == "stdout" ]]; then
        printf '%s\n' "$content"
    else
        mkdir -p "$(dirname "$DEST")"
        printf '%s\n' "$content" > "$DEST"
        echo "[*] Wrote $DEST"
    fi
}

LOGROTATE_DEST="/etc/logrotate.d/clipshare"

write_logrotate() {
    local content
    content=$(sed -e "s/__LOG_USER__/$SERVICE_USER/g" \
                  -e "s/__LOG_GROUP__/$SERVICE_GROUP/g" \
                  "$CLIPSHARE_DIR/logrotate-clipshare.conf")
    if [[ $EUID -eq 0 ]]; then
        printf '%s\n' "$content" > "$LOGROTATE_DEST"
        echo "[*] Wrote $LOGROTATE_DEST (logrotate: daily, keep 30 days)"
    elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
        printf '%s\n' "$content" | sudo tee "$LOGROTATE_DEST" >/dev/null
        echo "[*] Wrote $LOGROTATE_DEST via sudo (logrotate: daily, keep 30 days)"
    else
        echo "[!] logrotate config not installed (need root for $LOGROTATE_DEST)." >&2
        echo "    Manual: sudo sed -e 's/__LOG_USER__/$SERVICE_USER/g' -e \\" >&2
        echo "        's/__LOG_GROUP__/$SERVICE_GROUP/g' \\" >&2
        echo "        $CLIPSHARE_DIR/logrotate-clipshare.conf > $LOGROTATE_DEST" >&2
    fi
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
        else
            # system mode: make log/recv dirs writable by the service user
            mkdir -p "$LOG_DIR" "$RECV_DIR"
            chown "$SERVICE_USER" "$LOG_DIR" "$RECV_DIR" 2>/dev/null || true
            # warn if the service user cannot read the code
            if command -v sudo >/dev/null 2>&1 \
               && ! sudo -u "$SERVICE_USER" test -r "$CLIPSHARE_DIR/clipshare.py" 2>/dev/null; then
                echo "[!] Warning: '$SERVICE_USER' cannot read $CLIPSHARE_DIR/clipshare.py." >&2
                echo "    Grant read access or move the repo to a shared path (e.g. /opt/clipshare)." >&2
            fi
        fi
        write_unit
        write_logrotate
        "${CTRL[@]}" daemon-reload
        "${CTRL[@]}" enable --now clipshare
        if [[ "$MODE" == "user" ]]; then
            JOURNAL="journalctl --user -u clipshare -f"
        else
            JOURNAL="journalctl -u clipshare -f"
        fi
        echo "[*] clipshare service installed and started (${MODE} mode)."
        echo "[*] Service user: $SERVICE_USER   Logs: $LOG_DIR   Recv: $RECV_DIR"
        echo "[*] Check: ${CTRL[*]} status clipshare   | Logs: $JOURNAL"
        ;;
    status)
        "${CTRL[@]}" status clipshare --no-pager 2>&1 | head -30 || true
        ;;
    restart)
        "${CTRL[@]}" restart clipshare
        sleep 1
        echo "[*] clipshare service restarted (${MODE} mode)."
        "${CTRL[@]}" status clipshare --no-pager 2>&1 | head -15 || true
        ;;
    uninstall)
        "${CTRL[@]}" disable --now clipshare 2>/dev/null || true
        rm -f "$DEST"
        "${CTRL[@]}" daemon-reload
        echo "[*] clipshare service removed (${MODE} mode)."
        ;;
    preview)
        write_unit stdout
        ;;
    *)
        echo "Usage: $0 {install|status|restart|uninstall|preview} [--system] [--user NAME] [--log-dir DIR] [--recv-dir DIR]" >&2
        exit 1
        ;;
esac
