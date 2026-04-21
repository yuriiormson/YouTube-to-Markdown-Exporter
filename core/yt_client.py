import os
import tempfile
import time
from http.cookiejar import MozillaCookieJar
import yt_dlp
from typing import List, Optional
from models.data_models import VideoMeta
from requests import Session
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import WebVTTFormatter
from youtube_transcript_api.proxies import GenericProxyConfig

def is_target_video(title: str, description: str, filters: dict, debug: bool = False) -> bool:
    title_lower = title.lower()
    description_lower = (description or "").lower()
    text = f"{title_lower} {description_lower}"

    LIVE_KEYWORDS = [k.lower() for k in filters.get("live", [])]
    TOPIC_KEYWORDS = [k.lower() for k in filters.get("topic", [])]
    BRAND_KEYWORDS = [k.lower() for k in filters.get("brand", [])]

    has_live = any(k in text for k in LIVE_KEYWORDS) if LIVE_KEYWORDS else True
    has_topic = any(k in text for k in TOPIC_KEYWORDS) if TOPIC_KEYWORDS else True
    has_brand = any(k in text for k in BRAND_KEYWORDS) if BRAND_KEYWORDS else True
    
    # User's heuristic: has_live and (has_topic or has_brand)
    # If no filters were provided, this will evaluate to True, but since we assume filters are provided in config:
    is_target = has_live and (has_topic or has_brand)

    if debug:
        print(f"[FILTER] {title}")
        print(f"  live={has_live}, topic={has_topic}, brand={has_brand}")
        if is_target:
            print(f"[FILTER] INCLUDED: {title}")
        else:
            print(f"[FILTER] SKIPPED: {title}")

    return is_target

class YTClient:
    def __init__(self, config: dict):
        self.languages = config.get("languages", ["ru", "uk", "en"])
        self.proxy = config.get("proxy")
        self.cookies_from_browser = config.get("cookies_from_browser", "chrome")
        self.js_runtime = config.get("js_runtime", "node")
        self.retries = config.get("retries", 5)
        self.delay = config.get("delay", 5)
        self.use_browser_cookies = False
        self.cookies_path = self._resolve_cookies_path(config.get("cookies_path"))

    def _resolve_cookies_path(self, cookies_path: Optional[str]) -> Optional[str]:
        if cookies_path:
            expanded_path = os.path.expanduser(cookies_path)
            if os.path.exists(expanded_path):
                return expanded_path

        self.use_browser_cookies = True
        print("🔐 No valid cookies file found. Reading YouTube cookies from Chrome...")
        cookies_path = self._extract_cookies_from_chrome()
        print(f"Saved Chrome YouTube cookies to: {cookies_path}")
        return cookies_path

    def _extract_cookies_from_chrome(self) -> str:
        from copy import copy
        from yt_dlp.cookies import YoutubeDLCookieJar, extract_cookies_from_browser

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.close()

        try:
            browser_cookie_jar = extract_cookies_from_browser(self.cookies_from_browser)
            youtube_cookie_jar = YoutubeDLCookieJar()

            for cookie in browser_cookie_jar:
                if "youtube.com" in cookie.domain:
                    youtube_cookie_jar.set_cookie(copy(cookie))

            if not any(cookie.name == "SSID" for cookie in youtube_cookie_jar):
                print(
                    "⚠️ Chrome cookies were extracted, but SSID was not found. "
                    "Make sure Chrome is logged in to YouTube."
                )

            youtube_cookie_jar.save(
                tmp.name,
                ignore_discard=True,
                ignore_expires=True,
            )
            return tmp.name
        except Exception:
            os.unlink(tmp.name)
            raise

    def _build_transcript_api(self) -> YouTubeTranscriptApi:
        http_client = None
        proxy_config = None

        if self.cookies_path:
            cookie_jar = MozillaCookieJar(self.cookies_path)
            cookie_jar.load(ignore_discard=True, ignore_expires=True)
            http_client = Session()
            http_client.cookies = cookie_jar

        if self.proxy:
            proxy_config = GenericProxyConfig(https_url=self.proxy)

        return YouTubeTranscriptApi(
            proxy_config=proxy_config,
            http_client=http_client,
        )

    def _build_ydl_opts(self):
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'extract_flat': True
        }
        if self.cookies_path:
            ydl_opts['cookiefile'] = self.cookies_path
        return ydl_opts

    def _retry(self, func, video_id):
        NON_RETRY_ERRORS = [
            "Requested format is not available",
            "Only images are available",
            "n challenge solving failed"
        ]

        for attempt in range(1, self.retries + 1):
            try:
                return func()
            except Exception as e:
                error_str = str(e)
                if any(err in error_str for err in NON_RETRY_ERRORS):
                    print(f"[{video_id}] Non-retryable error. Skipping retries.")
                    return None
                    
                if attempt == self.retries:
                    return None

                time.sleep(2 ** attempt)

    def get_channel_videos(self, url_param: str, filters: dict = None, limit: Optional[int] = None, debug: bool = False) -> List[VideoMeta]:
        filters = filters or {}
        # If it's a base channel URL, fetch both videos and streams tabs explicitly
        if '@' in url_param and not any(url_param.rstrip('/').endswith(suffix) for suffix in ['/videos', '/streams', '/shorts', '/podcasts', '/playlists', '/releases']):
            videos = []
            videos.extend(self.get_channel_videos(url_param.rstrip('/') + '/videos', filters, limit, debug))
            if limit and len(videos) >= limit:
                return videos[:limit]
            videos.extend(self.get_channel_videos(url_param.rstrip('/') + '/streams', filters, limit, debug))
            return videos[:limit] if limit else videos

        ydl_opts = self._build_ydl_opts()
        ydl_opts.update({
            'dump_single_json': True,
        })

        videos = []
        def fetch():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url_param, download=False)
        
        info = self._retry(fetch, url_param)
        if info:
            try:
                if 'entries' in info:
                    for entry in info['entries']:
                        if entry:
                            vid = entry.get('id', '')
                            # Skip if not a valid video
                            if len(vid) != 11 or vid.startswith('UC'):
                                continue

                            title = entry.get('title', '')
                            description = entry.get('description', '')
                            
                            if not is_target_video(title, description, filters, debug):
                                continue

                            video = VideoMeta(
                                video_id=vid,
                                title=title,
                                url=entry.get('url', f"https://www.youtube.com/watch?v={vid}"),
                                published_at=entry.get('timestamp', entry.get('upload_date', '')), 
                                description=description,
                                duration=entry.get('duration')
                            )
                            videos.append(video)
                            
                            if limit and len(videos) >= limit:
                                break
                else:
                    # Single video case
                    title = info.get('title', '')
                    description = info.get('description', '')
                    if is_target_video(title, description, filters, debug):
                        video = VideoMeta(
                            video_id=info.get('id', ''),
                            title=title,
                            url=info.get('webpage_url', f"https://www.youtube.com/watch?v={info.get('id')}"),
                            published_at=info.get('upload_date', ''),
                            description=description,
                            duration=info.get('duration')
                        )
                        videos.append(video)
            except Exception as e:
                print(f"Error parsing channel videos: {e}")

        return videos

    def get_full_video_info(self, video_id: str) -> VideoMeta:
        ydl_opts = self._build_ydl_opts()

        def fetch():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        
        info = self._retry(fetch, video_id) or {}
            
        url = f"https://www.youtube.com/watch?v={video_id}"
        return VideoMeta(
            video_id=video_id,
            title=info.get('title') or video_id,
            url=url,
            published_at=info.get('upload_date', ''),
            description=info.get('description', ''),
            duration=info.get('duration'),
            tags=info.get('tags', [])
        )

    def download_subtitles(self, video_id: str, output_dir: str) -> Optional[str]:
        try:
            api = self._build_transcript_api()
            data = api.fetch(video_id, languages=self.languages)
            formatter = WebVTTFormatter()
            vtt_formatted = formatter.format_transcript(data)
            output_path = os.path.join(output_dir, f"{video_id}.vtt")
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(vtt_formatted)
            print(f"[{video_id}] ✅ Transcript loaded")
            return output_path
        except Exception as e:
            print(f"[{video_id}] ❌ Transcript error:", e)
            return None
