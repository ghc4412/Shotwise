import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
import { AssemblyPlanPage } from "@/components/canvas/AssemblyPlanPage";
import type { AssemblyFinalReview, AssemblyPlan, AssemblyPlanRevision, AssemblyRenderJob } from "@/types";

const { setLocationMock } = vi.hoisted(() => ({ setLocationMock: vi.fn() }));

vi.mock("wouter", () => ({
  useLocation: () => ["/app/assembly", setLocationMock],
}));

vi.mock("@/api", () => ({
  API: {
    listAssemblyPlans: vi.fn(),
    getAssemblyPlan: vi.fn(),
    createAssemblyPlanRevision: vi.fn(),
    confirmAssemblyPlanPreview: vi.fn(),
    confirmAssemblyPlanRender: vi.fn(),
    createAssemblyFinalRender: vi.fn(),
    getRenderJob: vi.fn(),
    retryFinalRenderJob: vi.fn(),
    downloadRenderJobArtifact: vi.fn(),
    getAssemblyFinalReview: vi.fn(),
    downloadAssemblyFinalReviewFrame: vi.fn(),
    downloadAssemblySubtitles: vi.fn(),
    confirmAssemblyFinalReview: vi.fn(),
  },
}));

const makeRevision = (overrides: Partial<AssemblyPlanRevision> = {}): AssemblyPlanRevision => ({
  id: "revision-1",
  plan_id: "plan-1",
  version_number: 2,
  source_fingerprint: "source-a",
  source_snapshot: {},
  timeline: [
    { id: "unit-1", order: 0, kind: "video_unit", source_ref: "media/unit-1.mp4", label: "Opening shot", duration_seconds: 8, status: "ready" },
    { id: "unit-2", order: 1, kind: "video_unit", source_ref: "media/unit-2.mp4", duration_seconds: 6, status: "missing" },
  ],
  audio: {},
  subtitle: {},
  packaging: {},
  output_profile: { format: "mp4" },
  validation: { valid: true, errors: [], warnings: [] },
  created_by: "user-1",
  created_at: "2026-09-13T00:00:00Z",
  ...overrides,
});

const makePlan = (overrides: Partial<AssemblyPlan> = {}): AssemblyPlan => ({
  id: "plan-1",
  project_name: "project-a",
  scope: "episode",
  episode_number: 1,
  name: "Episode 1 assembly",
  status: "draft",
  current_revision_number: 2,
  current_source_fingerprint: "source-a",
  created_at: "2026-09-13T00:00:00Z",
  updated_at: "2026-09-13T00:00:00Z",
  current_revision: makeRevision(),
  ...overrides,
});

function renderPage() {
  return render(<AssemblyPlanPage projectName="project-a" />);
}

function makeReadyPlan(overrides: Partial<AssemblyPlan> = {}): AssemblyPlan {
  return makePlan({
    status: "preview_ready",
    preview_revision_number: 2,
    preview_ready_at: "2026-09-13T00:01:00Z",
    preview_confirmed_by: "user-1",
    preview_confirmed_at: "2026-09-13T00:02:00Z",
    render_confirmed_by: "user-1",
    render_confirmed_at: "2026-09-13T00:02:30Z",
    preview_artifact: { id: "preview-1", url: "/preview.mp4", kind: "preview" },
    ...overrides,
  });
}

function makeFinalJob(overrides: Partial<AssemblyRenderJob> = {}): AssemblyRenderJob {
  return {
    id: "final-job-1",
    plan_id: "plan-1",
    revision_number: 2,
    kind: "final",
    status: "queued",
    attempt: 1,
    max_attempts: 3,
    ...overrides,
  };
}

function makeFinalReview(overrides: Partial<AssemblyFinalReview> = {}): AssemblyFinalReview {
  return {
    status: "ready",
    plan_id: "plan-1",
    revision_number: 2,
    artifact: { id: "final-artifact-1", kind: "final" },
    checks: {
      duration: { seconds: 14, metadata_seconds: 14, within_metadata_tolerance: true },
      audio_stream: { present: true },
      black_frames: { detected: false, segments: [] },
      frames: [
        { position: "first", timestamp_seconds: 0, relative_path: "frames/first.jpg" },
        { position: "middle", timestamp_seconds: 7, relative_path: "frames/middle.jpg" },
        { position: "last", timestamp_seconds: 13.9, relative_path: "frames/last.jpg" },
      ],
    },
    ...overrides,
  };
}

describe("AssemblyPlanPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    useProjectsStore.setState({
      currentProjectName: "project-a",
      currentProjectData: {
        title: "Project A",
        content_mode: "drama",
        style: "Cinematic",
        episodes: [
          { episode: 1, title: "Episode One", script_file: "scripts/episode_1.json" },
          { episode: 2, title: "Episode Two", script_file: "scripts/episode_2.json" },
        ],
        characters: {},
        scenes: {},
        props: {},
      },
    });
  });

  it("shows a loading state while the plan list is pending", () => {
    vi.mocked(API.listAssemblyPlans).mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByTestId("assembly-loading")).toBeInTheDocument();
  });

  it("shows the empty state when no plan exists for the selected episode", async () => {
    vi.mocked(API.listAssemblyPlans).mockResolvedValue({ items: [] });
    renderPage();
    expect(await screen.findByTestId("assembly-empty")).toBeInTheDocument();
    expect(screen.getByText("暂无成片计划")).toBeInTheDocument();
    expect(API.getAssemblyPlan).not.toHaveBeenCalled();
  });

  it("shows revision, duration, ordered materials, and validation issues", async () => {
    vi.mocked(API.listAssemblyPlans).mockResolvedValue({ items: [makePlan()] });
    vi.mocked(API.getAssemblyPlan).mockResolvedValue(makePlan({
      current_revision: makeRevision({
        validation: { valid: false, errors: [{ code: "missing_source", message: "Opening source is missing", severity: "error" }], warnings: [] },
      }),
    }));
    renderPage();
    expect(await screen.findByTestId("assembly-plan-summary")).toBeInTheDocument();
    expect(screen.getByTestId("assembly-revision")).toHaveTextContent("v2");
    expect(screen.getByTestId("assembly-duration")).toHaveTextContent("0:14");
    expect(screen.getByText("Opening shot")).toBeInTheDocument();
    expect(screen.getByText("Opening source is missing")).toBeInTheDocument();
    expect(screen.getAllByText("校验失败")).toHaveLength(2);
    expect(screen.getByTestId("assembly-packaging-editor")).toBeInTheDocument();
    expect(screen.getByTestId("assembly-packaging-save")).toBeDisabled();
  });

  it("shows a stale warning", async () => {
    vi.mocked(API.listAssemblyPlans).mockResolvedValue({ items: [makePlan({ stale: true, status: "stale" })] });
    vi.mocked(API.getAssemblyPlan).mockResolvedValue(makePlan({ stale: true, status: "stale" }));
    renderPage();
    expect(await screen.findByText("源素材已变化")).toBeInTheDocument();
  });

  it("reloads the selected episode plan", async () => {
    const user = userEvent.setup();
    vi.mocked(API.listAssemblyPlans).mockResolvedValue({ items: [makePlan(), makePlan({ id: "plan-2", episode_number: 2, name: "Episode 2 assembly" })] });
    vi.mocked(API.getAssemblyPlan)
      .mockResolvedValueOnce(makePlan())
      .mockResolvedValueOnce(makePlan({ id: "plan-2", episode_number: 2, name: "Episode 2 assembly" }));
    renderPage();
    await screen.findByText("Episode 1 assembly");
    await user.selectOptions(screen.getByRole("combobox", { name: "剧集" }), "2");
    await waitFor(() => expect(API.getAssemblyPlan).toHaveBeenCalledWith("plan-2", expect.anything()));
    expect(await screen.findByText("Episode 2 assembly")).toBeInTheDocument();
  });

  it("exports SRT and VTT subtitles as browser downloads", async () => {
    const user = userEvent.setup();
    const readyPlan = makeReadyPlan({
      current_revision: makeRevision({ subtitle: { mode: "burn-in" } }),
    });
    vi.mocked(API.listAssemblyPlans).mockResolvedValue({ items: [readyPlan] });
    vi.mocked(API.getAssemblyPlan).mockResolvedValue(readyPlan);
    vi.mocked(API.downloadAssemblySubtitles).mockResolvedValue(new Blob(["subtitle"], { type: "text/plain" }));
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:subtitle");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    renderPage();
    await waitFor(() => expect(screen.getByTestId("assembly-subtitle-burn-in-status")).toHaveTextContent("字幕已烧录到画面"));

    await user.click(screen.getByTestId("assembly-subtitle-export-srt"));
    await waitFor(() => expect(API.downloadAssemblySubtitles).toHaveBeenCalledWith("plan-1", "srt"));
    await waitFor(() => expect(click).toHaveBeenCalled());

    await user.click(screen.getByTestId("assembly-subtitle-export-vtt"));
    await waitFor(() => expect(API.downloadAssemblySubtitles).toHaveBeenCalledWith("plan-1", "vtt"));
    expect(createObjectURL).toHaveBeenCalledTimes(2);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:subtitle");

    createObjectURL.mockRestore();
    revokeObjectURL.mockRestore();
    click.mockRestore();
  });

  it("shows a subtitle export error without changing the plan", async () => {
    const user = userEvent.setup();
    const readyPlan = makeReadyPlan();
    vi.mocked(API.listAssemblyPlans).mockResolvedValue({ items: [readyPlan] });
    vi.mocked(API.getAssemblyPlan).mockResolvedValue(readyPlan);
    vi.mocked(API.downloadAssemblySubtitles).mockRejectedValue(new Error("subtitle export failed"));

    renderPage();
    await user.click(await screen.findByTestId("assembly-subtitle-export-srt"));

    expect(await screen.findByTestId("assembly-subtitle-export-error")).toHaveTextContent("subtitle export failed");
    expect(API.getAssemblyPlan).toHaveBeenCalledWith("plan-1", expect.anything());
  });

  it("enables final rendering only after all gates pass", async () => {
    const readyPlan = makeReadyPlan();
    vi.mocked(API.listAssemblyPlans).mockResolvedValue({ items: [readyPlan] });
    vi.mocked(API.getAssemblyPlan).mockResolvedValue(readyPlan);
    renderPage();
    await screen.findByTestId("assembly-render-gate");
    expect(screen.getByTestId("assembly-final-render")).toBeEnabled();
  });

  it("does not enable final rendering after preview confirmation alone", async () => {
    const previewOnlyPlan = makeReadyPlan({ render_confirmed_by: null, render_confirmed_at: null });
    vi.mocked(API.listAssemblyPlans).mockResolvedValue({ items: [previewOnlyPlan] });
    vi.mocked(API.getAssemblyPlan).mockResolvedValue(previewOnlyPlan);
    renderPage();
    await screen.findByTestId("assembly-final-render");
    expect(screen.getByTestId("assembly-final-render")).toBeDisabled();
    expect(screen.getByTestId("assembly-confirm-render")).toBeEnabled();
  });

  it("creates a final job, polls it, and displays the completed artifact", async () => {
    const user = userEvent.setup();
    const readyPlan = makeReadyPlan();
    vi.mocked(API.listAssemblyPlans).mockResolvedValue({ items: [readyPlan] });
    vi.mocked(API.getAssemblyPlan).mockResolvedValue(readyPlan);
    vi.mocked(API.createAssemblyFinalRender).mockResolvedValue(makeFinalJob());
    vi.mocked(API.getRenderJob).mockResolvedValue(makeFinalJob({
      status: "succeeded",
      completed_at: "2026-09-13T00:03:00Z",
      artifact: { id: "final-artifact-1", url: "/final.mp4", duration_seconds: 14, kind: "final" },
    }));
    vi.mocked(API.getAssemblyFinalReview).mockResolvedValue(makeFinalReview());
    vi.mocked(API.downloadAssemblyFinalReviewFrame).mockResolvedValue(new Blob(["frame"], { type: "image/jpeg" }));
    renderPage();
    await screen.findByTestId("assembly-final-render");
    await user.click(screen.getByTestId("assembly-final-render"));
    await waitFor(() => expect(API.createAssemblyFinalRender).toHaveBeenCalledWith("plan-1", {
      revision_number: 2,
      max_attempts: 3,
    }));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1600));
    });
    expect(await screen.findByTestId("assembly-final-artifact")).toBeInTheDocument();
    expect(await screen.findByTestId("assembly-final-review")).toBeInTheDocument();
    vi.mocked(API.confirmAssemblyFinalReview).mockResolvedValue({
      id: "review-1", artifact_id: "final-artifact-1", plan_id: "plan-1", revision_number: 2,
      status: "ready", created_at: "2026-09-13T00:04:00Z", confirmed_by: "user-1", confirmed_at: "2026-09-13T00:04:00Z",
    });
    expect(screen.getByTestId("assembly-final-review-first")).toBeInTheDocument();
    expect(screen.getByTestId("assembly-final-review-middle")).toBeInTheDocument();
    expect(screen.getByTestId("assembly-final-review-last")).toBeInTheDocument();
    expect(screen.getByTestId("assembly-final-download-locked")).toBeInTheDocument();
    expect(screen.queryByTestId("assembly-go-publishing")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("assembly-final-review-confirm"));
    expect(await screen.findByTestId("assembly-final-download")).toHaveAttribute("href", "/final.mp4");
    expect(screen.getByTestId("assembly-go-publishing")).toBeInTheDocument();
    await user.click(screen.getByTestId("assembly-go-publishing"));
    expect(setLocationMock).toHaveBeenCalledWith("/app/publishing?artifact_id=final-artifact-1&review_snapshot_id=review-1");
    expect(API.confirmAssemblyFinalReview).toHaveBeenCalledWith("final-artifact-1", { revision_number: 2 });
  });

  it("treats missing audio as informational and allows final review confirmation", async () => {
    const user = userEvent.setup();
    const readyPlan = makeReadyPlan();
    vi.mocked(API.listAssemblyPlans).mockResolvedValue({ items: [readyPlan] });
    vi.mocked(API.getAssemblyPlan).mockResolvedValue(readyPlan);
    vi.mocked(API.createAssemblyFinalRender).mockResolvedValue(makeFinalJob());
    vi.mocked(API.getRenderJob).mockResolvedValue(makeFinalJob({
      status: "succeeded",
      artifact: { id: "final-artifact-1", url: "/final.mp4", duration_seconds: 14, kind: "final" },
    }));
    vi.mocked(API.getAssemblyFinalReview).mockResolvedValue(makeFinalReview({
      checks: { ...makeFinalReview().checks, audio_stream: { present: false } },
    }));
    vi.mocked(API.downloadAssemblyFinalReviewFrame).mockResolvedValue(new Blob(["frame"], { type: "image/jpeg" }));
    renderPage();
    await user.click(await screen.findByTestId("assembly-final-render"));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 1600)); });
    expect(await screen.findByTestId("assembly-final-review-audio")).toHaveTextContent("未检测到音频流，不阻塞确认");
    expect(screen.getByTestId("assembly-final-review-confirm")).toBeEnabled();
  });

  it("blocks final review confirmation when black frames are detected", async () => {
    const readyPlan = makeReadyPlan();
    vi.mocked(API.listAssemblyPlans).mockResolvedValue({ items: [readyPlan] });
    vi.mocked(API.getAssemblyPlan).mockResolvedValue(readyPlan);
    vi.mocked(API.createAssemblyFinalRender).mockResolvedValue(makeFinalJob());
    vi.mocked(API.getRenderJob).mockResolvedValue(makeFinalJob({
      status: "succeeded",
      artifact: { id: "final-artifact-1", url: "/final.mp4", duration_seconds: 14, kind: "final" },
    }));
    vi.mocked(API.getAssemblyFinalReview).mockResolvedValue(makeFinalReview({
      checks: {
        ...makeFinalReview().checks,
        black_frames: { detected: true, segments: [{ start_seconds: 4, end_seconds: 5, duration_seconds: 1 }] },
      },
    }));
    vi.mocked(API.downloadAssemblyFinalReviewFrame).mockResolvedValue(new Blob(["frame"], { type: "image/jpeg" }));
    renderPage();
    await userEvent.setup().click(await screen.findByTestId("assembly-final-render"));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 1600)); });
    expect(await screen.findByTestId("assembly-final-review-black-frames")).toHaveTextContent("检测到 1 段黑帧");
    expect(screen.getByTestId("assembly-final-review-confirm")).toBeDisabled();
    expect(screen.getByTestId("assembly-final-download-locked")).toBeInTheDocument();
  });

  it("shows final render failure and retries the same job", async () => {
    const user = userEvent.setup();
    const readyPlan = makeReadyPlan();
    vi.mocked(API.listAssemblyPlans).mockResolvedValue({ items: [readyPlan] });
    vi.mocked(API.getAssemblyPlan).mockResolvedValue(readyPlan);
    vi.mocked(API.createAssemblyFinalRender).mockResolvedValue(makeFinalJob({
      status: "failed",
      error_message: "ffmpeg failed",
    }));
    vi.mocked(API.retryFinalRenderJob).mockResolvedValue(makeFinalJob({ status: "queued" }));
    renderPage();
    await screen.findByTestId("assembly-final-render");
    await user.click(screen.getByTestId("assembly-final-render"));
    expect(await screen.findByText("渲染错误：ffmpeg failed")).toBeInTheDocument();
    await user.click(screen.getByTestId("assembly-final-retry"));
    await waitFor(() => expect(API.retryFinalRenderJob).toHaveBeenCalledWith("final-job-1"));
  });

  it("shows a backend error instead of fabricating a plan", async () => {
    vi.mocked(API.listAssemblyPlans).mockRejectedValue(new Error("not ready"));
    renderPage();
    expect(await screen.findByTestId("assembly-error")).toBeInTheDocument();
    expect(screen.getByText("成片计划服务不可用，或当前还没有创建计划。")).toBeInTheDocument();
  });
});
