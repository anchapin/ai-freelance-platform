import uuid
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Text, Enum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class TaskStatus(PyEnum):
    PENDING = "PENDING"
    PAID = "PAID"
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
        }
