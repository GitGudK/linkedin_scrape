"""LinkedIn Job Scraper - Automated job search and email notifications"""

import json
import smtplib
import hashlib
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.sync_api import sync_playwright, Page

# Directories
DATA_DIR = Path(__file__).parent
SEEN_JOBS_FILE = DATA_DIR / "seen_jobs.json"
CONFIG_FILE = DATA_DIR / "config"

# Search configuration
SEARCH_QUERIES = [
    "data science director",
    "data science VP",
    "VP data science",
    "director of data science",
    "head of data science",
    "AI director",
    "ML director",
    "director machine learning",
]


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


def generate_job_id(job: dict) -> str:
    """Generate a unique ID for a job based on title, company, and URL."""
    unique_str = f"{job.get('title', '')}-{job.get('company', '')}-{job.get('url', '')}"
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


def search_jobs(page: Page, query: str) -> list[dict]:
    """Search for jobs with the given query."""
    jobs = []

    # Build search URL (last 24 hours filter)
    search_url = f"https://www.linkedin.com/jobs/search/?keywords={query.replace(' ', '%20')}&f_TPR=r86400"

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

    # Create JavaScript to open all jobs in new tabs
    job_urls = [job.get('url', '') for job in new_jobs if job.get('url')]
    js_urls = str(job_urls).replace("'", "\\'")
    open_all_script = f"javascript:(function(){{var urls={js_urls};urls.forEach(function(u){{window.open(u,'_blank')}})}})()"

    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px;">
    <h2>New Job Postings Found</h2>
    <p>The following jobs were posted in the last 24 hours:</p>
    <p style="margin: 15px 0;">
        <a href="{open_all_script}" style="background: #0066cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">
            Open All {len(new_jobs)} Jobs in New Tabs
        </a>
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

        # Search for each query
        for query in SEARCH_QUERIES:
            print(f"Searching: {query}")
            jobs = search_jobs(page, query)
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

    # Filter to new jobs only
    new_jobs = [job for job_id, job in unique_jobs.items() if job_id not in seen_job_ids]
    print(f"New jobs (not seen before): {len(new_jobs)}")

    if new_jobs:
        # Send email notification
        send_email(config, new_jobs)

        # Update seen jobs with full details
        for job_id, job in unique_jobs.items():
            seen_jobs_dict[job_id] = {
                "title": job.get("title"),
                "company": job.get("company"),
                "url": job.get("url"),
                "scraped_at": job.get("scraped_at"),
            }
        save_seen_jobs(seen_jobs_dict)

        # Print new jobs
        print("\n📋 New Jobs Found:")
        for job in new_jobs:
            print(f"  • {job['title']} at {job['company']}")
            print(f"    {job['url']}\n")
    else:
        print("\nNo new jobs found.")

    print(f"\n{'='*50}")
    print("Scraper finished")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    run_scraper()
