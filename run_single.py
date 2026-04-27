from core.yt_client import YTClient
from core.parser import Parser
from core.converter import Converter
from core.database import Database
from core.state import StateManager
from models.data_models import AppConfig
from main import process_video

config = AppConfig(
    channel_url="test",
    output_dir="output/test_structured",
    db_path=":memory:",
    state_path="output/test_structured/state.json",
)
client = YTClient(config.model_dump())
parser = Parser()
converter = Converter(config.output_dir)
db = Database(config.db_path)
state_manager = StateManager(config.state_path)

video_id = "3xABFjV9iVM"
meta = client.get_full_video_info(video_id)
if meta.title == "UNKNOWN" or not meta.title:
    meta.title = video_id
has_transcript = process_video(meta, client, parser, converter, db, config, state_manager)
print(f"Generated with transcript: {has_transcript}")
