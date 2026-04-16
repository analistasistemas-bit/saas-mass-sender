from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
    send_delay_min_seconds: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    send_delay_max_seconds: Mapped[int] = mapped_column(Integer, default=45, nullable=False)
    batch_pause_min_seconds: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    batch_pause_max_seconds: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    batch_size_initial: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    batch_size_max: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
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


class Conversation(Base):
    __tablename__ = 'conversations'
    __table_args__ = (
        Index('ix_conversations_status', 'status'),
        UniqueConstraint('customer_phone', name='uq_conversations_customer_phone'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='ai_active', nullable=False)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_wa_message_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    ai_consecutive_replies: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    handoff_target_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    messages = relationship('ConversationMessage', back_populates='conversation', cascade='all, delete-orphan')
    handoff_events = relationship('HandoffEvent', back_populates='conversation', cascade='all, delete-orphan')


class ConversationMessage(Base):
    __tablename__ = 'conversation_messages'
    __table_args__ = (
        Index('ix_conversation_messages_conversation_created', 'conversation_id', 'created_at'),
        UniqueConstraint('wa_message_id', name='uq_conversation_messages_wa_message_id'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    wa_message_id: Mapped[str] = mapped_column(String(120), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    conversation = relationship('Conversation', back_populates='messages')


class HandoffEvent(Base):
    __tablename__ = 'handoff_events'
    __table_args__ = (Index('ix_handoff_events_conversation_created', 'conversation_id', 'created_at'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    notified_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='created', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    conversation = relationship('Conversation', back_populates='handoff_events')


class AgentSettings(Base):
    __tablename__ = 'agent_settings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    inbound_ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    primary_model: Mapped[str] = mapped_column(String(120), default='', nullable=False)
    business_name: Mapped[str] = mapped_column(String(160), default='', nullable=False)

    agent_name: Mapped[str] = mapped_column(String(120), default='Assistente virtual', nullable=False)
    tone: Mapped[str] = mapped_column(String(40), default='comercial', nullable=False)
    style: Mapped[str] = mapped_column(String(40), default='equilibrado', nullable=False)
    proactivity_level: Mapped[str] = mapped_column(String(40), default='medio', nullable=False)
    use_emojis: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_response_length: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    personality_instructions: Mapped[str] = mapped_column(Text, default='', nullable=False)

    can_answer_price: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_answer_stock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_answer_description: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_suggest_similar_products: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_negotiate_discount: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_close_order: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    handoff_on_order_intent: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    handoff_on_low_confidence: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    handoff_on_human_request: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_auto_replies_per_conversation: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    response_delay_min_ms: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    response_delay_max_ms: Mapped[int] = mapped_column(Integer, default=3000, nullable=False)

    handoff_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    handoff_message: Mapped[str] = mapped_column(Text, default='Vou passar seu atendimento para meu gerente.', nullable=False)
    human_whatsapp_number: Mapped[str] = mapped_column(String(20), default='', nullable=False)
    stop_ai_after_handoff: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    manual_knowledge_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manual_knowledge_text: Mapped[str] = mapped_column(Text, default='', nullable=False)

    db_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    db_type: Mapped[str] = mapped_column(String(20), default='oracle', nullable=False)
    db_host: Mapped[str] = mapped_column(String(160), default='', nullable=False)
    db_port: Mapped[int] = mapped_column(Integer, default=1521, nullable=False)
    db_service: Mapped[str] = mapped_column(String(160), default='', nullable=False)
    db_user: Mapped[str] = mapped_column(String(160), default='', nullable=False)
    db_password_encrypted: Mapped[str] = mapped_column(Text, default='', nullable=False)
    db_view_name: Mapped[str] = mapped_column(String(160), default='', nullable=False)
    db_timeout_seconds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    knowledge_priority_json: Mapped[str] = mapped_column(Text, default='["manual","spreadsheet","database"]', nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class AgentSpreadsheetUpload(Base):
    __tablename__ = 'agent_spreadsheet_uploads'
    __table_args__ = (
        Index('ix_agent_spreadsheet_uploads_active_created', 'is_active', 'created_at'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_extension: Mapped[str] = mapped_column(String(10), default='', nullable=False)
    columns_json: Mapped[str] = mapped_column(Text, default='[]', nullable=False)
    preview_rows_json: Mapped[str] = mapped_column(Text, default='[]', nullable=False)
    mapping_json: Mapped[str] = mapped_column(Text, default='{}', nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(40), default='pending', nullable=False)
    validation_message: Mapped[str] = mapped_column(Text, default='', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
