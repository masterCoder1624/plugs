"""
LinkedIn Job Scraper  v5
========================
Completely rewritten from all lessons learned. Key design principles:

CARD SCRAPING (scrape_card):
  - Uses data-occludable-job-id / data-job-id for URL (never breaks)
  - aria-label on job link for title (no duplication)
  - span[class*="aece04b6"] for location + posted (exact DOM class from screenshots)
  - TreeWalker full-text fallback for posted
  - Class-based fallback chain for company

DETAIL PAGE SCRAPING (scrape_detail):
  - Single JS call extracts everything
  - a[href*="/company/"] with path-length=2 check for company_url
  - criteria list for industry/seniority/employment_type
  - Full TreeWalker over body → regex classification for followers/employees/sector
  - sector picks only from known industry label patterns (not "0 notifications")

INFRASTRUCTURE:
  - domcontentloaded only (never networkidle — LinkedIn never reaches it)
  - Timeout-safe navigation (PWTimeout caught, page still used)
  - Saves each job to MongoDB immediately after enrichment
  - Reads search URLs from users_db.engines
  - Humanised delays throughout
"""
import os
import sys
import asyncio
import json
import re
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from pymongo import MongoClient

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

SESSION_FILE = Path("linkedin_session.json")
OUTPUT_DIR   = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

BACKEND_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
ROOT_DIR = BACKEND_DIR.parent
CONFIG_FILE = ROOT_DIR / "config" / "config.json"

def load_mongo_uri():
    env_uri = os.environ.get("PLUGS_MONGO_URI")
    if env_uri:
        return env_uri

    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text())
            mongo_uri = config.get("mongoUri")
            if mongo_uri and mongo_uri != "PASTE_MONGODB_ATLAS_URI_HERE":
                return mongo_uri
        except Exception:
            pass

    return "mongodb://localhost:27017"

MONGO_URI = load_mongo_uri()

DB_LEADS         = "scraping_leads"
COL_REQUIREMENTS = "requirements"
DB_USERS         = "users_db"
COL_ENGINES      = "engines"

# ── Known industry sector labels from LinkedIn ────────────────────────────────
# Used to identify company_sector from the full-page text dump
KNOWN_SECTORS = {
    "software development", "information technology", "it services",
    "it services and it consulting", "computer and network security",
    "internet publishing", "technology", "staffing and recruiting",
    "human resources", "financial services", "banking", "insurance",
    "investment management", "accounting", "real estate", "construction",
    "manufacturing", "automotive", "aerospace", "defense", "oil and gas",
    "utilities", "energy", "renewables", "environmental services",
    "retail", "consumer goods", "food and beverage", "restaurants",
    "hospitality", "travel", "airlines", "logistics", "transportation",
    "healthcare", "hospitals", "pharmaceuticals", "biotechnology",
    "medical devices", "mental health care", "wellness",
    "education", "e-learning", "research", "higher education",
    "media", "broadcast", "entertainment", "gaming", "music",
    "marketing", "advertising", "public relations", "design",
    "architecture", "legal services", "consulting", "management consulting",
    "non-profit", "government", "military", "law enforcement",
    "telecommunications", "semiconductors", "nanotechnology",
    "venture capital", "private equity", "fundraising",
}

# ══════════════════════════════════════════════════════════════════════════════
#  MONGODB
# ══════════════════════════════════════════════════════════════════════════════

def get_mongo_client():
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=5_000)


def load_search_urls() -> list:
    try:
        client = get_mongo_client()
        docs   = list(client[DB_USERS][COL_ENGINES].find({}, {"url": 1}))
        client.close()
        urls = [doc["url"] for doc in docs if doc.get("url")]
        print(f"  📋 Loaded {len(urls)} URL(s) from {DB_USERS}.{COL_ENGINES}")
        return urls
    except Exception as e:
        print(f"  ❌ MongoDB read error: {e}")
        return []


def save_one_to_mongo(job: dict):
    try:
        client = get_mongo_client()
        job["scraped_at"] = datetime.now(timezone.utc)
        client[DB_LEADS][COL_REQUIREMENTS].insert_one(job)
        client.close()
        print(f"       💾 Saved → {job.get('title','')[:55]}")
    except Exception as e:
        print(f"       ❌ DB error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  HUMANISED DELAYS
# ══════════════════════════════════════════════════════════════════════════════

async def human_delay(min_s=0.8, max_s=2.2):
    await asyncio.sleep(random.uniform(min_s, max_s))

async def page_load_delay():
    await asyncio.sleep(random.uniform(2.5, 5.0))

async def human_scroll(page, total_px=2400):
    scrolled = 0
    for _ in range(random.randint(4, 8)):
        chunk = random.randint(300, 700)
        scrolled += chunk
        if scrolled > total_px:
            break
        await page.mouse.wheel(0, chunk)
        await asyncio.sleep(random.uniform(0.3, 1.1))
        if random.random() < 0.25:
            await asyncio.sleep(random.uniform(1.0, 2.5))

async def human_scroll_element(page, selector, total_px=2400):
    try:
        el = await page.query_selector(selector)
        if not el:
            return False
        scrolled = 0
        for _ in range(random.randint(4, 8)):
            chunk = random.randint(300, 700)
            scrolled += chunk
            await el.evaluate(f"e => e.scrollBy(0, {chunk})")
            await asyncio.sleep(random.uniform(0.3, 1.0))
            if random.random() < 0.2:
                await asyncio.sleep(random.uniform(1.0, 2.0))
            if scrolled >= total_px:
                break
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  BROWSER / SESSION
# ══════════════════════════════════════════════════════════════════════════════

async def save_session(context):
    storage = await context.storage_state()
    SESSION_FILE.write_text(json.dumps(storage, indent=2))
    print("  ✅ Session saved →", SESSION_FILE)


async def make_browser_context(playwright):
    browser = await playwright.chromium.launch(
        headless=False, slow_mo=0,
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
    )
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    kwargs = dict(viewport={"width": 1280, "height": 900}, user_agent=ua)
    if SESSION_FILE.exists():
        print("  🔄 Found saved session — loading …")
        kwargs["storage_state"] = json.loads(SESSION_FILE.read_text())
    else:
        print("  🌐 No saved session — fresh context.")
    context = await browser.new_context(**kwargs)
    await context.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return browser, context


# ══════════════════════════════════════════════════════════════════════════════
#  LOGIN
# ══════════════════════════════════════════════════════════════════════════════

async def is_logged_in(page) -> bool:
    return any(k in page.url for k in ["/feed", "/mynetwork", "/in/", "/jobs"])

async def verify_session(page) -> bool:
    print("  🔍 Verifying session …")
    try:
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        await page_load_delay()
    except Exception as e:
        print(f"  ⚠️  Navigation error: {e}")
        return False
    return await is_logged_in(page)

async def wait_for_manual_login(page, context) -> bool:
    print("\n" + "═"*62)
    print("  🔐  LOGIN REQUIRED — please log in to LinkedIn in the browser.")
    print("  Script resumes automatically. You have 5 minutes.")
    print("═"*62 + "\n")
    try:
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await page_load_delay()
    except Exception:
        pass
    deadline = time.monotonic() + 300
    dots = 0
    while time.monotonic() < deadline:
        if await is_logged_in(page):
            print("\n   Login detected!")
            await asyncio.sleep(random.uniform(3.0, 5.0))
            await save_session(context)
            return True
        dots += 1
        print(f"   Waiting … ({dots*2}s)", end="\r")
        await asyncio.sleep(2)
    print("\n   Login timed out.")
    return False

async def ensure_authenticated(page, context) -> bool:
    if SESSION_FILE.exists():
        if await verify_session(page):
            print("   Session valid — skipping login.\n")
            return True
        print("    Session expired — need to log in again.")
        SESSION_FILE.unlink(missing_ok=True)
    if not await wait_for_manual_login(page, context):
        return False
    if await verify_session(page):
        print("   Session verified — ready!\n")
        return True
    print("   Session verification failed.")
    return False


#  CARD DETECTION
CARD_SELECTORS = [
    "li[data-occludable-job-id]",
    "li[data-job-id]",
    "li.jobs-search-results__list-item",
    "li.ember-view.scaffold-layout__list-item",
    "li.scaffold-layout__list-item",
    "div.job-card-container",
    "div[data-job-id]",
    "li[class*='jobs-search-results']",
    "li[class*='scaffold-layout__list-item']",
    "li[class*='job-card']",
]

CONTAINER_SELECTORS = [
    ".jobs-search-results-list",
    ".scaffold-layout__list",
    ".jobs-search__results-list",
    ".jobs-search-two-pane__results",
    "[class*='jobs-search-results-list']",
    "[class*='scaffold-layout__list']",
    "[class*='two-pane__results']",
]

async def scroll_results_panel(page):
    for sel in CONTAINER_SELECTORS:
        if await human_scroll_element(page, sel, total_px=random.randint(2000, 3000)):
            return
    await human_scroll(page, total_px=random.randint(2000, 3000))

async def find_cards(page):
    for sel in CARD_SELECTORS:
        try:
            cards = await page.query_selector_all(sel)
            if cards:
                print(f"      Matched '{sel}' → {len(cards)} cards")
                return cards
        except Exception:
            pass
    for attr in ["data-occludable-job-id", "data-job-id"]:
        try:
            cards = await page.query_selector_all(f"[{attr}]")
            if cards:
                print(f"      JS fallback [{attr}] → {len(cards)} cards")
                return cards
        except Exception:
            pass
    return []

async def diagnose_page(page, page_num):
    try:
        r = await page.evaluate("""() => {
            const cls=new Set(), dat=new Set();
            for(const el of document.querySelectorAll('*')){
                if(typeof el.className==='string')
                    el.className.split(' ').forEach(c=>{
                        if(c&&(c.includes('job')||c.includes('scaffold')||
                               c.includes('result')||c.includes('card')))cls.add(c);});
                el.getAttributeNames().forEach(a=>{
                    if(a.startsWith('data-')&&(a.includes('job')||
                       a.includes('occludable')||a.includes('entity')))
                        dat.add(a+'="'+(el.getAttribute(a)||'').slice(0,30)+'"');});
            }
            return{cls:Array.from(cls).slice(0,40),
                   dat:Array.from(dat).slice(0,15),
                   li:document.querySelectorAll('li').length,
                   url:location.href};
        }""")
        print(f"\n     ── Diagnosis (page {page_num}) ───────────────────────────")
        print(f"     URL : {r['url'][:90]}")
        print(f"     <li>: {r['li']}")
        for c in r['cls']: print(f"       class · {c}")
        for d in r['dat']:  print(f"       attr  · {d}")
        print(f"     ──────────────────────────────────────────────────────────")
    except Exception as e:
        print(f"     Diagnosis error: {e}")


def normalize_posted_date(posted_text: str):
    if not posted_text:
        return ""

    posted_text = posted_text.lower().strip()
    now = datetime.now(timezone.utc)

    try:
        if "just now" in posted_text:
            return now.isoformat()

        m = re.search(r'(\d+)\s+(second|minute|hour|day|week|month)', posted_text)
        if not m:
            return posted_text

        value = int(m.group(1))
        unit  = m.group(2)

        from datetime import timedelta

        if "second" in unit:
            dt = now - timedelta(seconds=value)
        elif "minute" in unit:
            dt = now - timedelta(minutes=value)
        elif "hour" in unit:
            dt = now - timedelta(hours=value)
        elif "day" in unit:
            dt = now - timedelta(days=value)
        elif "week" in unit:
            dt = now - timedelta(weeks=value)
        elif "month" in unit:
            dt = now - timedelta(days=value * 30)
        else:
            return posted_text

        return dt.isoformat()

    except Exception:
        return posted_text


#  SCRAPE SINGLE CARD

async def scrape_card(card) -> dict:
    """
    Extract title, company, location, posted, url from a job card.

    DOM structure observed in screenshots:
      - Job link:  <a href="/jobs/view/ID" aria-label="TITLE">
      - Company:   <span class*="primary-description"> or subtitle span
      - Location:  <span class="aece04b6">CITY, Country</span>
      - Posted:    <span class="aece04b6">2 days ago</span>  ← same class as location!
      - Separator: <span class="e260aedb">·</span>
    """
    job = {}
    try:
        data = await card.evaluate(r"""el => {
            var agoRe = /(reposted\s+)?(\d+\s+(?:second|minute|hour|day|week|month)s?\s+ago|just\s+now)/i;

            // ── Title ─────────────────────────────────────────────────────
            var title = '';
            var titleLink = el.querySelector('a[href*="/jobs/view/"]');
            if (titleLink) {
                title = (titleLink.getAttribute('aria-label') || '').trim();
                if (!title) title = titleLink.innerText.trim().replace(/\s+/g, ' ');
            }
            if (!title) {
                var strong = el.querySelector('strong');
                if (strong) title = strong.innerText.trim().replace(/\s+/g, ' ');
            }
            // Deduplicate: "Foo Bar Foo Bar" -> "Foo Bar"
            var words = title.split(' ');
            var half  = Math.floor(words.length / 2);
            if (half > 1 &&
                words.slice(0, half).join(' ') === words.slice(half).join(' ')) {
                title = words.slice(0, half).join(' ');
            }

            // ── Company ───────────────────────────────────────────────────
            var company = '';
            var compSels = [
                '[class*="primary-description"]',
                '[class*="company-name"]',
                '.artdeco-entity-lockup__subtitle span',
                '[class*="subtitle"] span'
            ];
            for (var i = 0; i < compSels.length; i++) {
                var cn = el.querySelector(compSels[i]);
                if (cn && cn.innerText.trim()) {
                    company = cn.innerText.trim().replace(/\s+/g, ' ');
                    break;
                }
            }

            // ── Location & Posted
            var location = '', posted = '';

            // Strategy A: aria-hidden="true" — confirmed real tag from DOM screenshot
            // <span aria-hidden="true">3 days ago</span>
            // Use textContent (not innerText) to avoid CSS whitespace collapse issues
            var allSpans = el.querySelectorAll('span[aria-hidden="true"]');
            for (var ai = 0; ai < allSpans.length; ai++) {
                var at = (allSpans[ai].textContent || '').replace(/\s+/g, ' ').trim();
                if (at.length < 3) continue;
                var match = at.match(agoRe);
                if (match) { posted = match[2].replace(/\s+/g, ' ').trim(); break; }
            }

            // Strategy C: class fragment aece04b6 — also gives location
            var infoSpans = el.querySelectorAll('span[class*="aece04b6"]');
            for (var si = 0; si < infoSpans.length; si++) {
                var st = (infoSpans[si].textContent || '').replace(/\s+/g, ' ').trim();
                if (!st || st === '·' || st === '.' || st.length < 2) continue;
                if (!posted && agoRe.test(st)) {
                    var match = st.match(agoRe);
                    if (match) posted = match[2].trim();
                } else if (!location && !agoRe.test(st)) {
                    location = st;
                }
            }
            // Strategy: detect <strong> containing posted time (HIGH PRIORITY)
            var strongTags = el.querySelectorAll("strong");

            for (var si = 0; si < strongTags.length; si++) {
                var st = (strongTags[si].innerText || '').replace(/\s+/g, ' ').trim();

                var match = st.match(/(?:reposted\s+)?(\d+\s+(?:second|minute|hour|day|week|month)s?\s+ago)/i);

                if (match) {
                    posted = match[1];
                    break;
                }
            }

            // Strategy D: metadata list items for location fallback
            if (!location) {
                var metaItems = el.querySelectorAll(
                    '[class*="metadata-item"], [class*="metadata"] li'
                );
                for (var mi = 0; mi < metaItems.length; mi++) {
                    var mt = (metaItems[mi].textContent || '').replace(/\s+/g, ' ').trim();
                    if (!mt) continue;
                    if (!posted && agoRe.test(mt)) {
                        var match = mt.match(agoRe);
                        if (match) posted = match[2].trim();
                    } else if (!location && !agoRe.test(mt)) {
                        location = mt;
                    }
                }
            }

            // Strategy B: collect all text nodes via TreeWalker, match "X ago"
            // This is the most reliable fallback — works regardless of any class
            if (!posted) {
                var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
                var wNode;
                while ((wNode = walker.nextNode())) {
                    var wt = (wNode.textContent || '').replace(/\s+/g, ' ').trim();
                    var wm = wt.match(agoRe);
                    if (wm) { posted = wm[2].trim(); break; }
                }
            }

            return { title: title, company: company,
                     location: location, posted: posted };
        }""")

        job["title"]    = data.get("title",    "")
        job["company"]  = data.get("company",  "")
        job["location"] = data.get("location", "")
        raw_posted = data.get("posted", "")
        job["posted"] = raw_posted
        job["posted_timestamp"] = normalize_posted_date(raw_posted)

    except Exception as e:
        print(f"        scrape_card JS error: {e}")
        job.setdefault("title",    "")
        job.setdefault("company",  "")
        job.setdefault("location", "")
        job.setdefault("posted",   "")

    # URL — read data-attribute directly (most reliable, never breaks)
    try:
        job_id = (await card.get_attribute("data-occludable-job-id") or
                  await card.get_attribute("data-job-id"))
        if job_id:
            job["url"] = f"https://www.linkedin.com/jobs/view/{job_id}/"
        else:
            a = await card.query_selector('a[href*="/jobs/view/"]')
            href = await a.get_attribute("href") if a else ""
            job["url"] = ("https://www.linkedin.com" + href.split("?")[0]
                          if href and href.startswith("/") else href or "")
    except Exception:
        job["url"] = ""

    return job


#  SCRAPE DETAIL PAGE

# ══════════════════════════════════════════════════════════════════════════════
#  SCRAPE DETAIL PAGE
# ══════════════════════════════════════════════════════════════════════════════

async def scrape_detail(page, url: str) -> dict:
    """
    Visit job detail page, extract company info + job criteria via single JS call.

    Extraction strategy:
      - Navigate with domcontentloaded (never networkidle)
      - company_url: a[href*="/company/"] where path segments == 2 (/company/{slug})
      - criteria: job-criteria list items → classify into industry / seniority / employment_type
      - description: main job description container
      - followers / employees / company_sector: TreeWalker over document.body,
        regex-classified, sector matched only against KNOWN_SECTORS (avoids
        false positives like "0 notifications")
    """
    detail = {
        "industry": "", "employment_type": "", "seniority_level": "",
        "company_url": "", "company_name": "", "description": "",
        "followers": "", "employees": "", "company_sector": "",
    }

    try:
        await page.goto(url, wait_until="domcontentloaded")
    except PWTimeout:
        print("        ⏱️  Timeout loading detail page — using partial DOM")
    except Exception as e:
        print(f"        ❌ Detail nav error: {e}")
        return detail

    await page_load_delay()
    await human_scroll(page, total_px=random.randint(800, 1600))

    known_sectors_js = json.dumps(sorted(KNOWN_SECTORS))

    try:
        data = await page.evaluate(r"""(knownSectorsJson) => {
            var knownSectors = new Set(JSON.parse(knownSectorsJson));

            var result = {
                industry: '', employment_type: '', seniority_level: '',
                company_url: '', company_name: '', description: '',
                followers: '', employees: '', company_sector: ''
            };

            // ── Company URL & name ──────────────────────────────────────
            var companyLinks = document.querySelectorAll('a[href*="/company/"]');
            for (var i = 0; i < companyLinks.length; i++) {
                var href = companyLinks[i].getAttribute('href') || '';
                var path = href.split('?')[0].split('/').filter(Boolean);
                // /company/{slug} → ['company','slug'] → length 2
                if (path.length === 2 && path[0] === 'company') {
                    result.company_url = 'https://www.linkedin.com/' + path.join('/') + '/';
                    var name = (companyLinks[i].innerText || '').trim().replace(/\s+/g, ' ');
                    if (name) result.company_name = name;
                    break;
                }
            }

            // ── Job criteria (industry / seniority / employment type) ──
            var criteriaSels = [
                '.job-details-jobs-unified-top-card__job-insight',
                '[class*="job-criteria"] li',
                '.description__job-criteria-item',
                'li[class*="job-criteria-item"]'
            ];
            var criteriaItems = [];
            for (var ci = 0; ci < criteriaSels.length; ci++) {
                var found = document.querySelectorAll(criteriaSels[ci]);
                if (found.length) { criteriaItems = Array.from(found); break; }
            }

            for (var j = 0; j < criteriaItems.length; j++) {
                var txt = (criteriaItems[j].innerText || '').trim().replace(/\s+/g, ' ');
                var low = txt.toLowerCase();
                if (!txt) continue;

                if (/entry level|associate|mid-senior|director|executive|internship/.test(low)) {
                    result.seniority_level = txt;
                } else if (/full-time|part-time|contract|temporary|volunteer|internship/.test(low) &&
                           !/entry level|associate|mid-senior|director|executive/.test(low)) {
                    result.employment_type = txt;
                } else if (knownSectors.has(low)) {
                    result.industry = txt;
                }
            }

            // ── Description ─────────────────────────────────────────────
            var descSels = [
                '#job-details',
                '.jobs-description__content',
                '.jobs-box__html-content',
                '[class*="jobs-description-content"]'
            ];
            for (var di = 0; di < descSels.length; di++) {
                var descEl = document.querySelector(descSels[di]);
                if (descEl && descEl.innerText.trim()) {
                    result.description = descEl.innerText.trim().replace(/\n{3,}/g, '\n\n');
                    break;
                }
            }

            // ── TreeWalker over body: followers / employees / sector ───
            var followersRe = /([\d,.]+[kKmM]?)\s*followers/i;
            var employeesRe = /([\d,.]+[kKmM]?(?:-[\d,.]+[kKmM]?)?)\s*employees/i;

            var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
            var node;
            while ((node = walker.nextNode())) {
                var t = (node.textContent || '').replace(/\s+/g, ' ').trim();
                if (!t || t.length > 200) continue;

                if (!result.followers) {
                    var fm = t.match(followersRe);
                    if (fm) result.followers = fm[1];
                }
                if (!result.employees) {
                    var em = t.match(employeesRe);
                    if (em) result.employees = em[1];
                }
                if (!result.company_sector) {
                    var low2 = t.toLowerCase();
                    // Exact match only — rejects noise like "0 notifications"
                    if (knownSectors.has(low2)) {
                        result.company_sector = t;
                    }
                }

                if (result.followers && result.employees && result.company_sector) break;
            }

            return result;
        }""", known_sectors_js)

        for key in detail:
            if data.get(key):
                detail[key] = data[key]

    except Exception as e:
        print(f"        ❌ scrape_detail JS error: {e}")

    return detail


# ══════════════════════════════════════════════════════════════════════════════
#  ORCHESTRATION / PAGINATION
# ══════════════════════════════════════════════════════════════════════════════

async def scrape_search_url(page, context, search_url: str, max_pages: int = 5) -> int:
    """
    Paginate through a single LinkedIn job-search URL, scraping every card
    on every page, enriching each with detail-page data, and saving
    immediately to MongoDB.

    FIX: detail pages are opened in a SEPARATE tab (detail_page), not the
    same `page` used for the listing. Reusing one page for both navigates
    the listing away mid-loop, which destroys the JS execution context for
    every remaining card handle ("Execution context was destroyed, most
    likely because of a navigation") and silently drops every card after
    the first one on each page.
    """
    seen_urls = set()
    total_saved = 0
    detail_page = await context.new_page()   # <-- separate tab, created once

    try:
        for page_num in range(max_pages):
            start = page_num * 25
            sep = "&" if "?" in search_url else "?"
            paged_url = f"{search_url}{sep}start={start}"

            print(f"\n  📄 Page {page_num + 1}  (start={start})")
            try:
                await page.goto(paged_url, wait_until="domcontentloaded")
            except PWTimeout:
                print("      ⏱️  Timeout navigating — continuing with partial DOM")
            except Exception as e:
                print(f"      ❌ Navigation error: {e}")
                break

            await page_load_delay()
            await scroll_results_panel(page)
            await human_delay()

            cards = await find_cards(page)
            if not cards:
                print("      ⚠️  No cards found on this page.")
                await diagnose_page(page, page_num + 1)
                break

            page_new_count = 0
            for idx, card in enumerate(cards, start=1):
                try:
                    await card.scroll_into_view_if_needed()
                    await asyncio.sleep(random.uniform(0.3, 0.7))   # let LinkedIn render this card's content
                    job = await scrape_card(card)
                except Exception as e:
                    print(f"      ❌ Card {idx} scrape error: {e}")
                    continue

                if not job.get("url") or job["url"] in seen_urls:
                    continue
                seen_urls.add(job["url"])
                page_new_count += 1

                print(f"      [{idx}/{len(cards)}] {job.get('title','')[:55]}")

                try:
                    detail = await scrape_detail(detail_page, job["url"])  # <-- separate tab
                    job.update(detail)
                except Exception as e:
                    print(f"        ❌ Detail scrape error: {e}")

                save_one_to_mongo(job)
                total_saved += 1

                await human_delay()

            print(f"      → {page_new_count} new job(s) this page.")

            if page_new_count == 0:
                print("      No new jobs found — stopping pagination for this URL.")
                break

            await human_delay(1.5, 3.5)
    finally:
        await detail_page.close()

    return total_saved


async def main(search_urls=None):
    if search_urls is None:
        search_urls = load_search_urls()
    if not search_urls:
        print("  ⚠️  No search URLs configured in users_db.engines — nothing to do.")
        return

    async with async_playwright() as p:
        browser, context = await make_browser_context(p)
        page = await context.new_page()

        try:
            if not await ensure_authenticated(page, context):
                print("  ❌ Authentication failed — aborting.")
                return

            grand_total = 0
            for i, search_url in enumerate(search_urls, start=1):
                print(f"\n{'═'*62}")
                print(f"  🔎 Search {i}/{len(search_urls)}: {search_url[:80]}")
                print(f"{'═'*62}")
                try:
                    saved = await scrape_search_url(page, context, search_url)
                    grand_total += saved
                except Exception as e:
                    print(f"  ❌ Error processing search URL: {e}")
                await human_delay(2.0, 4.0)

            print(f"\n✅ Done. {grand_total} job(s) saved across {len(search_urls)} search URL(s).")

        finally:
            await save_session(context)
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
