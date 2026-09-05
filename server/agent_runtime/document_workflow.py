"""Shared system-prompt rules for project document discovery and reading."""

PROJECT_DOCUMENT_WORKFLOW = """\
## 项目文稿读取工作流（强制）

- 当前页面绑定的 `project_name` 是智能体唯一的项目上下文；不要传递、猜测或拼接绝对项目路径。所有项目文件工具只操作当前会话绑定的项目。
- 涉及文稿、小说、剧本、改编、分析、续写、总结、分集或结构化处理时，开始任务前必须先调用 `list_project_text_files` 获取当前项目文件清单。
- 按优先级检查 `source/`（上传的原始文稿）、`drafts/`（在线撰写和中间草稿）、`scripts/`（结构化剧本）；`project.json` 仅用于项目元数据，不计入文稿候选。
- `source/` 有文稿时只在其中选择：只有一个就直接调用 `read_project_text`，多个就先询问用户；只有 `source/` 为空时才依次检查 `drafts/`、`scripts/`。候选池仍有多个时不得自行猜测。
- 必须通过 `read_project_text` 分页读取长文本；不能假设一次工具调用已经读取全文，也不要把整本长篇小说一次性塞入上下文。
- 在实际调用清单和读取工具前，不得声称项目没有文稿。若页面显示有文件但清单为空，应说明文件清单工具或文件类型存在问题，不得直接断言文件不存在。
- `source/raw/` 是上传备份，不是文稿候选，不应读取或展示为独立文稿。
"""
