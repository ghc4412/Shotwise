export interface OutlineItem {
  chapter?: number;
  title: string;
  summary?: string;
}

export const OUTLINE_CHUNK_MAX_CHARS = 40000;
export const CREATIVE_OUTLINE_FILENAME = "_creative_outline.json";

export interface CreativeOutlineDocument {
  version: 1;
  volumes: Array<{
    id: string;
    title: string;
    chapters: Array<{
      id: string;
      title: string;
      summary: string;
      hook: string;
    }>;
  }>;
}

function newOutlineId(prefix: string): string {
  return prefix + "-" + (globalThis.crypto?.randomUUID?.() ?? (Date.now() + "-" + Math.random().toString(36).slice(2)));
}

function persistedChapterTitle(item: OutlineItem): string {
  if (item.chapter === undefined) return item.title;
  const chapterPrefix = new RegExp(
    "^\\s*(?:第\\s*" + item.chapter + "\\s*[章节回]|(?:chapter|ch\\.?|part)\\s*" + item.chapter + "\\b|0*" + item.chapter + "\\s+)",
    "i",
  );
  return chapterPrefix.test(item.title) ? item.title : "第" + item.chapter + "章 " + item.title;
}

export function buildCreativeOutlineDocument(items: OutlineItem[], volumeTitle: string): CreativeOutlineDocument {
  return {
    version: 1,
    volumes: [
      {
        id: newOutlineId("volume"),
        title: volumeTitle.trim(),
        chapters: items.map((item) => ({
          id: newOutlineId("chapter"),
          title: persistedChapterTitle(item),
          summary: item.summary ?? "",
          hook: "",
        })),
      },
    ],
  };
}

export function parseSavedCreativeOutline(content: string): OutlineItem[] {
  try {
    const parsed: unknown = JSON.parse(content);
    if (!parsed || typeof parsed !== "object") return [];
    const volumes = (parsed as { volumes?: unknown }).volumes;
    if (!Array.isArray(volumes)) return [];

    const items: OutlineItem[] = [];
    for (const volume of volumes) {
      if (!volume || typeof volume !== "object") continue;
      const chapters = (volume as { chapters?: unknown }).chapters;
      if (!Array.isArray(chapters)) continue;
      for (const chapter of chapters) {
        if (!chapter || typeof chapter !== "object") continue;
        const record = chapter as Record<string, unknown>;
        if (typeof record.title !== "string" || !record.title.trim()) continue;
        const titleMatch = record.title.match(CHAPTER_HEADING_PATTERN);
        const chapterNumber = parseChapterNumber(titleMatch?.[1] ?? titleMatch?.[2] ?? titleMatch?.[3]);
        const title = titleMatch?.[4]?.trim() || record.title.trim();
        items.push({
          ...(chapterNumber !== undefined ? { chapter: chapterNumber } : {}),
          title,
          ...(typeof record.summary === "string" && record.summary.trim()
            ? { summary: record.summary.trim() }
            : {}),
        });
      }
    }
    return items;
  } catch {
    return [];
  }
}

const CHAPTER_HEADING_PATTERN =
  /^\s*(?:第\s*([0-9]+|[零〇一二三四五六七八九十百千万两]+)\s*[章节回卷部]|(?:chapter|ch\.?|part)\s*([0-9]+)|([0-9]{3,}))\s*(?:[:：.、-]\s*)?(.*)$/i;
const CHAPTER_HEADING_GLOBAL_PATTERN =
  /^\s*(?:第\s*([0-9]+|[零〇一二三四五六七八九十百千万两]+)\s*[章节回卷部]|(?:chapter|ch\.?|part)\s*([0-9]+)|([0-9]{3,}))\s*(?:[:：.、-]\s*)?(.*)$/gim;

function parseChineseChapterNumber(value: string): number | undefined {
  const digits: Record<string, number> = {
    零: 0,
    〇: 0,
    一: 1,
    二: 2,
    两: 2,
    三: 3,
    四: 4,
    五: 5,
    六: 6,
    七: 7,
    八: 8,
    九: 9,
  };
  const units: Record<string, number> = { 十: 10, 百: 100, 千: 1000, 万: 10000 };
  let total = 0;
  let section = 0;
  let digit = 0;

  for (const character of value) {
    if (character in digits) {
      digit = digits[character];
      continue;
    }
    const unit = units[character];
    if (!unit) return undefined;
    if (unit === 10000) {
      section = (section + digit) * unit;
      total += section;
      section = 0;
    } else {
      section += (digit || 1) * unit;
    }
    digit = 0;
  }

  const result = total + section + digit;
  return result > 0 ? result : undefined;
}

function parseChapterNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isInteger(value) && value > 0) return value;
  if (typeof value !== "string") return undefined;
  const match = value.match(/(?:第\s*)?([0-9]+|[零〇一二三四五六七八九十百千万两]+)/i);
  if (!match) return undefined;
  if (/^\d+$/.test(match[1])) {
    const chapter = Number(match[1]);
    return Number.isInteger(chapter) && chapter > 0 ? chapter : undefined;
  }
  return parseChineseChapterNumber(match[1]);
}

function splitTextByLength(text: string, maxChars: number): string[] {
  const chunks: string[] = [];
  let start = 0;

  while (start < text.length) {
    const hardEnd = Math.min(start + maxChars, text.length);
    if (hardEnd === text.length) {
      const tail = text.slice(start).trim();
      if (tail) chunks.push(tail);
      break;
    }

    const minimumSplit = start + Math.floor(maxChars * 0.5);
    const paragraphBreak = text.lastIndexOf("\n\n", hardEnd - 1);
    const lineBreak = text.lastIndexOf("\n", hardEnd - 1);
    const splitAt =
      paragraphBreak >= minimumSplit
        ? paragraphBreak + 2
        : lineBreak >= minimumSplit
          ? lineBreak + 1
          : hardEnd;
    const chunk = text.slice(start, splitAt).trim();
    if (chunk) chunks.push(chunk);
    start = splitAt;
  }

  return chunks;
}

export function splitSourceIntoChunks(content: string, maxChars = OUTLINE_CHUNK_MAX_CHARS): string[] {
  if (!content.trim()) return [];
  if (maxChars <= 0) throw new Error("maxChars must be positive");

  const headings = [...content.matchAll(CHAPTER_HEADING_GLOBAL_PATTERN)];
  if (headings.length === 0) return splitTextByLength(content, maxChars);

  const sections: string[] = [];
  const firstHeadingIndex = headings[0].index ?? 0;
  if (firstHeadingIndex > 0) sections.push(content.slice(0, firstHeadingIndex));
  for (let index = 0; index < headings.length; index += 1) {
    const start = headings[index].index ?? 0;
    const end = headings[index + 1]?.index ?? content.length;
    sections.push(content.slice(start, end));
  }

  const chunks: string[] = [];
  let current = "";
  for (const section of sections) {
    const normalized = section.trim();
    if (!normalized) continue;

    if (normalized.length > maxChars) {
      if (current) {
        chunks.push(current.trim());
        current = "";
      }
      chunks.push(...splitTextByLength(normalized, maxChars));
      continue;
    }

    if (current && current.length + normalized.length + 2 > maxChars) {
      chunks.push(current.trim());
      current = "";
    }
    current += current ? "\n\n" + normalized : normalized;
  }

  if (current) chunks.push(current.trim());
  return chunks;
}

function normalizeOutlineTitle(value: string): string {
  return value
    .replace(/^\s*(?:第\s*(?:\d+|[零〇一二三四五六七八九十百千万两]+)\s*[章节回卷部]|(?:chapter|ch\.?|part)\s*\d+|0*\d+\s+)\s*[:：.、-]?\s*/i, "")
    .replace(/[：:，,。.!！？?、\s]+$/g, "")
    .trim()
    .toLocaleLowerCase();
}

function stripChapterHeading(value: string, chapter?: number): string {
  const match = value.match(CHAPTER_HEADING_PATTERN);
  if (!match) return value.trim();
  const parsedChapter = parseChapterNumber(match[1] ?? match[2] ?? match[3]);
  if (chapter !== undefined && parsedChapter !== chapter) return value.trim();
  return match[4]?.trim() || (parsedChapter !== undefined ? "第" + parsedChapter + "章" : value.trim());
}

/**
 * Builds the deterministic chapter skeleton from explicit headings in the source.
 * AI extraction enriches this skeleton but cannot remove source chapters.
 */
export function parseSourceChapters(content: string): OutlineItem[] {
  const chapters: OutlineItem[] = [];
  for (const rawLine of content.split(/\r?\n/)) {
    const heading = rawLine.match(CHAPTER_HEADING_PATTERN);
    if (!heading) continue;
    const chapter = parseChapterNumber(heading[1] ?? heading[2] ?? heading[3]);
    if (chapter === undefined) continue;
    const title = heading[4]?.trim() || "第" + chapter + "章";
    chapters.push({ chapter, title });
  }
  return chapters;
}

function compareOutlineItems(left: OutlineItem, right: OutlineItem): number {
  if (left.chapter === undefined && right.chapter === undefined) return 0;
  if (left.chapter === undefined) return 1;
  if (right.chapter === undefined) return -1;
  return left.chapter - right.chapter;
}

/**
 * Merges AI-generated details into the source chapter skeleton, retaining every
 * explicit source heading and appending only AI chapters absent from the source.
 */
export function mergeOutlineWithSourceChapters(
  sourceChapters: OutlineItem[],
  aiItems: OutlineItem[],
): OutlineItem[] {
  const merged = sourceChapters.map((item) => ({ ...item }));
  const matchedSourceIndexes = new Set<number>();
  const unmatchedAi: OutlineItem[] = [];

  for (const aiItem of aiItems) {
    const aiTitle = normalizeOutlineTitle(aiItem.title);
    const chapterCandidates = aiItem.chapter === undefined
      ? []
      : merged.flatMap((sourceItem, index) => sourceItem.chapter === aiItem.chapter ? [{ index, item: sourceItem }] : []);
    const titleCandidates = merged.flatMap((sourceItem, index) => {
      const sourceTitle = normalizeOutlineTitle(sourceItem.title);
      return aiTitle && sourceTitle && (sourceTitle === aiTitle || sourceTitle.includes(aiTitle) || aiTitle.includes(sourceTitle))
        ? [{ index, item: sourceItem }]
        : [];
    });
    const candidates = chapterCandidates.length > 0 ? chapterCandidates : titleCandidates;
    const exactTitle = candidates.find(({ item }) => normalizeOutlineTitle(item.title) === aiTitle);
    const available = candidates.find(({ index }) => !matchedSourceIndexes.has(index));
    const match = exactTitle ?? available ?? candidates[0];

    if (!match) {
      unmatchedAi.push({ ...aiItem });
      continue;
    }

    const sourceItem = merged[match.index];
    const aiTitleWithPrefix = stripChapterHeading(aiItem.title, aiItem.chapter);
    if (aiTitleWithPrefix) sourceItem.title = aiTitleWithPrefix;
    if (aiItem.summary?.trim()) sourceItem.summary = aiItem.summary.trim();
    matchedSourceIndexes.add(match.index);
  }

  return [...merged, ...unmatchedAi].sort(compareOutlineItems);
}

/**
 * Finds the source offset for an extracted outline item.
 * Chapter numbers are the stable key; titles make the fallback useful for
 * prose without explicit numbering and help disambiguate repeated headings.
 */
export function findOutlineItemOffset(content: string, item: OutlineItem): number | undefined {
  if (!content.trim()) return undefined;

  const wantedTitle = normalizeOutlineTitle(item.title);
  let best: { offset: number; score: number } | undefined;
  let offset = 0;

  for (const line of content.split(/(\r?\n)/)) {
    if (/^\r?\n$/.test(line)) {
      offset += line.length;
      continue;
    }

    const heading = line.match(CHAPTER_HEADING_PATTERN);
    const lineTitle = heading?.[4] ? normalizeOutlineTitle(heading[4]) : normalizeOutlineTitle(line);
    const titleMatches = Boolean(wantedTitle && lineTitle && (lineTitle === wantedTitle || lineTitle.includes(wantedTitle)));
    const chapterNumber = parseChapterNumber(heading?.[1] ?? heading?.[2] ?? heading?.[3]);
    const chapterMatches = item.chapter !== undefined && chapterNumber === item.chapter;

    if (chapterMatches || titleMatches) {
      const score = (chapterMatches ? 4 : 0) + (titleMatches ? 2 : 0) + (lineTitle === wantedTitle ? 1 : 0);
      if (!best || score > best.score) best = { offset, score };
    }

    offset += line.length;
  }

  return best?.offset;
}

export function parseOutline(value: string): OutlineItem[] {
  const fence = String.fromCharCode(96).repeat(3);
  const cleaned = value
    .trim()
    .replace(new RegExp("^\\s*" + fence + "(?:json)?\\s*", "i"), "")
    .replace(new RegExp("\\s*" + fence + "\\s*$"), "");
  if (!cleaned) return [];

  try {
    const parsed = JSON.parse(cleaned) as unknown;
    const items = Array.isArray(parsed)
      ? parsed
      : parsed && typeof parsed === "object"
        ? ((parsed as Record<string, unknown>).chapters ?? (parsed as Record<string, unknown>).outline)
        : null;
    if (Array.isArray(items)) {
      const result = items
        .map((item): OutlineItem | null => {
          if (typeof item === "string") return item.trim() ? { title: item.trim() } : null;
          if (!item || typeof item !== "object") return null;
          const record = item as Record<string, unknown>;
          const title = record.title ?? record.name ?? record.chapter_title ?? record.heading;
          if (typeof title !== "string" || !title.trim()) return null;
          const summary = record.summary ?? record.description ?? record.content;
          const chapter = parseChapterNumber(record.chapter ?? record.number ?? record.chapter_number);
          return {
            ...(chapter !== undefined ? { chapter } : {}),
            title: title.trim(),
            ...(typeof summary === "string" && summary.trim() ? { summary: summary.trim() } : {}),
          };
        })
        .filter((item): item is OutlineItem => item !== null);
      if (result.length > 0) return result;
    }
  } catch {
    // The model may return Markdown despite the JSON instruction.
  }

  const result: OutlineItem[] = [];
  let current: OutlineItem | null = null;
  for (const rawLine of value.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const heading = line.match(/^#{1,6}\s+(.+)$/);
    const chapterMatch = line.match(CHAPTER_HEADING_PATTERN);
    const numbered = line.match(/^\d+[、.)]\s*(.+)$/);
    const chapter = chapterMatch
      ? parseChapterNumber(chapterMatch[1] ?? chapterMatch[2] ?? chapterMatch[3])
      : undefined;
    const title = heading?.[1] ?? chapterMatch?.[4] ?? numbered?.[1];
    if (title?.trim()) {
      current = {
        ...(chapter !== undefined ? { chapter } : {}),
        title: title.trim(),
      };
      result.push(current);
    } else if (current && !current.summary && !/^[-*•]/.test(line)) {
      current.summary = line;
    }
  }
  return result;
}

function outlineKey(item: OutlineItem): string {
  return item.chapter !== undefined
    ? "chapter:" + item.chapter
    : "title:" + item.title.replace(/\s+/g, " ").trim().toLocaleLowerCase();
}

export function mergeOutlineItems(groups: OutlineItem[][]): OutlineItem[] {
  const merged: OutlineItem[] = [];
  const indexes = new Map<string, number>();

  for (const group of groups) {
    for (const item of group) {
      const key = outlineKey(item);
      const existingIndex = indexes.get(key);
      if (existingIndex === undefined) {
        indexes.set(key, merged.length);
        merged.push({ ...item });
        continue;
      }

      const existing = merged[existingIndex];
      if (item.summary && item.summary !== existing.summary) {
        existing.summary = existing.summary ? existing.summary + " " + item.summary : item.summary;
      }
    }
  }

  return merged.sort((left, right) => {
    if (left.chapter === undefined && right.chapter === undefined) return 0;
    if (left.chapter === undefined) return 1;
    if (right.chapter === undefined) return -1;
    return left.chapter - right.chapter;
  });
}
