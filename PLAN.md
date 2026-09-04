# clipshare 项目计划与 Bug 管理

> 本文档是项目持续开发、平台完善工作的**推进依据**。新需求、Bug 修复完成后请同步更新本文档
> 的状态字段，并遵循“计划 → 实现 → 充分测试 → 固定代码 → 提交推送”的流程。

---

## 1. 项目概述与现状

clipshare：局域网多主机剪贴板共享（Windows / Linux 同一份 Python 代码）。

### 已实现功能（截至 commit `7e64504`）

| 模块 | 说明 |
|---|---|
| 文本剪贴板同步 | UDP 广播自动组网 + TCP 32620 传输；N 节点全网状（full mesh），一机复制、多机粘贴 |
| 密码认证 | `--password` / `CLIPSHARE_PASSWORD`，口令 SHA-256 比对，未通过认证的连接被拒绝 |
| 文件/文件夹同步 | 复制文件或文件夹自动镜像到对端；递归遍历、相对路径保留、防路径穿越、回环防护、2 GiB 上限 |
| 图片/截图同步 | 剪贴板图片（截图）以 PNG 传输并放回对端剪贴板；Windows CF_DIB、X11 xclip、Wayland wl-clipboard、X11 无 xclip 时用内置 python-xlib（x11py）后端 |
| 日志 | 默认输出到 `logs/`，按天分文件（`clipshare-YYYY-MM-DD.log`），启动清理超 31 天旧日志；`--log-dir` 可改/可关 |
| Linux 服务化 | systemd 用户级/系统级服务：`install_linux_service.sh {install|status|restart|uninstall} [--system]`，支持图形会话环境自动探测、SIGTERM/SIGHUP 优雅退出 |
| Windows 服务化 | 计划任务（pythonw 静默后台、异常自重启）+ NSSM 真服务方案：`install_windows_service.ps1 -Install/-Restart/-Status/-Uninstall` |
| 测试与文档 | `TEST_REPORT.md` 记录各阶段实机测试；README 中英双语 |

---

## 2. 项目计划

### 2.1 近期（当前阶段，优先推进）

- [ ] **P0-部署收尾**：宿主 A 重启 clipshare 服务，加载 x11py 图片后端；随后做生产网格 A→B 截图发送回归（沙箱无法重启宿主进程，需宿主本机执行 `systemctl --user restart clipshare`）
- [ ] **P0-Windows 实机验证**：在有 Windows 主机后，实测计划任务/NSSM 服务脚本、CF_HDROP 文件剪贴板、CF_DIB 图片剪贴板、日志功能；结果记入 TEST_REPORT
- [ ] **P1-系统级服务增强**：`install_linux_service.sh install --system` 增加交互式/自动配置 `User=`、`DISPLAY=`、`XAUTHORITY=`、`XDG_RUNTIME_DIR=` 引导，减少手动配置出错
- [ ] **P1-日志落点明确**：系统级服务单元默认追加 `--log-dir`（避免 root 家目录下产生日志），并在 README 说明

### 2.2 中期（平台完善）

- [ ] 安全增强：评估并实现传输通道加密（如 TLS/对称加密），认证口令加盐存储与比对
- [ ] 性能：多实例/大网格压测；大文件分片传输与断点续传
- [ ] 可运维性：交互式对端管理（添加/移除/查看 `--peer`）、单机状态查询命令（`--status` 输出网格与后端状态）
- [ ] 跨平台打包：PyInstaller 产出 Windows exe / Linux 可执行文件，简化部署（免装 Python）
- [ ] 服务化监控：systemd 单元增加 `Restart=always` 策略评估、异常退出告警

### 2.3 长期（平台演进）

- [ ] GUI 托盘程序：系统托盘图标、一键连接状态、拖拽文件发送、截图按钮
- [ ] Web/状态面板：查看网格拓扑、节点在线状态、剪贴板历史
- [ ] 跨网段/跨公网：中继服务器或 P2P 打洞，突破局域网限制
- [ ] 剪贴板历史与多剪贴板：本地历史回放、跨机历史检索

---

## 3. 待修复 Bug / 待办问题列表

字段说明：ID / 标题 / 严重度（高=阻断或影响核心功能，中=功能受损，低=体验） / 状态（待办 / 进行中 / 已修复 / 阻塞） / 备注

| ID | 标题 | 严重度 | 状态 | 备注 |
|---|---|---|---|---|
| BUG-001 | 宿主 A 服务仍运行旧代码，x11py 截图后端未生效 | 高 | 待办 | 沙箱无法重启宿主进程；宿主执行 `systemctl --user restart clipshare` 后回归 |
| BUG-002 | Windows 服务化脚本（计划任务/NSSM）未实机验证 | 高 | 待办 | 需 Windows 实机；含 -Restart 分支 |
| BUG-003 | Windows 原生文件/图片剪贴板（CF_HDROP/CF_DIB）未实机回归 | 高 | 待办 | 需 Windows 实机 |
| BUG-004 | 系统级服务需手动配置图形会话环境变量，易出错 | 中 | 待办 | 计划在 install 脚本增加自动引导（P1） |
| BUG-005 | 系统级服务（root）日志落点不明确 | 中 | 待办 | 默认在 root 家目录 logs/，计划追加 --log-dir（P1） |
| BUG-006 | 认证/传输安全待评估 | 中 | 待办 | 口令为 SHA-256 比对，传输通道加密方案待确认与实现 |
| BUG-007 | 自定义端口时显式 `--peer` 连接端口取本地端口 | 低 | 已知行为 | 各节点需统一端口；README 已说明，文档可再强调 |

---

## 4. 已修复 Bug 记录（历史）

| ID | 标题 | 修复说明 |
|---|---|---|
| FIX-001 | 本地复制粘贴不可用（缺 xclip） | 新增内置 python-xlib X11 文本后端 |
| FIX-002 | 文件夹无法同步 | FileClipboard 支持文件夹；发送端递归遍历并保留相对路径，接收端安全重建子目录 |
| FIX-003 | X11SelectionOwner 接口错误 | 改用 `w.set_selection_owner`（python-xlib 版本差异） |
| FIX-004 | 文件 URI 污染文本剪贴板 | x11py 文件后端移除文本 target，仅暴露文件 targets |
| FIX-005 | 多主机文档误导（1:1 描述） | 重写 docstring 为 N 节点全网状模型 |
| FIX-006 | NameError: signal | 补回 signal 模块导入 |
| FIX-007 | 服务启动后无法连接 D-Bus | 终端环境限制，改为进程/网络/对端同步间接验证 |

---

## 5. 已知限制与环境约束

- 沙箱/CI 终端运行于独立 PID 命名空间：无法 `kill`/`systemctl` 操作宿主服务（需在宿主本机操作）。
- Linux Wayland 需要 `wl-clipboard`；X11 无 `xclip` 时依赖 `python-xlib`（`requirements.txt` 已含）。
- 图片同步依赖截图/复制工具将 PNG 放入系统剪贴板作为触发。
- 文件总大小上限 2 GiB（单帧协议限制）。
- 本机 `/home` 部分挂载为只读（沙箱限制），部署类改动需在宿主上复核。

---

## 6. 工作流程约定

1. 变更必须：实现 → 本地/跨机充分测试 → 记录 TEST_REPORT → 提交推送（含更新本文档状态）。
2. git 提交邮箱固定为 `lihuiliang01@picc.com.cn`（远端钩子校验），已写入本机 git config。
3. 每次提交保持工作区干净，文档与代码同步更新。
