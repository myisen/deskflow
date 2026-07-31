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

## File transfer

Besides syncing clipboard text, clipshare can also send a **single file** to all
connected peers.

- `--send-file <path>` / `-f <path>`: after startup, wait for a peer to connect,
  then send that file to all connected peers and keep running normally (clipboard
  sync continues).
- `--recv-dir <dir>`: directory where received files are stored (default
  `clipshare_recv`). It is created automatically if missing; if a file with the
  same name already exists, it is renamed to `name (1).ext`, `name (2).ext`, etc.
  to avoid overwriting.

```bash
# Send a file (waits up to ~15s after startup for a peer to connect)
python clipshare.py --send-file ./report.pdf

# Choose where received files land
python clipshare.py --recv-dir ./inbox
```

Notes:

- A single file is capped at 2 GiB.
- Files travel over the same authenticated channel as the clipboard; when a
  password is set, transfers must authenticate too.
- The receiver sanitizes the file name (keeping only the base name) so a peer
  cannot write outside the receive directory.

## Copy & paste files (file-level clipboard)

clipshare can also sync **files copied in your file manager**: copy a file
(Ctrl+C) on one machine and paste it (Ctrl+V) on another.

- This is **on by default**, no extra flags needed. When you copy a file on one
  machine, it is sent to all peers; each peer saves it into the receive
  directory and **puts it back on its own clipboard**, so you can paste it
  straight into the file manager with Ctrl+V.
- `--no-file-clip`: disable copy/paste file syncing (clipboard text still syncs).

```bash
# Enabled by default, just run it
python clipshare.py

# To turn it off
python clipshare.py --no-file-clip
```

Platform support:

- **Windows**: native (CF_HDROP).
- **Linux X11**: requires `xclip`.
- **Linux Wayland**: requires `wl-clipboard` (`wl-copy` / `wl-paste`).
- If the backend is missing, the feature is disabled automatically (text sync
  still works); the current status is printed at startup.

Notes:

- Copied files share the same 2 GiB total cap and travel over the same
  authenticated channel.
- Received files are saved to the receive directory (see `--recv-dir` above)
  first, then placed on the clipboard; name clashes are auto-renamed to avoid
  overwriting.
- Loop protection is built in: files a peer pushed onto your clipboard are not
  echoed back.

## Picture share (clipboard image)

clipshare can also sync **images copied to the clipboard**: copy a picture
(e.g. a screenshot) on one machine and paste it (Ctrl+V) on another.

- This is **on by default**, no extra flags needed. When you copy a picture it
  is sent to all peers as a PNG; each peer puts it back on its own clipboard,
  so you can paste it straight into any image-aware app with Ctrl+V.
- `--no-image`: disable picture syncing (clipboard text and files still sync).

```bash
# Enabled by default, just run it
python clipshare.py

# To turn it off
python clipshare.py --no-image
```

Platform support:

- **Windows**: native (CF_DIB; requires Pillow for format conversion).
- **Linux X11**: requires `xclip`.
- **Linux Wayland**: requires `wl-clipboard` (`wl-copy` / `wl-paste`).
- If the backend is missing, received images are automatically saved to the
  receive directory (see `--recv-dir`) instead of being lost; the current
  status is printed at startup.

Notes:

- Images travel as PNG over the same authenticated channel, under the same
  2 GiB cap.
- While an image sits on the clipboard the text baseline is kept fresh, so the
  leftover (empty/garbage) text target is not mistaken for a "text change" and
  echoed to peers.
- Loop protection is built in: an image a peer pushed onto your clipboard is
  not echoed back.

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
