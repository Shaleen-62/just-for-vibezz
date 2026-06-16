import logging
import random
import time

from sqlalchemy.orm import Session

from app.llm import call_llm
from app.models import Episode, MasterTimeline, Series, SeriesConnection
from app.modes import build_story_prompt

logger = logging.getLogger(__name__)


def _get_related_timelines(series_id: int, db: Session) -> dict:
    """
    Returns {series_title: timeline_content} for all approved connections
    that have a built timeline. Used to enrich episode prompts.
    """
    connections = (
        db.query(SeriesConnection)
        .filter(
            SeriesConnection.series_id == series_id,
            SeriesConnection.status == "approved",
            SeriesConnection.connected_series_id.isnot(None),
        )
        .all()
    )

    related = {}
    for conn in connections:
        connected = db.get(Series, conn.connected_series_id)
        if not connected or connected.status != "ready":
            continue
        timeline = (
            db.query(MasterTimeline)
            .filter(
                MasterTimeline.series_id == conn.connected_series_id,
                MasterTimeline.is_active == True,
            )
            .first()
        )
        if timeline:
            related[connected.title] = timeline.content

    return related


def generate_episode(series: Series, db: Session) -> Episode:
    """
    Generates one episode for a series (Pipeline B).

    Flow:
      1. Fetch the active timeline
      2. Fetch the last episode for recap continuity
      3. Pick a random storytelling mode
      4. Gather related timelines from approved connections
      5. Build the prompt, call the LLM, store the Episode
    """
    timeline = (
        db.query(MasterTimeline)
        .filter(MasterTimeline.series_id == series.id, MasterTimeline.is_active == True)
        .first()
    )
    if not timeline:
        raise ValueError(f"No active timeline for series {series.id} — run /build first")

    last_episode = (
        db.query(Episode)
        .filter(Episode.series_id == series.id, Episode.status == "done")
        .order_by(Episode.episode_number.desc())
        .first()
    )

    episode_number = (last_episode.episode_number + 1) if last_episode else 1
    mode = random.choice(list(["gossip", "dramatic", "explainer", "cartoon"]))
    related_timelines = _get_related_timelines(series.id, db)

    # Create the episode record in "processing" state
    episode = Episode(
        series_id=series.id,
        timeline_id=timeline.id,
        episode_number=episode_number,
        mode=mode,
        status="processing",
    )
    db.add(episode)
    db.commit()
    db.refresh(episode)

    logger.info(
        "Generating episode %d for '%s' (mode: %s, related: %d)",
        episode_number, series.title, mode, len(related_timelines),
    )

    prompt = build_story_prompt(
        series_title=series.title,
        episode_number=episode_number,
        timeline_content=timeline.content,
        mode=mode,
        previous_story=last_episode.content if last_episode else None,
        related_timelines=related_timelines or None,
    )

    t0 = time.time()
    try:
        content = call_llm(prompt)
        episode.llm_time_ms = int((time.time() - t0) * 1000)
        episode.content = content
        episode.status = "done"
        logger.info(
            "Episode %d done for '%s' in %dms",
            episode_number, series.title, episode.llm_time_ms,
        )
    except Exception as e:
        episode.status = "failed"
        logger.error("Episode generation failed for series %d: %s", series.id, e)

    db.commit()
    db.refresh(episode)
    return episode


def run_weekly_batch(db: Session) -> list:
    """
    Generates one episode for every 'ready' series.
    Called by POST /episodes/run and by the weekly APScheduler job.
    Returns a list of Episode objects (done or failed).
    """
    active_series = db.query(Series).filter(Series.status == "ready").all()
    logger.info("=== Weekly batch started: %d ready series ===", len(active_series))

    results = []
    for series in active_series:
        try:
            episode = generate_episode(series, db)
            results.append(episode)
        except Exception as e:
            logger.error("Batch: skipping series %d (%s): %s", series.id, series.title, e)

    done = sum(1 for e in results if e.status == "done")
    logger.info("=== Weekly batch done: %d/%d episodes generated ===", done, len(active_series))
    return results
