"""提示词模板注册表只读 API。

- ``GET /prompts/registry`` —— 按流程分组列出全部模板的元数据；
- ``GET /prompts/registry/{template_path}`` —— 读取单条模板的元数据与正文。

两个端点只读，不触发任何运行时 prompt 组装。模板是随发行版一起发布的静态文件，
既不含密钥也不含用户数据，故只做常规认证、不做管理员限制。
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Path

from lib.api_errors import NotFoundError
from lib.prompt_registry import build_prompt_registry, find_prompt_template

router = APIRouter()


@router.get("/prompts/registry")
async def list_prompt_registry() -> dict[str, object]:
    """列出注册表全部条目的元数据（不含正文），顺序即设置页展示顺序。"""

    return {"templates": [asdict(entry) for entry in build_prompt_registry()]}


@router.get("/prompts/registry/{template_path:path}")
async def get_prompt_registry_entry(
    template_path: str = Path(description="相对 profile 根目录的 POSIX 路径"),
) -> dict[str, object]:
    """返回单条模板的元数据与正文；未知路径返回 404。"""

    detail = find_prompt_template(template_path)
    if detail is None:
        raise NotFoundError("prompt_template_not_found", path=template_path)
    return {"template": asdict(detail.template), "content": detail.content}
