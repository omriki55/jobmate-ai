from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, JSON, DateTime,
    Boolean, ForeignKey, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship, DeclarativeBase
from datetime import datetime


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    state = Column(String, default="AWAITING_CV")   # AWAITING_CV | ACTIVE | PAUSED
    momentum_score = Column(Integer, default=0)
    streak_days = Column(Integer, default=0)
    last_active_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    timezone = Column(String, default="UTC")

    cvs = relationship("CV", back_populates="user")
    preferences = relationship("UserPreferences", back_populates="user", uselist=False)
    applications = relationship("Application", back_populates="user")


class CV(Base):
    __tablename__ = "cvs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    raw_text = Column(Text, nullable=False)
    parsed_data = Column(JSON, nullable=True)   # Full structured parse from Claude
    cv_score = Column(Integer, nullable=True)
    improvement_notes = Column(JSON, nullable=True)
    version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="cvs")


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    target_roles = Column(JSON, default=list)
    locations = Column(JSON, default=list)
    min_salary = Column(Integer, nullable=True)
    salary_currency = Column(String, default="USD")
    industries = Column(JSON, default=list)
    company_sizes = Column(JSON, default=list)
    employment_types = Column(JSON, default=list)
    match_threshold = Column(Integer, default=50)
    daily_apply_limit = Column(Integer, default=10)
    blocklist = Column(JSON, default=list)       # blocked companies
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="preferences")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    external_id = Column(String, nullable=True)
    source = Column(String, default="sample")    # sample | linkedin | indeed | ...
    title = Column(String, nullable=False)
    company = Column(String, nullable=False)
    location = Column(String, nullable=False)
    salary_min = Column(Integer, nullable=True)
    salary_max = Column(Integer, nullable=True)
    salary_currency = Column(String, default="USD")
    description = Column(Text, nullable=True)
    requirements = Column(JSON, default=list)
    employment_type = Column(String, default="full-time")
    industry = Column(String, nullable=True)
    company_size = Column(String, nullable=True)
    remote = Column(Boolean, default=False)
    posted_at = Column(DateTime, default=datetime.utcnow)
    url = Column(String, nullable=True)

    __table_args__ = (UniqueConstraint("external_id", "source", name="uq_job_external_source"),)


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    # applied | viewed | contacted | interview | offer | rejected | withdrawn
    status = Column(String, default="applied")
    submitted_at = Column(DateTime, default=datetime.utcnow)
    last_status_change_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)

    user = relationship("User", back_populates="applications")
    job = relationship("Job")

    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_application_user_job"),)


class ActivityLog(Base):
    """Tracks user actions for dashboard timeline."""
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String, nullable=False)  # applied, tailored_cv, interview_prep, status_change, search, coach
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class Notification(Base):
    """User notifications for new matches, status updates, etc."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String, nullable=False)  # new_match, status_update, daily_digest, coach_checkin
    data = Column(JSON, nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class InterviewSession(Base):
    """Persists mock interview simulation sessions."""
    __tablename__ = "interview_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    questions = Column(JSON, nullable=True)   # list of question dicts
    answers = Column(JSON, default=list)      # list of {answer, feedback} dicts
    overall_score = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    job = relationship("Job")
