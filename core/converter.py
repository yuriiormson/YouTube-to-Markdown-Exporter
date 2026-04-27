import os
import yaml
import re
import unicodedata
from datetime import datetime
from typing import Dict, List, Tuple
from models.data_models import VideoMeta

def normalize_filename(name: str) -> str:
    name = unicodedata.normalize("NFC", name)
    name = name.replace("/", "_").replace(":", "")
    return name

def clean_transcript(text: str) -> str:
    text = re.sub(r"\d{2}:\d{2}:\d{2}\.\d+ --> .*", "", text)
    text = re.sub(r"<.*?>", "", text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()

TOPIC_MARKERS = [
    "вопрос",
    "следующий",
    "давайте",
    "теперь",
    "спрашивают"
]

def split_sentences(text: str):
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]

def split_topics(sentences):
    topics = []
    current = []
    for s in sentences:
        if any(k in s.lower() for k in TOPIC_MARKERS) and current:
            topics.append(" ".join(current))
            current = []
        current.append(s)
    if current:
        topics.append(" ".join(current))
    return topics

def generate_title(topic_text):
    first_sentence = topic_text.split(".")[0].split("?")[0].split("!")[0]
    words = first_sentence.split()[:8]
    title = " ".join(words)
    if not title:
        title = "Раздел"
    # Ensure first letter is capitalized
    return title[0].upper() + title[1:] if title else title

def is_question(text):
    return "?" in text or "вопрос" in text.lower()

def format_qa(topic, level="###"):
    if is_question(topic):
        if "?" in topic:
            parts = topic.split("?")
            question = parts[0] + "?"
            answer = "?".join(parts[1:]).strip()
            # if question is too long, it might be a false positive
            if len(question.split()) < 30:
                return f"{level} ❓ {question}\n\n{answer}\n"
        
        # Fallback if "?" not present but "вопрос" is, or if question was too long
        sentences = re.split(r'(?<=[.!?])\s+', topic)
        if sentences:
            question = sentences[0]
            answer = " ".join(sentences[1:]).strip()
            return f"{level} ❓ {question}\n\n{answer}\n"
            
    return None

def build_structured_transcript(text: str, level: str = "###") -> str:
    sentences = split_sentences(text)
    topics = split_topics(sentences)
    sections = []
    for topic in topics:
        if not topic.strip():
            continue
        qa = format_qa(topic, level)
        if qa:
            sections.append(qa)
        else:
            title = generate_title(topic)
            sections.append(f"{level} 💡 {title}...\n\n{topic}\n")
    return "\n".join(sections)

class Converter:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_markdown(
        self,
        video: VideoMeta,
        grouped_transcript: Dict[str, List[str]],
        timestamps: List[Tuple[str, str]],
        has_transcript: bool = False,
        transcript_source: str = "groq_whisper",
        transcript_status: str = None,
    ) -> str:
        # Fallbacks
        title = video.title or f"Video {video.video_id}"
        description = video.description or "No description available"
        published = video.published_at or ""

        filename = normalize_filename(title) + ".md"
        filepath = os.path.join(self.output_dir, filename)
        print(f"[{video.video_id}] Filename normalized")

        # 1. Generate YAML Frontmatter
        frontmatter = {
            "title": title,
            "source": video.url,
            "transcript_status": transcript_status or ("available" if has_transcript else "missing"),
            "transcript_source": transcript_source if has_transcript else "none",
            "author": "Alexey Arestovych",
            "published": published,
            "description": description,
            "created": datetime.now().strftime("%Y-%m-%d"),
            "tags": [tag.replace(' ', '-') for tag in video.tags] + ["YouTube", "Arestovych", "Transcript"],
            "video_id": video.video_id
        }

        yaml_str = yaml.dump(frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False)

        # 2. Start building Markdown
        md_lines = []
        md_lines.append("---")
        md_lines.append(yaml_str.strip())
        md_lines.append("---\n")

        md_lines.append(f"# {title}")
        md_lines.append("## Description")
        md_lines.append(f"{description}\n")

        related_concepts = []
        for tag in video.tags:
            tag = tag.strip()
            if tag:
                related_concepts.append(f"[[{tag}]]")
        if related_concepts:
            md_lines.append("## Related Concepts")
            md_lines.append(", ".join(related_concepts) + "\n")

        # Process grouped transcript
        processed_transcript_lines = []
        for section_title, paragraphs in grouped_transcript.items():
            if section_title:
                processed_transcript_lines.append(f"### 📌 {section_title}\n")
            
            raw_text = " ".join(paragraphs)
            cleaned = clean_transcript(raw_text)
            if cleaned:
                # If there was a section title from timestamps, use level 4. Otherwise level 3.
                level = "####" if section_title and section_title != "00:00 Транскрипт" else "###"
                structured = build_structured_transcript(cleaned, level=level)
                processed_transcript_lines.append(f"{structured}\n")
        
        print(f"[{video.video_id}] Transcript structured")

        md_lines.append("## Transcript")
        if not has_transcript:
            md_lines.append("⚠️ Transcript not available for this video\n")
        else:
            md_lines.extend(processed_transcript_lines)

        # 7. Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md_lines))

        return filepath
