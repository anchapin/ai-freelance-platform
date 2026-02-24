import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Text, Integer, Enum, DateTime
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class TaskStatus(PyEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    stripe_session_id = Column(String, nullable=True)
    result_image_url = Column(String, nullable=True)
    csv_data = Column(Text, nullable=True)
    # New fields for file uploads
    file_type = Column(String, nullable=True)  # csv, excel, pdf
    file_content = Column(Text, nullable=True)  # Base64-encoded file content
    filename = Column(String, nullable=True)  # Original filename
    # Client tracking fields
    client_email = Column(String, nullable=True)  # Client email for history tracking
    amount_paid = Column(Integer, nullable=True)  # Amount paid in cents
    delivery_token = Column(String, nullable=True)  # Secure token for delivery links
    # Timestamp fields for tracking turnaround time
    created_at = Column(DateTime, default=datetime.utcnow)  # Task creation timestamp
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # Last update timestamp

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "domain": self.domain,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "stripe_session_id": self.stripe_session_id,
            "result_image_url": self.result_image_url,
            "csv_data": self.csv_data,
            "file_type": self.file_type,
            "filename": self.filename,
            "client_email": self.client_email,
            "amount_paid": self.amount_paid,
            "delivery_token": self.delivery_token,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
