/**
 * Agent SDK 凭证 + 预设供应商目录类型。
 *
 * 与后端 server/routers/agent_config.py 的 Pydantic 模型对齐。
 * ``sdk_type`` 区分 Agent SDK 接入方式：claude（Anthropic 协议）/ openai（OpenAI 协议）。
 */

export type AgentSdkType = "claude" | "openai";

export interface PresetProvider {
  id: string;
  sdk_type: AgentSdkType;
  display_name: string;
  icon_key: string;
  messages_url: string;
  discovery_url: string | null;
  default_model: string;
  suggested_models: string[];
  docs_url: string | null;
  api_key_url: string | null;
  notes: string | null;
  api_key_pattern: string | null;
  is_recommended: boolean;
  /** 是否提供 GET /v1/models 模型自动发现；false（如方舟 Agent/Coding Plan）时隐藏「获取模型列表」。 */
  supportsDiscovery: boolean;
}

export interface PresetProvidersResponse {
  providers: PresetProvider[];
  custom_sentinel_id: string;
}

/** 模型映射表条目：菜单显示名 → 实际请求模型（+ 可选上下文窗口）。 */
export interface AgentModelMapEntry {
  menu_name: string;
  request_model: string;
  context_window: number | null;
}

/** 模型发现返回的模型信息（模型映射选择器使用）。 */
export interface AgentDiscoveredModel {
  model_id: string;
  display_name: string;
  context_window: number | null;
}

export interface AgentCredential {
  id: number;
  sdk_type: AgentSdkType;
  preset_id: string;
  display_name: string;
  icon_key: string | null;
  base_url: string;
  api_key_masked: string;
  model: string | null;
  haiku_model: string | null;
  sonnet_model: string | null;
  opus_model: string | null;
  subagent_model: string | null;
  model_map: AgentModelMapEntry[] | null;
  is_active: boolean;
  created_at: string | null;
}

export interface CreateAgentCredentialRequest {
  sdk_type?: AgentSdkType;
  preset_id: string;
  display_name?: string | null;
  base_url?: string | null;
  api_key: string;
  model?: string | null;
  haiku_model?: string | null;
  sonnet_model?: string | null;
  opus_model?: string | null;
  subagent_model?: string | null;
  model_map?: AgentModelMapEntry[] | null;
  activate?: boolean | null;
}

export type UpdateAgentCredentialRequest = Partial<
  Omit<CreateAgentCredentialRequest, "preset_id" | "activate">
>;

export interface ProbeResult {
  success: boolean;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
}

export type DiagnosisCode =
  | "missing_anthropic_suffix"
  | "openai_compat_only"
  | "auth_failed"
  | "model_not_found"
  | "rate_limited"
  | "network"
  | "unknown";

export interface SuggestionAction {
  kind: "replace_base_url" | "check_api_key" | "run_discovery" | "see_docs";
  suggested_value: string | null;
}

export interface TestConnectionResponse {
  overall: "ok" | "warn" | "fail";
  messages_probe: ProbeResult;
  discovery_probe: ProbeResult | null;
  diagnosis: DiagnosisCode | null;
  suggestion: SuggestionAction | null;
  derived_messages_root: string;
  derived_discovery_root: string;
}

export interface TestConnectionRequest {
  sdk_type?: AgentSdkType;
  preset_id?: string | null;
  base_url?: string | null;
  api_key: string;
  model?: string | null;
}
