import { ChevronDown, Loader2, Plus, Search, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AgentDiscoveredModel, AgentModelMapEntry } from "@/types/agent-credential";
import { GHOST_BTN_CLS, ICON_BTN_CLS, INPUT_CLS } from "@/components/ui/darkroom-tokens";
import { Popover } from "@/components/ui/Popover";

interface Props {
  entries: AgentModelMapEntry[];
  onChange: (entries: AgentModelMapEntry[]) => void;
  /** 已发现模型（非空时每行「实际请求模型」出现下拉选择按钮）。 */
  discoveredModels: AgentDiscoveredModel[];
  onDiscover: () => void;
  discovering: boolean;
  discoverError: string | null;
}

export function ModelMapEditor({
  entries,
  onChange,
  discoveredModels,
  onDiscover,
  discovering,
  discoverError,
}: Props) {
  const { t } = useTranslation("dashboard");

  const updateRow = (index: number, patch: Partial<AgentModelMapEntry>) => {
    onChange(entries.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const removeRow = (index: number) => {
    onChange(entries.filter((_, i) => i !== index));
  };

  const addRow = () => {
    onChange([...entries, { menu_name: "", request_model: "", context_window: null }]);
  };

  const pickModel = (index: number, model: AgentDiscoveredModel) => {
    // 选中发现列表中的模型后，自动填入菜单显示名 / 实际请求模型 / 上下文窗口
    updateRow(index, {
      menu_name: model.display_name,
      request_model: model.model_id,
      context_window: model.context_window ?? null,
    });
  };

  return (
    <div className="rounded-[8px] border border-hairline-soft bg-bg-grad-a/35 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-text-2">
          {t("model_map_title")}
        </span>
        <div className="flex items-center gap-1.5">
          <button type="button" onClick={onDiscover} disabled={discovering} className={GHOST_BTN_CLS}>
            {discovering ? (
              <Loader2 className="h-3 w-3 motion-safe:animate-spin" aria-hidden />
            ) : (
              <Search className="h-3 w-3" aria-hidden />
            )}
            {discovering ? t("discovering_models") : t("model_map_fetch")}
          </button>
          <button type="button" onClick={addRow} className={GHOST_BTN_CLS}>
            <Plus className="h-3 w-3" aria-hidden />
            {t("model_map_add")}
          </button>
        </div>
      </div>

      {entries.length > 0 ? (
        <div
          className="grid gap-x-3 gap-y-1.5"
          style={{ gridTemplateColumns: "1fr 1.15fr 0.7fr auto" }}
        >
          <div className="font-mono text-[9.5px] font-bold uppercase tracking-[0.14em] text-text-4">
            {t("model_map_menu_name")}
          </div>
          <div className="font-mono text-[9.5px] font-bold uppercase tracking-[0.14em] text-text-4">
            {t("model_map_request_model")}
          </div>
          <div className="font-mono text-[9.5px] font-bold uppercase tracking-[0.14em] text-text-4">
            {t("model_map_context_window")}
          </div>
          <div aria-hidden />

          {entries.map((row, index) => (
            <ModelMapRow
              key={index}
              row={row}
              discoveredModels={discoveredModels}
              onPick={(model) => pickModel(index, model)}
              onPatch={(patch) => updateRow(index, patch)}
              onRemove={() => removeRow(index)}
            />
          ))}
        </div>
      ) : (
        <div className="rounded-[6px] border border-dashed border-hairline px-3 py-4 text-center text-[11.5px] text-text-3">
          {t("model_map_empty_hint")}
        </div>
      )}

      {discoverError && <div className="mt-2 text-[11px] text-warm-bright">{discoverError}</div>}
    </div>
  );
}

function ModelMapRow({
  row,
  discoveredModels,
  onPick,
  onPatch,
  onRemove,
}: {
  row: AgentModelMapEntry;
  discoveredModels: AgentDiscoveredModel[];
  onPick: (model: AgentDiscoveredModel) => void;
  onPatch: (patch: Partial<AgentModelMapEntry>) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation("dashboard");
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <input
        aria-label={t("model_map_menu_name")}
        value={row.menu_name}
        onChange={(e) => onPatch({ menu_name: e.target.value })}
        placeholder={t("model_map_menu_name_placeholder")}
        className={INPUT_CLS}
      />
      <div className="relative">
        <input
          aria-label={t("model_map_request_model")}
          value={row.request_model}
          onChange={(e) => onPatch({ request_model: e.target.value })}
          placeholder={t("model_map_request_model_placeholder")}
          className={`${INPUT_CLS} ${discoveredModels.length > 0 ? "pr-8" : ""}`}
        />
        {discoveredModels.length > 0 && (
          <>
            <button
              ref={pickerRef}
              type="button"
              onClick={() => setPickerOpen((v) => !v)}
              aria-label={t("model_map_pick_model")}
              className={`absolute right-1 top-1/2 -translate-y-1/2 ${ICON_BTN_CLS}`}
            >
              <ChevronDown className="h-4 w-4" aria-hidden />
            </button>
            <Popover
              open={pickerOpen}
              onClose={() => setPickerOpen(false)}
              anchorRef={pickerRef}
              width="w-72"
              // modal 容器是 z-50；Popover 默认 layer z-40 会被 modal 遮挡
              layer="modal"
              className="rounded-[8px] border border-hairline py-1 shadow-lg"
            >
              {discoveredModels.map((model) => (
                <button
                  key={model.model_id}
                  type="button"
                  onClick={() => {
                    onPick(model);
                    setPickerOpen(false);
                  }}
                  className="block w-full px-3 py-2 text-left hover:bg-bg-grad-a/50"
                >
                  <div className="truncate text-[12px] text-text-2">{model.display_name}</div>
                  <div className="truncate font-mono text-[10px] text-text-4">
                    {model.model_id}
                    {model.context_window ? ` · ${model.context_window}` : ""}
                  </div>
                </button>
              ))}
            </Popover>
          </>
        )}
      </div>
      <input
        aria-label={t("model_map_context_window")}
        type="number"
        min={0}
        value={row.context_window ?? ""}
        onChange={(e) =>
          onPatch({ context_window: e.target.value === "" ? null : Number(e.target.value) })
        }
        placeholder={t("model_map_context_window_placeholder")}
        className={INPUT_CLS}
      />
      <button
        type="button"
        onClick={onRemove}
        aria-label={t("model_map_delete")}
        className={`self-start ${ICON_BTN_CLS}`}
      >
        <Trash2 className="h-3.5 w-3.5" aria-hidden />
      </button>
    </>
  );
}
