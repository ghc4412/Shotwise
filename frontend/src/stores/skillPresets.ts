/**
 * Skills 工作台的静态预置数据。
 * 文案保留中文默认值，并附带 i18n key，页面接入翻译时可用 key 覆盖默认文案。
 */

export type SkillCategory =
  | "recommended"
  | "professional-film"
  | "commercial-ad"
  | "short-drama"
  | "anime-game"
  | "music-mv"
  | "self-media"
  | "general"
  | "discover";

export type SkillType = "official" | "template" | "community";

export interface SkillCategoryOption {
  id: SkillCategory;
  label: string;
  labelKey: string;
}

export interface SkillPreset {
  id: string;
  title: string;
  titleKey: string;
  description: string;
  descriptionKey: string;
  category: SkillCategory;
  image: string;
  author: string;
  usage: number;
  type: SkillType;
  tags: string[];
}

const PLACEHOLDER_COLORS = ["#172554", "#164e63", "#3f1d5b", "#713f12", "#134e4a", "#3f3f46"] as const;

function stableColorIndex(id: string): number {
  let hash = 0;
  for (const character of id) {
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  }
  return hash % PLACEHOLDER_COLORS.length;
}

/** Returns a deterministic inline SVG placeholder without a network dependency. */
export function skillPlaceholderImage(id: string): string {
  const color = PLACEHOLDER_COLORS[stableColorIndex(id)];
  const safeId = id.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const svg = [
    '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">',
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="', color, '"/><stop offset="1" stop-color="#09090b"/></linearGradient></defs>',
    '<rect width="640" height="360" fill="url(#g)"/>',
    '<circle cx="520" cy="80" r="110" fill="#ffffff" fill-opacity=".08"/>',
    '<circle cx="100" cy="310" r="170" fill="#ffffff" fill-opacity=".05"/>',
    '<text x="40" y="300" fill="#ffffff" fill-opacity=".72" font-family="Arial,sans-serif" font-size="20">', safeId, '</text>',
    '</svg>'
  ].join("");
  return "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(svg);
}

export const SKILL_CATEGORIES: readonly SkillCategoryOption[] = [
  {
    "id": "recommended",
    "label": "推荐",
    "labelKey": "skills.categories.recommended"
  },
  {
    "id": "professional-film",
    "label": "专业影视",
    "labelKey": "skills.categories.professionalFilm"
  },
  {
    "id": "commercial-ad",
    "label": "商业广告",
    "labelKey": "skills.categories.commercialAd"
  },
  {
    "id": "short-drama",
    "label": "短剧爽剧",
    "labelKey": "skills.categories.shortDrama"
  },
  {
    "id": "anime-game",
    "label": "动漫游戏",
    "labelKey": "skills.categories.animeGame"
  },
  {
    "id": "music-mv",
    "label": "音乐MV",
    "labelKey": "skills.categories.musicMv"
  },
  {
    "id": "self-media",
    "label": "自媒体创作",
    "labelKey": "skills.categories.selfMedia"
  },
  {
    "id": "general",
    "label": "通用技能",
    "labelKey": "skills.categories.general"
  },
  {
    "id": "discover",
    "label": "发现",
    "labelKey": "skills.categories.discover"
  }
];

export const PRESET_SKILLS: readonly SkillPreset[] = [
  {
    id: "cinematic-shot-language",
    title: "电影感镜头语言",
    titleKey: "skills.presets.cinematic-shot-language.title",
    description: "把文字场景拆成有节奏的景别、运镜与光影提示，适合快速建立统一的画面气质。",
    descriptionKey: "skills.presets.cinematic-shot-language.description",
    category: "recommended",
    image: "/style-thumbnails/live_cinema.png",
    author: "SHOTWISE 官方",
    usage: 12800,
    type: "official",
    tags: ["镜头","氛围"],
  },
  {
    id: "storyboard-director",
    title: "分镜导演助手",
    titleKey: "skills.presets.storyboard-director.title",
    description: "从剧本段落生成可执行的分镜规划，补齐镜号、景别、动作和转场逻辑。",
    descriptionKey: "skills.presets.storyboard-director.description",
    category: "professional-film",
    image: "/style-thumbnails/live_nolan.png",
    author: "影视创作组",
    usage: 9640,
    type: "official",
    tags: ["分镜","导演"],
  },
  {
    id: "character-continuity",
    title: "角色连续性管家",
    titleKey: "skills.presets.character-continuity.title",
    description: "检查角色外观、服装、道具和情绪在不同镜头之间的连续性，减少生成结果漂移。",
    descriptionKey: "skills.presets.character-continuity.description",
    category: "professional-film",
    image: "/style-thumbnails/live_kdrama.png",
    author: "镜头实验室",
    usage: 7310,
    type: "template",
    tags: ["角色","连续性"],
  },
  {
    id: "brand-hero-film",
    title: "品牌TVC大片",
    titleKey: "skills.presets.brand-hero-film.title",
    description: "将品牌卖点转译成高级、克制且有记忆点的广告片创意与镜头脚本。",
    descriptionKey: "skills.presets.brand-hero-film.description",
    category: "commercial-ad",
    image: "/style-thumbnails/live_zhang_yimou.png",
    author: "广告片工坊",
    usage: 8460,
    type: "official",
    tags: ["品牌","TVC"],
  },
  {
    id: "product-hero-shot",
    title: "产品高光展示",
    titleKey: "skills.presets.product-hero-shot.title",
    description: "突出产品材质、结构和使用场景，生成适合电商与新品发布的视觉展示方案。",
    descriptionKey: "skills.presets.product-hero-shot.description",
    category: "commercial-ad",
    image: "/style-thumbnails/live_premium_drama.png",
    author: "商业视觉社",
    usage: 6890,
    type: "template",
    tags: ["产品","电商"],
  },
  {
    id: "爽剧反转钩子",
    title: "爽剧反转钩子",
    titleKey: "skills.presets.爽剧反转钩子.title",
    description: "强化开场冲突、身份反差与连续反转，让短剧前几秒就建立追更动力。",
    descriptionKey: "skills.presets.爽剧反转钩子.description",
    category: "short-drama",
    image: "/style-thumbnails/live_got.png",
    author: "短剧编剧室",
    usage: 11760,
    type: "community",
    tags: ["短剧","反转"],
  },
  {
    id: "短剧节奏剪辑",
    title: "短剧节奏剪辑",
    titleKey: "skills.presets.短剧节奏剪辑.title",
    description: "为竖屏短剧规划高密度信息点、情绪落点和卡点剪辑节奏，适配连续剧集。",
    descriptionKey: "skills.presets.短剧节奏剪辑.description",
    category: "short-drama",
    image: "/style-thumbnails/live_tarantino.png",
    author: "爆款研究所",
    usage: 10240,
    type: "template",
    tags: ["竖屏","节奏"],
  },
  {
    id: "anime-action-choreography",
    title: "动漫动作分镜",
    titleKey: "skills.presets.anime-action-choreography.title",
    description: "设计夸张有力的动作连贯性、速度线和镜头切换，适合热血动漫与游戏宣传。",
    descriptionKey: "skills.presets.anime-action-choreography.description",
    category: "anime-game",
    image: "/style-thumbnails/anim_arcane.png",
    author: "二次元片场",
    usage: 5740,
    type: "community",
    tags: ["动漫","动作"],
  },
  {
    id: "game-world-builder",
    title: "游戏世界观视觉化",
    titleKey: "skills.presets.game-world-builder.title",
    description: "把世界观设定、阵营关系和关键场景整理成统一的游戏宣传视觉方向。",
    descriptionKey: "skills.presets.game-world-builder.description",
    category: "anime-game",
    image: "/style-thumbnails/anim_cyberpunk.png",
    author: "关卡叙事组",
    usage: 4380,
    type: "template",
    tags: ["游戏","世界观"],
  },
  {
    id: "neon-mv-concept",
    title: "霓虹音乐MV",
    titleKey: "skills.presets.neon-mv-concept.title",
    description: "围绕歌曲情绪构建霓虹、舞台与城市意象，输出具有节拍感的MV画面概念。",
    descriptionKey: "skills.presets.neon-mv-concept.description",
    category: "music-mv",
    image: "/style-thumbnails/live_cyberpunk.png",
    author: "MV视觉厂牌",
    usage: 6230,
    type: "official",
    tags: ["MV","霓虹"],
  },
  {
    id: "live-performance-mv",
    title: "现场演出MV",
    titleKey: "skills.presets.live-performance-mv.title",
    description: "将演唱、灯光、观众和舞台调度组织成富有现场张力的音乐视频镜头方案。",
    descriptionKey: "skills.presets.live-performance-mv.description",
    category: "music-mv",
    image: "/style-thumbnails/live_shaw.png",
    author: "现场影像社",
    usage: 3910,
    type: "community",
    tags: ["演出","舞台"],
  },
  {
    id: "vlog-opening-hook",
    title: "Vlog开场钩子",
    titleKey: "skills.presets.vlog-opening-hook.title",
    description: "为旅行、美食和生活记录设计自然不尴尬的开场，让观众迅速理解视频看点。",
    descriptionKey: "skills.presets.vlog-opening-hook.description",
    category: "self-media",
    image: "/style-thumbnails/live_anderson.png",
    author: "创作者工具箱",
    usage: 8990,
    type: "template",
    tags: ["Vlog","开场"],
  },
  {
    id: "knowledge-short-script",
    title: "知识短视频脚本",
    titleKey: "skills.presets.knowledge-short-script.title",
    description: "把复杂主题拆成清晰易懂的短视频结构，兼顾信息密度、口语表达和记忆点。",
    descriptionKey: "skills.presets.knowledge-short-script.description",
    category: "self-media",
    image: "/style-thumbnails/live_wong.png",
    author: "内容增长组",
    usage: 7560,
    type: "official",
    tags: ["知识","脚本"],
  },
  {
    id: "prompt-polisher",
    title: "提示词润色器",
    titleKey: "skills.presets.prompt-polisher.title",
    description: "补足主体、环境、风格和镜头约束，让模糊想法变成更稳定的生成提示词。",
    descriptionKey: "skills.presets.prompt-polisher.description",
    category: "general",
    image: "/style-thumbnails/live_lynch.png",
    author: "SHOTWISE 官方",
    usage: 14500,
    type: "official",
    tags: ["提示词","优化"],
  },
  {
    id: "story-idea-spark",
    title: "故事灵感火花",
    titleKey: "skills.presets.story-idea-spark.title",
    description: "从人物目标、冲突和场景限制出发，快速获得可继续发展的故事创意。",
    descriptionKey: "skills.presets.story-idea-spark.description",
    category: "general",
    image: "/style-thumbnails/live_ancient_xianxia.png",
    author: "灵感便利店",
    usage: 5320,
    type: "community",
    tags: ["创意","故事"],
  },
  {
    id: "trending-skill-discovery",
    title: "热门Skill发现",
    titleKey: "skills.presets.trending-skill-discovery.title",
    description: "根据当前创作方向推荐值得尝试的技能组合，帮助你找到下一种表达方式。",
    descriptionKey: "skills.presets.trending-skill-discovery.description",
    category: "discover",
    image: "/style-thumbnails/anim_90s_retro.png",
    author: "SHOTWISE 社区",
    usage: 2840,
    type: "community",
    tags: ["发现","推荐"],
  }
];

export interface SkillFilters {
  category?: SkillCategory | "all";
  query?: string;
  type?: SkillType | "all";
}

export function filterSkills(
  skills: readonly SkillPreset[] = PRESET_SKILLS,
  filters: SkillFilters = {},
): SkillPreset[] {
  const query = filters.query?.trim().toLocaleLowerCase();

  return skills.filter((skill) => {
    const matchesCategory = !filters.category || filters.category === "all" || skill.category === filters.category;
    const matchesType = !filters.type || filters.type === "all" || skill.type === filters.type;
    const searchableText = [skill.title, skill.description, skill.author, ...skill.tags].join(" ").toLocaleLowerCase();
    const matchesQuery = !query || searchableText.includes(query);
    return matchesCategory && matchesType && matchesQuery;
  });
}
