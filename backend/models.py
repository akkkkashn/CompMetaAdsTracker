from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Ad(SQLModel, table=True):
    __tablename__ = "ads"

    id: str = Field(primary_key=True)
    brand: str
    page_name: str = ""
    status: str = "Active"
    format: str = "Brand/Awareness"
    hook: str = ""
    body_copy: str = ""
    platforms: str = ""
    start_date: str = ""
    end_date: Optional[str] = None
    run_days: int = 0
    impressions_est: int = 0
    spend_est: int = 0
    snapshot_url: str = ""
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    is_new: bool = True
    saved: bool = False
