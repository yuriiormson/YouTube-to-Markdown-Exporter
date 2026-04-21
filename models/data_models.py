from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

class ProcessingConfig(BaseModel):
    delay_between_videos_sec: int = 5

class AppConfig(BaseModel):
    channel_url: str
    filters: dict = Field(default_factory=dict)
    output_dir: str = "output/Arestovych_LIVE"
    db_path: str = "data/videos.db"
    languages: List[str] = Field(default_factory=lambda: ["ru", "uk", "en"])
    cookies_from_browser: str = "chrome"
    js_runtime: str = "node"
    retries: int = 5
    delay: int = 5
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    
    class Config:
        extra = 'allow'

class VideoMeta(BaseModel):
    video_id: str
    title: str
    url: str
    published_at: Optional[str] = None
    description: str
    duration: Optional[int] = None
    tags: List[str] = Field(default_factory=list)

class TranscriptLine(BaseModel):
    start_time: str
    end_time: str
    text: str

class VideoRecord(BaseModel):
    video_id: str
    title: str
    url: str
    published_at: Optional[str] = None
    markdown_path: Optional[str] = None
    processed_at: Optional[datetime] = None
    status: str
