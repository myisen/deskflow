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
    python clipshare.py --send-file ./report.pdf         # also share a single file
    python clipshare.py --recv-dir ./inbox               # where received files land
    # Copy a file in your file manager -> it is mirrored to peers, ready to paste.
    python clipshare.py --no-file-clip                   # disable copy/paste of files
    # Copy a picture (e.g. a screenshot) -> it is mirrored to peers, ready to paste.
    python clipshare.py --no-image                       # disable picture syncing

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
import subprocess
import sys
import threading
import time
import urllib.parse
from shutil import which

import pyperclip

__version__ = "0.3"

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
TYPE_FILE = 0x03           # payload = NAMELEN(2) + name(utf-8) + file bytes
TYPE_CLIPFILES = 0x04      # payload = COUNT(2) + [NAMELEN(2)+name+DATALEN(8)+data]*
TYPE_IMAGE = 0x05          # payload = PNG image bytes
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GiB safety cap for a single file
DEFAULT_RECV_DIR = "clipshare_recv"     # where received files are stored
SEND_FILE_WAIT = 15.0      # seconds to wait for a peer before sending a file
FILE_POLL_INTERVAL = 1.0   # seconds between "copied files" clipboard polls
IMAGE_POLL_INTERVAL = 0.5  # seconds between "copied image" clipboard polls

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


# --------------------------- file clipboard ------------------------------- #
class FileClipboard:
    """Detect files copied to the OS clipboard and place received files back
    onto it, so a "copy file" on one machine becomes a "paste" (Ctrl+V) on
    another.

    Cross-platform, best effort:
      - Windows : native CF_HDROP via ctypes.
      - Linux   : xclip (X11) / wl-clipboard (Wayland) using the
                  'x-special/gnome-copied-files' and 'text/uri-list' targets.
    On unsupported systems every method degrades to a harmless no-op.
    """

    def __init__(self):
        self.backend = self._detect_backend()

    @property
    def available(self):
        return self.backend is not None

    def describe(self):
        return {
            "windows": "Windows native (CF_HDROP)",
            "x11": "Linux X11 (xclip)",
            "wayland": "Linux Wayland (wl-clipboard)",
        }.get(self.backend, "unavailable on this system")

    # -- backend detection ----------------------------------------------- #
    @staticmethod
    def _detect_backend():
        if sys.platform == "win32":
            return "windows"
        if sys.platform.startswith("linux"):
            wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
            if wayland and which("wl-paste") and which("wl-copy"):
                return "wayland"
            if which("xclip"):
                return "x11"
            if wayland and which("wl-paste"):
                return "wayland"
        return None

    # -- read: files currently copied ------------------------------------ #
    def get_files(self):
        """Return a list of existing local file paths currently on the
        clipboard, or None if there are none / it is unsupported."""
        try:
            if self.backend == "windows":
                paths = self._win_get_files()
            elif self.backend == "x11":
                paths = self._uris_to_paths(self._xclip_get())
            elif self.backend == "wayland":
                paths = self._uris_to_paths(self._wl_get())
            else:
                return None
        except Exception:
            return None
        files = [p for p in (paths or []) if os.path.isfile(p)]
        return files or None

    # -- write: put files on the clipboard ------------------------------- #
    def set_files(self, paths):
        paths = [os.path.abspath(p) for p in paths if os.path.isfile(p)]
        if not paths:
            return False
        try:
            if self.backend == "windows":
                return self._win_set_files(paths)
            if self.backend == "x11":
                return self._xclip_set(paths)
            if self.backend == "wayland":
                return self._wl_set(paths)
        except Exception:
            return False
        return False

    # -- uri <-> path helpers -------------------------------------------- #
    @staticmethod
    def _uris_to_paths(text):
        if not text:
            return []
        paths = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line in ("copy", "cut"):
                continue
            if line.startswith("file://"):
                p = urllib.parse.unquote(urllib.parse.urlparse(line).path)
            elif line.startswith("/"):
                p = line
            else:
                continue
            # Normalize so an accidental "///" (or other odd producer) does
            # not make the path differ from the one we computed locally -
            # this keeps loop-prevention signatures consistent.
            p = os.path.normpath(p)
            paths.append(p)
        return paths

    @staticmethod
    def _paths_to_gnome(paths, action="copy"):
        lines = [action]
        for p in paths:
            # RFC 8089 file URI: file:///absolute/path (exactly three slashes).
            lines.append("file://" + urllib.parse.quote(os.path.abspath(p)))
        return "\n".join(lines) + "\n"

    # -- Linux X11 (xclip) ------------------------------------------------ #
    @staticmethod
    def _xclip_get():
        for target in ("x-special/gnome-copied-files", "text/uri-list"):
            try:
                out = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-t", target, "-o"],
                    capture_output=True, timeout=5)
            except Exception:
                continue
            if out.returncode == 0 and out.stdout:
                return out.stdout.decode("utf-8", "replace")
        return ""

    def _xclip_set(self, paths):
        data = self._paths_to_gnome(paths).encode("utf-8")
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard",
                 "-t", "x-special/gnome-copied-files"],
                input=data, timeout=5, check=False)
            return True
        except Exception:
            return False

    # -- Linux Wayland (wl-clipboard) ------------------------------------ #
    @staticmethod
    def _wl_get():
        for target in ("x-special/gnome-copied-files", "text/uri-list"):
            try:
                out = subprocess.run(
                    ["wl-paste", "-t", target],
                    capture_output=True, timeout=5)
            except Exception:
                continue
            if out.returncode == 0 and out.stdout:
                return out.stdout.decode("utf-8", "replace")
        return ""

    def _wl_set(self, paths):
        data = self._paths_to_gnome(paths).encode("utf-8")
        try:
            subprocess.run(
                ["wl-copy", "-t", "x-special/gnome-copied-files"],
                input=data, timeout=5, check=False)
            return True
        except Exception:
            return False

    # -- Windows (CF_HDROP via ctypes) ----------------------------------- #
    @staticmethod
    def _win_get_files():
        import ctypes
        from ctypes import wintypes

        CF_HDROP = 15
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        shell32.DragQueryFileW.argtypes = [
            wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        shell32.DragQueryFileW.restype = wintypes.UINT
        user32.GetClipboardData.restype = wintypes.HANDLE

        if not user32.OpenClipboard(None):
            return []
        try:
            if not user32.IsClipboardFormatAvailable(CF_HDROP):
                return []
            handle = user32.GetClipboardData(CF_HDROP)
            if not handle:
                return []
            count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
            files = []
            for i in range(count):
                need = shell32.DragQueryFileW(handle, i, None, 0)
                buf = ctypes.create_unicode_buffer(need + 1)
                shell32.DragQueryFileW(handle, i, buf, need + 1)
                files.append(buf.value)
            return files
        finally:
            user32.CloseClipboard()

    @staticmethod
    def _win_set_files(paths):
        import ctypes
        from ctypes import wintypes

        CF_HDROP = 15
        GMEM_MOVEABLE = 0x0002

        class DROPFILES(ctypes.Structure):
            _fields_ = [
                ("pFiles", wintypes.DWORD),
                ("pt", wintypes.POINT),
                ("fNC", wintypes.BOOL),
                ("fWide", wintypes.BOOL),
            ]

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        user32.SetClipboardData.restype = wintypes.HANDLE

        files_str = "".join(p + "\0" for p in paths) + "\0"
        files_bytes = files_str.encode("utf-16-le")
        df = DROPFILES()
        df.pFiles = ctypes.sizeof(DROPFILES)
        df.fWide = True
        total = ctypes.sizeof(DROPFILES) + len(files_bytes)

        h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, total)
        if not h_global:
            return False
        ptr = kernel32.GlobalLock(h_global)
        if not ptr:
            kernel32.GlobalFree(h_global)
            return False
        try:
            ctypes.memmove(ptr, ctypes.byref(df), ctypes.sizeof(DROPFILES))
            ctypes.memmove(ptr + ctypes.sizeof(DROPFILES),
                           files_bytes, len(files_bytes))
        finally:
            kernel32.GlobalUnlock(h_global)

        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(h_global)
            return False
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_HDROP, h_global):
                kernel32.GlobalFree(h_global)
                return False
            # Ownership passed to the clipboard; must NOT free h_global now.
            return True
        finally:
            user32.CloseClipboard()


# --------------------------- image clipboard ------------------------------ #
class ImageClipboard:
    """Detect an image (picture) copied to the OS clipboard and place received
    images back onto it, so a "copy image" (e.g. a screenshot) on one machine
    becomes a "paste" (Ctrl+V) on another.

    Cross-platform, best effort:
      - Windows : native CF_DIB via ctypes (requires Pillow to convert).
      - Linux   : xclip (X11) / wl-clipboard (Wayland) using the
                  'image/png' target.
    On unsupported systems (or when Pillow is missing on Windows) every method
    degrades to a harmless no-op and the image is saved as a PNG in recv_dir
    instead.
    """

    def __init__(self):
        self.backend = self._detect_backend()

    @property
    def available(self):
        return self.backend is not None

    def describe(self):
        return {
            "windows": "Windows native (CF_DIB)",
            "x11": "Linux X11 (xclip)",
            "wayland": "Linux Wayland (wl-clipboard)",
        }.get(self.backend, "unavailable on this system")

    @staticmethod
    def _detect_backend():
        if sys.platform == "win32":
            return "windows"
        if sys.platform.startswith("linux"):
            wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
            if wayland and which("wl-paste") and which("wl-copy"):
                return "wayland"
            if which("xclip"):
                return "x11"
            if wayland and which("wl-paste"):
                return "wayland"
        return None

    @staticmethod
    def _is_png(data):
        return bool(data) and data[:8] == b"\x89PNG\r\n\x1a\n"

    # -- read ------------------------------------------------------------- #
    def get_image(self):
        try:
            if self.backend == "windows":
                data = self._win_get_image()
            elif self.backend == "x11":
                data = self._xclip_get_image()
            elif self.backend == "wayland":
                data = self._wl_get_image()
            else:
                return None
        except Exception:
            return None
        return data if self._is_png(data) else None

    # -- write ------------------------------------------------------------ #
    def set_image(self, png):
        if not self._is_png(png):
            return False
        try:
            if self.backend == "windows":
                return self._win_set_image(png)
            if self.backend == "x11":
                return self._xclip_set_image(png)
            if self.backend == "wayland":
                return self._wl_set_image(png)
        except Exception:
            return False
        return False

    # -- Linux Wayland ---------------------------------------------------- #
    @staticmethod
    def _wl_get_image():
        try:
            out = subprocess.run(["wl-paste", "--type", "image/png"],
                                 capture_output=True, timeout=5)
        except Exception:
            return b""
        return out.stdout if out.returncode == 0 else b""

    def _wl_set_image(self, png):
        try:
            subprocess.run(["wl-copy", "--type", "image/png"],
                           input=png, timeout=5, check=False)
            return True
        except Exception:
            return False

    # -- Linux X11 -------------------------------------------------------- #
    @staticmethod
    def _xclip_get_image():
        try:
            out = subprocess.run(
                ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
                capture_output=True, timeout=5)
        except Exception:
            return b""
        return out.stdout if out.returncode == 0 else b""

    def _xclip_set_image(self, png):
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard", "-t", "image/png"],
                input=png, timeout=5, check=False)
            return True
        except Exception:
            return False

    # -- Windows (CF_DIB via ctypes + Pillow) ----------------------------- #
    @staticmethod
    def _win_get_image():
        import ctypes
        from ctypes import wintypes
        CF_DIB = 8
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalSize.restype = wintypes.SIZE_T
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        if not user32.OpenClipboard(None):
            return b""
        try:
            if not user32.IsClipboardFormatAvailable(CF_DIB):
                return b""
            h = user32.GetClipboardData(CF_DIB)
            if not h:
                return b""
            size = kernel32.GlobalSize(h)
            ptr = kernel32.GlobalLock(h)
            if not ptr:
                return b""
            try:
                buf = ctypes.string_at(ptr, size)
            finally:
                kernel32.GlobalUnlock(h)
            return ImageClipboard._dib_to_png(buf) or b""
        finally:
            user32.CloseClipboard()

    @staticmethod
    def _win_set_image(png):
        import ctypes
        from ctypes import wintypes
        CF_DIB = 8
        GMEM_MOVEABLE = 0x0002
        dib = ImageClipboard._png_to_dib(png)
        if not dib:
            return False
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, wintypes.SIZE_T]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        user32.SetClipboardData.restype = wintypes.HANDLE
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
        if not h:
            return False
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            kernel32.GlobalFree(h)
            return False
        try:
            ctypes.memmove(ptr, dib, len(dib))
        finally:
            kernel32.GlobalUnlock(h)
        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(h)
            return False
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_DIB, h):
                kernel32.GlobalFree(h)
                return False
            return True
        finally:
            user32.CloseClipboard()

    @staticmethod
    def _dib_to_png(data):
        try:
            from PIL import Image
            import struct as _s
            import io as _io
            if len(data) < 40:
                return None
            biSize, width, height, _, bitcount = _s.unpack_from(
                "<IiiHH", data, 0)
            comp = _s.unpack_from("<I", data, 16)[0]
            color_used = _s.unpack_from("<I", data, 32)[0]
            if color_used == 0 and bitcount < 16:
                color_used = 1 << bitcount
            pixoff = biSize + color_used * 4
            if bitcount == 24:
                mode = "RGB"
            elif bitcount == 32:
                mode = "RGBA" if comp == 3 else "RGB"
            elif bitcount in (1, 4, 8):
                mode = "P"
            else:
                return None
            img = Image.frombytes(mode, (width, abs(height)), data[pixoff:],
                                  "raw", mode, 0, -1 if height > 0 else 1)
            if mode == "P":
                pal = data[biSize:biSize + color_used * 4]
                img.putpalette([b for i in range(0, len(pal), 4)
                                for b in (pal[i + 2], pal[i + 1], pal[i])])
            out = _io.BytesIO()
            img.save(out, "PNG")
            return out.getvalue()
        except Exception:
            return None

    @staticmethod
    def _png_to_dib(png):
        try:
            from PIL import Image
            import io as _io
            img = Image.open(_io.BytesIO(png)).convert("RGBA")
            buf = _io.BytesIO()
            img.save(buf, "BMP")
            bmp = buf.getvalue()
            return bmp[14:]  # strip BITMAPFILEHEADER; CF_DIB wants the rest
        except Exception:
            return None


# ------------------------------ peer network ------------------------------ #
class PeerNet:
    def __init__(self, port, peers, clip, password=None, recv_dir=DEFAULT_RECV_DIR):
        self.port = port
        self.peers = set(peers) if peers else set()  # empty => accept any (auto mode)
        self.clip = clip
        self.recv_dir = recv_dir
        self.file_clip = None            # optional FileClipboard (set by main)
        self._clipfile_lock = threading.Lock()
        self.last_recv_clip_sig = None   # sig of files we just placed on clipboard
        self.image_clip = None           # optional ImageClipboard (set by main)
        self._image_lock = threading.Lock()
        self.last_recv_image_sig = None  # sig of image we just placed on clipboard
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
                elif ftype == TYPE_FILE:
                    self._save_file(payload, peer_ip)
                elif ftype == TYPE_CLIPFILES:
                    self._save_clip_files(payload, peer_ip)
                elif ftype == TYPE_IMAGE:
                    self._save_image(payload, peer_ip)
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

    # -- single-file transfer -------------------------------------------- #
    def send_file(self, path):
        """Send a single file to all connected peers. Returns the number of
        peers it was sent to (0 if none, or on error)."""
        try:
            size = os.path.getsize(path)
        except OSError as e:
            print(f"[!] Cannot read file {path!r}: {e}")
            return 0
        if size > MAX_FILE_SIZE:
            print(f"[!] File too large ({size} bytes > {MAX_FILE_SIZE}); aborting.")
            return 0
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            print(f"[!] Cannot read file {path!r}: {e}")
            return 0

        name = os.path.basename(path).encode("utf-8")
        payload = struct.pack(">H", len(name)) + name + data
        frame = build_frame(TYPE_FILE, payload)

        with self._lock:
            peers = list(self.connections.items())
        if not peers:
            print(f"[!] No peers connected; file {path!r} was not sent.")
            return 0
        sent = 0
        for _, sock in peers:
            try:
                sock.sendall(frame)
                sent += 1
            except Exception:
                pass
        print(f"[>] Sent file {os.path.basename(path)!r} "
              f"({size} bytes) to {sent} peer(s)")
        return sent

    def send_file_when_ready(self, path, wait=SEND_FILE_WAIT):
        """Wait (up to `wait` seconds) for at least one peer, then send `path`."""
        deadline = time.time() + wait
        while _running.is_set() and time.time() < deadline:
            with self._lock:
                have_peer = bool(self.connections)
            if have_peer:
                # Give the handshake/reader a beat to settle.
                time.sleep(0.5)
                break
            time.sleep(0.3)
        self.send_file(path)

    def _save_file(self, payload, peer_ip):
        if len(payload) < 2:
            print(f"[!] Malformed file frame from {peer_ip}")
            return
        name_len = struct.unpack(">H", payload[:2])[0]
        name = payload[2:2 + name_len].decode("utf-8", "replace")
        data = payload[2 + name_len:]
        dest = self._write_recv_file(name, data, peer_ip)
        if dest:
            print(f"[<] Received file {os.path.basename(dest)!r} "
                  f"({len(data)} bytes) from {peer_ip} -> {dest}")

    def _write_recv_file(self, name, data, peer_ip):
        """Write one received file into recv_dir; return the path or None.
        The name is sanitized so a peer cannot escape the receive directory."""
        safe_name = os.path.basename(name) or "received.bin"
        try:
            os.makedirs(self.recv_dir, exist_ok=True)
        except OSError as e:
            print(f"[!] Cannot create recv dir {self.recv_dir!r}: {e}")
            return None
        dest = self._unique_path(os.path.join(self.recv_dir, safe_name))
        try:
            with open(dest, "wb") as f:
                f.write(data)
        except OSError as e:
            print(f"[!] Failed to save file from {peer_ip}: {e}")
            return None
        return dest

    # -- copy/paste of files (OS clipboard) ------------------------------ #
    @staticmethod
    def _files_sig(paths):
        return tuple(sorted(os.path.abspath(p) for p in paths))

    def mark_clip_files(self, paths):
        """Record files we just put on the local clipboard, so the poller
        does not treat them as a fresh local copy and echo them back."""
        with self._clipfile_lock:
            self.last_recv_clip_sig = self._files_sig(paths)

    def recv_clip_sig(self):
        with self._clipfile_lock:
            return self.last_recv_clip_sig

    # -- copy/paste of images (OS clipboard) ------------------------------ #
    def mark_recv_image(self, png):
        with self._image_lock:
            self.last_recv_image_sig = hashlib.md5(png).digest()

    def recv_image_sig(self):
        with self._image_lock:
            return self.last_recv_image_sig

    def send_image(self, png):
        """Send a copied image (PNG bytes) to all peers. Returns the number
        of peers it reached (0 if none / too large)."""
        if not png:
            return 0
        if len(png) > MAX_FILE_SIZE:
            print("[!] Image too large; not sending.")
            return 0
        frame = build_frame(TYPE_IMAGE, png)
        with self._lock:
            peers = list(self.connections.items())
        if not peers:
            return 0
        sent = 0
        for _, sock in peers:
            try:
                sock.sendall(frame)
                sent += 1
            except Exception:
                pass
        print(f"[>] Sent image ({len(png)} bytes) to {sent} peer(s)")
        return sent

    def _save_image(self, payload, peer_ip):
        if not payload:
            return
        print(f"[<] Received image ({len(payload)} bytes) from {peer_ip}")
        if self.image_clip and self.image_clip.available:
            if self.image_clip.set_image(payload):
                self.mark_recv_image(payload)
                # Keep the text baseline fresh so the text poller does not
                # echo the (now empty/garbage) text target left behind.
                try:
                    v = self.clip.get()
                    if v is not None:
                        self.clip.last_value = v
                except Exception:
                    pass
                print("[*] Image placed on clipboard - paste (Ctrl+V) to use it.")
        else:
            dest = self._write_recv_file("clipboard.png", payload, peer_ip)
            if dest:
                print(f"[*] No image clipboard backend; saved to {dest}")

    def send_clip_files(self, paths):
        """Send the given copied files to all peers as a single frame.
        Returns the number of peers it reached."""
        blobs, total = [], 0
        for p in paths:
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            total += size
            if total > MAX_FILE_SIZE:
                print(f"[!] Copied files exceed {MAX_FILE_SIZE} bytes; "
                      f"not sending.")
                return 0
            try:
                with open(p, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            blobs.append((os.path.basename(p).encode("utf-8"), data))
        if not blobs:
            return 0

        parts = [struct.pack(">H", len(blobs))]
        for name, data in blobs:
            parts.append(struct.pack(">H", len(name)))
            parts.append(name)
            parts.append(struct.pack(">Q", len(data)))
            parts.append(data)
        frame = build_frame(TYPE_CLIPFILES, b"".join(parts))

        with self._lock:
            peers = list(self.connections.items())
        if not peers:
            return 0
        sent = 0
        for _, sock in peers:
            try:
                sock.sendall(frame)
                sent += 1
            except Exception:
                pass
        names = ", ".join(n.decode("utf-8", "replace") for n, _ in blobs)
        print(f"[>] Sent {len(blobs)} copied file(s) [{names}] "
              f"to {sent} peer(s)")
        return sent

    def _save_clip_files(self, payload, peer_ip):
        saved = []
        try:
            off = 0
            count = struct.unpack_from(">H", payload, off)[0]
            off += 2
            for _ in range(count):
                name_len = struct.unpack_from(">H", payload, off)[0]
                off += 2
                name = payload[off:off + name_len].decode("utf-8", "replace")
                off += name_len
                data_len = struct.unpack_from(">Q", payload, off)[0]
                off += 8
                data = payload[off:off + data_len]
                off += data_len
                dest = self._write_recv_file(name, data, peer_ip)
                if dest:
                    saved.append(dest)
        except Exception as e:
            print(f"[!] Malformed copied-files frame from {peer_ip}: {e}")
            return
        if not saved:
            return
        print(f"[<] Received {len(saved)} copied file(s) from {peer_ip} "
              f"-> {self.recv_dir}")
        # Put them on our clipboard so they can be pasted straight away.
        if self.file_clip and self.file_clip.available:
            if self.file_clip.set_files(saved):
                self.mark_clip_files(saved)
                print("[*] Files placed on clipboard - paste (Ctrl+V) "
                      "in your file manager to use them.")

    @staticmethod
    def _unique_path(path):
        """Avoid overwriting: foo.txt -> foo (1).txt -> foo (2).txt ..."""
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        i = 1
        while True:
            candidate = f"{base} ({i}){ext}"
            if not os.path.exists(candidate):
                return candidate
            i += 1

    # -- lifecycle -------------------------------------------------------- #
    def start(self):
        print(f"[*] clipshare v{__version__}")
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
    parser.add_argument("--send-file", "-f", metavar="PATH",
                        help="Send a single file to all connected peers shortly "
                             "after startup, then keep running normally.")
    parser.add_argument("--recv-dir", default=DEFAULT_RECV_DIR, metavar="DIR",
                        help=f"Directory to store received files "
                             f"(default: {DEFAULT_RECV_DIR}).")
    parser.add_argument("--no-file-clip", action="store_true",
                        help="Disable copy/paste file syncing (copying files "
                             "in the file manager is otherwise mirrored to "
                             "peers, ready to paste).")
    parser.add_argument("--no-image", action="store_true",
                        help="Disable picture (clipboard image) syncing.")
    parser.add_argument("--version", action="version",
                        version=f"clipshare {__version__}")
    args = parser.parse_args()

    if args.send_file and not os.path.isfile(args.send_file):
        raise SystemExit(f"[!] --send-file: not a file: {args.send_file!r}")

    peers = []
    for item in args.peer:
        peers.extend(p.strip() for p in item.split(",") if p.strip())

    clip = Clipboard()
    net = PeerNet(args.port, peers, clip, password=args.password,
                  recv_dir=args.recv_dir)

    file_clip = None
    if not args.no_file_clip:
        file_clip = FileClipboard()
        net.file_clip = file_clip

    image_clip = None
    if not args.no_image:
        image_clip = ImageClipboard()
        net.image_clip = image_clip

    net.start()

    if args.send_file:
        print(f"[*] Will send file once a peer connects: {args.send_file}")
        threading.Thread(target=net.send_file_when_ready,
                         args=(args.send_file,), daemon=True).start()

    print(f"[*] Receiving files into: {os.path.abspath(args.recv_dir)}")
    if file_clip and file_clip.available:
        print(f"[*] Copy/paste file sync: on ({file_clip.describe()})")
    elif args.no_file_clip:
        print("[*] Copy/paste file sync: off (--no-file-clip)")
    else:
        print("[*] Copy/paste file sync: unavailable on this system "
              "(text still syncs)")
    if image_clip and image_clip.available:
        print(f"[*] Picture sync: on ({image_clip.describe()})")
    elif args.no_image:
        print("[*] Picture sync: off (--no-image)")
    else:
        print("[*] Picture sync: unavailable on this system "
              "(received images are saved to recv_dir)")
    print("[*] Watching clipboard. Copy something to share it. Ctrl+C to quit.")

    last_clip_files_sig = None
    next_file_poll = 0.0
    last_image_sig = None
    next_image_poll = 0.0
    try:
        while _running.is_set():
            changed = clip.poll_changed()
            if changed is not None:
                net.broadcast(changed)

            if image_clip and image_clip.available and time.time() >= next_image_poll:
                next_image_poll = time.time() + IMAGE_POLL_INTERVAL
                img = image_clip.get_image()
                if img:
                    # While an image sits on the clipboard, keep the text
                    # baseline fresh so the text poller does not echo the
                    # (now empty/garbage) text target as a "change".
                    v = clip.get()
                    if v is not None:
                        clip.last_value = v
                    sig = hashlib.md5(img).digest()
                    # Skip if unchanged, or if this is the image a peer just
                    # pushed onto our clipboard (avoid echoing it back).
                    if sig != last_image_sig and sig != net.recv_image_sig():
                        last_image_sig = sig
                        net.send_image(img)

            if file_clip and file_clip.available and time.time() >= next_file_poll:
                next_file_poll = time.time() + FILE_POLL_INTERVAL
                files = file_clip.get_files()
                if files:
                    sig = PeerNet._files_sig(files)
                    # Skip if unchanged, or if these are files a peer just
                    # pushed onto our clipboard (avoid echoing them back).
                    if sig != last_clip_files_sig and sig != net.recv_clip_sig():
                        last_clip_files_sig = sig
                        net.send_clip_files(files)

            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        _running.clear()
        print("\n[*] Stopped.")


if __name__ == "__main__":
    main()
