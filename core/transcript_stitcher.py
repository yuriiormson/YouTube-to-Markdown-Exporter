import re
import string
from typing import Iterable, List

from models.data_models import ChunkTranscriptionResult


def normalize_transcript(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "")
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def _comparison_token(token: str) -> str:
    return token.lower().strip(string.punctuation + "«»“”„—–…")


def _find_overlap_words(previous_words: List[str], current_words: List[str], max_words: int = 80) -> int:
    limit = min(max_words, len(previous_words), len(current_words))
    for size in range(limit, 3, -1):
        previous_slice = [_comparison_token(word) for word in previous_words[-size:]]
        current_slice = [_comparison_token(word) for word in current_words[:size]]
        if previous_slice == current_slice and any(previous_slice):
            return size
    return 0


def remove_overlap(previous_text: str, current_text: str) -> str:
    previous_text = normalize_transcript(previous_text)
    current_text = normalize_transcript(current_text)
    if not previous_text:
        return current_text
    if not current_text:
        return ""

    previous_words = previous_text.split()
    current_words = current_text.split()
    overlap_words = _find_overlap_words(previous_words, current_words)
    if overlap_words:
        return " ".join(current_words[overlap_words:]).strip()

    previous_tail = previous_text[-500:].lower()
    lowered_current = current_text.lower()
    for char_count in range(min(len(previous_tail), len(lowered_current)), 39, -1):
        if previous_tail.endswith(lowered_current[:char_count]):
            return current_text[char_count:].strip()

    return current_text


def stitch_chunk_transcripts(chunk_results: Iterable[ChunkTranscriptionResult]) -> str:
    ordered = sorted(chunk_results, key=lambda item: item.chunk_index)
    stitched = ""
    for result in ordered:
        text = normalize_transcript(result.text)
        if not text:
            continue
        addition = remove_overlap(stitched, text)
        stitched = normalize_transcript(f"{stitched} {addition}")
    return normalize_transcript(stitched)
