# WSL2 完整功能运行

WSL2 是 Windows 上运行 Shotwise 完整 Agent 功能的推荐方式。后端、前端和项目数据应放在 WSL 的 Linux 文件系统中，例如 `~/Shotwise`，不要长期从 `/mnt/c` 或 `/mnt/g` 运行开发服务，以免文件监听、权限和依赖性能下降。

## 1. 准备 Ubuntu

以下命令在 Ubuntu 24.04 中执行：

```bash
sudo apt update
sudo apt install -y git curl build-essential ffmpeg bubblewrap socat
```

安装 `uv`，并启用项目锁定版本的 pnpm：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
corepack enable pnpm
```

验证关键工具：

```bash
uv --version
node --version
pnpm --version
ffmpeg -version
bwrap --version
socat -V
```

## 2. 安装 Shotwise

```bash
cd ~
git clone https://github.com/ghc4412/Shotwise.git
cd Shotwise
cp .env.example .env
uv sync
uv run alembic upgrade head

cd frontend
pnpm install --frozen-lockfile
cd ..
```

不要把 Windows 生成的 `.venv` 或 `frontend/node_modules` 复制进 WSL。二者包含平台相关文件和绝对路径，必须在 WSL 中重新生成。

## 3. 启动开发服务

打开第一个 Ubuntu 终端启动后端：

```bash
cd ~/Shotwise
uv run uvicorn server.app:app \
  --reload \
  --reload-dir server \
  --reload-dir lib \
  --host 0.0.0.0 \
  --port 1241
```

打开第二个 Ubuntu 终端启动前端：

```bash
cd ~/Shotwise/frontend
pnpm dev --host 0.0.0.0
```

Windows 浏览器访问：

- 前端：<http://localhost:5173>
- 后端健康检查：<http://localhost:1241/health>

后端启动日志中的 `sandbox runtime: enabled=True` 表示完整 Agent 沙箱已启用。Linux 下如果 bwrap 探测失败，后端会直接退出并给出对应的 sysctl 或容器权限修复命令，不会静默降级。

## 4. Docker Compose 服务器部署

WSL 原生开发与 Docker Compose 部署彼此独立。服务器部署继续使用仓库现有配置。

SQLite 单机部署：

```bash
cd ~/Shotwise/deploy
cp .env.example .env
docker compose up -d --build
docker compose ps
```

PostgreSQL 生产部署：

```bash
cd ~/Shotwise/deploy/production
cp .env.example .env
# 编辑 .env，为 POSTGRES_PASSWORD 设置强随机值
docker compose up -d --build
docker compose ps
```

Compose 已为容器内 bwrap 配置 `seccomp:unconfined`、`apparmor:unconfined` 和 `NET_ADMIN`。运行前需要确保 Docker Desktop 已启用 WSL integration，或 Linux 服务器已经安装 Docker Engine 与 Compose 插件。

常用运维命令：

```bash
docker compose logs -f shotwise-app
docker compose pull
docker compose up -d --build
docker compose down
```

`docker compose down` 不会删除绑定到部署目录的项目、日志和数据库数据。不要使用 `docker compose down -v`，除非明确需要删除命名卷中的数据库数据。

## 5. 数据位置

| 运行方式 | 数据位置 |
|---|---|
| WSL 原生 | `~/Shotwise/projects`、`~/Shotwise/logs`、`~/Shotwise/vertex_keys` |
| Compose SQLite | `~/Shotwise/deploy/projects`、`logs`、`vertex_keys`、`claude_data` |
| Compose PostgreSQL | `~/Shotwise/deploy/production/pgdata`，以及同目录下的项目和运行目录 |

API Key 和 Agent 凭据通过 WebUI 设置页保存。`.env` 只保留认证、数据库、时区和日志等部署配置，不要提交到 Git。
