import json
import os
import shutil
import subprocess
from typing import List

from models.data_models import AudioChunk


class FFmpegError(RuntimeError):
    pass


class AudioChunker:
    def __init__(self, chunk_duration_seconds: int, chunk_overlap_seconds: int):
        self.chunk_duration_seconds = chunk_duration_seconds
        self.chunk_overlap_seconds = chunk_overlap_seconds

    def get_duration_seconds(self, audio_path: str) -> float:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            return float(result.stdout.strip())
        except FileNotFoundError as exc:
            raise FFmpegError("ffprobe is not installed or not available on PATH") from exc
        except Exception as exc:
            stderr = getattr(exc, "stderr", "") or str(exc)
            raise FFmpegError(f"ffprobe failed for {audio_path}: {stderr}") from exc

    def manifest_path(self, chunk_dir: str) -> str:
        return os.path.join(chunk_dir, "chunks.json")

    def load_chunks(self, chunk_dir: str) -> List[AudioChunk]:
        manifest_path = self.manifest_path(chunk_dir)
        if not os.path.exists(manifest_path):
            return []
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        chunks = [AudioChunk(**item) for item in data]
        if not all(os.path.exists(chunk.path) for chunk in chunks):
            return []
        return chunks

    def create_chunks(self, audio_path: str, chunk_dir: str) -> List[AudioChunk]:
        os.makedirs(chunk_dir, exist_ok=True)
        duration = self.get_duration_seconds(audio_path)

        chunks = []
        start = 0.0
        index = 0
        while start < duration:
            end = min(start + self.chunk_duration_seconds, duration)
            chunk_path = os.path.join(chunk_dir, f"chunk_{index:04d}.mp3")
            self._export_chunk(audio_path, chunk_path, start, end)
            chunks.append(
                AudioChunk(
                    chunk_index=index,
                    start_time=round(start, 3),
                    end_time=round(end, 3),
                    path=chunk_path,
                )
            )
            if end >= duration:
                break
            start = max(0.0, end - self.chunk_overlap_seconds)
            index += 1

        with open(self.manifest_path(chunk_dir), "w", encoding="utf-8") as f:
            json.dump([chunk.model_dump(mode="json") for chunk in chunks], f, ensure_ascii=False, indent=2)
            f.write("\n")

        return chunks

    def _export_chunk(self, audio_path: str, chunk_path: str, start: float, end: float) -> None:
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-i",
            audio_path,
            "-t",
            f"{end - start:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            chunk_path,
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise FFmpegError("ffmpeg is not installed or not available on PATH") from exc
        except subprocess.CalledProcessError as exc:
            raise FFmpegError(f"ffmpeg failed while creating {chunk_path}: {exc.stderr}") from exc

    def cleanup_chunks(self, chunk_dir: str) -> None:
        if chunk_dir and os.path.exists(chunk_dir):
            shutil.rmtree(chunk_dir)
