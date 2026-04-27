import sqlite3
import os
from typing import Optional
from models.data_models import VideoRecord
from datetime import datetime

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        # Create directory if it doesn't exist
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    title TEXT,
                    url TEXT,
                    published_at TEXT,
                    markdown_path TEXT,
                    processed_at TIMESTAMP,
                    status TEXT
                )
            ''')
            conn.commit()

    def get_video(self, video_id: str) -> Optional[VideoRecord]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM videos WHERE video_id = ?', (video_id,))
            row = cursor.fetchone()
            
            if row:
                return VideoRecord(
                    video_id=row['video_id'],
                    title=row['title'],
                    url=row['url'],
                    published_at=row['published_at'],
                    markdown_path=row['markdown_path'],
                    processed_at=row['processed_at'],
                    status=row['status']
                )
            return None

    def upsert_video(self, record: VideoRecord):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO videos (video_id, title, url, published_at, markdown_path, processed_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    title=excluded.title,
                    url=excluded.url,
                    published_at=excluded.published_at,
                    markdown_path=excluded.markdown_path,
                    processed_at=excluded.processed_at,
                    status=excluded.status
            ''', (
                record.video_id,
                record.title,
                record.url,
                record.published_at,
                record.markdown_path,
                record.processed_at.isoformat() if record.processed_at else None,
                record.status
            ))
            conn.commit()

    def get_all(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM videos')
            rows = cursor.fetchall()
            
            return [
                VideoRecord(
                    video_id=row['video_id'],
                    title=row['title'],
                    url=row['url'],
                    published_at=row['published_at'],
                    markdown_path=row['markdown_path'],
                    processed_at=row['processed_at'],
                    status=row['status']
                ) for row in rows
            ]

    def delete(self, video_id: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM videos WHERE video_id = ?', (video_id,))
            conn.commit()
