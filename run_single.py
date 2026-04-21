from core.yt_client import YTClient
from core.parser import Parser
from core.converter import Converter
from models.data_models import AppConfig

config = AppConfig(
    channel_url="test",
    match_filter="",
    output_dir="output/test_structured",
    db_path=":memory:"
)
client = YTClient({"cookies_from_browser": "chrome"})
parser = Parser()
converter = Converter("output/test_structured")

video_id = "3xABFjV9iVM"
meta = client.get_full_video_info(video_id)
if meta.title == "UNKNOWN" or not meta.title:
    meta.title = video_id
vtt = client.download_subtitles(video_id, "output/test_structured")
transcript = parser.parse_vtt(vtt) if vtt else []
timestamps = parser.parse_description_timestamps(meta.description)
grouped = parser.group_transcript_by_timestamps(transcript, timestamps)
md_path = converter.generate_markdown(meta, grouped, timestamps)
print(f"Generated: {md_path}")
