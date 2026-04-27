import os
import argparse
import yaml
from datetime import datetime
import traceback

from models.data_models import AppConfig, VideoRecord, VideoMeta
from core.aggregator import generate_combined_markdown
from core.audio_chunker import AudioChunker, FFmpegError
from core.database import Database
from core.groq_transcriber import GroqTranscriptionError, GroqWhisperTranscriber
from core.yt_client import YTClient
from core.parser import Parser
from core.converter import Converter, normalize_filename
from core.state import StateManager
from core.transcript_stitcher import normalize_transcript, stitch_chunk_transcripts
from core.yt_client import AudioExtractionError

def sync_db_with_files(db: Database):
    for record in db.get_all():
        if record.markdown_path and not os.path.exists(record.markdown_path):
            print(f"[{record.video_id}] Removing stale DB record (file missing)")
            db.delete(record.video_id)

def load_config(config_path: str) -> AppConfig:
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return AppConfig(**data)

def _write_failed_record(db: Database, video: VideoMeta, status: str = "FAILED"):
    existing = db.get_video(video.video_id)
    record = VideoRecord(
        video_id=video.video_id,
        title=video.title,
        url=video.url,
        published_at=video.published_at,
        markdown_path=existing.markdown_path if existing else None,
        processed_at=datetime.now(),
        status=status,
    )
    db.upsert_video(record)


def _read_transcript(transcript_path: str) -> str:
    with open(transcript_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _write_transcript(transcript_path: str, transcript: str) -> None:
    os.makedirs(os.path.dirname(transcript_path), exist_ok=True)
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(transcript.strip())
        f.write("\n")


def process_video(
    video: VideoMeta,
    client: YTClient,
    parser: Parser,
    converter: Converter,
    db: Database,
    config: AppConfig,
    state_manager: StateManager,
    force_reprocess: bool = False,
):
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

    source_video_filename = normalize_filename(video.title or video_id) + ".mp3"
    state = state_manager.ensure_state(video_id, source_video_filename)

    if (
        not force_reprocess
        and state.status in {"completed", "no_speech"}
        and state.final_note_path
        and os.path.exists(state.final_note_path)
    ):
        print(f"[{video_id}] Resume: final note already exists, skipping")
        db_status = "SUCCESS" if state.status == "completed" else "NO_SPEECH"
        db.upsert_video(
            VideoRecord(
                video_id=video.video_id,
                title=video.title,
                url=video.url,
                published_at=video.published_at,
                markdown_path=state.final_note_path,
                processed_at=datetime.now(),
                status=db_status,
            )
        )
        return state.status == "completed"

    try:
        transcripts_dir = os.path.join(config.output_dir, "_transcripts")
        default_transcript_path = os.path.join(transcripts_dir, f"{video_id}.txt")
        transcript_path = state.transcript_path if state.transcript_path and os.path.exists(state.transcript_path) else default_transcript_path
        final_transcript = ""

        if os.path.exists(transcript_path) and os.path.getsize(transcript_path) > 0:
            print(f"[{video_id}] Resume: stitched transcript already exists, skipping transcription")
            final_transcript = _read_transcript(transcript_path)
            state = state_manager.update_state(
                video_id,
                status="transcribed",
                transcript_path=transcript_path,
                error_message=None,
            )
        else:
            mp3_path = state.mp3_path
            if mp3_path and os.path.exists(mp3_path):
                print(f"[{video_id}] Resume: audio already extracted")
            else:
                print(f"[{video_id}] Extracting audio")
                mp3_path = client.download_audio(video_id, config.output_dir)
            state = state_manager.update_state(
                video_id,
                status="audio_extracted",
                mp3_path=mp3_path,
                error_message=None,
            )

            chunker = AudioChunker(
                chunk_duration_seconds=config.chunk_duration_seconds,
                chunk_overlap_seconds=config.chunk_overlap_seconds,
            )
            chunk_dir = state.chunk_temp_dir or os.path.join(config.output_dir, "_chunks", video_id)
            chunks = chunker.load_chunks(chunk_dir) if os.path.exists(chunk_dir) else []
            if chunks:
                print(f"[{video_id}] Resume: using {len(chunks)} existing audio chunks")
            else:
                print(f"[{video_id}] Creating audio chunks")
                chunks = chunker.create_chunks(mp3_path, chunk_dir)
            print(f"[{video_id}] Created {len(chunks)} audio chunks")
            state = state_manager.update_state(
                video_id,
                status="chunked",
                chunk_temp_dir=chunk_dir,
                error_message=None,
            )

            transcriber = GroqWhisperTranscriber(
                api_key=config.groq_api_key,
                model=config.groq_model,
                language=config.transcription_language,
                max_retries=config.max_retries,
                retry_backoff_seconds=config.retry_backoff_seconds,
            )

            existing_results = {item.chunk_index: item for item in state.chunk_transcripts}
            state_manager.update_state(video_id, status="transcribing")
            for chunk in chunks:
                if chunk.chunk_index in existing_results:
                    print(f"[{video_id}] Chunk {chunk.chunk_index + 1}/{len(chunks)} already transcribed, skipping")
                    continue

                print(f"[{video_id}] Transcribing chunk {chunk.chunk_index + 1}/{len(chunks)}")
                result = transcriber.transcribe_chunk(chunk)
                state = state_manager.record_chunk_result(video_id, result)
                existing_results[result.chunk_index] = result

            state = state_manager.get_state(video_id)
            chunk_results = state.chunk_transcripts if state else []
            final_transcript = stitch_chunk_transcripts(chunk_results)
            final_transcript = normalize_transcript(final_transcript)

            print(f"[{video_id}] Stitching complete")
            chunker.cleanup_chunks(chunk_dir)
            print(f"[{video_id}] Temporary chunks removed")

            if final_transcript:
                _write_transcript(transcript_path, final_transcript)
                state = state_manager.update_state(
                    video_id,
                    status="transcribed",
                    transcript_path=transcript_path,
                    error_message=None,
                )
            else:
                state = state_manager.update_state(
                    video_id,
                    status="no_speech",
                    transcript_path=None,
                    error_message="No speech detected in transcribed chunks",
                )

        has_transcript = bool(final_transcript)
        timestamps = parser.parse_description_timestamps(video.description)
        transcript_lines = parser.plain_text_to_transcript_lines(final_transcript, duration_seconds=video.duration)
        grouped_transcript = parser.group_transcript_by_timestamps(transcript_lines, timestamps)

        print(f"[{video_id}] Writing Markdown note")
        md_path = converter.generate_markdown(
            video,
            grouped_transcript,
            timestamps,
            has_transcript=has_transcript,
            transcript_source="groq_whisper",
            transcript_status="available" if has_transcript else "no_speech",
        )
        print(f"[{video_id}] Markdown saved")

        state_manager.update_state(video_id, status="note_written", final_note_path=md_path)
        final_state_status = "completed" if has_transcript else "no_speech"
        state_manager.update_state(video_id, status=final_state_status, final_note_path=md_path)

        db_status = "SUCCESS" if has_transcript else "NO_SPEECH"
        record = VideoRecord(
            video_id=video.video_id,
            title=video.title,
            url=video.url,
            published_at=video.published_at,
            markdown_path=md_path,
            processed_at=datetime.now(),
            status=db_status,
        )
        db.upsert_video(record)
        return has_transcript

    except AudioExtractionError as e:
        message = f"ffmpeg failure: {e}" if "ffmpeg" in str(e).lower() else f"audio extraction failure: {e}"
        print(f"[{video_id}] {message}")
        state_manager.mark_failed(video_id, message)
        _write_failed_record(db, video)
        raise
    except FFmpegError as e:
        message = f"ffmpeg failure: {e}"
        print(f"[{video_id}] {message}")
        state_manager.mark_failed(video_id, message)
        _write_failed_record(db, video)
        raise
    except GroqTranscriptionError as e:
        message = f"API failure: {e}" if "groq" in str(e).lower() else f"transcription failure: {e}"
        print(f"[{video_id}] {message}")
        state_manager.mark_failed(video_id, message)
        _write_failed_record(db, video)
        raise
    except Exception as e:
        message = f"transcription failure: {e}"
        print(f"[{video_id}] {message}")
        state_manager.mark_failed(video_id, message)
        _write_failed_record(db, video)
        raise

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
    arg_parser.add_argument('--reset-state', action='store_true', help='Reset JSON resume state')
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

    if args.reset_state:
        if os.path.exists(config.state_path):
            os.remove(config.state_path)
            print("State reset")

    if not (args.initial or args.update or args.reprocess or args.force):
        if args.reset_db or args.clean_output or args.reset_state:
            return # Just ran cleanup commands
        print("Please specify an action (e.g., --initial, --update, --reprocess, --force).")
        return

    db = Database(config.db_path)
    sync_db_with_files(db)
    state_manager = StateManager(config.state_path)
    
    client = YTClient(config.model_dump())
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
            if record and record.status in {"SUCCESS", "NO_SPEECH"}:
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
                has_transcript = process_video(
                    video,
                    client,
                    parser,
                    converter,
                    db,
                    config,
                    state_manager,
                    force_reprocess=args.force or args.reprocess,
                )
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

    combined_path = generate_combined_markdown(config.output_dir, config.combined_markdown_filename)
    if combined_path:
        print(f"Combined Markdown saved: {combined_path}")

if __name__ == '__main__':
    main()
