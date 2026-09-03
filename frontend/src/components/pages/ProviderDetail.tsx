import { useState, useEffect, useCallback, useMemo, type CSSProperties } from "react";
import { errMsg, voidCall, voidPromise } from "@/utils/async";
import { ChevronRight, ExternalLink, Eye, EyeOff, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useWarnUnsaved } from "@/hooks/useWarnUnsaved";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { ProviderIcon } from "@/components/ui/ProviderIcon";
import { PillSwitch } from "@/components/ui/PillSwitch";
import { CredentialList } from "@/components/pages/CredentialList";
import { formatDurationsLabel } from "@/utils/duration_format";
import { ACCENT_BTN_CLS, ACCENT_BUTTON_STYLE, CARD_STYLE, GHOST_BTN_CLS, INPUT_CLS } from "@/components/ui/darkroom-tokens";
import { FieldLabel } from "@/components/ui/FieldLabel";
import type { ModelMediaType, ProviderConfigDetail, ProviderField, ProviderTestResult } from "@/types";

// ---------------------------------------------------------------------------
// Status badge — Darkroom OKLCH tokens
// ---------------------------------------------------------------------------

interface BadgeStyle {
  label: string;
  style: CSSProperties;
}

const STATUS_BADGE_MAP: Record<string, BadgeStyle> = {
  ready: {
    label: "status_ready",
    style: {
      background: "oklch(0.30 0.10 155 / 0.18)",
      color: "var(--color-good)",
      border: "1px solid oklch(0.45 0.10 155 / 0.40)",
      boxShadow: "0 0 14px -6px oklch(0.55 0.10 155 / 0.50)",
    },
  },
  unconfigured: {
    label: "status_unconfigured",
    style: {
      background: "var(--color-bg-grad-a)",
      color: "var(--color-text-3)",
      border: "1px solid var(--color-hairline)",
    },
  },
  error: {
    label: "status_error",
    style: {
      background: "var(--color-warm-tint)",
      color: "var(--color-warm-bright)",
      border: "1px solid var(--color-warm-ring)",
      boxShadow: "0 0 14px -6px var(--color-warm-glow)",
    },
  },
};

function StatusBadge({ status, consoleUrl }: { status: string; consoleUrl?: string | null }) {
  const { t } = useTranslation("dashboard");
  const { label, style } = STATUS_BADGE_MAP[status] ?? STATUS_BADGE_MAP.unconfigured;

  // 无论是否已配置，只要有控制台地址就渲染为跳转供应商控制台的外链（新标签页打开）。
  // 未配置时是申请 API Key 的引导入口；已配置/异常时也可随时回到供应商控制台核对。
  if (consoleUrl) {
    return (
      <a
        href={consoleUrl}
        target="_blank"
        rel="noopener noreferrer"
        title={t("provider_console_link")}
        className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-[0.14em] transition-colors hover:text-accent-2 hover:border-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        style={{ ...style, cursor: "pointer" }}
      >
        {t(label)}
        <ExternalLink className="h-2.5 w-2.5" aria-hidden />
      </a>
    );
  }

  return (
    <span
      className="rounded-full px-2.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-[0.14em]"
      style={style}
    >
      {t(label)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Field editor
// ---------------------------------------------------------------------------

interface FieldEditorProps {
  field: ProviderField;
  draft: Record<string, string>;
  setDraft: React.Dispatch<React.SetStateAction<Record<string, string>>>;
}

function FieldEditor({ field, draft, setDraft }: FieldEditorProps) {
  const { t } = useTranslation("dashboard");
  const [showSecret, setShowSecret] = useState(false);
  const [confirmingClear, setConfirmingClear] = useState(false);

  const currentValue = draft[field.key] ?? field.value ?? "";

  const handleChange = (value: string) => {
    setDraft((prev) => ({ ...prev, [field.key]: value }));
  };

  const handleClear = () => {
    if (!confirmingClear) {
      setConfirmingClear(true);
      return;
    }
    setDraft((prev) => ({ ...prev, [field.key]: "" }));
    setConfirmingClear(false);
  };

  const fieldId = `field-${field.key}`;

  if (field.type === "secret") {
    const displayValue = field.key in draft ? draft[field.key] : "";

    return (
      <div>
        <FieldLabel htmlFor={fieldId} required={field.required}>
          {field.label}
        </FieldLabel>
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <input
              id={fieldId}
              name={field.key}
              autoComplete="off"
              type={showSecret ? "text" : "password"}
              value={displayValue}
              onChange={(e) => handleChange(e.target.value)}
              placeholder={
                field.is_set
                  ? field.value_masked ?? "••••••••••"
                  : field.placeholder ?? t("enter_key_placeholder")
              }
              className={`${INPUT_CLS} pr-9`}
            />
            <button
              type="button"
              onClick={() => setShowSecret((v) => !v)}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded text-text-4 transition-colors hover:text-text-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              aria-label={showSecret ? t("common:hide") : t("common:show")}
            >
              {showSecret ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          </div>
          {field.is_set && !confirmingClear && (
            <button
              type="button"
              onClick={handleClear}
              title={t("clear_key")}
              className={GHOST_BTN_CLS}
            >
              <X className="h-3 w-3" />
              {t("clear_label")}
            </button>
          )}
          {confirmingClear && (
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={handleClear}
                className="inline-flex items-center gap-1 rounded-[8px] px-3 py-1.5 font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                style={{
                  background: "var(--color-warm-tint)",
                  color: "var(--color-warm-bright)",
                  border: "1px solid var(--color-warm-ring)",
                }}
              >
                {t("confirm_clear")}
              </button>
              <button
                type="button"
                onClick={() => setConfirmingClear(false)}
                className={GHOST_BTN_CLS}
              >
                {t("common:cancel")}
              </button>
            </div>
          )}
        </div>
        {field.is_set && !(field.key in draft) && (
          <p className="mt-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-text-4">
            {t("key_set_hint")}
          </p>
        )}
      </div>
    );
  }

  if (field.type === "number") {
    return (
      <div>
        <FieldLabel htmlFor={fieldId} required={field.required}>
          {field.label}
        </FieldLabel>
        <input
          id={fieldId}
          name={field.key}
          autoComplete="off"
          type="number"
          value={currentValue}
          onChange={(e) => handleChange(e.target.value)}
          placeholder={field.placeholder ?? ""}
          className={`${INPUT_CLS} max-w-[140px]`}
        />
      </div>
    );
  }

  return (
    <div>
      <FieldLabel htmlFor={fieldId} required={field.required}>
        {field.label}
      </FieldLabel>
      <input
        id={fieldId}
        name={field.key}
        autoComplete="off"
        type={field.type === "url" ? "url" : "text"}
        value={currentValue}
        onChange={(e) => handleChange(e.target.value)}
        placeholder={field.placeholder ?? ""}
        className={INPUT_CLS}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Capability pill
// ---------------------------------------------------------------------------

// 能力徽标展示顺序：图片→视频→文本→音频，未列出的类型排到末尾。
// media_types 由后端按注册顺序返回，前端统一排序避免 audio 等新类型插到队首。
const CAPABILITY_PILL_ORDER = ["image", "video", "text", "audio", "unknown"];
const EDITABLE_MEDIA_TYPES: ModelMediaType[] = ["image", "video", "text", "audio", "unknown"];

function capabilityPillRank(kind: string): number {
  const idx = CAPABILITY_PILL_ORDER.indexOf(kind);
  return idx === -1 ? CAPABILITY_PILL_ORDER.length : idx;
}

function mediaTypeLabel(kind: string, t: (key: string) => string): string {
  return kind === "video"
    ? t("media_type_video")
    : kind === "image"
      ? t("media_type_image")
      : kind === "text"
        ? t("media_type_text")
        : kind === "audio"
          ? t("media_type_audio")
          : kind === "unknown"
            ? t("media_type_unknown")
            : kind;
}

function CapabilityPill({ kind }: { kind: string }) {
  const { t } = useTranslation("dashboard");
  return (
    <span className="rounded-full border border-hairline-soft bg-bg-grad-a/55 px-2.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-text-3">
      {mediaTypeLabel(kind, t)}
    </span>
  );
}

// 模型列表顶部的媒体类型筛选按钮（「全部」+ 该供应商存在的类型）
function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        "rounded-full border px-2.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-[0.14em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent " +
        (active
          ? "border-accent/40 bg-accent-dim text-accent-2"
          : "border-hairline-soft bg-bg-grad-a/55 text-text-3 hover:border-hairline hover:text-text")
      }
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

interface Props {
  providerId: string;
  onSaved?: () => void;
}

export function ProviderDetail({ providerId, onSaved }: Props) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [detail, setDetail] = useState<ProviderConfigDetail | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [togglingEnabled, setTogglingEnabled] = useState(false);
  // 模型列表的媒体类型筛选；null = 全部
  const [modelTypeFilter, setModelTypeFilter] = useState<string | null>(null);
  // 最近一次连接测试从供应商 API 发现的模型及其媒体类型。
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([]);
  const [discoveredModelTypes, setDiscoveredModelTypes] = useState<Record<string, ModelMediaType>>({});

  const hasDraft = Object.keys(draft).length > 0;
  useWarnUnsaved(hasDraft);

  // 模型列表可选筛的媒体类型（该供应商实际存在，按 图片→视频→文本→音频 排序）
  const availableTypes = useMemo(() => {
    if (!detail?.models && discoveredModels.length === 0) return [];
    const registeredTypes = detail?.models ? Object.values(detail.models).map((m) => m.media_type) : [];
    const discoveredTypes = discoveredModels.map((modelId) => discoveredModelTypes[modelId] ?? "unknown");
    return [...new Set([...registeredTypes, ...discoveredTypes])].sort(
      (a, b) => capabilityPillRank(a) - capabilityPillRank(b),
    );
  }, [detail, discoveredModels, discoveredModelTypes]);

  const registeredModels = useMemo(() => detail?.models ?? {}, [detail?.models]);
  const discoveredOnlyModels = useMemo(
    () => discoveredModels.filter((modelId) => !(modelId in registeredModels)),
    [discoveredModels, registeredModels],
  );

  const handleCredentialChanged = useCallback(async () => {
    const updated = await API.getProviderConfig(providerId);
    setDetail(updated);
    onSaved?.();
  }, [providerId, onSaved]);

  const handleCredentialTested = useCallback(
    (result: ProviderTestResult) => {
      // 失败时保留上一次成功发现的结果，避免一次临时网络错误清空模型列表。
      if (result.success) {
        const registered = detail?.models ?? {};
        const discoveredTypes: Record<string, ModelMediaType> = {};
        for (const [modelId, mediaType] of Object.entries(result.model_types ?? {})) {
          if (EDITABLE_MEDIA_TYPES.includes(mediaType as ModelMediaType)) {
            discoveredTypes[modelId] = mediaType as ModelMediaType;
          }
        }
        for (const [modelId, mediaType] of Object.entries(detail?.model_type_overrides ?? {})) {
          if (!(modelId in registered) && result.available_models.includes(modelId)) {
            discoveredTypes[modelId] = mediaType;
          }
        }
        setDiscoveredModels(result.available_models);
        setDiscoveredModelTypes(discoveredTypes);
      }
    },
    [detail],
  );

  const handleDiscoveredTypeChange = useCallback(
    async (modelId: string, mediaType: ModelMediaType) => {
      try {
        const response = await API.patchProviderModelTypes(providerId, { [modelId]: mediaType });
        setDiscoveredModelTypes((previous) => ({ ...previous, [modelId]: mediaType }));
        setDetail((previous) =>
          previous
            ? { ...previous, model_type_overrides: response.model_type_overrides as Record<string, ModelMediaType> }
            : previous,
        );
      } catch (err) {
        useAppStore.getState().pushToast(errMsg(err), "error");
      }
    },
    [providerId],
  );

  // 用户编辑草稿时同步清掉上一次保存失败的错误，避免旧文案滞留误导
  const handleDraftEdit = useCallback<React.Dispatch<React.SetStateAction<Record<string, string>>>>((action) => {
    setSaveError(null);
    setDraft(action);
  }, []);

  useEffect(() => {
    let disposed = false;
    // providerId 变化时重置草稿/详情/错误/类型筛选后再异步拉取，属于动作驱动重置
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft({});
    setDetail(null);
    setLoadError(null);
    setSaveError(null);
    setModelTypeFilter(null);
    setDiscoveredModels([]);
    setDiscoveredModelTypes({});
    voidCall(
      API.getProviderConfig(providerId)
        .then((res) => {
          if (!disposed) {
            setDetail(res);
            setDiscoveredModels(res.discovered_models ?? Object.keys(res.model_type_overrides ?? {}));
            setDiscoveredModelTypes(res.model_type_overrides ?? {});
          }
        })
        .catch((err: unknown) => {
          if (!disposed) setLoadError(errMsg(err));
        }),
    );
    return () => {
      disposed = true;
    };
  }, [providerId, reloadKey]);

  const handleSave = useCallback(async () => {
    if (Object.keys(draft).length === 0) return;
    setSaving(true);
    setSaveError(null);
    try {
      const patch: Record<string, string | null> = {};
      for (const [key, value] of Object.entries(draft)) {
        patch[key] = value || null;
      }
      await API.patchProviderConfig(providerId, patch);
      const updated = await API.getProviderConfig(providerId);
      setDetail(updated);
      setDraft({});
      onSaved?.();
    } catch (err) {
      // 后端校验失败（如 Max Workers 非法值）返回已本地化的 detail，直接展示
      setSaveError(errMsg(err));
    } finally {
      setSaving(false);
    }
  }, [draft, providerId, onSaved]);

  const handleToggleEnabled = useCallback(async () => {
    if (!detail || togglingEnabled) return;
    setTogglingEnabled(true);
    try {
      await API.setProviderEnabled(providerId, !detail.enabled);
      const updated = await API.getProviderConfig(providerId);
      setDetail(updated);
      onSaved?.();
    } catch (err) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    } finally {
      setTogglingEnabled(false);
    }
  }, [detail, providerId, onSaved, togglingEnabled]);

  if (loadError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-2.5 px-1 py-10">
        <span className="inline-flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-warm">
          {t("common:load_failed")}
        </span>
        <p className="text-[12.5px] text-text-2">{loadError}</p>
        <button
          type="button"
          onClick={() => setReloadKey((k) => k + 1)}
          className="rounded-[7px] border border-hairline-soft bg-bg-grad-a/55 px-3 py-1.5 text-[12px] text-text-2 transition-colors hover:border-hairline hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {t("common:retry")}
        </button>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="flex items-center gap-2 px-1 py-12 text-text-3">
        <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin text-accent-2" aria-hidden />
        <span className="font-mono text-[11px] uppercase tracking-[0.14em]">
          {t("common:loading")}
        </span>
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-6">
      {/* Header */}
      <div className="flex items-start gap-3">
        <ProviderIcon providerId={providerId} className="mt-0.5 h-7 w-7 shrink-0" />
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h3
              className="font-editorial"
              style={{
                fontSize: 22,
                fontWeight: 400,
                lineHeight: 1.1,
                letterSpacing: "-0.012em",
                color: "var(--color-text)",
              }}
            >
              {detail.display_name}
            </h3>
            <StatusBadge status={detail.status} consoleUrl={detail.console_url} />
          </div>
          {detail.description && (
            <p className="mt-1.5 text-[12.5px] leading-[1.55] text-text-3">
              {detail.description}
            </p>
          )}
        </div>
      </div>

      {/* 供应商级启用开关 */}
      <div className="flex items-start gap-2.5 rounded-[10px] border border-hairline px-3.5 py-3" style={CARD_STYLE}>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <PillSwitch
              checked={detail.enabled}
              onToggle={() => void handleToggleEnabled()}
              labelledBy="provider-enabled-label"
            />
            <span
              id="provider-enabled-label"
              className={`text-[12.5px] font-medium ${detail.enabled ? "text-text" : "text-text-3"}`}
            >
              {t(detail.enabled ? "provider_enabled" : "provider_disabled")}
            </span>
            {togglingEnabled && (
              <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin text-accent-2" aria-hidden />
            )}
          </div>
          <p className="mt-1.5 text-[11px] leading-[1.5] text-text-4">{t("provider_enabled_hint")}</p>
        </div>
      </div>

      {/* Credentials */}
      <CredentialList
        providerId={providerId}
        supportsBaseUrl={detail.supports_base_url}
        secretFields={detail.secret_fields}
        secretFieldGroups={detail.secret_field_groups}
        onChanged={voidPromise(handleCredentialChanged)}
        onTested={handleCredentialTested}
      />

      {/* Models — 注册表声明的模型清单（只读，真相源 PROVIDER_REGISTRY，不可编辑）。
          位于密钥管理下方；顶部类型标签筛选下方列表（默认全部）。 */}
      {(Object.keys(registeredModels).length > 0 || discoveredOnlyModels.length > 0) && (
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-accent-2">
              {t("model_list")}
            </span>
            {discoveredOnlyModels.some((modelId) => (discoveredModelTypes[modelId] ?? "unknown") === "unknown") && (
              <span className="text-[11px] text-text-4">{t("manual_media_type_hint")}</span>
            )}
            <div role="group" aria-label={t("model_list")} className="flex flex-wrap gap-1">
              <FilterChip active={modelTypeFilter === null} onClick={() => setModelTypeFilter(null)}>
                {t("all")}
              </FilterChip>
              {availableTypes.map((mt) => (
                <FilterChip
                  key={mt}
                  active={modelTypeFilter === mt}
                  onClick={() => setModelTypeFilter(mt)}
                >
                  {mediaTypeLabel(mt, t)}
                </FilterChip>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            {Object.entries(registeredModels)
              .filter(([, m]) => modelTypeFilter === null || m.media_type === modelTypeFilter)
              .map(([modelId, m]) => (
                <div
                  key={modelId}
                  className="flex flex-wrap items-center gap-2 rounded-[8px] border border-hairline px-3 py-2 text-[12.5px] text-text"
                  style={CARD_STYLE}
                >
                  <span className="min-w-0 flex-1 truncate font-mono text-[11.5px]">{modelId}</span>
                  {m.supported_durations.length > 0 && (
                    <span className="font-mono text-[10.5px] text-text-4">
                      {t("supported_durations_summary", {
                        value: formatDurationsLabel(m.supported_durations),
                      })}
                    </span>
                  )}
                  <CapabilityPill kind={m.media_type} />
                </div>
              ))}
            {discoveredOnlyModels
              .filter(
                (modelId) =>
                  modelTypeFilter === null ||
                  (discoveredModelTypes[modelId] ?? "unknown") === modelTypeFilter,
              )
              .map((modelId) => (
              <div
                key={modelId}
                className="flex flex-wrap items-center gap-2 rounded-[8px] border border-hairline px-3 py-2 text-[12.5px] text-text"
                style={CARD_STYLE}
              >
                <span className="min-w-0 flex-1 truncate font-mono text-[11.5px]">{modelId}</span>
                <label className="sr-only" htmlFor={`media-type-${modelId}`}>
                  {t("set_media_type")} {modelId}
                </label>
                <select
                  id={`media-type-${modelId}`}
                  aria-label={`${t("set_media_type")}: ${modelId}`}
                  value={discoveredModelTypes[modelId] ?? "unknown"}
                  onChange={(event) => void handleDiscoveredTypeChange(modelId, event.target.value as ModelMediaType)}
                  className="rounded-full border border-hairline-soft bg-bg-grad-a/55 px-2.5 py-0.5 font-mono text-[10px] font-bold tracking-[0.08em] text-text-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  {EDITABLE_MEDIA_TYPES.map((mediaType) => (
                    <option key={mediaType} value={mediaType}>
                      {mediaTypeLabel(mediaType, t)}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Advanced */}
      {detail.fields.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="inline-flex items-center gap-1 rounded font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-text-3 transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <ChevronRight
              className={`h-3.5 w-3.5 transition-transform ${showAdvanced ? "rotate-90" : ""}`}
              aria-hidden
            />
            {t("advanced_config")}
          </button>
          {showAdvanced && (
            <div className="mt-3 space-y-4">
              {detail.fields.map((field) => (
                <FieldEditor key={field.key} field={field} draft={draft} setDraft={handleDraftEdit} />
              ))}
              {hasDraft && (
                <div className="pt-1">
                  {saveError && (
                    <p
                      aria-live="polite"
                      className="mb-2 rounded-[6px] px-2.5 py-1.5 text-[11.5px]"
                      style={{
                        background: "var(--color-warm-tint)",
                        color: "var(--color-warm-bright)",
                        border: "1px solid var(--color-warm-ring)",
                      }}
                    >
                      {saveError}
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={() => void handleSave()}
                    disabled={saving}
                    className={ACCENT_BTN_CLS}
                    style={ACCENT_BUTTON_STYLE}
                  >
                    {saving ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin" aria-hidden />
                        {t("common:saving")}
                      </>
                    ) : (
                      t("save_provider")
                    )}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
