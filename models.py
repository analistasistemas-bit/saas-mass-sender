from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base, utcnow


class Campaign(Base):
    __tablename__ = 'campaigns'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    message_template: Mapped[str] = mapped_column(Text, default='Oi, {{nome}}', nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='draft', nullable=False)
    is_test_required: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    test_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    speed_profile: Mapped[str] = mapped_column(String(20), default='conservative', nullable=False)
    send_delay_min_seconds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    send_delay_max_seconds: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    batch_pause_min_seconds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    batch_pause_max_seconds: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    batch_size_initial: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    batch_size_max: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    batch_growth_step: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    batch_growth_streak_required: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    batch_shrink_step: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    batch_shrink_error_streak_required: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    batch_size_floor: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    send_window_start_hour: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    send_window_end_hour: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    daily_limit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_send_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    pause_reason: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    total_contacts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_contacts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_contacts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pending_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    contacts = relationship('Contact', back_populates='campaign', cascade='all, delete-orphan')


class Contact(Base):
    __tablename__ = 'contacts'
    __table_args__ = (
        Index('ix_contacts_campaign_status', 'campaign_id', 'status'),
        UniqueConstraint('campaign_id', 'phone_e164', name='uq_contacts_campaign_phone'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False)

    name: Mapped[str] = mapped_column(String(120), default='', nullable=False)
    phone_raw: Mapped[str] = mapped_column(String(40), nullable=False)
    phone_e164: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    email: Mapped[str] = mapped_column(String(255), default='', nullable=False)
    source: Mapped[str] = mapped_column(String(20), default='csv', nullable=False)

    status: Mapped[str] = mapped_column(String(20), default='pending', nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    campaign = relationship('Campaign', back_populates='contacts')


class SendLog(Base):
    __tablename__ = 'send_logs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False)
    contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey('contacts.id', ondelete='SET NULL'), nullable=True)

    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_class: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
