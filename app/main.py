import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.mailer import compile_newsletter, send_newsletter
from app.models import ContextBuildJob, Episode, MasterTimeline, Series, SeriesConnection
from app.pipeline import generate_episode, run_weekly_batch
from app.scheduler import start_scheduler
from app.schemas import (
    ContextBuildMetrics,
    ContextJobResponse,
    EpisodeMetrics,
    EpisodeRateRequest,
    EpisodeResponse,
    MetricsResponse,
    NewsletterPreviewResponse,
    NewsletterSendResponse,
    SeriesConnectionResponse,
    SeriesCreate,
    SeriesResponse,
    TimelineResponse,
)
from app.scraper import scrape_all
from app.timeline import build_master_timeline, discover_related_topics, merge_timeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="NewsLore", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

@app.post("/series", response_model=SeriesResponse, status_code=201)
def create_series(payload: SeriesCreate, db: Session = Depends(get_db)):
    series = Series(title=payload.title, description=payload.description, status="building")
    db.add(series)
    db.commit()
    db.refresh(series)
    logger.info("Created series %d: %s", series.id, series.title)
    return series


@app.get("/series", response_model=List[SeriesResponse])
def list_series(db: Session = Depends(get_db)):
    return db.query(Series).order_by(Series.created_at.desc()).all()


@app.get("/series/{series_id}", response_model=SeriesResponse)
def get_series(series_id: int, db: Session = Depends(get_db)):
    series = db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    return series


@app.delete("/series/{series_id}", status_code=204)
def delete_series(series_id: int, db: Session = Depends(get_db)):
    """Deletes a series and all its timelines, episodes, build jobs, and connections."""
    series = db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    db.delete(series)
    db.commit()


# ---------------------------------------------------------------------------
# Pipeline A — initial context build
# ---------------------------------------------------------------------------

@app.post("/series/{series_id}/build", response_model=ContextJobResponse, status_code=202)
def build_series(series_id: int, seed_urls: Optional[List[str]] = None, db: Session = Depends(get_db)):
    series = db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    if series.status == "ready":
        raise HTTPException(status_code=409, detail="Series already built. Use /refresh to update.")

    job = ContextBuildJob(series_id=series_id, job_type="initial_build", status="processing")
    db.add(job)
    series.status = "building"
    db.commit()
    db.refresh(job)

    t_total = time.time()

    # Scraping
    logger.info("Pipeline A: scraping for series %d (%s)", series_id, series.title)
    t_scrape = time.time()
    scraped = scrape_all(series.title, description=series.description or "", seed_urls=seed_urls or [])
    scraping_time_ms = int((time.time() - t_scrape) * 1000)

    if not scraped:
        job.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail="Scraping returned no content")

    # Timeline build
    logger.info("Pipeline A: building timeline for series %d", series_id)
    t_timeline = time.time()
    result = build_master_timeline(series.title, scraped, description=series.description or "")
    timeline_time_ms = int((time.time() - t_timeline) * 1000)

    timeline = MasterTimeline(
        series_id=series_id,
        content=result["content"],
        confidence_score=result["confidence_score"],
        gaps=result["gaps"],
        is_active=True,
    )
    db.add(timeline)

    series.status = "ready"
    series.last_refreshed_at = datetime.now(timezone.utc)

    total_time_ms = int((time.time() - t_total) * 1000)
    job.status = "done"
    job.scraping_time_ms = scraping_time_ms
    job.timeline_time_ms = timeline_time_ms
    job.total_time_ms = total_time_ms
    job.completed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(job)
    db.refresh(timeline)

    logger.info(
        "Pipeline A done for series %d — scrape: %dms, timeline: %dms, total: %dms",
        series_id, scraping_time_ms, timeline_time_ms, total_time_ms,
    )

    # Discover related topics (depth-limited to prevent runaway expansion)
    if series.discovery_depth < 2:
        logger.info("Pipeline A: discovering related topics for series %d", series_id)
        related = discover_related_topics(series.title, timeline.content)
        for r in related:
            db.add(SeriesConnection(
                series_id=series_id,
                connected_topic=r["topic"],
                relationship_hint=r["relationship_hint"],
                status="suggested",
            ))
        if related:
            db.commit()
            logger.info("Stored %d connection suggestions for series %d", len(related), series_id)

    return job


# ---------------------------------------------------------------------------
# Pipeline C — context refresh
# ---------------------------------------------------------------------------

@app.post("/series/{series_id}/refresh", response_model=ContextJobResponse, status_code=202)
def refresh_series(series_id: int, seed_urls: Optional[List[str]] = None, db: Session = Depends(get_db)):
    """Re-scrapes and merges new content into the existing timeline. Archives the old version."""
    series = db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    if series.status == "building":
        raise HTTPException(status_code=409, detail="Initial build still in progress.")

    existing_timeline = (
        db.query(MasterTimeline)
        .filter(MasterTimeline.series_id == series_id, MasterTimeline.is_active == True)
        .first()
    )
    if not existing_timeline:
        raise HTTPException(status_code=404, detail="No existing timeline to refresh. Run /build first.")

    job = ContextBuildJob(series_id=series_id, job_type="refresh", status="processing")
    db.add(job)
    series.status = "needs_refresh"
    db.commit()
    db.refresh(job)

    t_total = time.time()

    # Scraping
    t_scrape = time.time()
    scraped = scrape_all(series.title, description=series.description or "", seed_urls=seed_urls or [])
    scraping_time_ms = int((time.time() - t_scrape) * 1000)

    if not scraped:
        job.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail="Scraping returned no content")

    # Merge into existing timeline
    t_timeline = time.time()
    result = merge_timeline(series.title, existing_timeline.content, scraped)
    timeline_time_ms = int((time.time() - t_timeline) * 1000)

    # Archive old timeline
    existing_timeline.is_active = False
    existing_timeline.superseded_at = datetime.now(timezone.utc)

    # Store new timeline
    new_timeline = MasterTimeline(
        series_id=series_id,
        content=result["content"],
        confidence_score=result["confidence_score"],
        gaps=result["gaps"],
        is_active=True,
    )
    db.add(new_timeline)

    series.status = "ready"
    series.last_refreshed_at = datetime.now(timezone.utc)

    total_time_ms = int((time.time() - t_total) * 1000)
    job.status = "done"
    job.scraping_time_ms = scraping_time_ms
    job.timeline_time_ms = timeline_time_ms
    job.total_time_ms = total_time_ms
    job.completed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(job)

    logger.info("Pipeline C done for series %d — total: %dms", series_id, total_time_ms)
    return job


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

@app.get("/series/{series_id}/timeline", response_model=TimelineResponse)
def get_timeline(series_id: int, db: Session = Depends(get_db)):
    series = db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    timeline = (
        db.query(MasterTimeline)
        .filter(MasterTimeline.series_id == series_id, MasterTimeline.is_active == True)
        .first()
    )
    if not timeline:
        raise HTTPException(status_code=404, detail="No active timeline found. Run /build first.")
    return timeline


@app.delete("/series/{series_id}/timeline", status_code=204)
def delete_timeline(series_id: int, db: Session = Depends(get_db)):
    """Deletes the active timeline, resetting status to building."""
    timeline = (
        db.query(MasterTimeline)
        .filter(MasterTimeline.series_id == series_id, MasterTimeline.is_active == True)
        .first()
    )
    if not timeline:
        raise HTTPException(status_code=404, detail="No active timeline found")
    db.delete(timeline)
    series = db.get(Series, series_id)
    if series:
        series.status = "building"
    db.commit()


# ---------------------------------------------------------------------------
# Series connections
# ---------------------------------------------------------------------------

@app.get("/series/{series_id}/connections", response_model=List[SeriesConnectionResponse])
def get_connections(series_id: int, db: Session = Depends(get_db)):
    series = db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    return (
        db.query(SeriesConnection)
        .filter(SeriesConnection.series_id == series_id)
        .order_by(SeriesConnection.created_at)
        .all()
    )


@app.post("/connections/{connection_id}/approve", response_model=SeriesResponse, status_code=201)
def approve_connection(connection_id: int, db: Session = Depends(get_db)):
    """Creates a new Series for the connected topic. Run /build on the returned series next."""
    conn = db.get(SeriesConnection, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    if conn.status != "suggested":
        raise HTTPException(status_code=409, detail=f"Connection is already '{conn.status}'")

    parent = db.get(Series, conn.series_id)
    new_depth = (parent.discovery_depth + 1) if parent else 1

    new_series = Series(
        title=conn.connected_topic,
        description=conn.relationship_hint,
        status="building",
        discovery_depth=new_depth,
    )
    db.add(new_series)
    db.flush()

    conn.connected_series_id = new_series.id
    conn.status = "approved"
    db.commit()
    db.refresh(new_series)
    return new_series


@app.delete("/connections/{connection_id}", status_code=204)
def dismiss_connection(connection_id: int, db: Session = Depends(get_db)):
    conn = db.get(SeriesConnection, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    conn.status = "dismissed"
    db.commit()


# ---------------------------------------------------------------------------
# Context build job status
# ---------------------------------------------------------------------------

@app.get("/context-jobs/{job_id}", response_model=ContextJobResponse)
def get_context_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(ContextBuildJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ---------------------------------------------------------------------------
# Pipeline B — episode generation
# ---------------------------------------------------------------------------

@app.post("/episodes/run", response_model=List[EpisodeResponse])
def run_episodes(db: Session = Depends(get_db)):
    """Generates one episode for every ready series. The manual weekly batch trigger."""
    episodes = run_weekly_batch(db)
    if not episodes:
        raise HTTPException(status_code=404, detail="No ready series found.")
    return episodes


@app.post("/series/{series_id}/episode", response_model=EpisodeResponse, status_code=201)
def run_single_episode(series_id: int, db: Session = Depends(get_db)):
    """Generates one episode for a single series. Good for testing."""
    series = db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    if series.status != "ready":
        raise HTTPException(status_code=409, detail="Series is not ready. Run /build first.")
    return generate_episode(series, db)


@app.get("/episodes", response_model=List[EpisodeResponse])
def list_episodes(series_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Episode).order_by(Episode.created_at.desc())
    if series_id:
        query = query.filter(Episode.series_id == series_id)
    return query.all()


@app.get("/episodes/{episode_id}", response_model=EpisodeResponse)
def get_episode(episode_id: int, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    return episode


@app.post("/episodes/{episode_id}/rate", response_model=EpisodeResponse)
def rate_episode(episode_id: int, payload: EpisodeRateRequest, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    episode.quality_rating = payload.rating
    db.commit()
    db.refresh(episode)
    return episode


# ---------------------------------------------------------------------------
# Newsletter
# ---------------------------------------------------------------------------

@app.get("/newsletter/preview", response_model=NewsletterPreviewResponse)
def newsletter_preview(days: int = 7, db: Session = Depends(get_db)):
    """Compiles this week's episodes into a newsletter preview without sending."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    episodes = (
        db.query(Episode)
        .filter(Episode.status == "done", Episode.created_at >= since)
        .order_by(Episode.series_id, Episode.episode_number)
        .all()
    )
    if not episodes:
        raise HTTPException(
            status_code=404,
            detail=f"No done episodes in the last {days} days. Generate some first."
        )

    episode_data = [
        {
            "series_title": (db.get(Series, ep.series_id).title if db.get(Series, ep.series_id) else "Unknown"),
            "episode_number": ep.episode_number,
            "mode": ep.mode,
            "content": ep.content,
        }
        for ep in episodes
    ]

    content = compile_newsletter(episode_data)
    return NewsletterPreviewResponse(episode_count=len(episodes), content=content)


@app.post("/newsletter/send", response_model=NewsletterSendResponse)
def newsletter_send(days: int = 7, db: Session = Depends(get_db)):
    """Compiles and emails this week's episodes."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    episodes = (
        db.query(Episode)
        .filter(Episode.status == "done", Episode.created_at >= since)
        .order_by(Episode.series_id, Episode.episode_number)
        .all()
    )
    if not episodes:
        raise HTTPException(status_code=404, detail=f"No done episodes in the last {days} days.")

    episode_data = [
        {
            "series_title": (db.get(Series, ep.series_id).title if db.get(Series, ep.series_id) else "Unknown"),
            "episode_number": ep.episode_number,
            "mode": ep.mode,
            "content": ep.content,
        }
        for ep in episodes
    ]

    content = compile_newsletter(episode_data)
    success = send_newsletter(content)

    if not success:
        raise HTTPException(status_code=502, detail="Failed to send newsletter. Check RESEND_API_KEY and email config.")

    return NewsletterSendResponse(message="Newsletter sent successfully.", episode_count=len(episodes))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@app.get("/metrics/context-builds", response_model=ContextBuildMetrics)
def metrics_context_builds(db: Session = Depends(get_db)):
    row = db.query(
        func.avg(ContextBuildJob.scraping_time_ms),
        func.avg(ContextBuildJob.timeline_time_ms),
        func.avg(ContextBuildJob.total_time_ms),
        func.count(ContextBuildJob.id),
    ).filter(ContextBuildJob.status == "done").first()

    return ContextBuildMetrics(
        avg_scraping_time_ms=row[0],
        avg_timeline_time_ms=row[1],
        avg_total_time_ms=row[2],
        total_jobs=row[3] or 0,
    )


@app.get("/metrics/episodes", response_model=EpisodeMetrics)
def metrics_episodes(db: Session = Depends(get_db)):
    row = db.query(
        func.avg(Episode.llm_time_ms),
        func.count(Episode.id),
        func.count(Episode.quality_rating),
        func.avg(Episode.quality_rating),
    ).filter(Episode.status == "done").first()

    return EpisodeMetrics(
        avg_llm_time_ms=row[0],
        total_episodes=row[1] or 0,
        rated_episodes=row[2] or 0,
        avg_quality_rating=row[3],
    )


@app.get("/metrics", response_model=MetricsResponse)
def metrics(db: Session = Depends(get_db)):
    return MetricsResponse(
        context_builds=metrics_context_builds(db),
        episodes=metrics_episodes(db),
    )
