# clipshare

在同一局域网内的多台电脑之间共享剪贴板 —— **同一份 Python 代码可同时运行在 Windows 和 Linux 上**。

## 安装

```bash
pip install -r requirements.txt
# 仅 Linux 需要：安装剪贴板后端
#   X11     : sudo apt install xclip
#   Wayland : sudo dnf install wl-clipboard   （Fedora/RHEL）
#             sudo apt install wl-clipboard   （Debian/Ubuntu）
```

## 运行

在**每一台**机器上运行（无需参数 —— 它们会通过局域网广播自动组网）：

```bash
python clipshare.py
```

程序会自动发现局域网内的**所有**对端并组成全网状（full mesh）连接，因此 3 台或更多电脑可以共享同一个剪贴板。在任意一台上复制，在其他任意一台上粘贴即可。

TCP 服务端默认绑定在 `0.0.0.0` 的 **`32620`** 端口。

### 密码保护

在每一个节点上设置相同的密码（通过 `--password` 或 `CLIPSHARE_PASSWORD` 环境变量）。未提供正确密码的连接会被拒绝。不设置密码则保持开放（无认证）。

```bash
python clipshare.py --password yourSecret
# 或
CLIPSHARE_PASSWORD=yourSecret python clipshare.py
```

如果你的网络 / Wi-Fi 屏蔽了 UDP 广播，可以显式列出对端。你可以重复使用 `--peer` 或用逗号分隔；在**每一台**节点上都这样配置，列出*其他*节点：

```bash
# 节点 A:
python clipshare.py --password yourSecret --peer 192.168.1.50 --peer 192.168.1.60
# 节点 B:
python clipshare.py --password yourSecret --peer 192.168.1.40 --peer 192.168.1.60
# 节点 C:
python clipshare.py --password yourSecret --peer 192.168.1.40 --peer 192.168.1.50
# （也支持逗号形式: --peer 192.168.1.50,192.168.1.60）
```

### 对端管理与状态查询（运维命令）

显式对端可以**持久化**到仓库内 `peers.conf`，守护进程启动时自动读取（与命令行 `--peer` 合并去重）；方便服务化部署后不改服务单元即可增删对端：

```bash
# 持久化添加 / 移除 / 查看对端（立即生效，下次启动守护进程时加载）
python clipshare.py --peer-add 192.168.1.50
python clipshare.py --peer-del 192.168.1.50
python clipshare.py --peer-list
```

`--status` 在**不启动守护进程**的前提下输出单机状态：版本、本地 IP/端口、认证、配置的对端、各剪贴板后端，以及守护进程是否在运行（若在运行且状态快照新鲜，还会列出当前已连接的对端）：

```bash
python clipshare.py --status
[*] clipshare v0.3
[*] Local IP: 10.180.15.216  TCP port: 32620
[*] Auth: off
[*] Peers (peers.conf): 192.168.1.50
[*] Text backend : Linux X11 (built-in python-xlib)
[*] File backend : Linux X11 (built-in python-xlib)
[*] Image backend: Linux X11 (python-xlib)
[*] Daemon: running (pid 1234, snapshot 5s ago)
[*] Mesh: connected to 2 peer(s): 192.168.1.50, 192.168.1.60
[*] Log dir: '/var/log/clipshare'  Recv dir: /home/user/dev/clipshare/clipshare_recv
```

> 守护进程把运行状态快照写入仓库内 `clipshare.status`（每次组网变化时刷新，停止时删除），
> `--status` 据此显示“运行中 + 已连接对端”；两者都被 .gitignore 忽略。

## 文件传输

除了同步剪贴板文本，clipshare 还支持向所有已连接的对端发送**单个文件**。

- `--send-file <路径>` / `-f <路径>`：启动后待有对端连接，即把该文件发送给所有已连接的对端，随后继续正常运行（继续同步剪贴板）。
- `--recv-dir <目录>`：接收到的文件保存到该目录（默认 `clipshare_recv`）。目录不存在时会自动创建；若存在同名文件，会自动重命名为 `文件名 (1).ext`、`文件名 (2).ext` 以避免覆盖。

```bash
# 发送一个文件（启动后等待对端连接，最长等待约 15 秒）
python clipshare.py --send-file ./report.pdf

# 指定接收文件的存放目录
python clipshare.py --recv-dir ./inbox
```

说明：

- 单个文件大小上限为 2 GiB。
- 文件通过与剪贴板相同的加密/认证通道传输；设置了密码时，同样需要通过认证。
- 接收端会对文件名做安全处理（仅保留文件名部分），防止对端写入接收目录之外的位置。

## 复制粘贴文件（文件级剪贴板）

clipshare 还能同步**在文件管理器里“复制”的文件**：在一台机器上复制文件（Ctrl+C），在另一台机器上直接粘贴（Ctrl+V）即可。

- 该功能**默认开启**，无需额外参数。在一台机器上复制文件后，会自动把文件传给所有对端；对端会将文件保存到接收目录，并**放回其系统剪贴板**，于是可在文件管理器中直接 Ctrl+V 粘贴出来。
                                                                                                                                                                                                                                                                                                                                                    - `--no-file-clip`：关闭复制粘贴文件功能（仍会同步剪贴板文本）。

```bash
# 默认即启用，直接运行即可
python clipshare.py

# 如需关闭
python clipshare.py --no-file-clip
```

平台支持：

- **Windows**：原生支持（CF_HDROP）。
- **Linux X11**：需要 `xclip`。
- **Linux Wayland**：需要 `wl-clipboard`（`wl-copy` / `wl-paste`）。
- 若当前系统缺少上述后端，则该功能自动禁用（不影响文本同步）；启动时会打印当前状态。

说明：

- 复制的文件同样受 2 GiB 总大小上限约束，并通过相同的认证通道传输。
- 接收到的文件先保存到接收目录（见上文 `--recv-dir`），再放回剪贴板；同名文件会自动重命名以避免覆盖。
- 已内置回环防护：对端推送并放到本地剪贴板的文件不会被再次回传。

## 图片共享（剪贴板图片）

clipshare 还能同步**复制到剪贴板的图片**：在一台机器上复制一张图片（例如截图），在另一台机器上直接粘贴（Ctrl+V）即可。

- 该功能**默认开启**，无需额外参数。复制图片后会自动把图片（PNG）传给所有对端；对端会把图片放回其系统剪贴板，于是可在任意支持粘贴图片的程序里直接 Ctrl+V。
- `--no-image`：关闭图片同步（仍会同步剪贴板文本与文件）。

```bash
# 默认即启用，直接运行即可
python clipshare.py

# 如需关闭
python clipshare.py --no-image
```

平台支持：

- **Windows**：原生支持（CF_DIB，需安装 Pillow 做格式转换）。
- **Linux X11**：需要 `xclip`。
- **Linux Wayland**：需要 `wl-clipboard`（`wl-copy` / `wl-paste`）。
- 若当前系统缺少上述后端，则收到的图片会自动保存到接收目录（见 `--recv-dir`），不会丢失；启动时会打印当前状态。

说明：

- 图片以 PNG 格式传输，沿用相同的认证通道与 2 GiB 上限。
- 复制图片时会自动同步文本基线，避免把剪贴板残留的空文本误当作一次“文本变更”回传给对端。
- 已内置回环防护：对端推送并放到本地剪贴板的图片不会被再次回传。

## 工作原理

- 每个节点都运行一个 TCP 服务端（接收更新）以及每个对端一个 TCP 客户端（推送更新）。重复连接会被去重，因此每一对节点之间恰好只有一条连接 —— 在 N 个节点间形成全网状。
- 一个轮询器监视本地剪贴板。检测到的**本地**变更会被广播给所有已连接的对端；从对端**收到**的更新会被写入本地剪贴板并打上标记，避免被回传（不会形成无限同步循环）。
- 仅支持文本。任一节点上的变更会一跳传播到所有其他节点。

## 故障排查

- 确保防火墙放行 TCP `32620`（以及用于发现的 UDP `54321`）。
- 如果自动发现无法连接，优先使用 `--peer <ip>`。
- Linux 需要 `xclip`（X11）或 `wl-clipboard`（Wayland）作为 `pyperclip` 的后端。

## 用户信息

- 作者 / 维护者：lihuiliang01
- 邮箱：lihuiliang01@picc.com.cn
- 代码仓库：http://code.devops.piccnet/picc/lihuiliang01picc.com.cn/clipshare.git
- 许可证：见 [LICENSE](LICENSE)
