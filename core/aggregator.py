import os
from typing import Optional


def generate_combined_markdown(output_dir: str, combined_filename: str = "combined_notes.md") -> Optional[str]:
    if not os.path.isdir(output_dir):
        return None

    note_paths = []
    combined_path = os.path.join(output_dir, combined_filename)
    for filename in os.listdir(output_dir):
        path = os.path.join(output_dir, filename)
        if not os.path.isfile(path):
            continue
        if not filename.endswith(".md"):
            continue
        if filename == combined_filename:
            continue
        if filename.startswith("_") or filename.startswith("."):
            continue
        note_paths.append(path)

    note_paths.sort(key=lambda path: os.path.basename(path).casefold())
    if not note_paths:
        return None

    sections = []
    for path in note_paths:
        with open(path, "r", encoding="utf-8") as f:
            sections.append(f.read().strip())

    with open(combined_path, "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join(section for section in sections if section))
        f.write("\n")

    return combined_path
