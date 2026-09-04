import type { ImagePrompt, Utterance, VideoPrompt } from "@/types";

export interface PromptConversionSuccess<T> {
  value: T;
  error: null;
}

export interface PromptConversionFailure {
  value: null;
  error: "invalid_shape";
}

export type PromptConversionResult<T> = PromptConversionSuccess<T> | PromptConversionFailure;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * 严格守卫：单条 utterance 必须含 kind ∈ {dialogue, voiceover}、text 字符串，且满足 kind ⇄ speaker——
 * dialogue 带非空 speaker、voiceover 的 speaker 为 null/缺省。drama 字段迁移后由剧本视图据此安全
 * 收窄发声条目，避免访问 undefined 字段崩溃。
 */
export function isUtterance(value: unknown): value is Utterance {
  if (!isRecord(value)) return false;
  if (value.kind !== "dialogue" && value.kind !== "voiceover") return false;
  if (typeof value.text !== "string") return false;
  const speaker = value.speaker;
  if (value.kind === "dialogue") {
    return typeof speaker === "string" && speaker.trim().length > 0;
  }
  return speaker === null || speaker === undefined;
}

/** 守卫：整段 utterances 必须是数组且每条都是良构 utterance（缺省/非数组判否）。 */
export function isUtteranceArray(value: unknown): value is Utterance[] {
  return Array.isArray(value) && value.every(isUtterance);
}

/**
 * 严格守卫：完整 ImagePrompt 必须含 scene + composition.{shot_type, lighting, ambiance}。
 * 部分形态（仅 scene 或 composition 缺字段）会落到 string fallback，避免结构化编辑器渲染时
 * 访问 undefined 字段崩溃。
 */
export function isStructuredImagePrompt(value: unknown): value is ImagePrompt {
  if (!isRecord(value) || typeof value.scene !== "string") return false;
  const composition = value.composition;
  if (!isRecord(composition)) return false;
  return (
    typeof composition.shot_type === "string" &&
    typeof composition.lighting === "string" &&
    typeof composition.ambiance === "string"
  );
}

/**
 * 严格守卫：VideoPrompt 必须含 action + camera_motion + ambiance_audio；dialogue 可省略，
 * 但若提供必须是 {speaker, line} 数组。
 */
export function isStructuredVideoPrompt(value: unknown): value is VideoPrompt {
  if (
    !isRecord(value) ||
    typeof value.action !== "string" ||
    typeof value.camera_motion !== "string" ||
    typeof value.ambiance_audio !== "string"
  ) {
    return false;
  }
  const dialogue = value.dialogue;
  if (dialogue === undefined) return true;
  if (!Array.isArray(dialogue)) return false;
  return dialogue.every(
    (item) =>
      isRecord(item) &&
      typeof item.speaker === "string" &&
      typeof item.line === "string",
  );
}

/** Convert the structured editor model to the stable plain-text representation. */
export function imagePromptToText(prompt: ImagePrompt): string {
  return [
    prompt.scene,
    `Shot type: ${prompt.composition.shot_type}`,
    `Lighting: ${prompt.composition.lighting}`,
    `Ambiance: ${prompt.composition.ambiance}`,
  ].join("\n");
}

/** Convert the structured editor model to the stable plain-text representation. */
export function videoPromptToText(prompt: VideoPrompt): string {
  const lines = [
    prompt.action,
    `Camera motion: ${prompt.camera_motion}`,
    `Ambiance audio: ${prompt.ambiance_audio}`,
  ];
  if (prompt.dialogue?.length) {
    lines.push(...prompt.dialogue.map(({ speaker, line }) => `${speaker}: ${line}`));
  }
  return lines.join("\n");
}

/** Parse only text produced by imagePromptToText; arbitrary text stays untouched on failure. */
export function textToImagePrompt(value: string): PromptConversionResult<ImagePrompt> {
  const lines = value.split(/\r?\n/);
  const scene = lines[0]?.trim();
  const shotType = lines[1]?.match(/^Shot type:\s*(.+)$/i)?.[1]?.trim();
  const lighting = lines[2]?.match(/^Lighting:\s*(.+)$/i)?.[1]?.trim();
  const ambiance = lines[3]?.match(/^Ambiance:\s*(.+)$/i)?.[1]?.trim();
  if (lines.length !== 4 || !scene || !shotType || !lighting || !ambiance) {
    return { value: null, error: "invalid_shape" };
  }
  return {
    value: {
      scene,
      composition: {
        shot_type: shotType as ImagePrompt["composition"]["shot_type"],
        lighting,
        ambiance,
      },
    },
    error: null,
  };
}

/** Parse only text produced by videoPromptToText; arbitrary text stays untouched on failure. */
export function textToVideoPrompt(value: string): PromptConversionResult<VideoPrompt> {
  const lines = value.split(/\r?\n/);
  const action = lines[0]?.trim();
  const cameraMotion = lines[1]?.match(/^Camera motion:\s*(.+)$/i)?.[1]?.trim();
  const ambianceAudio = lines[2]?.match(/^Ambiance audio:\s*(.+)$/i)?.[1]?.trim();
  if (!action || !cameraMotion || !ambianceAudio) return { value: null, error: "invalid_shape" };
  const dialogue = lines.slice(3)
    .map((line) => {
      const separator = line.indexOf(":");
      return separator > 0
        ? { speaker: line.slice(0, separator).trim(), line: line.slice(separator + 1).trim() }
        : null;
    })
    .filter((item): item is { speaker: string; line: string } => Boolean(item?.speaker && item.line));
  if (dialogue.length !== lines.slice(3).length) return { value: null, error: "invalid_shape" };
  return {
    value: { action, camera_motion: cameraMotion as VideoPrompt["camera_motion"], ambiance_audio: ambianceAudio, dialogue },
    error: null,
  };
}

/**
 * 浅合并 patch 进 base：嵌套对象（如 ImagePrompt.composition）做一层浅 merge，
 * 数组与基础值直接替换。
 */
export function mergePromptPatch<T extends Record<string, unknown>>(
  base: T,
  patch: Record<string, unknown>,
): T {
  const merged: Record<string, unknown> = { ...base };
  for (const [k, v] of Object.entries(patch)) {
    const baseVal = base[k];
    if (
      isRecord(v) &&
      isRecord(baseVal) &&
      !Array.isArray(v) &&
      !Array.isArray(baseVal)
    ) {
      merged[k] = { ...baseVal, ...v };
    } else {
      merged[k] = v;
    }
  }
  return merged as T;
}
