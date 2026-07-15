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
