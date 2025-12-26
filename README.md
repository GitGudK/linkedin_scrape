# LinkedIn Job Scraper

Automated job scraper that searches LinkedIn for Data Science leadership roles and emails you when new jobs are found. Designed to run on a cron schedule.

## Setup

### 1. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure credentials

Edit the `config` file with 4 lines:
```
your_linkedin_email@gmail.com
your_linkedin_password
your_gmail_address@gmail.com
your_gmail_app_password
```

### 3. Get a Gmail App Password

1. Go to https://myaccount.google.com/apppasswords
2. Select "Mail" and your device
3. Copy the 16-character password (no spaces)
4. Paste it as line 4 in your `config` file

### 4. Test the scraper

```bash
python scraper.py
```

### 5. Set up cron job (every 3 hours)

```bash
crontab -e
```

Add this line:
```
0 */3 * * * cd /Users/kris/Code/linkedin_scrape && /Users/kris/Code/linkedin_scrape/venv/bin/python scraper.py >> /Users/kris/Code/linkedin_scrape/scraper.log 2>&1
```

## How it works

1. Searches LinkedIn for these queries (posted in last 24 hours):
   - data science director
   - data science VP
   - VP data science
   - director of data science
   - head of data science
   - AI director
   - ML director
   - director machine learning

2. Deduplicates results and tracks seen jobs in `seen_jobs.json`

3. Emails you only about **new** jobs not seen before

4. Creates `open_all_jobs.html` - open this file to launch all jobs in browser tabs:
   ```bash
   open open_all_jobs.html
   ```

## Files

- `scraper.py` - Main scraper script
- `config` - Your credentials (gitignored)
- `seen_jobs.json` - Tracks previously seen jobs with title, company, URL
- `open_all_jobs.html` - Open this to launch all new jobs in browser tabs
- `scraper.log` - Cron output log

## Customizing search queries

Edit the `SEARCH_QUERIES` list in `scraper.py`:

```python
SEARCH_QUERIES = [
    "data science director",
    "your custom search",
    ...
]
```
