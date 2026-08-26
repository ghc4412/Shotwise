import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import "@/i18n";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import type { ProjectData } from "@/types";
import { SourceFilesPage } from "./SourceFilesPage";

vi.mock("./CreativeDraftEditor", () => ({
  CreativeDraftEditor: ({ initialGenerate }: { initialGenerate: boolean }) => (
    <div data-testid="creative-draft-editor">{initialGenerate ? "generate" : "write"}</div>
  ),
}));

function renderPage(path: string) {
  const location = memoryLocation({ path, record: true });
  return render(
    <Router hook={location.hook} searchHook={location.searchHook}>
      <SourceFilesPage projectName="demo" />
    </Router>,
  );
}

describe("SourceFilesPage creative draft tab", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useAppStore.setState(useAppStore.getInitialState(), true);
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    vi.spyOn(API, "listFiles").mockResolvedValue({ files: { source: [] } });
  });

  it("opens the creative draft tab and generation panel from the creation route", async () => {
    useProjectsStore.setState({ currentProjectData: { content_mode: "narration" } as ProjectData });
    renderPage("/source?tab=draft&action=generate");

    expect(await screen.findByTestId("creative-draft-editor")).toHaveTextContent("generate");
    expect(screen.getByRole("button", { name: "创作稿" })).toHaveAttribute("aria-pressed", "true");
  });

  it("does not expose the creative draft tab for ad projects", async () => {
    useProjectsStore.setState({ currentProjectData: { content_mode: "ad" } as ProjectData });
    renderPage("/source?tab=draft");

    await waitFor(() => expect(API.listFiles).toHaveBeenCalledWith("demo"));
    expect(screen.queryByRole("button", { name: "创作稿" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("creative-draft-editor")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "文稿" })).toHaveAttribute("aria-pressed", "true");
  });
});
