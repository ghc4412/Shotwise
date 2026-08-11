# 部署补充说明

本文档补充 [`getting-started.md`](getting-started.md) 未覆盖的部署细节，主要面向已经能够通过 Docker / 本地启动 SHOTWISE 的运维与开发者。

## 部署方式选择

SHOTWISE 启动会进行严格的安全检查 — sandbox 工具缺失即拒绝启动。

| 环境 | 工具 | 安装 |
|---|---|---|
| macOS | `sandbox-exec` | 系统自带，无需额外安装 |
| Linux 本地开发 | `bwrap` + `socat` | Ubuntu/Debian：`sudo apt install bubblewrap socat`；Fedora：`sudo dnf install bubblewrap socat`；Arch：`sudo pacman -S bubblewrap socat` |
| Docker | `bwrap` + `socat` | 官方镜像已包含 |
| Windows 原生 | 无 `bwrap` 沙箱 | 自动降级为 Bash 命令白名单；推荐 WSL2 / Docker Desktop |

官方 Compose 为 Agent Bash 沙箱配置了：

- `seccomp:unconfined`
- `apparmor:unconfined`
- `NET_ADMIN`

这些设置用于支持容器中的 `bwrap` 隔离和嵌套网络命名空间，但也意味着容器获得了比普通 Web 应用更高的权限。

生产部署建议：

- 使用专用主机或至少使用隔离良好的运行环境；
- 不把 Docker Socket 挂载到容器；
- 不额外挂载不必要的宿主机目录；
- 限制管理页面访问范围；
- 及时更新 Shotwise 和基础镜像；
- 只为 Agent 配置必要的网络和文件访问权限；
- 对未知来源的项目输入保持谨慎。

Docker 镜像虽然已包含 `bwrap` 和 `socat`，宿主机的 user namespace 或 AppArmor 策略仍可能阻止沙箱启动。启动失败时应根据服务输出的 `SANDBOX_*` 诊断修复，不要改成特权模式绕过检查，也不要在不了解影响的情况下删除官方 Compose 的沙箱配置。

## 9. 监控建议

最低限度应监控：

- `/health` 是否可用；
- 容器是否频繁重启；
- 磁盘剩余空间；
- `projects/` 增长速度；
- PostgreSQL 数据目录大小；
- 任务失败率；
- 供应商限流和额度不足；
- 备份最近成功时间。

媒体资产增长通常快于数据库，应优先为项目目录设置容量告警。

## 10. 常见故障

### 服务无法启动

```bash
docker compose ps
docker compose logs --tail=300 shotwise
```

检查：

- `.env` 是否存在；
- 端口 `1241` 是否被占用；
- 镜像是否成功拉取；
- 挂载目录是否可写；
- 生产部署是否设置 `POSTGRES_PASSWORD`。

### 健康检查失败

```bash
curl -v http://localhost:1241/health
docker compose logs --tail=300 shotwise
```

如果容器刚启动，先确认是否仍在执行数据库迁移。

### 无法登录

- 检查 `AUTH_USERNAME`；
- 检查 `.env` 中的 `AUTH_PASSWORD`；
- 如果首次启动时密码留空，查看是否已被回写；
- 修改 `AUTH_TOKEN_SECRET` 后需要重新登录。

### Agent 请求失败

- 验证 AI 助手凭据；
- 检查 Base URL 和模型名称；
- 检查网络和代理；
- 查看供应商是否限流；
- 使用少量内容验证，不要用完整小说做连接测试。

### 任务一直排队

- 查看图像、视频和音频并发设置；
- 检查是否有长时间停留在运行中或取消中的异常任务；
- 查看供应商 RPM 配额；
- 检查前序任务是否尚未完成。

### 磁盘快速增长

重点检查：

```bash
du -sh projects logs
find projects -type f -size +500M
```

不要直接删除当前项目引用的文件。优先通过项目归档、清理无用项目和保留必要版本控制空间。

## 11. 上线检查清单

- [ ] 使用 PostgreSQL；
- [ ] 固定 Release 镜像版本；
- [ ] 设置强 `AUTH_PASSWORD`；
- [ ] 设置固定 `AUTH_TOKEN_SECRET`；
- [ ] 配置 HTTPS；
- [ ] 不直接暴露 `1241`；
- [ ] 验证 SSE 可正常工作；
- [ ] 备份数据库和项目目录；
- [ ] 完成一次恢复演练；
- [ ] 配置磁盘和健康检查告警；
- [ ] 确认模型 API Key 不出现在日志和仓库；
- [ ] 阅读许可证和 `NOTICE`。
