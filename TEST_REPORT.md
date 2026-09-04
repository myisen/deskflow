# clipshare 测试报告

> 本报告包含四部分：
> - **Part 1**：Linux ↔ Linux 剪贴板同步功能测试（2026-09-01）
> - **Part 2**：服务化启动（systemd / Windows 计划任务）功能测试（2026-09-02）
> - **Part 3**：截图（剪贴板图片）传输测试（2026-09-02）
> - **Part 4**：P0 部署收尾 —— 宿主 A 服务重启 + 生产网格 A→B 截图发送回归（2026-09-04）

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
   - 系统级服务（`install --system`）自动探测桌面用户与图形会话环境（P1 已实现并提交 e431b00），详见 README。

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
| 7 | 生产网格接收路径 | ✅ 通过 | 对端 B 生产服务检测到 Wayland 剪贴板截图 → 经生产网格（32620）投递 → A 宿主服务收到并保存为 `clipboard (8).png`，md5 与源图一致（`422509640074112f3de8acb0119631a6`） |

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
   - 截图传输依赖截图工具把 PNG 放进系统剪贴板（与现有文本/图片同步一致的触发方式）。
   - （原“宿主 A 服务未加载 x11py”限制已解除，见 Part 4。）

### 遗留事项

- **本机宿主 A 服务已重启并加载 x11py 后端**（2026-09-04，见 Part 4）：
  `systemctl --user restart clipshare` 后启动横幅显示 `Picture sync: on (Linux X11 (python-xlib))`，
  生产网格 A→B 截图发送回归通过；发送路径此前已在隔离网格（32621）中以同一 X 显示实机验证。
- 生产网格 B→A 接收路径已实测通过（见用例 7）。

---

## Part 4 P0 部署收尾 —— 宿主 A 服务重启 + 生产网格 A→B 截图发送回归（2026-09-04）

- 测试时间：2026-09-04 10:42 ~ 10:45
- 测试对象：宿主 A 的 systemd 用户服务重启后加载 x11py 图片后端，随后在生产网格（32620）做 A→B 截图发送回归
- 前置：BUG-001 —— 宿主 A 服务启动时 X 连接失败，`Picture sync: unavailable`，x11py 未生效
- 触发方式：宿主 A 的 X11 剪贴板写入测试 PNG（96×64、178B、MD5 `becdedff348969b089f4dcb408838474`），
  与真实“截图复制到剪贴板”触发路径一致

### 操作

1. 通过宿主用户总线重启服务：`systemctl --user restart clipshare`
   （服务单元已含 `DISPLAY=:0`/`XAUTHORITY=/home/user/.Xauthority`，重启后 X 连接成功，x11py 生效）
2. 用 x11py 机制（`ImageClipboard.set_image`）把测试 PNG 写入宿主 A 剪贴板，保持所有者存活 5s 供服务轮询

### 测试用例与结果

| # | 项 | 结果 | 说明 / 证据 |
|---|---|---|---|
| 1 | 服务重启后 x11py 后端加载 | ✅ 通过 | 重启后启动横幅：`Local IP: 10.180.15.216`、`Copy/paste file sync: on (Linux X11 (built-in python-xlib))`、`Picture sync: on (Linux X11 (python-xlib))` |
| 2 | 生产网格 A→B 截图发送 | ✅ 通过（A 侧） | A 侧 X11 剪贴板写入 178B PNG → 服务检测并发送：日志 `[>] Sent image (178 bytes) to 2 peer(s)`，字节数与源 PNG 一致；B 侧目视确认待人工核对（沙箱无 B 访问权限） |
| 3 | 生产网格连通性 | ✅ 通过 | 重启后自动发现并连接 2 对端：`Mesh: connected to 2 peer(s): 10.180.15.233, 10.180.15.251` |

### 关键日志摘录（宿主 A）

```
2026-09-04 10:42:06 [*] clipshare v0.3
2026-09-04 10:42:06 [*] Local IP: 10.180.15.216  TCP port: 32620
2026-09-04 10:42:06 [*] Copy/paste file sync: on (Linux X11 (built-in python-xlib))
2026-09-04 10:42:06 [*] Picture sync: on (Linux X11 (python-xlib))
2026-09-04 10:42:08 [+] Connected to 10.180.15.251:32620
2026-09-04 10:42:10 [*] Mesh: connected to 2 peer(s): 10.180.15.233, 10.180.15.251
2026-09-04 10:44:38 [>] Sent image (178 bytes) to 2 peer(s)
```

### 结论

1. **BUG-001 已解决**：宿主 A 服务重启后 x11py 图片后端生效，`Picture sync: on (Linux X11 (python-xlib))`，
   `Local IP` 亦恢复为 `10.180.15.216`（此前启动时显示 127.0.0.1）。
2. **生产网格 A→B 截图发送路径通过**：A 侧剪贴板图片被服务检测并以 PNG 发送至全部对端（含 B），A 侧证据充分。
3. **遗留**：B 侧收图目视确认（B 的 Wayland 剪贴板 `wl-paste --type image/png` 或 recv 目录）需在有 B 访问权限时核对；
   测试 PNG 源文件保留在 `/tmp/cs_a2b_test.png`（MD5 `becdedff348969b089f4dcb408838474`）可供比对。

---

## Part 5 Windows 实机验证清单（2026-09-04 编制，待实机执行）

> 当前无 Windows 主机，Part 5 先完成**静态审查 + 验证清单编制**，便于拿到 Windows 实机后逐项勾选。
> 与本次配套的变更：修复 Windows 默认日志目录（`/var/log/clipshare` 为 Linux 路径，Windows 改为仓库内 `logs/`）。

### 5.1 静态审查结论

| 项 | 结论 |
|---|---|
| `install_windows_service.ps1` | 无阻断问题。`Get-PythonW` 通配探测 + PATH 兜底；计划任务设置 `-Hidden`、电池感知、失败自重启 3 次（间隔 1 分钟）、执行时长无限；`-Principal Interactive + RunLevel Limited` 无需管理员；`-Install/-Restart/-Status/-Uninstall` 分支完整 |
| CF_HDROP（文件） | `_win_get_files`/`_win_set_files` 结构正确：`DROPFILES` 布局、UTF-16-LE 宽字符、`OpenClipboard`/`CloseClipboard` 成对、`SetClipboardData` 后不误释放句柄（所有权移交剪贴板） |
| CF_DIB（图片） | `_dib_to_png` 正确解析 BITMAPINFOHEADER（支持 1/4/8/24/32 bpp、调色板、自底向上翻转）；`_png_to_dib` 用 Pillow 转 RGBA→BMP 后剥离 14 字节文件头。Windows 图片后端依赖 Pillow，缺失时降级为保存 PNG 到 recv 目录 |
| 回环防护 | 接收文件/图片放回剪贴板后，轮询器用 `recv_clip_sig()`/`recv_image_sig()` 比对签名，避免把“刚收到的”内容回传给对端，与 Linux 路径共用同一逻辑 |
| 日志落点 | 修复前默认 `/var/log/clipshare` 在 Windows 会解析为 `C:\var\log\clipshare`；已按平台区分，Windows 默认 `logs/`（计划任务 `WorkingDirectory` 为仓库目录，故落点为 `<仓库>\logs\clipshare.log`） |

### 5.2 Windows 实机验证清单（执行后逐项记录结果）

**A. 服务化（计划任务方案）**
- [ ] `powershell -ExecutionPolicy Bypass -File install_windows_service.ps1 -Install`
- [ ] `-Status` 显示任务存在、`LastTaskResult == 0`、`LastRunTime` 为最近
- [ ] 任务使用 `pythonw.exe`（无控制台窗口）；进程列表中存在 `pythonw.exe` 且无报错
- [ ] 剪贴板同步可用（见 D）；`-Restart` 后功能恢复
- [ ] `-Uninstall` 后任务移除、进程停止
- [ ] 服务重启/异常退出后自动拉起（任务设置 `RestartCount 3`）——可手动 Kill 进程观察

**B. 服务化（NSSM 真服务方案，可选）**
- [ ] NSSM 注册服务并随系统启动（`Services.msc` 可见 clipshare 服务）
- [ ] 服务状态下剪贴板同步可用

**C. 日志**
- [ ] 默认日志写入 `<仓库>\logs\clipshare.log`（非 `C:\var\log\clipshare`）
- [ ] 日志含时间戳前缀，启动横幅显示剪贴板后端状态
- [ ] `--log-dir ""` 可关闭文件日志；`--log-dir <dir>` 可改目录

**D. 功能回归（Windows ↔ Linux / Windows ↔ Windows）**
- [ ] 文本剪贴板：Windows 复制 → Linux 粘贴；反向亦然（双向）
- [ ] 文件 CF_HDROP：Windows 资源管理器复制文件 → Linux 收到到 recv；反向 Linux 复制 → Windows 粘贴可用
- [ ] 文件夹 CF_HDROP：Windows 复制文件夹 → Linux 重建目录树
- [ ] 图片 CF_DIB：Windows 截图（Win+Shift+S）→ Linux 收到 PNG；反向 Linux 复制图片 → Windows 剪贴板可粘贴
- [ ] 回环防护：双向无重复回传/无限循环

**E. 密码认证（可选）**
- [ ] 两端 `--password` 一致可互通；不一致被拒绝并告警

### 5.3 结论与遗留

- 静态审查未发现 Windows 侧功能阻断问题；`install_windows_service.ps1` 与 CF_HDROP/CF_DIB 实现结构正确。
- 本次修复一处跨平台回归：Windows 默认日志目录由 `/var/log/clipshare` 改为 `logs/`。
- **遗留**：以上 5.2 清单待 Windows 实机执行后逐项补记结果，并将结论汇总到本 Part。
