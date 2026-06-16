# NewsLore — Implementation Plan

---

## Deviations from Original Plan

Changes made during build that differ from the original design:

| Area | Original | Actual |
|---|---|---|
| LLM provider | Anthropic (`anthropic` SDK) | Groq (`groq` SDK, `llama-3.3-70b-versatile`) — Anthropic key unavailable, Gemini free tier had quota=0 |
| Scraper char limit | 15,000 chars/source | 40,000 chars/source — increased after timelines came out too sparse |
| Articles per news source | 1 | 2 — concatenated, richer content for LLM |
| Scraper search query | Topic title only | Topic title + first 80 chars of series description — surfaces connected angles |
| Timeline prompt | Topic only | Topic + description as `CONTEXT FOCUS` — LLM told what angles matter |
| Delete endpoints | Not in original plan | Added: `DELETE /series/{id}` (cascades), `DELETE /series/{id}/timeline` |
| Model cascade | Not set | `cascade="all, delete-orphan"` added to all Series relationships |
| Series connections | Not in original plan | Added: `SeriesConnection` model, `discovery_depth` on Series, `POST /connections/{id}/approve`, `DELETE /connections/{id}` — see Step 8b |
| Cross-series episodes | Not in original plan | Episode prompt includes related timelines from approved connections via `RELATED CONTEXT` block |
| Scheduler | Standalone script | APScheduler `BackgroundScheduler` wired into FastAPI lifespan — Sunday 9am weekly batch |

---

## Planned Additions (agreed during build, not yet implemented)

*(All agreed additions have been implemented — Phase 1 complete.)*

---

## Tech Stack

| Layer | Library | Status |
|---|---|---|
| API | `fastapi`, `uvicorn` | ✅ In use |
| ORM | `sqlalchemy` | ✅ In use |
| Migrations | `alembic` | ⚠️ Initialized but not wired — app uses `create_all` via lifespan |
| Scraping | `beautifulsoup4`, `requests` | ✅ In use |
| Async HTTP | `aiohttp` | Phase 2 only |
| LLM | `groq` (Llama-3.3-70b) | ✅ In use — swapped from Anthropic |
| Scheduling | `apscheduler` | ✅ In use — BackgroundScheduler, Sunday 9am cron |
| Email | `resend` | ✅ In use — Resend API |
| Task Queue | `redis`, `rq` | Phase 2 only |
| Validation | `pydantic` | ✅ In use |
| Config | `python-dotenv` | ✅ In use |
| Testing | `pytest`, `pytest-asyncio`, `httpx` | Not started |
| Containers | Docker + Docker Compose | ✅ Done — `Dockerfile`, `docker-compose.yml`, `.dockerignore` |

---

## Phase 1 — Foundation & Core Pipelines ✅ COMPLETE

- [x] **Step 1 — Project scaffold & environment** `DONE`
  - Full directory structure created (`app/`, `workers/`, `scripts/`, `tests/`)
  - All source files created inside `app/`
  - Python virtual environment created, all packages installed
  - `requirements.txt` written (uses `groq==0.13.0`)
  - `.env` template created (keys: `GROQ_API_KEY`, `RESEND_API_KEY`, `DATABASE_URL`, email fields)
  - `.gitignore` created

- [x] **Step 2 — Database layer** `DONE`
  - ✅ `app/database.py` — SQLAlchemy engine, `SessionLocal`, `Base`, `get_db()` dependency
  - ✅ `app/models.py` — five models: `Series`, `MasterTimeline`, `Episode`, `ContextBuildJob`, `SeriesConnection`
  - ✅ `SeriesConnection`: `series_id`, `connected_topic`, `connected_series_id` (nullable), `status`, `relationship_hint`
  - ✅ `discovery_depth` field on `Series` (default 0, max 2 before discovery stops)
  - ✅ `cascade="all, delete-orphan"` on all Series relationships
  - ⚠️ Alembic initialized but not wired — `create_all` runs in FastAPI lifespan for now

- [x] **Step 3 — Pydantic schemas** `DONE`
  - ✅ `app/schemas.py` — all request/response models
  - Includes: `SeriesCreate`, `SeriesResponse` (with `discovery_depth`), `TimelineResponse`, `ContextJobResponse`, `EpisodeResponse`, `EpisodeRateRequest`, `NewsletterPreviewResponse`, `NewsletterSendResponse`, `MetricsResponse`, `ContextBuildMetrics`, `EpisodeMetrics`, `SeriesConnectionResponse`

- [x] **Step 4 — Scraper** `DONE`
  - ✅ `scrape_wikipedia(topic)` — MediaWiki API, follows redirects
  - ✅ `scrape_url(url)` — fetches any URL, strips nav/scripts
  - ✅ `_duckduckgo_search(query)` — no API key, parses DDG HTML
  - ✅ `scrape_news_source(domain, topic, description)` — top 2 articles/domain, description in query
  - ✅ `scrape_all(topic, description, seed_urls)` — orchestrates all sources
  - MAX_CHARS_PER_SOURCE = 40,000; ARTICLES_PER_SOURCE = 2

- [x] **Step 5 — Timeline builder** `DONE`
  - ✅ `app/timeline.py`
  - ✅ `build_master_timeline(topic, scraped_content, description)` — parses `content`/`confidence_score`/`gaps`/`llm_time_ms`
  - ✅ `merge_timeline(topic, existing_content, new_scraped_content)` — for Pipeline C
  - ✅ `discover_related_topics(topic, timeline_content)` — LLM call returning `[{topic, relationship_hint}]`, parses numbered list `1. Topic | hint`
  - ✅ `description` injected as `CONTEXT FOCUS` in LLM prompt

- [x] **Step 6 — LLM abstraction** `DONE`
  - ✅ `app/llm.py` — single `call_llm(prompt)` function
  - Uses Groq SDK, model `llama-3.3-70b-versatile`

- [x] **Step 7 — Series API + Pipeline A** `DONE`
  - ✅ `POST /series` — creates series
  - ✅ `GET /series` — lists all series
  - ✅ `GET /series/{id}` — gets one series
  - ✅ `DELETE /series/{id}` — cascades to all child records
  - ✅ `POST /series/{id}/build` — **Pipeline A** — scrapes, builds timeline, runs topic discovery, stores connections
  - ✅ `GET /series/{id}/timeline` — returns active timeline
  - ✅ `DELETE /series/{id}/timeline` — resets series to building
  - ✅ `GET /context-jobs/{id}` — returns job status + timing

- [x] **Step 8 — Storytelling modes** `DONE`
  - ✅ `app/modes.py` — `MODES` dict: `gossip`, `dramatic`, `explainer`, `cartoon`
  - ✅ `build_story_prompt()` — assembles prompt with optional recap and `RELATED CONTEXT` block

- [x] **Step 8b — Series connections (knowledge graph)** `DONE` *(added step)*
  - ✅ `SeriesConnection` model in `models.py`
  - ✅ `discover_related_topics()` called after every Pipeline A build
  - ✅ Depth-limited: suggestions only generated for `discovery_depth < 2`
  - ✅ `GET /series/{id}/connections` — list all connections for a series
  - ✅ `POST /connections/{id}/approve` — creates new Series for the connected topic (caller then runs `/build`)
  - ✅ `DELETE /connections/{id}` — dismisses a suggestion

- [x] **Step 9 — Episode generation (Pipeline B)** `DONE`
  - ✅ `app/pipeline.py`
  - ✅ `generate_episode(series, db)` — timeline → last episode → random mode → related timelines → prompt → LLM → Episode
  - ✅ `run_weekly_batch(db)` — all ready series → `generate_episode`
  - ✅ `_get_related_timelines(series_id, db)` — queries approved connections with built timelines

- [x] **Step 10 — Episode API** `DONE`
  - ✅ `POST /episodes/run` — triggers weekly batch (all ready series)
  - ✅ `POST /series/{id}/episode` — single series episode generation
  - ✅ `GET /episodes` — list all episodes (optional `?series_id=` filter)
  - ✅ `GET /episodes/{id}` — full episode detail
  - ✅ `POST /episodes/{id}/rate` — stores quality rating 1–5

- [x] **Step 11 — Newsletter** `DONE`
  - ✅ `app/mailer.py` — `compile_newsletter(episodes)` builds HTML, `send_newsletter(html)` sends via Resend
  - ✅ `GET /newsletter/preview?days=7` — compiles without sending
  - ✅ `POST /newsletter/send?days=7` — sends email via Resend

- [x] **Step 12 — Context Refresh (Pipeline C)** `DONE`
  - ✅ `POST /series/{id}/refresh` — scrapes new content, calls `merge_timeline()`, archives old timeline, stores new one
  - ✅ Creates `ContextBuildJob(job_type="refresh")` with full timing

- [x] **Step 13 — Metrics endpoints** `DONE`
  - ✅ `GET /metrics` — combined view
  - ✅ `GET /metrics/context-builds` — avg scraping/timeline/total time + job count
  - ✅ `GET /metrics/episodes` — avg LLM time, total/rated episodes, avg quality rating
  - Pure `func.avg()` / `func.count()` aggregations

- [x] **Step 14 — Docker (Phase 1)** `DONE`
  - ✅ `Dockerfile` — `python:3.11-slim`, `uvicorn app.main:app --host 0.0.0.0 --port 8000`
  - ✅ `docker-compose.yml` — `api` service, port 8000, DB stored in `./data/` volume
  - ✅ `.dockerignore` — excludes `__pycache__`, `.env`, `*.db`, `.git`

- [x] **Scheduler** `DONE` *(woven into Step 14 / lifespan)*
  - ✅ `app/scheduler.py` — APScheduler `BackgroundScheduler`, Sunday 9am `CronTrigger`
  - ✅ Wired into FastAPI `lifespan` context manager — starts on boot, shuts down cleanly

---

## Phase 2 — Parallelism (after measuring Phase 1 bottleneck)

> Run 4 weeks of real data first. Measure. Only proceed if justified.

- [ ] **Step 15 — Async scraping** `NOT STARTED`
  - Refactor `scraper.py` to use `aiohttp` with `asyncio.gather`
  - `scrape_all()` becomes `async def scrape_all(...)`
  - Benchmark before and after

- [ ] **Step 16 — Redis + RQ workers** `NOT STARTED`
  - Write `workers/worker.py` — RQ worker entry point
  - Update `POST /episodes/run` to enqueue jobs instead of running inline
  - Add `GET /episodes/status` endpoint for polling

- [ ] **Step 17 — Docker Compose (Phase 2)** `NOT STARTED`
  - Add `redis` service and `worker` service with replica count
  - Wire `env_file` and `depends_on`

- [ ] **Step 18 — Benchmark** `NOT STARTED`
  - Write `scripts/benchmark.py` — batch with 1/2/4 workers, record times
  - Produces the resume talking-point table

---

## Phase 3 — Automated Refresh Detection

- [ ] **Step 19 — News monitor** `NOT STARTED`
  - Write `app/news_monitor.py`
  - `check_series_for_updates(series)` — hits NewsAPI/RSS, returns `True` if new articles since `last_refreshed_at`
  - `check_all_series()` — iterates `ready` series, auto-creates `ContextBuildJob(type="refresh")`

- [ ] **Step 20 — Daily scheduler job** `NOT STARTED`
  - Add daily 6am APScheduler job calling `check_all_series()`
  - Weekly Sunday job for `run_weekly_batch()` already exists (Step 14)

---

## Build Order at a Glance

```
Step 1   → scaffold                            ✅ DONE
Step 2   → DB models                           ✅ DONE
Step 3   → schemas                             ✅ DONE
Step 4   → scraper                             ✅ DONE
Step 5   → timeline builder                    ✅ DONE
Step 6   → LLM abstraction                     ✅ DONE
Step 7   → Pipeline A + series endpoints       ✅ DONE
Step 8   → modes + prompt builder              ✅ DONE
Step 8b  → series connections (knowledge graph)✅ DONE
Step 9   → Pipeline B (episode generation)     ✅ DONE
Step 10  → episode endpoints                   ✅ DONE
Step 11  → mailer + newsletter endpoints       ✅ DONE
Step 12  → Pipeline C (refresh)                ✅ DONE
Step 13  → metrics endpoints                   ✅ DONE
Step 14  → Docker + scheduler lifespan         ✅ DONE  ← PHASE 1 COMPLETE

         [measure — 4 weeks of real runs]

Step 15  → async scraping                      ⬜ NOT STARTED
Step 16  → Redis + RQ                          ⬜ NOT STARTED
Step 17  → Docker Phase 2                      ⬜ NOT STARTED
Step 18  → benchmark                           ⬜ NOT STARTED  ← Phase 2 complete

Step 19  → news monitor                        ⬜ NOT STARTED
Step 20  → daily scheduler                     ⬜ NOT STARTED  ← Phase 3 complete
```

---

## Measurement Gate (between Phase 1 and 2)

```sql
-- Context build performance
SELECT
  AVG(scraping_time_ms) as avg_scrape,
  AVG(timeline_time_ms) as avg_timeline,
  AVG(total_time_ms) as avg_total_build
FROM context_build_jobs WHERE status = 'done';

-- Weekly episode generation performance
SELECT
  AVG(llm_time_ms) as avg_llm,
  COUNT(*) as total_episodes
FROM episodes WHERE status = 'done';
```

| Question | Decision |
|---|---|
| Is avg_total_build > 2 minutes? | Context builds are bottleneck — go to Step 15 |
| Is avg_llm > 30s per episode? | Episode generation is bottleneck — go to Step 16 |
| Does a 5-series Sunday run take > 3 minutes? | Strong case for Phase 2 |
| Does a 5-series Sunday run take < 1 minute? | No bottleneck. Ship Phase 1 as-is. |
