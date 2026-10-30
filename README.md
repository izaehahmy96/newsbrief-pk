# Newsbrief PK

Pakistan's news in 60 words, English and Urdu. A web app you can install on a phone.

## What is in this folder

| File | What it does |
|---|---|
| `pipeline.py` | Reads news feeds, shortens each story to ~60 words, writes `news.json` |
| `news.json` | The news the app shows (starts with placeholders) |
| `index.html`, `style.css`, `app.js` | The swipe-card reader |
| `manifest.json`, `sw.js`, `icon-*.png` | Make it installable and work offline |
| `.github/workflows/update-news.yml` | Runs the collector every 30 minutes, free |

## Try it on your computer

1. Install Python 3 (python.org) if you don't have it.
2. In this folder run: `python3 pipeline.py` (on Windows: `python pipeline.py`).
   Watch which feeds say `ok` and which say `SKIP`. For any SKIP, open that
   address in your browser; if it is dead, find the outlet's current RSS link
   and fix it in the `FEEDS` list at the top of `pipeline.py`.
3. Start a local server: `python3 -m http.server 8000`
4. Open http://localhost:8000 in your browser.

## Put it online (free)

1. Create a free GitHub account and a new repository; upload all these files
   (including the hidden `.github` folder).
2. Go to Cloudflare Pages or Netlify, connect that repository, and deploy.
   No build command is needed; the folder itself is the site.
3. In GitHub, open the Actions tab and run "Update news" once. After that it
   refreshes every 30 minutes and your site updates itself.
4. Open the site on your phone and choose "Add to Home Screen".

## Better summaries (optional)

Get an API key from console.anthropic.com. In your GitHub repository go to
Settings > Secrets and variables > Actions and add a secret named
`ANTHROPIC_API_KEY`. Without it the app still works, but summaries are the
first sentences of each story rather than a proper rewrite. It costs a small
amount per story.

## Please keep

- The source name and "Read full story" link on every card.
- Your own short summaries, not copied article text. Check each outlet's terms.
