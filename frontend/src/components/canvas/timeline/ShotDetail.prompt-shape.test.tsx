import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ShotDetail } from "./ShotDetail";
import type { DramaScene } from "@/types";

function makeScene(overrides: Partial<DramaScene> = {}): DramaScene {
  return {
    scene_id: "E1S01",
    duration_seconds: 8,
    segment_break: false,
    characters_in_scene: [],
    scenes: [],
    props: [],
    image_prompt: {
      scene: "A lantern glows in rain",
      composition: {
        shot_type: "Medium Shot",
        lighting: "Warm",
        ambiance: "Quiet",
      },
    },
    video_prompt: {
      action: "The lantern sways",
      camera_motion: "Static",
      ambiance_audio: "Rainfall",
      dialogue: [],
    },
    utterances: [],
    transition_to_next: "cut",
    ...overrides,
  };
}

function renderDetail(
  props: Partial<Parameters<typeof ShotDetail>[0]> = {},
) {
  const scene = makeScene();
  return render(
    <ShotDetail
      segment={scene}
      segmentId={scene.scene_id}
      contentMode="drama"
      aspectRatio="9:16"
      projectName="demo"
      scriptFile="episode_1.json"
      selectedIndex={0}
      totalCount={1}
      onPrev={() => {}}
      onNext={() => {}}
      durationOptions={[8]}
      {...props}
    />,
  );
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function textboxWithValue(value: string): HTMLTextAreaElement {
  const textbox = screen.getAllByRole("textbox").find((node) => (node as HTMLTextAreaElement).value === value);
  if (!textbox) throw new Error(`textbox not found: ${value}`);
  return textbox as HTMLTextAreaElement;
}

describe("ShotDetail Prompt Shape", () => {
  it("切换 shape 只修改本地 working draft，用户点击保存后才提交", async () => {
    const onUpdatePrompt = vi.fn().mockResolvedValue(undefined);
    renderDetail({ onUpdatePrompt });

    fireEvent.click(screen.getByTestId("image-prompt-shape-toggle"));

    const textPrompt = screen.getByPlaceholderText("描述这一镜的画面：环境、人物、动作、构图细节…");
    expect(textPrompt).toHaveValue(
      "A lantern glows in rain\nShot type: Medium Shot\nLighting: Warm\nAmbiance: Quiet",
    );
    expect(textPrompt).toBeInTheDocument();
    expect(onUpdatePrompt).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(onUpdatePrompt).toHaveBeenCalledWith("E1S01", {
        image_prompt: "A lantern glows in rain\nShot type: Medium Shot\nLighting: Warm\nAmbiance: Quiet",
      });
    });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "保存" })).toBeNull();
    });
  });

  it("保存失败时恢复最近 committed draft，将失败输入保留为可恢复草稿并显示字段错误", async () => {
    const onUpdatePrompt = vi.fn().mockRejectedValue(new Error("network unavailable"));
    renderDetail({ onUpdatePrompt });

    fireEvent.click(screen.getByTestId("image-prompt-shape-toggle"));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveAttribute(
        "data-prompt-error-field",
        "image_prompt",
      );
    });
    expect(textboxWithValue("A lantern glows in rain")).toHaveValue(
      "A lantern glows in rain",
    );
    expect(screen.queryByRole("button", { name: "保存" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "重试保存" }));

    expect(textboxWithValue("A lantern glows in rain\nShot type: Medium Shot\nLighting: Warm\nAmbiance: Quiet")).toHaveValue(
      "A lantern glows in rain\nShot type: Medium Shot\nLighting: Warm\nAmbiance: Quiet",
    );
    expect(screen.getByRole("button", { name: "保存" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("旧保存响应结算时不覆盖请求后继续编辑的 working draft", async () => {
    const firstSave = deferred<void>();
    const onUpdatePrompt = vi.fn().mockReturnValue(firstSave.promise);
    renderDetail({ onUpdatePrompt });

    fireEvent.click(screen.getByTestId("image-prompt-shape-toggle"));
    const textPrompt = screen.getByPlaceholderText("描述这一镜的画面：环境、人物、动作、构图细节…");
    expect(textPrompt).toHaveValue(
      "A lantern glows in rain\nShot type: Medium Shot\nLighting: Warm\nAmbiance: Quiet",
    );
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    fireEvent.change(textPrompt, { target: { value: "Newer local working draft" } });
    firstSave.resolve();

    await waitFor(() => {
      expect(screen.getByDisplayValue("Newer local working draft")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "保存" })).toBeInTheDocument();
  });

  it("保存失败后重试不会覆盖请求期间产生的新编辑", async () => {
    const firstSave = deferred<void>();
    const onUpdatePrompt = vi.fn().mockReturnValue(firstSave.promise);
    renderDetail({ onUpdatePrompt });

    fireEvent.click(screen.getByTestId("image-prompt-shape-toggle"));
    const textPrompt = screen.getByPlaceholderText("描述这一镜的画面：环境、人物、动作、构图细节…");
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    fireEvent.change(textPrompt, { target: { value: "Newer local working draft" } });
    firstSave.reject(new Error("network unavailable"));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(textboxWithValue("Newer local working draft")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重试保存" }));

    expect(textboxWithValue("Newer local working draft")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存" })).toBeInTheDocument();
  });

  it("转换失败时保留原始文本并显示字段错误", () => {
    const onUpdatePrompt = vi.fn();
    renderDetail({ onUpdatePrompt });

    fireEvent.click(screen.getByTestId("image-prompt-shape-toggle"));
    const textPrompt = screen.getByPlaceholderText("描述这一镜的画面：环境、人物、动作、构图细节…");
    fireEvent.change(textPrompt, { target: { value: "free-form prompt with no structured fields" } });
    fireEvent.click(screen.getByTestId("image-prompt-shape-toggle"));

    expect(textboxWithValue("free-form prompt with no structured fields")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveAttribute("data-prompt-error-field", "image_prompt");
    expect(onUpdatePrompt).not.toHaveBeenCalled();
  });
});
