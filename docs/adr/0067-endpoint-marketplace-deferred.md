# ADR 0067：端点市场延后，本轮只补来源元数据

- 状态：Accepted
- 日期：2026-09-25

## 背景

ArcReel v0.31.0 新增了端点市场：市场源登记与刷新、浏览网格、安装与卸载的原子落库、两轴状态（可更新 / 已修改 / 市场不可用）、版本要求校验。

Shotwise 的现状：

- `ENDPOINT_REGISTRY`（`lib/custom_provider/endpoints.py`）是随发行版发布的**静态目录**，由 `server/routers/custom_providers.py::list_endpoint_catalog` 透出，没有远端源、安装记录、更新或卸载。
- 已有更成熟的 workflow 模板市场（`server/services/workflows.py`），含 `submit_template` / `review_template` / `list_marketplace` / `rate_template` / `get_template_upgrade` / `derive_template`，并在升级路径上给出 `compatible` 与 `compatibility_reasons`。

一次端点安装的后果比一次模板安装重得多：端点声明决定出站请求的形态（method / path / headers / body 模板 / 轮询与产物取值），等于可执行的供应链输入。今天 Shotwise 对**用户手填**的端点声明有 `validate_outbound_url` 的形态校验，但市场安装的信任模型是另一回事。

## 决策

**不做**市场安装 / 更新 / 卸载，本轮只补一条纯描述性的来源元数据。

- `EndpointSpec` 增加 `source: str = "builtin"` 与 `version: str | None = None`，并同步到 `EndpointDescriptor` 与前端类型。
- 这两个字段**只回答「这条从哪来」**，不承载安装 / 更新 / 卸载语义，也没有任何执行路径读它。
- 在拿到下面全部前置能力之前，不开放任何从远端源自动安装端点声明的入口。

## 待满足的前置能力

自动安装端点声明需要先定义清楚，缺一不可：

1. **manifest 格式**：一条端点声明的可安装形态、必需的元数据与校验规则。
2. **来源身份**：谁发布的、如何验证（签名或等价的可信渠道），而不是「某个 HTTP 地址返回了 JSON」。
3. **版本与兼容约束**：条目版本、所要求的应用版本或 schema 版本；不满足时拒绝安装而不是尽力而为。
4. **原子更新 + 回滚**：安装 / 更新要么整体生效、要么整体不动，并保留可回滚的上一版本。
5. **用户改动保护**：用户改过的条目不得被静默覆盖——参照 `lib/profile_manifest.py` 的 manifest + sha256 思路（未改 / 用户修改 / 用户删除三态）。
6. **审核与暂停**：参照 workflow 模板市场的 `submit_template` / `review_template` / `suspend` 生命周期，以及 `compatible` / `compatibility_reasons` 的升级校验口径。

供应链风险：没有签名、没有版本约束、没有回滚的自动安装，等于把一个可执行出站请求形态的写入口开放给网络，收益远小于风险。

## 后果

- 目录条目今天可以携带来源与版本描述，为将来的市场机制预留展示位；对现有行为零影响（默认 `builtin` / `None`，无读取者）。
- 市场机制继续缺席：用户想要目录外的端点仍走「手填声明」路径，受 `validate_outbound_url` 约束。
- 若未来要做，本 ADR 的六项前置能力是评审清单；其中任何一项缺失都不应开放自动安装。

## 参考

- `lib/custom_provider/endpoints.py`（`EndpointSpec.source` / `.version`）
- `server/routers/custom_providers.py`（`EndpointDescriptor`）
- `server/services/workflows.py`（`submit_template` / `review_template` / `list_marketplace` / `get_template_upgrade` / `compatible`）
- `lib/profile_manifest.py`（manifest + sha256 的用户改动保护）
- `docs/adr/0068-custom-endpoint-scheme-not-restricted.md`
