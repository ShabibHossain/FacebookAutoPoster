"""FacebookAutoPoster

Picks a fresh animal video from Reddit, downloads it with yt-dlp, reformats it
to 9:16 with ffmpeg, and uploads it to a Facebook Page as a Reel (scheduled or
published right away).

All config comes from environment variables (see README.md).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import praw
import requests
import yt_dlp

# ---------- config ----------
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v21.0")  # bump if Meta retires it
PAGE_ID = os.environ["FB_PAGE_ID"]
PAGE_TOKEN = os.environ["FB_PAGE_TOKEN"]  # long-lived Page access token

REDDIT_CLIENT_ID = os.environ["REDDIT_CLIENT_ID"]
REDDIT_CLIENT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "FacebookAutoPoster/1.0")

SUBREDDITS = os.environ.get(
    "SUBREDDITS", "aww+AnimalsBeingBros+AnimalsBeingDerps+Zoomies+rarepuppers"
)
MIN_SECONDS = int(os.environ.get("MIN_SECONDS", "3"))
MAX_SECONDS = int(os.environ.get("MAX_SECONDS", "90"))
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "5"))

# "schedule" = upload now, Facebook publishes LEAD_MINUTES from now
# "now"      = publish immediately
PUBLISH_MODE = os.environ.get("PUBLISH_MODE", "schedule")
LEAD_MINUTES = int(os.environ.get("LEAD_MINUTES", "30"))

ROOT = Path(__file__).parent
WORK = ROOT / "work"
STATE_FILE = ROOT / "posted.json"


# ---------- state ----------
def load_posted():
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_posted(ids):
    STATE_FILE.write_text(json.dumps(ids[-2000:], indent=2))


# ---------- reddit ----------
def candidates(reddit, posted):
    """Yield unposted video posts that fit the Reel length limits."""
    seen = set()
    for window in ("day", "week"):
        for post in reddit.subreddit(SUBREDDITS).top(time_filter=window, limit=60):
            if post.id in seen or post.id in posted:
                continue
            seen.add(post.id)
            if post.stickied or post.over_18 or not post.is_video:
                continue
            video = (post.media or {}).get("reddit_video") or {}
            duration = video.get("duration", 0)
            if not (MIN_SECONDS <= duration <= MAX_SECONDS):
                continue
            yield post


# ---------- media ----------
def download(post):
    WORK.mkdir(exist_ok=True)
    opts = {
        "outtmpl": str(WORK / f"{post.id}.%(ext)s"),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "noprogress": True,
        "retries": 3,
    }
    url = "https://www.reddit.com" + post.permalink
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    path = WORK / f"{post.id}.mp4"
    if not path.exists():
        raise RuntimeError("yt-dlp finished but output file is missing")
    return path


def to_vertical(src, dst):
    """Fit video into 1080x1920 with a blurred copy as background."""
    vf = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:5[bg];"
        "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
            "-filter_complex", vf,
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", str(dst),
        ],
        check=True,
    )


# ---------- facebook ----------
def check(resp, step):
    if not resp.ok:
        print(f"[facebook:{step}] {resp.status_code} {resp.text}", file=sys.stderr)
        resp.raise_for_status()
    return resp


def upload_reel(path, caption):
    base = f"https://graph.facebook.com/{GRAPH_VERSION}/{PAGE_ID}/video_reels"

    # 1) start
    r = check(
        requests.post(
            base,
            data={"upload_phase": "start", "access_token": PAGE_TOKEN},
            timeout=60,
        ),
        "start",
    ).json()
    video_id, upload_url = r["video_id"], r["upload_url"]

    # 2) upload the file
    size = path.stat().st_size
    with open(path, "rb") as f:
        check(
            requests.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {PAGE_TOKEN}",
                    "offset": "0",
                    "file_size": str(size),
                },
                data=f,
                timeout=900,
            ),
            "upload",
        )

    # 3) finish (publish or schedule)
    data = {
        "upload_phase": "finish",
        "video_id": video_id,
        "description": caption,
        "access_token": PAGE_TOKEN,
    }
    if PUBLISH_MODE == "schedule":
        data["video_state"] = "SCHEDULED"
        data["scheduled_publish_time"] = str(int(time.time()) + LEAD_MINUTES * 60)
    else:
        data["video_state"] = "PUBLISHED"

    res = check(requests.post(base, data=data, timeout=120), "finish").json()
    print("Facebook response:", res)
    return video_id


# ---------- main ----------
def main():
    posted = load_posted()
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )

    attempts = 0
    for post in candidates(reddit, posted):
        if attempts >= MAX_ATTEMPTS:
            break
        attempts += 1
        print(f"Trying {post.id}: {post.title[:70]!r} (r/{post.subreddit})")
        try:
            raw = download(post)
            out = WORK / f"{post.id}_reel.mp4"
            to_vertical(raw, out)
            author = f"u/{post.author}" if post.author else "the original poster"
            caption = (
                f"{post.title}\n\n"
                f"Credit: {author} on r/{post.subreddit}\n"
                f"#animals #cute #funnyanimals"
            )
            upload_reel(out, caption)
        except Exception as exc:  # try the next candidate
            print(f"  failed: {exc}", file=sys.stderr)
            continue
        posted.append(post.id)
        save_posted(posted)
        print("Done.")
        return 0

    print("No post succeeded this run.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
