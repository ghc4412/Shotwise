<h1 align="center">
  <br>
  <picture>
    <source media="(prefers-color-scheme: light)" srcset="frontend/public/shotwise-mark.svg">
    <source media="(prefers-color-scheme: dark)" srcset="frontend/public/shotwise-mark.svg">
    <img src="frontend/public/shotwise-mark.svg" alt="SHOTWISE Logo" width="128" style="border-radius: 16px;">
  </picture>
  <br>
  SHOTWISE
  <br>
</h1>

<p align="center">
  <strong>An open-source, self-hosted AI video production workspace</strong>
  <br>
  Turn novels, finished screenplays, or product assets into consistent, controllable, cost-aware videos that remain editable.
</p>

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/lang-中文-red?style=flat-square" alt="中文"></a>
  <a href="README.en.md"><img src="https://img.shields.io/badge/lang-English-blue?style=flat-square" alt="English"></a>
</p>

<p align="center">
  <a href="#quick-start"><img src="https://img.shields.io/badge/Quick_Start-blue?style=for-the-badge" alt="Quick Start"></a>
  <a href="https://github.com/ghc4412/Shotwise/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-green?style=for-the-badge" alt="License"></a>
  <a href="https://github.com/ghc4412/Shotwise"><img src="https://img.shields.io/github/stars/ghc4412/Shotwise?style=for-the-badge" alt="Stars"></a>
  <a href="https://github.com/ghc4412/Shotwise/pkgs/container/SHOTWISE"><img src="https://img.shields.io/badge/Docker-ghcr.io-blue?style=for-the-badge&logo=docker" alt="Docker"></a>
  <a href="https://github.com/ghc4412/Shotwise/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/ghc4412/Shotwise/test.yml?style=for-the-badge&label=Tests" alt="Tests"></a>
  <a href="https://codecov.io/gh/ghc4412/Shotwise"><img src="https://img.shields.io/codecov/c/github/ghc4412/Shotwise?style=for-the-badge&label=Coverage" alt="Coverage"></a>
  <a href="https://github.com/ghc4412/Shotwise/security/code-scanning"><img src="https://img.shields.io/github/actions/workflow/status/ghc4412/Shotwise/codeql.yml?style=for-the-badge&label=CodeQL" alt="CodeQL"></a>
  <a href="https://github.com/ghc4412/Shotwise/releases/latest"><img src="https://img.shields.io/github/v/release/ghc4412/Shotwise?style=for-the-badge&label=Release" alt="Release"></a>
</p>

<p align="center">
  <a href="#quick-start"><strong>Quick Start</strong></a>
  ·
  <a href="docs/getting-started.md">Getting Started</a>
  ·
  <a href="docs/README.md">Documentation</a>
</p>

<p align="center">
  <img src="docs/assets/hero-screenshot.png" alt="SHOTWISE Workspace" width="800">
</p>

> ArcReel is not a thin prompt wrapper. It organizes content analysis, screenplay structuring, character and scene assets, storyboards, media generation tasks, cost tracking, version history, and export into an inspectable and resumable production pipeline.

## Interface and Themes

Shotwise uses a production-focused workspace layout across the project lobby, studio workspace, and login page. Use the sun/moon button in the top-right utility area to switch between light and dark mode. The preference is stored in the current browser and restored after refresh.

The browser tab, PWA manifest, login page, and project lobby share the `shotwise-mark.svg` brand mark.

## Core Features

<table>
<tr>
<td width="33%" valign="top">

### 🎭 AI drama and novel adaptation

Extract characters, locations, and plot structure from long-form fiction or finished screenplays, then produce visually consistent episodes.

</td>
<td width="33%" valign="top">

### 🎙️ Narrated short videos

Split content by narration rhythm, generate storyboards and voice-over tracks, and export a vertical video or editable CapCut draft.

</td>
<td width="33%" valign="top">

### 🛍️ Ads and product shorts

Upload multiple product images, build stable product references, and generate product-anchored promotional shots for a target duration.

</td>
</tr>
</table>

## From source to final video

```mermaid
flowchart LR
    A["Novel / Screenplay / Product Assets"] --> B["Content Analysis & Planning"]
    B --> C["Character / Scene / Prop Assets"]
    C --> D["Episode Plan & Structured Script"]
    D --> E["Storyboard / Grid Images"]
    E --> F["Video Clips / Voice-over"]
    F --> G["Final Composition"]
    F --> H["CapCut Draft Export"]
```

Every stage can be orchestrated by the AI assistant while remaining reviewable and replaceable in the workspace. See [Workflows and Modes](docs/workflows.md) for guidance.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Start with at least 2 GB of available memory
- A complete workflow requires:
  - model credentials for the ArcReel AI assistant
  - working text, image, and video generation capabilities, provided by one multimodal provider or a combination of providers
  - optional TTS capability when narration is needed
- The default setup uses remote model APIs and normally does not require a local GPU; local model deployments have their own requirements

### Default deployment: SQLite

```bash
git clone https://github.com/ghc4412/Shotwise.git
cd SHOTWISE/deploy
cp .env.example .env
docker compose up -d
```

Verify the service:

```bash
cd SHOTWISE/deploy/production
cp .env.example .env    # Set POSTGRES_PASSWORD
docker compose up -d
```

See [Deployment and Operations](docs/deployment.md) for upgrades, backups, and reverse proxies. See the [Security Policy](SECURITY.md) for supported deployments and vulnerability reporting.

1. **SHOTWISE Agent** — Configure provider credentials that power the AI assistant. Supports Anthropic and compatible providers, with custom Base URL and model
2. **AI Image/Video/Text Generation** — Configure at least one provider's API Key (Gemini / Volcengine Ark / Grok / OpenAI / Vidu / DashScope / MiniMax / Kling), or add a custom provider

### 🤖 Agent-driven, resumable workflow

ArcReel uses an orchestration Skill and focused Subagents built on the Claude Agent SDK. The main Agent detects the current project stage and delegates character extraction, episode planning, screenplay normalization, and asset generation to focused workers.

### 🎨 Reusable character, scene, and prop assets

Character designs, style references, scene assets, and prop assets act as cross-shot references to reduce visual drift across generated media.

SHOTWISE supports multiple built-in and custom providers through unified `ImageBackend` / `VideoBackend` / `TextBackend` protocols, switchable at global or project level:

- **Storyboard image-to-video**: generate from one storyboard image at a time for straightforward shot-by-shot review.
- **Storyboard sheet-to-video**: create several shots together on a storyboard sheet, split them into individual images, then generate each video; best when cross-shot consistency matters.
- **Reference-to-video**: generate directly from character, scene, and prop assets.

### ⚡ Asynchronous tasks and concurrency controls

Image, video, and audio jobs use independent concurrency channels with RPM limits, live status reporting, failure recovery, and resumable execution.

### 🕰️ Version history and project archives

Regeneration preserves earlier versions. Entire projects can be exported and imported for backup, migration, and handoff.

### 💰 Estimates and actual usage

Track calls and costs by provider and media type, preserve currency boundaries, and compare estimates with actual usage at project, episode, and shot levels.

### 🎙️ Voice-over and editable export

Generate and audition narration tracks, fill an episode in bulk, and export CapCut drafts containing video, voice-over, and subtitle tracks.

### 🔌 External Agent integration

ArcReel can issue `arc-` API keys and expose a synchronous Agent chat endpoint for platforms such as OpenClaw.

SHOTWISE's AI assistant is built on the Claude Agent SDK, using an **Orchestration Skill + Focused Subagent** multi-agent architecture:

ArcReel hides provider differences behind `TextBackend`, `ImageBackend`, and `VideoBackend` protocols. Models, parameters, availability, and pricing change over time, so the **ArcReel Settings page and provider documentation are the source of truth**.

| Provider | Text | Image | Video | TTS |
|---|:---:|:---:|:---:|:---:|
| Gemini | ✅ | ✅ | ✅ | — |
| Volcengine Ark | ✅ | ✅ | ✅ | — |
| Grok | ✅ | ✅ | ✅ | — |
| OpenAI | ✅ | ✅ | ✅ | — |
| Vidu | — | ✅ | ✅ | — |
| DashScope | ✅ | ✅ | ✅ | ✅ |
| MiniMax | ✅ | ✅ | ✅ | — |
| Kling | — | ✅ | ✅ | — |
| Agnes | ✅ | ✅ | ✅ | — |
| Custom providers | Interface-dependent | Interface-dependent | Interface-dependent | Interface-dependent |

Global defaults, project-level overrides, and multiple API keys per provider are supported. See [Provider Configuration](docs/providers.md).

## OpenClaw Integration

SHOTWISE supports invocation through external AI Agent platforms like [OpenClaw](https://openclaw.ai), enabling natural language-driven video creation:

1. Generate an API Key in SHOTWISE's Settings page (`arc-` prefix)
2. Load SHOTWISE's Skill definition in OpenClaw (access `http://your-domain/skill.md` to auto-fetch)
3. Create projects, generate scripts, and produce videos through OpenClaw conversations

Technical implementation: API Key authentication (Bearer Token) + synchronous Agent chat endpoint (`POST /api/v1/agent/chat`), internally connects to SSE streaming assistant and collects complete responses.

## Technical Architecture

```mermaid
flowchart TB
    UI["React 19 Web UI"] --> API["FastAPI API / SSE"]
    API --> AGENT["Agent Runtime<br/>Skill + Subagent"]
    API --> CORE["Core Services"]
    AGENT --> CORE
    CORE --> PROVIDERS["Text / Image / Video / TTS Backends"]
    CORE --> QUEUE["Generation Queue<br/>RPM + Independent Channels"]
    CORE --> PROJECTS["Project Manager<br/>Assets + Version History"]
    CORE --> DB["SQLAlchemy 2.0<br/>SQLite / PostgreSQL"]
```

The stack includes React 19, TypeScript, FastAPI, Python 3.12+, the Claude Agent SDK, SQLAlchemy 2.0, FFmpeg, Docker, and Docker Compose. See [Architecture](docs/architecture.md) for boundaries and extension points.

## Important limitations

- Media generation depends on third-party services; speed, availability, policy, and pricing are provider-controlled.
- Long-form projects still benefit from human review of episode boundaries, character assets, and key plot decisions.
- Video providers differ in reference-image count, duration, start/end-frame support, audio support, and regional availability.
- Native Windows can run parts of the basic workflow, but POSIX-dependent Agent sandbox features degrade; prefer Linux, macOS, WSL2, or Docker.
- Production deployments should use PostgreSQL, HTTPS, strong credentials, and regular backups. Do not expose an unprotected port `1241` to the public Internet.

See [FAQ](docs/FAQ.md) for more.

## Documentation

Detailed documentation is currently maintained in Chinese; English documentation contributions are welcome.

| Document | Purpose |
|---|---|
| [Documentation Index](docs/README.md) | Entry points for creators, operators, and contributors |
| [Getting Started](docs/getting-started.md) | From first deployment to the first generated video |
| [Workflows and Modes](docs/workflows.md) | Novel, screenplay, narration, drama, ad, and video-making workflows |
| [Provider Configuration](docs/providers.md) | Agent, text, image, video, and TTS provider choices |
| [Deployment and Operations](docs/deployment.md) | SQLite, PostgreSQL, upgrades, backups, and reverse proxies |
| [Security Policy](SECURITY.md) | Supported versions, deployment boundaries, private reporting, and coordinated disclosure |
| [Security Threat Model](docs/security/threat-model.md) | Security assets, trust boundaries, attack surfaces, and reassessment triggers |
| [CapCut Draft Export](docs/jianying-export-guide.md) | Continue editing ArcReel output in CapCut |
| [Architecture](docs/architecture.md) | Agent runtime, queue, provider abstraction, and data layer |
| [FAQ](docs/FAQ.md) | Deployment, cost, data, model, and licensing questions |
| [Contributing](CONTRIBUTING.md) | Local development, tests, conventions, and pull requests |
| [Changelog](CHANGELOG.md) | Release history |

## Contributing

Contributions to code, documentation, tests, provider adapters, and reproducible bug reports are welcome.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before starting. After cloning the repository, install the pre-commit hooks:

```bash
uv run pre-commit install
```

## License and commercial use

ArcReel is licensed under the [GNU Affero General Public License v3.0](LICENSE). Additional terms are available in [NOTICE](NOTICE).

For organizations that cannot use AGPL-3.0, or need commercial deployment, white-labeling, or redistribution without AGPL obligations, contact:

**support@arc-reel.com**

Copyright © 2026 Pollo3470 and SHOTWISE contributors

---

<p align="center">
  If ArcReel helps your work, consider giving the project a ⭐ Star.
</p>
