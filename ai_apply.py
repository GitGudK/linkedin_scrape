#!/usr/bin/env python3
"""AI-powered job application assistant using Playwright."""

import json
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

DATA_DIR = Path(__file__).parent
CONFIG_FILE = DATA_DIR / "config"
RESUME_DIR = DATA_DIR / "resumes"

# Resume data - parsed from Kris_Shrestha_Resume.pdf
RESUME_DATA = {
    "name": "Kris Shrestha",
    "email": "",  # Will be loaded from config
    "phone": "",  # Add if needed
    "linkedin": "linkedin.com/in/krisshrestha",
    "location": "Atlanta, GA",
    "title": "Enterprise AI & GenAI Executive",
    "summary": "Enterprise AI & GenAI Executive with 15+ years of experience leading high-impact data science and AI initiatives at Fortune 500 companies including JPMorgan Chase and Raytheon Technologies.",
    "experience_years": "15+",
    "education": {
        "degree": "Ph.D.",
        "field": "Computer Science",
        "school": "University of Florida",
    },
    "skills": [
        "Machine Learning", "Deep Learning", "NLP", "Computer Vision",
        "Python", "TensorFlow", "PyTorch", "AWS", "Azure", "GCP",
        "Data Science", "AI Strategy", "Team Leadership", "GenAI", "LLMs"
    ],
    "work_authorization": "Yes",
    "sponsorship_required": "No",
    "willing_to_relocate": "Yes",
}


def load_config() -> dict:
    """Load configuration from config file."""
    config = {}
    if CONFIG_FILE.exists():
        lines = CONFIG_FILE.read_text().strip().split("\n")
        if len(lines) >= 4:
            config["linkedin_email"] = lines[0].strip()
            config["linkedin_password"] = lines[1].strip()
    return config


def dismiss_cookie_modal(page: Page) -> bool:
    """Dismiss cookie consent modal if present. Single attempt, no loops."""
    try:
        # Common cookie consent button selectors
        cookie_selectors = [
            # LinkedIn specific
            "button[action-type='ACCEPT']",
            "[data-tracking-control-name='ga-cookie.consent.accept.v4']",
            # Generic cookie banners - be very specific
            "#onetrust-accept-btn-handler",  # OneTrust (common)
            "#accept-cookie-consent",
            ".cookie-consent-accept",
            "[data-testid='cookie-accept']",
            "button[id*='accept'][id*='cookie']",
            "button[class*='accept'][class*='cookie']",
        ]

        for selector in cookie_selectors:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    print(f"✓ Dismissed cookie modal via: {selector}")
                    page.wait_for_timeout(1000)
                    return True
            except:
                continue

        # Try finding buttons by text content - but be careful
        try:
            # Look specifically in cookie banner containers
            cookie_containers = [
                "#onetrust-banner-sdk",
                ".cookie-banner",
                ".cookie-consent",
                "[class*='cookie']",
                "[id*='cookie']",
                ".gdpr",
                "#gdpr",
            ]

            for container_sel in cookie_containers:
                try:
                    container = page.query_selector(container_sel)
                    if container and container.is_visible():
                        buttons = container.query_selector_all("button")
                        for btn in buttons:
                            if btn.is_visible():
                                text = btn.inner_text().lower().strip()
                                if text in ['accept', 'accept all', 'accept cookies', 'agree', 'ok', 'i agree', 'got it', 'allow', 'allow all']:
                                    btn.click()
                                    print(f"✓ Dismissed cookie modal (clicked: {text})")
                                    page.wait_for_timeout(1000)
                                    return True
                except:
                    continue
        except:
            pass

        return False
    except:
        return False


def auto_login(page: Page, email: str, password: str) -> bool:
    """Log in to LinkedIn."""
    try:
        page.goto("https://www.linkedin.com/login", timeout=60000)
        page.wait_for_timeout(3000)

        # Dismiss cookie modal if present
        dismiss_cookie_modal(page)

        if "/feed" in page.url or "/jobs" in page.url:
            return True

        page.wait_for_selector('input[name="session_key"]', timeout=10000)
        page.fill('input[name="session_key"]', email)
        page.fill('input[name="session_password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_timeout(5000)

        return "/feed" in page.url or "/jobs" in page.url or "linkedin.com" in page.url
    except Exception as e:
        print(f"Login error: {e}")
        return False


def fill_field(page: Page, selectors: list, value: str) -> bool:
    """Try to fill a field using multiple selectors."""
    for selector in selectors:
        try:
            elements = page.query_selector_all(selector)
            for el in elements:
                if el.is_visible():
                    el.fill(value)
                    return True
        except:
            continue
    return False


def click_button(page: Page, selectors: list) -> bool:
    """Try to click a button using multiple selectors."""
    for selector in selectors:
        try:
            elements = page.query_selector_all(selector)
            for el in elements:
                if el.is_visible():
                    el.click()
                    return True
        except:
            continue
    return False


def select_option(page: Page, label_text: str, option_text: str) -> bool:
    """Try to select a dropdown option."""
    try:
        # Find select elements
        selects = page.query_selector_all("select")
        for select in selects:
            # Check if label matches
            parent = select.evaluate_handle("el => el.closest('.fb-dash-form-element, .jobs-easy-apply-form-section__grouping')")
            if parent:
                label = parent.query_selector("label, .fb-dash-form-element__label")
                if label and label_text.lower() in label.inner_text().lower():
                    # Find matching option
                    options = select.query_selector_all("option")
                    for opt in options:
                        if option_text.lower() in opt.inner_text().lower():
                            select.select_option(value=opt.get_attribute("value"))
                            return True
    except:
        pass
    return False


def answer_question(page: Page, question_text: str) -> str:
    """Determine the best answer for a question based on resume data."""
    q = question_text.lower()

    # Work authorization
    if "authorized" in q or "legally authorized" in q or "eligib" in q:
        return "Yes"

    # Sponsorship
    if "sponsor" in q or "visa" in q:
        return "No"

    # Relocation
    if "relocat" in q or "willing to move" in q:
        return "Yes"

    # Years of experience
    if "years" in q and ("experience" in q or "experi" in q):
        if "manage" in q or "lead" in q:
            return "10"
        elif "python" in q or "machine learning" in q or "data science" in q:
            return "15"
        else:
            return "15"

    # Education
    if "degree" in q or "education" in q:
        return "Doctorate"

    # Remote/hybrid preference
    if "remote" in q or "hybrid" in q or "on-site" in q or "work arrangement" in q:
        return "Remote"

    # Salary (if asked - be strategic)
    if "salary" in q or "compensation" in q or "pay" in q:
        return ""  # Skip salary questions

    # Start date
    if "start" in q and "date" in q:
        return "2 weeks"

    # Default
    return ""


def fill_easy_apply_form(page: Page, resume_data: dict) -> dict:
    """Fill out LinkedIn Easy Apply form fields."""
    results = {"filled": [], "skipped": [], "errors": []}

    page.wait_for_timeout(2000)

    # Fill text inputs
    text_inputs = page.query_selector_all("input[type='text'], input[type='email'], input[type='tel']")
    for inp in text_inputs:
        try:
            if not inp.is_visible():
                continue

            # Get label
            label = ""
            label_el = inp.evaluate_handle("el => el.closest('.fb-dash-form-element, .jobs-easy-apply-form-section__grouping')?.querySelector('label')")
            if label_el:
                label = label_el.inner_text().lower()

            placeholder = (inp.get_attribute("placeholder") or "").lower()
            name = (inp.get_attribute("name") or "").lower()

            value = ""
            field_name = label or placeholder or name

            if "email" in field_name:
                value = resume_data.get("email", "")
            elif "phone" in field_name or "mobile" in field_name:
                value = resume_data.get("phone", "")
            elif "linkedin" in field_name:
                value = resume_data.get("linkedin", "")
            elif "city" in field_name or "location" in field_name:
                value = resume_data.get("location", "")
            elif "name" in field_name and "first" in field_name:
                value = resume_data.get("name", "").split()[0]
            elif "name" in field_name and "last" in field_name:
                value = resume_data.get("name", "").split()[-1]

            if value and not inp.input_value():
                inp.fill(value)
                results["filled"].append(field_name)
        except Exception as e:
            results["errors"].append(str(e))

    # Handle radio buttons and checkboxes
    radios = page.query_selector_all("input[type='radio']")
    for radio in radios:
        try:
            if not radio.is_visible():
                continue

            # Get the question/label
            parent = radio.evaluate_handle("el => el.closest('.fb-dash-form-element, .jobs-easy-apply-form-section__grouping')")
            if parent:
                question_el = parent.query_selector("legend, .fb-dash-form-element__label, span[aria-hidden='true']")
                if question_el:
                    question = question_el.inner_text()
                    answer = answer_question(page, question)

                    if answer:
                        # Find the radio with matching value
                        label = radio.evaluate_handle("el => el.closest('label') || el.nextElementSibling")
                        if label:
                            label_text = label.inner_text().lower()
                            if answer.lower() in label_text or label_text in answer.lower():
                                if not radio.is_checked():
                                    radio.click()
                                    results["filled"].append(f"Radio: {question}")
        except Exception as e:
            results["errors"].append(str(e))

    # Handle dropdowns
    selects = page.query_selector_all("select")
    for select in selects:
        try:
            if not select.is_visible():
                continue

            parent = select.evaluate_handle("el => el.closest('.fb-dash-form-element, .jobs-easy-apply-form-section__grouping')")
            if parent:
                label_el = parent.query_selector("label, .fb-dash-form-element__label")
                if label_el:
                    label = label_el.inner_text()
                    answer = answer_question(page, label)

                    if answer:
                        options = select.query_selector_all("option")
                        for opt in options:
                            opt_text = opt.inner_text().lower()
                            if answer.lower() in opt_text or opt_text in answer.lower():
                                select.select_option(value=opt.get_attribute("value"))
                                results["filled"].append(f"Select: {label}")
                                break
        except Exception as e:
            results["errors"].append(str(e))

    return results


def apply_to_job(job_url: str, headless: bool = False) -> dict:
    """Apply to a job using AI-assisted form filling."""
    result = {
        "success": False,
        "url": job_url,
        "message": "",
        "steps_completed": [],
        "errors": []
    }

    config = load_config()
    if not config.get("linkedin_email"):
        result["message"] = "LinkedIn credentials not found"
        return result

    # Load email from config
    resume_data = RESUME_DATA.copy()
    resume_data["email"] = config.get("linkedin_email", "")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            # Login
            print("Logging in to LinkedIn...")
            if not auto_login(page, config["linkedin_email"], config["linkedin_password"]):
                result["message"] = "Login failed"
                browser.close()
                return result
            result["steps_completed"].append("Logged in")
            print("✓ Logged in")

            # Navigate to job
            print(f"Navigating to job: {job_url}")
            page.goto(job_url, timeout=60000)
            page.wait_for_timeout(3000)

            # Try to dismiss cookie modal if it appears on job page
            if dismiss_cookie_modal(page):
                result["steps_completed"].append("Dismissed cookie modal")

            result["steps_completed"].append("Opened job page")

            # Check if this is an Easy Apply job or external application
            page.wait_for_timeout(2000)

            # Click Easy Apply button
            easy_apply_selectors = [
                "button.jobs-apply-button",
                "[data-control-name='jobdetails_topcard_inapply']",
                "button:has-text('Easy Apply')",
                ".jobs-apply-button--top-card"
            ]

            apply_clicked = False
            for selector in easy_apply_selectors:
                try:
                    btn = page.query_selector(selector)
                    if btn and btn.is_visible():
                        btn.click()
                        apply_clicked = True
                        break
                except:
                    continue

            if not apply_clicked:
                # No Easy Apply - check if we're on an external site or if there's an Apply button
                apply_btn = page.query_selector("button:has-text('Apply'), a:has-text('Apply')")
                if apply_btn and apply_btn.is_visible():
                    apply_btn.click()
                    result["steps_completed"].append("Clicked Apply button")
                    page.wait_for_timeout(3000)
                    # Try to dismiss any cookie modals on external site
                    dismiss_cookie_modal(page)

                result["message"] = "No Easy Apply - browser open for manual application"
                result["success"] = True
                result["requires_review"] = True
                print("\n" + "="*50)
                print("📋 MANUAL APPLICATION REQUIRED")
                print("="*50)
                print("This job doesn't have Easy Apply.")
                print("Complete the application manually in the browser.")
                print("Close the browser when done.")
                print("="*50 + "\n")

                # Keep browser open for manual completion
                try:
                    while True:
                        page.wait_for_timeout(2000)
                        try:
                            page.title()
                        except:
                            break
                except:
                    pass

                try:
                    browser.close()
                except:
                    pass
                return result

            result["steps_completed"].append("Clicked Easy Apply")
            print("✓ Clicked Easy Apply")
            page.wait_for_timeout(2000)

            # Dismiss any cookie modal that appears on external application page
            dismiss_cookie_modal(page)
            page.wait_for_timeout(1000)

            # Fill forms until we reach submit or hit an issue
            max_steps = 10
            for step in range(max_steps):
                print(f"Processing step {step + 1}...")

                # Fill form fields
                fill_results = fill_easy_apply_form(page, resume_data)
                result["steps_completed"].extend([f"Filled: {f}" for f in fill_results["filled"]])

                page.wait_for_timeout(1000)

                # Check for submit button
                submit_btn = page.query_selector("button[aria-label='Submit application']")
                if submit_btn and submit_btn.is_visible():
                    print("\n" + "="*50)
                    print("🛑 STOPPING FOR HUMAN REVIEW")
                    print("="*50)
                    print("Application is ready to submit.")
                    print("Please review all fields in the browser before submitting.")
                    print("\nThe browser will stay open for you to:")
                    print("  1. Review and correct any auto-filled information")
                    print("  2. Fill in any fields that couldn't be auto-filled")
                    print("  3. Click 'Submit application' when ready")
                    print("="*50 + "\n")

                    result["message"] = "Application ready - REVIEW REQUIRED before submitting"
                    result["success"] = True
                    result["requires_review"] = True

                    # Take screenshot for review
                    screenshot_path = DATA_DIR / "application_preview.png"
                    page.screenshot(path=str(screenshot_path))
                    result["screenshot"] = str(screenshot_path)

                    # NEVER auto-submit - always require human review
                    # Keep browser open for manual review and submission
                    # Wait for user to close browser or submit
                    print("Browser will stay open. Close it when done reviewing/submitting.")
                    try:
                        # Wait until browser is closed by user
                        while True:
                            page.wait_for_timeout(2000)
                            # Check if page is still valid
                            try:
                                page.title()
                            except:
                                break
                    except:
                        pass
                    break

                # Check for Next button
                next_btn = page.query_selector("button[aria-label='Continue to next step']")
                if next_btn and next_btn.is_visible():
                    next_btn.click()
                    result["steps_completed"].append(f"Step {step + 1} completed")
                    print(f"✓ Step {step + 1} completed")
                    page.wait_for_timeout(2000)
                    continue

                # Check for Review button
                review_btn = page.query_selector("button[aria-label='Review your application']")
                if review_btn and review_btn.is_visible():
                    review_btn.click()
                    result["steps_completed"].append("Reached review page")
                    print("✓ Reached review page")
                    page.wait_for_timeout(2000)
                    continue

                # No recognized button found
                page.wait_for_timeout(1000)

            # Keep browser open for manual completion if not headless
            if not headless and not result["success"]:
                print("\nBrowser left open for manual completion. Close browser when done.")
                result["message"] = "Browser open for manual completion - close when done"
                try:
                    while True:
                        page.wait_for_timeout(2000)
                        try:
                            page.title()
                        except:
                            break
                except:
                    pass

        except Exception as e:
            result["errors"].append(str(e))
            result["message"] = f"Error: {str(e)}"

        try:
            browser.close()
        except:
            pass  # Browser may already be closed

    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        job_url = sys.argv[1]
        result = apply_to_job(job_url, headless=False)
        print("\n" + "="*50)
        print("Application Result:")
        print(f"  Success: {result['success']}")
        print(f"  Message: {result['message']}")
        print(f"  Steps: {result['steps_completed']}")
        if result['errors']:
            print(f"  Errors: {result['errors']}")
    else:
        print("Usage: python ai_apply.py <job_url>")
