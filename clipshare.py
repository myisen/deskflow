#!/usr/bin/env python3
"""
clipshare - Share the clipboard between two PCs on the same LAN.

The *same* script runs unchanged on Windows and Linux. It auto-discovers the
peer over a UDP broadcast; if your network blocks broadcasts you can pass
--peer <ip> to connect directly.

How it works
------------
- Each node runs a TCP server (to receive clipboard updates) and, if it has
  the "higher" IP, a TCP client (to push updates). This guarantees exactly one
  connection between the two machines.
- A poller watches the local clipboard. When it changes *locally*, the new
  text is sent to the peer. When an update arrives *from* the peer, it is
  written to the local clipboard and marked as "remote" so it is not echoed
  back (no sync loop).

Usage
-----
    python clipshare.py                                  # auto-discover peers
    python clipshare.py --peer 192.168.1.50              # connect to a peer
    python clipshare.py --port 32620 --password secret   # custom port + auth
    CLIPSHARE_PASSWORD=secret python clipshare.py        # password via env

The TCP server binds to 0.0.0.0 on port 32620 by default. When a password is
set (via --password or CLIPSHARE_PASSWORD) every connection must authenticate
with the same password, otherwise it is rejected.

Dependencies
------------
    pip install pyperclip
    # Linux only: install a clipboard backend
    #   X11  : sudo apt install xclip
    #   Wayland: sudo apt install wl-clipboard
"""

import argparse
import hashlib
import os
import socket
import struct
import threading
import time

import pyperclip

# ----------------------------- configuration ------------------------------ #
CLIP_PORT = 32620          # TCP port for clipboard transfer (binds 0.0.0.0)
DISCOVERY_PORT = 54321      # UDP port for LAN broadcast discovery
DISCOVERY_MSG = b"CLIPSHARE_DISCOVER"
BROADCAST_INTERVAL = 2.0   # seconds between discovery broadcasts
POLL_INTERVAL = 0.3        # seconds between local clipboard polls
RECONNECT_INTERVAL = 3.0   # seconds between reconnect attempts
HANDSHAKE_TIMEOUT = 5.0    # seconds to wait for the peer's auth frame
AUTH_FAIL_LOG_INTERVAL = 60.0  # min seconds between auth-failure log lines per peer
ACCEPT_COOLDOWN = RECONNECT_INTERVAL  # ignore re-connects from a peer that just failed auth
HEADER = b"CS1"            # 3-byte magic marking a framed message
TYPE_AUTH = 0x01           # payload = SHA-256(password)
TYPE_CLIP = 0x02           # payload = clipboard text (utf-8)

# ------------------------------- globals ---------------------------------- #
_running = threading.Event()
_running.set()


def get_local_ip():
    """Best-effort detection of the LAN IP (no traffic is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# --------------------------- clipboard access ----------------------------- #
class Clipboard:
    """Thread-safe wrapper around pyperclip with loop prevention."""

    def __init__(self):
        self._lock = threading.Lock()
        self._backend_ok = self._check_backend()
        self._warn_printed = False
        try:
            self.last_value = pyperclip.paste() if self._backend_ok else ""
        except Exception:
            self.last_value = ""

    def _check_backend(self):
        """Return True if pyperclip can actually find a copy/paste mechanism.
        On Linux this requires xclip/xsel (X11) or wl-clipboard (Wayland)."""
        try:
            pyperclip.paste()
            return True
        except pyperclip.PyperclipException:
            return False
        except Exception:
            return False

    def _warn_once(self):
        if not self._warn_printed:
            self._warn_printed = True
            print("[!] No clipboard backend available on this system. "
                  "Clipboard sharing will not work until one is installed:")
            print("      Linux X11   : sudo apt install xclip   (or xsel)")
            print("      Linux Wayland: sudo apt install wl-clipboard")
            print("    Remote updates will be received but cannot be written locally.")

    def get(self):
        with self._lock:
            if not self._backend_ok:
                return None
            try:
                return pyperclip.paste()
            except Exception:
                return None

    def set(self, text):
        """Set the clipboard AND record the value so the poller will not
        treat this remote write as a local change (prevents echo loops).
        Returns True on success, False if the write failed (e.g. no backend)."""
        with self._lock:
            if not self._backend_ok:
                self._warn_once()
                self.last_value = text  # still record it to avoid echo loops
                return False
            try:
                pyperclip.copy(text)
                self.last_value = text
                return True
            except pyperclip.PyperclipException:
                self._backend_ok = False
                self._warn_once()
                self.last_value = text
                return False
            except Exception:
                self.last_value = text
                return False

    def poll_changed(self):
        """Return the new local value if it changed since last seen, else None."""
        with self._lock:
            if not self._backend_ok:
                return None
            try:
                cur = pyperclip.paste()
            except Exception:
                return None
            if cur != self.last_value and cur is not None:
                self.last_value = cur
                return cur
            return None


# ----------------------------- frame codec -------------------------------- #
def build_frame(ftype, payload):
    return HEADER + bytes([ftype]) + struct.pack(">I", len(payload)) + payload


def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def recv_frame(conn):
    header = recv_exact(conn, 8)  # HEADER(3) + TYPE(1) + LEN(4)
    if not header or header[:3] != HEADER:
        return None, None
    ftype = header[3]
    n = struct.unpack(">I", header[4:8])[0]
    payload = recv_exact(conn, n)
    if payload is None:
        return None, None
    return ftype, payload


# ------------------------------ peer network ------------------------------ #
class PeerNet:
    def __init__(self, port, peers, clip, password=None):
        self.port = port
        self.peers = set(peers) if peers else set()  # empty => accept any (auto mode)
        self.clip = clip
        # SHA-256 of the password; None means "open" (no auth required).
        self._pw_hash = (hashlib.sha256(password.encode("utf-8")).digest()
                         if password else None)
        self.my_ip = get_local_ip()
        self.connections = {}          # ip -> socket
        self._lock = threading.Lock()
        self._connectors = set()
        self._fail_lock = threading.Lock()
        self._fail_times = {}          # peer_ip -> last auth-failure timestamp
        self._fail_log_times = {}      # peer_ip -> last time we logged a failure

        self.sock_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock_server.bind(("0.0.0.0", port))
        except OSError as e:
            raise SystemExit(
                f"[!] Cannot bind TCP server on 0.0.0.0:{port}: {e}\n"
                f"    Another clipshare instance is probably already running "
                f"(or the port is in use by another app). Stop it and retry.")
        self.sock_server.listen(5)

        self.sock_discovery = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_discovery.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock_discovery.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self.sock_discovery.bind(("", DISCOVERY_PORT))
        except OSError as e:
            print(f"[!] Cannot bind UDP discovery port {DISCOVERY_PORT}: {e} "
                  f"(auto-discovery disabled; use --peer to connect)")

    # -- connection bookkeeping ------------------------------------------- #
    def _do_handshake(self, conn, peer_ip):
        """Exchange and verify the password. Returns True if allowed through.
        In open mode (no password configured) this is a no-op. When a password
        is set we expect the peer to reply with its auth frame; a timeout
        (e.g. peer has no password) is treated as failure, not a hang."""
        if self._pw_hash is None:
            return True
        try:
            conn.sendall(build_frame(TYPE_AUTH, self._pw_hash))
            # Don't block forever if the peer never authenticates.
            conn.settimeout(HANDSHAKE_TIMEOUT)
            ftype, payload = recv_frame(conn)
            conn.settimeout(None)
        except (OSError, socket.timeout):
            conn.settimeout(None)
            self._auth_failed(peer_ip, "timed out")
            return False
        if ftype != TYPE_AUTH or payload != self._pw_hash:
            self._auth_failed(peer_ip, "bad password")
            return False
        return True

    def _auth_failed(self, peer_ip, reason):
        now = time.time()
        with self._fail_lock:
            self._fail_times[peer_ip] = now
            last_log = self._fail_log_times.get(peer_ip, 0)
            do_log = (now - last_log) >= AUTH_FAIL_LOG_INTERVAL
            if do_log:
                self._fail_log_times[peer_ip] = now
        if do_log:
            print(f"[!] Authentication failed from {peer_ip} ({reason}). "
                  f"Ensure every node uses the same --password.")

    def register_connection(self, conn, peer_ip):
        with self._lock:
            if peer_ip in self.connections:
                # Duplicate (e.g. both sides connected). Keep the existing one.
                try:
                    conn.close()
                except Exception:
                    pass
                return False
            self.connections[peer_ip] = conn
        # Authenticate before handing the socket to the reader.
        if not self._do_handshake(conn, peer_ip):
            with self._lock:
                if self.connections.get(peer_ip) is conn:
                    del self.connections[peer_ip]
            try:
                conn.close()
            except Exception:
                pass
            return False
        self._enable_keepalive(conn)
        threading.Thread(target=self._reader, args=(conn, peer_ip),
                         daemon=True).start()
        print(f"[+] Connected to {peer_ip}:{self.port}")
        return True

    def _enable_keepalive(self, sock):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass

    # -- discovery -------------------------------------------------------- #
    def _discovery_loop(self):
        while _running.is_set():
            try:
                data, addr = self.sock_discovery.recvfrom(1024)
            except Exception:
                break
            if data == DISCOVERY_MSG:
                peer_ip = addr[0]
                if peer_ip != self.my_ip:
                    self._learn_peer(peer_ip)
            time.sleep(0.01)

    def _announce_loop(self):
        while _running.is_set():
            try:
                self.sock_discovery.sendto(
                    DISCOVERY_MSG, ("<broadcast>", DISCOVERY_PORT))
            except Exception:
                pass
            time.sleep(BROADCAST_INTERVAL)

    def _learn_peer(self, peer_ip):
        # In manual mode only talk to the listed peers.
        if self.peers and peer_ip not in self.peers:
            return
        if peer_ip in self._connectors:
            return
        self._connectors.add(peer_ip)
        threading.Thread(target=self._connect_loop, args=(peer_ip,),
                         daemon=True).start()

    def _connect_loop(self, peer_ip):
        while _running.is_set():
            with self._lock:
                if peer_ip in self.connections:
                    # Already connected (likely via the peer's accept side).
                    time.sleep(1)
                    continue
            try:
                sock = socket.create_connection((peer_ip, self.port), timeout=5)
            except Exception:
                time.sleep(RECONNECT_INTERVAL)
                continue
            # Reset the connect timeout so the reader blocks indefinitely.
            sock.settimeout(None)
            ok = self.register_connection(sock, peer_ip)
            if not ok:
                # Rejected (e.g. wrong password) or duplicate. Back off before
                # retrying so we don't pummel the peer with connection attempts.
                time.sleep(RECONNECT_INTERVAL)
                continue
            # Block until this connection is gone, then retry.
            while _running.is_set() and self.connections.get(peer_ip) is sock:
                time.sleep(1)

    # -- server ----------------------------------------------------------- #
    def _server_loop(self):
        while _running.is_set():
            try:
                conn, addr = self.sock_server.accept()
            except Exception:
                break
            peer_ip = addr[0]
            if self.peers and peer_ip not in self.peers:
                conn.close()
                continue
            # A peer that just failed auth tends to reconnect immediately.
            # Ignore its connections until the cooldown passes to avoid a
            # reconnect storm (and the resulting log spam).
            with self._fail_lock:
                last = self._fail_times.get(peer_ip, 0)
                if (time.time() - last) < ACCEPT_COOLDOWN:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    continue
            self.register_connection(conn, peer_ip)

    # -- reader ----------------------------------------------------------- #
    def _reader(self, conn, peer_ip):
        try:
            while _running.is_set():
                ftype, payload = recv_frame(conn)
                if ftype is None:
                    break
                if ftype == TYPE_CLIP:
                    text = payload.decode("utf-8", "replace")
                    self.clip.set(text)
                    print(f"[<] Clipboard updated from {peer_ip}")
                # Any other type is ignored.
        finally:
            with self._lock:
                if self.connections.get(peer_ip) is conn:
                    del self.connections[peer_ip]
            try:
                conn.close()
            except Exception:
                pass
            print(f"[-] Disconnected from {peer_ip}")

    # -- broadcast -------------------------------------------------------- #
    def broadcast(self, text):
        data = build_frame(TYPE_CLIP, text.encode("utf-8"))
        with self._lock:
            peers = list(self.connections.items())
        if not peers:
            return
        for _, sock in peers:
            try:
                sock.sendall(data)
            except Exception:
                # The reader thread will clean up the dead socket.
                pass
        print(f"[>] Sent clipboard to {len(peers)} peer(s)")

    # -- lifecycle -------------------------------------------------------- #
    def start(self):
        print(f"[*] Local IP: {self.my_ip}  TCP port: {self.port}")
        if self.peers:
            print(f"[*] Explicit peers: {', '.join(sorted(self.peers))}")
            for p in self.peers:
                self._learn_peer(p)
        else:
            print("[*] Auto-discovering peer via LAN broadcast...")
        threading.Thread(target=self._server_loop, daemon=True).start()
        threading.Thread(target=self._discovery_loop, daemon=True).start()
        threading.Thread(target=self._announce_loop, daemon=True).start()


# -------------------------------- main ------------------------------------ #
def main():
    parser = argparse.ArgumentParser(description="LAN clipboard sharing")
    parser.add_argument("--peer", action="append", default=[],
                        help="Peer IP (repeatable; omit for auto-discovery). "
                             "Comma-separated values in one flag are also allowed.")
    parser.add_argument("--port", type=int, default=CLIP_PORT,
                        help=f"TCP port (default {CLIP_PORT}, binds 0.0.0.0)")
    parser.add_argument("--password", "-P", default=os.environ.get("CLIPSHARE_PASSWORD"),
                        help="Connection password (same on all nodes). "
                             "May also be set via CLIPSHARE_PASSWORD env var.")
    args = parser.parse_args()

    peers = []
    for item in args.peer:
        peers.extend(p.strip() for p in item.split(",") if p.strip())

    clip = Clipboard()
    net = PeerNet(args.port, peers, clip, password=args.password)
    net.start()

    print("[*] Watching clipboard. Copy something to share it. Ctrl+C to quit.")
    try:
        while _running.is_set():
            changed = clip.poll_changed()
            if changed is not None:
                net.broadcast(changed)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        _running.clear()
        print("\n[*] Stopped.")


if __name__ == "__main__":
    main()
