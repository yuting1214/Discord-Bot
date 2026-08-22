# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Search
- **Two-tier retrieval with Reciprocal Rank Fusion.** Lexical (BM25) and semantic
  (pgvector) rankings are now fused by rank rather than blended by score. The previous
  weighted sum was unworkable: cosine similarity lands around 0.3–0.5 while `ts_rank`
  lands around 0.05, so a nominal 50/50 split behaved as roughly 90% semantic.
- `search_documents` gains a trigger-populated `bm25` column and index, installed at
  startup. A database without `vchord_bm25` still runs, with search falling back to the
  semantic tier — so the app stays deployable against stock PostgreSQL.
- **Each tier now decides what counts as a match before fusion.** RRF scores a document
  by where it *placed*, not by whether it matched, and `ORDER BY … LIMIT n` always
  returns n documents — so on a small table every document was a result for every query,
  ranked by the tiers' opinions of each other rather than by the query. A BM25 score of
  exactly 0 means no shared term and is no longer a hit; the vector tier is bounded by
  `SEARCH_SEMANTIC_MAX_DISTANCE` (default 0.6, measured). On the live database a query
  for 麵包 went from 5 results spanning 0.031–0.033, with a decoy second, to 2 results
  where the right one leads by 2×; a query about something never discussed now returns
  nothing at all, which was previously impossible.
- Tunable via `SEARCH_RRF_K`, `SEARCH_LEXICAL_WEIGHT`, `SEARCH_SEMANTIC_WEIGHT`,
  `SEARCH_SEMANTIC_MAX_DISTANCE`.

- **A valid session ID for a missing session no longer reports as malformed.**
  `extract_uuid` matched UUID **4** only, so the nil UUID — and any v1/v5/v7 ID — was
  rejected on shape before the lookup ran, and the user was told to go back to `/search`
  and re-copy the ID they already had. It now accepts any UUID version, which also
  matters because PostgreSQL 18 ships `uuidv7()` and this template's own database image
  documents it: the day session IDs come from the database, every resume would have
  broken. It no longer raises either — it is called outside the caller's `try`, so a
  `ValueError` surfaced as the generic failure message.

### Search
- **One embedding per session, not one per turn.** Every user message was embedded as it
  arrived — a provider call on the hot path of every command — and most turns do not
  deserve one: `"you good?"` embedded to something plausible and outranked a genuinely
  relevant turn, because a short aside sits near everything in vector space. The semantic
  tier now works from an LLM summary written once when a session ends, which is
  O(sessions) rather than O(turns) and is dense and topical by construction.
  Lexical search is unaffected and still covers every individual message, because BM25 is
  populated by a database trigger at no cost.
- **Three things trigger a summary**, because each leaves a hole the others do not:
  closing a session, an idle sweep (a session nobody ever closes would otherwise never be
  summarised), and `POST /api/v1/sessions/{id}/summary` for backfill and retries.
  Tunable via `SUMMARY_ENABLED`, `SUMMARY_IDLE_MINUTES`, `SUMMARY_SWEEP_INTERVAL_MINUTES`
  and `SUMMARY_BATCH_SIZE`.
- `sessions` gains `summary`, `summary_vector` and `summarized_at`, all nullable and added
  on startup, so an existing deployment upgrades without a migration.
- **Documents indexed before BM25 existed are backfilled.** They carried a NULL `bm25`,
  and the lexical tier filters on `bm25 IS NOT NULL` — so an upgrading deployment's entire
  existing history was invisible to search, silently and permanently. Up to 5,000 rows per
  restart, bounded so a large table cannot hold the boot transaction open past the
  healthcheck.

### Security
- **The summary endpoint requires the `/docs` login.** It calls a paid provider on demand
  and `?force=true` removes the once-per-session guard, so open to the internet it is an
  unbounded charge against whoever deployed the template. Every other route under
  `/api/v1` is a read; this is the only one that spends money.

### Testing
- **The suite runs against real PostgreSQL** (`./scripts/ci.sh`), not only SQLite. Set
  `TEST_DATABASE_URL` and every test runs on a private schema of a real database. Every
  production defect this project has had lived in a branch SQLite never executes, and
  turning this on immediately found four more: `CREATE EXTENSION` resolving against the
  caller's `search_path`, `bm25_vocabulary` doing the same, 26-dimension stub vectors that
  only a JSON column would accept, and `TestClient` running the app on its own event loop
  where asyncpg's pooled connections do not work.
- `scripts/check_upgrade.py` builds a v0.1.0-era database and boots the current release
  against it, asserting the columns are added, the data survives and pre-BM25 rows become
  searchable.
- HTTP tests moved from `TestClient` to `httpx.ASGITransport` on the test's own loop.

### Configuration
- **One file for the bot's behaviour** (`config/bot.yaml`): persona, provider, model,
  temperature, reasoning, embeddings, search tuning and memory window. Changing the
  bot's character no longer means editing Python — it was previously spread across
  `llm/config.py`, a prompt template module and a dozen `os.getenv` calls.
- **Precedence is environment > file > defaults.** Every variable this template already
  publishes still works and still wins, so a Railway variable retunes a running service
  without a rebuild. A missing or malformed file falls back to defaults rather than
  failing to boot, and one bad variable is logged and ignored rather than taking the
  container down where the dashboard cannot be reached to fix it.
- **Secrets are environment-only.** No API key or token is readable from the file, and a
  test asserts the override table never gains one.
- Removed `SEARCH_SEMANTIC_RATIO`. It was threaded through three functions and read by
  none of them — a leftover from the linear blend that RRF replaced.

### Database
- **Search now runs inside PostgreSQL** (`docker/postgres-search/`): Railway's
  `postgres-ssl` 18.6 plus `vchord_bm25` for BM25 ranking and `icu_ext` for word
  segmentation, keeping pgvector, pgBackRest and the SSL wrapper. **6.7 MB idle**,
  against 6.4 MB for the stock image. This replaces Meilisearch, which cost a second
  always-on container, a volume and a public domain the bot called over the internet.
- **The analyzer** (`src/backend/search/analyzer.sql`, applied at startup) tokenizes per
  script within a single document: `to_tsvector` for spaced scripts, ICU for Chinese,
  Thai, Khmer, Lao and Burmese, bigrams for Japanese and Korean. It also folds
  diacritics, keeps high-cardinality tokens such as ids and hashes out of the vocabulary
  — `vchord_bm25` spends ~8 KB of index per distinct term, so on 20,000 chat-shaped rows
  that is the difference between a 641 MB index and a 736 KB one — expands
  single-character CJK queries, and highlights results in scripts `ts_headline` cannot
  mark.
- The database image, its 13-locale verification corpus and the benchmarks behind these
  numbers now live in **[postgres-search](https://github.com/yuting1214/postgres-search)**.
  `analyzer.sql` is vendored here because the application container ships `src/` and
  nothing else.

## [0.2.0] - 2026-08-21

The template is rebranded and made public at this release. The deploy slug and
referral link are unchanged.

### Security
- **Empty docs credentials no longer authenticate.** `authenticate_user` compared the
  submitted form against `os.getenv("USER_NAME")` / `os.getenv("PASSWORD")`, and the
  Railway template declares both with empty-string defaults — so on a default deploy
  `"" == ""` held and an empty login form opened `/docs`, `/redoc` and the full API
  schema to anyone. Credentials are now generated when unset and printed once in the
  startup logs.
- **Constant-time credential comparison** (`secrets.compare_digest`), evaluating both
  halves rather than short-circuiting, so neither timing nor early exit reveals a
  correct username.
- **`SECRET_KEY` is a real setting**, generated per process when unset. Session cookies
  were previously signed with the literal `"your_secret_key"`, published in this
  repository and identical across every deployment.
- **Command handlers no longer echo raw exception strings into Discord**, which could
  disclose connection strings and provider errors to any member of the server.
- Repository history was re-rooted before publication: a tracked `.env` carried live
  credentials in 12 of 15 revisions, including a bot token present from the first commit.

### Usability
- **Failures now say what to fix.** Every error reached Discord as "Something went wrong",
  so a stale API key was indistinguishable from a database outage. Errors are classified
  and reported as a hint naming the setting to check — and sent ephemerally, so a broken
  key does not spam the channel. The underlying exception stays in the logs, because it
  quotes the API key and the connection string.
- **Command parameters are named and described.** Every command took a parameter literally
  called `user_input`, so `/resume_session` gave no indication it wanted a session ID.
  They are now `message`, `query` and `session_id`, each with a description.
- **Search results are readable.** They were a raw JSON dump, which meant picking a
  `session_id` out of a wall of braces before `/resume_session` could be used at all.
- **Truncated searches say so.** The top-N cut was silent, so a correctly-ranked low-scoring
  result looked as though it had never been indexed. The header now reads "3 of 6 result(s)",
  and the limit is configurable via `SEARCH_TOP_N` (default raised 3 → 5).
- **Group search points at the group resume command.** Its footer named `/resume_session`,
  which cannot resume the group sessions it had just listed.

### Deploy Health
- **No-op command syncs are skipped.** The tree was re-registered on every deploy, which
  invalidates the definitions cached by connected Discord clients — they then answer the
  next invocation with "This command is outdated, please try again in a few minutes" until
  the user reloads. The tree is now compared with what Discord already has, and synced only
  when it differs. A genuine command change still requires connected clients to refresh.
- **Removed the `message_content` privileged intent.** Unless a deployer had also enabled
  it in the Discord Developer Portal — a step no documentation mentioned — login failed
  with `PrivilegedIntentsRequired` and the container died on boot. The bot serves slash
  commands only and never read message content.
- **Commands work in DMs**, or rather fail cleanly there: `interaction.guild` is `None`
  in a direct message, so reading guild attributes raised `AttributeError` and the
  command died with no reply at all.
- **Fail fast on a missing `DISCORD_TOKEN`** with an actionable message, instead of
  passing `None` into discord.py and surfacing an opaque `TypeError`.
- **Command tree syncs from `setup_hook`**, not `on_ready`, which re-fires on every
  gateway reconnect against a sharply rate-limited endpoint.
- **Added `GET /health`**, reporting database reachability rather than a bare `ok`, and
  wired it as the platform healthcheck via `railway.json` with an `ON_FAILURE` restart
  policy.

### Architecture
- **The bot no longer calls its own HTTP API.** Every read and write went out over
  `RAILWAY_PUBLIC_DOMAIN` and back into the same container — six to ten sequential
  public-internet round trips per slash command, billed as egress, failing outright
  during cold start before the domain had a certificate. The bot now uses the database
  directly. Net 330 lines and an entire indirection tier removed.
- **Real transactions replace the compensating-rollback manager**, which undid partial
  work by issuing DELETE and POST requests that could themselves fail.
- **The async path is genuinely async.** `run_async.py` previously called synchronous
  HTTP helpers inside `async def`, blocking the event loop and stalling the bot for
  every other user for the duration of each request.
- **Two short transactions per command**, with the embedding and completion calls
  between them, so a pooled connection is never held across a multi-second completion.
- **Collapsed the duplicate synchronous data path**: one generic async CRUD replaces ten
  hand-written sync/async service pairs, and the mirrored `/api/v1/sync` and
  `/api/v1/async` route trees become a single `/api/v1`. OpenAPI surface 53 → 28 paths.
- `llm_usages` is populated from provider-reported token counts; no code path had ever
  written to that table.

### Search
- **Meilisearch replaced by pgvector**, inside the PostgreSQL service the template
  already deploys. This deletes an always-on container, a persistent volume and a public
  service domain from every deployment — and the bot had been reaching that public domain
  on *every message*, not only on search. Railway's `postgres-ssl` image already ships
  `postgresql-17-pgvector`.
- The pinned image was two years stale (v1.8.4 against v1.53) and the app toggled an
  experimental `vectorStore` flag at startup that has since gone stable.
- Ranking blends cosine similarity with `ts_rank`, matching the previous `semanticRatio`
  behaviour, and degrades to keyword-only when an embedding cannot be produced.

### LLM
- **Dropped LangChain for the provider SDKs.** The chain used `langchain.prompts` and
  `langchain_community.chat_models`, both of which moved in LangChain 1.x, so a fresh
  install of the unpinned requirement resolved to 1.3 and failed to import. One OpenAI
  SDK now serves both OpenAI and OpenRouter. Worth **−36 MB** of resident floor,
  −31 packages and −61 MB of site-packages.
- **Default models are `gpt-5.6-luna` / `openai/gpt-5.6-luna`**, and every model id is
  env-overridable. Hardcoding is what pinned the previous release to `gpt-3.5-turbo-0125`.
- **Reasoning is persisted and replayed.** Reasoning models return a `reasoning_details`
  trace that must be handed back verbatim on the next request; without it the model
  restarts its reasoning every turn, paying for it repeatedly and still losing the thread.
- Provider clients are cached, so the httpx connection pool is reused rather than rebuilt
  on every message.
- `llm/` no longer imports `backend/`: importing the LLM layer used to run the
  application's import-time argparse as a side effect.

### Memory & Deployment (Railway bills by memory)
- **Multi-stage Dockerfile on `uv`**: the runtime layer holds only the venv and `src/`.
  Execs the venv interpreter directly rather than through `uv run`, which would keep a
  ~25 MB wrapper process resident for the life of the container.
- `UV_COMPILE_BYTECODE=1`, `MALLOC_ARENA_MAX=2`, `MALLOC_TRIM_THRESHOLD_=100000`.
- **Connection pool sized for an idle service**: `pool_size=1` (held open, billed idle)
  with `max_overflow=12` (opened on demand, closed on return), plus `pool_pre_ping` and
  `pool_recycle=1800` so the first request after an idle night is not served on a
  connection the database has already dropped.
- **Guard test** asserts in a fresh interpreter that no removed dependency creeps back
  into either entrypoint — validated against a planted regression, so it is not inert.
- Entrypoint import floor **124.5 MB → 104.5 MB**; locked packages **85 → 61**.
- **Idle service 104.9 MB on Railway** (`MEMORY_USAGE_GB`, measured on a real deploy with
  the bot connected to the gateway and the API serving); 87.4 MB anon in a local container
  against the same PostgreSQL image.

### Upgrades
- **Columns added to already-deployed tables are now backfilled on boot.**
  `create_all` creates missing *tables* and leaves existing ones untouched, so
  `messages.reasoning_details` would never have appeared on an existing database —
  and every insert referencing it would have failed. With GitHub-sourced templates
  receiving auto-update delivery, that would have reached every live deployment.
  Startup now reconciles missing nullable columns against the models, idempotently.
  A required column is logged as needing a migration rather than added with an
  invented default.

### Search
- **One embedding per session, not one per turn.** Every user message was embedded as it
  arrived — a provider call on the hot path of every command — and most turns do not
  deserve one: `"you good?"` embedded to something plausible and outranked a genuinely
  relevant turn, because a short aside sits near everything in vector space. The semantic
  tier now works from an LLM summary written once when a session ends, which is
  O(sessions) rather than O(turns) and is dense and topical by construction.
  Lexical search is unaffected and still covers every individual message, because BM25 is
  populated by a database trigger at no cost.
- **Three things trigger a summary**, because each leaves a hole the others do not:
  closing a session, an idle sweep (a session nobody ever closes would otherwise never be
  summarised), and `POST /api/v1/sessions/{id}/summary` for backfill and retries.
  Tunable via `SUMMARY_ENABLED`, `SUMMARY_IDLE_MINUTES`, `SUMMARY_SWEEP_INTERVAL_MINUTES`
  and `SUMMARY_BATCH_SIZE`.
- `sessions` gains `summary`, `summary_vector` and `summarized_at`, all nullable and added
  on startup, so an existing deployment upgrades without a migration.
- **Documents indexed before BM25 existed are backfilled.** They carried a NULL `bm25`,
  and the lexical tier filters on `bm25 IS NOT NULL` — so an upgrading deployment's entire
  existing history was invisible to search, silently and permanently. Up to 5,000 rows per
  restart, bounded so a large table cannot hold the boot transaction open past the
  healthcheck.

### Security
- **The summary endpoint requires the `/docs` login.** It calls a paid provider on demand
  and `?force=true` removes the once-per-session guard, so open to the internet it is an
  unbounded charge against whoever deployed the template. Every other route under
  `/api/v1` is a read; this is the only one that spends money.

### Testing
- **The suite runs against real PostgreSQL** (`./scripts/ci.sh`), not only SQLite. Set
  `TEST_DATABASE_URL` and every test runs on a private schema of a real database. Every
  production defect this project has had lived in a branch SQLite never executes, and
  turning this on immediately found four more: `CREATE EXTENSION` resolving against the
  caller's `search_path`, `bm25_vocabulary` doing the same, 26-dimension stub vectors that
  only a JSON column would accept, and `TestClient` running the app on its own event loop
  where asyncpg's pooled connections do not work.
- `scripts/check_upgrade.py` builds a v0.1.0-era database and boots the current release
  against it, asserting the columns are added, the data survives and pre-BM25 rows become
  searchable.
- HTTP tests moved from `TestClient` to `httpx.ASGITransport` on the test's own loop.

### Configuration
- **Env-driven settings replace module-level argparse**, which consumed the arguments of
  whatever process was running. The test suite could not collect a single test, and the
  app could not be started under plain `uvicorn` or gunicorn.
- Fixed `HOST_URL`, declared as `os.getenv('HOST_URL ')` with a trailing space in the
  variable name, so it never read the variable it named.
- Removed `os.getenv()` defaults from pydantic-settings fields, which evaluate once at
  import and shadow the settings machinery meant to read them.

### Fixed
- **The bot and the web application now share one event loop.** They ran on two: uvicorn
  in a background thread, discord.py in the main thread. Both halves use the same
  SQLAlchemy engine, so once the bot began talking to the database directly, a connection
  pooled on one loop was checked out on the other and asyncpg failed with
  `got Future attached to a different loop` — every slash command returned an error while
  every test passed. The bot is now a task inside the application's lifespan.
- **`/login` returned 500.** The handler used the old
  `TemplateResponse("name", {"request": ...})` signature; newer Starlette reads the first
  positional argument as the request, so the template name arrived as a dict and Jinja
  raised `unhashable type: 'dict'`. Every earlier test stopped at the redirect to /login
  without following it.
- **`temperature` is no longer sent unless explicitly configured.** Reasoning models --
  including the default `gpt-5.6-luna` -- reject any value but their own and fail the
  request with `400 Unsupported value: 'temperature'`. The hardcoded `0.5` would have
  broken every completion on the default model. A rejected value is now retried without it.
- `uvicorn.run(app=...)` still named the pre-`src/` module path, so the API thread died
  on startup in the container while every test passed, because tests import the app
  object directly and never go through that string.
- **A missing database in prod now says what to set.** Assembling a connection URL from
  blank parts failed deep inside SQLAlchemy with
  `invalid literal for int() with base 10: ''`, naming nothing the deployer could act on.
- pgvector's `cosine_distance` is not inherited through a `TypeDecorator`; the `<=>`
  operator is applied explicitly, with the query vector bound as a vector literal.
- `extract_uuid` returns a `str` while `Session.id` is a `UUID` column — `/resume_session`
  would have raised on every invocation. Search result ids had the same mismatch.
- `crud/user.py` imported `Session` from both `sqlalchemy.orm` and the models package;
  the later import won, so the `db_sync: Session` annotation named the wrong type.
- `delete_conversation_async` was declared `def` and returned an un-awaited coroutine.
- Timestamps mixed the database's `func.now()` with values the application wrote in
  `Etc/GMT-4`, making ordering and duration arithmetic across them wrong. All UTC now.
- Background tasks are strongly referenced; asyncio holds only a weak reference, so an
  in-flight task could be garbage collected mid-request.
- Long responses are chunked on paragraph, line, then word boundaries instead of being
  sliced every 2000 characters mid-word.
- Deleted `dependencies/rate_limiter.py`, which imported `fastapi_limiter` and `aioredis`
  — neither ever a declared dependency, so the module could not be imported at all.

### Housekeeping
- Migrated to `uv` with a committed lockfile; Python 3.9 → 3.12.
- Restructured to `src/backend`, `src/frontend`, `src/llm` with tests at the top level,
  matching the [Fullstack-FastAPI](https://github.com/yuting1214/Fullstack-FastAPI) template.
- `ruff` configured and clean, from 530 errors.
- Test suite added: 37 tests covering the command flow, search, authentication, HTTP
  surface and import weight.

## [0.1.0] - 2024-07-21

Initial release. Discord LLM chatbot with FastAPI, PostgreSQL, Meilisearch hybrid search
and LangChain, deployed as a Railway template.
