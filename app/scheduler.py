import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def start_scheduler() -> BackgroundScheduler:
    """
    Starts the background scheduler and registers all recurring jobs.
    Returns the scheduler so the caller can shut it down on app teardown.
    """
    scheduler = BackgroundScheduler()

    # Weekly batch — every Sunday at 9am
    scheduler.add_job(
        _run_weekly_batch,
        trigger=CronTrigger(day_of_week="sun", hour=9, minute=0),
        id="weekly_batch",
        name="Weekly episode generation",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started — weekly batch runs every Sunday at 09:00")
    return scheduler


def _run_weekly_batch():
    """Wrapper so the scheduler can call run_weekly_batch with its own DB session."""
    from app.database import SessionLocal
    from app.pipeline import run_weekly_batch

    db = SessionLocal()
    try:
        run_weekly_batch(db)
    except Exception as e:
        logger.error("Scheduled weekly batch failed: %s", e)
    finally:
        db.close()
