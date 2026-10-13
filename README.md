# FacebookAutoPoster

Grabs a video from animal subreddits, downloads it with yt-dlp, reformats it to
9:16 with ffmpeg, and uploads it to a Facebook Page as a Reel. Runs on GitHub
Actions twice a day.

## Setup

1. **Reddit app**: create a "script" app at https://www.reddit.com/prefs/apps
   and note the client id and secret.
2. **Facebook**: you need a Page access token (long-lived) with permission to
   publish to your Page, plus the Page ID.
3. **GitHub secrets** (Settings > Secrets and variables > Actions):
   - `FB_PAGE_ID`
   - `FB_PAGE_TOKEN`
   - `REDDIT_CLIENT_ID`
   - `REDDIT_CLIENT_SECRET`
4. Edit `REDDIT_USER_AGENT` in `.github/workflows/post.yml` with your Reddit username.
5. Edit the two `cron` times (UTC) in the workflow.
6. Run it once manually from the Actions tab (workflow_dispatch) to test.

## Config (env vars)

| Var | Default | What it does |
| --- | --- | --- |
| `SUBREDDITS` | aww+AnimalsBeingBros+... | Subreddits joined with `+` |
| `PUBLISH_MODE` | `schedule` | `schedule` or `now` |
| `LEAD_MINUTES` | `30` | How far ahead Facebook schedules the post |
| `MIN_SECONDS` / `MAX_SECONDS` | 3 / 90 | Reel length limits |
| `GRAPH_VERSION` | `v21.0` | Graph API version, bump if retired |

## Notes

- `posted.json` stores IDs already posted. The workflow commits it back so
  clips never repeat.
- If Reddit blocks GitHub's IPs (403s in the logs), that is the likely cause.
- Check Meta's current Reels publishing docs if scheduling errors out, and
  fall back to `PUBLISH_MODE=now`.
- Reposting other people's videos can trigger copyright claims on your Page.
