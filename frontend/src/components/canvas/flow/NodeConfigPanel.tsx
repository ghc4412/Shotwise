import { useEffect, useMemo, useState } from "react";
import { Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { nodeTypeLabelKey } from "./node-registry";
import type { WorkflowNodeData } from "./workflow-utils";

interface FieldDef {
  key: string;
  labelKey: string;
  type: "number" | "text" | "textarea" | "checkbox" | "json";
  default?: unknown;
}

const NODE_FIELDS: Record<string, FieldDef[]> = {
  script_generate: [
    { key: "episode", labelKey: "flow_field_episode", type: "number", default: 1 },
    { key: "instructions", labelKey: "flow_field_instructions", type: "textarea" },
  ],
  script_review: [{ key: "script_file", labelKey: "flow_field_script_file", type: "text" }],
  storyboard_generate: [{ key: "script_file", labelKey: "flow_field_script_file", type: "text" }],
  storyboard_review: [{ key: "script_file", labelKey: "flow_field_script_file", type: "text" }],
  shot_image_generate: [
    { key: "script_file", labelKey: "flow_field_script_file", type: "text" },
    { key: "prompt", labelKey: "flow_field_prompt", type: "textarea" },
    { key: "only_missing", labelKey: "flow_field_only_missing", type: "checkbox" },
  ],
  shot_video_generate: [{ key: "video_prompt", labelKey: "flow_field_video_prompt", type: "textarea" }],
  voice_generate: [{ key: "script_file", labelKey: "flow_field_script_file", type: "text" }],
  subtitle_generate: [{ key: "script_file", labelKey: "flow_field_script_file", type: "text" }],
  compose: [
    { key: "episode", labelKey: "flow_field_episode", type: "number", default: 1 },
    { key: "draft_path", labelKey: "flow_field_draft_path", type: "text" },
  ],
  character_reference: [{ key: "characters", labelKey: "flow_field_characters", type: "text" }],
  source_import: [{ key: "source_file", labelKey: "flow_field_source_file", type: "text" }],
  image_input: [
    { key: "path", labelKey: "flow_field_asset_path", type: "text" },
    { key: "label", labelKey: "flow_field_label", type: "text" },
  ],
  video_input: [
    { key: "path", labelKey: "flow_field_asset_path", type: "text" },
    { key: "label", labelKey: "flow_field_label", type: "text" },
  ],
  loop: [{ key: "items", labelKey: "flow_field_items", type: "textarea" }],
  param_adjust: [{ key: "overrides", labelKey: "flow_field_overrides", type: "json" }],
};

const BRANCH_FIELDS: FieldDef[] = [
  { key: "condition.field", labelKey: "flow_field_condition_field", type: "text" },
  { key: "condition.equals", labelKey: "flow_field_condition_equals", type: "text" },
];

interface NodeConfigPanelProps {
  nodeId: string;
  data: WorkflowNodeData;
  onChange: (next: WorkflowNodeData) => void;
  onDelete: (nodeId: string) => void;
  onAddToGroup: (nodeId: string) => void;
}

function setAtPath(config: Record<string, unknown>, dottedKey: string, value: unknown): Record<string, unknown> {
  const parts = dottedKey.split(".");
  const next: Record<string, unknown> = { ...config };
  let cursor = next;
  for (const part of parts.slice(0, -1)) {
    const child = typeof cursor[part] === "object" && cursor[part] !== null ? { ...(cursor[part] as Record<string, unknown>) } : {};
    cursor[part] = child;
    cursor = child;
  }
  cursor[parts[parts.length - 1]] = value;
  return next;
}

function getAtPath(config: Record<string, unknown>, dottedKey: string): unknown {
  return dottedKey.split(".").reduce<unknown>((acc, part) => {
    if (typeof acc === "object" && acc !== null) return (acc as Record<string, unknown>)[part];
    return undefined;
  }, config);
}

function FieldEditor({
  field,
  value,
  onChange,
}: {
  field: FieldDef;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const { t } = useTranslation("dashboard");
  const label = t(field.labelKey);
  const base = "w-full rounded-md border border-hairline bg-bg px-2 py-1.5 text-[11px] text-text focus-ring";
  if (field.type === "checkbox") {
    return (
      <label className="flex items-center gap-2 text-[11px] text-text-2">
        <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} className="h-3.5 w-3.5 accent-current" />
        {label}
      </label>
    );
  }
  if (field.type === "textarea") {
    const text = typeof value === "string" ? value : "";
    return (
      <label className="block">
        <span className="mb-1 block text-[10px] text-text-3">{label}</span>
        <textarea value={text} onChange={(event) => onChange(event.target.value)} rows={4} className={`${base} resize-y`} />
      </label>
    );
  }
  if (field.type === "json") {
    const text = typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
    return (
      <label className="block">
        <span className="mb-1 block text-[10px] text-text-3">{label}</span>
        <textarea
          value={text}
          onChange={(event) => {
            try {
              onChange(JSON.parse(event.target.value));
            } catch {
              onChange(event.target.value);
            }
          }}
          rows={5}
          className={`${base} resize-y font-mono`}
        />
      </label>
    );
  }
  if (field.type === "number") {
    return (
      <label className="block">
        <span className="mb-1 block text-[10px] text-text-3">{label}</span>
        <input
          type="number"
          value={typeof value === "number" ? value : Number(field.default ?? 1)}
          onChange={(event) => onChange(Number(event.target.value))}
          className={base}
        />
      </label>
    );
  }
  const text = typeof value === "string" ? value : "";
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] text-text-3">{label}</span>
      <input value={text} onChange={(event) => onChange(event.target.value)} className={base} />
    </label>
  );
}

export function NodeConfigPanel({ nodeId, data, onChange, onDelete, onAddToGroup }: NodeConfigPanelProps) {
  const { t } = useTranslation("dashboard");
  const fields = useMemo<FieldDef[]>(() => {
    if (data.nodeType === "branch") return BRANCH_FIELDS;
    return NODE_FIELDS[data.nodeType] ?? [];
  }, [data.nodeType]);
  const [draft, setDraft] = useState(data.config);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- re-sync draft when switching selected node
  useEffect(() => setDraft(data.config), [data.config]);

  const commit = (next: Record<string, unknown>) => {
    setDraft(next);
    onChange({ ...data, config: next });
  };

  return (
    <aside className="flex w-[260px] shrink-0 flex-col border-l border-hairline bg-bg-raised">
      <header className="flex items-center justify-between gap-2 border-b border-hairline px-3 py-2">
        <div className="min-w-0">
          <h3 className="truncate text-[12px] font-semibold text-text">{t(nodeTypeLabelKey(data.nodeType))}</h3>
          <p className="truncate font-mono text-[9px] text-text-4">{nodeId}</p>
        </div>
        <button
          type="button"
          onClick={() => onDelete(nodeId)}
          className="grid h-6 w-6 shrink-0 place-items-center rounded text-text-3 transition-colors hover:bg-danger/10 hover:text-danger focus-ring"
          title={t("flow_node_delete")}
          aria-label={t("flow_node_delete")}
        >
          <Trash2 aria-hidden className="h-3.5 w-3.5" />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-[11px] text-text-2">
            <input
              type="checkbox"
              checked={data.disabled}
              onChange={(event) => onChange({ ...data, disabled: event.target.checked })}
              className="h-3.5 w-3.5 accent-current"
            />
            {t("flow_field_disabled")}
          </label>
          <button
            type="button"
            onClick={() => onAddToGroup(nodeId)}
            className="w-full rounded-md border border-hairline px-2 py-1.5 text-[11px] text-text-2 transition-colors hover:bg-bg focus-ring"
          >
            {t("flow_node_add_to_group")}
          </button>

          {fields.length > 0 ? (
            <div className="space-y-3 border-t border-hairline-soft pt-3">
              {fields.map((field) => (
                <FieldEditor
                  key={field.key}
                  field={field}
                  value={getAtPath(draft, field.key)}
                  onChange={(value) => commit(setAtPath(draft, field.key, value))}
                />
              ))}
            </div>
          ) : (
            <p className="border-t border-hairline-soft pt-3 text-[10px] text-text-4">{t("flow_node_no_params")}</p>
          )}
        </div>
      </div>
    </aside>
  );
}
