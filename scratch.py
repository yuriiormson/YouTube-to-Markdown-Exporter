import os
import yt_dlp

ydl_opts = {
    'quiet': True,
    'skip_download': True,
    'writesubtitles': True,
    'writeautomaticsub': True,
    'subtitlesformat': 'vtt',
    'subtitleslangs': ['uk', 'ru', 'en'],
    'outtmpl': '%(id)s.%(ext)s',
    'cookiesfrombrowser': ('chrome',),
    'extractor_args': {
        'youtube': {
            'player_client': ['web']
        }
    }
}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    ydl.download(['https://www.youtube.com/watch?v=aqz-KE-bpKQ'])

print([f for f in os.listdir('.') if 'aqz-KE-bpKQ' in f])
