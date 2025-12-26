"""LinkedIn Job Scraper - Automated job search and email notifications"""

import json
import smtplib
import hashlib
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.sync_api import sync_playwright, Page

# Directories
DATA_DIR = Path(__file__).parent
SEEN_JOBS_FILE = DATA_DIR / "seen_jobs.json"
CONFIG_FILE = DATA_DIR / "config"
FILTERS_FILE = DATA_DIR / "filters.json"

# Default filters (used if filters.json doesn't exist)
DEFAULT_FILTERS = {
    "location_keywords": ["remote", "work from home", "wfh", "anywhere", "atlanta", "atl", ", ga", "georgia"],
    "exclude_keywords": ["contractor", "contract", "freelance", "consultant", "hourly", "/hr", "per hour", "$/hour", "c2c", "corp to corp", "1099", "w2 contract", "temp", "temporary"],
    "search_queries": ["data science director", "data science VP", "VP data science", "director of data science", "head of data science", "AI director", "ML director", "director machine learning"],
    "time_filter": "Past week"
}


def load_filters() -> dict:
    """Load filters from filters.json."""
    if FILTERS_FILE.exists():
        try:
            return json.loads(FILTERS_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return DEFAULT_FILTERS


def load_config() -> dict:
    """Load configuration from config file."""
    config = {}
    if CONFIG_FILE.exists():
        lines = CONFIG_FILE.read_text().strip().split("\n")
        if len(lines) >= 4:
            config["linkedin_email"] = lines[0].strip()
            config["linkedin_password"] = lines[1].strip()
            config["gmail_address"] = lines[2].strip()
            config["gmail_app_password"] = lines[3].strip()
    return config


def load_seen_jobs() -> tuple[set, dict]:
    """Load set of previously seen job IDs and their details."""
    if SEEN_JOBS_FILE.exists():
        data = json.loads(SEEN_JOBS_FILE.read_text())
        # Support both old format (just IDs) and new format (with details)
        if "jobs" in data:
            return set(data["jobs"].keys()), data["jobs"]
        else:
            # Migrate from old format
            return set(data.get("job_ids", [])), {}
    return set(), {}


def save_seen_jobs(jobs_dict: dict):
    """Save seen jobs with their details to file."""
    SEEN_JOBS_FILE.write_text(json.dumps({
        "jobs": jobs_dict,
        "last_updated": datetime.now().isoformat()
    }, indent=2))


def extract_job_view_id(url: str) -> str:
    """Extract the job view ID from a LinkedIn URL, stripping tracking params."""
    # LinkedIn URLs look like: https://www.linkedin.com/jobs/view/4329321531/?eBP=...
    # We just want the job ID (4329321531)
    if "/jobs/view/" in url:
        parts = url.split("/jobs/view/")[1]
        job_view_id = parts.split("/")[0].split("?")[0]
        return job_view_id
    return url


def generate_job_id(job: dict) -> str:
    """Generate a unique ID for a job based on title, company, and job view ID."""
    url = job.get('url', '')
    job_view_id = extract_job_view_id(url)
    unique_str = f"{job.get('title', '')}-{job.get('company', '')}-{job_view_id}"
    return hashlib.md5(unique_str.encode()).hexdigest()[:12]


def auto_login(page: Page, email: str, password: str) -> bool:
    """Automatically log in to LinkedIn."""
    try:
        page.goto("https://www.linkedin.com/login", timeout=60000)
        page.wait_for_timeout(3000)

        # Check if already logged in
        if "/feed" in page.url or "/jobs" in page.url:
            return True

        # Wait for and fill login form
        page.wait_for_selector('input[name="session_key"]', timeout=10000)
        page.fill('input[name="session_key"]', email)
        page.fill('input[name="session_password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_timeout(5000)

        # Check for verification challenge
        if "checkpoint" in page.url or "challenge" in page.url:
            print("ERROR: LinkedIn requires verification. Please log in manually first.")
            return False

        return "/feed" in page.url or "/jobs" in page.url or "linkedin.com" in page.url
    except Exception as e:
        print(f"Login error: {e}")
        return False


def search_jobs(page: Page, query: str, time_filter: str = "Past week") -> list[dict]:
    """Search for jobs with the given query."""
    jobs = []

    # Time filter mapping to LinkedIn's f_TPR parameter
    # r86400 = past 24 hours, r604800 = past week, r2592000 = past month
    time_param = ""
    if time_filter == "Past 24 hours":
        time_param = "&f_TPR=r86400"
    elif time_filter == "Past week":
        time_param = "&f_TPR=r604800"
    elif time_filter == "Past month":
        time_param = "&f_TPR=r2592000"
    # "Any time" = no param

    # Build search URL
    search_url = f"https://www.linkedin.com/jobs/search/?keywords={query.replace(' ', '%20')}{time_param}"

    try:
        page.goto(search_url, timeout=60000)
        page.wait_for_timeout(5000)  # Let page load

        # Scroll to load jobs
        for _ in range(2):
            page.evaluate("window.scrollBy(0, 800)")
            page.wait_for_timeout(1000)

        # Find job cards
        job_card_selectors = [
            ".job-card-container",
            ".jobs-search-results__list-item",
            "[data-job-id]",
        ]

        job_cards = []
        for selector in job_card_selectors:
            job_cards = page.query_selector_all(selector)
            if job_cards:
                break

        for card in job_cards[:10]:  # Limit to 10 per query
            try:
                card.click()
                page.wait_for_timeout(1500)

                job = extract_job(page, card)
                if job and job.get("title"):
                    jobs.append(job)
            except:
                continue

    except Exception as e:
        print(f"Search error for '{query}': {e}")

    return jobs


def extract_job(page: Page, card) -> dict | None:
    """Extract job details from the page."""
    try:
        # Title selectors
        title = ""
        for sel in [".job-card-list__title", ".artdeco-entity-lockup__title", "strong"]:
            el = card.query_selector(sel)
            if el:
                title = el.inner_text().strip()
                break

        # Company selectors
        company = ""
        for sel in [".job-card-container__primary-description", ".artdeco-entity-lockup__subtitle"]:
            el = card.query_selector(sel)
            if el:
                company = el.inner_text().strip()
                break

        # Location
        location = ""
        for sel in [".job-card-container__metadata-item", ".artdeco-entity-lockup__caption"]:
            el = card.query_selector(sel)
            if el:
                location = el.inner_text().strip()
                break

        # Description from details panel
        description = ""
        for sel in [".jobs-description-content__text", ".jobs-description__content", "#job-details"]:
            el = page.query_selector(sel)
            if el:
                description = el.inner_text().strip()[:2000]  # Limit length
                break

        # URL
        job_url = ""
        link_el = card.query_selector("a[href*='/jobs/view/']")
        if link_el:
            job_url = link_el.get_attribute("href")
        if not job_url:
            job_id = card.get_attribute("data-job-id")
            if job_id:
                job_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
        if job_url and not job_url.startswith("http"):
            job_url = f"https://www.linkedin.com{job_url}"
        # Clean URL - strip tracking parameters
        if job_url and "/jobs/view/" in job_url:
            job_view_id = extract_job_view_id(job_url)
            job_url = f"https://www.linkedin.com/jobs/view/{job_view_id}/"

        if not title:
            return None

        return {
            "title": title,
            "company": company,
            "location": location,
            "description": description,
            "url": job_url,
            "scraped_at": datetime.now().isoformat(),
        }
    except Exception as e:
        return None


def is_location_match(location: str, description: str, location_keywords: list) -> bool:
    """Check if job matches any location keywords."""
    location_lower = location.lower()
    description_lower = description.lower()

    for keyword in location_keywords:
        keyword_lower = keyword.lower()
        if keyword_lower in location_lower or keyword_lower in description_lower:
            return True

    return False


def is_full_time_employee(title: str, description: str, exclude_keywords: list) -> bool:
    """Check if job is a full-time employee position (not hourly/contractor)."""
    title_lower = title.lower()
    description_lower = description.lower()

    for keyword in exclude_keywords:
        keyword_lower = keyword.lower()
        if keyword_lower in title_lower or keyword_lower in description_lower:
            return False

    return True


def send_email(config: dict, new_jobs: list[dict]):
    """Send email notification about new jobs."""
    if not new_jobs:
        return

    gmail = config.get("gmail_address")
    app_password = config.get("gmail_app_password")

    if not gmail or not app_password:
        print("Email not configured. Skipping notification.")
        return

    # Build email content
    subject = f"🎯 {len(new_jobs)} New Data Science Leadership Jobs Found"

    # Create local HTML file that opens all jobs in tabs
    job_urls = [job.get('url', '') for job in new_jobs if job.get('url')]
    job_items = []
    for job in new_jobs:
        url = job.get('url', '')
        title = job.get('title', 'Unknown')
        company = job.get('company', 'Unknown')
        if url:
            job_items.append(f'<li style="margin: 10px 0;"><a href="{url}" target="_blank" style="font-size: 16px;">{title}</a> - {company}</li>')

    open_all_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Open All Jobs</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; }}
        .open-all {{ background: #0066cc; color: white; padding: 15px 30px; font-size: 18px; border: none; border-radius: 5px; cursor: pointer; margin: 20px 0; }}
        .open-all:hover {{ background: #0052a3; }}
        ul {{ list-style: none; padding: 0; }}
    </style>
</head>
<body>
<h1>{len(job_urls)} New Jobs Found</h1>
<button class="open-all" onclick="openAll()">Click Here to Open All {len(job_urls)} Jobs in New Tabs</button>
<p style="color: #666;">If pop-ups are blocked, allow pop-ups for this page and click again, or click each link below:</p>
<ul>
{"".join(job_items)}
</ul>
<script>
var urls = {json.dumps(job_urls)};
function openAll() {{
    urls.forEach(function(u) {{ window.open(u, '_blank'); }});
}}
</script>
</body>
</html>"""

    open_all_file = DATA_DIR / "open_all_jobs.html"
    open_all_file.write_text(open_all_html)

    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px;">
    <h2>New Job Postings Found</h2>
    <p>The following jobs were posted in the last 24 hours:</p>
    <p style="margin: 15px 0; padding: 10px; background: #f0f0f0; border-radius: 5px;">
        <strong>Open all jobs at once:</strong> Run <code>open ~/Code/linkedin_scrape/open_all_jobs.html</code> in Terminal
    </p>
    """

    for job in new_jobs:
        html_content += f"""
        <div style="border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 8px;">
            <h3 style="margin: 0 0 5px 0;">
                <a href="{job.get('url', '#')}" style="color: #0066cc;">{job.get('title', 'Unknown')}</a>
            </h3>
            <p style="margin: 5px 0; color: #666;">
                <strong>{job.get('company', 'Unknown')}</strong> • {job.get('location', 'Unknown')}
            </p>
            <p style="margin: 10px 0; font-size: 14px; color: #444;">
                {job.get('description', '')[:300]}...
            </p>
        </div>
        """

    html_content += """
    <p style="color: #888; font-size: 12px; margin-top: 20px;">
        Sent by LinkedIn Job Scraper
    </p>
    </body>
    </html>
    """

    # Plain text version
    text_content = f"Found {len(new_jobs)} new jobs:\n\n"
    for job in new_jobs:
        text_content += f"• {job.get('title')} at {job.get('company')}\n  {job.get('url')}\n\n"

    # Create message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail
    msg["To"] = gmail
    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    # Send email
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail, app_password)
            server.send_message(msg)
        print(f"✓ Email sent with {len(new_jobs)} jobs")
    except Exception as e:
        print(f"✗ Failed to send email: {e}")


def run_scraper():
    """Main function to run the job scraper."""
    print(f"\n{'='*50}")
    print(f"LinkedIn Job Scraper - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    # Load config
    config = load_config()
    if not config.get("linkedin_email") or not config.get("linkedin_password"):
        print("ERROR: LinkedIn credentials not found in config file")
        return

    # Load previously seen jobs
    seen_job_ids, seen_jobs_dict = load_seen_jobs()
    print(f"Loaded {len(seen_job_ids)} previously seen job IDs")

    # Load filters
    filters = load_filters()

    all_jobs = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,  # Run headless for cron
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        # Login
        print("Logging in to LinkedIn...")
        if not auto_login(page, config["linkedin_email"], config["linkedin_password"]):
            print("Login failed!")
            browser.close()
            return
        print("✓ Logged in successfully\n")

        # Get search queries and time filter from filters
        search_queries = filters.get("search_queries", DEFAULT_FILTERS["search_queries"])
        time_filter = filters.get("time_filter", "Past week")
        print(f"Time filter: {time_filter}\n")

        for query in search_queries:
            print(f"Searching: {query}")
            jobs = search_jobs(page, query, time_filter)
            print(f"  Found {len(jobs)} jobs")
            all_jobs.extend(jobs)

        browser.close()

    # Deduplicate jobs
    unique_jobs = {}
    for job in all_jobs:
        job_id = generate_job_id(job)
        if job_id not in unique_jobs:
            job["id"] = job_id
            unique_jobs[job_id] = job

    print(f"\nTotal unique jobs found: {len(unique_jobs)}")

    # Get filter keywords
    location_keywords = filters.get("location_keywords", DEFAULT_FILTERS["location_keywords"])
    exclude_keywords = filters.get("exclude_keywords", DEFAULT_FILTERS["exclude_keywords"])

    # Filter by location keywords
    location_filtered = {
        job_id: job for job_id, job in unique_jobs.items()
        if is_location_match(job.get("location", ""), job.get("description", ""), location_keywords)
    }
    print(f"Jobs matching location filter: {len(location_filtered)}")

    # Filter out excluded keywords (contractor/hourly)
    fte_filtered = {
        job_id: job for job_id, job in location_filtered.items()
        if is_full_time_employee(job.get("title", ""), job.get("description", ""), exclude_keywords)
    }
    print(f"Jobs after exclusion filter: {len(fte_filtered)}")

    # Filter to new jobs only
    new_jobs = [job for job_id, job in fte_filtered.items() if job_id not in seen_job_ids]
    print(f"New jobs (not seen before): {len(new_jobs)}")

    if new_jobs:
        # Send email notification
        send_email(config, new_jobs)

        # Update seen jobs with full details (only filtered jobs)
        for job_id, job in fte_filtered.items():
            seen_jobs_dict[job_id] = {
                "title": job.get("title"),
                "company": job.get("company"),
                "location": job.get("location"),
                "url": job.get("url"),
                "scraped_at": job.get("scraped_at"),
            }
        save_seen_jobs(seen_jobs_dict)

        # Print new jobs
        print("\n📋 New Jobs Found:")
        for job in new_jobs:
            print(f"  • {job['title']} at {job['company']}")
            print(f"    {job['url']}\n")

        # Open all jobs in browser if running interactively (not cron)
        if sys.stdout.isatty():
            open_all_file = DATA_DIR / "open_all_jobs.html"
            if open_all_file.exists():
                print("Opening all jobs in browser...")
                subprocess.run(["open", str(open_all_file)])
    else:
        print("\nNo new jobs found.")

    print(f"\n{'='*50}")
    print("Scraper finished")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    run_scraper()
