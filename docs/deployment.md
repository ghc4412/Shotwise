# 部署补充说明

本文档补充 [`getting-started.md`](getting-started.md) 未覆盖的部署细节，主要面向已经能够通过 Docker / 本地启动 Shotwise 的运维与开发者。

Windows 用户需要完整 Agent 功能时，请先按 [`wsl2.md`](wsl2.md) 将代码和运行数据放入 WSL2 的 Linux 文件系统。服务器继续使用 `deploy/`（SQLite）或 `deploy/production/`（PostgreSQL）的 Docker Compose 配置。

## Agent 沙箱依赖

Shotwise 启动会进行严格的安全检查：sandbox 工具缺失即拒绝启动。

| 环境 | 工具 | 安装 |
|---|---|---|
| macOS | `sandbox-exec` | 系统自带，无需额外安装 |
| Linux 本地开发 | `bwrap` + `socat` | `sudo apt install bubblewrap socat` (Ubuntu/Debian) / `sudo dnf install bubblewrap socat` (Fedora) / `sudo pacman -S bubblewrap socat` (Arch) |
| Docker | `bwrap` + `socat` | Dockerfile 已包含 |

启动失败时 server 会输出明确错误信息，按提示安装即可。

**.env 迁移说明**：sandbox 设计要求父进程 `os.environ` 不含任何 provider 密钥。
请把 `.env` 中的下列 key 移到 WebUI 系统配置页：

- `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` 等 ANTHROPIC_*
- `ARK_API_KEY` / `XAI_API_KEY` / `GEMINI_API_KEY` / `VIDU_API_KEY` / `DASHSCOPE_API_KEY` / `MINIMAX_API_KEY` / `OPENAI_API_KEY`
- `GOOGLE_APPLICATION_CREDENTIALS`（vertex 凭据继续放 `vertex_keys/` 目录）

启动检测发现这些 key 仍存在于 env 时，server 会拒绝启动并提示需要清理。
