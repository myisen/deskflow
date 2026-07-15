# clipshare

Share the clipboard between PCs on the same LAN — **the same Python code runs
on both Windows and Linux**.

## Install

```bash
pip install -r requirements.txt
# Linux only: install a clipboard backend
#   X11     : sudo apt install xclip
#   Wayland : sudo dnf install wl-clipboard   (Fedora/RHEL)
#             sudo apt install wl-clipboard   (Debian/Ubuntu)
```

## Run

On **every** machine (no args needed — they mesh together via LAN broadcast):

```bash
python clipshare.py
```

This auto-discovers **all** peers on the LAN and forms a full mesh, so 3 or
more PCs all share one clipboard. Copy on any machine, paste on any other.

The TCP server binds to `0.0.0.0` on port **`32620`** by default.

### Password protection

Set the same password on every node (via `--password` or the
`CLIPSHARE_PASSWORD` environment variable). Connections that don't present the
matching password are rejected. Leaving it unset keeps the link open (no auth).

```bash
python clipshare.py --password yourSecret
# or
CLIPSHARE_PASSWORD=yourSecret python clipshare.py
```

If your network/Wi-Fi blocks UDP broadcasts, list the peers explicitly. You can
repeat `--peer` or comma-separate them; do this on **every** node, listing the
*other* nodes:

```bash
# node A:
python clipshare.py --password yourSecret --peer 192.168.1.50 --peer 192.168.1.60
# node B:
python clipshare.py --password yourSecret --peer 192.168.1.40 --peer 192.168.1.60
# node C:
python clipshare.py --password yourSecret --peer 192.168.1.40 --peer 192.168.1.50
# (comma form also works: --peer 192.168.1.50,192.168.1.60)
```

## How it works

- Each node runs a TCP server (receives updates) and a TCP client per peer
  (pushes updates). Duplicate links are deduplicated, so every pair has exactly
  one connection — a full mesh across N nodes.
- A poller watches the local clipboard. A **local** change is broadcast to all
  connected peers. An update **received** from a peer is written to the local
  clipboard and tagged so it is not echoed back (no infinite sync loop).
- Text only. A change on any node propagates to all others in a single hop.

## Troubleshooting

- Make sure the firewall allows TCP `32620` (and UDP `54321` for discovery).
- Prefer `--peer <ip>` if auto-discovery does not connect.
- Linux requires `xclip` (X11) or `wl-clipboard` (Wayland) for `pyperclip`.

## User Information

- Author / Maintainer: lihuiliang01
- Email: lihuiliang01@picc.com.cn
- Repository: http://code.devops.piccnet/picc/lihuiliang01picc.com.cn/clipshare.git
- License: see [LICENSE](LICENSE)
