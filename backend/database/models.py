import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, String, DateTime
from backend.database.core import Base

def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)

class User(Base):
    """The canonical 'Owner' of the platform."""
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=get_datetime_utc)

# We map ClientWorkspace to the database
class Workspace(Base):
    """Isolated tenant representation (logical workspace)."""
    __tablename__ = "workspaces"

    workspace_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    workspace_type = Column(String, default="internal")
    owner_id = Column(String, nullable=False, index=True) # Logical isolation via foreign key logic
    created_at = Column(DateTime(timezone=True), default=get_datetime_utc)
