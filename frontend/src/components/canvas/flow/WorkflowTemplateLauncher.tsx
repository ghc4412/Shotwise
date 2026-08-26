import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, Loader2, Play, RefreshCw, Sparkles, Workflow } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import type { WorkflowTemplateCatalogItem } from "@/types";
import { errMsg } from "@/utils/async";

type TemplateFilter = "all" | "manga" | "short_drama";

type WizardForm = {
  contentMode: "manga" | "short_drama";
  source: string;
  episode: number;
  aspectRatio: "16:9" | "9:16" | "1:1";
  style: string;
  videoModel: string;
  voiceModel: string;
  budget: number;
};

interface WorkflowTemplateLauncherProps {
  projectName: string;
  onDerived?: () => void | Promise<void>;
  onOpenCanvas?: () => void;
}
const FILTERS: TemplateFilter[] = ["all", "manga", "short_drama"];
const DEFAULT_WIZARD: WizardForm = {
  contentMode: "manga",
  source: "",
  episode: 1,
  aspectRatio: "16:9",
  style: "",
  videoModel: "",
  voiceModel: "",
  budget: 10,
};

function templateMatchesFilter(template: WorkflowTemplateCatalogItem, filter: TemplateFilter): boolean {
  if (filter === "all") return true;
  const type = template.template_type?.toLowerCase();
  return filter === "manga" ? type === "manga" : type === "short_drama";
}

function formatCount(value: number | undefined): string {
  return new Intl.NumberFormat().format(value ?? 0);
}

import type { TFunction } from "i18next";

function isTemplateNotPublishedError(value: unknown): boolean {
  if (value == null) return false;
  const serialized = typeof value === "string" ? value : JSON.stringify(value);
  const message = [
    String(errMsg(value)),
    serialized ?? "",
    value instanceof Error ? value.message : "",
  ].join(" ");
  return message.toLowerCase().replace(/[^a-z0-9]/g, "").includes("workflowtemplatenotpublished");
}

const TEMPLATE_NOT_PUBLISHED_FALLBACK = "这个创作 Skill 尚未发布，暂时无法使用。";

function templateNotPublishedMessage(translate: TFunction): string {
  const message = translate("flow_template_not_published", {
    defaultValue: TEMPLATE_NOT_PUBLISHED_FALLBACK,
  });
  return !message || message.includes("flow_template_not_published") || message.includes("workflow_template_not_published")
    ? TEMPLATE_NOT_PUBLISHED_FALLBACK
    : message;
}

export function WorkflowTemplateLauncher({ projectName, onDerived, onOpenCanvas }: WorkflowTemplateLauncherProps) {
  const { t } = useTranslation("dashboard");
  const translateRef = useRef(t);
  useEffect(() => {
    translateRef.current = t;
  }, [t]);
  const [templates, setTemplates] = useState<WorkflowTemplateCatalogItem[]>([]);
  const [filter, setFilter] = useState<TemplateFilter>("all");
  const [selectedTemplate, setSelectedTemplate] = useState<WorkflowTemplateCatalogItem | null>(null);
  const [wizard, setWizard] = useState<WizardForm>(DEFAULT_WIZARD);
  const [preparedRevisionId, setPreparedRevisionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [derivingId, setDerivingId] = useState<string | null>(null);
  const [derivedId, setDerivedId] = useState<string | null>(null);
  const [ratingTemplateId, setRatingTemplateId] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);
  const [launchedRunId, setLaunchedRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const userErrorMessage = useCallback(
    (requestError: unknown) => {
      const message = errMsg(requestError);
      return isTemplateNotPublishedError(requestError) || isTemplateNotPublishedError(message)
        ? templateNotPublishedMessage(translateRef.current)
        : message;
    },
    [],
  );

  const loadTemplates = useCallback(async () => {
    setRefreshing(true);
    try {
      const response = await API.listWorkflowTemplates();
      setTemplates(response.items.filter((template) => !template.status || template.status === "published"));
      setError(null);
    } catch (requestError) {
      setError(userErrorMessage(requestError));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [userErrorMessage]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load the remote catalog when the panel mounts
    void loadTemplates();
  }, [loadTemplates]);

  const visibleTemplates = useMemo(
    () => templates.filter((template) => templateMatchesFilter(template, filter)),
    [filter, templates],
  );

  const selectTemplate = useCallback((template: WorkflowTemplateCatalogItem) => {
    setSelectedTemplate(template);
    setPreparedRevisionId(null);
    setLaunchedRunId(null);
    setWizard((current) => ({
      ...current,
      contentMode: template.template_type === "short_drama" ? "short_drama" : "manga",
    }));
  }, []);

  const deriveTemplate = useCallback(
    async (template: WorkflowTemplateCatalogItem) => {
      selectTemplate(template);
      setDerivingId(template.id);
      setDerivedId(null);
      setLaunchedRunId(null);
      try {
        const derived = await API.deriveWorkflowTemplate(template.id, {
          workspace_id: "default",
          project_id: projectName,
          name: template.name ? template.name + " — " + projectName : projectName,
        });
        setPreparedRevisionId(derived.revision_id);
        setDerivedId(template.id);
        setError(null);
        await onDerived?.();
        onOpenCanvas?.();
      } catch (requestError) {
        setError(userErrorMessage(requestError));
      } finally {
        setDerivingId(null);
      }
    },
    [onDerived, onOpenCanvas, projectName, selectTemplate, userErrorMessage],
  );

  const launchProduction = useCallback(async () => {
    if (!selectedTemplate) return;
    setLaunching(true);
    setLaunchedRunId(null);
    try {
      const revisionId = selectedTemplate.published_revision_id;
      if (!revisionId) {
        setError(t("flow_template_not_ready"));
        return;
      }
      const planned = await API.planWorkflowRun(revisionId, projectName, {
        episode_id: String(wizard.episode),
        budget_limit: wizard.budget,
        input_snapshot: {
          content_mode: wizard.contentMode,
          source: wizard.source,
          episode: wizard.episode,
          aspect_ratio: wizard.aspectRatio,
          style: wizard.style,
          video_model: wizard.videoModel,
          voice_model: wizard.voiceModel,
          budget_limit: wizard.budget,
        },
      });
      const started = await API.transitionWorkflowRun(planned.id, "start", planned.version);
      setLaunchedRunId(started.id);
      setError(null);
      await onDerived?.();
    } catch (requestError) {
      setError(userErrorMessage(requestError));
    } finally {
      setLaunching(false);
    }
  }, [onDerived, projectName, selectedTemplate, t, userErrorMessage, wizard]);

  const estimatedCost = selectedTemplate?.stats?.average_cost ?? 0;
  const estimatedDuration = selectedTemplate?.stats?.average_duration_seconds ?? 0;

  const rateTemplate = async (templateId: string, value: number) => {
    setRatingTemplateId(templateId);
    try {
      await API.rateWorkflowTemplate(templateId, value);
      await loadTemplates();
    } finally {
      setRatingTemplateId(null);
    }
  };
  const displayError = isTemplateNotPublishedError(error)
    ? templateNotPublishedMessage(t)
   : error;

  return (
    <section className="flex flex-col border-b border-hairline bg-bg-raised px-4 py-3" aria-labelledby="creation-skill-launcher-title">
      <div className="order-1 flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          <div className="mt-0.5 rounded-md border border-accent-2/30 bg-accent-2/10 p-1.5 text-accent-2">
            <Sparkles size={15} aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 id="creation-skill-launcher-title" className="text-sm font-semibold text-text-1">
              {t("creation_skills_title")}
            </h2>
            <p className="mt-0.5 text-xs text-text-3">{t("creation_skills_subtitle")}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => void loadTemplates()}
            disabled={refreshing}
            className="inline-flex h-8 items-center gap-1.5 rounded border border-hairline px-2.5 text-xs text-text-2 transition hover:border-accent-2 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label={t("flow_templates_refresh")}
          >
            <RefreshCw size={13} className={refreshing ? "animate-spin" : undefined} aria-hidden="true" />
            {t("flow_templates_refresh")}
          </button>
          {onOpenCanvas ? (
            <button
              type="button"
              role="tab"
              aria-selected={false}
              aria-label={t("flow_mode_advanced")}
              data-testid="workflow-page-canvas-mode"
              onClick={onOpenCanvas}
              className="inline-flex h-8 items-center gap-1.5 rounded border border-hairline px-3 text-[11px] font-semibold text-text-2 transition-colors hover:border-accent hover:bg-bg-raised focus-ring"
            >
              <Workflow aria-hidden className="h-3.5 w-3.5" />
              {t("flow_mode_advanced")}
            </button>
          ) : null}
        </div>
      </div>

      <div className="order-2 mt-3 flex flex-wrap gap-1.5" role="group" aria-label={t("creation_skills_filter_label")}>
        {FILTERS.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={filter === option}
            onClick={() => setFilter(option)}
            className={filter === option ? "rounded-full border border-accent-2 bg-accent-2/10 px-2.5 py-1 text-[11px] text-accent-2" : "rounded-full border border-hairline px-2.5 py-1 text-[11px] text-text-3 hover:text-text-1"}
          >
            {t(option === "manga" ? "flow_templates_manga" : option === "short_drama" ? "flow_templates_short_drama" : "flow_templates_all")}
          </button>
        ))}
      </div>

      {selectedTemplate ? (
        <div className="order-4 mt-3 rounded-lg border border-accent-2/30 bg-bg p-3" data-testid="workflow-production-wizard">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 className="text-xs font-semibold text-text-1">{t("creation_skill_prepare_title")}</h3>
              <p className="mt-1 text-[10px] text-text-3">
                {t("creation_skill_prepare_subtitle", { skill: selectedTemplate.name || t(selectedTemplate.name_key) })}
              </p>
            </div>
            <span className="rounded-full border border-accent-2/30 px-2 py-0.5 text-[10px] text-accent-2">
              {preparedRevisionId ? t("creation_skill_ready") : t("creation_skill_select")}
            </span>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-[10px] text-text-3">
              {t("flow_wizard_content_mode")}
              <select
                value={wizard.contentMode}
                onChange={(event) => setWizard((current) => ({ ...current, contentMode: event.target.value as WizardForm["contentMode"] }))}
                className="mt-1 w-full rounded border border-hairline bg-bg-raised px-2 py-1.5 text-xs text-text-1"
              >
                <option value="manga">{t("flow_templates_manga")}</option>
                <option value="short_drama">{t("flow_templates_short_drama")}</option>
              </select>
            </label>
            <label className="text-[10px] text-text-3">
              {t("flow_wizard_source")}
              <input value={wizard.source} onChange={(event) => setWizard((current) => ({ ...current, source: event.target.value }))} placeholder={t("flow_wizard_source_placeholder")} className="mt-1 w-full rounded border border-hairline bg-bg-raised px-2 py-1.5 text-xs text-text-1" />
            </label>
            <label className="text-[10px] text-text-3">
              {t("flow_wizard_episode")}
              <input type="number" min={1} value={wizard.episode} onChange={(event) => setWizard((current) => ({ ...current, episode: Math.max(1, Number(event.target.value) || 1) }))} className="mt-1 w-full rounded border border-hairline bg-bg-raised px-2 py-1.5 text-xs text-text-1" />
            </label>
            <label className="text-[10px] text-text-3">
              {t("flow_wizard_aspect_ratio")}
              <select value={wizard.aspectRatio} onChange={(event) => setWizard((current) => ({ ...current, aspectRatio: event.target.value as WizardForm["aspectRatio"] }))} className="mt-1 w-full rounded border border-hairline bg-bg-raised px-2 py-1.5 text-xs text-text-1">
                <option value="16:9">16:9</option>
                <option value="9:16">9:16</option>
                <option value="1:1">1:1</option>
              </select>
            </label>
            <label className="text-[10px] text-text-3">
              {t("flow_wizard_style")}
              <input value={wizard.style} onChange={(event) => setWizard((current) => ({ ...current, style: event.target.value }))} placeholder={t("flow_wizard_style_placeholder")} className="mt-1 w-full rounded border border-hairline bg-bg-raised px-2 py-1.5 text-xs text-text-1" />
            </label>
            <label className="text-[10px] text-text-3">
              {t("flow_wizard_video_model")}
              <input value={wizard.videoModel} onChange={(event) => setWizard((current) => ({ ...current, videoModel: event.target.value }))} placeholder={t("flow_wizard_model_placeholder")} className="mt-1 w-full rounded border border-hairline bg-bg-raised px-2 py-1.5 text-xs text-text-1" />
            </label>
            <label className="text-[10px] text-text-3">
              {t("flow_wizard_voice_model")}
              <input value={wizard.voiceModel} onChange={(event) => setWizard((current) => ({ ...current, voiceModel: event.target.value }))} placeholder={t("flow_wizard_model_placeholder")} className="mt-1 w-full rounded border border-hairline bg-bg-raised px-2 py-1.5 text-xs text-text-1" />
            </label>
            <label className="text-[10px] text-text-3">
              {t("flow_wizard_budget")}
              <input type="number" min={0} step={0.01} value={wizard.budget} onChange={(event) => setWizard((current) => ({ ...current, budget: Math.max(0, Number(event.target.value) || 0) }))} className="mt-1 w-full rounded border border-hairline bg-bg-raised px-2 py-1.5 text-xs text-text-1" />
            </label>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-text-3">
            <span>{t("flow_wizard_estimate", { cost: estimatedCost.toFixed(2), duration: Math.round(estimatedDuration / 60) })}</span>
            <span>{t("flow_wizard_budget_remaining", { budget: wizard.budget.toFixed(2) })}</span>
          </div>
          {launchedRunId ? <p className="mt-2 text-xs text-good">{t("flow_wizard_launched", { run: launchedRunId })}</p> : null}
          <button type="button" onClick={() => void launchProduction()} disabled={launching} className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-accent-2 px-3 py-1.5 text-xs font-medium text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60">
            {launching ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Play size={13} aria-hidden="true" />}
            {launching ? t("flow_wizard_launching") : t("flow_wizard_launch")}
          </button>
        </div>
      ) : null}

      {displayError ? <p className="order-5 mt-2 text-xs text-danger">{displayError}</p> : null}
      {loading ? (
        <div className="order-3 mt-4 flex items-center gap-2 text-xs text-text-3">
          <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          {t("creation_skills_loading")}
        </div>
      ) : visibleTemplates.length === 0 ? (
        <div className="order-3 mt-4 flex items-center gap-2 rounded border border-dashed border-hairline px-3 py-3 text-xs text-text-3">
          <Workflow size={14} aria-hidden="true" />
          {t("creation_skills_empty")}
        </div>
      ) : (
        <div className="order-3 mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {visibleTemplates.map((template) => {
            const stats = template.stats;
            const successRate = stats?.run_count ? Math.round((stats.successful_run_count / stats.run_count) * 100) : null;
            const deriving = derivingId === template.id;
            const derived = derivedId === template.id;
            return (
              <article key={template.id} className="flex min-h-0 flex-col rounded-lg border border-hairline bg-bg p-3">
                <div className="flex items-start gap-2">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-2/10 text-accent-2">
                    <Workflow size={16} aria-hidden="true" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate text-xs font-semibold text-text-1">{template.name || t(template.name_key)}</h3>
                    <p className="mt-0.5 text-[10px] uppercase tracking-wide text-text-4">{template.template_type || template.scope}</p>
                  </div>
                </div>
                <p className="mt-2 line-clamp-3 min-h-8 text-xs leading-4 text-text-3">
                  {template.description || (template.description_key ? t(template.description_key) : t("creation_skill_no_description"))}
                </p>
                <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-text-4">
                  <span>{t("creation_skills_usage_count", { count: formatCount(stats?.derivations) })}</span>
                  {successRate !== null ? <span>{t("creation_skills_success_rate", { rate: successRate })}</span> : null}
                  {stats?.rating != null ? <span>{t("creation_skills_rating", { rating: stats.rating.toFixed(1) })}</span> : null}
                </div>
                <button
                  type="button"
                  onClick={() => void deriveTemplate(template)}
                  disabled={derivingId !== null || derived}
                  className="mt-3 inline-flex items-center justify-center gap-1.5 rounded-md bg-accent-2 px-2.5 py-1.5 text-xs font-medium text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {deriving ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : derived ? <CheckCircle2 size={13} aria-hidden="true" /> : null}
                  {deriving ? t("creation_skill_using") : derived ? t("creation_skill_used") : t("creation_skill_use")}
                </button>
                  <div className="mt-3 flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">{t("flow_templates_rate")}</span>
                    {[1, 2, 3, 4, 5].map((value) => (
                      <button
                        key={value}
                        type="button"
                        data-testid={`workflow-template-rate-${template.id}-${value}`}
                        aria-label={t("flow_templates_rate_value", { value })}
                        className="text-sm text-amber-500 transition-opacity hover:opacity-70 disabled:opacity-50"
                        disabled={ratingTemplateId === template.id}
onClick={() => { void rateTemplate(template.id, value); }}
                      >
                        ★
                      </button>
                    ))}
                  </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
