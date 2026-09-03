import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { EpisodeDurationPlanPanel } from "./EpisodeDurationPlanPanel";

vi.mock("@/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api")>();
  return {
    ...original,
    API: {
      getEpisodeDurationPlan: vi.fn(),
      saveEpisodeDurationPlan: vi.fn(),
      previewEpisodeDurationPlan: vi.fn(),
      applyEpisodeDurationPlan: vi.fn(),
      setEpisodeDurationLock: vi.fn(),
    },
  };
});

const STATE = {
  revision: "rev-1",
  plan: { target_seconds: 20, strategy: "equal" as const, manual_allocations: {} },
  items: [
    { resource_id: "S1", duration_seconds: 4, locked: false, generated: false },
    { resource_id: "S2", duration_seconds: 6, locked: true, generated: false },
  ],
};

describe("EpisodeDurationPlanPanel", () => {
  beforeEach(() => {
    vi.mocked(API.getEpisodeDurationPlan).mockResolvedValue(STATE);
    vi.mocked(API.saveEpisodeDurationPlan).mockResolvedValue({ revision: "rev-2", plan: STATE.plan });
    vi.mocked(API.previewEpisodeDurationPlan).mockResolvedValue({
      revision: "rev-1",
      plan: STATE.plan,
      target_seconds: 20,
      changes: [{ resource_id: "S1", from_seconds: 4, to_seconds: 8, clamp_reason: null }],
    });
    vi.mocked(API.applyEpisodeDurationPlan).mockResolvedValue({
      revision: "rev-2",
      plan: STATE.plan,
      applied: { S1: 8 },
      skipped: [],
    });
    vi.mocked(API.setEpisodeDurationLock).mockResolvedValue({
      revision: "rev-2",
      resource_id: "S1",
      locked: true,
    });
  });

  it("previews and explicitly applies changes", async () => {
    const onApplied = vi.fn();
    render(<EpisodeDurationPlanPanel projectName="demo" episode={1} onApplied={onApplied} />);

    await screen.findByDisplayValue(20);
    fireEvent.click(screen.getByRole("button", { name: "预览调整" }));
    expect(await screen.findByText("应用时长调整？")).toBeInTheDocument();
    expect(screen.getByText("4s → 8s")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "应用调整" }));
    await waitFor(() =>
      expect(API.applyEpisodeDurationPlan).toHaveBeenCalledWith("demo", 1, "rev-1", STATE.plan),
    );
    expect(onApplied).toHaveBeenCalledTimes(1);
  });

  it("toggles a per-shot duration lock with the current revision", async () => {
    render(<EpisodeDurationPlanPanel projectName="demo" episode={1} />);

    fireEvent.click(await screen.findByRole("button", { name: /S1/ }));
    await waitFor(() =>
      expect(API.setEpisodeDurationLock).toHaveBeenCalledWith("demo", 1, "S1", "rev-1", true),
    );
  });
});
