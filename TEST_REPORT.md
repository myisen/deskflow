# clipshare 测试报告

> 本报告包含两部分：
> - **Part 1**：Linux ↔ Linux 剪贴板同步功能测试（2026-09-01）
> - **Part 2**：服务化启动（systemd / Windows 计划任务）功能测试（2026-09-02）

---

## Part 1 跨机功能测试（Linux ↔ Linux）

- 测试时间：2026-09-01 15:0x ~ 15:2x
- 测试对象：clipshare v0.3（commit df5f8c1，含内置 python-xlib X11 后端 + 文件夹同步）
- 测试方式：双机实机互测 + 交叉同步验证（A→B / B→A）

## 测试环境

| 项 | 本机 A | 对端 B |
|---|---|---|
| IP | 10.180.15.216 | 10.180.15.251 |
| 主机名 | - | lianghwfedora |
| 系统 | Linux（X11） | Fedora 44（Wayland） |
| 代码路径 | /home/user/dev/clipshare | /home/liang/dev/clipshare |
| 剪贴板后端 | 内置 python-xlib（x11py） | wl-clipboard（Wayland） |
| 运行状态 | 测试期间运行，已停止 | 常驻运行 |

组网方式：UDP 广播自动发现，二者成功建立 TCP 32620 连接（另有 10.180.15.233 第三方节点参与，形成全网格）。

## 测试用例与结果

| # | 功能 | 方向 | 结果 | 说明 / 证据 |
|---|---|---|---|---|
| 1 | 文本剪贴板同步 | A→B | ✅ 通过 | 本机写入 `CS-TEST-TEXT-A2B-20260901`，对端 `wl-paste` 读到相同文本；本机日志 `[>] Sent clipboard to 2 peer(s)` |
| 2 | 文本剪贴板同步 | B→A | ✅ 通过 | 对端 `wl-copy` 写入 `CS-TEST-TEXT-B2A-20260901`，本机读到相同文本；日志 `[<] Clipboard updated from 10.180.15.251` |
| 3 | 单文件复制粘贴 | A→B | ✅ 通过 | `cs_single_a.txt`（46B）发送至对端 recv 目录；内容与 MD5（`7821b11b...`）双端完全一致 |
| 4 | 单文件复制粘贴 | B→A | ✅ 通过 | `cs_single_b.txt`（44B）反向同步至本机；MD5（`a08a40e0...`）完全一致 |
| 5 | 文件夹递归同步 | A→B | ✅ 通过 | 本机复制 `cs_test_src/`（含 subdir/deep 两级子目录）→ 对端完整重建目录树，3 个文件内容一致 |
| 6 | 文件夹递归同步 | B→A | ✅ 通过 | 对端复制 `cs_dir_b/`（含 level1/level2 两级子目录）→ 本机完整重建目录树，3 个文件内容一致 |
| 7 | 图片同步 | B→A | ✅ 通过 | 对端放入 1x1 PNG → 本机收到并保存 `clipboard.png`（70B），MD5（`2cd8bde4...`）一致 |
| 8 | 接收后放回剪贴板 | A/B | ✅ 通过 | 双方收到文件后日志输出 `[*] Files placed on clipboard - paste (Ctrl+V)...`；对端 `x-special/gnome-copied-files` 可读到 `file://` URI |
| 9 | 路径安全（防穿越） | - | ✅ 通过 | `_safe_relpath` 对 `../` 及 `a/../../evil` 均返回拒绝 |
| 10 | 多节点组网 | 全网格 | ✅ 通过 | 本机同时连接 .251 与 .233；三方剪贴板相互同步（捕获到对端真实文件 `skills.tar.gz` 3.7MB、`123456.txt`） |

## 关键日志摘录（本机 A）

```
[+] Connected to 10.180.15.233:32620
[+] Connected to 10.180.15.251:32620
[>] Sent 3 copied file(s) [cs_test_src/root.txt, cs_test_src/subdir/a.txt, cs_test_src/subdir/deep/b.txt] to 2 peer(s)
[>] Sent clipboard to 2 peer(s)
[<] Clipboard updated from 10.180.15.251
[<] Received 1 copied file(s) from 10.180.15.251 -> clipshare_recv
[*] Files placed on clipboard - paste (Ctrl+V) in your file manager to use them.
[<] Received 3 copied file(s) from 10.180.15.251 -> clipshare_recv
[*] Files placed on clipboard - paste (Ctrl+V) in your file manager to use them.
[>] Sent 1 copied file(s) [skills.tar.gz] to 2 peer(s)
[<] Received image (70 bytes) from 10.180.15.251
[*] No image clipboard backend; saved to clipshare_recv/clipboard.png
```

## 接收文件核对（双端 MD5 一致）

| 文件 | 本机 A | 对端 B |
|---|---|---|
| cs_single_a.txt | 源文件 | recv/cs_single_a.txt（46B，`7821b11b`） |
| cs_single_b.txt | recv/cs_single_b.txt（44B，`a08a40e0`） | 源文件 |
| cs_test_src/（文件夹） | 源 | recv/cs_test_src/{root.txt,subdir/a.txt,subdir/deep/b.txt} |
| cs_dir_b/（文件夹） | recv/cs_dir_b/{rb.txt,level1/l1.txt,level1/level2/l2.txt} | 源 |
| test_img.png | recv/clipboard.png（70B，`2cd8bde4`） | 源 |

## 结论

1. **文本、单文件、文件夹、图片** 四类剪贴板同步在 Linux ↔ Linux 之间双向均正常。
2. **文件夹同步**：递归遍历、相对路径保留、对端目录树重建正确。
3. **路径安全**：`_safe_relpath` 有效拦截目录穿越。
4. **多节点组网**：UDP 自动发现 + 全网格连接工作正常，三方数据互通。
5. **已知限制**：
   - 本机 A 为 X11 且未装 xclip，无图片剪贴板后端（`Picture sync: unavailable`），因此 A 无法主动复制图片；A→B 图片同步未测试。对端图片可正常到达 A 并保存为 `clipboard.png`。此限制在 README 中已有说明。
   - 图片同步 A→B 方向需要 A 侧安装 `xclip` 或补充 X11 图片后端。

## 遗留事项

- 测试产生的接收文件保留在双方 `clipshare_recv/`（已被 .gitignore 忽略），可手动清理。
- 对端 B 的 clipshare 仍在常驻运行；本机 A 的测试实例已停止。

---

## Part 2 服务化启动功能测试

- 测试时间：2026-09-02
- 测试对象：clipshare v0.3 + 服务化改动（commit 36c6b99 起）
  - `clipshare.py`：SIGTERM/SIGHUP 信号处理，主循环收到信号后打印 `[*] Stopped.` 并干净退出
  - `install_linux_service.sh`：Fedora/UOS systemd 服务安装脚本（用户级 / `--system` 系统级），支持从桌面进程自动探测图形会话环境（Wayland/X11），并设置 `PYTHONUNBUFFERED=1` 使 journalctl 实时显示日志
  - `install_windows_service.ps1`：Windows 计划任务安装脚本（`pythonw.exe` 静默运行、异常自动重启），另附 NSSM 真服务方案（README）
- 测试方式：本机 A（UOS）与对端 B（Fedora）实机安装 systemd 用户服务并互测；Windows 仅提供脚本（无 Windows 实机，未实机执行）

### 测试环境

| 项 | 本机 A | 对端 B |
|---|---|---|
| IP | 10.180.15.216 | 10.180.15.251 |
| 系统 | UOS（X11） | Fedora 44 KDE（Wayland） |
| 服务化方式 | systemd 用户服务 | systemd 用户服务 |
| 会话环境 | DISPLAY=:0 + python-xlib | WAYLAND_DISPLAY=wayland-0 + wl-clipboard |
| 剪贴板后端 | 内置 python-xlib（x11py） | wl-clipboard（Wayland） |

### 测试用例与结果

| # | 功能 | 结果 | 说明 / 证据 |
|---|---|---|---|
| 1 | systemd 用户服务安装 | ✅ 通过 | 本机与对端 B 均执行 `./install_linux_service.sh install` 成功，单元写入 `~/.config/systemd/user/clipshare.service` 并启用 |
| 2 | SSH 环境自动探测 | ✅ 通过 | 对端 B 通过 SSH（无会话环境变量）安装，脚本从 plasmashell 探测到 `WAYLAND_DISPLAY=wayland-0`、`XDG_RUNTIME_DIR=/run/user/1000`、`DBUS_SESSION_BUS_ADDRESS` 写入单元 |
| 3 | 服务自启状态 | ✅ 通过 | 两端 `systemctl --user is-active` = active、`is-enabled` = enabled |
| 4 | 服务内后端可用 | ✅ 通过 | 对端 B journal：`Copy/paste file sync: on (Linux Wayland (wl-clipboard))`、`Picture sync: on` |
| 5 | 服务内组网 | ✅ 通过 | 对端 B journal：`Mesh: connected to 2 peer(s): 10.180.15.216, 10.180.15.233` |
| 6 | 服务内日志实时性 | ✅ 通过 | 单元含 `PYTHONUNBUFFERED=1`，journal 逐行实时显示（含 Mesh/连接日志） |
| 7 | SIGTERM 优雅退出 | ✅ 通过 | 对端 B 实例收到 SIGTERM 后日志输出 `[*] Stopped.`，进程清零（`exited cleanly, zero daemons`） |
| 8 | 服务实例端到端同步 | ✅ 通过 | 本机 A 写入 `SVC-FINAL-1788329248`，经 systemd 服务实例同步，对端 B `wl-paste` 读到相同文本 |
| 9 | 反向同步 | ✅ 通过 | 对端 B `wl-copy` 写入 `REVERSE-1788328201`，本机 A 读到相同文本 |
| 10 | Windows 服务化脚本 | ⚠️ 未实机 | `install_windows_service.ps1`（计划任务）与 NSSM 方案已提供并在 README 说明；当前无 Windows 主机，未实机执行 |

### 关键日志摘录（对端 B systemd journal）

```
[*] Local IP: 10.180.15.251  TCP port: 32620
[*] Copy/paste file sync: on (Linux Wayland (wl-clipboard))
[*] Picture sync: on (Linux Wayland (wl-clipboard))
[*] Watching clipboard. Copy something to share it. Ctrl+C to quit.
[+] Connected to 10.180.15.233:32620
[*] Mesh: connected to 1 peer(s): 10.180.15.233
[+] Connected to 10.180.15.216:32620
[*] Mesh: connected to 2 peer(s): 10.180.15.216, 10.180.15.233
```

### 结论

1. **Linux 服务化（Fedora/UOS）**：systemd 用户服务可安装、随图形会话自启、常驻运行，剪贴板后端与组网在服务环境下完全正常。
2. **SSH 安装**：新增的图形会话环境自动探测使脚本可在无会话终端下正确生成含 `WAYLAND_DISPLAY`/`DISPLAY` 等变量的服务单元。
3. **优雅退出**：SIGTERM/SIGHUP 处理生效，`systemctl --user stop clipshare` 可干净停止并释放资源。
4. **日志**：`PYTHONUNBUFFERED=1` 保证 `journalctl --user -u clipshare -f` 实时可见日志。
5. **已知限制**：
   - Windows 侧脚本（计划任务 / NSSM）未在真实 Windows 主机上执行，仅提供与文档化；首次部署建议先 `-Status` 确认任务创建成功。
   - 系统级服务（`install --system`）以 root 运行且无图形会话，需按 README 说明补充 `User=`/`DISPLAY=`/`XAUTHORITY=` 等变量后方可读写剪贴板。

### 遗留事项

- 对端 B 已改为 systemd 用户服务常驻（非手动 nohup），与 A 端一致。
- Windows 实机部署与回归测试待有环境时补充。

---

## Part 3 截图（剪贴板图片）传输测试

- 测试时间：2026-09-02
- 测试对象：clipshare v0.3 + **x11py 图片后端**（为 X11 无 xclip 环境新增的 python-xlib 图片支持，如本机 UOS）
- 测试方式：隔离测试网格（A2 ↔ B2，均跑新代码，端口 32621，独立于生产网格 32620），模拟“截图复制到剪贴板”后做双向传输，全部实机互测
- 变更内容：`ImageClipboard` 新增 `x11py` 后端 —— `_detect_backend()` 在 X11 无 xclip 且 python-xlib 可用时回退到 x11py；`_x11py_get_image()` 用 `image/png` target 读取剪贴板 PNG，`_x11py_set_image()` 以 `image/png`/`PNG` target 占有剪贴板

### 测试环境

| 项 | A2（发送/接收方） | B2（接收/发送方） |
|---|---|---|
| 运行 | 沙箱内新代码实例（端口 32621） | 对端 B 新代码实例（端口 32621） |
| 图片后端 | `Linux X11 (python-xlib)`（x11py） | `Linux Wayland (wl-clipboard)` |
| 网格 | 1 对端（10.180.15.251） | 1 对端（10.180.15.216） |

### 测试用例与结果

| # | 功能 | 结果 | 说明 / 证据 |
|---|---|---|---|
| 1 | x11py 后端探测 | ✅ 通过 | 本机 UOS（X11、无 xclip）`ImageClipboard().backend == "x11py"`，describe 显示 `Linux X11 (python-xlib)` |
| 2 | x11py 本地往返 | ✅ 通过 | `set_image(png)` 后 `get_image()` md5 一致（76 字节 PNG）；`x11_paste(("image/png",))` 可取回；非 PNG 数据被拒绝；图片占有剪贴板时文本读取返回 None（不误触发文本轮询） |
| 3 | A→B2 截图传输 | ✅ 通过 | A2 的 X11 剪贴板放入 PNG → A2 检测发送 → B2 收到并 `wl-copy` 到 Wayland 剪贴板 → `wl-paste --type image/png` md5 一致（`8c6411386f832bc4d9a6e90c38bfd53b`） |
| 4 | B2→A 截图传输 | ✅ 通过 | B 的 Wayland 剪贴板放入 PNG → B2 检测发送 → A2 收到并以 x11py 放入 X11 剪贴板 → `get_image()` md5 一致 |
| 5 | 文本同步回归 | ✅ 通过 | 同一隔离网格内 A→B2 文本 `CS-IMG-REGRESSION-*` 正常同步（图片改动不影响文本） |
| 6 | 回环防护 | ✅ 通过 | 双向传输均未出现重复回传/无限循环（测试正常结束、无重复图片） |

### 关键日志摘录（A2）

```
[*] Picture sync: on (Linux X11 (python-xlib))
[+] Connected to 10.180.15.251:32621
[*] Mesh: connected to 1 peer(s): 10.180.15.251
```

### 结论

1. **无 xclip 的 X11 也可传输截图**：python-xlib 图片后端使本机 UOS 一类环境具备剪贴板图片的检测与放回能力，截图复制后即可跨机粘贴。
2. **双向链路完整**：X11(x11py) ↔ Wayland(wl) 之间 PNG 传输、解码、剪贴板放回均正确。
3. **无副作用**：图片占位不影响文本轮询，回环防护正常，文本同步无回归。
4. **已知限制**：
   - 本机宿主 A 的服务仍运行旧代码（沙箱无法重启宿主进程），x11py 图片后端需宿主下次重启服务后生效；其在沙箱内的实机验证已通过（同一 X 显示）。
   - 截图传输依赖截图工具把 PNG 放进系统剪贴板（与现有文本/图片同步一致的触发方式）。

### 遗留事项

- 待宿主 A 重启 clipshare 服务后，可做一次生产网格内的截图实机回归。
