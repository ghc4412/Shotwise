import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleHelp, CloudUpload, Loader2, RefreshCw, ShieldAlert } from "lucide-react";
import { useLocation } from "wouter";
import { publishingApi, type PublishJob, type PublishingAccount, type PublishingPlatform } from "./publishing-api";
import { usePublishingEventsSSE } from "@/hooks/usePublishingEventsSSE";
import { usePublishingText } from "./publishing-i18n";

function platformLabel(platform: PublishingPlatform, t: ReturnType<typeof usePublishingText>): string {
  if (platform.platform === "douyin") return t("douyin");
  if (platform.platform === "hongguo") return t("hongguo");
  return platform.display_name;
}

function statusClass(status: string): string {
  if (["published", "succeeded", "retracted"].includes(status)) return "text-emerald-300";
  if (["failed", "failed_retryable", "failed_needs_user_action", "retract_failed"].includes(status)) return "text-rose-300";
  return "text-amber-200";
}

function errorText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "unknown_error";
}

function userFacingError(error: unknown, t: ReturnType<typeof usePublishingText>): string {
  const message = errorText(error).toLowerCase();
  if (message.includes("409") || message.includes("conflict") || message.includes("version")) return t("errorConflict");
  if (message.includes("422") || message.includes("validation") || message.includes("not_publishable")) return t("errorValidation");
  if (message.includes("503") || message.includes("adapter_not_connected") || message.includes("official adapter")) return t("errorUnavailable");
  if (message.includes("404") || message.includes("not_found") || message.includes("not found")) return t("errorNotFound");
  return t("failed", { message: errorText(error) });
}

function createIdempotencyKey(): string {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function") return `publish-${cryptoApi.randomUUID()}`;
  return `publish-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const PUBLISH_JOBS_PAGE_SIZE = 20;

function fieldClass(): string {
  return "mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-[var(--color-text)] outline-none transition focus:border-violet-300/60";
}

export function PublishingPage() {
  const t = usePublishingText();
  const [, setLocation] = useLocation();
  const [platforms, setPlatforms] = useState<PublishingPlatform[]>([]);
  const [accounts, setAccounts] = useState<PublishingAccount[]>([]);
  const [job, setJob] = useState<PublishJob | null>(null);
  const [jobs, setJobs] = useState<PublishJob[]>([]);
  const [jobsTotal, setJobsTotal] = useState(0);
  const [jobsOffset, setJobsOffset] = useState(0);
  const [jobsLoading, setJobsLoading] = useState(false);
  const jobsRef = useRef<PublishJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [artifactId, setArtifactId] = useState(() => new URLSearchParams(globalThis.location.search).get("artifact_id") ?? "");
  const [reviewSnapshotId, setReviewSnapshotId] = useState(() => new URLSearchParams(globalThis.location.search).get("review_snapshot_id") ?? "");
  const [jobIdInput, setJobIdInput] = useState("");
  const [platform, setPlatform] = useState("douyin");
  const [accountId, setAccountId] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState(createIdempotencyKey);

  const selectedPlatform = useMemo(
    () => platforms.find((item) => item.platform === platform) ?? null,
    [platforms, platform],
  );
  const selectedAccounts = useMemo(
    () => accounts.filter((item) => item.platform === platform),
    [accounts, platform],
  );

  const loadJobHistory = useCallback(async (offset: number) => {
    setJobsLoading(true);
    try {
      const result = await publishingApi.listJobs(PUBLISH_JOBS_PAGE_SIZE, offset);
      jobsRef.current = result.items;
      setJobs(result.items);
      setJobsTotal(result.total);
      setJobsOffset(result.offset);
    } catch (reason) {
      setError(userFacingError(reason, t));
    } finally {
      setJobsLoading(false);
    }
  }, [t]);

  const updateJobInHistory = useCallback((updatedJob: PublishJob, countAsNew = false) => {
    const existing = jobsRef.current.some((item) => item.id === updatedJob.id);
    const nextJobs = existing
      ? jobsRef.current.map((item) => item.id === updatedJob.id ? updatedJob : item)
      : [updatedJob, ...jobsRef.current].slice(0, PUBLISH_JOBS_PAGE_SIZE);
    jobsRef.current = nextJobs;
    setJobs(nextJobs);
    if (countAsNew && !existing) setJobsTotal((current) => current + 1);
  }, []);

  const loadJob = useCallback(async (id: string) => {
    if (!id.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await publishingApi.getJob(id.trim());
      setJob(result);
      setPlatform(result.platform);
      setJobIdInput(result.id);
      updateJobInHistory(result);
    } catch (reason) {
      setError(userFacingError(reason, t));
    } finally {
      setBusy(false);
    }
  }, [t, updateJobInHistory]);

  useEffect(() => {
    const params = new URLSearchParams(globalThis.location.search);
    const initialJobId = params.get("job_id");
    void Promise.all([
      publishingApi.listPlatforms(),
      publishingApi.listAccounts(),
      publishingApi.listJobs(PUBLISH_JOBS_PAGE_SIZE, 0),
    ])
      .then(([platformResult, accountResult, jobsResult]) => {
        setPlatforms(platformResult);
        setAccounts(accountResult);
        jobsRef.current = jobsResult.items;
        setJobs(jobsResult.items);
        setJobsTotal(jobsResult.total);
        setJobsOffset(jobsResult.offset);
        if (platformResult[0]) setPlatform((current) => platformResult.some((item) => item.platform === current) ? current : platformResult[0].platform);
      })
      .catch((reason) => setError(userFacingError(reason, t)))
      .finally(() => setLoading(false));
    if (initialJobId) {
      void publishingApi.getJob(initialJobId)
        .then((result) => {
          setJob(result);
          setPlatform(result.platform);
          setJobIdInput(result.id);
          updateJobInHistory(result);
        })
        .catch((reason) => setError(userFacingError(reason, t)));
    }
  }, [t, updateJobInHistory]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedPlatform?.supports_publish) {
      setError(t("notReady"));
      return;
    }
    if (!artifactId.trim() || !reviewSnapshotId.trim()) {
      setError(t("missingFields"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await publishingApi.createJob(artifactId.trim(), {
        review_snapshot_id: reviewSnapshotId.trim(),
        platform,
        idempotency_key: idempotencyKey.trim() || createIdempotencyKey(),
        ...(accountId ? { account_id: accountId } : {}),
      });
      setJob(result);
      setJobIdInput(result.id);
      updateJobInHistory(result, true);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function runJobAction(action: "poll" | "retry" | "retract" | "cancel") {
    if (!job) return;
    setBusy(true);
    setError(null);
    try {
      const result = action === "poll"
        ? await publishingApi.pollJob(job.id)
        : action === "retry"
          ? await publishingApi.retryJob(job.id)
          : action === "cancel"
            ? await publishingApi.cancelJob(job.id)
            : await publishingApi.retractJob(job.id);
      setJob(result);
      updateJobInHistory(result);
    } catch (reason) {
      setError(userFacingError(reason, t));
    } finally {
      setBusy(false);
    }
  }

  const refreshSelectedJob = useCallback(async () => {
    if (!job || !["queued", "submitted", "processing", "publish_pending"].includes(job.status)) return;
    try {
      const result = await publishingApi.pollJob(job.id);
      setJob(result);
      updateJobInHistory(result);
    } catch (reason) {
      setError(userFacingError(reason, t));
    }
  }, [job, t, updateJobInHistory]);

  useEffect(() => {
    if (!job || !["queued", "submitted", "processing", "publish_pending"].includes(job.status)) return;
    const timer = window.setTimeout(() => void refreshSelectedJob(), 5000);
    return () => window.clearTimeout(timer);
  }, [job, refreshSelectedJob]);

  const canPoll = Boolean(job && ["queued", "submitted", "processing", "publish_pending"].includes(job.status));
  const canRetry = job?.status === "failed_retryable";
  const canCancel = Boolean(
    job && ["queued", "publishing", "submitted", "processing", "publish_pending", "failed_retryable"].includes(job.status),
  );
  const canRetract = Boolean(job?.status === "published" && selectedPlatform?.supports_retract);

  const handlePublishJobEvent = useCallback((jobId: string) => {
    void publishingApi.getJob(jobId)
      .then((result) => {
        setJob((current) => current?.id === result.id ? result : current);
        setPlatform((current) => job?.id === result.id ? result.platform : current);
        updateJobInHistory(result);
      })
      .catch((reason) => {
        if (job?.id === jobId) setError(userFacingError(reason, t));
      });
  }, [job?.id, t, updateJobInHistory]);

  usePublishingEventsSSE(job?.project_name, handlePublishJobEvent);

  if (loading) {
    return <div data-testid="publishing-loading" className="flex h-full items-center justify-center text-sm text-[var(--color-text-3)]"><Loader2 className="mr-2 h-4 w-4 animate-spin" />{t("loading")}</div>;
  }

  return (
    <main className="h-full overflow-y-auto px-6 py-8 text-[var(--color-text)]" data-testid="publishing-page">
      <div className="mx-auto max-w-6xl space-y-6">
        <button type="button" className="text-xs text-[var(--color-text-3)] hover:text-[var(--color-text)]" onClick={() => setLocation("/app/projects")}>
          ← {t("title")}
        </button>
        <header>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-violet-300">{t("kicker")}</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">{t("title")}</h1>
          <p className="mt-2 max-w-2xl text-sm text-[var(--color-text-3)]">{t("subtitle")}</p>
        </header>

        {error && <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-100"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}

        <section className="grid gap-4 md:grid-cols-2" aria-labelledby="publishing-platform-title">
          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 md:col-span-2">
            <div className="flex items-center justify-between gap-3"><h2 id="publishing-platform-title" className="font-medium">{t("platformTitle")}</h2><CircleHelp className="h-4 w-4 text-[var(--color-text-3)]" /></div>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {platforms.map((item) => (
                <article key={item.platform} className={`rounded-xl border p-4 ${item.platform === platform ? "border-violet-300/50 bg-violet-300/[0.06]" : "border-white/10 bg-black/10"}`}>
                  <div className="flex items-start justify-between gap-3"><div><h3 className="font-medium">{platformLabel(item, t)}</h3><p className="mt-1 text-xs text-[var(--color-text-3)]">{item.platform}</p></div>{item.adapter_connected ? <CheckCircle2 className="h-5 w-5 text-emerald-300" /> : <ShieldAlert className="h-5 w-5 text-amber-200" />}</div>
                  <p className={`mt-3 text-xs ${item.adapter_connected ? "text-emerald-200" : "text-amber-100"}`}>{item.adapter_connected ? t("adapterConnected") : t("adapterUnavailable")}</p>
                  <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-[var(--color-text-3)]"><dt>{t("publish")}</dt><dd>{item.supports_publish ? t("true") : t("false")}</dd><dt>{t("schedule")}</dt><dd>{item.supports_schedule ? t("true") : t("false")}</dd><dt>{t("polling")}</dt><dd>{item.supports_status_polling ? t("true") : t("false")}</dd><dt>{t("retract")}</dt><dd>{item.supports_retract ? t("true") : t("false")}</dd></dl>
                  {!item.adapter_connected && <p className="mt-3 text-xs leading-5 text-[var(--color-text-3)]">{t("notReady")}</p>}
                </article>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5">
            <h2 className="font-medium">{t("accountTitle")}</h2>
            {accounts.length === 0 ? <p className="mt-4 text-sm text-[var(--color-text-3)]">{t("noAccounts")}</p> : <div className="mt-4 space-y-3">{accounts.map((item) => <div key={item.id} className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-black/10 px-3 py-3"><div><p className="text-sm font-medium">{item.account_name}</p><p className="mt-1 text-xs text-[var(--color-text-3)]">{item.platform} · {item.platform_account_id}</p></div><span className="text-xs text-[var(--color-text-3)]">{item.status === "active" ? t("accountActive") : t("accountRevoked")}</span></div>)}</div>}
            <p className="mt-4 text-xs leading-5 text-[var(--color-text-3)]">{t("oauthPending")}</p>
          </div>

          <form className="rounded-2xl border border-white/10 bg-white/[0.03] p-5" onSubmit={(event) => { void handleCreate(event); }}>
            <h2 className="font-medium">{t("formTitle")}</h2>
            <label className="mt-4 block text-xs text-[var(--color-text-3)]">{t("artifactId")}<input className={fieldClass()} value={artifactId} onChange={(event) => setArtifactId(event.target.value)} placeholder="final-artifact-id" /></label>
            <label className="mt-3 block text-xs text-[var(--color-text-3)]">{t("reviewSnapshotId")}<input className={fieldClass()} value={reviewSnapshotId} onChange={(event) => setReviewSnapshotId(event.target.value)} placeholder="review-snapshot-id" /></label>
            <label className="mt-3 block text-xs text-[var(--color-text-3)]">{t("platform")}<select className={fieldClass()} value={platform} onChange={(event) => setPlatform(event.target.value)}>{platforms.map((item) => <option key={item.platform} value={item.platform}>{platformLabel(item, t)}</option>)}</select></label>
            <label className="mt-3 block text-xs text-[var(--color-text-3)]">{t("account")}<select className={fieldClass()} value={accountId} onChange={(event) => setAccountId(event.target.value)}><option value="">{t("noAccount")}</option>{selectedAccounts.map((item) => <option key={item.id} value={item.id}>{item.account_name}</option>)}</select></label>
            <label className="mt-3 block text-xs text-[var(--color-text-3)]">{t("idempotencyKey")}<input className={fieldClass()} value={idempotencyKey} onChange={(event) => setIdempotencyKey(event.target.value)} /></label>
            <button type="submit" disabled={busy || !selectedPlatform?.supports_publish} className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-violet-300 px-3 py-2 text-sm font-medium text-slate-950 transition hover:bg-violet-200 disabled:cursor-not-allowed disabled:opacity-45"><CloudUpload className="h-4 w-4" />{t("createJob")}</button>
            {!selectedPlatform?.supports_publish && <p className="mt-3 text-xs leading-5 text-amber-100">{t("notReady")}</p>}
          </form>
        </section>

        <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5" aria-labelledby="publishing-history-title">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 id="publishing-history-title" className="font-medium">{t("historyTitle")}</h2>
              <p className="mt-1 text-xs text-[var(--color-text-3)]">{t("historyCount", { count: jobsTotal })}</p>
            </div>
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => void loadJobHistory(jobsOffset)} disabled={jobsLoading} className="inline-flex items-center gap-1 rounded-lg border border-white/10 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-45"><RefreshCw className="h-3.5 w-3.5" />{t("refresh")}</button>
              <button type="button" onClick={() => void loadJobHistory(Math.max(0, jobsOffset - PUBLISH_JOBS_PAGE_SIZE))} disabled={jobsLoading || jobsOffset === 0} className="rounded-lg border border-white/10 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-45">{t("previous")}</button>
              <button type="button" onClick={() => void loadJobHistory(jobsOffset + PUBLISH_JOBS_PAGE_SIZE)} disabled={jobsLoading || jobsOffset + jobs.length >= jobsTotal} className="rounded-lg border border-white/10 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-45">{t("next")}</button>
            </div>
          </div>
          {jobsLoading ? <p className="mt-4 text-sm text-[var(--color-text-3)]">{t("historyLoading")}</p> : jobs.length === 0 ? <p className="mt-4 text-sm text-[var(--color-text-3)]">{t("historyEmpty")}</p> : <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[520px] text-left text-xs"><thead className="text-[var(--color-text-3)]"><tr><th className="pb-2 pr-4 font-medium">{t("jobId")}</th><th className="pb-2 pr-4 font-medium">{t("platform")}</th><th className="pb-2 pr-4 font-medium">{t("status")}</th><th className="pb-2 font-medium">{t("createdAt")}</th></tr></thead><tbody>{jobs.map((item) => <tr key={item.id}><td colSpan={4} className="p-0"><button type="button" onClick={() => void loadJob(item.id)} disabled={busy} className={`grid w-full grid-cols-4 items-center rounded-lg px-2 py-3 text-left hover:bg-white/10 disabled:opacity-45 ${job?.id === item.id ? "bg-violet-300/[0.08]" : ""}`}><span className="truncate pr-4 font-medium">{item.id}</span><span className="pr-4">{item.platform}</span><span className={`pr-4 font-medium ${statusClass(item.status)}`}>{item.status}</span><span className="text-[var(--color-text-3)]">{item.created_at ?? "—"}</span></button></td></tr>)}</tbody></table></div>}
        </section>

        <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5" aria-labelledby="publishing-job-title">
          <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="publishing-job-title" className="font-medium">{t("jobTitle")}</h2><div className="flex gap-2"><input aria-label={t("jobId")} className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm outline-none" value={jobIdInput} onChange={(event) => setJobIdInput(event.target.value)} placeholder="job-id" /><button type="button" onClick={() => void loadJob(jobIdInput)} disabled={busy || !jobIdInput.trim()} className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm hover:bg-white/10 disabled:opacity-45"><RefreshCw className="h-4 w-4" />{t("loadJob")}</button></div></div>
          {!job ? <p className="mt-4 text-sm text-[var(--color-text-3)]">{t("noJob")}</p> : <div className="mt-4 rounded-xl border border-white/10 bg-black/10 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-medium">{job.platform} · {job.id}</p><p className={`mt-2 text-sm font-medium ${statusClass(job.status)}`}>{t("status")}: {job.status}</p></div><div className="flex flex-wrap gap-2"><button type="button" onClick={() => void runJobAction("poll")} disabled={busy || !canPoll} className="rounded-lg border border-white/10 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-45">{t("poll")}</button><button type="button" onClick={() => void runJobAction("retry")} disabled={busy || !canRetry} className="rounded-lg border border-white/10 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-45">{t("retry")}</button><button type="button" onClick={() => void runJobAction("cancel")} disabled={busy || !canCancel} className="rounded-lg border border-white/10 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-45">{t("cancel")}</button><button type="button" onClick={() => void runJobAction("retract")} disabled={busy || !canRetract} className="rounded-lg border border-white/10 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-45">{t("retract")}</button></div></div><dl className="mt-4 grid gap-2 text-xs text-[var(--color-text-3)] md:grid-cols-2"><div><dt>{t("attempts", { attempt: job.attempt, max: job.max_attempts })}</dt></div><div>{job.external_status ? t("externalStatus", { status: job.external_status }) : t("noExternalId")}</div><div>{job.error_code ?? ""}{job.error_message ? ` · ${job.error_message}` : ""}</div></dl></div>}
        </section>
      </div>
    </main>
  );
}

export default PublishingPage;







