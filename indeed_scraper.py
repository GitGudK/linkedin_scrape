"""Indeed Job Scraper - Automated job search"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

# Directories
DATA_DIR = Path(__file__).parent
SEEN_JOBS_FILE = DATA_DIR / "seen_jobs.json"
FILTERS_FILE = DATA_DIR / "filters.json"

# Default filters
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


def load_seen_jobs() -> tuple[set, dict]:
    """Load set of previously seen job IDs and their details."""
    if SEEN_JOBS_FILE.exists():
        data = json.loads(SEEN_JOBS_FILE.read_text())
        if "jobs" in data:
            return set(data["jobs"].keys()), data["jobs"]
        else:
            return set(data.get("job_ids", [])), {}
    return set(), {}


def save_seen_jobs(jobs_dict: dict):
    """Save seen jobs with their details to file."""
    SEEN_JOBS_FILE.write_text(json.dumps({
        "jobs": jobs_dict,
        "last_updated": datetime.now().isoformat()
    }, indent=2))


def generate_job_id(job: dict) -> str:
    """Generate a unique ID for a job."""
    unique_str = f"indeed-{job.get('title', '')}-{job.get('company', '')}-{job.get('url', '')}"
    return hashlib.md5(unique_str.encode()).hexdigest()[:12]


def dismiss_cookie_modal(page: Page) -> bool:
    """Dismiss cookie consent modal if present."""
    try:
        cookie_selectors = [
            "#onetrust-accept-btn-handler",
            "button[id*='accept']",
            "button:has-text('Accept')",
            "button:has-text('Accept all')",
            "button:has-text('I Accept')",
            "[data-testid='cookie-accept']",
        ]
        for selector in cookie_selectors:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1000)
                    return True
            except:
                continue
        return False
    except:
        return False


def search_indeed(page: Page, query: str, location: str = "", time_filter: str = "Past week") -> list[dict]:
    """Search Indeed for jobs."""
    jobs = []

    # Time filter mapping to Indeed's fromage parameter
    # 1 = last 24 hours, 3 = last 3 days, 7 = last 7 days, 14 = last 14 days
    fromage = ""
    if time_filter == "Past 24 hours":
        fromage = "&fromage=1"
    elif time_filter == "Past week":
        fromage = "&fromage=7"
    elif time_filter == "Past month":
        fromage = "&fromage=14"

    # Build search URL
    query_encoded = query.replace(" ", "+")

    # For Indeed, "remote" is a special location filter
    if not location or location.lower() in ["remote", "work from home", "wfh", "anywhere"]:
        search_url = f"https://www.indeed.com/jobs?q={query_encoded}&l=&sc=0kf%3Aattr%28DSQF7%29%3B"  # Remote filter
    else:
        location_encoded = location.replace(" ", "+").replace(",", "%2C")
        search_url = f"https://www.indeed.com/jobs?q={query_encoded}&l={location_encoded}"

    search_url += fromage
    print(f"  URL: {search_url}")

    try:
        page.goto(search_url, timeout=60000)
        page.wait_for_timeout(2000)

        # Dismiss cookie modal
        dismiss_cookie_modal(page)

        # Scroll to load more jobs
        for _ in range(2):
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(500)

        # Find job cards - Indeed 2024 structure
        job_card_selectors = [
            ".jobsearch-ResultsList .job_seen_beacon",
            ".mosaic-provider-jobcards .job_seen_beacon",
            "[data-jk]",
            ".result",
            ".jobCard_mainContent",
        ]

        job_cards = []
        for selector in job_card_selectors:
            job_cards = page.query_selector_all(selector)
            if job_cards:
                print(f"  Found {len(job_cards)} cards with selector: {selector}")
                break

        if not job_cards:
            # Try a broader approach - get all elements with data-jk attribute
            job_cards = page.query_selector_all("[data-jk]")
            print(f"  Found {len(job_cards)} cards with data-jk")

        for card in job_cards[:10]:  # Limit per query for speed
            try:
                job = extract_indeed_job(page, card)
                if job and job.get("title"):
                    jobs.append(job)
                    print(f"    ✓ {job['title']} at {job['company']}")
            except Exception as e:
                print(f"    Error extracting job: {e}")
                continue

    except Exception as e:
        print(f"Indeed search error for '{query}': {e}")

    return jobs


def extract_indeed_job(page: Page, card) -> dict | None:
    """Extract job details from an Indeed job card."""
    try:
        # Title - try multiple approaches
        title = ""
        title_selectors = [
            "h2.jobTitle span",
            "h2.jobTitle a span",
            "h2.jobTitle a",
            ".jobTitle span",
            ".jobTitle a",
            ".jobTitle",
            "[data-testid='jobTitle']",
            "a[id^='job_']",
            "a[id^='sj_']",
        ]
        for sel in title_selectors:
            el = card.query_selector(sel)
            if el:
                title = el.get_attribute("title") or el.inner_text()
                title = title.strip()
                # Skip "new" labels
                if title and title.lower() != "new":
                    break

        # Company
        company = ""
        company_selectors = [
            "[data-testid='company-name']",
            ".companyName a",
            ".companyName",
            ".company_location .companyName",
            "span[data-testid='company-name']",
            ".css-92r8pb",  # Indeed's company class
        ]
        for sel in company_selectors:
            el = card.query_selector(sel)
            if el:
                company = el.inner_text().strip()
                if company:
                    break

        # Location
        location = ""
        location_selectors = [
            "[data-testid='text-location']",
            ".companyLocation",
            ".company_location .companyLocation",
            ".location",
            ".css-1p0sjhy",  # Indeed's location class
        ]
        for sel in location_selectors:
            el = card.query_selector(sel)
            if el:
                location = el.inner_text().strip()
                if location:
                    break

        # Salary (if available)
        salary = ""
        salary_selectors = [
            ".salary-snippet-container",
            "[data-testid='attribute_snippet_testid']",
            ".salaryText",
            ".metadata .attribute_snippet",
            ".css-1cvvo1b",  # Indeed's salary class
        ]
        for sel in salary_selectors:
            el = card.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if "$" in text or "year" in text.lower() or "hour" in text.lower():
                    salary = text
                    break

        # URL - try to get job key first
        job_url = ""
        job_key = card.get_attribute("data-jk")

        if not job_key:
            # Try to find job key in nested elements
            jk_el = card.query_selector("[data-jk]")
            if jk_el:
                job_key = jk_el.get_attribute("data-jk")

        if not job_key:
            # Try from link href
            link_el = card.query_selector("a[href*='jk=']")
            if link_el:
                href = link_el.get_attribute("href")
                if "jk=" in href:
                    job_key = href.split("jk=")[1].split("&")[0]

        if job_key:
            job_url = f"https://www.indeed.com/viewjob?jk={job_key}"
        else:
            # Fallback to any job link
            link_el = card.query_selector("a[href*='/viewjob'], a[href*='/rc/clk']")
            if link_el:
                href = link_el.get_attribute("href")
                if href:
                    if href.startswith("/"):
                        job_url = f"https://www.indeed.com{href}"
                    else:
                        job_url = href

        # Description snippet
        description = ""
        desc_selectors = [
            ".job-snippet",
            "[data-testid='job-snippet']",
            ".jobCardShelfContainer",
            ".underShelfFooter",
            "ul li",
        ]
        for sel in desc_selectors:
            el = card.query_selector(sel)
            if el:
                description = el.inner_text().strip()[:500]
                if description and len(description) > 20:
                    break

        if not title:
            return None

        return {
            "title": title,
            "company": company,
            "location": location,
            "description": description + (f" | {salary}" if salary else ""),
            "url": job_url,
            "source": "indeed",
            "scraped_at": datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"  Extract error: {e}")
        return None


def is_relevant_title(title: str, search_queries: list) -> bool:
    """Check if job title is relevant based on search queries."""
    title_lower = title.lower()

    # Hard exclusions - these roles are never relevant
    hard_exclude = ["clinical", "quality assurance", "qa ", "advisory", "consulting", "sales", "marketing", "hr ", "human resources", "finance", "accounting", "legal", "compliance", "supply chain", "operations manager", "customer"]
    if any(term in title_lower for term in hard_exclude):
        return False

    # Must-have keywords for leadership roles (director-level or above)
    leadership_terms = ["director", "vp", "vice president", "head of", "head,", "chief", "lead", "principal", "senior director", "executive"]

    # Domain terms that indicate data science / AI / ML
    domain_phrases = [
        "data science",
        "data scientist",
        "machine learning",
        "artificial intelligence",
        " ai ",
        " ai,",
        "ai/ml",
        "ml/ai",
        "analytics",
        "data & analytics",
        "data and analytics",
        " ml ",
        " ml,",
        "deep learning",
        "nlp",
        "natural language",
        "computer vision",
    ]

    # Check if title has a leadership term
    has_leadership = any(term in title_lower for term in leadership_terms)

    # Check if title has a domain phrase
    has_domain = any(phrase in title_lower for phrase in domain_phrases)

    # Must have both leadership AND domain relevance
    if has_leadership and has_domain:
        return True

    # Direct matches to common patterns
    direct_patterns = [
        "director of data science",
        "director, data science",
        "data science director",
        "vp of data science",
        "vp, data science",
        "vp data science",
        "head of data science",
        "head of machine learning",
        "head of ai",
        "head of analytics",
        "director of machine learning",
        "director of ai",
        "director of analytics",
        "ml director",
        "ai director",
        "chief data",
        "chief analytics",
        "data science lead",
        "machine learning lead",
        "ai lead",
    ]

    for pattern in direct_patterns:
        if pattern in title_lower:
            return True

    return False


def is_location_match(location: str, description: str, location_keywords: list) -> bool:
    """Check if job matches any location keywords."""
    location_lower = location.lower()
    description_lower = description.lower()
    for keyword in location_keywords:
        if keyword.lower() in location_lower or keyword.lower() in description_lower:
            return True
    return False


def is_full_time_employee(title: str, description: str, exclude_keywords: list) -> bool:
    """Check if job is a full-time employee position."""
    title_lower = title.lower()
    description_lower = description.lower()
    for keyword in exclude_keywords:
        if keyword.lower() in title_lower or keyword.lower() in description_lower:
            return False
    return True


def run_indeed_scraper():
    """Main function to run the Indeed job scraper."""
    print(f"\n{'='*50}")
    print(f"Indeed Job Scraper - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    # Load previously seen jobs
    seen_job_ids, seen_jobs_dict = load_seen_jobs()
    print(f"Loaded {len(seen_job_ids)} previously seen job IDs")

    # Load filters
    filters = load_filters()

    all_jobs = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        # Get search queries and time filter
        search_queries = filters.get("search_queries", DEFAULT_FILTERS["search_queries"])
        time_filter = filters.get("time_filter", "Past week")
        print(f"Time filter: {time_filter}\n")

        # Only search remote - Indeed already shows remote jobs well
        # Searching multiple locations makes it too slow
        for query in search_queries:
            print(f"Searching Indeed: {query} (Remote)")
            jobs = search_indeed(page, query, "", time_filter)
            print(f"  Found {len(jobs)} jobs")
            all_jobs.extend(jobs)

        browser.close()

    # Deduplicate
    unique_jobs = {}
    for job in all_jobs:
        job_id = generate_job_id(job)
        if job_id not in unique_jobs:
            job["id"] = job_id
            unique_jobs[job_id] = job

    print(f"\nTotal unique Indeed jobs found: {len(unique_jobs)}")

    # Get filter keywords
    search_queries = filters.get("search_queries", DEFAULT_FILTERS["search_queries"])
    location_keywords = filters.get("location_keywords", DEFAULT_FILTERS["location_keywords"])
    exclude_keywords = filters.get("exclude_keywords", DEFAULT_FILTERS["exclude_keywords"])

    # Filter by title relevance first
    title_filtered = {
        job_id: job for job_id, job in unique_jobs.items()
        if is_relevant_title(job.get("title", ""), search_queries)
    }
    print(f"Jobs with relevant titles: {len(title_filtered)}")

    # Filter by location
    location_filtered = {
        job_id: job for job_id, job in title_filtered.items()
        if is_location_match(job.get("location", ""), job.get("description", ""), location_keywords)
    }
    print(f"Jobs matching location filter: {len(location_filtered)}")

    # Filter out excluded keywords
    fte_filtered = {
        job_id: job for job_id, job in location_filtered.items()
        if is_full_time_employee(job.get("title", ""), job.get("description", ""), exclude_keywords)
    }
    print(f"Jobs after exclusion filter: {len(fte_filtered)}")

    # Filter to new jobs only
    new_jobs = [job for job_id, job in fte_filtered.items() if job_id not in seen_job_ids]
    print(f"New jobs (not seen before): {len(new_jobs)}")

    if new_jobs:
        # Update seen jobs
        for job_id, job in fte_filtered.items():
            seen_jobs_dict[job_id] = {
                "title": job.get("title"),
                "company": job.get("company"),
                "location": job.get("location"),
                "url": job.get("url"),
                "source": "indeed",
                "scraped_at": job.get("scraped_at"),
            }
        save_seen_jobs(seen_jobs_dict)

        print("\n📋 New Indeed Jobs Found:")
        for job in new_jobs:
            print(f"  • {job['title']} at {job['company']}")
            print(f"    {job['url']}\n")
    else:
        print("\nNo new Indeed jobs found.")

    print(f"\n{'='*50}")
    print("Indeed scraper finished")
    print(f"{'='*50}\n")

    return new_jobs


if __name__ == "__main__":
    run_indeed_scraper()
