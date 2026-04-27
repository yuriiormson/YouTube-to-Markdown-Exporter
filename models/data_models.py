import os
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator

class ProcessingConfig(BaseModel):
    delay_between_videos_sec: int = 5

class AppConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    channel_url: str
    filters: dict = Field(default_factory=dict)
    output_dir: str = "output/Arestovych_LIVE"
    db_path: str = "data/videos.db"
    state_path: str = "data/state.json"
    languages: List[str] = Field(default_factory=lambda: ["ru", "uk", "en"])
    cookies_path: Optional[str] = None
    proxy: Optional[str] = None
    cookies_from_browser: str = "chrome"
    js_runtime: str = "node"
    retries: int = 5
    delay: int = 5
    groq_api_key: Optional[str] = None
    chunk_duration_seconds: int = 600
    chunk_overlap_seconds: int = 5
    groq_model: str = "whisper-large-v3-turbo"
    transcription_language: Optional[str] = None
    max_retries: int = 5
    retry_backoff_seconds: float = 2.0
    combined_markdown_filename: str = "combined_notes.md"
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)

    @model_validator(mode="after")
    def load_env_defaults(self):
        if not self.groq_api_key:
            self.groq_api_key = os.getenv("GROQ_API_KEY")
        if self.chunk_duration_seconds <= 0:
            raise ValueError("chunk_duration_seconds must be greater than 0")
        if self.chunk_overlap_seconds < 0:
            raise ValueError("chunk_overlap_seconds cannot be negative")
        if self.chunk_overlap_seconds >= self.chunk_duration_seconds:
            raise ValueError("chunk_overlap_seconds must be less than chunk_duration_seconds")
        return self

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

class AudioChunk(BaseModel):
    chunk_index: int
    start_time: float
    end_time: float
    path: str

class TranscriptionSegment(BaseModel):
    start_time: float
    end_time: float
    text: str

class ChunkTranscriptionResult(BaseModel):
    chunk_index: int
    start_time: float
    end_time: float
    text: str = ""
    segments: List[TranscriptionSegment] = Field(default_factory=list)

class ProcessingState(BaseModel):
    video_id: str
    source_video_filename: str
    mp3_path: Optional[str] = None
    chunk_temp_dir: Optional[str] = None
    status: str = "pending"
    last_processed_chunk_index: int = -1
    final_note_path: Optional[str] = None
    transcript_path: Optional[str] = None
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    error_message: Optional[str] = None
    chunk_transcripts: List[ChunkTranscriptionResult] = Field(default_factory=list)

class VideoRecord(BaseModel):
    video_id: str
    title: str
    url: str
    published_at: Optional[str] = None
    markdown_path: Optional[str] = None
    processed_at: Optional[datetime] = None
    status: str
