import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CheckCircle,
  Captions,
  Clapperboard,
  Clock3,
  FileWarning,
  Loader2,
  LockKeyhole,
  Pencil,
  PlayCircle,
  Volume2,
  XCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation } from "wouter";
import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
import type {
  AssemblyAudioStrategy,
  AssemblyPlan,
  AssemblyPlanIssue,
  AssemblyPackagingConfig,
  AssemblyPlanRevision,
  AssemblyRenderJob,
  AssemblyFinalReview,
  AssemblyFinalReviewFramePosition,
  AssemblySubtitleMode,
  AssemblyTimelineItem,
} from "@/types";

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function formatDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function issueSeverity(issue: AssemblyPlanIssue, fallback: "warning" | "error"): "warning" | "error" {
  return issue.severity === "error" || fallback === "error" ? "error" : "warning";
}

function normalizeRevision(plan: AssemblyPlan | null): AssemblyPlanRevision | null {
  return plan?.current_revision ?? null;
}

function readAudioStrategy(revision: AssemblyPlanRevision | null): AssemblyAudioStrategy {
  const value = revision?.audio.strategy;
  return value === "keep" || value === "mute" || value === "duck" ? value : "duck";
}

function readSubtitleMode(revision: AssemblyPlanRevision | null): AssemblySubtitleMode {
  const value = revision?.subtitle.mode;
  return value === "vtt" || value === "burn-in" || value === "srt" ? value : "srt";
}

type PackagingDraft = {
  introEnabled: boolean;
  introText: string;
  introDuration: string;
  outroEnabled: boolean;
  outroText: string;
  outroDuration: string;
  coverEnabled: boolean;
  coverSourceRef: string;
  coverDuration: string;
  coverFit: "cover" | "contain";
};

function readPackagingDraft(revision: AssemblyPlanRevision | null): PackagingDraft {
  const packaging = revision?.packaging ?? {};
  const intro = packaging.intro;
  const outro = packaging.outro;
  const cover = packaging.cover;
  return {
    introEnabled: Boolean(intro && typeof intro === "object"),
    introText: intro && typeof intro === "object" && typeof intro.text === "string" ? intro.text : "",
    introDuration: intro && typeof intro === "object" && typeof intro.duration_seconds === "number" ? String(intro.duration_seconds) : "3",
    outroEnabled: Boolean(outro && typeof outro === "object"),
    outroText: outro && typeof outro === "object" && typeof outro.text === "string" ? outro.text : "",
    outroDuration: outro && typeof outro === "object" && typeof outro.duration_seconds === "number" ? String(outro.duration_seconds) : "3",
    coverEnabled: Boolean(cover && typeof cover === "object"),
    coverSourceRef: cover && typeof cover === "object" && typeof cover.source_ref === "string" ? cover.source_ref : "",
    coverDuration: cover && typeof cover === "object" && typeof cover.duration_seconds === "number" ? String(cover.duration_seconds) : "3",
    coverFit: cover && typeof cover === "object" && cover.fit === "contain" ? "contain" : "cover",
  };
}

function buildPackaging(revision: AssemblyPlanRevision, draft: PackagingDraft): AssemblyPackagingConfig {
  const packaging: AssemblyPackagingConfig = { ...revision.packaging };
  if (draft.introEnabled) packaging.intro = { text: draft.introText, duration_seconds: Number(draft.introDuration) };
  else delete packaging.intro;
  if (draft.outroEnabled) packaging.outro = { text: draft.outroText, duration_seconds: Number(draft.outroDuration) };
  else delete packaging.outro;
  if (draft.coverEnabled) {
    packaging.cover = {
      source_ref: draft.coverSourceRef,
      duration_seconds: Number(draft.coverDuration),
      fit: draft.coverFit,
    };
  } else delete packaging.cover;
  return packaging;
}

function artifactUrl(plan: AssemblyPlan | null): string | null {
  const artifact = plan?.preview_artifact;
  return artifact?.url ?? artifact?.content_url ?? artifact?.download_url ?? null;
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error && reason.message ? reason.message : "Unknown error";
}

const FINAL_REVIEW_POSITIONS: AssemblyFinalReviewFramePosition[] = ["first", "middle", "last"];

export interface AssemblyPlanPageProps {
  projectName: string;
}

export function AssemblyPlanPage({ projectName }: AssemblyPlanPageProps) {
  const { t } = useTranslation("dashboard");
  const [, setLocation] = useLocation();
  const currentProjectData = useProjectsStore((state) => state.currentProjectData);
  const episodes = useMemo(
    () => currentProjectData?.episodes ?? [],
    [currentProjectData?.episodes],
  );
  const [selectedEpisode, setSelectedEpisode] = useState<number | null>(episodes[0]?.episode ?? null);
  const [plans, setPlans] = useState<AssemblyPlan[]>([]);
  const [plan, setPlan] = useState<AssemblyPlan | null>(null);
  const [loadingPlans, setLoadingPlans] = useState(true);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [confirmingPreview, setConfirmingPreview] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [confirmingRender, setConfirmingRender] = useState(false);
  const [renderConfirmationError, setRenderConfirmationError] = useState<string | null>(null);
  const [audioStrategy, setAudioStrategy] = useState<AssemblyAudioStrategy>("duck");
  const [subtitleMode, setSubtitleMode] = useState<AssemblySubtitleMode>("srt");
  const [packagingDraft, setPackagingDraft] = useState<PackagingDraft>(() => readPackagingDraft(null));
  const [savingConfiguration, setSavingConfiguration] = useState(false);
  const [configurationSaveError, setConfigurationSaveError] = useState<string | null>(null);
  const [exportingSubtitleFormat, setExportingSubtitleFormat] = useState<"srt" | "vtt" | null>(null);
  const [subtitleExportError, setSubtitleExportError] = useState<string | null>(null);
  const [exportingJianyingDraft, setExportingJianyingDraft] = useState(false);
  const [jianyingExportError, setJianyingExportError] = useState<string | null>(null);
  const [configurationDirty, setConfigurationDirty] = useState(false);
  const [finalJob, setFinalJob] = useState<AssemblyRenderJob | null>(null);
  const [creatingFinalRender, setCreatingFinalRender] = useState(false);
  const [retryingFinalRender, setRetryingFinalRender] = useState(false);
  const [finalRenderError, setFinalRenderError] = useState<string | null>(null);
  const [confirmingPlan, setConfirmingPlan] = useState(false);
  const [planConfirmError, setPlanConfirmError] = useState<string | null>(null);
  const [previewJob, setPreviewJob] = useState<AssemblyRenderJob | null>(null);
  const [creatingPreviewRender, setCreatingPreviewRender] = useState(false);
  const [retryingPreviewRender, setRetryingPreviewRender] = useState(false);
  const [previewRenderError, setPreviewRenderError] = useState<string | null>(null);
  const refreshedPreviewJobRef = useRef<string | null>(null);
  const [finalArtifactBlob, setFinalArtifactBlob] = useState<{ jobId: string; url: string } | null>(null);
  const [finalReview, setFinalReview] = useState<AssemblyFinalReview | null>(null);
  const [loadingFinalReview, setLoadingFinalReview] = useState(false);
  const [finalReviewError, setFinalReviewError] = useState<string | null>(null);
  const [finalReviewConfirmedAt, setFinalReviewConfirmedAt] = useState<string | null>(null);
  const [confirmingFinalReview, setConfirmingFinalReview] = useState(false);
  const [reviewFrameUrls, setReviewFrameUrls] = useState<Partial<Record<AssemblyFinalReviewFramePosition, string>>>({});
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    // The selected episode mirrors the active project episode list.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- synchronize the active episode with the project context
    setSelectedEpisode(episodes[0]?.episode ?? null);
  }, [projectName, episodes]);

  useEffect(() => {
    const controller = new AbortController();
    // Request lifecycle state must reset when the project changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset loading state before starting the request
    setLoadingPlans(true);
    setError(null);
    setPlan(null);
    setPreviewError(null);
    setRenderConfirmationError(null);
    setConfigurationDirty(false);
    void API.listAssemblyPlans(projectName, { signal: controller.signal })
      .then((response) => setPlans(response.items))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setPlans([]);
          setError(reason);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingPlans(false);
      });
    return () => controller.abort();
  }, [projectName]);

  const matchingPlan = useMemo(
    () => plans.find((item) => item.episode_number === selectedEpisode) ?? null,
    [plans, selectedEpisode],
  );

  useEffect(() => {
    if (!matchingPlan) {
      // Clear the detail view when the selected episode has no plan.
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clear derived detail state for an empty selection
      setPlan(null);
      setLoadingPlan(false);
      setPreviewError(null);
      setRenderConfirmationError(null);
      setConfigurationDirty(false);
      setFinalJob(null);
      setFinalRenderError(null);
      setFinalArtifactBlob(null);
      setFinalReview(null);
      setLoadingFinalReview(false);
      setFinalReviewError(null);
      setFinalReviewConfirmedAt(null);
      setConfirmingFinalReview(false);
      setReviewFrameUrls({});
      setPreviewJob(null);
      setPreviewRenderError(null);
      setPlanConfirmError(null);
      setConfirmingPlan(false);
      setCreatingPreviewRender(false);
      setRetryingPreviewRender(false);
      refreshedPreviewJobRef.current = null;
      return;
    }
    const controller = new AbortController();
    // Request lifecycle state must reset when the selected plan changes.
    setLoadingPlan(true);
    setError(null);
    setPreviewError(null);
    setRenderConfirmationError(null);
    setConfigurationDirty(false);
    setFinalJob(null);
    setFinalRenderError(null);
    setFinalArtifactBlob(null);
    setFinalReview(null);
    setLoadingFinalReview(false);
    setFinalReviewError(null);
    setFinalReviewConfirmedAt(null);
    setReviewFrameUrls({});
    setPreviewJob(null);
    setPreviewRenderError(null);
    setPlanConfirmError(null);
    setConfirmingPlan(false);
    setCreatingPreviewRender(false);
    setRetryingPreviewRender(false);
    refreshedPreviewJobRef.current = null;
    void API.getAssemblyPlan(matchingPlan.id, { signal: controller.signal })
      .then(setPlan)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setPlan(null);
          setError(reason);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingPlan(false);
      });
    return () => controller.abort();
  }, [matchingPlan]);

  const revision = normalizeRevision(plan);
  const items = revision?.timeline ?? [];
  const validation = revision?.validation ?? { valid: true, errors: [], warnings: [] };
  const issues = [
    ...(validation?.errors ?? []).map((issue) => ({ issue, fallback: "error" as const })),
    ...(validation?.warnings ?? []).map((issue) => ({ issue, fallback: "warning" as const })),
  ];
  const totalDuration = items.reduce((total, item) => total + item.duration_seconds, 0);
  const isStale = plan?.stale === true || plan?.status === "stale";
  const previewUrl = artifactUrl(plan);
  const previewRevisionMatches = Boolean(
    plan && revision && plan.preview_revision_number === revision.version_number,
  );
  const previewReady = Boolean(
    (plan?.status === "preview_ready" || plan?.status === "render_pending") &&
      revision &&
      previewRevisionMatches &&
      plan.preview_artifact &&
      previewUrl &&
      !isStale,
  );
  const previewConfirmed = Boolean(plan?.preview_confirmed_by && plan?.preview_confirmed_at);
  const renderConfirmed = Boolean(plan?.render_confirmed_by && plan?.render_confirmed_at);
  const finalRenderAvailable = true;
  const finalRenderRunning = finalJob?.status === "queued" || finalJob?.status === "running";
  const finalRenderCompleted = finalJob?.status === "succeeded";
  const finalRenderFailed = finalJob?.status === "failed";
  const previewRenderRunning = previewJob?.status === "queued" || previewJob?.status === "running";
  const previewRenderFailed = previewJob?.status === "failed";
  const previewRenderHasArtifact = Boolean(
    revision && previewRevisionMatches && plan?.preview_artifact && previewUrl && !isStale,
  );
  // POST /preview-renders only queues a job for a confirmed plan, so re-rendering a plan that is
  // already preview_ready returns it to the confirmed state before starting the new job.
  const previewRenderAvailable = Boolean(
    (plan?.status === "confirmed" || plan?.status === "preview_ready") &&
      revision &&
      validation.valid &&
      !isStale &&
      !configurationDirty &&
      !creatingPreviewRender &&
      !previewRenderRunning,
  );
  const finalReviewFramesReady = FINAL_REVIEW_POSITIONS.every((position) => Boolean(reviewFrameUrls[position]));
  const finalReviewRevisionMatches = Boolean(
    finalReview &&
      finalJob &&
      revision &&
      finalReview.revision_number === finalJob.revision_number &&
      finalReview.revision_number === revision.version_number,
  );
  const finalReviewBlocked = Boolean(
    !finalReview ||
      !finalReviewFramesReady ||
      !finalReviewRevisionMatches ||
      !finalReview.checks.duration.within_metadata_tolerance ||
      finalReview.checks.black_frames.detected ||
      finalReview.checks.timeline_duration?.within_tolerance === false ||
      finalReview.checks.subtitle_bounds?.valid === false ||
      finalReview.checks.audio_quality?.severity === "blocking" ||
      (finalReview.blocking_reasons?.length ?? 0) > 0,
  );
  const finalReviewConfirmed = Boolean(finalReviewConfirmedAt && !finalReviewBlocked);
  const finalRenderBlocked = Boolean(
    !finalRenderAvailable ||
      !previewReady ||
      !previewConfirmed ||
      !renderConfirmed ||
      configurationDirty ||
      !validation.valid ||
      isStale ||
      !revision ||
      creatingFinalRender ||
      finalRenderRunning,
  );

  useEffect(() => {
    if (!finalJob || finalJob.status !== "succeeded" || !finalJob.artifact || !plan || !revision) return;
    let disposed = false;
    const loadFinalReview = async () => {
      setLoadingFinalReview(true);
      setFinalReviewError(null);
      setFinalReview(null);
      setFinalReviewConfirmedAt(null);
      setConfirmingFinalReview(false);
      setReviewFrameUrls({});
      try {
        const review = await API.getAssemblyFinalReview(plan.id);
        if (disposed) return;
        if (review.revision_number !== finalJob.revision_number || review.revision_number !== revision.version_number) {
          throw new Error("最终审阅版本与当前渲染版本不一致");
        }
        const frameEntries = await Promise.all(
          FINAL_REVIEW_POSITIONS.map(async (position) => {
            if (!review.checks.frames.some((frame) => frame.position === position)) return [position, null] as const;
            const blob = await API.downloadAssemblyFinalReviewFrame(review.artifact.id, position);
            return [position, URL.createObjectURL(blob)] as const;
          }),
        );
        if (disposed) {
          frameEntries.forEach(([, url]) => { if (url) URL.revokeObjectURL(url); });
          return;
        }
        setFinalReview(review);
        setFinalReviewConfirmedAt(review.review_snapshot?.confirmed_at ?? null);
        setReviewFrameUrls(Object.fromEntries(frameEntries.filter((entry): entry is [AssemblyFinalReviewFramePosition, string] => Boolean(entry[1]))));
      } catch (reason: unknown) {
        if (!disposed) setFinalReviewError(errorMessage(reason));
      } finally {
        if (!disposed) setLoadingFinalReview(false);
      }
    };
    void loadFinalReview();
    return () => { disposed = true; };
  }, [finalJob, plan, revision]);

  useEffect(() => {
    return () => {
      Object.values(reviewFrameUrls).forEach((url) => { if (url) URL.revokeObjectURL(url); });
    };
  }, [reviewFrameUrls]);

  useEffect(() => {
    if (!finalJob || !["queued", "running"].includes(finalJob.status)) return;
    let disposed = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await API.getRenderJob(finalJob.id);
        if (disposed) return;
        setFinalJob(next);
        setFinalRenderError(null);
      } catch (reason: unknown) {
        if (!disposed) {
          setFinalRenderError(errorMessage(reason));
          timer = window.setTimeout(() => void poll(), 1500);
        }
      }
    };
    timer = window.setTimeout(() => void poll(), 1500);
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [finalJob]);

  const finalDirectArtifactUrl = finalJob?.artifact?.url ?? finalJob?.artifact?.content_url ?? finalJob?.artifact?.download_url ?? null;
  const finalArtifactUrl = finalDirectArtifactUrl ?? (finalArtifactBlob && finalArtifactBlob.jobId === finalJob?.id ? finalArtifactBlob.url : null);

  useEffect(() => {
    if (!finalJob || finalJob.status !== "succeeded" || !finalJob.artifact || finalDirectArtifactUrl) return;
    let disposed = false;
    let objectUrl: string | null = null;
    void API.downloadRenderJobArtifact(finalJob.id)
      .then((blob) => {
        if (disposed) return;
        objectUrl = URL.createObjectURL(blob);
        setFinalArtifactBlob({ jobId: finalJob.id, url: objectUrl });
      })
      .catch((reason: unknown) => {
        if (!disposed) setFinalRenderError(errorMessage(reason));
      });
    return () => {
      disposed = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [finalJob, finalDirectArtifactUrl]);

  useEffect(() => {
    if (!previewJob || !plan) return;
    if (previewJob.status !== "succeeded" && previewJob.status !== "failed") return;
    if (refreshedPreviewJobRef.current === previewJob.id) return;
    refreshedPreviewJobRef.current = previewJob.id;
    const planId = plan.id;
    const timer = window.setTimeout(() => {
      void API.getAssemblyPlan(planId)
        .then(setPlan)
        .catch(() => {
          // A transient refresh failure keeps the last known plan in place.
        });
    }, 800);
    return () => window.clearTimeout(timer);
  }, [previewJob, plan]);

  useEffect(() => {
    if (!previewJob || !["queued", "running"].includes(previewJob.status)) return;
    const jobId = previewJob.id;
    let disposed = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await API.getRenderJob(jobId);
        if (disposed) return;
        setPreviewJob(next);
        setPreviewRenderError(null);
      } catch (reason: unknown) {
        if (!disposed) {
          setPreviewRenderError(errorMessage(reason));
          timer = window.setTimeout(() => void poll(), 1500);
        }
      }
    };
    timer = window.setTimeout(() => void poll(), 1500);
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [previewJob]);

  useEffect(() => {
    // The controls mirror the saved revision until the user changes them locally.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- synchronize controls with the loaded immutable revision
    setAudioStrategy(readAudioStrategy(revision));
    setSubtitleMode(readSubtitleMode(revision));
    setPackagingDraft(readPackagingDraft(revision));
    setConfigurationSaveError(null);
  }, [revision]);

  const saveConfiguration = async () => {
    if (!plan || !revision || savingConfiguration) return;
    setSavingConfiguration(true);
    setConfigurationSaveError(null);
    try {
      const saved = await API.createAssemblyPlanRevision(plan.id, {
        source_snapshot: revision.source_snapshot,
        timeline: revision.timeline,
        audio: { ...revision.audio, strategy: audioStrategy },
        subtitle: { ...revision.subtitle, mode: subtitleMode },
        packaging: buildPackaging(revision, packagingDraft),
        output_profile: revision.output_profile,
      });
      setPlan(saved);
      setConfigurationDirty(false);
    } catch (reason: unknown) {
      setConfigurationSaveError(errorMessage(reason));
    } finally {
      setSavingConfiguration(false);
    }
  };

  const exportSubtitles = async (format: "srt" | "vtt") => {
    if (!plan || exportingSubtitleFormat) return;
    setExportingSubtitleFormat(format);
    setSubtitleExportError(null);
    try {
      const blob = await API.downloadAssemblySubtitles(plan.id, format);
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `${plan.name || "subtitles"}.${format}`;
      link.click();
      URL.revokeObjectURL(objectUrl);
    } catch (reason: unknown) {
      setSubtitleExportError(errorMessage(reason));
    } finally {
      setExportingSubtitleFormat(null);
    }
  };

  const exportJianyingDraft = async () => {
    if (!plan || !finalReviewConfirmed || exportingJianyingDraft) return;
    setExportingJianyingDraft(true);
    setJianyingExportError(null);
    try {
      const blob = await API.downloadAssemblyJianyingDraft(plan.id);
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `${plan.name || "assembly"}.jianying.zip`;
      link.click();
      URL.revokeObjectURL(objectUrl);
    } catch (reason: unknown) {
      setJianyingExportError(errorMessage(reason));
    } finally {
      setExportingJianyingDraft(false);
    }
  };

  const createFinalRender = async () => {
    if (!plan || !revision || finalRenderBlocked) return;
    setCreatingFinalRender(true);
    setFinalRenderError(null);
    try {
      const job = await API.createAssemblyFinalRender(plan.id, {
        revision_number: revision.version_number,
        max_attempts: 3,
      });
      setFinalJob(job);
      setFinalReview(null);
      setFinalReviewConfirmedAt(null);
      setFinalReviewError(null);
      setReviewFrameUrls({});
    } catch (reason: unknown) {
      setFinalRenderError(errorMessage(reason));
    } finally {
      setCreatingFinalRender(false);
    }
  };

  const confirmFinalReview = async () => {
    if (!finalReview || finalReviewBlocked || !finalJob?.artifact || confirmingFinalReview) return;
    setConfirmingFinalReview(true);
    setFinalReviewError(null);
    try {
      const snapshot = await API.confirmAssemblyFinalReview(finalJob.artifact.id, {
        revision_number: finalReview.revision_number,
      });
      setFinalReviewConfirmedAt(snapshot.confirmed_at ?? null);
      setFinalReview((current) => current ? { ...current, review_snapshot: { ...current.review_snapshot, ...snapshot } } : current);
    } catch (reason: unknown) {
      setFinalReviewError(errorMessage(reason));
    } finally {
      setConfirmingFinalReview(false);
    }
  };

  const goToPublishing = () => {
    const artifactId = finalJob?.artifact?.id;
    const reviewSnapshotId = finalReview?.review_snapshot?.id;
    if (!finalReviewConfirmed || !artifactId || !reviewSnapshotId) return;
    setLocation(`/app/publishing?artifact_id=${encodeURIComponent(artifactId)}&review_snapshot_id=${encodeURIComponent(reviewSnapshotId)}`);
  };

  const retryFinalRender = async () => {
    if (!finalJob || !finalRenderFailed || retryingFinalRender) return;
    setRetryingFinalRender(true);
    setFinalRenderError(null);
    try {
      setFinalJob(await API.retryFinalRenderJob(finalJob.id));
      setFinalReview(null);
      setFinalReviewConfirmedAt(null);
      setFinalReviewError(null);
      setReviewFrameUrls({});
    } catch (reason: unknown) {
      setFinalRenderError(errorMessage(reason));
    } finally {
      setRetryingFinalRender(false);
    }
  };

  const confirmPreview = async () => {
    if (!plan || !revision || !previewReady || confirmingPreview) return;
    setConfirmingPreview(true);
    setPreviewError(null);
    try {
      const confirmed = await API.confirmAssemblyPlanPreview(plan.id, {
        revision_number: revision.version_number,
      });
      setPlan(confirmed);
    } catch (reason: unknown) {
      setPreviewError(errorMessage(reason));
    } finally {
      setConfirmingPreview(false);
    }
  };

  const confirmRender = async () => {
    if (!plan || !revision || !previewReady || !previewConfirmed || confirmingRender || renderConfirmed) return;
    setConfirmingRender(true);
    setRenderConfirmationError(null);
    try {
      const confirmed = await API.confirmAssemblyPlanRender(plan.id, {
        revision_number: revision.version_number,
      });
      setPlan(confirmed);
    } catch (reason: unknown) {
      setRenderConfirmationError(errorMessage(reason));
    } finally {
      setConfirmingRender(false);
    }
  };

  const confirmPlan = async () => {
    if (!plan || plan.status !== "draft" || confirmingPlan) return;
    setConfirmingPlan(true);
    setPlanConfirmError(null);
    try {
      const confirmed = await API.transitionAssemblyPlan(plan.id, { status: "confirmed" });
      setPlan(confirmed);
    } catch (reason: unknown) {
      setPlanConfirmError(errorMessage(reason));
    } finally {
      setConfirmingPlan(false);
    }
  };

  const createPreviewRender = async () => {
    if (!plan || !revision || !previewRenderAvailable) return;
    setCreatingPreviewRender(true);
    setPreviewRenderError(null);
    try {
      let confirmedPlan = plan;
      if (confirmedPlan.status !== "confirmed") {
        confirmedPlan = await API.transitionAssemblyPlan(plan.id, { status: "confirmed" });
        setPlan(confirmedPlan);
      }
      const job = await API.createAssemblyPreviewRender(confirmedPlan.id, {
        revision_number: revision.version_number,
        max_attempts: 3,
      });
      refreshedPreviewJobRef.current = null;
      setPreviewJob(job);
    } catch (reason: unknown) {
      setPreviewRenderError(errorMessage(reason));
    } finally {
      setCreatingPreviewRender(false);
    }
  };

  const retryPreviewRender = async () => {
    if (!previewJob || !previewRenderFailed || retryingPreviewRender) return;
    setRetryingPreviewRender(true);
    setPreviewRenderError(null);
    try {
      refreshedPreviewJobRef.current = null;
      setPreviewJob(await API.retryRenderJob(previewJob.id));
    } catch (reason: unknown) {
      setPreviewRenderError(errorMessage(reason));
    } finally {
      setRetryingPreviewRender(false);
    }
  };

  if (loadingPlans || loadingPlan) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--color-text-3)]" data-testid="assembly-loading">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
        {t("assembly_loading")}
      </div>
    );
  }

  if (error) {
    return (
      <section className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center" data-testid="assembly-error">
        <FileWarning className="h-7 w-7 text-amber-500" aria-hidden />
        <h1 className="text-sm font-semibold text-[var(--color-text)]">{t("assembly_load_error")}</h1>
        <p className="max-w-md text-xs text-[var(--color-text-3)]">{t("assembly_backend_pending")}</p>
      </section>
    );
  }

  return (
    <main className="h-full overflow-y-auto p-4 md:p-6" data-testid="assembly-plan-page">
      <div className="mx-auto max-w-6xl space-y-4">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="mb-1 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--color-text-4)]">
              <Clapperboard className="h-3.5 w-3.5" aria-hidden />
              {t("assembly_kicker")}
            </div>
            <h1 className="text-xl font-semibold text-[var(--color-text)]">{t("assembly_title")}</h1>
            <p className="mt-1 max-w-2xl text-xs text-[var(--color-text-3)]">{t("assembly_subtitle")}</p>
          </div>
          {episodes.length > 0 ? (
            <label className="grid gap-1 text-[10px] font-semibold text-[var(--color-text-3)]">
              <span>{t("assembly_episode_label")}</span>
              <select
                value={selectedEpisode ?? ""}
                onChange={(event) => setSelectedEpisode(Number(event.target.value))}
                className="rounded-lg border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] px-3 py-2 text-xs text-[var(--color-text)] outline-none"
                aria-label={t("assembly_episode_label")}
              >
                {episodes.map((episode) => (
                  <option key={episode.episode} value={episode.episode}>
                    {episode.display_episode ?? episode.episode} · {episode.title}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </header>

        {!matchingPlan ? (
          <section className="rounded-xl border border-dashed border-[var(--color-hairline)] bg-[var(--panel-card-bg)] p-8 text-center" data-testid="assembly-empty">
            <Clapperboard className="mx-auto h-8 w-8 text-[var(--color-text-4)]" aria-hidden />
            <h2 className="mt-3 text-sm font-semibold text-[var(--color-text)]">{t("assembly_empty_title")}</h2>
            <p className="mx-auto mt-1 max-w-md text-xs text-[var(--color-text-3)]">{t("assembly_empty_description")}</p>
            <p className="mt-3 text-[10px] text-[var(--color-text-4)]">{t("assembly_backend_pending")}</p>
          </section>
        ) : plan && revision ? (
          <>
            <section className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto]" data-testid="assembly-plan-summary">
              <div className="rounded-xl border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] p-4">
                <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--color-text-4)]">{t("assembly_plan_status")}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <StatusBadge status={plan.status} t={t} />
                  {isStale ? <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-1 text-[10px] font-medium text-amber-700"><AlertTriangle className="h-3 w-3" aria-hidden />{t("assembly_plan_stale")}</span> : null}
                </div>
                <h2 className="mt-3 text-sm font-semibold text-[var(--color-text)]">{plan.name}</h2>
                {plan.status === "draft" ? (
                  <button
                    type="button"
                    onClick={() => void confirmPlan()}
                    disabled={confirmingPlan}
                    className="mt-3 inline-flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-3 py-2 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
                    data-testid="assembly-confirm-plan"
                  >
                    {confirmingPlan ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <CheckCircle className="h-3.5 w-3.5" aria-hidden />}
                    {t(confirmingPlan ? "assembly_plan_confirming" : "assembly_confirm_plan")}
                  </button>
                ) : null}
                {planConfirmError ? <p className="mt-2 text-[10px] text-red-700" role="alert">{t("assembly_plan_confirm_error", { message: planConfirmError })}</p> : null}
              </div>
              <StatCard label={t("assembly_plan_revision")} value={`v${plan.current_revision_number}`} testId="assembly-revision" />
              <StatCard label={t("assembly_total_duration")} value={formatDuration(totalDuration)} testId="assembly-duration" />
            </section>

            <section className="rounded-xl border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] p-4" data-testid="assembly-validation">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h2 className="text-sm font-semibold text-[var(--color-text)]">{t("assembly_validation_title")}</h2>
                  <p className="mt-1 text-[10px] text-[var(--color-text-3)]">{t(validation.valid ? "assembly_validation_passed" : "assembly_validation_failed")}</p>
                </div>
                <ValidationBadge valid={validation.valid} warningCount={validation.warnings.length} t={t} />
              </div>
              {issues.length > 0 ? (
                <ul className="mt-3 space-y-2">
                  {issues.map(({ issue, fallback }, index) => {
                    const severity = issueSeverity(issue, fallback);
                    return <li key={`${issue.code}-${index}`} className="flex gap-2 rounded-lg bg-[var(--color-shell-field)] px-3 py-2 text-xs text-[var(--color-text-2)]"><IssueIcon severity={severity} /><span>{issue.message}</span></li>;
                  })}
                </ul>
              ) : <p className="mt-3 text-xs text-[var(--color-text-3)]">{t("assembly_validation_no_issues")}</p>}
            </section>

            <section className="rounded-xl border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] p-4" data-testid="assembly-preview">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <PlayCircle className="h-4 w-4 text-[var(--color-accent)]" aria-hidden />
                    <h2 className="text-sm font-semibold text-[var(--color-text)]">{t("assembly_preview_title")}</h2>
                  </div>
                  <p className="mt-1 text-xs text-[var(--color-text-3)]">
                    {plan.status === "preview_pending" ? t("assembly_preview_pending_description") : previewReady ? t("assembly_preview_ready_description") : t("assembly_preview_not_ready_description")}
                  </p>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[10px] font-medium ${previewReady ? "bg-emerald-500/10 text-emerald-700" : "bg-amber-500/10 text-amber-700"}`}>
                    {previewReady ? <CheckCircle2 className="h-3 w-3" aria-hidden /> : <Loader2 className="h-3 w-3" aria-hidden />}
                    {t(previewReady ? "assembly_preview_ready" : "assembly_preview_pending")}
                  </span>
                  <button
                    type="button"
                    onClick={() => void createPreviewRender()}
                    disabled={!previewRenderAvailable}
                    className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-3 py-2 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
                    data-testid="assembly-generate-preview"
                  >
                    {creatingPreviewRender || previewRenderRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <PlayCircle className="h-3.5 w-3.5" aria-hidden />}
                    {previewRenderRunning ? t("assembly_preview_rendering") : previewRenderHasArtifact ? t("assembly_regenerate_preview") : t("assembly_generate_preview")}
                  </button>
                </div>
              </div>
              {plan.status === "draft" ? <p className="mt-3 rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-800" data-testid="assembly-confirm-plan-hint">{t("assembly_confirm_plan_hint")}</p> : null}
              {previewRenderError || previewJob?.error_message ? (
                <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-700" role="alert" data-testid="assembly-preview-render-error">
                  {t("assembly_preview_render_error", { message: previewRenderError ?? previewJob?.error_message ?? "" })}
                </p>
              ) : null}
              {previewRenderFailed ? (
                <button type="button" onClick={() => void retryPreviewRender()} disabled={retryingPreviewRender} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-[var(--color-hairline)] px-3 py-2 text-xs font-medium text-[var(--color-text)] disabled:opacity-50" data-testid="assembly-preview-retry">
                  {retryingPreviewRender ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
                  {t("assembly_preview_retry")}
                </button>
              ) : null}
              {previewUrl ? (
                <div className="mt-4 overflow-hidden rounded-lg border border-[var(--color-hairline-soft)] bg-black">
                  <video className="max-h-[420px] w-full" controls preload="metadata" src={previewUrl} poster={revision.timeline[0]?.thumbnail_url ?? undefined} data-testid="assembly-preview-player">
                    <track kind="captions" src="data:text/vtt;charset=utf-8,WEBVTT%0A%0A" srcLang="en" label={t("assembly_preview_captions_label")} />
                    {t("assembly_preview_video_fallback")}
                  </video>
                </div>
              ) : (
                <div className="mt-4 flex min-h-28 items-center justify-center rounded-lg border border-dashed border-[var(--color-hairline)] bg-[var(--color-shell-field)] text-xs text-[var(--color-text-3)]" data-testid="assembly-preview-placeholder">
                  {t("assembly_preview_artifact_missing")}
                </div>
              )}
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[10px] text-[var(--color-text-3)]">
                <span>{t("assembly_preview_revision", { revision: plan.preview_revision_number ?? "—" })}</span>
                {plan.preview_ready_at ? <span>{t("assembly_preview_generated_at", { date: formatDate(plan.preview_ready_at) ?? "—" })}</span> : null}
              </div>
              {previewError ? <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-700" role="alert">{t("assembly_preview_confirm_error", { message: previewError })}</p> : null}
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--color-hairline-soft)] p-3">
                <div>
                  <p className="text-xs font-medium text-[var(--color-text)]">{t("assembly_preview_confirmation_title")}</p>
                  <p className="mt-1 text-[10px] text-[var(--color-text-3)]">
                    {previewConfirmed ? t("assembly_preview_confirmed", { date: formatDate(plan.preview_confirmed_at) ?? "—" }) : t("assembly_preview_confirmation_required")}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void confirmPreview()}
                  disabled={!previewReady || confirmingPreview || previewConfirmed}
                  className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-3 py-2 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
                  data-testid="assembly-confirm-preview"
                >
                  {confirmingPreview ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <CheckCircle className="h-3.5 w-3.5" aria-hidden />}
                  {previewConfirmed ? t("assembly_preview_confirmed_button") : t("assembly_confirm_preview")}
                </button>
              </div>
            </section>

            <section className="rounded-xl border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] p-4" data-testid="assembly-media-config">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <Volume2 className="h-4 w-4 text-[var(--color-accent)]" aria-hidden />
                    <h2 className="text-sm font-semibold text-[var(--color-text)]">{t("assembly_media_config_title")}</h2>
                  </div>
                  <p className="mt-1 text-xs text-[var(--color-text-3)]">{t("assembly_media_config_description")}</p>
                </div>
                <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-shell-field)] px-2 py-1 text-[10px] text-[var(--color-text-3)]"><LockKeyhole className="h-3 w-3" aria-hidden />{t("assembly_config_draft_badge")}</span>
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <label className="grid gap-1 text-xs text-[var(--color-text-2)]">
                  <span className="flex items-center gap-1"><Volume2 className="h-3.5 w-3.5" aria-hidden />{t("assembly_audio_strategy_label")}</span>
                  <select
                    value={audioStrategy}
                    onChange={(event) => { setAudioStrategy(event.target.value as AssemblyAudioStrategy); setConfigurationDirty(true); }}
                    className="rounded-lg border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] px-3 py-2 text-xs text-[var(--color-text)] outline-none"
                    aria-label={t("assembly_audio_strategy_label")}
                  >
                    <option value="duck">{t("assembly_audio_strategy_duck")}</option>
                    <option value="keep">{t("assembly_audio_strategy_keep")}</option>
                    <option value="mute">{t("assembly_audio_strategy_mute")}</option>
                  </select>
                  <span className="text-[10px] text-[var(--color-text-3)]">{t("assembly_audio_strategy_hint")}</span>
                </label>
                <label className="grid gap-1 text-xs text-[var(--color-text-2)]">
                  <span className="flex items-center gap-1"><Captions className="h-3.5 w-3.5" aria-hidden />{t("assembly_subtitle_mode_label")}</span>
                  <select
                    value={subtitleMode}
                    onChange={(event) => { setSubtitleMode(event.target.value as AssemblySubtitleMode); setConfigurationDirty(true); }}
                    className="rounded-lg border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] px-3 py-2 text-xs text-[var(--color-text)] outline-none"
                    aria-label={t("assembly_subtitle_mode_label")}
                  >
                    <option value="srt">{t("assembly_subtitle_mode_srt")}</option>
                    <option value="vtt">{t("assembly_subtitle_mode_vtt")}</option>
                    <option value="burn-in">{t("assembly_subtitle_mode_burn_in")}</option>
                  </select>
                  <span className="text-[10px] text-[var(--color-text-3)]">{t("assembly_subtitle_mode_hint")}</span>
                  <div className="mt-2 flex flex-wrap items-center gap-2" data-testid="assembly-subtitle-export">
                    <button
                      type="button"
                      onClick={() => void exportSubtitles("srt")}
                      disabled={exportingSubtitleFormat !== null}
                      className="rounded-lg border border-[var(--color-hairline)] px-2.5 py-1.5 text-[10px] font-medium text-[var(--color-text-2)] disabled:cursor-not-allowed disabled:opacity-50"
                      data-testid="assembly-subtitle-export-srt"
                    >
                      {exportingSubtitleFormat === "srt" ? t("assembly_subtitle_exporting") : t("assembly_subtitle_export_srt")}
                    </button>
                    <button
                      type="button"
                      onClick={() => void exportSubtitles("vtt")}
                      disabled={exportingSubtitleFormat !== null}
                      className="rounded-lg border border-[var(--color-hairline)] px-2.5 py-1.5 text-[10px] font-medium text-[var(--color-text-2)] disabled:cursor-not-allowed disabled:opacity-50"
                      data-testid="assembly-subtitle-export-vtt"
                    >
                      {exportingSubtitleFormat === "vtt" ? t("assembly_subtitle_exporting") : t("assembly_subtitle_export_vtt")}
                    </button>
                  </div>
                  {subtitleExportError ? (
                    <p className="mt-2 text-[10px] text-red-700" data-testid="assembly-subtitle-export-error">
                      {t("assembly_subtitle_export_error", { error: subtitleExportError })}
                    </p>
                  ) : null}
                  <p
                    className={`mt-2 text-[10px] ${subtitleMode === "burn-in" ? "text-emerald-700" : "text-[var(--color-text-3)]"}`}
                    data-testid="assembly-subtitle-burn-in-status"
                  >
                    {subtitleMode === "burn-in" ? t("assembly_subtitle_burn_in_enabled") : t("assembly_subtitle_burn_in_disabled")}
                  </p>
                </label>
              </div>
              {configurationDirty ? <p className="mt-3 rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-800">{t("assembly_config_unsaved")}</p> : null}
            </section>

            <section className="rounded-xl border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] p-4" data-testid="assembly-render-gate">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-[var(--color-text)]">{t("assembly_render_gate_title")}</h2>
                  <p className="mt-1 text-xs text-[var(--color-text-3)]">{t("assembly_render_gate_description")}</p>
                </div>
                <button type="button" onClick={() => void createFinalRender()} disabled={finalRenderBlocked} className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-3 py-2 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-40" data-testid="assembly-final-render">
                  {creatingFinalRender || finalRenderRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Clapperboard className="h-3.5 w-3.5" aria-hidden />}
                  {finalRenderRunning ? t(finalJob?.status === "queued" ? "assembly_final_render_queued" : "assembly_final_rendering") : t("assembly_final_render")}
                </button>
              </div>
              <ul className="mt-3 grid gap-2 text-xs text-[var(--color-text-2)] md:grid-cols-2">
                <RenderGateItem ready={previewReady} label={t("assembly_gate_preview_ready")} />
                <RenderGateItem ready={previewConfirmed} label={t("assembly_gate_preview_confirmed")} />
                <RenderGateItem ready={renderConfirmed} label={t("assembly_gate_render_confirmed")} />
                <RenderGateItem ready={!isStale} label={t("assembly_gate_revision_current")} />
                <RenderGateItem ready={validation.valid} label={t("assembly_gate_validation_passed")} />
                <RenderGateItem ready={!configurationDirty} label={t("assembly_gate_config_saved")} />
                <RenderGateItem ready={finalRenderAvailable} label={t("assembly_gate_render_service_ready")} />
              </ul>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--color-hairline-soft)] p-3">
                <div>
                  <p className="text-xs font-medium text-[var(--color-text)]">{t("assembly_render_confirmation_title")}</p>
                  <p className="mt-1 text-[10px] text-[var(--color-text-3)]">
                    {renderConfirmed ? t("assembly_render_confirmed", { date: formatDate(plan.render_confirmed_at) ?? "—" }) : t("assembly_render_confirmation_required")}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void confirmRender()}
                  disabled={!previewReady || !previewConfirmed || confirmingRender || renderConfirmed || configurationDirty || !validation.valid || isStale}
                  className="inline-flex items-center gap-2 rounded-lg border border-[var(--color-hairline)] px-3 py-2 text-xs font-medium text-[var(--color-text)] disabled:cursor-not-allowed disabled:opacity-50"
                  data-testid="assembly-confirm-render"
                >
                  {confirmingRender ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <CheckCircle className="h-3.5 w-3.5" aria-hidden />}
                  {renderConfirmed ? t("assembly_render_confirmed_button") : t("assembly_confirm_render")}
                </button>
              </div>
              {renderConfirmationError ? <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-700" role="alert">{t("assembly_render_confirm_error", { message: renderConfirmationError })}</p> : null}
              <p className="mt-3 text-[10px] text-[var(--color-text-3)]">{t(finalRenderAvailable ? "assembly_final_render_service_ready" : "assembly_render_backend_pending")}</p>
              {finalJob ? (
                <div className="mt-3 rounded-lg border border-[var(--color-hairline-soft)] p-3" data-testid="assembly-final-status">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span className="font-medium text-[var(--color-text)]">{t(finalRenderCompleted ? "assembly_final_render_completed" : finalRenderFailed ? "assembly_final_render_failed" : finalJob.status === "queued" ? "assembly_final_render_queued" : "assembly_final_rendering")}</span>
                    <span className="text-[10px] text-[var(--color-text-3)]">{t("assembly_final_render_revision", { revision: finalJob.revision_number })}</span>
                  </div>
                  {finalJob.attempt != null ? <p className="mt-1 text-[10px] text-[var(--color-text-3)]">{t("assembly_final_render_attempt", { attempt: finalJob.attempt, max: finalJob.max_attempts ?? "—" })}</p> : null}
                  {finalRenderError || finalJob.error_message ? <p className="mt-2 text-xs text-red-700" role="alert">{t("assembly_final_render_error", { message: finalRenderError ?? finalJob.error_message })}</p> : null}
                  {finalRenderFailed ? <button type="button" onClick={() => void retryFinalRender()} disabled={retryingFinalRender} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-[var(--color-hairline)] px-3 py-2 text-xs font-medium text-[var(--color-text)] disabled:opacity-50" data-testid="assembly-final-retry">{retryingFinalRender ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}{t("assembly_final_render_retry")}</button> : null}
                </div>
              ) : null}
              {finalRenderCompleted && finalArtifactUrl ? (
                <div className="mt-3 overflow-hidden rounded-lg border border-[var(--color-hairline-soft)] bg-black" data-testid="assembly-final-artifact">
                  <video className="max-h-[420px] w-full" controls preload="metadata" src={finalArtifactUrl}>
                    <track kind="captions" src="data:text/vtt;charset=utf-8,WEBVTT%0A%0A" srcLang="en" label={t("assembly_preview_captions_label")} />
                    {t("assembly_preview_video_fallback")}
                  </video>
                  <div className="flex flex-wrap items-center justify-between gap-2 bg-[var(--panel-card-bg)] px-3 py-2 text-xs">
                    <span className="text-[var(--color-text-2)]">{t("assembly_final_render_duration", { duration: formatDuration(finalJob?.artifact?.duration_seconds ?? totalDuration) })}</span>
                    {finalReviewConfirmed ? (
                      <div className="flex flex-wrap items-center gap-3">
                        <a href={finalArtifactUrl} download={`episode-${plan.episode_number ?? "final"}.mp4`} className="font-medium text-[var(--color-accent)] hover:underline" data-testid="assembly-final-download">{t("assembly_final_render_download")}</a>
                        <button type="button" onClick={() => void exportJianyingDraft()} disabled={exportingJianyingDraft} className="font-medium text-[var(--color-accent)] hover:underline disabled:cursor-not-allowed disabled:opacity-50" data-testid="assembly-jianying-export">{exportingJianyingDraft ? t("assembly_jianying_exporting") : t("assembly_jianying_export")}</button>
                      </div>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[var(--color-text-3)]" aria-disabled="true" data-testid="assembly-final-download-locked"><LockKeyhole className="h-3 w-3" aria-hidden />{t("assembly_final_review_export_locked")}</span>
                    )}
                  </div>
                  {jianyingExportError ? <p className="mt-2 text-[10px] text-red-700" role="alert" data-testid="assembly-jianying-export-error">{t("assembly_jianying_export_error", { error: jianyingExportError })}</p> : null}
                </div>
              ) : null}
              {finalRenderCompleted && finalJob.artifact ? (
                <section className="mt-3 rounded-lg border border-[var(--color-hairline-soft)] p-3" data-testid="assembly-final-review">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold text-[var(--color-text)]">{t("assembly_final_review_title")}</h3>
                      <p className="mt-1 text-xs text-[var(--color-text-3)]">{t("assembly_final_review_description")}</p>
                    </div>
                    {finalReviewConfirmed ? <span className="inline-flex items-center gap-1 text-xs text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden />{t("assembly_final_review_confirmed")}</span> : null}
                  </div>
                  {loadingFinalReview ? <p className="mt-3 text-xs text-[var(--color-text-3)]">{t("assembly_final_review_loading")}</p> : null}
                  {finalReviewError ? <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-700" role="alert">{t("assembly_final_review_unavailable")}</p> : null}
                  {finalReview ? (
                    <>
                      <div className="mt-3 grid gap-2 md:grid-cols-3">
                        {FINAL_REVIEW_POSITIONS.map((position) => {
                          const frame = finalReview.checks.frames.find((item) => item.position === position);
                          const frameUrl = reviewFrameUrls[position];
                          return <figure key={position} className="overflow-hidden rounded-lg border border-[var(--color-hairline-soft)]" data-testid={`assembly-final-review-${position}`}>
                            {frameUrl ? <img src={frameUrl} alt={t(`assembly_final_review_frame_${position}`)} className="aspect-video w-full object-cover" /> : <div className="flex aspect-video items-center justify-center text-xs text-[var(--color-text-3)]">{t("assembly_final_review_unavailable")}</div>}
                            <figcaption className="px-2 py-1 text-[10px] text-[var(--color-text-3)]">{t(`assembly_final_review_frame_${position}`)} · {formatDuration(frame?.timestamp_seconds ?? 0)}</figcaption>
                          </figure>;
                        })}
                      </div>
                      <ul className="mt-3 grid gap-2 text-xs text-[var(--color-text-2)]">
                        <li data-testid="assembly-final-review-duration"><span className="font-medium">{t("assembly_final_review_check_duration")}：</span>{finalReview.checks.duration.within_metadata_tolerance ? t("assembly_final_review_check_duration_ok", { duration: formatDuration(finalReview.checks.duration.seconds) }) : t("assembly_final_review_check_duration_failed")}</li>
                        {finalReview.checks.timeline_duration ? <li data-testid="assembly-final-review-timeline-duration"><span className="font-medium">{t("assembly_final_review_check_timeline_duration")}：</span>{finalReview.checks.timeline_duration.within_tolerance ? t("assembly_final_review_check_timeline_duration_ok", { duration: formatDuration(finalReview.checks.timeline_duration.actual_seconds) }) : t("assembly_final_review_check_timeline_duration_failed", { expected: formatDuration(finalReview.checks.timeline_duration.expected_seconds), actual: formatDuration(finalReview.checks.timeline_duration.actual_seconds) })}</li> : null}
                        <li data-testid="assembly-final-review-audio"><span className="font-medium">{t("assembly_final_review_check_audio")}：</span>{finalReview.checks.audio_stream.present ? t("assembly_final_review_check_audio_present") : t("assembly_final_review_check_audio_missing")}</li>
                        {finalReview.checks.audio_quality?.abnormal ? <li data-testid="assembly-final-review-audio-quality"><span className="font-medium">{t("assembly_final_review_check_audio_quality")}：</span>{finalReview.checks.audio_quality.severity === "blocking" ? t("assembly_final_review_check_audio_quality_blocked") : t("assembly_final_review_check_audio_quality_warning", { count: finalReview.checks.audio_quality.silence_segments.length })}</li> : null}
                        <li data-testid="assembly-final-review-black-frames"><span className="font-medium">{t("assembly_final_review_check_black_frames")}：</span>{finalReview.checks.black_frames.detected ? t("assembly_final_review_check_black_frames_failed", { count: finalReview.checks.black_frames.segments.length }) : t("assembly_final_review_check_black_frames_ok")}</li>
                        {finalReview.checks.black_frames.detected ? <li data-testid="assembly-final-review-black-frame-details"><span className="font-medium">{t("assembly_final_review_check_black_frame_details")}：</span>{t("assembly_final_review_check_black_frame_details_value", { opening: finalReview.checks.black_frames.segments.filter((segment) => segment.edge === "opening").length, middle: finalReview.checks.black_frames.segments.filter((segment) => segment.edge === "middle").length, ending: finalReview.checks.black_frames.segments.filter((segment) => segment.edge === "ending").length })}</li> : null}
                        {finalReview.checks.subtitle_bounds?.detected ? <li data-testid="assembly-final-review-subtitles"><span className="font-medium">{t("assembly_final_review_check_subtitles")}：</span>{t("assembly_final_review_check_subtitles_failed", { count: finalReview.checks.subtitle_bounds.items.length })}</li> : null}
                      </ul>
                      {finalReviewBlocked && !loadingFinalReview ? <p className="mt-3 rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-800">{t("assembly_final_review_blocked")}</p> : null}
                      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs text-[var(--color-text-3)]">{finalReviewConfirmed ? t("assembly_final_review_export_ready") : t("assembly_final_review_confirmation_required")}</span>
                        <button type="button" onClick={() => void confirmFinalReview()} disabled={finalReviewBlocked || Boolean(finalReviewConfirmedAt) || confirmingFinalReview} className="inline-flex items-center gap-2 rounded-lg border border-[var(--color-hairline)] px-3 py-2 text-xs font-medium text-[var(--color-text)] disabled:cursor-not-allowed disabled:opacity-50" data-testid="assembly-final-review-confirm">{confirmingFinalReview ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <CheckCircle className="h-3.5 w-3.5" aria-hidden />}{finalReviewConfirmed ? t("assembly_final_review_confirmed") : t("assembly_final_review_confirm")}</button>
                         {finalReviewConfirmed && finalJob.artifact.id && finalReview.review_snapshot?.id ? <button type="button" onClick={goToPublishing} className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-3 py-2 text-xs font-medium text-white" data-testid="assembly-go-publishing"><Clapperboard className="h-3.5 w-3.5" aria-hidden />{t("assembly_go_publishing")}</button> : null}
                      </div>
                    </>
                  ) : null}
                </section>
              ) : null}
            </section>

            <section className="rounded-xl border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] p-4" data-testid="assembly-materials">
              <div className="flex flex-wrap items-end justify-between gap-2">
                <div>
                  <h2 className="text-sm font-semibold text-[var(--color-text)]">{t("assembly_materials_title")}</h2>
                  <p className="mt-1 text-[10px] text-[var(--color-text-3)]">{t("assembly_material_count", { count: items.length })}</p>
                </div>
                <div className="flex items-center gap-1 text-[10px] text-[var(--color-text-3)]"><Clock3 className="h-3.5 w-3.5" aria-hidden />{formatDuration(totalDuration)}</div>
              </div>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[620px] text-left text-xs">
                  <thead className="border-b border-[var(--color-hairline-soft)] text-[10px] text-[var(--color-text-4)]"><tr><th className="px-2 py-2 font-medium">{t("assembly_item_order")}</th><th className="px-2 py-2 font-medium">{t("assembly_item_name")}</th><th className="px-2 py-2 font-medium">{t("assembly_item_type")}</th><th className="px-2 py-2 font-medium">{t("assembly_item_duration")}</th><th className="px-2 py-2 font-medium">{t("assembly_item_status")}</th></tr></thead>
                  <tbody>{items.slice().sort((a, b) => a.order - b.order).map((item) => <TimelineRow key={item.id} item={item} t={t} />)}</tbody>
                </table>
              </div>
            </section>

            <section className="rounded-xl border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] p-4" data-testid="assembly-packaging-editor">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2"><Pencil className="h-4 w-4 text-[var(--color-accent)]" aria-hidden /><h2 className="text-sm font-semibold text-[var(--color-text)]">{t("assembly_packaging_title")}</h2></div>
                  <p className="mt-1 text-xs text-[var(--color-text-3)]">{t("assembly_packaging_description")}</p>
                </div>
                <button type="button" onClick={() => void saveConfiguration()} disabled={!configurationDirty || savingConfiguration} className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-3 py-2 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-40" data-testid="assembly-packaging-save">
                  {savingConfiguration ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <CheckCircle className="h-3.5 w-3.5" aria-hidden />}{t("assembly_packaging_save")}
                </button>
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-3">
                <PackagingTextEditor kind="intro" enabled={packagingDraft.introEnabled} text={packagingDraft.introText} duration={packagingDraft.introDuration} t={t} onChange={(patch) => { setPackagingDraft((current) => ({ ...current, ...patch })); setConfigurationDirty(true); }} />
                <PackagingTextEditor kind="outro" enabled={packagingDraft.outroEnabled} text={packagingDraft.outroText} duration={packagingDraft.outroDuration} t={t} onChange={(patch) => { setPackagingDraft((current) => ({ ...current, ...patch })); setConfigurationDirty(true); }} />
                <div className="grid gap-2 rounded-lg border border-[var(--color-hairline-soft)] p-3" data-testid="assembly-packaging-cover">
                  <label className="flex items-center gap-2 text-xs font-medium text-[var(--color-text-2)]"><input type="checkbox" checked={packagingDraft.coverEnabled} onChange={(event) => { setPackagingDraft((current) => ({ ...current, coverEnabled: event.target.checked })); setConfigurationDirty(true); }} />{t("assembly_packaging_cover_enabled")}</label>
                  <label className="grid gap-1 text-[10px] text-[var(--color-text-3)]"><span>{t("assembly_packaging_cover_source")}</span><input value={packagingDraft.coverSourceRef} onChange={(event) => { setPackagingDraft((current) => ({ ...current, coverSourceRef: event.target.value })); setConfigurationDirty(true); }} disabled={!packagingDraft.coverEnabled} className="rounded border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] px-2 py-1.5 text-xs text-[var(--color-text)]" /></label>
                  <div className="grid grid-cols-2 gap-2"><label className="grid gap-1 text-[10px] text-[var(--color-text-3)]"><span>{t("assembly_packaging_duration")}</span><input type="number" min="0.1" step="0.1" value={packagingDraft.coverDuration} onChange={(event) => { setPackagingDraft((current) => ({ ...current, coverDuration: event.target.value })); setConfigurationDirty(true); }} disabled={!packagingDraft.coverEnabled} className="rounded border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] px-2 py-1.5 text-xs text-[var(--color-text)]" /></label><label className="grid gap-1 text-[10px] text-[var(--color-text-3)]"><span>{t("assembly_packaging_cover_fit")}</span><select value={packagingDraft.coverFit} onChange={(event) => { setPackagingDraft((current) => ({ ...current, coverFit: event.target.value as "cover" | "contain" })); setConfigurationDirty(true); }} disabled={!packagingDraft.coverEnabled} className="rounded border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] px-2 py-1.5 text-xs text-[var(--color-text)]"><option value="cover">{t("assembly_packaging_cover_fit_cover")}</option><option value="contain">{t("assembly_packaging_cover_fit_contain")}</option></select></label></div>
                </div>
              </div>
              {configurationSaveError ? <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-700" role="alert" data-testid="assembly-packaging-save-error">{t("assembly_packaging_save_error", { error: configurationSaveError })}</p> : null}
              {configurationDirty ? <p className="mt-3 rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-800">{t("assembly_config_unsaved")}</p> : null}
            </section>
          </>
        ) : null}
      </div>
    </main>
  );
}

function PackagingTextEditor({
  kind,
  enabled,
  text,
  duration,
  t,
  onChange,
}: {
  kind: "intro" | "outro";
  enabled: boolean;
  text: string;
  duration: string;
  t: (key: string) => string;
  onChange: (patch: Partial<PackagingDraft>) => void;
}) {
  const prefix = kind === "intro" ? "intro" : "outro";
  return <div className="grid gap-2 rounded-lg border border-[var(--color-hairline-soft)] p-3" data-testid={`assembly-packaging-${prefix}`}>
    <label className="flex items-center gap-2 text-xs font-medium text-[var(--color-text-2)]"><input type="checkbox" checked={enabled} onChange={(event) => onChange({ [`${prefix}Enabled`]: event.target.checked })} />{t(`assembly_packaging_${prefix}_enabled`)}</label>
    <label className="grid gap-1 text-[10px] text-[var(--color-text-3)]"><span>{t("assembly_packaging_text")}</span><textarea value={text} onChange={(event) => onChange({ [`${prefix}Text`]: event.target.value })} disabled={!enabled} rows={2} className="resize-y rounded border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] px-2 py-1.5 text-xs text-[var(--color-text)]" /></label>
    <label className="grid gap-1 text-[10px] text-[var(--color-text-3)]"><span>{t("assembly_packaging_duration")}</span><input type="number" min="0.1" step="0.1" value={duration} onChange={(event) => onChange({ [`${prefix}Duration`]: event.target.value })} disabled={!enabled} className="rounded border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] px-2 py-1.5 text-xs text-[var(--color-text)]" /></label>
  </div>;
}

function StatCard({ label, value, testId }: { label: string; value: string; testId: string }) {
  return <div className="rounded-xl border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] p-4" data-testid={testId}><p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--color-text-4)]">{label}</p><p className="mt-3 text-lg font-semibold text-[var(--color-text)]">{value}</p></div>;
}

function StatusBadge({ status, t }: { status: string; t: (key: string) => string }) {
  return <span className="inline-flex rounded-full bg-[var(--color-accent-soft)] px-2 py-1 text-[10px] font-medium text-[var(--color-accent)]">{t(`assembly_status_${status}`)}</span>;
}

function ValidationBadge({ valid, warningCount, t }: { valid: boolean; warningCount: number; t: (key: string) => string }) {
  if (!valid) return <span className="inline-flex items-center gap-1 rounded-full bg-red-500/10 px-2 py-1 text-[10px] font-medium text-red-700"><XCircle className="h-3 w-3" aria-hidden />{t("assembly_validation_failed")}</span>;
  if (warningCount > 0) return <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-1 text-[10px] font-medium text-amber-700"><AlertTriangle className="h-3 w-3" aria-hidden />{t("assembly_validation_has_warnings")}</span>;
  return <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-1 text-[10px] font-medium text-emerald-700"><CheckCircle2 className="h-3 w-3" aria-hidden />{t("assembly_validation_passed")}</span>;
}

function RenderGateItem({ ready, label }: { ready: boolean; label: string }) {
  return <li className="flex items-center gap-2"><span className={ready ? "text-emerald-600" : "text-amber-600"}>{ready ? <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> : <AlertTriangle className="h-3.5 w-3.5" aria-hidden />}</span>{label}</li>;
}

function IssueIcon({ severity }: { severity: "warning" | "error" }) {
  return severity === "error" ? <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-600" aria-hidden /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" aria-hidden />;
}

function TimelineRow({ item, t }: { item: AssemblyTimelineItem; t: (key: string) => string }) {
  const status = item.status ?? "ready";
  return <tr className="border-b border-[var(--color-hairline-soft)] last:border-0"><td className="px-2 py-3 font-mono text-[10px] text-[var(--color-text-4)]">{item.order + 1}</td><td className="max-w-[280px] truncate px-2 py-3 text-[var(--color-text)]" title={item.label ?? item.source_ref}>{item.label ?? item.source_ref}</td><td className="px-2 py-3 text-[var(--color-text-3)]">{item.kind}</td><td className="px-2 py-3 text-[var(--color-text-3)]">{formatDuration(item.duration_seconds)}</td><td className="px-2 py-3"><span className={`rounded-full px-2 py-1 text-[10px] ${status === "ready" ? "bg-emerald-500/10 text-emerald-700" : status === "failed" || status === "missing" ? "bg-red-500/10 text-red-700" : "bg-amber-500/10 text-amber-700"}`}>{t(`assembly_item_status_${status}`)}</span></td></tr>;
}
