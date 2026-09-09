#!/usr/bin/env python3
"""Deploy clipshare.py to UOS and Fedora, then restart."""
import paramiko, os, time

script_path = r"d:\dev\clipshare\clipshare.py"
with open(script_path, "rb") as f:
    local_data = f.read()

# === Deploy to UOS ===
print("=== Deploying to UOS (10.180.15.216) ===")
try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("10.180.15.216", 22, "user", "ELmm,,2026", timeout=10)
    sftp = ssh.open_sftp()
    remote_path = "/home/user/dev/clipshare/clipshare.py"
    ssh.exec_command("pkill -f 'python3.*clipshare' 2>/dev/null; sleep 1")
    time.sleep(1)
    sftp.put(script_path, remote_path)
    sftp.close()
    print(f"  Uploaded {len(local_data)} bytes")
    stdin, stdout, stderr = ssh.exec_command(
        "cd /home/user/dev/clipshare && DISPLAY=:0 nohup python3 clipshare.py "
        "--log-dir logs >/dev/null 2>&1 &",
        timeout=10,
    )
    stdout.channel.recv_exit_status()
    time.sleep(3)
    stdin, stdout, stderr = ssh.exec_command(
        "cd /home/user/dev/clipshare && python3 clipshare.py --status", timeout=10
    )
    status = stdout.read().decode()
    print(f"  Status: {status[:300]}")
    ssh.close()
    print("  UOS: OK")
except Exception as e:
    print(f"  UOS Error: {e}")

# === Deploy to Fedora ===
print("=== Deploying to Fedora (10.180.15.251) ===")
try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("10.180.15.251", 22, "liang", "ELmm,,2026", timeout=10)
    sftp = ssh.open_sftp()
    remote_path = "/home/liang/dev/clipshare/clipshare.py"
    ssh.exec_command("pkill -f 'python3.*clipshare' 2>/dev/null; sleep 1")
    time.sleep(1)
    sftp.put(script_path, remote_path)
    sftp.close()
    print(f"  Uploaded {len(local_data)} bytes")
    stdin, stdout, stderr = ssh.exec_command(
        "cd /home/liang/dev/clipshare && WAYLAND_DISPLAY=wayland-0 "
        "XDG_RUNTIME_DIR=/run/user/1000 nohup python3 clipshare.py "
        "--log-dir logs >/dev/null 2>&1 &",
        timeout=10,
    )
    stdout.channel.recv_exit_status()
    time.sleep(3)
    stdin, stdout, stderr = ssh.exec_command(
        "cd /home/liang/dev/clipshare && python3 clipshare.py --status", timeout=10
    )
    status = stdout.read().decode()
    print(f"  Status: {status[:300]}")
    ssh.close()
    print("  Fedora: OK")
except Exception as e:
    print(f"  Fedora Error: {e}")

print("\n=== All deployments done ===")