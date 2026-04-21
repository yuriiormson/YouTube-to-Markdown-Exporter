import sys
sys.path.append('.')
from core.yt_client import YTClient

client = YTClient({
    'language': 'en',
    'cookies_from_browser': 'chrome',
    'js_runtime': 'node',
    'retries': 3,
    'delay': 1
})

print("Fetching videos...")
videos = client.get_channel_videos("https://www.youtube.com/@arestovych/videos")
print(f"Found {len(videos)} videos matching the new multi-signal filter.")
for v in videos[:5]:
    print(f"- {v.title}")
