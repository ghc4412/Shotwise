import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "@/i18n";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useAssistantStore } from "@/stores/assistant-store";
import { useProjectsStore } from "@/stores/projects-store";
import { CreativeDraftEditor } from "./CreativeDraftEditor";

describe("CreativeDraftEditor", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useAppStore.setState(useAppStore.getInitialState(), true);
    useAssistantStore.setState(useAssistantStore.getInitialState(), true);
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    vi.spyOn(API, "getSourceContent").mockResolvedValue("已有原稿");
    vi.spyOn(API, "saveSourceFile").mockResolvedValue({ success: true });
    vi.spyOn(API, "generateCreativeDraft").mockResolvedValue({
      operation: "generate",
      content: "AI 建议内容",
      provider: "test",
      model: "test-model",
    });
  });

  it("loads the draft and saves explicit edits to the stable source filename", async () => {
    render(<CreativeDraftEditor projectName="demo" contentMode="narration" />);

    const editor = await screen.findByDisplayValue("已有原稿");
    fireEvent.change(editor, { target: { value: "修改后的原稿" } });
    fireEvent.click(screen.getByRole("button", { name: "保存创作稿" }));

    await waitFor(() => {
      expect(API.saveSourceFile).toHaveBeenCalledWith("demo", "creative_draft.md", "修改后的原稿");
    });
  });

  it("saves draft edits with the standard keyboard shortcut", async () => {
    render(<CreativeDraftEditor projectName="demo" contentMode="narration" />);

    const editor = await screen.findByDisplayValue("已有原稿");
    fireEvent.change(editor, { target: { value: "快捷保存后的原稿" } });
    fireEvent.keyDown(editor, { key: "s", ctrlKey: true });

    await waitFor(() => {
      expect(API.saveSourceFile).toHaveBeenCalledWith("demo", "creative_draft.md", "快捷保存后的原稿");
    });
  });

  it("keeps AI output as a suggestion until the user explicitly replaces the draft", async () => {
    render(<CreativeDraftEditor projectName="demo" contentMode="narration" />);

    await screen.findByDisplayValue("已有原稿");
    fireEvent.change(screen.getByLabelText("创作要求"), { target: { value: "写一个雨夜开场" } });
    fireEvent.click(screen.getByRole("button", { name: "生成初稿" }));

    await screen.findByText("AI 建议内容");
    expect(screen.getByDisplayValue("已有原稿")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "替换草稿" }));
    expect(screen.getByDisplayValue("AI 建议内容")).toBeInTheDocument();
  });

  it("uses selected text for polishing and replaces only that selection", async () => {
    vi.mocked(API.getSourceContent).mockResolvedValue("前文旧句后文");
    render(<CreativeDraftEditor projectName="demo" contentMode="narration" />);

    const editor = (await screen.findByDisplayValue("前文旧句后文")) as HTMLTextAreaElement;
    editor.setSelectionRange(2, 4);
    fireEvent.select(editor);
    fireEvent.click(screen.getByRole("button", { name: "润色" }));

    await waitFor(() => {
      expect(API.generateCreativeDraft).toHaveBeenCalledWith(
        "demo",
        expect.objectContaining({ operation: "polish", content: "旧句" }),
      );
    });
    fireEvent.click(screen.getByRole("button", { name: "替换草稿" }));
    expect(screen.getByDisplayValue("前文AI 建议内容后文")).toBeInTheDocument();
  });

  it("adds the selected novel profile to the AI creative direction", async () => {
    render(<CreativeDraftEditor projectName="demo" contentMode="drama" sourceKind="novel" />);

    await screen.findByDisplayValue("已有原稿");
    fireEvent.click(screen.getByRole("button", { name: "悬疑" }));
    fireEvent.click(screen.getByRole("button", { name: "女频" }));
    fireEvent.click(screen.getByRole("button", { name: "第三人称" }));
    fireEvent.click(screen.getByRole("button", { name: "长篇小说" }));
    fireEvent.click(screen.getByRole("button", { name: "紧张刺激" }));
    fireEvent.change(screen.getByLabelText("创作要求"), { target: { value: "写一个雨夜开场" } });
    fireEvent.click(screen.getByRole("button", { name: "生成初稿" }));

    await waitFor(() => {
      expect(API.generateCreativeDraft).toHaveBeenCalledWith(
        "demo",
        expect.objectContaining({
          instruction: expect.stringContaining("小说题材：悬疑；目标读者：女频；作品视角：第三人称；篇幅长短：长篇小说；叙事基调：紧张刺激"),
        }),
      );
    });
  });

  it("does not show novel profile controls for screenplay drafts", async () => {
    render(<CreativeDraftEditor projectName="demo" contentMode="drama" sourceKind="screenplay" />);

    await screen.findByDisplayValue("已有原稿");
    expect(screen.queryByText("小说设定")).not.toBeInTheDocument();
  });

  it("collapses and reopens the novel profile controls", async () => {
    render(<CreativeDraftEditor projectName="demo" contentMode="drama" sourceKind="novel" />);

    await screen.findByDisplayValue("已有原稿");
    expect(screen.getByRole("button", { name: "悬疑" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "收起小说设定" }));
    expect(screen.queryByRole("button", { name: "悬疑" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开小说设定" }));
    expect(screen.getByRole("button", { name: "悬疑" })).toBeInTheDocument();
  });

  it("collapses and reopens creative direction", async () => {
    render(<CreativeDraftEditor projectName="demo" contentMode="narration" />);

    await screen.findByDisplayValue("已有原稿");
    expect(screen.getByLabelText("创作要求")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "收起创作要求" }));
    expect(screen.queryByLabelText("创作要求")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开创作要求" }));
    expect(screen.getByLabelText("创作要求")).toBeInTheDocument();
  });

  it("collapses and reopens the detailed-outline sidebar for novel drafts", async () => {
    render(<CreativeDraftEditor projectName="demo" contentMode="drama" sourceKind="novel" />);

    await screen.findByText("细纲管理");
    fireEvent.click(screen.getByRole("button", { name: "收起细纲侧栏" }));
    expect(screen.queryByText("细纲管理")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开细纲侧栏" }));
    expect(await screen.findByText("细纲管理")).toBeInTheDocument();
  });

  it("saves before asset extraction and hands the source path to the existing assistant", async () => {
    render(<CreativeDraftEditor projectName="demo" contentMode="drama" sourceKind="screenplay" />);

    const editor = await screen.findByDisplayValue("已有原稿");
    fireEvent.change(editor, { target: { value: "更新后的剧本原稿" } });
    fireEvent.click(screen.getByRole("button", { name: "提取角色、场景、道具" }));

    await waitFor(() => {
      expect(API.saveSourceFile).toHaveBeenCalledWith("demo", "creative_draft.md", "更新后的剧本原稿");
    });
    expect(useAssistantStore.getState().input).toContain("source/creative_draft.md");
    expect(useAppStore.getState().assistantPanelOpen).toBe(true);
  });

  it("generates an overview and opens the screenplay planning handoff only after confirmation", async () => {
    const refreshProject = vi
      .spyOn(useProjectsStore.getState(), "refreshProject")
      .mockResolvedValue("success");
    vi.spyOn(API, "generateOverview").mockResolvedValue({
      success: true,
      overview: {
        synopsis: "demo",
        genre: "",
        world_setting: "",
        theme: "",
      },
    });
    render(<CreativeDraftEditor projectName="demo" contentMode="drama" sourceKind="screenplay" />);

    await screen.findByDisplayValue("已有原稿");
    fireEvent.click(screen.getByRole("button", { name: "确认作为制作原稿" }));

    await waitFor(() => {
      expect(API.generateOverview).toHaveBeenCalledWith("demo");
      expect(refreshProject).toHaveBeenCalledWith("demo");
    });
    expect(useAssistantStore.getState().input).toContain("场次、角色、对白与旁白");
  });
});
