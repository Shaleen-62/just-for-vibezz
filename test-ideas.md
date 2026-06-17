# NewsLore — Test Ideas & Phase 2 Gate Evaluation

Work through these tests in order. By the end you will have:
- Verified every pipeline end-to-end
- A timing dataset in the DB ready to query the Phase 2 gate
- A newsletter preview you can read to assess story quality
- An honest read on whether async scraping or a worker queue is actually needed

Open `http://localhost:8000/docs` for Swagger UI. Keep a terminal open with `sqlite3 newslore.db` for DB inspection.

---

## Before You Start

```powershell
# Reset to a clean slate
Remove-Item newslore.db   # if it exists
uvicorn app.main:app --reload
```

```sql
-- In sqlite3 shell, turn on readable output
.mode column
.headers on
```

---

## Test 1 — Single Series, Full Pipeline A → B

**Goal:** Verify Pipeline A produces a real timeline and Pipeline B produces a readable story.

**Series to create:**

> Title: `Ukraine War`
> Description: `Focus on the military conflict timeline, key turning points, Western arms supply, and the grain/energy dimension of the war.`

**Steps in Swagger UI:**

1. `POST /series` — create the series. Note the `id` returned (call it `S1`).
2. `POST /series/{S1}/build` — starts Pipeline A. Note the `id` of the returned job (call it `J1`). The response comes back immediately with `status: processing`.
3. Watch the terminal — you'll see scraping logs per source, then timeline build. Takes 1–3 minutes.
4. `GET /context-jobs/{J1}` — confirm `status: done`. Check `scraping_time_ms`, `timeline_time_ms`, `total_time_ms`. Write these down — they're your Phase 2 baseline.
5. `GET /series/{S1}` — confirm `status: ready`.
6. `GET /series/{S1}/timeline` — read the timeline. Check: is it chronological? Does it mention key events (2022 invasion, Kharkiv counteroffensive, Bakhmut, grain deal, F-16s)? Is `confidence_score` ≥ 6? Are the `gaps` reasonable?
7. `GET /series/{S1}/connections` — the LLM should have suggested 3–5 related topics. Read the `relationship_hint` for each. Are they plausible (e.g. NATO expansion, Zelensky, energy crisis, Russia sanctions)?
8. `POST /series/{S1}/episode` — generates Episode 1. Note the `llm_time_ms`.
9. `GET /episodes/{episode_id}` — read the full story. Check:
   - Does it open with a "Previously on..." line? (No — it's Episode 1, so there should be none.)
   - Does it have a "Next week, we get into..." teaser at the end?
   - Is it under 500 words?
   - Is the storytelling mode's voice clear (gossip vs. documentary vs. explainer vs. cartoon)?
10. `POST /episodes/{episode_id}/rate` — rate it 1–5 with `{ "rating": N }`.

**DB verification:**

```sql
SELECT id, title, status, discovery_depth FROM series;
SELECT id, series_id, confidence_score, is_active, length(content) AS chars FROM master_timelines;
SELECT id, series_id, job_type, scraping_time_ms, timeline_time_ms, total_time_ms FROM context_build_jobs;
SELECT id, episode_number, mode, status, quality_rating, llm_time_ms FROM episodes;
SELECT id, connected_topic, status, relationship_hint FROM series_connections WHERE series_id = 1;
```

**Pass criteria:**
- Timeline has `confidence_score` ≥ 5
- Timeline content is > 2,000 characters
- Episode `status = done`
- Episode ends with a "Next week" teaser
- At least 3 connection suggestions exist

---

## Test 2 — Knowledge Graph: Two Connected Series

**Goal:** Verify that approved connections actually enrich episode prompts with cross-series context.

**Series to create:**

> Title: `US-China Trade War`
> Description: `Focus on tariff escalation from 2018 onwards, tech decoupling, Huawei and TSMC restrictions, and the fentanyl/dollar diplomacy dimension.`

**Steps in Swagger UI:**

1. `POST /series` — create. Note id as `S2`.
2. `POST /series/{S2}/build` — run Pipeline A. Wait for completion.
3. `GET /series/{S2}/connections` — look for a suggestion that mentions COVID-19, pandemic supply chains, or something clearly linked to the Ukraine War series you already built.
4. Find the connection suggestion that links to `Ukraine War` or to a topic that overlaps with `S1`. `POST /connections/{connection_id}/approve` — this creates a new series (call it `S3`) with `status: building` and `discovery_depth: 1`. Note the returned series id.
5. `POST /series/{S3}/build` — build S3's timeline. This auto-links it to S2 via the approved connection.
6. Once both S2 and S3 are `ready`, `POST /series/{S2}/episode` — generate an episode.
7. `GET /episodes/{new_episode_id}` — read it. It should contain a `RELATED CONTEXT` section drawn from S3's timeline. Look for references to both topics in the same story.

**DB verification:**

```sql
-- Check connection was approved and linked
SELECT id, series_id, connected_topic, connected_series_id, status
FROM series_connections;

-- Both series should be ready
SELECT id, title, status, discovery_depth FROM series;

-- Episode's related context shows up in the prompt — verify the story references both topics
SELECT id, episode_number, mode, length(content), llm_time_ms FROM episodes WHERE series_id = 2;
```

**Pass criteria:**
- Connection `status = approved` and `connected_series_id` is set
- S3 has `discovery_depth = 1`
- The episode for S2 mentions S3's topic or events somewhere in the story

---

## Test 3 — Multi-Series Batch + Newsletter Preview

**Goal:** Run the full weekly batch across all ready series and verify the newsletter compiles correctly. This is the closest simulation of real Sunday operation without actually sending email.

**Series to have ready before this test:** S1 (Ukraine War) and S2 (US-China Trade War) from Tests 1 and 2. If either is not `ready`, fix them first.

**Steps in Swagger UI:**

1. `POST /episodes/run` — triggers the batch for all `ready` series. The response is a list of all generated episodes. Note the `llm_time_ms` for each.
2. `GET /episodes` — confirm two new episodes exist (one per series), both `status: done`.
3. `GET /newsletter/preview` — returns the compiled HTML. Copy the `content` field into a browser or an HTML file and open it. Check:
   - Both series appear with their title and episode number
   - The storytelling mode label is visible (e.g. "GOSSIP", "DRAMATIC")
   - Layout renders cleanly (no broken HTML)
   - Each story has a "Next week" teaser
4. `GET /metrics` — read the aggregated numbers. You now have at least 2 context build jobs and 2+ episodes recorded.

**DB verification:**

```sql
-- Both series should have 2+ episodes now (Episode 1 from Test 1/2, Episode 2 from this batch)
SELECT series_id, COUNT(*) AS episode_count, AVG(llm_time_ms) AS avg_llm_ms
FROM episodes WHERE status = 'done'
GROUP BY series_id;

-- Phase 2 gate query — run this after this test
SELECT
  ROUND(AVG(scraping_time_ms) / 1000.0, 1) AS avg_scrape_s,
  ROUND(AVG(timeline_time_ms) / 1000.0, 1) AS avg_timeline_s,
  ROUND(AVG(total_time_ms)    / 1000.0, 1) AS avg_total_s,
  COUNT(*) AS total_jobs
FROM context_build_jobs WHERE status = 'done';

SELECT
  ROUND(AVG(llm_time_ms) / 1000.0, 1) AS avg_llm_s,
  COUNT(*) AS total_episodes
FROM episodes WHERE status = 'done';
```

**Pass criteria:**
- `/episodes/run` returns 2 episodes, both `status: done`
- Newsletter preview HTML is non-empty and renders both series
- Metrics endpoint returns non-null averages

---

## Test 4 — Pipeline C (Context Refresh)

**Goal:** Verify that re-scraping merges new content without destroying the existing timeline, and that the old version is properly archived.

**Use S1 (Ukraine War) from Test 1.**

**Steps in Swagger UI:**

1. `GET /series/{S1}/timeline` — note the current `id` (call it `TL1`) and `built_at`. Copy the first 200 characters of `content` — you'll check that the refreshed timeline extends this, not replaces it.
2. `POST /series/{S1}/refresh` — starts Pipeline C. Returns a job with `job_type: refresh`.
3. Wait for completion. `GET /context-jobs/{job_id}` — confirm `status: done`.
4. `GET /series/{S1}/timeline` — this should be a **new** timeline with a newer `built_at`. The `id` should be different from TL1.
5. Check that the content of the new timeline is at least as long as the old one (it merged, not replaced).

**DB verification:**

```sql
-- Should show two timelines for series 1: one active, one archived
SELECT id, series_id, is_active, built_at, superseded_at, length(content) AS chars
FROM master_timelines WHERE series_id = 1
ORDER BY built_at;

-- Two jobs for series 1: one initial_build, one refresh
SELECT id, job_type, status, total_time_ms FROM context_build_jobs WHERE series_id = 1;
```

**Pass criteria:**
- Old timeline has `is_active = 0` and `superseded_at` is set
- New timeline has `is_active = 1`
- New timeline's `content` length ≥ old timeline's `content` length (merge, not shrink)

---

## Test 5 — Third Series + Episode Continuity

**Goal:** Generate a second episode for a series and verify the "Previously on..." recap appears, proving episode-to-episode continuity works.

**Series to create:**

> Title: `Global AI Regulation`
> Description: `Focus on the EU AI Act, US executive orders on AI, China's generative AI rules, and the tension between innovation and safety governance.`

**Steps in Swagger UI:**

1. `POST /series` → `POST /series/{id}/build` — build normally. Note id as `S4`.
2. `POST /series/{S4}/episode` — generate Episode 1. Read it. No "Previously on..." expected.
3. `POST /series/{S4}/episode` — generate Episode 2. Read it. Should open with "Previously on Global AI Regulation..." referencing something from Episode 1.
4. `POST /episodes/{ep1_id}/rate` and `POST /episodes/{ep2_id}/rate` — rate both. Compare quality scores.

**DB verification:**

```sql
-- Confirm episode numbers increment and previous episode content flows through
SELECT id, episode_number, mode, quality_rating, llm_time_ms,
       substr(content, 1, 150) AS preview
FROM episodes WHERE series_id = 4
ORDER BY episode_number;
```

**Pass criteria:**
- Episode 2 content starts with "Previously on..."
- Both episodes have `status = done`
- The two episodes cover different angles (Episode 2 shouldn't just repeat Episode 1)

---

## Phase 2 Gate Evaluation

After completing all five tests, run the gate queries from Test 3 and fill in this table:

| Metric | Your result | Phase 2 threshold |
|---|---|---|
| Avg context build total time | ___s | > 120s → consider async scraping |
| Avg episode LLM time | ___s | > 30s → consider worker queue |
| 3-series Sunday batch total | ___s | > 180s → strong case for Phase 2 |
| Avg story quality rating | ___ / 5 | < 3 → fix prompts before scaling |

**How to time the Sunday batch manually:**

Note the time before `POST /episodes/run`, note the time when the response returns. That's your batch wall time for N ready series.

**Decision guide:**

- If all three time thresholds are comfortably under → Phase 1 is fast enough. Skip Phase 2 and go to Phase 3 (automated refresh detection).
- If context build is the slow part → Phase 2 Step 15 (async scraping with asyncio).
- If episode generation is the slow part → Phase 2 Step 16 (Redis + RQ workers).
- If story quality is consistently ≤ 2 → fix the prompts in `app/modes.py` and `app/timeline.py` before worrying about performance at all.

Since the newsletter isn't live yet, the quality rating you assign in these tests is the only feedback signal. Rate honestly — it's the data you need.

---

## Bonus: Edge Cases Worth Trying

These aren't required for the Phase 2 decision but are good to try when you have time.

**Obscure topic (low Wikipedia coverage)**
> Title: `2023 Wagner Group Mutiny`
> Description: `The Prigozhin rebellion — focus on the 24-hour march on Moscow, its aftermath, and what it revealed about Russian military fragility.`
> Expected: Lower `confidence_score` (maybe 4–6), larger `gaps` field. Good test of graceful degradation.

**Highly connected topic (many cross-links)**
> Title: `COVID-19 Pandemic`
> Description: `Focus on origin timeline, vaccine development race, economic shutdowns, and long-term geopolitical shifts it triggered.`
> Expected: The connection suggestions should overlap with both Ukraine War (supply chains, energy) and US-China Trade War (decoupling, PPE dependency). Good test of the knowledge graph breadth.

**Refresh right after build (minimal new content)**
Run `POST /series/{id}/refresh` on a series you built 5 minutes ago. Expected: the merged timeline should be nearly identical to the original. Verify `confidence_score` doesn't drop and content length doesn't shrink. Tests that the merge prompt doesn't hallucinate new events when there are none.
