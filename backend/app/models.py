import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY as PGArray
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.database import Base
from app.config import settings


class Image(Base):
    __tablename__ = "images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_path = Column(Text, nullable=False)
    oss_url = Column(Text)
    oss_key = Column(Text)
    source_app = Column(Text)
    scenario = Column(Text)
    captured_at = Column(DateTime)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="images")
    analysis = relationship("Analysis", back_populates="image", uselist=False)


class Analysis(Base):
    __tablename__ = "analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id"), unique=True)
    design_analysis = Column(Text)
    ops_analysis = Column(Text)
    status = Column(String, default="pending")
    analyzed_at = Column(DateTime, nullable=True)

    image = relationship("Image", back_populates="analysis")
    embeddings = relationship("Embedding", back_populates="analysis")


class Request(Base):
    __tablename__ = "requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Text, default="anonymous")
    target_app = Column(Text)
    target_scenario = Column(Text)
    keywords = Column(PGArray(Text))
    description = Column(Text)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

    tasks = relationship("Task", back_populates="request")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("requests.id"), nullable=True)
    name = Column(Text)
    keyword = Column(Text)
    target_app = Column(Text)
    target_scenario = Column(Text)
    mode = Column(String, default="uiautomator2")
    generated_instruction = Column(Text, nullable=True, comment="LLM生成的AutoGLM可执行指令")
    status = Column(String, default="pending")
    admin_id = Column(Text, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    request = relationship("Request", back_populates="tasks")
    images = relationship("Image", back_populates="task")


class Embedding(Base):
    __tablename__ = "embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analysis.id"))
    embedding = Column(Vector(settings.EMBEDDING_DIM))
    content_type = Column(Text)

    analysis = relationship("Analysis", back_populates="embeddings")
