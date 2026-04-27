import re
import webvtt
from typing import List, Dict, Tuple
from models.data_models import TranscriptLine

def is_valid_transcript(text: str) -> bool:
    if not text:
        return False
    # too short → not transcript
    if len(text) < 500:
        return False
    # too many timestamps → likely description
    timestamp_lines = sum(
        1 for line in text.splitlines()
        if line.strip().startswith(("00:", "01:", "02:", "03:"))
    )
    if timestamp_lines > 5:
        return False
    return True

class Parser:
    def __init__(self):
        # Regex to find timestamps like "00:00", "01:23:45"
        self.timestamp_regex = re.compile(r'(?:[0-5]?\d:)?(?:[0-5]?\d):[0-5]\d')

    def parse_description_timestamps(self, description: str) -> List[Tuple[str, str]]:
        """
        Parses description to find lines with timestamps.
        Returns a list of tuples (timestamp, title).
        Example: [("00:00", "Intro"), ("05:30", "Question 1")]
        """
        timestamps = []
        for line in description.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            match = self.timestamp_regex.search(line)
            if match:
                time_str = match.group()
                # Remove the timestamp and some common separators from the line to get the title
                title = line.replace(time_str, '').strip(' -–:\t➤')
                if not title:
                    title = "Розділ"
                timestamps.append((time_str, title))
        
        return timestamps

    def parse_vtt(self, vtt_path: str) -> List[TranscriptLine]:
        """
        Parses a VTT file and returns a list of TranscriptLine objects.
        """
        transcript = []
        try:
            for caption in webvtt.read(vtt_path):
                # webvtt returns time as "00:00:00.000", let's strip the ms for simple comparison
                start = caption.start.split('.')[0]
                end = caption.end.split('.')[0]
                text = caption.text.strip().replace('\n', ' ')
                if text:
                    transcript.append(TranscriptLine(start_time=start, end_time=end, text=text))
        except Exception as e:
            print(f"Error parsing VTT file {vtt_path}: {e}")
        
        return transcript

    def convert_to_seconds(self, time_str: str) -> int:
        """
        Converts "HH:MM:SS" or "MM:SS" to total seconds.
        """
        parts = time_str.split(':')
        parts = [int(p) for p in parts]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return 0

    def seconds_to_timestamp(self, seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def plain_text_to_transcript_lines(self, text: str, duration_seconds: int = None) -> List[TranscriptLine]:
        """
        Converts a stitched plain-text transcript into timestamped transcript lines.
        Groq returns the final clean transcript as text; this keeps downstream grouping
        compatible with the existing timestamp-based Markdown converter.
        """
        text = (text or "").strip()
        if not text:
            return []

        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if current and len(current) + len(sentence) > 700:
                chunks.append(current.strip())
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current.strip())

        if not chunks:
            chunks = [text]

        total_duration = duration_seconds or max(len(chunks) * 20, 1)
        seconds_per_chunk = max(total_duration / len(chunks), 1)

        transcript = []
        for index, chunk_text in enumerate(chunks):
            start = index * seconds_per_chunk
            end = min((index + 1) * seconds_per_chunk, total_duration)
            transcript.append(
                TranscriptLine(
                    start_time=self.seconds_to_timestamp(start),
                    end_time=self.seconds_to_timestamp(end),
                    text=chunk_text,
                )
            )
        return transcript

    def group_transcript_by_timestamps(self, transcript: List[TranscriptLine], timestamps: List[Tuple[str, str]]) -> Dict[str, List[str]]:
        """
        Groups transcript lines into sections based on the timestamps from description.
        Returns a dict: { "00:00 Intro": ["text line 1", "text line 2"], ... }
        If no timestamps provided, everything goes under "00:00 Транскрипт".
        """
        if not timestamps:
            default_title = "00:00 Транскрипт"
            return {default_title: [line.text for line in transcript]}

        grouped = {}
        
        # Sort timestamps by seconds to be sure
        sorted_timestamps = sorted(timestamps, key=lambda x: self.convert_to_seconds(x[0]))
        
        current_section_idx = 0
        current_title = f"{sorted_timestamps[0][0]} {sorted_timestamps[0][1]}"
        grouped[current_title] = []

        for line in transcript:
            line_sec = self.convert_to_seconds(line.start_time)
            
            # Check if we should move to the next section
            if current_section_idx + 1 < len(sorted_timestamps):
                next_sec = self.convert_to_seconds(sorted_timestamps[current_section_idx + 1][0])
                if line_sec >= next_sec:
                    current_section_idx += 1
                    current_title = f"{sorted_timestamps[current_section_idx][0]} {sorted_timestamps[current_section_idx][1]}"
                    grouped[current_title] = []
            
            grouped[current_title].append(line.text)

        # Merge short consecutive lines to make paragraphs
        for k, v in grouped.items():
            merged = []
            paragraph = ""
            for text in v:
                paragraph += text + " "
                if len(paragraph) > 300 and text.endswith(('.', '?', '!')):
                    merged.append(paragraph.strip())
                    paragraph = ""
            if paragraph:
                merged.append(paragraph.strip())
            grouped[k] = merged

        return grouped
