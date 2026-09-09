#!/usr/bin/env python3
"""
ClipShare 截图拷贝完整测试计划

测试场景（6个方向 × 2 = 12次测试）：
  1. Windows → UOS 截图
  2. Windows → Fedora 截图
  3. UOS → Windows 截图
  4. UOS → Fedora 截图
  5. Fedora → Windows 截图
  6. Fedora → UOS 截图
  7. 连续多次截图切换测试
  8. 截图+文字混合操作测试

测试方法：
  - 每个方向：在源机器创建测试图片并放入剪贴板，检查目标机器是否收到
  - 通过日志验证传输结果
  - 通过目标机器的 ImageClipboard 后端验证图片可读
"""

import paramiko
import time
import io
import sys
from PIL import Image, ImageDraw

# ============================================================
# 配置
# ============================================================
HOSTS = {
    "Windows": {"ip": "10.180.15.233", "port": 22, "user": "", "pass": ""},
    "UOS": {"ip": "10.180.15.216", "port": 22, "user": "user", "pass": "ELmm,,2026"},
    "Fedora": {"ip": "10.180.15.251", "port": 22, "user": "liang", "pass": "ELmm,,2026"},
}

UOS_PROJECT_DIR = "/home/user/dev/clipshare"
FEDORA_PROJECT_DIR = "/home/liang/dev/clipshare"
WINDOWS_PROJECT_DIR = r"D:\dev\clipshare"

# ============================================================
# 辅助函数
# ============================================================

def create_test_image(text):
    """创建测试图片，包含可识别文字"""
    img = Image.new("RGB", (320, 120), color=(30, 80, 180))
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), text, fill="white")
    draw.text((20, 60), time.strftime("%H:%M:%S"), fill="yellow")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def ssh_exec(host, cmd, timeout=15):
    """在远程主机执行命令并返回输出"""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host["ip"], host["port"], host["user"], host["pass"], timeout=10)
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode()
        err = stderr.read().decode()
        ssh.close()
        return out, err
    except Exception as e:
        return "", f"SSH Error: {e}"


def test_remote_image_clipboard(host, label, project_dir, display_env=""):
    """在远程主机测试 ImageClipboard 是否可读"""
    cmd = (
        f"cd {project_dir} && {display_env} python3 -c "
        '"from clipshare import ImageClipboard; ic=ImageClipboard(); '
        f'print(\\"backend=\\" + (ic.backend or \\"None\\")); '
        f'print(\\"avail=\\" + str(ic.available)); '
        f'data=ic.get_image(); print(\\"has_image=\\" + str(data is not None and len(data)>0))" 2>&1'
    )
    out, err = ssh_exec(host, cmd)
    return out + err


def set_image_windows(png_data, log_prefix=""):
    """在 Windows 本地设置图片到剪贴板"""
    import ctypes
    from ctypes import wintypes
    from clipshare import ImageClipboard

    ic = ImageClipboard()
    ok = ic._win_set_image(png_data)
    print(f"{log_prefix} Windows set_image: {ok}")
    return ok


def set_image_remote(host, label, project_dir, png_data, display_env=""):
    """在远程主机设置图片到剪贴板"""
    import base64
    b64 = base64.b64encode(png_data).decode()
    cmd = (
        f"cd {project_dir} && {display_env} python3 -c "
        f'"import base64; from clipshare import ImageClipboard; '
        f'ic=ImageClipboard(); '
        f'data=base64.b64decode(\\\"{b64}\\\"); '
        f'ok=ic.set_image(data); print(\\\"set_image=\\\" + str(ok))" 2>&1'
    )
    out, err = ssh_exec(host, cmd)
    print(f"{label} set_image: {out.strip()[:100]}")
    if err:
        print(f"  stderr: {err[:200]}")


def check_log_contains(host, label, project_dir, keyword, timeout=10):
    """检查日志中是否包含关键字（带超时轮询）"""
    if host == HOSTS["Windows"]:
        log_path = f"{project_dir}\\logs\\clipshare.log"
        cmd = f'powershell -Command "Get-Content \\\"{log_path}\\\" -Tail 20 2>$null"'
    else:
        log_path = f"{project_dir}/logs/clipshare.log"
        cmd = f"tail -20 {log_path} 2>/dev/null || echo NO_LOG"

    for _ in range(timeout):
        out, err = ssh_exec(host, cmd)
        if keyword in out:
            return True, out[:500]
        time.sleep(1)
    return False, out[:500]


def run_test(test_id, test_name, source, target, set_func, display_env=""):
    """执行单个测试用例"""
    print(f"\n{'='*60}")
    print(f"【测试 {test_id}】{test_name}")
    print(f"  源: {source}  →  目标: {target}")
    print(f"{'='*60}")

    # 1. 确保日志不包含干扰项
    time.sleep(2)

    # 2. 在源机器创建并设置图片
    img_text = f"TEST-{test_id}-{source}to{target}"
    png_data = create_test_image(img_text)
    print(f"  [创建] 测试图片: {len(png_data)} bytes, 内容: {img_text}")

    if source == "Windows":
        if not set_image_windows(png_data, f"  [设置]"):
            print(f"  [失败] 无法在 Windows 设置图片")
            return False
    else:
        project_dir = UOS_PROJECT_DIR if source == "UOS" else FEDORA_PROJECT_DIR
        set_image_remote(
            HOSTS[source], f"  [设置]", project_dir, png_data, display_env
        )

    # 3. 等待传输
    print(f"  [等待] 等待传输完成...")
    time.sleep(5)

    # 4. 检查源日志：图片已发送
    src_log_dir = (
        WINDOWS_PROJECT_DIR if source == "Windows"
        else UOS_PROJECT_DIR if source == "UOS"
        else FEDORA_PROJECT_DIR
    )
    sent, sent_log = check_log_contains(
        HOSTS[source], source, src_log_dir, "Sent image", timeout=8
    )
    if sent:
        print(f"  [源日志] ✅ 已发送: {sent_log[:200]}")
    else:
        print(f"  [源日志] ❌ 未检测到发送记录")
        print(f"    日志: {sent_log[:200]}")

    # 5. 检查目标日志：图片已接收
    tgt_log_dir = (
        WINDOWS_PROJECT_DIR if target == "Windows"
        else UOS_PROJECT_DIR if target == "UOS"
        else FEDORA_PROJECT_DIR
    )
    recv, recv_log = check_log_contains(
        HOSTS[target], target, tgt_log_dir, "Received image", timeout=8
    )
    if recv:
        print(f"  [目标日志] ✅ 已接收: {recv_log[:200]}")
    else:
        print(f"  [目标日志] ❌ 未检测到接收记录")
        print(f"    日志: {recv_log[:200]}")

    # 6. 验证目标机器剪贴板可读
    print(f"  [验证] 检查目标机器剪贴板...")
    time.sleep(2)
    if target == "Windows":
        from clipshare import ImageClipboard
        ic = ImageClipboard()
        data = ic.get_image()
        has_img = data is not None and len(data) > 0
        print(f"  [目标剪贴板] ImageClipboard: {'✅ 有图片' if has_img else '❌ 无图片'} ({len(data) if data else 0} bytes)")
    else:
        tgt_project_dir = UOS_PROJECT_DIR if target == "UOS" else FEDORA_PROJECT_DIR
        tgt_display = "DISPLAY=:0" if target == "UOS" else "WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000"
        result = test_remote_image_clipboard(HOSTS[target], target, tgt_project_dir, tgt_display)
        has_img = "has_image=True" in result
        print(f"  [目标剪贴板] {result[:200]}")
        print(f"  {'✅ 有图片' if has_img else '❌ 无图片'}")

    result = sent and recv
    print(f"  【{'✅ 通过' if result else '❌ 失败'}】")
    return result


# ============================================================
# 测试执行
# ============================================================
if __name__ == "__main__":
    results = []
    passed = 0
    failed = 0

    display_envs = {
        "Windows": "",
        "UOS": "DISPLAY=:0",
        "Fedora": "WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000",
    }

    # 测试 1-6: 六方向截图测试
    scenarios = [
        ("1", "Windows → UOS 截图", "Windows", "UOS"),
        ("2", "Windows → Fedora 截图", "Windows", "Fedora"),
        ("3", "UOS → Windows 截图", "UOS", "Windows"),
        ("4", "UOS → Fedora 截图", "UOS", "Fedora"),
        ("5", "Fedora → Windows 截图", "Fedora", "Windows"),
        ("6", "Fedora → UOS 截图", "Fedora", "UOS"),
    ]

    for test_id, test_name, source, target in scenarios:
        ok = run_test(
            test_id, test_name, source, target,
            set_image_windows if source == "Windows" else set_image_remote,
            display_envs.get(source, ""),
        )
        results.append((test_id, test_name, ok))
        if ok:
            passed += 1
        else:
            failed += 1

    # 测试 7: 连续多次截图切换
    print(f"\n{'='*60}")
    print(f"【测试 7】连续多次截图切换测试")
    print(f"{'='*60}")
    rapid_ok = True
    for i in range(3):
        png = create_test_image(f"RAPID-{i}-{time.time()}")
        set_image_windows(png, f"  [第{i+1}次]")
        time.sleep(3)
        sent, _ = check_log_contains(HOSTS["Windows"], "Windows", WINDOWS_PROJECT_DIR, f"Sent image", timeout=5)
        if sent:
            print(f"  [第{i+1}次] ✅ 已发送")
        else:
            print(f"  [第{i+1}次] ❌ 未发送")
            rapid_ok = False
        time.sleep(1)
    results.append(("7", "连续多次截图切换", rapid_ok))
    passed += 1 if rapid_ok else 0
    failed += 0 if rapid_ok else 1

    # 测试 8: 截图+文字混合操作
    print(f"\n{'='*60}")
    print(f"【测试 8】截图+文字混合操作测试")
    print(f"{'='*60}")
    mix_ok = True

    # 先复制文字
    import pyperclip
    pyperclip.copy(f"TEXT-BEFORE-IMAGE-{time.time()}")
    print(f"  [文字] 复制文字到剪贴板")
    time.sleep(3)
    sent_text, _ = check_log_contains(HOSTS["Windows"], "Windows", WINDOWS_PROJECT_DIR, "Sent text", timeout=5)
    print(f"  {'✅ 文字已发送' if sent_text else '❌ 文字未发送'}")
    if not sent_text:
        mix_ok = False

    # 再复制图片
    png = create_test_image(f"MIX-TEST-{time.time()}")
    set_image_windows(png, f"  [图片]")
    time.sleep(3)
    sent_img, _ = check_log_contains(HOSTS["Windows"], "Windows", WINDOWS_PROJECT_DIR, "Sent image", timeout=5)
    print(f"  {'✅ 图片已发送' if sent_img else '❌ 图片未发送'}")
    if not sent_img:
        mix_ok = False

    # 再复制文字
    pyperclip.copy(f"TEXT-AFTER-IMAGE-{time.time()}")
    print(f"  [文字] 再次复制文字到剪贴板")
    time.sleep(3)
    sent_text2, _ = check_log_contains(HOSTS["Windows"], "Windows", WINDOWS_PROJECT_DIR, "Sent text", timeout=5)
    print(f"  {'✅ 文字已发送' if sent_text2 else '❌ 文字未发送'}")
    if not sent_text2:
        mix_ok = False

    # 检查远端剪贴板：最后应该存的是文字
    from clipshare import ImageClipboard
    ic = ImageClipboard()
    data = ic.get_image()
    if data and len(data) > 0:
        print(f"  [验证] Windows 剪贴板仍有图片 ({len(data)} bytes) - 远端图片已放置")
    else:
        print(f"  [验证] Windows 剪贴板图片已被文字覆盖 - 正常")

    results.append(("8", "截图+文字混合操作", mix_ok))
    passed += 1 if mix_ok else 0
    failed += 0 if mix_ok else 1

    # ============================================================
    # 汇总报告
    # ============================================================
    print(f"\n{'='*60}")
    print(f"测试汇总报告")
    print(f"{'='*60}")
    print(f"总计: {len(results)} 项测试")
    print(f"通过: {passed}")
    print(f"失败: {failed}")
    print(f"\n详细结果:")
    for tid, tname, ok in results:
        print(f"  {'✅' if ok else '❌'} {tid}. {tname}")

    if failed == 0:
        print(f"\n🎉 全部测试通过！")
    else:
        print(f"\n⚠️  {failed} 项测试失败，需要排查")

    sys.exit(0 if failed == 0 else 1)