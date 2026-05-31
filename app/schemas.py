from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

class SeriesCreate(BaseModel):
    title: str
    description: Optional[str] = None


class SeriesResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    status: str
    created_at: datetime
    last_refreshed_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# MasterTimeline
# ---------------------------------------------------------------------------

class TimelineResponse(BaseModel):
    id: int
    series_id: int
    content: str
    confidence_score: Optional[int]
    gaps: Optional[str]
    is_active: bool
    built_at: datetime
    superseded_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# ContextBuildJob
# ---------------------------------------------------------------------------

class ContextJobResponse(BaseModel):
    id: int
    series_id: int
    job_type: str
    status: str
    scraping_time_ms: Optional[int]
    timeline_time_ms: Optional[int]
    total_time_ms: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------

class EpisodeResponse(BaseModel):
    id: int
    series_id: int
    timeline_id: int
    episode_number: int
    mode: str
    content: Optional[str]
    quality_rating: Optional[int]
    status: str
    created_at: datetime
    llm_time_ms: Optional[int]

    model_config = {"from_attributes": True}


class EpisodeRateRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)


# ---------------------------------------------------------------------------
# Newsletter
# ---------------------------------------------------------------------------

class NewsletterPreviewResponse(BaseModel):
    episode_count: int
    content: str


class NewsletterSendResponse(BaseModel):
    message: str
    episode_count: int


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class ContextBuildMetrics(BaseModel):
    avg_scraping_time_ms: Optional[float]
    avg_timeline_time_ms: Optional[float]
    avg_total_time_ms: Optional[float]
    total_jobs: int


class EpisodeMetrics(BaseModel):
    avg_llm_time_ms: Optional[float]
    total_episodes: int
    rated_episodes: int
    avg_quality_rating: Optional[float]


class MetricsResponse(BaseModel):
    context_builds: ContextBuildMetrics
    episodes: EpisodeMetrics
