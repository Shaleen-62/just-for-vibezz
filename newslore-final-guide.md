# NewsLore — Final Technical Build Guide
### "News as Stories, Week by Week" — A Backend Project Built the Right Way

---

## The Philosophy (Read This First)

Build simple. Measure. Scale only if needed. Every architectural decision must be
justified by real data, not theory.

The project has two goals:
1. **Personal**: A weekly newsletter that makes complex, context-heavy news digestible
   — told as gossip, drama, or stories, in episodes, like a TV show.
2. **Resume**: A backend system demonstrating pipeline design, web scraping,
   context-aware LLM integration, stateful content generation, and (potentially)
   distributed task management.

The storytelling is the product. The system is the star.

---

## The Core Idea (Read This Second)

Most news explainers are either too shallow or too dense. NewsLore fixes this by:
- Building a **deep, comprehensive timeline** for each topic once
- Using that timeline to generate **weekly episodic stories** — gossip, drama, cartoons
- Updating the timeline only when something significant actually happens

This means scraping and story generation are completely decoupled. Weekly runs are
fast and cheap. The timeline gets richer over time. Updates happen only when needed.

---

## How It Actually Works

### When You Create a New Series (One-Time)

You create a series called "The US-China Trade War." The system:

1. Does a **deep scrape** — Wikipedia + 3 news sources + any extra URLs you provide
2. Sends all scraped content to the LLM to build a **master timeline** — a
   comprehensive, conflict-aware, chronological record of everything up to today
3. Stores the master timeline in the database — this is the source of truth
4. Flags the series as "ready"

This happens once per series. It's slow. That's fine — it's supposed to be.

### Every Sunday (Weekly Run)

For each active series, the system:

1. Pulls the **master timeline** from the database — no scraping
2. Pulls the **previous episode's story** for continuity
3. Assigns a random **storytelling mode** (gossip, dramatic, explainer, cartoon)
4. Sends timeline + previous episode + mode to the LLM
5. Gets back a story with a "Previously on..." recap and a "Next week..." teaser
6. Stores the output
7. Compiles all stories into one newsletter and emails it out

Weekly runs are fast. The only LLM call is story generation.

### When Something New Happens (Context Refresh)

You manually flag a series for refresh — or eventually, automated news detection
does it. The system:

1. Scrapes for new information since the last timeline build
2. Sends the new content + existing master timeline to the LLM
3. LLM merges new events into the existing timeline — no full rebuild
4. Updated master timeline is stored, old one is archived with a timestamp

The timeline gets richer over time rather than being rebuilt from scratch.

---

## System Architecture — Three Distinct Pipelines

```
PIPELINE A — Context Build (one-time per series)
─────────────────────────────────────────────────
Input: series title + optional seed URLs
  ↓
scraper.py       → deep scrape: Wikipedia + 3 news sources
  ↓
timeline.py      → LLM builds master timeline from scraped content
  ↓
models.py        → store MasterTimeline, mark series as "ready"


PIPELINE B — Weekly Episode Generation (every Sunday)
──────────────────────────────────────────────────────
Input: active series list
  ↓
pipeline.py      → fetch master timeline + previous episode per series
  ↓
pipeline.py      → assign random mode, build story prompt
  ↓
LLM call         → generate story with recap + teaser
  ↓
models.py        → store Episode output with timing data
  ↓
mailer.py        → compile newsletter + send email


PIPELINE C — Context Refresh (on-demand)
─────────────────────────────────────────
Input: series flagged for refresh
  ↓
scraper.py       → scrape for new content since last build
  ↓
timeline.py      → LLM merges new content into existing master timeline
  ↓
models.py        → store updated MasterTimeline, archive old one
```

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| API | FastAPI (Python) | Modern, fast, async-native |
| Scraping | BeautifulSoup + requests | Free, no API key needed |
| Database | SQLite → PostgreSQL | Start simple, migrate if needed |
| ORM | SQLAlchemy | Consistent DB interface |
| LLM | Anthropic/OpenAI free tier OR Ollama | Abstract behind a function — swap freely |
| Task Queue | Redis + RQ (Phase 2 only) | Only if bottleneck is measured |
| Scheduler | APScheduler | Weekly batch, runs inside the app |
| Email | Resend or Gmail SMTP | Free tiers available |
| Containerization | Docker + Docker Compose | Clean, portable setup |
| Observability | Python logging + timing decorators | Measure everything from day one |

---

## Project Structure

```
newslore/
├── app/
│   ├── main.py              # FastAPI entrypoint
│   ├── models.py            # SQLAlchemy models
│   ├── database.py          # DB connection setup
│   ├── scraper.py           # Web scraping (Pipelines A + C)
│   ├── timeline.py          # Timeline build + merge logic (Pipelines A + C)
│   ├── pipeline.py          # Episode generation logic (Pipeline B)
│   ├── modes.py             # Storytelling mode prompts
│   ├── mailer.py            # Newsletter compilation + sending
│   ├── scheduler.py         # APScheduler weekly job
│   └── schemas.py           # Pydantic request/response models
├── workers/
│   └── worker.py            # (Phase 2) Worker process
├── scripts/
│   └── run_batch.py         # Manual batch trigger for testing
├── .env                     # API keys, config
├── requirements.txt
└── docker-compose.yml
```

---

## Database Models

### Series
Represents an ongoing story arc.

| Field | Type | Notes |
|---|---|---|
| id | int | primary key |
| title | str | e.g., "The US-China Trade War" |
| description | text | brief description of the arc |
| status | str | building / ready / needs_refresh |
| created_at | datetime | |
| last_refreshed_at | datetime | when context was last rebuilt |

### MasterTimeline
The source of truth for a series. A series can have multiple versions
(one per refresh), but only one is active at a time.

| Field | Type | Notes |
|---|---|---|
| id | int | primary key |
| series_id | int | foreign key → Series |
| content | text | the full structured timeline |
| confidence_score | int | LLM self-rated 1–10 |
| gaps | text | what the LLM flagged as missing |
| is_active | bool | only one active timeline per series |
| built_at | datetime | |
| superseded_at | datetime | nullable — set when a newer version replaces this |

### Episode
One week's generated story for a series.

| Field | Type | Notes |
|---|---|---|
| id | int | primary key |
| series_id | int | foreign key → Series |
| timeline_id | int | foreign key → MasterTimeline (which version was used) |
| episode_number | int | 1, 2, 3... auto-incremented |
| mode | str | gossip / dramatic / explainer / cartoon |
| content | text | the full generated story |
| quality_rating | int | nullable, 1–5, added manually after reading |
| status | str | pending / processing / done / failed |
| created_at | datetime | |
| llm_time_ms | int | time for story generation |

### ContextBuildJob
Tracks the work done during Pipeline A and C (scraping + timeline building).
Separate from Episode because this is expensive and happens rarely.

| Field | Type | Notes |
|---|---|---|
| id | int | primary key |
| series_id | int | foreign key → Series |
| job_type | str | initial_build / refresh |
| status | str | pending / processing / done / failed |
| scraping_time_ms | int | time to scrape all sources |
| timeline_time_ms | int | time to build/merge timeline |
| total_time_ms | int | end-to-end |
| created_at | datetime | |
| completed_at | datetime | nullable |

> **Why separate ContextBuildJob from Episode?**
> Because they are fundamentally different operations with different performance
> characteristics. Context builds are slow and rare. Episodes are fast and weekly.
> Mixing them in one table makes your metrics meaningless.

---

## Handling the Hard Problems

### Bias and Conflicting Narratives

Scraping multiple sources means conflicting descriptions of the same event.
Don't resolve this before the LLM — give the LLM the instruction explicitly:

```
"You will receive content from multiple sources. Some accounts may conflict.
Identify facts all sources agree on. Where narratives diverge, note it neutrally
with the label [DISPUTED]. Build the timeline from agreed facts only."
```

On the resume: **multi-source context aggregation with conflict-aware summarization**.

### Knowing When to Stop Scraping

Use a simple depth limit for Phase 1:
- Always scrape: Wikipedia main article
- Always scrape: 2–3 news sources (BBC, Reuters, Al Jazeera — pick 3)
- Accept any seed URLs you manually provide
- Stop there

In Phase 2, add gap detection: after building the timeline, ask the LLM
"what key information is missing?" If it flags a significant gap, scrape
one more targeted source. If not, stop.

### Knowing When a Refresh Is Needed

Phase 1: **Manual only.** You flag a series for refresh via API when you know
something significant happened.

Phase 2: Add a lightweight news monitor — once a day, search a free news API
or RSS feed for the series title. If new results appear, auto-flag for refresh.
This is a separate background job and does not block anything.

### Metrics Without Historical Data

You measure from day one. No baseline needed.

**System metrics (automatic, stored in DB):**
- Scraping time per source (ContextBuildJob)
- Timeline build time (ContextBuildJob)
- LLM story generation time (Episode)
- Total pipeline time per run

**Quality metrics (manual, takes 2 minutes after each newsletter):**
- Read each story, rate it 1–5 via `POST /episodes/{id}/rate`
- After 4 weeks you have a quality trend

**LLM self-assessment (imperfect but trackable):**
- Confidence score stored on MasterTimeline (1–10, LLM-rated)
- Gaps field shows what the LLM flagged as missing
- Low-confidence timelines get flagged for manual review before episode generation

---

## Storytelling Modes

```python
MODES = {
    "gossip": """You are a gossipy friend who has been following this story
                 obsessively. Explain it like you're spilling tea to someone
                 who just tuned in. Be dramatic, be catty, keep the facts straight.""",

    "dramatic": """You are a documentary narrator. Retell this as a gripping
                   chapter in a larger saga. Use tension, contrast, and weight.
                   Think Ken Burns.""",

    "explainer": """You are a patient, witty teacher explaining this to a curious
                    17-year-old who knows nothing about it. Simple language,
                    real stakes, no condescension.""",

    "cartoon": """You are a children's fable writer. Turn the key players into
                  animal characters, the conflict into a simple moral story.
                  Keep it accurate underneath the whimsy."""
}
```

---

## The Story Prompt Template

```python
def build_story_prompt(series, episode_number, timeline, mode, previous_story=None):
    recap = ""
    if previous_story:
        recap = f"""
        PREVIOUS EPISODE SUMMARY:
        {previous_story}
        Begin this episode with a one-sentence "Previously on {series.title}..." recap.
        """

    return f"""
    {recap}

    MASTER TIMELINE:
    {timeline.content}

    YOUR TASK:
    Write Episode {episode_number} of "{series.title}" in the following style:
    {MODES[mode]}

    REQUIREMENTS:
    - Start with "Previously on..." recap if a previous episode exists
    - Draw from the timeline above — stay factually grounded
    - Focus on one interesting angle or period from the timeline per episode
      (don't try to cover everything — leave material for future episodes)
    - End with: "Next week, we get into..." — hint at what's coming
    - Keep it under 500 words
    """
```

---

## API Endpoints

```
# Series management
POST   /series                        → Create a new series
GET    /series                        → List all series with status
GET    /series/{id}                   → Get series details

# Context building (Pipeline A + C)
POST   /series/{id}/build             → Trigger initial context build
POST   /series/{id}/refresh           → Trigger context refresh
GET    /series/{id}/timeline          → View current master timeline
GET    /context-jobs/{id}             → Check build/refresh job status

# Episode generation (Pipeline B)
POST   /episodes/run                  → Generate this week's episodes (manual trigger)
GET    /episodes                      → List all episodes
GET    /episodes/{id}                 → Get a specific episode
POST   /episodes/{id}/rate            → Rate story quality 1–5

# Newsletter
GET    /newsletter/preview            → Preview this week's compiled newsletter
POST   /newsletter/send               → Send the newsletter via email

# Metrics
GET    /metrics                       → Aggregated timing + quality data
GET    /metrics/context-builds        → Context build performance over time
GET    /metrics/episodes              → Episode generation performance over time
```

---

## Phase 1 — Deliverable Checklist

Before moving to Phase 2, confirm all of these:

- [ ] Series can be created via API
- [ ] Context build (Pipeline A) runs end-to-end for one series
- [ ] Master timeline is stored with confidence score and gaps
- [ ] Weekly episode generation (Pipeline B) runs for one series
- [ ] Episode has recap intro and teaser outro
- [ ] All timing fields recorded (scraping, timeline, LLM)
- [ ] Quality rating endpoint works
- [ ] Newsletter preview compiles correctly
- [ ] Email sends successfully
- [ ] At least 3 series created, at least 4 weekly runs completed

---

## The Measurement Gate

After 4 weeks of real runs, pull this from your DB:

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

Then answer:

| Question | Decision |
|---|---|
| Is avg_total_build > 2 minutes? | Context builds are the bottleneck — parallelize scraping |
| Is avg_llm > 30s per episode? | Episode generation is the bottleneck — parallelize LLM calls |
| Does a 5-series Sunday run take > 3 minutes? | Strong case for Phase 2 |
| Does a 5-series Sunday run take < 1 minute? | No bottleneck. Ship Phase 1. |

Either outcome is valid. The measurement is what makes this credible.

---

## Phase 2 — Parallel Processing (Only If Justified)

**Goal:** Context builds and/or episode generation run concurrently across series.

Since context builds and episode generation are now separate pipelines,
you can parallelize them independently based on where the actual bottleneck is.

### If Context Builds Are Slow — Parallelize Scraping

Within a single context build, scrape all sources concurrently:

```python
import asyncio
import aiohttp

async def scrape_all_sources(topic: str, sources: list) -> dict:
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_source(session, source, topic) for source in sources]
        results = await asyncio.gather(*tasks)
    return dict(zip(sources, results))
```

This alone can cut context build time significantly — 3 sequential HTTP
requests become 1 concurrent batch.

### If Episode Generation Is Slow — Use Redis Queue + Workers

```python
from redis import Redis
from rq import Queue

redis_conn = Redis()
q = Queue("newslore-episodes", connection=redis_conn)

# In POST /episodes/run, instead of processing inline:
for series in active_series:
    q.enqueue(generate_episode, series.id)
```

Workers run as separate processes:

```bash
rq worker newslore-episodes
```

### Docker Compose (Phase 2)

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env

  worker:
    build: .
    command: rq worker newslore-episodes
    depends_on:
      - redis
    env_file: .env
    deploy:
      replicas: 3

  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
```

### What You Measure in Phase 2

| Workers | Sunday Batch Time | Notes |
|---|---|---|
| 1 (sequential) | X seconds | from Phase 1 data |
| 2 workers | Y seconds | first parallel run |
| 4 workers | Z seconds | diminishing returns visible here |

This table is your resume talking point.

---

## Phase 2 — Deliverable Checklist

- [ ] Redis running via Docker
- [ ] Episode jobs enqueued and processed by workers
- [ ] `GET /episodes/status` endpoint for polling progress
- [ ] Benchmark table with 1 / 2 / 4 worker comparison documented
- [ ] Phase 1 vs Phase 2 batch time comparison documented in README

---

## Phase 3 — Automated Refresh Detection

**Goal:** System detects when a series needs a context refresh without you manually flagging it.

Use a free RSS feed or news API (NewsAPI has a free tier) to monitor series titles daily.
If new articles appear, auto-flag the series for refresh:

```python
def check_for_updates(series: Series) -> bool:
    # Search RSS / news API for series title
    # If results newer than series.last_refreshed_at exist → return True
    ...

scheduler.add_job(check_all_series_for_updates, 'cron', hour=6)  # runs daily at 6am
```

This is a background job. It does not block anything. If it finds updates,
it creates a ContextBuildJob with type="refresh" and the existing refresh
pipeline handles it.

---

## Resume Write-Up (Fill In Real Numbers Later)

> **NewsLore** — Episodic News Intelligence Pipeline
> Python · FastAPI · SQLAlchemy · BeautifulSoup · Redis · Docker
>
> Built a backend system that transforms complex news topics into episodic,
> narrative-style stories for a weekly newsletter. Architecture separates
> context building (one-time deep scrape + conflict-aware timeline construction
> using multi-source aggregation) from weekly episode generation (stateful
> story generation with episode continuity — each story references last week's
> output and teases next week's). Tracked per-stage latency across both pipelines
> from day one. After measuring [X] across [N] series, introduced [parallel
> scraping with asyncio / Redis worker queue] reducing [context build / batch]
> time from [A]s to [B]s. Deployed via Docker Compose with automated weekly
> scheduling and daily refresh detection.

Fill in the brackets with real numbers. That specificity is what makes it credible.

---

## What to Build This Week

Nothing more than this:

1. Set up project structure and git repo
2. Create all database models with SQLAlchemy
3. Build the scraper — get Wikipedia text for one topic, print it to console
4. Build `POST /series` and `POST /series/{id}/build` endpoints
5. Run Pipeline A end-to-end for one series — scrape, build timeline, store it

No episodes. No email. No scheduler. No modes yet.
Just one series with a master timeline stored in the database.

That's the week.

---

## Quick Reference — Commands

```bash
# Install dependencies
pip install fastapi uvicorn sqlalchemy pydantic apscheduler \
            redis rq python-dotenv requests beautifulsoup4 \
            aiohttp anthropic resend

# Run API
uvicorn app.main:app --reload

# Run worker (Phase 2 only)
rq worker newslore-episodes

# Run Redis locally (Phase 2 only)
docker run -p 6379:6379 redis:alpine

# Run full stack (Phase 2+)
docker-compose up
```

---

*This is a living document. Update timing benchmarks, quality ratings,
and architectural decisions as you build and measure.*
