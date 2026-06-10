# werkstudent-agent

Two-script toolkit for automating a working-student job search in Germany.

| Script | What it does |
|---|---|
| `job_search.py` | Scrapes LinkedIn, Indeed, StepStone and Glassdoor; deduplicates results; sends a daily HTML email digest via Gmail |
| `apply.py` | Claude-powered agent — reads a job posting (URL or pasted text), reads your profile, and writes a tailored German/English cover letter |

---

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install requests beautifulsoup4 python-dotenv anthropic
cp .env.example .env          # fill in credentials
cp profile.example.md profile.md   # fill in your profile
```

## Usage

**Daily digest** (or add to launchd / cron):
```bash
python job_search.py
```

**Write a cover letter:**
```bash
python apply.py
# paste a job URL or description when prompted
```

## Configuration

Edit the constants at the top of `job_search.py`:

| Variable | Default | Description |
|---|---|---|
| `CITIES` | München, Nürnberg, Erlangen… | Target cities |
| `SEEN_EXPIRY_DAYS` | 45 | Days before a seen listing reappears |
| `EXCLUDED_FIELDS` | law, finance, sales… | Domains to filter out |

## Files not tracked in git

| File | Why |
|---|---|
| `.env` | Gmail + Anthropic credentials |
| `profile.md` | Personal CV data used by `apply.py` |
| `letters/` | Generated cover letters |
| `applications.csv` | Application tracker |
| `seen_jobs.json` | Dedup state |

## Stack

- Python 3.11+
- `beautifulsoup4`, `requests` — scraping
- `anthropic` — Claude API for letter generation
- Gmail SMTP — email delivery
- macOS `launchd` — daily scheduling
