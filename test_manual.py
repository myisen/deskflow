#!/usr/bin/env python3
"""手动执行截图拷贝测试，每个场景分步验证"""
import paramiko, time, io, sys
from PIL import Image, ImageDraw

# 配置
HOSTS = {
    "UOS": {"ip": "10.180.15.216", "port": 22, "user": "user", "pass": "ELmm,,2026", "dir": "/home/user/dev/clipshare"},
    "Fedora": {"ip": "10.180.15.251", "port": 22, "user": "liang", "pass": "ELmm,,2026", "dir": "/home/liang/dev/clipshare"},
}
WINDOWS_DIR = r"D:\dev\clipshare"

def make_img(label):
    img = Image.new("RGB", (320, 120), color=(30, 80, 180))
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), label, fill="white")
    draw.text((20, 60), time.strftime("%H:%M:%S"), fill="yellow")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def ssh(host, cmd):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host["ip"], host["port"], host["user"], host["pass"], timeout=10)
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
        out = stdout.read().decode()
        err = stderr.read().decode()
        ssh.close()
        return out, err
    except Exception as e:
        return "", f"SSH Error: {e}"

def check_log(host, dir, keyword, wait=10):
    for _ in range(wait):
        if host == "Windows":
            try:
                with open(f"{dir}\\logs\\clipshare.log", "r", errors="replace") as f:
                    lines = f.readlines()
                    out = "".join(lines[-30:])
            except Exception:
                out = ""
        else:
            cmd = f"tail -30 {dir}/logs/clipshare.log 2>/dev/null"
            out, _ = ssh(HOSTS[host], cmd)
        if keyword in out:
            return True, out
        time.sleep(1)
    return False, out

def set_image_win(png):
    from clipshare import ImageClipboard
    ic = ImageClipboard()
    return ic._win_set_image(png)

def set_image_remote(host, dir, png, env):
    import base64
    b64 = base64.b64encode(png).decode()
    cmd = f"cd {dir} && {env} python3 -c \"import base64; from clipshare import ImageClipboard; ic=ImageClipboard(); ok=ic.set_image(base64.b64decode('{b64}')); print('ok='+str(ok))\" 2>&1"
    return ssh(host, cmd)

def run_test(test_id, desc, src, tgt):
    print(f"\n{'='*60}")
    print(f"【测试 {test_id}】{desc}")
    print(f"  源: {src}  →  目标: {tgt}")
    print(f"{'='*60}")

    img = make_img(desc)
    size = len(img)
    print(f"  [创建] 图片 {size} bytes")

    # 设置图片到源剪贴板
    if src == "Windows":
        ok = set_image_win(img)
        print(f"  [设置] Windows → {'成功' if ok else '失败'}")
    else:
        env = "DISPLAY=:0" if src == "UOS" else "WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000"
        out, err = set_image_remote(HOSTS[src], HOSTS[src]["dir"], img, env)
        print(f"  [设置] {src} → {out[:80]}")

    # 等待传输
    print(f"  [等待] 10秒...")
    time.sleep(10)

    # 检查源日志：Sent image
    src_dir = WINDOWS_DIR if src == "Windows" else HOSTS[src]["dir"]
    src_h = "Windows" if src == "Windows" else src
    sent, sent_log = check_log(src_h, src_dir, "Sent image", wait=3)
    print(f"  [源日志] {'✅ Sent image' if sent else '❌ 未发送'}")
    if sent:
        # 提取 Sent image 行
        for line in sent_log.split("\n"):
            if "Sent image" in line:
                print(f"    {line.strip()}")
                break

    # 检查目标日志：Received image
    tgt_dir = WINDOWS_DIR if tgt == "Windows" else HOSTS[tgt]["dir"]
    tgt_h = "Windows" if tgt == "Windows" else tgt
    recv, recv_log = check_log(tgt_h, tgt_dir, "Received image", wait=3)
    print(f"  [目标日志] {'✅ Received image' if recv else '❌ 未接收'}")
    if recv:
        for line in recv_log.split("\n"):
            if "Received image" in line:
                print(f"    {line.strip()}")
                break

    # 验证目标剪贴板
    print(f"  [验证] 目标剪贴板...")
    time.sleep(2)
    if tgt == "Windows":
        from clipshare import ImageClipboard
        ic = ImageClipboard()
        data = ic.get_image()
        ok = bool(data and len(data) > 0)
        print(f"    {'✅ 有图片' if ok else '❌ 无图片'} ({len(data) if data else 0} bytes)")
    else:
        env = "DISPLAY=:0" if tgt == "UOS" else "WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000"
        d = HOSTS[tgt]["dir"]
        out, _ = ssh(HOSTS[tgt], f"cd {d} && {env} python3 -c \"from clipshare import ImageClipboard; ic=ImageClipboard(); d=ic.get_image(); print('has_image='+str(d is not None and len(d)>0))\" 2>&1")
        ok = "has_image=True" in out
        print(f"    {'✅ 有图片' if ok else '❌ 无图片'} ({out.strip()[:80]})")

    result = sent and recv
    print(f"  【{'✅ 通过' if result else '❌ 失败'}】")
    return result

# ============================================================
# 执行
# ============================================================
results = []
passed = 0
failed = 0

tests = [
    ("1", "Windows → UOS 截图", "Windows", "UOS"),
    ("2", "Windows → Fedora 截图", "Windows", "Fedora"),
    ("3", "UOS → Windows 截图", "UOS", "Windows"),
    ("4", "UOS → Fedora 截图", "UOS", "Fedora"),
    ("5", "Fedora → Windows 截图", "Fedora", "Windows"),
    ("6", "Fedora → UOS 截图", "Fedora", "UOS"),
]

for tid, desc, src, tgt in tests:
    ok = run_test(tid, desc, src, tgt)
    results.append((tid, desc, ok))
    passed += 1 if ok else 0
    failed += 0 if ok else 1

# 测试7: 连续多次截图切换
print(f"\n{'='*60}")
print(f"【测试 7】连续多次截图切换测试")
print(f"{'='*60}")
rapid_ok = True
for i in range(3):
    img = make_img(f"RAPID-{i+1}")
    set_image_win(img)
    print(f"  [第{i+1}次] 设置图片 {len(img)} bytes")
    time.sleep(5)
    sent, log = check_log("Windows", WINDOWS_DIR, "Sent image", wait=3)
    if sent:
        print(f"    ✅ 已发送")
    else:
        print(f"    ❌ 未发送")
        rapid_ok = False
results.append(("7", "连续多次截图切换", rapid_ok))
passed += 1 if rapid_ok else 0
failed += 0 if rapid_ok else 1

# 测试8: 截图+文字混合操作
print(f"\n{'='*60}")
print(f"【测试 8】截图+文字混合操作测试")
print(f"{'='*60}")
mix_ok = True
import pyperclip

# 文字 → 图片 → 文字
for step_name, content in [
    ("文字复制", f"TEXT-1-{time.time()}"),
    ("图片复制", None),
    ("文字复制", f"TEXT-2-{time.time()}"),
]:
    if content is None:
        img = make_img("MIX-IMAGE")
        set_image_win(img)
        print(f"  [图片] 设置图片 {len(img)} bytes")
        keyword = "Sent image"
    else:
        pyperclip.copy(content)
        print(f"  [文字] 复制: {content[:40]}")
        keyword = "Sent text"
    time.sleep(5)
    found, log = check_log("Windows", WINDOWS_DIR, keyword, wait=3)
    if found:
        print(f"    ✅ 已发送")
    else:
        print(f"    ❌ 未发送")
        mix_ok = False

results.append(("8", "截图+文字混合操作", mix_ok))
passed += 1 if mix_ok else 0
failed += 0 if mix_ok else 1

# 汇总
print(f"\n{'='*60}")
print(f"测试汇总报告")
print(f"{'='*60}")
print(f"总计: {len(results)} 项测试")
print(f"通过: {passed}")
print(f"失败: {failed}")
for tid, desc, ok in results:
    print(f"  {'✅' if ok else '❌'} {tid}. {desc}")

sys.exit(0 if failed == 0 else 1)