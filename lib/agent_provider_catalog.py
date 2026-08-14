"""预设 Anthropic 兼容供应商目录。

每条 PresetProvider 提供 messages_url + discovery_url + 「获取 API Key」链接，
让用户在 UI 上选 chip 即填好 URL。`default_model` 仅作为输入框 placeholder
提示，不再自动预填到表单。

新增 entries 在此文件添加；前端 ICON_LOADERS 通过 icon_key 与 @lobehub/icons 对齐。
"""

from __future__ import annotations

from dataclasses import dataclass

CUSTOM_SENTINEL_ID = "__custom__"


@dataclass(frozen=True)
class PresetProvider:
    id: str
    display_name: str
    icon_key: str  # @lobehub/icons 子组件名 (如 "DeepSeek")
    messages_url: str
    discovery_url: str | None
    default_model: str
    suggested_models: tuple[str, ...]
    docs_url: str | None
    api_key_url: str | None
    notes_i18n_key: str | None
    api_key_pattern: str | None
    is_recommended: bool
    # display_name 的 i18n key；为空时直接用 display_name（当前所有预设为英文品牌名）
    name_i18n_key: str | None = None
    # 归属的 Agent SDK 类型：claude（Anthropic 协议端点）| openai（OpenAI 协议端点）
    sdk_type: str = "claude"
    # 是否提供 GET /v1/models 模型自动发现端点；为 False 的预设（如方舟
    # Agent/Coding Plan）UI 应隐藏「获取模型列表」按钮，改用 suggested_models 下拉或手动输入
    supports_discovery: bool = True


PRESET_PROVIDERS: dict[str, PresetProvider] = {
    "anthropic-official": PresetProvider(
        id="anthropic-official",
        display_name="Anthropic Official",
        icon_key="Anthropic",
        messages_url="https://api.anthropic.com",
        discovery_url="https://api.anthropic.com",
        default_model="",
        suggested_models=(),
        docs_url=None,
        api_key_url="https://platform.claude.com/",
        notes_i18n_key=None,
        api_key_pattern=r"^sk-ant-[A-Za-z0-9_-]+$",
        is_recommended=False,
    ),
    "alibaba-coding-plan": PresetProvider(
        id="alibaba-coding-plan",
        display_name="Alibaba Cloud Coding Plan",
        icon_key="Qwen",
        messages_url="https://coding.dashscope.aliyuncs.com/apps/anthropic",
        discovery_url=None,
        default_model="",
        suggested_models=(),
        docs_url="https://help.aliyun.com/zh/model-studio/coding-plan-faq",
        api_key_url="https://bailian.console.aliyun.com/",
        notes_i18n_key="preset_notes_alibaba_coding_plan",
        api_key_pattern=r"^sk-sp-[A-Za-z0-9_-]+$",
        is_recommended=True,
    ),
    "glm-cn": PresetProvider(
        id="glm-cn",
        display_name="Zhipu GLM (中国)",
        icon_key="Zhipu",
        messages_url="https://open.bigmodel.cn/api/anthropic",
        discovery_url="https://open.bigmodel.cn/api/anthropic",
        default_model="glm-5.1",
        suggested_models=(),
        docs_url=None,
        api_key_url="https://www.bigmodel.cn/glm-coding?ic=92O3DUV7NS",
        notes_i18n_key=None,
        api_key_pattern=None,
        is_recommended=False,
    ),
    "glm-intl": PresetProvider(
        id="glm-intl",
        display_name="Zhipu GLM (Global)",
        icon_key="Zhipu",
        messages_url="https://api.z.ai/api/anthropic",
        discovery_url="https://api.z.ai/api/anthropic",
        default_model="glm-5.1",
        suggested_models=(),
        docs_url=None,
        api_key_url="https://z.ai/subscribe?ic=3TIZJG5I0I",
        notes_i18n_key=None,
        api_key_pattern=None,
        is_recommended=False,
    ),
    "xiaomi-mimo": PresetProvider(
        id="xiaomi-mimo",
        display_name="Xiaomi MiMo",
        icon_key="XiaomiMiMo",
        messages_url="https://api.xiaomimimo.com/anthropic",
        discovery_url=None,
        default_model="mimo-v2.5-pro",
        suggested_models=(),
        docs_url=None,
        api_key_url="https://platform.xiaomimimo.com?ref=9JF5V2",
        notes_i18n_key="preset_notes_xiaomi_mimo",
        api_key_pattern=None,
        is_recommended=False,
    ),
    "deepseek": PresetProvider(
        id="deepseek",
        display_name="DeepSeek",
        icon_key="DeepSeek",
        messages_url="https://api.deepseek.com/anthropic",
        discovery_url="https://api.deepseek.com",
        default_model="deepseek-v4-pro",
        suggested_models=(),
        docs_url=None,
        api_key_url="https://platform.deepseek.com/",
        notes_i18n_key="preset_notes_deepseek",
        api_key_pattern=r"^sk-[A-Za-z0-9]+$",
        is_recommended=False,
    ),
    "minimax-cn": PresetProvider(
        id="minimax-cn",
        display_name="MiniMax (中国)",
        icon_key="Minimax",
        messages_url="https://api.minimaxi.com/anthropic",
        discovery_url="https://api.minimaxi.com/anthropic",
        default_model="MiniMax-M3",
        suggested_models=(),
        docs_url=None,
        api_key_url="https://platform.minimaxi.com/subscribe/coding-plan",
        notes_i18n_key=None,
        api_key_pattern=None,
        is_recommended=False,
    ),
    "minimax-intl": PresetProvider(
        id="minimax-intl",
        display_name="MiniMax (Global)",
        icon_key="Minimax",
        messages_url="https://api.minimax.io/anthropic",
        discovery_url="https://api.minimax.io/anthropic",
        default_model="MiniMax-M3",
        suggested_models=(),
        docs_url=None,
        api_key_url="https://platform.minimax.io/subscribe/coding-plan",
        notes_i18n_key=None,
        api_key_pattern=None,
        is_recommended=False,
    ),
    "kimi": PresetProvider(
        id="kimi",
        display_name="Kimi For Coding",
        icon_key="Kimi",
        messages_url="https://api.kimi.com/coding",
        discovery_url="https://api.kimi.com/coding",
        default_model="",
        suggested_models=(),
        docs_url=None,
        api_key_url="https://www.kimi.com/coding/docs/",
        notes_i18n_key=None,
        api_key_pattern=r"^sk-[A-Za-z0-9]+$",
        is_recommended=False,
    ),
    "ark-coding-plan": PresetProvider(
        id="ark-coding-plan",
        display_name="Volcengine Ark Coding Plan",
        icon_key="Volcengine",
        messages_url="https://ark.cn-beijing.volces.com/api/coding",
        discovery_url="https://ark.cn-beijing.volces.com",
        default_model="",
        suggested_models=(
            "doubao-seed-2.0-code",
            "doubao-seed-2.0-pro",
            "doubao-seed-2.0-lite",
            "doubao-seed-code",
            "glm-5.2",
            "glm-5.1",
            "glm-4.7",
            "kimi-k2.7-code",
            "kimi-k2.6",
            "kimi-k2.5",
            "kimi-k2-thinking",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "deepseek-v3.2",
            "minimax-m3",
            "minimax-m2.7",
            "minimax-m2.5",
            "ark-code-latest",
        ),
        docs_url="https://www.volcengine.com/docs/82379/1928262",
        api_key_url="https://console.volcengine.com/ark",
        notes_i18n_key="preset_notes_ark_coding_plan",
        api_key_pattern=None,
        is_recommended=False,
        name_i18n_key="provider_name_ark-coding-plan",
        supports_discovery=False,
    ),
    "ark-agent-plan": PresetProvider(
        id="ark-agent-plan",
        display_name="Volcengine Ark Agent Plan",
        icon_key="Volcengine",
        messages_url="https://ark.cn-beijing.volces.com/api/plan",
        discovery_url="https://ark.cn-beijing.volces.com",
        default_model="",
        suggested_models=(
            "doubao-seed-2.0-code",
            "doubao-seed-2.0-pro",
            "doubao-seed-2.0-lite",
            "doubao-seed-code",
            "glm-5.2",
            "glm-5.1",
            "glm-4.7",
            "kimi-k2.7-code",
            "kimi-k2.6",
            "kimi-k2.5",
            "kimi-k2-thinking",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "deepseek-v3.2",
            "minimax-m3",
            "minimax-m2.7",
            "minimax-m2.5",
            "ark-code-latest",
        ),
        docs_url="https://www.volcengine.com/docs/82379/2375486",
        api_key_url="https://console.volcengine.com/ark",
        notes_i18n_key="preset_notes_ark_agent_plan",
        api_key_pattern=None,
        is_recommended=False,
        name_i18n_key="provider_name_ark-agent-plan",
        supports_discovery=False,
    ),
    "tencent-tokenhub-coding": PresetProvider(
        id="tencent-tokenhub-coding",
        display_name="Tencent Cloud TokenHub Coding Plan",
        icon_key="TencentCloud",
        messages_url="https://api.lkeap.cloud.tencent.com/coding/anthropic",
        discovery_url=None,
        default_model="",
        suggested_models=(),
        docs_url="https://cloud.tencent.com/document/product/1823/130092",
        api_key_url="https://console.cloud.tencent.com/lkeap",
        notes_i18n_key="preset_notes_tencent_tokenhub_coding",
        api_key_pattern=r"^sk-sp-[A-Za-z0-9_-]+$",
        is_recommended=False,
    ),
    "openrouter": PresetProvider(
        id="openrouter",
        display_name="OpenRouter",
        icon_key="OpenRouter",
        messages_url="https://openrouter.ai/api",
        discovery_url="https://openrouter.ai/api",
        default_model="anthropic/claude-sonnet-4",
        suggested_models=(),
        docs_url="https://openrouter.ai/docs/guides/coding-agents/claude-code-integration",
        api_key_url="https://openrouter.ai/keys",
        notes_i18n_key="preset_notes_openrouter",
        api_key_pattern=r"^sk-or-v1-[A-Za-z0-9_-]+$",
        is_recommended=False,
    ),
    "siliconflow": PresetProvider(
        id="siliconflow",
        display_name="SiliconFlow",
        icon_key="SiliconCloud",
        messages_url="https://api.siliconflow.cn",
        discovery_url="https://api.siliconflow.cn",
        default_model="Pro/zai-org/GLM-4.7",
        suggested_models=(),
        docs_url="https://docs.siliconflow.cn/cn/api-reference/chat-completions/messages",
        api_key_url="https://cloud.siliconflow.cn/account/ak",
        notes_i18n_key="preset_notes_siliconflow",
        api_key_pattern=r"^sk-[A-Za-z0-9_-]+$",
        is_recommended=False,
    ),
    # ── OpenAI Agents SDK (OpenAI 协议端点) ──────────────────────────────────────
    "openai-official": PresetProvider(
        id="openai-official",
        display_name="OpenAI Official",
        icon_key="OpenAI",
        messages_url="https://api.openai.com",
        discovery_url="https://api.openai.com",
        default_model="",
        suggested_models=(),
        docs_url=None,
        api_key_url="https://platform.openai.com/api-keys",
        notes_i18n_key=None,
        api_key_pattern=r"^sk-[A-Za-z0-9_-]+$",
        is_recommended=False,
        sdk_type="openai",
    ),
    "deepseek-openai": PresetProvider(
        id="deepseek-openai",
        display_name="DeepSeek (OpenAI)",
        icon_key="DeepSeek",
        messages_url="https://api.deepseek.com",
        discovery_url="https://api.deepseek.com",
        default_model="deepseek-chat",
        suggested_models=("deepseek-chat", "deepseek-reasoner"),
        docs_url=None,
        api_key_url="https://platform.deepseek.com/",
        notes_i18n_key=None,
        api_key_pattern=r"^sk-[A-Za-z0-9]+$",
        is_recommended=True,
        sdk_type="openai",
    ),
    "kimi-openai": PresetProvider(
        id="kimi-openai",
        display_name="Kimi (Moonshot)",
        icon_key="Kimi",
        messages_url="https://api.moonshot.cn",
        discovery_url="https://api.moonshot.cn",
        default_model="kimi-k2",
        suggested_models=(),
        docs_url=None,
        api_key_url="https://platform.moonshot.cn/console/api-keys",
        notes_i18n_key=None,
        api_key_pattern=r"^sk-[A-Za-z0-9]+$",
        is_recommended=False,
        sdk_type="openai",
    ),
    "zhipu-openai": PresetProvider(
        id="zhipu-openai",
        display_name="Zhipu GLM (OpenAI)",
        icon_key="Zhipu",
        messages_url="https://open.bigmodel.cn/api/paas/v4",
        discovery_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-5.1",
        suggested_models=(),
        docs_url=None,
        api_key_url="https://www.bigmodel.cn/glm-coding?ic=92O3DUV7NS",
        notes_i18n_key=None,
        api_key_pattern=None,
        is_recommended=False,
        sdk_type="openai",
    ),
    "agnes-openai": PresetProvider(
        id="agnes-openai",
        display_name="Agnes",
        icon_key="Agnes",
        messages_url="https://apihub.agnes-ai.com/v1",
        discovery_url="https://apihub.agnes-ai.com/v1",
        default_model="agnes-2.0-flash",
        suggested_models=("agnes-2.0-flash",),
        docs_url=None,
        api_key_url="https://agnes-ai.com",
        notes_i18n_key=None,
        api_key_pattern=None,
        is_recommended=False,
        sdk_type="openai",
    ),
}


# 显示顺序：显式定义，Anthropic Official 永远第一，阿里云 Coding Plan 第二，其余按区域归组。
PRESET_ORDER: tuple[str, ...] = (
    "anthropic-official",
    "alibaba-coding-plan",
    "deepseek",
    "kimi",
    "xiaomi-mimo",
    "glm-cn",
    "glm-intl",
    "minimax-cn",
    "minimax-intl",
    "ark-coding-plan",
    "ark-agent-plan",
    "tencent-tokenhub-coding",
    "openrouter",
    "siliconflow",
    "openai-official",
    "deepseek-openai",
    "kimi-openai",
    "zhipu-openai",
    "agnes-openai",
)


def get_preset(preset_id: str) -> PresetProvider | None:
    return PRESET_PROVIDERS.get(preset_id)


def list_presets(sdk_type: str | None = None) -> list[PresetProvider]:
    presets = [PRESET_PROVIDERS[k] for k in PRESET_ORDER]
    if sdk_type is None:
        return presets
    return [p for p in presets if p.sdk_type == sdk_type]
