/** 提示词模板注册表的只读响应类型（与 server/routers/prompt_registry.py 对齐）。 */

/** 一个流程分组的取值；后端按此顺序返回。 */
export type PromptTemplateGroup = "system" | "agent" | "skill" | "reference";

/** 模板可声明的内容模式变体。 */
export type PromptTemplateContentMode = "drama" | "narration" | "ad";

/** 模板元数据（不含正文）；`path` 相对 profile 根目录，同时充当模板标识。 */
export interface PromptTemplateSummary {
  path: string;
  group: PromptTemplateGroup;
  title: string;
  description: string;
  content_mode: PromptTemplateContentMode | null;
  sections: string[];
  char_count: number;
}

export interface PromptRegistryResponse {
  templates: PromptTemplateSummary[];
}

export interface PromptTemplateDetailResponse {
  template: PromptTemplateSummary;
  content: string;
}
