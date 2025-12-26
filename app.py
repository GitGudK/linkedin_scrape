#!/usr/bin/env python3
"""Streamlit frontend for LinkedIn Job Scraper."""

import json
import subprocess
from datetime import datetime
from pathlib import Path

import streamlit as st

DATA_DIR = Path(__file__).parent
SEEN_JOBS_FILE = DATA_DIR / "seen_jobs.json"
FILTERS_FILE = DATA_DIR / "filters.json"
PYTHON_PATH = Path.home() / ".pyenv/versions/3.11.5/envs/li/bin/python"
SCRAPER_PATH = DATA_DIR / "scraper.py"

DEFAULT_FILTERS = {
    "location_keywords": ["remote", "work from home", "wfh", "anywhere", "atlanta", "atl", ", ga", "georgia"],
    "exclude_keywords": ["contractor", "contract", "freelance", "consultant", "hourly", "/hr", "per hour", "$/hour", "c2c", "corp to corp", "1099", "w2 contract", "temp", "temporary"],
    "search_queries": ["data science director", "data science VP", "VP data science", "director of data science", "head of data science", "AI director", "ML director", "director machine learning"],
    "time_filter": "Past week"
}


def load_jobs() -> dict:
    """Load jobs from seen_jobs.json."""
    if not SEEN_JOBS_FILE.exists():
        return {}
    try:
        data = json.loads(SEEN_JOBS_FILE.read_text())
        return data.get("jobs", {})
    except (json.JSONDecodeError, KeyError):
        return {}


def save_jobs(jobs: dict):
    """Save jobs to seen_jobs.json."""
    SEEN_JOBS_FILE.write_text(json.dumps({
        "jobs": jobs,
        "last_updated": datetime.now().isoformat()
    }, indent=2))


def load_filters() -> dict:
    """Load filters from filters.json."""
    if not FILTERS_FILE.exists():
        save_filters(DEFAULT_FILTERS)
        return DEFAULT_FILTERS
    try:
        return json.loads(FILTERS_FILE.read_text())
    except json.JSONDecodeError:
        return DEFAULT_FILTERS


def save_filters(filters: dict):
    """Save filters to filters.json."""
    FILTERS_FILE.write_text(json.dumps(filters, indent=2))


def run_scraper():
    """Run the scraper script and return output."""
    result = subprocess.run(
        [str(PYTHON_PATH), str(SCRAPER_PATH)],
        capture_output=True,
        text=True,
        timeout=300
    )
    return result.stdout + result.stderr


# Page config
st.set_page_config(
    page_title="LinkedIn Job Scraper",
    page_icon="💼",
    layout="wide"
)

st.title("💼 LinkedIn Job Scraper")

# Load current filters
filters = load_filters()

# Sidebar
with st.sidebar:
    st.header("🔄 Run Scraper")

    if st.button("🚀 Run Scraper Now", type="primary", use_container_width=True):
        with st.spinner("Running scraper..."):
            try:
                output = run_scraper()
                st.success("Scraper completed!")
                st.session_state["scraper_output"] = output
            except subprocess.TimeoutExpired:
                st.error("Scraper timed out after 5 minutes.")
            except Exception as e:
                st.error(f"Error: {e}")

    # Show last run info
    if SEEN_JOBS_FILE.exists():
        try:
            data = json.loads(SEEN_JOBS_FILE.read_text())
            last_updated = data.get("last_updated", "Unknown")
            if last_updated != "Unknown":
                try:
                    dt = datetime.fromisoformat(last_updated)
                    last_updated = dt.strftime("%b %d %I:%M %p")
                except:
                    pass
            st.caption(f"Last run: {last_updated}")
        except:
            pass

    st.divider()

    # Editable Filters
    st.header("⚙️ Filters")

    with st.expander("📍 Location Keywords", expanded=False):
        location_text = st.text_area(
            "Include jobs matching these (one per line):",
            value="\n".join(filters.get("location_keywords", [])),
            height=150,
            key="location_keywords"
        )
        new_location = [k.strip() for k in location_text.split("\n") if k.strip()]

    with st.expander("🚫 Exclude Keywords", expanded=False):
        exclude_text = st.text_area(
            "Exclude jobs containing these (one per line):",
            value="\n".join(filters.get("exclude_keywords", [])),
            height=150,
            key="exclude_keywords"
        )
        new_exclude = [k.strip() for k in exclude_text.split("\n") if k.strip()]

    with st.expander("🔍 Search Queries", expanded=False):
        queries_text = st.text_area(
            "LinkedIn search queries (one per line):",
            value="\n".join(filters.get("search_queries", [])),
            height=150,
            key="search_queries"
        )
        new_queries = [k.strip() for k in queries_text.split("\n") if k.strip()]

    # Time filter for LinkedIn search
    time_options = ["Any time", "Past month", "Past week", "Past 24 hours"]
    current_time = filters.get("time_filter", "Past week")
    if current_time not in time_options:
        current_time = "Past week"
    new_time_filter = st.selectbox(
        "🕐 Posted within",
        time_options,
        index=time_options.index(current_time)
    )

    # Check if filters changed
    new_filters = {
        "location_keywords": new_location,
        "exclude_keywords": new_exclude,
        "search_queries": new_queries,
        "time_filter": new_time_filter
    }

    if new_filters != filters:
        if st.button("💾 Save Filters", use_container_width=True):
            save_filters(new_filters)
            st.success("Filters saved!")
            st.rerun()

    st.divider()
    st.header("Quick Actions")

    sidebar_jobs = load_jobs()
    not_applied = [j for j in sidebar_jobs.values() if not j.get("applied", False) and not j.get("ignored", False)]

    if not_applied:
        st.write(f"**{len(not_applied)}** jobs to review")

        if st.button("🔗 Open All Unapplied Jobs", use_container_width=True):
            urls = [j.get("url") for j in not_applied if j.get("url")]
            html_content = f"""<!DOCTYPE html>
<html>
<head><title>Open Jobs</title></head>
<body>
<h2>Click the button to open {len(urls)} jobs in new tabs</h2>
<button onclick="openAll()" style="padding: 20px 40px; font-size: 18px; cursor: pointer;">
    Open All {len(urls)} Jobs
</button>
<script>
function openAll() {{
    const urls = {json.dumps(urls)};
    urls.forEach(url => window.open(url, '_blank'));
}}
</script>
</body>
</html>"""
            open_file = DATA_DIR / "open_all_jobs.html"
            open_file.write_text(html_content)
            st.success("Created!")
            st.code(f"open {open_file}", language="bash")
    else:
        st.success("All jobs reviewed!")

    st.divider()

    if st.button("🗑️ Clear All Applied", use_container_width=True):
        sidebar_jobs = load_jobs()
        for job_id in sidebar_jobs:
            sidebar_jobs[job_id]["applied"] = False
        save_jobs(sidebar_jobs)
        st.rerun()

# Main content: Jobs list with checkboxes
st.header("Scraped Jobs")

jobs = load_jobs()

if not jobs:
    st.info("No jobs found. Run the scraper to find jobs.")
else:
    # Filter options
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        show_filter = st.selectbox(
            "Show",
            ["Not Applied", "Applied", "Ignored", "All"],
            index=0
        )
    with col2:
        st.metric("Total", len(jobs))
    with col3:
        applied_count = sum(1 for j in jobs.values() if j.get("applied", False))
        st.metric("Applied", applied_count)
    with col4:
        ignored_count = sum(1 for j in jobs.values() if j.get("ignored", False))
        st.metric("Ignored", ignored_count)

    st.divider()

    # Track changes
    changes_made = False

    # Sort jobs by scraped_at (newest first)
    sorted_jobs = sorted(
        jobs.items(),
        key=lambda x: x[1].get("scraped_at", ""),
        reverse=True
    )

    # Filter jobs
    filtered_jobs = []
    for job_id, job in sorted_jobs:
        applied = job.get("applied", False)
        ignored = job.get("ignored", False)

        # Status filter
        if show_filter == "Not Applied" and (applied or ignored):
            continue
        elif show_filter == "Applied" and not applied:
            continue
        elif show_filter == "Ignored" and not ignored:
            continue

        filtered_jobs.append((job_id, job))

    if not filtered_jobs:
        st.info(f"No jobs matching filter: {show_filter}")

    # Column headers
    header_col1, header_col2 = st.columns([0.12, 0.88])
    with header_col1:
        st.caption("Applied | Skip")

    # Display jobs
    for job_id, job in filtered_jobs:
        title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")
        location = job.get("location", "Unknown")
        url = job.get("url", "")
        scraped_at = job.get("scraped_at", "")
        applied = job.get("applied", False)
        ignored = job.get("ignored", False)

        # Format date
        if scraped_at:
            try:
                dt = datetime.fromisoformat(scraped_at)
                date_str = dt.strftime("%b %d, %Y %I:%M %p")
            except:
                date_str = scraped_at
        else:
            date_str = "Unknown"

        with st.container():
            col1, col2 = st.columns([0.12, 0.88])

            with col1:
                subcol1, subcol2 = st.columns(2)
                with subcol1:
                    new_applied = st.checkbox(
                        "✓",
                        value=applied,
                        key=f"applied_{job_id}",
                        label_visibility="collapsed"
                    )
                    if new_applied != applied:
                        jobs[job_id]["applied"] = new_applied
                        if new_applied:
                            jobs[job_id]["ignored"] = False
                        changes_made = True
                with subcol2:
                    new_ignored = st.checkbox(
                        "✗",
                        value=ignored,
                        key=f"ignored_{job_id}",
                        label_visibility="collapsed"
                    )
                    if new_ignored != ignored:
                        jobs[job_id]["ignored"] = new_ignored
                        if new_ignored:
                            jobs[job_id]["applied"] = False
                        changes_made = True

            with col2:
                status = ""
                if applied:
                    status = " ✅"
                elif ignored:
                    status = " ❌"
                st.markdown(f"**[{title}]({url})** at **{company}**{status}")
                st.caption(f"📍 {location} | 🕐 {date_str}")

            st.divider()

    # Save changes if any
    if changes_made:
        save_jobs(jobs)
        st.rerun()
