import { describe, expect, it } from "vitest";
import {
  buildCreativeOutlineDocument,
  findOutlineItemOffset,
  mergeOutlineItems,
  mergeOutlineWithSourceChapters,
  parseOutline,
  parseSavedCreativeOutline,
  parseSourceChapters,
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

  it("keeps every explicit source chapter when AI skips middle chapters", () => {
    const sourceChapters = parseSourceChapters(
      "第1章 开始\n甲\n\n第2章 转折\n乙\n\n第3章 结局\n丙\n\n第14章 新篇章\n丁",
    );

    expect(
      mergeOutlineWithSourceChapters(sourceChapters, [
        { chapter: 1, title: "开始", summary: "主角登场" },
        { chapter: 14, title: "新篇章", summary: "新的冲突" },
      ]),
    ).toEqual([
      { chapter: 1, title: "开始", summary: "主角登场" },
      { chapter: 2, title: "转折" },
      { chapter: 3, title: "结局" },
      { chapter: 14, title: "新篇章", summary: "新的冲突" },
    ]);
  });

  it("keeps the exact source title when AI rewrites a chapter title", () => {
    const sourceChapters = parseSourceChapters("第242章 思想落后的张羽（求月票）\n本章正文");

    expect(
      mergeOutlineWithSourceChapters(sourceChapters, [
        { chapter: 242, title: "有钱的张羽", summary: "张羽遇到新的冲突" },
      ]),
    ).toEqual([
      { chapter: 242, title: "思想落后的张羽（求月票）", summary: "张羽遇到新的冲突" },
    ]);
  });

  it("normalizes a saved AI outline against the current source headings", () => {
    const sourceChapters = parseSourceChapters("第242章 思想落后的张羽（求月票）\n本章正文");
    const savedItems = parseSavedCreativeOutline(JSON.stringify({
      version: 1,
      volumes: [{
        id: "volume-1",
        title: "source.txt",
        chapters: [{ id: "chapter-242", title: "第242章 有钱的张羽", summary: "已保存摘要", hook: "" }],
      }],
    }));

    expect(mergeOutlineWithSourceChapters(sourceChapters, savedItems)).toEqual([
      { chapter: 242, title: "思想落后的张羽（求月票）", summary: "已保存摘要" },
    ]);
  });

  it("does not add hallucinated numbered chapters when source headings exist", () => {
    const sourceChapters = parseSourceChapters("第1章 开始\n甲\n\n第2章 转折\n乙");

    expect(
      mergeOutlineWithSourceChapters(sourceChapters, [
        { chapter: 1, title: "开始", summary: "人物登场" },
        { chapter: 99, title: "不存在的章节", summary: "模型臆测" },
        { title: "一层巨变之始", summary: "模型改写的标题" },
      ]),
    ).toEqual([
      { chapter: 1, title: "开始", summary: "人物登场" },
      { chapter: 2, title: "转折" },
    ]);
  });

  it("finds the source offset by chapter number and falls back to the title", () => {
    const source = "引子\n\n第2章 转折\n发现线索\n\n雨夜\n冲突升级";

    expect(findOutlineItemOffset(source, { chapter: 2, title: "转折" })).toBe(source.indexOf("第2章"));
    expect(findOutlineItemOffset(source, { title: "雨夜" })).toBe(source.indexOf("雨夜"));
    expect(findOutlineItemOffset(source, { chapter: 9, title: "不存在" })).toBeUndefined();
  });

  it("parses Chinese-numbered source chapters and locates them", () => {
    const source = "序幕\n\n第十四章 极度低温\n外界风云\n\n第十五章 新的开始\n新的线索";

    expect(parseSourceChapters(source)).toEqual([
      { chapter: 14, title: "极度低温" },
      { chapter: 15, title: "新的开始" },
    ]);
    expect(findOutlineItemOffset(source, { chapter: 14, title: "极度低温" })).toBe(source.indexOf("第十四章"));
  });

  it("does not treat numeric prose lines as chapters when explicit headings exist", () => {
    const source = [
      "第242章 思想落后的张羽（求月票）",
      "张羽迎来新的冲突。",
      "250万?!",
      "285 诞生地",
      "350 肉体第三关",
    ].join("\n");

    expect(parseSourceChapters(source)).toEqual([
      { chapter: 242, title: "思想落后的张羽（求月票）" },
    ]);
    expect(splitSourceIntoChunks(source, 20_000)).toEqual([source]);
  });

  it("parses zero-padded numeric headings and locates chapter one without matching chapter seventy", () => {
    const source = "楔子\n正文\n\n001 东归酒肆\n本章正文内容\n东归酒肆再次出现\n\n070 初入学堂\n后续正文内容";

    expect(parseSourceChapters(source)).toEqual([
      { chapter: 1, title: "东归酒肆" },
      { chapter: 70, title: "初入学堂" },
    ]);
    expect(findOutlineItemOffset(source, { chapter: 1, title: "东归酒肆" })).toBe(source.indexOf("001 东归酒肆"));
    expect(findOutlineItemOffset(source, { chapter: 70, title: "初入学堂" })).toBe(source.indexOf("070 初入学堂"));
  });

  it("restores zero-padded numeric headings from saved outlines", () => {
    const saved = {
      version: 1,
      volumes: [{
        id: "volume-1",
        title: "source.txt",
        chapters: [
          { id: "chapter-1", title: "001 东归酒肆", summary: "开篇", hook: "" },
          { id: "chapter-70", title: "070 初入学堂", summary: "入学", hook: "" },
        ],
      }],
    };

    expect(parseSavedCreativeOutline(JSON.stringify(saved))).toEqual([
      { chapter: 1, title: "东归酒肆", summary: "开篇" },
      { chapter: 70, title: "初入学堂", summary: "入学" },
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
