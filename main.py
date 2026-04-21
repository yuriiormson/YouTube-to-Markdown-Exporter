import os
import argparse
import yaml
from datetime import datetime
import traceback

from models.data_models import AppConfig, VideoRecord, VideoMeta
from core.database import Database
from core.yt_client import YTClient
from core.parser import Parser, is_valid_transcript
from core.converter import Converter

def sync_db_with_files(db: Database):
    for record in db.get_all():
        if record.markdown_path and not os.path.exists(record.markdown_path):
            print(f"[{record.video_id}] Removing stale DB record (file missing)")
            db.delete(record.video_id)

def load_config(config_path: str) -> AppConfig:
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return AppConfig(**data)

def process_video(video: VideoMeta, client: YTClient, parser: Parser, converter: Converter, db: Database, output_dir: str):
    video_id = video.video_id
    print(f"[{video_id}] Processing started")
    
    metadata_source = "discovery"
    
    try:
        enriched_meta = client.get_full_video_info(video_id)
        if enriched_meta:
            if enriched_meta.title and enriched_meta.title != video_id:
                video.title = enriched_meta.title
            if enriched_meta.description:
                video.description = enriched_meta.description
            if enriched_meta.tags:
                video.tags = enriched_meta.tags
            metadata_source = "yt-dlp"
    except Exception:
        pass # yt-dlp enrichment is optional, ignore failures

    # Fallback title if still empty
    if not video.title or video.title == "UNKNOWN" or video.title == video_id:
        video.title = f"video_{video_id}"
        
    print(f"[{video_id}] Metadata source: {metadata_source}")

    status = "SUCCESS"

    # Download subtitles (using transcript API)
    vtt_path = client.download_subtitles(video_id, output_dir)
    
    transcript = []
    has_transcript = False
    if vtt_path:
        transcript = parser.parse_vtt(vtt_path)
        raw_text = "\n".join([line.text for line in transcript])
        
        if is_valid_transcript(raw_text):
            has_transcript = True
            print(f"[{video_id}] ✅ Real transcript loaded")
            print(f"[{video_id}] Transcript source: API")
        else:
            transcript = []
            status = "NO_TRANSCRIPT"
            print(f"[{video_id}] ❌ No transcript available (YouTube limitation)")
            print(f"[{video_id}] Transcript source: none")
    else:
        status = "NO_TRANSCRIPT"
        print(f"[{video_id}] ❌ No transcript available (YouTube limitation)")
        print(f"[{video_id}] Transcript source: none")

    # Parse Description for timestamps
    timestamps = parser.parse_description_timestamps(video.description)
    
    # Group transcript by timestamps
    grouped_transcript = parser.group_transcript_by_timestamps(transcript, timestamps)
    
    # Convert to Markdown
    md_path = converter.generate_markdown(video, grouped_transcript, timestamps, has_transcript=has_transcript)
    print(f"[{video_id}] Markdown saved")
    
    # Save to DB
    record = VideoRecord(
        video_id=video.video_id,
        title=video.title,
        url=video.url,
        published_at=video.published_at,
        markdown_path=md_path,
        processed_at=datetime.now(),
        status=status
    )
    db.upsert_video(record)
    return has_transcript

def main():
    arg_parser = argparse.ArgumentParser(description="YouTube to Markdown Exporter")
    arg_parser.add_argument('--config', default='config.yaml', help='Path to config file')
    arg_parser.add_argument('--initial', action='store_true', help='Initial run: process all videos')
    arg_parser.add_argument('--update', action='store_true', help='Update mode: process only new videos')
    arg_parser.add_argument('--limit', type=int, default=None, help='Limit the number of videos to process')
    arg_parser.add_argument('--reset-db', action='store_true', help='Reset the database')
    arg_parser.add_argument('--reprocess', action='store_true', help='Reprocess all videos')
    arg_parser.add_argument('--force', action='store_true', help='Force process, ignoring DB')
    arg_parser.add_argument('--clean-output', action='store_true', help='Clean the output directory')
    arg_parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = arg_parser.parse_args()

    print(f"Loading config from {args.config}...")
    config = load_config(args.config)

    if args.reset_db:
        if os.path.exists(config.db_path):
            os.remove(config.db_path)
            print("Database reset")

    if args.clean_output:
        import shutil
        shutil.rmtree(config.output_dir, ignore_errors=True)
        print("Output directory cleaned")

    if not (args.initial or args.update or args.reprocess or args.force):
        if args.reset_db or args.clean_output:
            return # Just ran cleanup commands
        print("Please specify an action (e.g., --initial, --update, --reprocess, --force).")
        return

    db = Database(config.db_path)
    sync_db_with_files(db)
    
    client = YTClient(config.dict())
    parser = Parser()
    converter = Converter(config.output_dir)

    print(f"Fetching videos from {config.channel_url}...")
    # Get a list of videos (lite metadata)
    videos = client.get_channel_videos(config.channel_url, filters=config.filters, limit=args.limit, debug=args.debug)
    print(f"Found {len(videos)} target videos using multi-signal filter")

    processed_count = 0
    skipped_count = 0
    with_transcript = 0
    without_transcript = 0
    
    for video in videos:
        if args.limit and processed_count >= args.limit:
            print(f"Reached limit of {args.limit} videos.")
            break
            
        should_process = False

        if args.force:
            print(f"[{video.video_id}] Force mode → processing")
            should_process = True
        else:
            record = db.get_video(video.video_id)
            if record and record.status == "SUCCESS":
                if not record.markdown_path or not os.path.exists(record.markdown_path):
                    print(f"[{video.video_id}] File missing → reprocessing")
                    should_process = True
                elif args.reprocess:
                    print(f"[{video.video_id}] Reprocess mode → processing")
                    should_process = True
                else:
                    if args.initial:
                        print(f"[{video.video_id}] Already processed → skipping")
                    elif args.update:
                        print(f"[{video.video_id}] Already processed → stopping update")
                        break # Stop on first processed video in update mode
            else:
                should_process = True

        if should_process:
            try:
                import time
                has_transcript = process_video(video, client, parser, converter, db, config.output_dir)
                processed_count += 1
                if has_transcript:
                    with_transcript += 1
                else:
                    without_transcript += 1
                time.sleep(config.processing.delay_between_videos_sec)
            except Exception as e:
                print(f"[{video.video_id}] Unexpected error: {e}")
                traceback.print_exc()
        else:
            skipped_count += 1
            
    print("\n--- Summary ---")
    print(f"Processed: {processed_count}")
    print(f"Skipped: {skipped_count}")
    print(f"With transcript: {with_transcript}")
    print(f"Without transcript: {without_transcript}")

if __name__ == '__main__':
    main()
