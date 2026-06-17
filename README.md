# NewsLore

A backend system that turns complex news topics into episodic, narrative-style stories delivered as a weekly newsletter. Topics are scraped once to build a deep master timeline; weekly runs draw from that timeline to generate new story episodes in rotating styles — gossip, documentary, explainer, or cartoon fable.

---

## How It Works

**Pipeline A — Context Build (one-time per series)**
Deep-scrape Wikipedia + three news sources → LLM builds a conflict-aware master timeline → stored as source of truth.

**Pipeline B — Weekly Episode Generation (every Sunday)**
Pull timeline from DB → pick a random storytelling mode → generate a 500-word episode with a "Previously on..." recap and a "Next week..." teaser → compile and email the newsletter.

**Pipeline C — Context Refresh (on-demand)**
Re-scrape for new content → LLM merges it into the existing timeline → old version archived, new version activated.

Scraping and story generation are fully decoupled. Weekly runs touch no scrapers; the timeline grows incrementally over time.

---

## Setup

**1. Clone and create a virtual environment**

```bash
git clone <repo-url>
cd newslore
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

**2. Configure environment variables**

Copy `.env.example` to `.env` and fill in your keys:

```env
GROQ_API_KEY=gsk_...
RESEND_API_KEY=re_...
NEWSLETTER_FROM_EMAIL=newsletter@yourdomain.com
NEWSLETTER_TO_EMAIL=you@example.com
DATABASE_URL=sqlite:///./newslore.db
```

- **Groq key**: [console.groq.com](https://console.groq.com) — free tier, no credit card
- **Resend key**: [resend.com](https://resend.com) — free tier, requires a verified sender domain

**3. Run the API**

```bash
uvicorn app.main:app --reload
```

API is at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

---

## Running with Docker

```bash
docker-compose up --build
```

The database is persisted in a `./data/` volume. Set env vars in your `.env` file — it's passed through automatically.

---

## Typical Workflow

```
1. Create a series
   POST /series
   { "title": "US-China Trade War", "description": "Focus on tariff escalation and tech decoupling" }

2. Build its context (Pipeline A — slow, one-time)
   POST /series/{id}/build

3. Check the timeline once it's done
   GET /series/{id}/timeline

4. Review suggested cross-topic connections
   GET /series/{id}/connections
   POST /connections/{id}/approve   → creates a new linked series, run /build on it next

5. Generate an episode (or wait for the Sunday scheduler)
   POST /series/{id}/episode

6. Preview and send the newsletter
   GET  /newsletter/preview
   POST /newsletter/send
```

---

## API Reference

### Series

| Method | Path | Description |
|---|---|---|
| `POST` | `/series` | Create a new series |
| `GET` | `/series` | List all series |
| `GET` | `/series/{id}` | Get one series |
| `DELETE` | `/series/{id}` | Delete series and all child records |

### Pipelines

| Method | Path | Description |
|---|---|---|
| `POST` | `/series/{id}/build` | Pipeline A — initial scrape + timeline build |
| `POST` | `/series/{id}/refresh` | Pipeline C — re-scrape and merge into existing timeline |
| `GET` | `/series/{id}/timeline` | View active master timeline |
| `DELETE` | `/series/{id}/timeline` | Delete active timeline, reset series to building |
| `GET` | `/context-jobs/{id}` | Check build/refresh job status and timing |

### Connections (Knowledge Graph)

| Method | Path | Description |
|---|---|---|
| `GET` | `/series/{id}/connections` | List suggested/approved connections for a series |
| `POST` | `/connections/{id}/approve` | Approve a suggestion — creates a new linked series |
| `DELETE` | `/connections/{id}` | Dismiss a suggestion |

### Episodes

| Method | Path | Description |
|---|---|---|
| `POST` | `/episodes/run` | Generate one episode for every ready series |
| `POST` | `/series/{id}/episode` | Generate one episode for a single series |
| `GET` | `/episodes` | List all episodes (optional `?series_id=` filter) |
| `GET` | `/episodes/{id}` | Get one episode |
| `POST` | `/episodes/{id}/rate` | Rate story quality 1–5 |

### Newsletter

| Method | Path | Description |
|---|---|---|
| `GET` | `/newsletter/preview` | Compile this week's episodes into HTML without sending |
| `POST` | `/newsletter/send` | Compile and send the newsletter via Resend |

Both accept an optional `?days=7` query param to control the lookback window.

### Metrics

| Method | Path | Description |
|---|---|---|
| `GET` | `/metrics` | Combined view |
| `GET` | `/metrics/context-builds` | Avg scraping/timeline/total time + job count |
| `GET` | `/metrics/episodes` | Avg LLM time, total/rated episodes, avg quality rating |

---

## Project Structure

```
app/
├── main.py          FastAPI app, all endpoints, lifespan (scheduler + DB init)
├── models.py        SQLAlchemy models: Series, MasterTimeline, Episode, ContextBuildJob, SeriesConnection
├── schemas.py       Pydantic request/response models
├── database.py      Engine, SessionLocal, get_db()
├── scraper.py       Wikipedia + DuckDuckGo + news sources
├── timeline.py      build_master_timeline(), merge_timeline(), discover_related_topics()
├── pipeline.py      generate_episode(), run_weekly_batch()
├── modes.py         MODES dict and build_story_prompt()
├── mailer.py        compile_newsletter(), send_newsletter()
└── scheduler.py     APScheduler — Sunday 9am weekly batch
```

---

## Storytelling Modes

Each episode is assigned a random mode:

- **gossip** — spilling tea on the story like a gossipy friend
- **dramatic** — documentary narrator, Ken Burns energy
- **explainer** — patient teacher explaining to a curious 17-year-old
- **cartoon** — children's fable with animal characters, accurate underneath the whimsy

---

## Knowledge Graph

After Pipeline A builds a timeline, it runs a second LLM call to discover 3–5 causally connected topics. These are stored as `suggested` connections. You review and approve them — approved connections get their own series, and once built, their timelines are woven into future episode prompts via a `RELATED CONTEXT` block.

Discovery is depth-limited: roots (depth 0) can discover, their children (depth 1) can discover, grandchildren (depth 2) cannot. This prevents unbounded expansion.

---

## Scheduler

The API starts an APScheduler `BackgroundScheduler` on boot. It runs `POST /episodes/run` automatically every Sunday at 9am. You can also trigger it manually at any time via the endpoint.

---

## Database Commands

All commands below assume you are in the project root and the server is stopped (unless noted).

### Reset the database

Required whenever the schema changes (new columns, new tables). All data is lost.

```powershell
# Windows
Remove-Item newslore.db

# macOS / Linux
rm newslore.db
```

Restart the server — `create_all` in the lifespan will recreate every table.

### Open the SQLite shell

```powershell
# Windows (sqlite3.exe must be on PATH — download from https://sqlite.org/download.html)
sqlite3 newslore.db

# macOS / Linux
sqlite3 newslore.db
```

Useful shell commands once inside:

```sql
.tables                          -- list all tables
.schema series                   -- show CREATE TABLE for one table
.mode column                     -- align output into columns
.headers on                      -- show column names in output
.quit                            -- exit
```

### Inspect state

```sql
-- All series and their status
SELECT id, title, status, discovery_depth, last_refreshed_at FROM series;

-- All timelines (active and archived)
SELECT id, series_id, confidence_score, is_active, built_at FROM master_timelines;

-- All context build jobs with timing
SELECT id, series_id, job_type, status, scraping_time_ms, timeline_time_ms, total_time_ms
FROM context_build_jobs ORDER BY created_at DESC;

-- All episodes with mode and quality rating
SELECT id, series_id, episode_number, mode, status, quality_rating, llm_time_ms
FROM episodes ORDER BY created_at DESC;

-- All connection suggestions for a series (replace 1 with your series id)
SELECT id, connected_topic, status, relationship_hint FROM series_connections WHERE series_id = 1;
```

### Performance summary (Phase 2 gate query)

```sql
-- Context build averages
SELECT
  ROUND(AVG(scraping_time_ms) / 1000.0, 1) AS avg_scrape_s,
  ROUND(AVG(timeline_time_ms) / 1000.0, 1) AS avg_timeline_s,
  ROUND(AVG(total_time_ms)    / 1000.0, 1) AS avg_total_s,
  COUNT(*) AS total_jobs
FROM context_build_jobs WHERE status = 'done';

-- Episode generation averages
SELECT
  ROUND(AVG(llm_time_ms) / 1000.0, 1) AS avg_llm_s,
  COUNT(*) AS total_episodes,
  ROUND(AVG(quality_rating), 2) AS avg_quality
FROM episodes WHERE status = 'done';
```

### Insert a series directly (bypass the API)

Useful for seeding test data without waiting for the server.

```sql
INSERT INTO series (title, description, status, discovery_depth, created_at)
VALUES (
  'Silicon Valley Bank Collapse',
  'Focus on contagion risk, Fed rate hikes, and the startup funding freeze',
  'building',
  0,
  datetime('now')
);
```

Run `SELECT last_insert_rowid();` immediately after to get the new series id.

### Wipe one series cleanly (via API, cascade-safe)

```
DELETE /series/{id}
```

This cascades to timelines, episodes, context jobs, and connections. Prefer this over direct SQL deletes.

---

## Phase Roadmap

| Phase | Status | Goal |
|---|---|---|
| Phase 1 | **Complete** | Full pipeline A/B/C, newsletter, metrics, Docker, scheduler |
| Phase 2 | Not started | Measure bottleneck → parallelize scraping (asyncio) or episode generation (Redis + RQ workers) |
| Phase 3 | Not started | Automated refresh detection via RSS/NewsAPI daily scan |

Phase 2 is gated on 4 weeks of real timing data from Phase 1. See `newslore-implementation-plan.md` for the measurement gate criteria.
