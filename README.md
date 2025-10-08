# NSA Codebreaker Challenge Scraper

Scripts to scrape and analyze NSA Codebreaker Challenge leaderboards and personal submissions.

## Installation

```bash
cd cbc_scraper

# Using uv (recommended)
uv venv && source .venv/bin/activate && uv pip install -e .

# Using pip
python -m .venv venv && source .venv/bin/activate && pip install -e .
```

## Usage

### Leaderboard Scraper

```bash
python scrape_leaderboards.py                    # Scrape current year
python scrape_leaderboards.py --all-years        # Scrape 2018-2025
python scrape_leaderboards.py --year 2023        # Scrape specific year
python scrape_leaderboards.py --display          # Display cached data
```

**Output:**
- `data/leaderboard_stats_2025.json` - Current year
- `data/archived_leaderboards.json` - Historical years (2018-2024)

**Features:**
- Color-coded solve rates (🟢 ≥25% | 🟡 2-25% | 🔴 <2%)
- Fast parallel scraping (~2-3s current year, ~15-20s all years)
- No authentication required

### Submissions Scraper

```bash
python scrape_submissions.py            # Scrape your submissions
python scrape_submissions.py --display  # Display cached data
```

**Authentication** (prompts for input if not set):
```bash
export CBC_EMAIL="your.email@example.com"
export CBC_PASSWORD="your_password"
```

**Output:**
- `data/submission_stats.json` - Your submission history with time spent per task

**Features:**
- Calculates time spent on each task
- Shows attempts per task
- Tracks progress on current task

**Time Calculation:**
- Latest task (any attempts): `now - first_submission` (tracks ongoing work)
- Earlier tasks (multiple attempts): `last_submission - first_submission`
- Earlier tasks (single attempt): `submission_time - previous_task_last_submission`

