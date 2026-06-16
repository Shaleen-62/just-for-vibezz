import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import ContextBuildJob, MasterTimeline, Series, SeriesConnection
from app.schemas import (
    ContextJobResponse,
    SeriesConnectionResponse,
    SeriesCreate,
    SeriesResponse,
    TimelineResponse,
)
from app.scraper import scrape_all
from app.timeline import build_master_timeline, discover_related_topics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create all tables on startup (Alembic handles this in production)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="NewsLore", version="0.1.0")


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
# Pipeline A — context build
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

    # --- Scraping ---
    logger.info("Pipeline A: scraping for series %d (%s)", series_id, series.title)
    t_scrape = time.time()
    scraped = scrape_all(series.title, description=series.description or "", seed_urls=seed_urls or [])
    scraping_time_ms = int((time.time() - t_scrape) * 1000)

    if not scraped:
        job.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail="Scraping returned no content")

    # --- Timeline build ---
    logger.info("Pipeline A: building timeline for series %d", series_id)
    t_timeline = time.time()
    result = build_master_timeline(series.title, scraped, description=series.description or "")
    timeline_time_ms = int((time.time() - t_timeline) * 1000)

    # --- Store MasterTimeline ---
    timeline = MasterTimeline(
        series_id=series_id,
        content=result["content"],
        confidence_score=result["confidence_score"],
        gaps=result["gaps"],
        is_active=True,
    )
    db.add(timeline)

    # --- Update series and job ---
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

    # --- Discover related topics (skip for deeply discovered series to avoid runaway expansion) ---
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
    """Deletes the active timeline for a series, resetting it to building."""
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
# Series connections (knowledge graph)
# ---------------------------------------------------------------------------

@app.get("/series/{series_id}/connections", response_model=List[SeriesConnectionResponse])
def get_connections(series_id: int, db: Session = Depends(get_db)):
    """Lists all connections discovered for a series — suggested, approved, and dismissed."""
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
    """
    Approves a suggested connection — creates a new Series for that topic
    and links it back to the connection. Run /series/{id}/build on the
    returned series to actually build its timeline.
    """
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
    db.flush()  # get the new ID before committing

    conn.connected_series_id = new_series.id
    conn.status = "approved"
    db.commit()
    db.refresh(new_series)

    logger.info(
        "Approved connection %d → created series %d (%s, depth %d)",
        connection_id, new_series.id, new_series.title, new_depth,
    )
    return new_series


@app.delete("/connections/{connection_id}", status_code=204)
def dismiss_connection(connection_id: int, db: Session = Depends(get_db)):
    """Dismisses a suggested connection so it stops appearing in the list."""
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
