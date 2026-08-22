---
title: Discord LLM Bot
description: A Discord LLM chatbot with FastAPI, PostgreSQL and semantic search
tags:
  - discord
  - fastapi
  - postgresql
  - pgvector
  - python
---

# Discord LLM Bot

A production-ready [Discord](https://discord.com/developers/docs) chatbot with persistent
sessions, conversation memory and semantic search — built on
[FastAPI](https://fastapi.tiangolo.com/), [PostgreSQL](https://www.postgresql.org/) and
[pgvector](https://github.com/pgvector/pgvector), fully async.

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.com/deploy/PVL8qm?referralCode=jk_FgY&utm_medium=integration&utm_source=template&utm_campaign=generic)

> **[CHANGELOG](./CHANGELOG.md)** — See what's changed between versions.

## Features

- **Slash commands** for single and group sessions — start, continue, resume, search
- **Conversation memory** — prior turns are replayed each request, so the bot follows
  the thread instead of answering in isolation
- **Reasoning continuity** — a reasoning model's trace is stored and handed back on the
  next turn, so it resumes its thinking rather than starting over
- **Search that finds things two ways** — exact terms *and* meaning, over your own
  history, inside PostgreSQL. No search cluster to run
- **Multilingual search** — Chinese, Japanese, Korean, Thai and 30+ more, with real word
  segmentation rather than whole-sentence tokens
- **One YAML for behaviour** — persona, model, provider and search tuning live in
  [`config/bot.yaml`](./config/bot.yaml); no Python to edit
- **Any OpenAI-compatible provider** — OpenAI and OpenRouter share one client, and models
  are overridable, so the template does not go stale
- **Two services, not four** — the bot and its database are the whole deployment

## Commands

| Command | Description |
|---|---|
| `/start_session` | Start a new single session |
| `/bot` | Send a message in the current single session |
| `/start_group_session` | Start a new group session in this channel |
| `/bot_group` | Send a message in the current group session |
| `/resume_session` | Resume a previous single session by id |
| `/resume_group_session` | Resume a previous group session by id |
| `/search` | Search your own past messages |
| `/search_group` | Search this channel's group messages |

## Where things live

| | |
|---|---|
| `config/bot.yaml` | persona, provider, model, search tuning — start here |
| `src/backend/discord/` | slash commands and what happens when one runs |
| `src/backend/search/` | the two search tiers, session summaries, the analyzer |
| `src/backend/fastapi/` | REST API, models, and the admin surface behind `/docs` |
| `src/llm/` | provider clients, completions, memory |
| `docker/app/` | the bot's image |
| `docker/postgres-search/` | its database: PostgreSQL with search extensions |
| `scripts/ci.sh` | lint and tests, against SQLite *and* real PostgreSQL |

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- A Discord bot token — [Developer Portal](https://discord.com/developers/applications)
  → **Applications** → **Bot** → **Token**
- An OpenAI or OpenRouter API key

> No privileged intents are required. You do **not** need to enable Message Content.

### Setup

```bash
# Clone the repository
git clone https://github.com/yuting1214/Discord-Bot.git
cd Discord-Bot

# Install dependencies
uv sync

# Copy environment template
cp .env.example .env
# Edit .env with your values

# Run in development mode (SQLite, auto-reload)
uv run python -m src.backend.fastapi.main
```

Then invite the bot to a server with the `applications.commands` and `bot` scopes,
and run `/start_session` in any channel.

### Tests

```bash
uv run pytest              # fast: SQLite
./scripts/ci.sh            # lint, SQLite, and real PostgreSQL in Docker
```

The second one is worth running before you push. SQLite and PostgreSQL take
different code paths, and only one of them ships.

### Docker

```bash
docker build -f docker/app/Dockerfile -t discord-llm-bot .
docker run --env-file .env -p 5000:5000 discord-llm-bot
```

## Configuration

Two layers, and **the environment always wins** — so a deployed service can be retuned
from your platform's dashboard without a rebuild.

### `config/bot.yaml` — what the bot is like

Persona, provider, model, search tuning, how much history to replay. Edit it, redeploy,
done. The file is commented; deleting it is safe, since every value has a built-in default.

```yaml
llm:
  provider: openai            # openai | openrouter
  models:
    openai: gpt-5.6-luna
prompts:
  system: |
    You are a helpful assistant...
```

### Environment — secrets, and anything you want to override

Secrets are **never** read from the YAML file.

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | **yes** | Discord bot token |
| `OPENAI_API_KEY` | **yes** | Completions and embeddings |
| `OPENROUTER_API_KEY` | if routing | Required when `LLM_PROVIDER=openrouter` |
| `DATABASE_URL` | prod | PostgreSQL connection string |
| `ENV_MODE` | no | `dev` (SQLite) or `prod` (PostgreSQL) |
| `USER_NAME` / `PASSWORD` | no | Protects `/docs`. Generated and logged if unset |
| `SECRET_KEY` | no | Signs session cookies. Generated per process if unset |
| `HOST` / `PORT` | no | Defaults `127.0.0.1` / `5000`; `0.0.0.0` in prod |

Every key in `bot.yaml` also has a matching variable — `LLM_PROVIDER`, `OPENAI_MODEL`,
`SEARCH_TOP_N`, `MEMORY_WINDOW_SIZE` and so on. See [`.env.example`](./.env.example) for
the full list with defaults.

## How search works

Two independent searches run over your history and their **rankings** are combined, not
their scores.

- **Exact terms** — BM25, maintained by the database itself as messages arrive. No API
  call, no delay, and it covers sessions that are still open.
- **Meaning** — when a session ends, the bot writes one summary of it and embeds that.
  So `resource exhaustion over time` finds a conversation about a memory leak, even
  though those words were never typed.

Summarising once per session rather than embedding every message keeps the cost
proportional to conversations rather than keystrokes — and a summary is a better thing to
search than a turn that reads *"you good?"*.

Each side decides for itself whether something matched before the two are merged, so a
query about nothing you have discussed returns nothing rather than the least-bad guess.

**The two tiers cover different text**, which is worth knowing before it surprises you:

| | searches |
|---|---|
| exact terms | your messages only |
| meaning | the whole conversation, the bot's replies included |

So a phrase the bot said and you did not is findable by meaning but not by exact term —
even though results display the reply. Verified on a live session: an eight-message
conversation indexes its four user messages, and a distinctive word appearing fifteen
times across the bot's answers matches nothing on the exact-term side.

Search is scoped by channel for group sessions and by (you, channel) for single ones, so
one person's history is never searchable from another's.

## Learn More

- [CHANGELOG](./CHANGELOG.md) — what changed, and why
- [discord.py](https://discordpy.readthedocs.io/) · [FastAPI](https://fastapi.tiangolo.com/)
- [OpenRouter reasoning](https://openrouter.ai/docs/use-cases/reasoning-tokens) — how the
  reasoning trace is requested and replayed
- [pgvector](https://github.com/pgvector/pgvector) · [VectorChord BM25](https://github.com/tensorchord/VectorChord-bm25)

## License

MIT — see [LICENSE](./LICENSE).
