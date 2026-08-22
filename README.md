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

- **Slash commands** — single and group chat sessions, resume, and search
- **Conversation memory** — a configurable window of prior turns is replayed each request
- **Reasoning continuity** — `reasoning_details` are stored per message and returned
  verbatim on the next turn, so a reasoning model resumes rather than restarts
- **Semantic + keyword search** over your own history, on **pgvector** — no extra service
- **Provider-agnostic LLM layer** — OpenAI and OpenRouter over one SDK, no LangChain
- **Env-overridable models** — the template does not go stale when a provider ships a new one
- **Two services, not three** — bot + PostgreSQL is the whole deployment
- **Fully async** — commands, CRUD and the data layer
- **SQLAlchemy 2.0** with async engine and `select()` style queries
- **Session-based auth** protecting `/docs` and `/redoc`, with generated credentials
- **`/health` endpoint** reporting database reachability, for platform healthchecks
- **uv** for fast, reproducible dependency management
- **Memory-tuned Docker image** — multi-stage build, pool sized for an idle service
  (Railway bills by memory)

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

## Project Structure

```
├── src/
│   ├── backend/
│   │   ├── constants.py         # Shared constants and UTC helper
│   │   ├── data/                # Seed data (commands, LLM catalogue)
│   │   ├── discord/             # Discord bot
│   │   │   ├── bot.py           # Client, intents, message chunking
│   │   │   ├── register.py      # Slash command registration
│   │   │   ├── decorator_async.py  # Interaction handling
│   │   │   ├── run_async.py     # Command orchestration
│   │   │   └── service.py       # Database operations
│   │   ├── fastapi/             # REST API and admin surface
│   │   │   ├── main.py          # App entry point
│   │   │   ├── api/v1/endpoints/  # Route handlers
│   │   │   ├── core/            # Config and settings
│   │   │   ├── crud/            # Async CRUD services
│   │   │   ├── dependencies/    # Engine, session, DI
│   │   │   ├── models/          # SQLAlchemy ORM models
│   │   │   └── schemas/         # Pydantic schemas
│   │   ├── search/              # Hybrid BM25 + vector search
│   │   │   ├── analyzer.sql     # Multilingual tokenizer (vendored)
│   │   │   ├── service.py       # Two tiers, fused by rank
│   │   │   ├── summary.py       # One embedding per session
│   │   │   └── embeddings.py    # Provider calls
│   │   └── security/            # Docs authentication
│   ├── config/                  # Loads config/bot.yaml, env wins
│   ├── frontend/login/          # Login page templates & static files
│   └── llm/                     # Provider layer
│       ├── client.py            # Cached OpenAI / OpenRouter clients
│       ├── chat.py              # Completions, memory, reasoning
│       ├── config.py            # Models and tuning
│       ├── memory/              # Memory formatting
│       └── prompt/              # System prompt templates
├── config/bot.yaml              # Persona, provider, search tuning
├── docker/
│   ├── app/Dockerfile           # The bot: multi-stage build with uv
│   └── postgres-search/         # The database image this bot deploys
├── tests/                       # Async test suite
├── pyproject.toml               # Dependencies & project config
├── railway.json                 # Points the builder at docker/app/Dockerfile
└── .env.example                 # Environment variable template
```

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

### Running Tests

```bash
uv run pytest
```

### Docker

```bash
docker build -t discord-llm-bot .
docker run --env-file .env -p 5000:5000 discord-llm-bot
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | **yes** | Discord bot token |
| `OPENAI_API_KEY` | **yes** | Used for completions and embeddings |
| `OPENROUTER_API_KEY` | if routing | Required when `LLM_PROVIDER=openrouter` |
| `LLM_PROVIDER` | no | `openai` (default) or `openrouter` |
| `OPENAI_MODEL` | no | Default `gpt-5.6-luna` |
| `OPENROUTER_MODEL` | no | Default `openai/gpt-5.6-luna` |
| `LLM_REASONING` | no | Request reasoning via OpenRouter. Default `true` |
| `LLM_TEMPERATURE` | no | Default `0.5` |
| `EMBEDDING_MODEL` | no | Default `text-embedding-3-small` |
| `EMBEDDING_DIM` | no | Must match the model. Default `1536` |
| `DATABASE_URL` | prod | PostgreSQL connection string |
| `USER_NAME` / `PASSWORD` | no | Protects `/docs`. Generated and logged if unset |
| `SECRET_KEY` | no | Signs session cookies. Generated per process if unset |
| `ENV_MODE` | no | `dev` (SQLite) or `prod` (PostgreSQL) |
| `HOST` / `PORT` | no | Defaults `127.0.0.1` / `5000`; `0.0.0.0` in prod |

## How It Works

Each slash command runs as two short database transactions with the slow work between
them: the user's turn is committed, the embedding and completion calls run holding **no**
database connection, then the model's turn is committed and indexed. This keeps a pooled
connection from being pinned for the multi-second life of a completion.

Search is scoped by an `index_key` — the channel id for group sessions, a hash of
(user, channel) for single ones — so one user's history is never searchable from another's.

## Learn More

- [discord.py documentation](https://discordpy.readthedocs.io/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [pgvector](https://github.com/pgvector/pgvector)
- [OpenRouter reasoning](https://openrouter.ai/docs/use-cases/reasoning-tokens)

## License

MIT — see [LICENSE](./LICENSE).
