"""只读推导官方剧本里各条目的「待编写」(pending authoring) 状态。

ArcReel 的 ``pending_authoring`` 是持久化在条目上的布尔标记：内容变动时置位、视觉层编写后
清除，并接进全部写路径（内容物化、时间线编辑、晋升、提示词编写）才保持。Shotwise 的官方剧本
是内容单一真相，内容与视觉层经同一批 PATCH 路由写入，且没有「上次编写时的正文」基线快照，
故本模块**不引入持久化标记**，只做读时纯计算：

    一个条目的视觉层（image_prompt / video_prompt）是与当前正文配套的，当正文自上次编写后
    变了，该条目的视觉层即与正文脱钩、须重新生成提示词。

正文的「当前值」取自该变体的 step1 结构化中间态（``drafts/episode_N/step1_*.json``），因为
它是本流程里唯一一份与视觉编写分离的正文契约；官方剧本侧的同名字段是合并时的透传副本。两侧按
条目 id（scene_id / segment_id / unit_id）对齐，只比对 step1 定稿、step2 不重写的字段
（内容投影）：

- drama：场景除视觉层外的字段；``scene_description`` 是 step1-only、合并时被剔除，不参与。
- narration：片段除视觉层外的全部字段。
- reference_video：unit 的 ``duration_seconds`` 与 ``references``；``shots[*].text`` 由 step2
  视觉展开改写、``source_text`` 是 step1-only，两者都不参与。

该推导对「step1 侧改动」（重拆分、编辑中间态、晋升）是权威的；对「直接在官方脚本上改正文」
只能给出提示——那种改动没有留下基线，本模块无法区分「改了正文且同步改了提示词」与「只改了
正文」。要精确覆盖后者需要把「上次编写时的正文指纹」持久化到条目上，见
``docs/adr/0068-pending-authoring-read-only-projection.md`` 记录的范围与后续路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from lib import script_review
from lib.episode_paths import episode_script_relpath
from lib.json_io import load_json_or_none
from lib.project_manager import find_episode

#: 条目的视觉层字段：本模块判定「已编写」所依据的字段，不参与内容投影比对。
VISUAL_FIELDS = frozenset({"image_prompt", "video_prompt"})

#: 待编写原因。``missing_visual``：step1 有该条目、官方剧本没有（还没编写过）；``stale_visual``：
#: 两侧同 id 但内容投影不一致（剧本里的视觉层对应旧正文）；``orphan_item``：剧本有、step1 没有
#: （条目已从内容契约移除，剧本里的那份视觉层已无正文可依据）。
PendingReason = Literal["missing_visual", "stale_visual", "orphan_item"]


@dataclass(frozen=True)
class _ModeSpec:
    """某变体的条目定位契约：两侧列表键、id 字段、不参与内容投影的字段。"""

    step1_key: str
    script_key: str
    id_field: str
    #: step1-only（合并时被剔除）或由 step2 重写的字段，两侧取值本就不同、不构成「正文变了」。
    ignored_fields: frozenset[str]


_MODES: dict[str, _ModeSpec] = {
    "drama": _ModeSpec("scenes", "scenes", "scene_id", frozenset({"scene_description"})),
    "narration": _ModeSpec("segments", "segments", "segment_id", frozenset()),
    # shots 正文由 step2 视觉展开改写（两侧必然不同）、source_text 落地时被剔除，
    # 剩下的 duration_seconds / references 才是 step1 定稿、step2 不动的契约。
    "reference_video": _ModeSpec("units", "video_units", "unit_id", frozenset({"shots", "source_text"})),
}


@dataclass(frozen=True)
class PendingItem:
    """一个待编写条目：``item_id`` 与判定原因。"""

    item_id: str
    reason: PendingReason

    def to_dict(self) -> dict[str, str]:
        return {"item_id": self.item_id, "reason": self.reason}


@dataclass(frozen=True)
class PendingAuthoringReport:
    """某集的待编写报告。

    ``applicable`` 为 False 时该集不走结构化 step1（如 ad），``kind`` 为 None、``items`` 为空。
    ``script_present`` 为 False 时官方剧本尚未产出，此时不做逐条比对、``items`` 为空——「还没
    生成过剧本」与「剧本里的视觉层过期」是两件事，前者不该被报成一整集的待编写。
    """

    applicable: bool
    kind: script_review.Step1Kind | None
    script_present: bool
    items: tuple[PendingItem, ...]

    @property
    def has_pending(self) -> bool:
        return bool(self.items)

    @property
    def item_ids(self) -> tuple[str, ...]:
        return tuple(item.item_id for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "applicable": self.applicable,
            "kind": self.kind,
            "script_present": self.script_present,
            "has_pending": self.has_pending,
            "items": [item.to_dict() for item in self.items],
        }


def _not_applicable() -> PendingAuthoringReport:
    return PendingAuthoringReport(applicable=False, kind=None, script_present=False, items=())


def _item_list(payload: object, key: str) -> list[dict[str, Any]] | None:
    """取列表键下的对象条目；**无从比对**时返回 None，列表在场时返回其中的对象条目。

    顶层非对象、键缺失、键不是列表（脏数据 / 损坏剧本）都返回 None，而不是空列表：空列表
    会被上层读成「另一侧一个条目都没有」，把损坏剧本报成整集孤儿，或把缺失基线报成整集待
    编写。元素非对象一律跳过——这是只读提示，单个脏条目不值得让整条路径 fail-loud（真正的
    结构约束由 step1 / 剧本各自的校验器负责，走到这里的判定是校验之后的展示层）。
    """
    if not isinstance(payload, dict):
        return None
    raw = payload.get(key)
    if not isinstance(raw, list):
        return None
    return [item for item in raw if isinstance(item, dict)]


def _index_by_id(items: list[dict[str, Any]], id_field: str) -> dict[str, dict[str, Any]]:
    """按 id 建索引，跳过 id 缺失 / 非字符串 / 空的条目；重复 id 保留首个。"""
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        item_id = item.get(id_field)
        if isinstance(item_id, str) and item_id and item_id not in indexed:
            indexed[item_id] = item
    return indexed


def _content_projection(step1_item: dict[str, Any], ignored: frozenset[str]) -> dict[str, Any]:
    """内容投影：step1 条目的非视觉、非豁免字段。

    **以 step1 声明过的键为契约**（而非两侧键的并集）：官方剧本条目带的 ``note`` /
    ``transition_to_next`` / ``generated_assets`` 是 step1 没有的 UI / 运行时字段，取并集会把
    它们算成差异、让每个条目恒判待编写。视觉层字段同样剔除——它们正是「是否已编写」的客体，
    不是正文。
    """
    return {key: value for key, value in step1_item.items() if key not in VISUAL_FIELDS and key not in ignored}


def _same_content(step1_item: dict[str, Any], script_item: dict[str, Any], ignored: frozenset[str]) -> bool:
    """两侧内容投影是否一致：对 step1 声明的键逐一取值，规范化后比对。

    用 step1 的键在剧本条目上取值：剧本缺某个 step1 声明过的字段时取到 None、与 step1 的实值
    不等，判为不一致而非静默通过。规范化复用 ``content_fingerprint_of_data``（键序 / 空白重排
    不改判定、语义变更才改）。
    """
    projection = _content_projection(step1_item, ignored)
    counterpart = {key: script_item.get(key) for key in projection}
    return script_review.content_fingerprint_of_data(projection) == script_review.content_fingerprint_of_data(
        counterpart
    )


def _compare(
    step1_items: list[dict[str, Any]],
    script_items: list[dict[str, Any]],
    spec: _ModeSpec,
) -> tuple[PendingItem, ...]:
    """按 id 对齐两侧条目，产出待编写列表。

    结果按 step1 顺序排列（剧本侧的孤儿条目随后），使同一份输入的输出稳定、便于前端逐条渲染。
    """
    step1_by_id = _index_by_id(step1_items, spec.id_field)
    script_by_id = _index_by_id(script_items, spec.id_field)

    pending: list[PendingItem] = []
    for step1_item in step1_items:
        item_id = step1_item.get(spec.id_field)
        if not isinstance(item_id, str) or not item_id:
            continue
        script_item = script_by_id.get(item_id)
        if script_item is None:
            pending.append(PendingItem(item_id, "missing_visual"))
        elif not _same_content(step1_item, script_item, spec.ignored_fields):
            pending.append(PendingItem(item_id, "stale_visual"))
    for script_item in script_items:
        item_id = script_item.get(spec.id_field)
        if isinstance(item_id, str) and item_id and item_id not in step1_by_id:
            pending.append(PendingItem(item_id, "orphan_item"))
    return tuple(pending)


def pending_authoring_report(project_path: Path, project: dict[str, Any], episode: int) -> PendingAuthoringReport:
    """该集官方剧本的待编写报告（读时纯计算，不落盘、不改任何状态）。

    step1 文件缺失 / 损坏、或官方剧本不存在时退化为空列表（``script_present`` 如实反映剧本在
    不在场）。episode 条目缺失时按默认剧本路径 ``scripts/episode_N.json`` 兜底，与
    ``script_review.step2_generated`` 同一口径。
    """
    kind = script_review.step1_kind(project)
    if kind is None:
        return _not_applicable()
    spec = _MODES[kind]

    step1_path = script_review.step1_path(project_path, project, episode)
    step1_payload = load_json_or_none(step1_path) if step1_path is not None else None

    entry = find_episode(project, episode) or {}
    script_file = entry.get("script_file") or episode_script_relpath(episode)
    script_present = False
    script_payload: dict[str, Any] | None = None
    if isinstance(script_file, str) and script_file:
        resolved = project_path / script_file
        if resolved.is_file():
            script_present = True
            script_payload = load_json_or_none(resolved)

    if not script_present:
        return PendingAuthoringReport(applicable=True, kind=kind, script_present=False, items=())

    step1_items = _item_list(step1_payload, spec.step1_key)
    script_items = _item_list(script_payload, spec.script_key)
    if step1_items is None or script_items is None:
        # 一侧没有可比对的条目表（step1 缺失 / 损坏，或剧本列表键脏）：没有基线就不做判定，
        # 既不报整集待编写、也不报整集孤儿。
        return PendingAuthoringReport(applicable=True, kind=kind, script_present=True, items=())

    items = _compare(step1_items, script_items, spec)
    return PendingAuthoringReport(applicable=True, kind=kind, script_present=True, items=items)
