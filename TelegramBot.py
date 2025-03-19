import os
import json
import logging
import re
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters.command import Command
from aiogram.types import FSInputFile
import asyncio
from moviepy.editor import VideoFileClip
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
import time
import subprocess

# Load environment variables
load_dotenv()

# Get API keys from environment variables
TELEGRAM_BOT_TOKEN = os.getenv(7680645796:AAGHvl0xgFg2nkiQTAEHE81oHvqCMVHs5YA)
YOUTUBE_API_KEY = os.getenv(AIzaSyCEGsG-0CLb_jga0SdrzsE0hO8It_L3zJ4)

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
CACHE_FOLDER = "cache"
REELS_FOLDER = "reels"
CACHE_FILE = os.path.join(CACHE_FOLDER, "cache.json")
TEMP_FOLDER = "temp"

# Create necessary directories
for folder in [CACHE_FOLDER, REELS_FOLDER, TEMP_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# Initialize YouTube API
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

# Cache management functions
def load_cache():
    """Load cache from file or return empty dict if file doesn't exist"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as file:
                return json.load(file)
        except json.JSONDecodeError:
            logger.error("Cache file corrupted, creating new cache")
            return {}
    return {}

def save_cache(cache):
    """Save cache to file"""
    with open(CACHE_FILE, "w") as file:
        json.dump(cache, file)

def is_video_cached(video_id):
    """Check if video is already in cache"""
    cache = load_cache()
    return video_id in cache and all(os.path.exists(path) for path in cache[video_id])

def cache_video(video_id, reels):
    """Add video to cache"""
    cache = load_cache()
    cache[video_id] = reels
    save_cache(cache)

def get_cached_reels(video_id):
    """Get cached reels for a video"""
    cache = load_cache()
    return cache.get(video_id, [])

# YouTube video processing functions
def get_video_id(url):
    """Extract video ID from YouTube URL"""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([^ &?/]+)',
        r'youtube\.com/shorts/([^ &?/]+)'
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

async def download_video(video_id):
    """Download YouTube video using yt-dlp"""
    output_path = os.path.join(TEMP_FOLDER, f"{video_id}.mp4")

    if os.path.exists(output_path):
        return output_path

    try:
        process = await asyncio.create_subprocess_exec(
            "yt-dlp", 
            "-f", "best[height<=720]", 
            "-o", output_path,
            f"https://www.youtube.com/watch?v={video_id}",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120  # Timeout after 120 seconds
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"Error downloading video: {stderr.decode()}")
            return None

        return output_path

    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        return None

def get_video_details(video_id):
    """Fetch video details using YouTube Data API"""
    request = youtube.videos().list(
        part='snippet,statistics',
        id=video_id
    )
    response = request.execute()
    return response['items'][0] if response['items'] else None

def get_transcript(video_id):
    """Fetch video transcript using youtube_transcript_api"""
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        return transcript
    except Exception as e:
        logger.warning(f"Could not fetch transcript: {e}")
        return []

async def find_viral_segments(video_path, video_id, video_details, transcript):
    """Identify viral segments based on transcript and other factors"""
    segments = []

    if not transcript:
        logger.warning("No transcript available for viral segment detection.")
        return segments

    # Process transcript to find interesting segments
    for i in range(len(transcript) - 29):
        window = transcript[i:i+30]
        start_time = window[0]["start"]
        end_time = window[-1]["start"] + window[-1]["duration"]

        # Ensure segment is at least 30 seconds long
        if end_time - start_time > 30:
            end_time = start_time + 30

        # Skip if segment is too short
        if end_time - start_time < 5:
            continue

        # Calculate a score based on various factors
        text = " ".join([entry["text"] for entry in window])

        # Simple keyword-based scoring
        keywords = ["amazing", "incredible", "wow", "awesome", "best", "perfect", 
                    "insane", "unbelievable", "shocking", "surprising"]

        # Count keywords in text
        keyword_count = sum(1 for keyword in keywords if keyword.lower() in text.lower())

        # Basic score calculation
        score = 1.0 + (keyword_count * 0.2)

        segments.append({
            "start": start_time,
            "end": end_time,
            "score": score,
            "text": text
        })

    # Sort segments by score and take the top 5
    segments.sort(key=lambda x: x["score"], reverse=True)
    return segments[:5]

async def create_reels(video_path, segments, video_id):
    """Create reel clips from the identified segments"""
    reel_paths = []

    try:
        clip = VideoFileClip(video_path)

        for i, segment in enumerate(segments):
            start_time = segment["start"]
            end_time = segment["end"]

            # Ensure start_time and end_time are within video duration
            if start_time >= clip.duration or end_time > clip.duration:
                logger.warning(f"Segment {i} out of video duration bounds, skipping")
                continue

            # Create unique filename
            timestamp = int(time.time())
            reel_path = os.path.join(REELS_FOLDER, f"{video_id}_reel_{i}_{timestamp}.mp4")

            # Extract segment and write to file
            logger.info(f"Creating reel {i+1} from {start_time} to {end_time}")
            sub_clip = clip.subclip(start_time, end_time)

            # Write video file with reasonable settings
            sub_clip.write_videofile(
                reel_path, 
                codec="libx264", 
                audio_codec="aac",
                fps=24, 
                preset="medium",
                threads=2,
                verbose=False,
                logger=None
            )

            reel_paths.append(reel_path)

        clip.close()
        return reel_paths

    except Exception as e:
        logger.error(f"Error creating reels: {e}")
        if 'clip' in locals():
            clip.close()
        return []

# Bot command handlers
@dp.message(Command("start"))
async def start_command(message: types.Message):
    """Handle /start command"""
    await message.reply(
        "👋 Welcome to YouTube Viral Reels Bot!\n\n"
        "Send me a YouTube video link, and I'll generate up to 5 viral reels from it.\n\n"
        "Just paste the URL and I'll take care of the rest!"
    )

@dp.message(Command("help"))
async def help_command(message: types.Message):
    """Handle /help command"""
    await message.reply(
        "📖 *YouTube Viral Reels Bot Help*\n\n"
        "This bot creates viral reels from YouTube videos. Here's how to use it:\n\n"
        "1. Simply paste a YouTube video URL\n"
        "2. Wait while I process the video\n"
        "3. Receive up to 5 viral reels extracted from the video\n\n"
        "Supported URL formats:\n"
        "• youtube.com/watch?v=VIDEO_ID\n"
        "• youtu.be/VIDEO_ID\n"
        "• youtube.com/shorts/VIDEO_ID\n\n"
        "For any issues, contact the developer.",
        parse_mode="MarkdownV2"
    )

@dp.message(F.text)
async def process_youtube_link(message: types.Message):
    """Handle YouTube links and process videos"""
    url = message.text.strip()
    video_id = get_video_id(url)

    if not video_id:
        await message.reply("❌ This doesn't look like a valid YouTube URL. Please send a valid YouTube video link.")
        return

    progress_message = await message.reply("🔍 Analyzing YouTube video...")

    try:
        # Check cache first
        if is_video_cached(video_id):
            await bot.edit_message_text("🎬 Found cached reels! Sending them now...", 
                                      chat_id=message.chat.id, 
                                      message_id=progress_message.message_id)
            reels = get_cached_reels(video_id)

            for i, reel_path in enumerate(reels):
                if os.path.exists(reel_path):
                    await bot.send_video(
                        message.chat.id, 
                        FSInputFile(reel_path),
                        caption=f"Viral Reel #{i+1} from your video"
                    )
                else:
                    logger.warning(f"Cached reel {reel_path} not found")

            await bot.send_message(
                message.chat.id,
                "✅ All done! These are the top viral moments from your video."
            )
            return

        # Fetch video details
        await bot.edit_message_text("🔍 Fetching video details...", 
                                  chat_id=message.chat.id, 
                                  message_id=progress_message.message_id)
        video_details = get_video_details(video_id)

        if not video_details:
            await bot.edit_message_text("❌ Couldn't retrieve video information. Please try again later.", 
                                      chat_id=message.chat.id, 
                                      message_id=progress_message.message_id)
            return

        # Download video
        await bot.edit_message_text("⬇️ Downloading video...", 
                                  chat_id=message.chat.id, 
                                  message_id=progress_message.message_id)
        video_path = await download_video(video_id)

        if not video_path:
            await bot.edit_message_text("❌ Failed to download video. Please try again later.", 
                                      chat_id=message.chat.id, 
                                      message_id=progress_message.message_id)
            return

        # Get transcript if available
        transcript = get_transcript(video_id)

        # Find viral segments
        await bot.edit_message_text("🔎 Identifying viral moments...", 
                                  chat_id=message.chat.id, 
                                  message_id=progress_message.message_id)
        segments = await find_viral_segments(video_path, video_id, video_details, transcript)

        if not segments:
            await bot.edit_message_text("⚠️ Couldn't identify viral moments in this video.", 
                                      chat_id=message.chat.id, 
                                      message_id=progress_message.message_id)
            return

        # Create reels
        await bot.edit_message_text("✂️ Creating reels (this may take a few minutes)...", 
                                  chat_id=message.chat.id, 
                                  message_id=progress_message.message_id)
        reels = await create_reels(video_path, segments, video_id)

        if not reels:
            await bot.edit_message_text("❌ Failed to create reels. Please try again later.", 
                                      chat_id=message.chat.id, 
                                      message_id=progress_message.message_id)
            return

        # Cache the results
        cache_video(video_id, reels)

        # Send reels to user
        await bot.edit_message_text("📤 Sending reels...", 
                                  chat_id=message.chat.id, 
                                  message_id=progress_message.message_id)

        for i, reel_path in enumerate(reels):
            await bot.send_video(
                message.chat.id, 
                FSInputFile(reel_path),
                caption=f"Viral Reel #{i+1} from your video"
            )

        # Delete temporary downloaded video to save space
        if os.path.exists(video_path):
            os.remove(video_path)

        await bot.send_message(
            message.chat.id,
            "✅ All done! These are the top viral moments from your video."
        )

    except Exception as e:
        logger.error(f"Error processing video: {e}")
        await bot.edit_message_text(f"❌ An error occurred: {str(e)[:100]}...\nPlease try again later.", 
                                   chat_id=message.chat.id, 
                                   message_id=progress_message.message_id)

async def main():
    # Start bot
    logger.info("Starting bot...")
    try:
        logger.info("Bot started successfully!")
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
    finally:
        logger.info("Bot stopped")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")