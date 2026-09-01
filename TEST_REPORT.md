# clipshare 跨机测试报告（Linux ↔ Linux）

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
