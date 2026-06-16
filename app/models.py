from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class Series(Base):
    __tablename__ = "series"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="building")  # building | ready | needs_refresh
    discovery_depth = Column(Integer, default=0)  # 0=root, 1=discovered, 2=discovered-from-discovered
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_refreshed_at = Column(DateTime, nullable=True)

    timelines = relationship("MasterTimeline", back_populates="series", cascade="all, delete-orphan")
    episodes = relationship("Episode", back_populates="series", cascade="all, delete-orphan")
    context_jobs = relationship("ContextBuildJob", back_populates="series", cascade="all, delete-orphan")
    connections = relationship(
        "SeriesConnection",
        primaryjoin="Series.id == SeriesConnection.series_id",
        back_populates="series",
        cascade="all, delete-orphan",
    )


class MasterTimeline(Base):
    __tablename__ = "master_timelines"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("series.id"), nullable=False)
    content = Column(Text, nullable=False)
    confidence_score = Column(Integer, nullable=True)  # LLM self-rated 1-10
    gaps = Column(Text, nullable=True)                 # what the LLM flagged as missing
    is_active = Column(Boolean, default=True)
    built_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    superseded_at = Column(DateTime, nullable=True)

    series = relationship("Series", back_populates="timelines")
    episodes = relationship("Episode", back_populates="timeline")


class Episode(Base):
    __tablename__ = "episodes"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("series.id"), nullable=False)
    timeline_id = Column(Integer, ForeignKey("master_timelines.id"), nullable=False)
    episode_number = Column(Integer, nullable=False)
    mode = Column(String, nullable=False)              # gossip | dramatic | explainer | cartoon
    content = Column(Text, nullable=True)
    quality_rating = Column(Integer, nullable=True)    # 1-5, added manually
    status = Column(String, default="pending")         # pending | processing | done | failed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    llm_time_ms = Column(Integer, nullable=True)

    series = relationship("Series", back_populates="episodes")
    timeline = relationship("MasterTimeline", back_populates="episodes")


class ContextBuildJob(Base):
    __tablename__ = "context_build_jobs"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("series.id"), nullable=False)
    job_type = Column(String, nullable=False)          # initial_build | refresh
    status = Column(String, default="pending")         # pending | processing | done | failed
    scraping_time_ms = Column(Integer, nullable=True)
    timeline_time_ms = Column(Integer, nullable=True)
    total_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)

    series = relationship("Series", back_populates="context_jobs")


class SeriesConnection(Base):
    __tablename__ = "series_connections"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("series.id"), nullable=False)
    connected_topic = Column(String, nullable=False)
    connected_series_id = Column(Integer, ForeignKey("series.id"), nullable=True)  # set when approved
    relationship_hint = Column(Text, nullable=True)    # one-sentence explanation from the LLM
    status = Column(String, default="suggested")       # suggested | approved | dismissed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    series = relationship("Series", foreign_keys=[series_id], back_populates="connections")
