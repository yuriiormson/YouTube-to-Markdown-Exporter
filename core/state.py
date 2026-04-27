import json
import os
from datetime import datetime
from typing import Dict, Optional

from models.data_models import ChunkTranscriptionResult, ProcessingState


VALID_STATUSES = {
    "pending",
    "audio_extracted",
    "chunked",
    "transcribing",
    "transcribed",
    "note_written",
    "completed",
    "failed",
    "no_speech",
}


class StateManager:
    def __init__(self, state_path: str):
        self.state_path = state_path
        state_dir = os.path.dirname(self.state_path)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)

    def _read_all(self) -> Dict[str, dict]:
        if not os.path.exists(self.state_path):
            return {}
        with open(self.state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def _write_all(self, data: Dict[str, dict]) -> None:
        tmp_path = f"{self.state_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, self.state_path)

    def get_state(self, video_id: str) -> Optional[ProcessingState]:
        raw = self._read_all().get(video_id)
        return ProcessingState(**raw) if raw else None

    def ensure_state(self, video_id: str, source_video_filename: str) -> ProcessingState:
        state = self.get_state(video_id)
        if state:
            if state.source_video_filename != source_video_filename:
                return self.update_state(video_id, source_video_filename=source_video_filename)
            return state

        state = ProcessingState(
            video_id=video_id,
            source_video_filename=source_video_filename,
        )
        data = self._read_all()
        data[video_id] = state.model_dump(mode="json")
        self._write_all(data)
        return state

    def update_state(self, video_id: str, **changes) -> ProcessingState:
        if "status" in changes and changes["status"] not in VALID_STATUSES:
            raise ValueError(f"Unsupported state status: {changes['status']}")

        data = self._read_all()
        current = data.get(video_id, {"video_id": video_id, "source_video_filename": f"{video_id}.mp3"})
        current.update(changes)
        current["updated_at"] = datetime.now().isoformat(timespec="seconds")
        data[video_id] = current
        self._write_all(data)
        return ProcessingState(**current)

    def record_chunk_result(self, video_id: str, result: ChunkTranscriptionResult) -> ProcessingState:
        state = self.get_state(video_id)
        if not state:
            state = self.ensure_state(video_id, f"{video_id}.mp3")

        by_index = {item.chunk_index: item for item in state.chunk_transcripts}
        by_index[result.chunk_index] = result
        ordered = [by_index[index] for index in sorted(by_index)]

        return self.update_state(
            video_id,
            chunk_transcripts=[item.model_dump(mode="json") for item in ordered],
            last_processed_chunk_index=max(state.last_processed_chunk_index, result.chunk_index),
            error_message=None,
        )

    def mark_failed(self, video_id: str, error_message: str) -> ProcessingState:
        return self.update_state(
            video_id,
            status="failed",
            error_message=error_message,
        )
