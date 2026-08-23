# 创作 Skill 灰度与媒体索引运维验收

本文只描述可执行的验收和运维动作。代码中已有的开关、接口或测试不等于生产环境已经完成灰度；生产完成必须以目标环境的命令输出、迁移记录和回填报告为准。

## 灰度配置校验

服务启动或变更配置后，调用 GET /api/v1/feature-flags/validate。返回 valid=false 时不得继续启用灰度。常见原因是 SHOTWISE_FEATURE_* 使用了未知名称，或值不是 1/0/true/false/yes/no/on/off。接口不会返回原始环境变量值，只返回每个开关的 enabled 和 source（environment/default/invalid）。

推荐上线顺序：先关闭新入口，验证旧路径，再按项目或环境逐项开启官方 Skill、MediaAsset 索引、Creation Plan、媒体库、Creative Board 和上下文 Agent。关闭 MediaAsset 索引后，旧项目必须仍使用原 JSON 路径和原文件访问 URL。

## Skill 事件与隐私边界

灰度指标覆盖 skill_open、skill_preview、skill_start、skill_success、skill_failure、skill_cancel、skill_incompatible。不兼容结果还应使用受控枚举记录后续结果，例如 dismissed、alternative_skill、new_project。

指标只允许项目无关的分类维度：Skill 版本 ID、generation mode、资源类型、原因码和结果码。禁止写入文稿、Prompt、媒体内容、物理路径、URL、文件名或用户输入原文。路径、空格、换行等自由文本会被指标记录接口拒绝。

## 旧项目媒体回填

迁移不会自动扫描媒体目录。先在目标项目执行 dry-run：

    uv run python -m server.media_index_cli <project-id> <project-root> --dry-run --report reports/<project-id>-media-dry-run.json

确认报告中的候选文件、缺失文件和不可识别文件后，再执行实际回填：

    uv run python -m server.media_index_cli <project-id> <project-root> --report reports/<project-id>-media-index.json

对账记录可重试；--retry 不能与 --dry-run 同时使用：

    uv run python -m server.media_index_cli <project-id> <project-root> --retry --report reports/<project-id>-media-retry.json

回填验收必须记录：重复执行前后的 MediaAsset 数量、物理路径清单哈希、缺失/非法文件数量、对账成功与失败数量。回填不得移动、重命名、覆盖、压缩、转码或删除原文件；报告失败也不得删除已生成媒体。

## SQLite / PostgreSQL 迁移清单

SQLite 开发库：

    $env:DATABASE_URL = "sqlite+aiosqlite:///./projects/.SHOTWISE.db"
    uv run alembic current
    uv run alembic upgrade head
    uv run alembic heads

PostgreSQL 验收环境：

    $env:DATABASE_URL = "postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>"
    uv run alembic current
    uv run alembic upgrade head
    uv run alembic heads

两种数据库都要确认：最新 head 为 p5_media_assets；Creation Skill、Creation Plan、MediaAsset、MediaBinding、MediaDerivation 和相关索引存在；已发布 Skill 没有无效 Workflow Revision 绑定；迁移不会触发历史媒体扫描。PostgreSQL 还需在备份和维护窗口内验证约束、外键和并发索引行为；SQLite 验收需覆盖旧项目关闭索引开关后的回退路径。

迁移失败时保留日志并停止回填，不要用降级迁移掩盖数据问题。任何 downgrade、生产回填和默认开关变更都需要单独的发布审批。

## 完成判定

只有同时具备以下证据，才能把对应项目标记为生产已验收：目标环境的配置校验为 valid、迁移命令和 schema 检查通过、dry-run 报告已审阅、实际回填与 retry 报告已归档、旧路径回退测试通过、Skill 生命周期与不兼容指标无敏感字段。仅有源码、单元测试或本地默认开关，不足以宣称生产完成。
