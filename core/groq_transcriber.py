import os
import time
from typing import Any, Dict, List, Optional

from models.data_models import AudioChunk, ChunkTranscriptionResult, TranscriptionSegment


class GroqTranscriptionError(RuntimeError):
    pass


class GroqWhisperTranscriber:
    def __init__(
        self,
        api_key: Optional[str],
        model: str,
        language: Optional[str] = None,
        max_retries: int = 5,
        retry_backoff_seconds: float = 2.0,
    ):
        if not api_key:
            raise GroqTranscriptionError("GROQ_API_KEY is required for transcription")

        try:
            from groq import Groq
        except ImportError as exc:
            raise GroqTranscriptionError("groq package is not installed. Run: pip install -r requirements.txt") from exc

        self.client = Groq(api_key=api_key)
        self.model = model
        self.language = language
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

    def transcribe_chunk(self, chunk: AudioChunk) -> ChunkTranscriptionResult:
        response = self._with_retries(lambda: self._transcribe_once(chunk))
        data = self._response_to_dict(response)
        text = (data.get("text") or "").strip()
        segments = self._parse_segments(data.get("segments") or [], chunk.start_time)
        if not text and segments:
            text = " ".join(segment.text for segment in segments).strip()

        return ChunkTranscriptionResult(
            chunk_index=chunk.chunk_index,
            start_time=chunk.start_time,
            end_time=chunk.end_time,
            text=text,
            segments=segments,
        )

    def _transcribe_once(self, chunk: AudioChunk) -> Any:
        with open(chunk.path, "rb") as audio_file:
            params = {
                "file": (os.path.basename(chunk.path), audio_file.read()),
                "model": self.model,
                "response_format": "verbose_json",
            }
            if self.language:
                params["language"] = self.language
            return self.client.audio.transcriptions.create(**params)

    def _with_retries(self, func):
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return func()
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries or not self._is_retryable(exc):
                    break
                sleep_seconds = self._retry_after_seconds(exc, attempt)
                print(f"[groq] Retryable transcription error: {exc}. Retrying in {sleep_seconds:.1f}s")
                time.sleep(sleep_seconds)

        raise GroqTranscriptionError(f"Groq transcription failed: {last_error}") from last_error

    def _is_retryable(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code in {408, 409, 429, 500, 502, 503, 504}:
            return True

        message = str(exc).lower()
        retry_markers = [
            "rate limit",
            "timeout",
            "temporarily",
            "try again",
            "service unavailable",
            "connection",
        ]
        return any(marker in message for marker in retry_markers)

    def _retry_after_seconds(self, exc: Exception, attempt: int) -> float:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", {}) if response is not None else {}
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return self.retry_backoff_seconds * (2 ** (attempt - 1))

    def _response_to_dict(self, response: Any) -> Dict[str, Any]:
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if isinstance(response, dict):
            return response
        return {
            "text": getattr(response, "text", ""),
            "segments": getattr(response, "segments", []),
            "start": getattr(response, "start", None),
            "end": getattr(response, "end", None),
        }

    def _parse_segments(self, raw_segments: List[Any], chunk_offset: float) -> List[TranscriptionSegment]:
        segments = []
        for raw in raw_segments:
            segment = raw if isinstance(raw, dict) else self._response_to_dict(raw)
            text = (segment.get("text") or "").strip()
            if not text:
                continue
            start = float(segment.get("start") or 0.0) + chunk_offset
            end = float(segment.get("end") or start) + chunk_offset
            segments.append(
                TranscriptionSegment(
                    start_time=round(start, 3),
                    end_time=round(end, 3),
                    text=text,
                )
            )
        return segments
