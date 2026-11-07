from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

from database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    license = Column(String, nullable=False)

    governance_model = Column(String, nullable=False)

    contact_email = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)