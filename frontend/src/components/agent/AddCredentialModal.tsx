import {
  ChevronDown,
  Download,
  ExternalLink,
  Loader2,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { API } from "@/api";
import {
  ACCENT_BTN_CLS,
  ACCENT_BUTTON_STYLE,
  DROPDOWN_PANEL_STYLE,
  GHOST_BTN_CLS,
  INPUT_CLS,
} from "@/components/ui/darkroom-tokens";
import { ModelCombobox } from "@/components/ui/ModelCombobox";
import { Popover } from "@/components/ui/Popover";
import { useCredentialForm } from "@/hooks/useCredentialForm";
import { useEscapeClose } from "@/hooks/useEscapeClose";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { useAppStore } from "@/stores/app-store";
import type {
  AgentSdkType,
  CreateAgentCredentialRequest,
  PresetProvider,
  TestConnectionResponse,
} from "@/types/agent-credential";
import type { CustomProviderInfo } from "@/types/custom-provider";
import { errMsg } from "@/utils/async";

import { PresetIcon } from "./PresetIcon";
import { TestResultPanel } from "./TestResultPanel";

interface Props {
  open: boolean;
  /** "create" (default) renders the new-credential form; "edit" locks the preset chips
   * and lets the user leave api_key empty to preserve the existing one. */
  mode?: "create" | "edit";
  /** Agent SDK 类型：claude（Anthropic 协议）/ openai（OpenAI 协议）。决定 discover
   * 端点、表单字段（openai 无 haiku/sonnet/opus/subagent 路由）与文案。 */
  sdkType: AgentSdkType;
  presets: PresetProvider[];
  customSentinelId: string;
  initial?: Partial<CreateAgentCredentialRequest>;
  onSubmit: (req: CreateAgentCredentialRequest) => Promise<void>;
  onClose: () => void;
}

export function AddCredentialModal({
  open,
  mode = "create",
  sdkType,
  presets,
  customSentinelId,
  initial,
  onSubmit,
  onClose,
}: Props) {
  const { t } = useTranslation("dashboard");
  const panelRef = useRef<HTMLDivElement>(null);
  useFocusTrap(panelRef, open);
  const form = useCredentialForm(initial, customSentinelId, presets);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(
    mode === "edit" &&
      Boolean(
        initial?.haiku_model || initial?.sonnet_model || initial?.opus_model || initial?.subagent_model,
      ),
  );
  // 浠庤嚜瀹氫箟渚涘簲鍟嗗鍏ワ細鍒楀嚭宸查厤缃?api_key 鐨?providers锛岄€変腑鍚庡～鍏?baseUrl + apiKey 鑽夌
  const [providers, setProviders] = useState<CustomProviderInfo[]>([]);
  const [importPickerOpen, setImportPickerOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const importTriggerRef = useRef<HTMLButtonElement>(null);

  // 鑽夌鎬佽繛鎺ユ祴璇曪細淇濆瓨鍓嶅厛楠?base_url + api_key 鏄惁鑳界湡瀹炶窇閫?
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestConnectionResponse | null>(null);
  const [testedBaseUrl, setTestedBaseUrl] = useState<string | null>(null);

  // 寮傛绔炴€侀殧绂伙細modal 閲嶅紑锛堟垨鐖剁粍浠跺垏鍒板彟涓€鏉″嚟璇侊級鍚庯紝鏃?session 閲?
  // discover/test/import 鐨?await 浠嶅彲鑳借繑鍥炲苟鍐?state銆傛瘡娆?reset effect 閲?
  // bump 涓€娆★紝async 璺緞鍦?await 鍚庢瘮瀵?session id锛屼笉涓€鑷村垯涓㈠純缁撴灉銆?
  const sessionRef = useRef(0);

  useEffect(() => {
    if (!open || mode !== "create") return;
    let cancelled = false;
    // 鎷夊彇鍓嶅厛娓呮棫鍒楄〃锛氬け璐ユ椂涓嶄細娈嬬暀涓婁竴杞?providers锛堝悓涓€ React 缁勪欢瀹炰緥
    // 璺?modal 浼氳瘽淇濈暀 state锛夛紝閬垮厤鐢ㄦ埛鐐瑰埌宸插垹闄?澶辨晥鐨?provider 瑙﹀彂 404銆?
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProviders([]);
    void (async () => {
      try {
        const res = await API.listCustomProviders();
        if (!cancelled) {
          setProviders(res.providers.filter((p) => p.api_key_masked));
        }
      } catch {
        // 闈欓粯锛氬鍏ユ槸鍙€夊揩鎹峰叆鍙ｏ紝澶辫触涓嶆墦鏂富娴佺▼
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, mode]);

  // 鐖剁粍浠跺鐢?modal 鏃跺彧鍒囨崲 open/initial锛屾湰鍦颁竴娆℃€ц瘖鏂姸鎬佷笉浼氳嚜鍔ㄦ竻銆?
  // 閲嶅紑锛堟垨鍒囨崲鍒板彟涓€鏉″嚟璇侊級鏃舵妸妯″瀷鍒楄〃銆侀敊璇€佹祴璇曠粨鏋溿€乸opover銆乮nflight
  // loading 鍏ㄩ儴褰掗浂锛屾寜鏂?initial 閲嶇畻 advancedOpen锛宐ump sessionRef 璁╂棫
  // session 鐨?await 杩斿洖鏃朵涪寮冪粨鏋溿€?
  useEffect(() => {
    sessionRef.current += 1;
    if (!open) return;
    // 閲嶅紑 modal 鏃剁殑鎵归噺閲嶇疆锛屾槸鍔ㄤ綔椹卞姩鐨勭姸鎬佸綊闆躲€?
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setModelOptions([]);
    setDiscoverError(null);
    setSubmitError(null);
    setTestResult(null);
    setTestedBaseUrl(null);
    setImportPickerOpen(false);
    setDiscovering(false);
    setTesting(false);
    setImporting(false);
    setAdvancedOpen(
      mode === "edit" &&
        Boolean(
          initial?.haiku_model || initial?.sonnet_model || initial?.opus_model || initial?.subagent_model,
        ),
    );
  }, [open, initial, mode]);

  const selected: PresetProvider | null = useMemo(() => {
    if (form.presetId === customSentinelId) return null;
    return presets.find((p) => p.id === form.presetId) ?? null;
  }, [form.presetId, presets, customSentinelId]);

  useEscapeClose(onClose, open);

  if (!open) return null;

  // 妯″瀷涓嬫媺閫夐」锛氫紭鍏堜娇鐢ㄦā鍨嬪彂鐜扮粨鏋滐紱鏈彂鐜帮紙鎴栦緵搴斿晢涓嶆敮鎸佸彂鐜帮紝濡傜伀灞辨柟鑸燂級
  // 鏃跺洖閫€鍒伴璁剧殑 suggested_models锛堝畼鏂规敮鎸佺殑妯″瀷鍚嶏級锛岀敤鎴蜂粛鍙墜鍔ㄨ緭鍏ャ€?
  const selectableModels =
    modelOptions.length > 0 ? modelOptions : (selected?.suggested_models ?? []);

  // 鑽夌浠绘剰鍙奖鍝嶈繛閫氭€х殑瀛楁锛坧reset / base_url / api_key / model锛夊彉鍖栧悗锛?
  // 鏃?testResult 宸茬粡涓嶅搴斿綋鍓嶈崏绋夸簡锛屽繀椤诲け鏁堬紝閬垮厤鐢ㄦ埛鎶婃湭閲嶆柊楠岃瘉鐨勯厤缃?
  // 褰撴垚宸查€氳繃楠岃瘉銆?
  const invalidateDraftTest = () => {
    setTestResult(null);
    setTestedBaseUrl(null);
  };

  // modelOptions 鏄寜 (endpoint, credential) 鍏冪粍鍙戠幇鍑烘潵鐨勶紱base_url 鎴?api_key
  // 鍙樹簡锛屾棫鍒楄〃閲岀殑 id 鍦ㄦ柊 endpoint 涓嶄竴瀹氭敮鎸侊紝璁╁畠澶辨晥閬垮厤鐢ㄦ埛淇濆瓨鏃犳晥閰嶇疆銆?
  const invalidateDiscoveredModels = () => {
    setModelOptions([]);
    setDiscoverError(null);
  };

  const handlePresetClick = (id: string) => {
    form.setPreset(id);
    invalidateDiscoveredModels();
    invalidateDraftTest();
  };

  const handleDiscover = async () => {
    const session = sessionRef.current;
    setDiscovering(true);
    setDiscoverError(null);
    try {
      // 浼樺厛浣跨敤琛ㄥ崟閲岀殑 base_url锛氱敤鎴锋敼浜?URL 浣嗗彂鐜颁粛璧伴璁鹃粯璁ょ鐐逛細閫夊埌
      // 褰撳墠 endpoint 涓嶆敮鎸佺殑妯″瀷銆傛棤 base_url 鏃跺洖閫€鍒伴璁剧殑 discovery/messages URL銆?
      const discoverBase =
        form.baseUrl.trim() ||
        (form.presetId === customSentinelId
          ? ""
          : selected?.discovery_url || selected?.messages_url || "");
      if (!discoverBase) {
        if (session === sessionRef.current) setDiscoverError(t("discover_no_base"));
        return;
      }
      if (!form.apiKey.trim()) {
        if (session === sessionRef.current) setDiscoverError(t("discover_api_key_required"));
        return;
      }
      const res =
        sdkType === "openai"
          ? await API.discoverOpenAIModels({
              base_url: discoverBase,
              api_key: form.apiKey,
            })
          : await API.discoverAnthropicModels({
              base_url: discoverBase,
              api_key: form.apiKey,
            });
      if (session !== sessionRef.current) return;
      setModelOptions(res.models.map((m) => m.model_id));
      const toast = useAppStore.getState().pushToast;
      if (res.models.length === 0) {
        toast(t("discover_no_models"), "warning");
      } else {
        toast(t("discover_models_success", { count: res.models.length }), "success");
      }
    } catch (err) {
      if (session === sessionRef.current) setDiscoverError(errMsg(err));
    } finally {
      if (session === sessionRef.current) setDiscovering(false);
    }
  };

  const handleImportProvider = async (provider: CustomProviderInfo) => {
    // 鍚?session 闃查噸鍏ワ細popover 鍐?provider option 娌℃湁 disabled锛岀敤鎴峰彲浠?
    // 杩炲嚮鎴栧湪 inflight 鏈熼棿鐐瑰埆鐨?provider锛泂essionRef 鍙尅璺?session race锛?
    // 鎸′笉浣忓悓涓€ session 鍐呯殑骞跺彂锛屾渶鍚庤繑鍥炵殑璇锋眰浼氳鐩栬〃鍗曘€?
    if (importing) return;
    const session = sessionRef.current;
    setImporting(true);
    // 绔嬪嵆鍏抽棴 popover锛岄伩鍏?inflight 鏈熼棿鐢ㄦ埛缁х画鐪嬪埌鍙偣閫夐」
    setImportPickerOpen(false);
    try {
      const cred = await API.getCustomProviderCredentials(provider.id);
      if (session !== sessionRef.current) return;
      // 鍒囧埌 __custom__锛氶伩鍏嶉璁剧殑 messages_url 瑕嗙洊鍒氬鍏ョ殑 base_url
      form.setPreset(customSentinelId);
      form.setApiKey(cred.api_key);
      form.setBaseUrl(cred.base_url);
      if (!form.displayName.trim()) {
        form.setDisplayName(provider.display_name);
      }
      invalidateDiscoveredModels();
      invalidateDraftTest();
      useAppStore
        .getState()
        .pushToast(t("import_provider_success", { name: provider.display_name }), "success");
    } catch (err) {
      if (session === sessionRef.current) {
        useAppStore.getState().pushToast(errMsg(err), "error");
      }
    } finally {
      if (session === sessionRef.current) setImporting(false);
    }
  };

  const handleTest = async () => {
    const session = sessionRef.current;
    setTesting(true);
    // 澶辫触鏃舵竻鏃х殑"杩炴帴鎴愬姛"闈㈡澘锛岄伩鍏嶇敤鎴风湅鍒颁笂涓€娆＄殑杩囨湡缁撴灉
    setTestResult(null);
    const submitBaseUrl = form.baseUrl.trim() || undefined;
    setTestedBaseUrl(submitBaseUrl ?? null);
    try {
      const res = await API.testAgentConnectionDraft({
        sdk_type: sdkType,
        preset_id: form.presetId,
        base_url: submitBaseUrl,
        api_key: form.apiKey,
        model: form.model || undefined,
      });
      if (session !== sessionRef.current) return;
      setTestResult(res);
    } catch (err) {
      if (session === sessionRef.current) {
        useAppStore.getState().pushToast(errMsg(err), "error");
      }
    } finally {
      if (session === sessionRef.current) setTesting(false);
    }
  };

  const handleApplyFix = (suggestedBaseUrl: string) => {
    form.setBaseUrl(suggestedBaseUrl);
    // base_url 鍙樹簡 鈫?鏃?discovery 鍜屾祴璇曠粨鏋滈兘涓嶅啀鍙俊锛岄紦鍔辩敤鎴烽噸鏂板彂鐜?娴嬭瘯
    invalidateDiscoveredModels();
    invalidateDraftTest();
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      await onSubmit(form.buildRequest());
      onClose();
    } catch (err) {
      setSubmitError(errMsg(err));
    } finally {
      setSubmitting(false);
    }
  };

  const submitDisabled =
    submitting ||
    (mode === "create" && !form.apiKey.trim()) ||
    !form.baseUrl.trim() ||
    (mode === "edit" && !form.isDirty(initial));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <div
        data-testid="modal-overlay"
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 bg-black/50"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="cred-modal-title"
        className="relative max-h-[90vh] w-full max-w-2xl overflow-y-auto overscroll-contain rounded-[12px] border border-hairline p-5"
        style={DROPDOWN_PANEL_STYLE}
      >
        {/* Header */}
        <div className="mb-4 flex items-start justify-between gap-3">
          <h3
            id="cred-modal-title"
            className="text-[15px] font-medium text-text"
          >
            {mode === "edit" ? t("edit_credential_title") : t("add_credential")}
          </h3>
          <div className="flex items-center gap-2">
            {mode === "create" && providers.length > 0 && (
              <>
                <button
                  ref={importTriggerRef}
                  type="button"
                  onClick={() => setImportPickerOpen((v) => !v)}
                  disabled={importing}
                  data-testid="import-from-provider"
                  className="inline-flex items-center gap-1.5 rounded-[6px] border border-hairline px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-text-2 transition hover:border-accent/40 hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {importing ? (
                    <Loader2 className="h-3 w-3 motion-safe:animate-spin" aria-hidden />
                  ) : (
                    <Download className="h-3 w-3" aria-hidden />
                  )}
                  {t("import_from_provider")}
                </button>
                <Popover
                  open={importPickerOpen}
                  onClose={() => setImportPickerOpen(false)}
                  anchorRef={importTriggerRef}
                  width="w-64"
                  // modal 瀹瑰櫒鏄?z-50锛涢粯璁?Popover layer 鏄?z-40 浼氳 modal 閬尅
                  layer="modal"
                  className="rounded-[8px] border border-hairline py-1 shadow-lg"
                >
                  {providers.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => void handleImportProvider(p)}
                      data-testid="import-provider-option"
                      className="block w-full truncate px-3 py-2 text-left text-[12px] text-text-2 hover:bg-bg-grad-a/50"
                    >
                      {p.display_name}
                    </button>
                  ))}
                </Popover>
              </>
            )}
            <button
              type="button"
              onClick={onClose}
              className="text-text-3 hover:text-text"
              aria-label={t("common:close")}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Preset grid 鈥?3 鍒楀浐瀹氱綉鏍?鑷畾涔夋案杩滃浐瀹氶鏍?鎺ㄨ崘椤规涔?*/}
        <div className="mb-5">
          <div className="mb-2 font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-text-2">
            {t("select_provider")}
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            <PresetChip
              dataTestid="preset-chip"
              selected={form.presetId === customSentinelId}
              onClick={() => handlePresetClick(customSentinelId)}
              label={t("custom_config")}
              disabled={mode === "edit"}
              title={mode === "edit" ? t("preset_locked_in_edit") : undefined}
            />
            {presets.map((p) => (
              <PresetChip
                key={p.id}
                dataTestid="preset-chip"
                selected={form.presetId === p.id}
                onClick={() => handlePresetClick(p.id)}
                label={p.display_name}
                iconKey={p.icon_key}
                disabled={mode === "edit"}
                title={mode === "edit" ? t("preset_locked_in_edit") : undefined}
              />
            ))}
          </div>
        </div>

        {/* Form */}
        <div className="space-y-4">
          <Field label={t("display_name")} htmlFor="cred-name">
            <input
              id="cred-name"
              value={form.displayName}
              onChange={(e) => form.setDisplayName(e.target.value)}
              className={INPUT_CLS}
            />
          </Field>

          <Field label={t("api_base_url")} htmlFor="cred-url">
            <input
              id="cred-url"
              type="url"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              value={form.baseUrl}
              onChange={(e) => {
                form.setBaseUrl(e.target.value);
                invalidateDiscoveredModels();
                invalidateDraftTest();
              }}
              placeholder="https://api.example.com/anthropic"
              className={INPUT_CLS}
            />
          </Field>

          <Field
            label={sdkType === "openai" ? t("openai_api_key") : t("anthropic_api_key")}
            htmlFor="cred-key"
            trailing={
              selected?.api_key_url ? (
                <a
                  href={selected.api_key_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[11px] text-accent hover:underline"
                >
                  {t("get_api_key")}
                  <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              ) : null
            }
          >
            <input
              id="cred-key"
              type="password"
              value={form.apiKey}
              onChange={(e) => {
                form.setApiKey(e.target.value);
                invalidateDiscoveredModels();
                invalidateDraftTest();
              }}
              autoComplete="off"
              spellCheck={false}
              placeholder={mode === "edit" ? t("api_key_unchanged_hint") : undefined}
              className={INPUT_CLS}
            />
          </Field>

          <Field
            label={t("default_model")}
            htmlFor="cred-model"
            trailing={
              <button
                type="button"
                onClick={() => void handleDiscover()}
                disabled={discovering}
                className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.14em] text-text-3 transition-colors hover:text-accent-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {discovering ? (
                  <Loader2 className="h-3 w-3 motion-safe:animate-spin" aria-hidden />
                ) : (
                  <Search className="h-3 w-3" aria-hidden />
                )}
                {discovering ? t("discovering_models") : t("discover_models")}
              </button>
            }
          >
            <ModelCombobox
              id="cred-model"
              value={form.model}
              onChange={(v) => {
                form.setModel(v);
                invalidateDraftTest();
              }}
              options={selectableModels}
              placeholder={selected?.default_model || ""}
              clearable
            />
            {discoverError && (
              <div className="mt-1 text-[11px] text-warm-bright">{discoverError}</div>
            )}
          </Field>

          {/* Advanced model routing - 折叠区（仅 Claude：haiku/sonnet/opus/subagent 路由） */}
          {sdkType === "claude" && (
          <details
            open={advancedOpen}
            onToggle={(e) => setAdvancedOpen(e.currentTarget.open)}
            className="rounded-[8px] border border-hairline-soft bg-bg-grad-a/35 p-3"
          >
            <summary className="flex cursor-pointer list-none items-center justify-between">
              <span className="inline-flex items-center gap-2 font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-text-2">
                <SlidersHorizontal className="h-3.5 w-3.5 text-accent-2" aria-hidden />
                {t("advanced_model_routing")}
              </span>
              <span className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-hairline-soft bg-bg-grad-a/55 text-text-3">
                <ChevronDown
                  className={`h-3 w-3 transition-transform duration-200 ${
                    advancedOpen ? "rotate-180 text-accent-2" : ""
                  }`}
                  aria-hidden
                />
              </span>
            </summary>
            <p className="mt-2 text-[11px] leading-[1.55] text-text-3">
              {t("model_routing_hint")}
            </p>
            <div className="mt-3 grid gap-3">
              <RoutingField
                id="cred-haiku"
                label={t("haiku_model")}
                desc={t("haiku_desc")}
                envVar="ANTHROPIC_DEFAULT_HAIKU_MODEL"
                value={form.haikuModel}
                onChange={form.setHaikuModel}
                options={selectableModels}
              />
              <RoutingField
                id="cred-sonnet"
                label={t("sonnet_model")}
                desc={t("sonnet_desc")}
                envVar="ANTHROPIC_DEFAULT_SONNET_MODEL"
                value={form.sonnetModel}
                onChange={form.setSonnetModel}
                options={selectableModels}
              />
              <RoutingField
                id="cred-opus"
                label={t("opus_model")}
                desc={t("opus_desc")}
                envVar="ANTHROPIC_DEFAULT_OPUS_MODEL"
                value={form.opusModel}
                onChange={form.setOpusModel}
                options={selectableModels}
              />
              <RoutingField
                id="cred-subagent"
                label={t("subagent_model")}
                desc={t("subagent_desc")}
                envVar="CLAUDE_CODE_SUBAGENT_MODEL"
                value={form.subagentModel}
                onChange={form.setSubagentModel}
                options={selectableModels}
              />
            </div>
          </details>
          )}

          {selected?.notes && (
            <div className="rounded-[8px] border border-hairline-soft bg-bg-grad-a/45 px-3 py-2 text-[11.5px] text-text-3">
              {selected.notes}
            </div>
          )}

          {submitError && (
            <div className="text-[11.5px] text-warm-bright">{submitError}</div>
          )}

          {testResult && (
            <TestResultPanel
              originalBaseUrl={testedBaseUrl}
              result={testResult}
              onApplyFix={handleApplyFix}
            />
          )}
        </div>

        {/* Footer */}
        <div className="mt-5 flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => void handleTest()}
            disabled={testing || submitting || !form.apiKey.trim() || !form.baseUrl.trim()}
            className={GHOST_BTN_CLS}
            data-testid="test-connection"
          >
            {testing ? (
              <Loader2 className="mr-1 inline-block h-3 w-3 motion-safe:animate-spin" aria-hidden />
            ) : null}
            {testing ? t("cred_testing") : t("cred_test_label")}
          </button>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className={GHOST_BTN_CLS}>
              {t("common:cancel")}
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={submitDisabled}
              className={ACCENT_BTN_CLS}
              style={ACCENT_BUTTON_STYLE}
            >
              {submitting
                ? t("common:loading")
                : mode === "edit"
                  ? t("common:save")
                  : t("common:add")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PresetChip({
  selected,
  onClick,
  label,
  iconKey,
  dataTestid,
  disabled,
  title,
}: {
  selected: boolean;
  onClick: () => void;
  label: string;
  iconKey?: string;
  dataTestid?: string;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      data-testid={dataTestid}
      onClick={onClick}
      disabled={disabled}
      aria-pressed={selected}
      title={title}
      className={`group inline-flex items-center justify-start gap-1.5 truncate rounded-[8px] border px-2.5 py-1.5 text-left text-[12px] transition disabled:cursor-not-allowed disabled:opacity-60 ${
        selected
          ? "border-accent bg-accent/10 text-accent"
          : "border-hairline bg-bg-grad-a/35 text-text-2 hover:border-accent/40"
      }`}
    >
      {iconKey && <PresetIcon iconKey={iconKey} size={14} />}
      <span className="truncate">{label}</span>
    </button>
  );
}

function Field({
  label,
  htmlFor,
  children,
  trailing,
}: {
  label: string;
  htmlFor?: string;
  children: React.ReactNode;
  trailing?: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label
          htmlFor={htmlFor}
          className="text-[11.5px] font-medium text-text-2"
        >
          {label}
        </label>
        {trailing}
      </div>
      {children}
    </div>
  );
}

function RoutingField({
  id,
  label,
  desc,
  envVar,
  value,
  onChange,
  options,
}: {
  id: string;
  label: string;
  desc: string;
  envVar: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <div>
      <label htmlFor={id} className="block font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-text-2">
        {label}
      </label>
      <div className="text-[11px] text-text-4">{desc}</div>
      <div className="mt-1.5">
        <ModelCombobox
          id={id}
          value={value}
          onChange={onChange}
          options={options}
          placeholder={envVar}
          aria-label={label}
          clearable
        />
      </div>
    </div>
  );
}

