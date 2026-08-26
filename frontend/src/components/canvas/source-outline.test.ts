import { describe, expect, it } from "vitest";
import {
  buildCreativeOutlineDocument,
  mergeOutlineItems,
  parseOutline,
  parseSavedCreativeOutline,
  splitSourceIntoChunks,
} from "./source-outline";

describe("source outline extraction helpers", () => {
  it("splits long sources at chapter boundaries without exceeding the batch limit", () => {
    const source = [
      "作品简介\n\n",
      "第1章 开始\n" + "甲".repeat(24),
      "\n\n第2章 转折\n" + "乙".repeat(24),
      "\n\n第3章 结局\n" + "丙".repeat(24),
    ].join("");

    const chunks = splitSourceIntoChunks(source, 40);

    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks.every((chunk) => chunk.length <= 40)).toBe(true);
    expect(chunks.join("\n\n")).toContain("第1章 开始");
    expect(chunks.join("\n\n")).toContain("第3章 结局");
  });

  it("parses chapter numbers from JSON output", () => {
    expect(parseOutline('[{"chapter":51,"title":"雨夜","summary":"冲突升级"}]')).toEqual([
      { chapter: 51, title: "雨夜", summary: "冲突升级" },
    ]);
  });

  it("merges repeated chapters from adjacent batches and sorts by chapter number", () => {
    const merged = mergeOutlineItems([
      [{ chapter: 2, title: "转折", summary: "发现线索" }],
      [
        { chapter: 1, title: "开始", summary: "人物登场" },
        { chapter: 2, title: "转折", summary: "决定追查" },
      ],
    ]);

    expect(merged).toEqual([
      { chapter: 1, title: "开始", summary: "人物登场" },
      { chapter: 2, title: "转折", summary: "发现线索 决定追查" },
    ]);
  });

  it("builds the persistent detailed-outline document and keeps chapter numbers", () => {
    const document = buildCreativeOutlineDocument(
      [{ chapter: 51, title: "雨夜", summary: "冲突升级" }],
      "source.txt",
    );

    expect(document.version).toBe(1);
    expect(document.volumes).toHaveLength(1);
    expect(document.volumes[0].title).toBe("source.txt");
    expect(document.volumes[0].chapters).toEqual([
      expect.objectContaining({ title: "第51章 雨夜", summary: "冲突升级", hook: "" }),
    ]);
  });

  it("restores chapters from the persisted detailed-outline document", () => {
    const saved = buildCreativeOutlineDocument(
      [
        { chapter: 51, title: "雨夜", summary: "冲突升级" },
        { chapter: 52, title: "追踪", summary: "发现线索" },
      ],
      "source.txt",
    );

    expect(parseSavedCreativeOutline(JSON.stringify(saved))).toEqual([
      { chapter: 51, title: "雨夜", summary: "冲突升级" },
      { chapter: 52, title: "追踪", summary: "发现线索" },
    ]);
  });
});
