import { useCallback, useEffect, useState } from "react";
import { Clock3, Eye, Loader2, Lock, Save, Unlock } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API, type EpisodeDurationPlanInput, type EpisodeDurationPreview, type EpisodeDurationState, type EpisodeDurationStrategy } from "@/api";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { PrimaryButton } from "@/components/ui/PrimaryButton";
import { SecondaryButton } from "@/components/ui/SecondaryButton";

interface EpisodeDurationPlanPanelProps {
  projectName: string;
  episode: number;
  onApplied?: () => void | Promise<void>;
}

const STRATEGIES: EpisodeDurationStrategy[] = ["equal", "proportional"];

export function EpisodeDurationPlanPanel({ projectName, episode, onApplied }: EpisodeDurationPlanPanelProps) {
  const { t } = useTranslation("dashboard");
  const [state, setState] = useState<EpisodeDurationState | null>(null);
  const [targetSeconds, setTargetSeconds] = useState(60);
  const [strategy, setStrategy] = useState<EpisodeDurationStrategy>("equal");
  const [preview, setPreview] = useState<EpisodeDurationPreview | null>(null);
  const [busy, setBusy] = useState<"load" | "save" | "preview" | "apply" | "lock" | null>("load");
  const [error, setError] = useState<string | null>(null);

  const adopt = useCallback((next: EpisodeDurationState) => {
    setState(next);
    if (next.plan) {
      setTargetSeconds(next.plan.target_seconds);
      setStrategy(next.plan.strategy);
    }
  }, []);

  const reload = useCallback(async (signal?: AbortSignal) => {
    const next = await API.getEpisodeDurationPlan(projectName, episode, { signal });
    adopt(next);
    return next;
  }, [adopt, episode, projectName]);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const next = await API.getEpisodeDurationPlan(projectName, episode, { signal: controller.signal });
        if (!controller.signal.aborted) adopt(next);
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      } finally {
        if (!controller.signal.aborted) setBusy(null);
      }
    })();
    return () => controller.abort();
  }, [adopt, episode, projectName]);

  const input = (): EpisodeDurationPlanInput => ({ target_seconds: targetSeconds, strategy });

  const run = async (kind: Exclude<typeof busy, "load" | null>, action: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    try {
      await action();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      await reload().catch(() => undefined);
    } finally {
      setBusy(null);
    }
  };

  const save = () => run("save", async () => {
    if (!state) return;
    await API.saveEpisodeDurationPlan(projectName, episode, state.revision, input());
    await reload();
  });

  const buildPreview = () => run("preview", async () => {
    setPreview(await API.previewEpisodeDurationPlan(projectName, episode, input()));
  });

  const apply = () => run("apply", async () => {
    if (!preview) return;
    await API.applyEpisodeDurationPlan(projectName, episode, preview.revision, preview.plan);
    setPreview(null);
    await reload();
    await onApplied?.();
  });

  const toggleLock = (resourceId: string, locked: boolean) => run("lock", async () => {
    if (!state) return;
    await API.setEpisodeDurationLock(projectName, episode, resourceId, state.revision, locked);
    await reload();
    setPreview(null);
  });

  if (busy === "load" && !state) {
    return <div className="flex min-h-24 items-center justify-center"><Loader2 className="h-4 w-4 animate-spin" /></div>;
  }

  return (
    <section className="border-y px-5 py-4" style={{ borderColor: "var(--color-hairline)", background: "var(--color-shell-side-a)" }}>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-36 flex-1">
          <label className="mb-1 block text-[11px] font-medium" htmlFor={`episode-duration-${episode}`}>{t("episode_duration_target")}</label>
          <div className="relative">
            <Clock3 className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5" />
            <input id={`episode-duration-${episode}`} type="number" min={1} value={targetSeconds} onChange={(event) => setTargetSeconds(Math.max(1, Number(event.target.value) || 1))} className="h-9 w-full rounded-md border bg-transparent pl-8 pr-10 text-[13px] focus-ring" style={{ borderColor: "var(--color-hairline)" }} />
            <span className="absolute right-2.5 top-2 text-[11px]" style={{ color: "var(--color-text-4)" }}>{t("episode_duration_seconds")}</span>
          </div>
        </div>
        <div role="group" aria-label={t("episode_duration_strategy")} className="inline-flex h-9 rounded-md border p-0.5" style={{ borderColor: "var(--color-hairline)" }}>
          {STRATEGIES.map((value) => <button key={value} type="button" aria-pressed={strategy === value} onClick={() => setStrategy(value)} className="rounded px-2.5 text-[11px] focus-ring" style={{ background: strategy === value ? "var(--color-accent-dim)" : "transparent", color: strategy === value ? "var(--color-accent-2)" : "var(--color-text-3)" }}>{t(`episode_duration_strategy_${value}`)}</button>)}
        </div>
        <SecondaryButton size="sm" onClick={() => void save()} disabled={!state || busy !== null} leadingIcon={<Save className="h-3.5 w-3.5" />}>{t("episode_duration_save")}</SecondaryButton>
        <PrimaryButton size="sm" onClick={() => void buildPreview()} disabled={!state || busy !== null} leadingIcon={<Eye className="h-3.5 w-3.5" />}>{t("episode_duration_preview")}</PrimaryButton>
      </div>
      {error && <p role="alert" className="mt-2 text-[11px]" style={{ color: "var(--color-danger)" }}>{error}</p>}
      {state && state.items.length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{state.items.map((item) => <button key={item.resource_id} type="button" disabled={busy !== null || item.generated} onClick={() => void toggleLock(item.resource_id, !item.locked)} className="inline-flex h-7 items-center gap-1 rounded border px-2 text-[10.5px] focus-ring disabled:opacity-50" style={{ borderColor: "var(--color-hairline)" }} title={item.generated ? t("episode_duration_generated_locked") : item.locked ? t("episode_duration_unlock") : t("episode_duration_lock")}>{item.locked || item.generated ? <Lock className="h-3 w-3" /> : <Unlock className="h-3 w-3" />}{item.resource_id}<span style={{ color: "var(--color-text-4)" }}>{item.duration_seconds ?? "-"}s</span></button>)}</div>}
      <ConfirmDialog open={preview !== null} title={t("episode_duration_confirm_title")} description={preview ? <div><p>{t("episode_duration_confirm_description", { count: preview.changes.length })}</p><div className="mt-3 max-h-44 overflow-y-auto border-y" style={{ borderColor: "var(--color-hairline)" }}>{preview.changes.map((change) => <div key={change.resource_id} className="flex items-center justify-between py-2 text-[11px]"><span>{change.resource_id}</span><span>{change.from_seconds ?? "-"}s → {change.to_seconds}s</span></div>)}</div></div> : undefined} confirmLabel={t("episode_duration_apply")} loadingLabel={t("episode_duration_applying")} loading={busy === "apply"} onConfirm={apply} onCancel={() => setPreview(null)} />
    </section>
  );
}
