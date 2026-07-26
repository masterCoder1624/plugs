import asyncio
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from pymongo import MongoClient


BACKEND_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)

ROOT_DIR = BACKEND_DIR.parent
CONFIG_FILE = ROOT_DIR / "config" / "config.json"
SESSION_FILE = ROOT_DIR / "config" / "linkedin_session.json"

DB_OUTREACH = "plugs_outreach"
COL_CAMPAIGNS = "campaigns"
COL_PROFILES = "people_profiles"
COL_INVITES = "connection_invites"
COL_MESSAGES = "messages"


def utc_now():
    return datetime.now(timezone.utc)


def today_key():
    return utc_now().strftime("%Y-%m-%d")


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


def get_mongo_client():
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)


def normalize_profile_url(url: str) -> str:
    if not url:
        return ""

    url = url.split("?")[0].strip()

    if url.startswith("/"):
        url = "https://www.linkedin.com" + url

    if url.startswith("https://www.linkedin.com/in/") and not url.endswith("/"):
        url += "/"

    return url


def first_name_from_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    return name.split()[0]


def safe_doc(value: Any):
    if isinstance(value, list):
        return [safe_doc(item) for item in value]

    if isinstance(value, dict):
        return {key: safe_doc(val) for key, val in value.items()}

    if isinstance(value, ObjectId):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    return str(value)


class OutreachService:
    def __init__(self, add_log):
        self.add_log = add_log
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.running = False
        self.stop_requested = False

    async def ensure_browser(self):
        if self.playwright and self.browser and self.context and self.page:
            return

        self.playwright = await async_playwright().start()

        self.browser = await self.playwright.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )

        kwargs = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        }

        if SESSION_FILE.exists():
            try:
                kwargs["storage_state"] = json.loads(SESSION_FILE.read_text())
                self.add_log("Loaded saved LinkedIn session.")
            except Exception:
                self.add_log("Saved LinkedIn session was invalid. Starting fresh.")

        self.context = await self.browser.new_context(**kwargs)
        self.page = await self.context.new_page()

    async def save_session(self):
        if not self.context:
            return

        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        await self.context.storage_state(path=str(SESSION_FILE))
        self.add_log("LinkedIn session saved.")

    async def page_text(self) -> str:
        try:
            return (await self.page.inner_text("body")).lower()
        except Exception:
            return ""

    async def detect_linkedin_warning(self) -> str | None:
        text = await self.page_text()

        hard_stop_phrases = [
            "security verification",
            "verify it's you",
            "verify it’s you",
            "quick security check",
            "captcha",
            "unusual activity",
            "temporarily restricted",
            "account has been restricted",
            "your account is restricted",
            "weekly invitation limit",
            "you’ve reached the weekly invitation limit",
            "you've reached the weekly invitation limit",
            "you have reached the weekly invitation limit",
            "try again later",
            "we limit how often you can do certain things",
            "something went wrong",
        ]

        for phrase in hard_stop_phrases:
            if phrase in text:
                return phrase

        return None

    async def should_stop_for_linkedin_warning(self, context: str) -> bool:
        warning = await self.detect_linkedin_warning()

        if not warning:
            return False

        self.add_log(f"Safety stop during {context}: LinkedIn warning detected: {warning}")
        self.stop_requested = True
        return True

    async def find_button_by_text(self, possible_texts: list[str]):
        buttons = await self.page.query_selector_all("button")

        for button in buttons:
            try:
                text = (await button.inner_text()).strip().lower()
                aria = (await button.get_attribute("aria-label") or "").strip().lower()

                for wanted in possible_texts:
                    wanted = wanted.lower()

                    if text == wanted or wanted in aria:
                        return button
            except Exception:
                continue

        return None

    async def close_dialog_if_open(self):
        close_texts = ["dismiss", "close", "cancel", "not now", "got it"]

        for text in close_texts:
            button = await self.find_button_by_text([text])
            if button:
                try:
                    await button.click()
                    await asyncio.sleep(random.uniform(1.0, 2.0))
                    return True
                except Exception:
                    pass

        return False

    async def human_pause(self, min_s=1.5, max_s=3.5):
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def is_logged_in(self) -> bool:
        if not self.page:
            return False

        url = self.page.url.lower()
        return any(part in url for part in ["/feed", "/mynetwork", "/in/", "/jobs", "/search/results"])

    async def connect_linkedin(self, timeout_seconds: int = 300):
        await self.ensure_browser()

        self.add_log("Opening LinkedIn login page.")
        await self.page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

        self.add_log("Please log in manually in the LinkedIn browser window.")
        deadline = asyncio.get_event_loop().time() + timeout_seconds

        while asyncio.get_event_loop().time() < deadline:
            if await self.is_logged_in():
                await asyncio.sleep(2)
                await self.save_session()
                self.add_log("LinkedIn login detected.")
                return {
                    "ok": True,
                    "connected": True,
                    "message": "LinkedIn connected.",
                }

            await asyncio.sleep(2)

        return {
            "ok": False,
            "connected": False,
            "message": "LinkedIn login timed out.",
        }

    async def linkedin_status(self):
        if not SESSION_FILE.exists():
            return {
                "ok": True,
                "connected": False,
                "message": "No saved LinkedIn session found.",
            }

        await self.ensure_browser()

        try:
            await self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            await asyncio.sleep(3)

            connected = await self.is_logged_in()

            return {
                "ok": True,
                "connected": connected,
                "message": "LinkedIn connected." if connected else "LinkedIn session expired.",
            }
        except Exception as error:
            return {
                "ok": False,
                "connected": False,
                "message": str(error),
            }

    def create_campaign(
        self,
        name: str,
        search_url: str,
        daily_limit: int,
        message_template: str | None,
        like_post_after_invite: bool = False,
    ):
        campaign = {
            "name": name,
            "searchUrl": search_url,
            "dailyLimit": min(max(daily_limit, 1), 10),
            "messageTemplate": message_template or "",
            "likePostAfterInvite": bool(like_post_after_invite),
            "status": "created",
            "createdAt": utc_now(),
            "updatedAt": utc_now(),
        }

        client = get_mongo_client()
        result = client[DB_OUTREACH][COL_CAMPAIGNS].insert_one(campaign)
        client.close()

        return str(result.inserted_id)

    def get_campaign(self, campaign_id: str):
        try:
            client = get_mongo_client()
            campaign = client[DB_OUTREACH][COL_CAMPAIGNS].find_one({
                "_id": ObjectId(campaign_id),
            })
            client.close()
            return campaign
        except Exception:
            return None

    def update_campaign_status(self, campaign_id: str, status: str, error: str | None = None):
        try:
            update = {
                "status": status,
                "updatedAt": utc_now(),
            }

            if error:
                update["error"] = error

            client = get_mongo_client()
            client[DB_OUTREACH][COL_CAMPAIGNS].update_one(
                {"_id": ObjectId(campaign_id)},
                {"$set": update},
            )
            client.close()
        except Exception:
            pass

    def get_sent_today_count(self, campaign_id: str) -> int:
        client = get_mongo_client()
        count = client[DB_OUTREACH][COL_INVITES].count_documents({
            "campaignId": campaign_id,
            "dateKey": today_key(),
            "status": {"$in": ["sent", "already_connected", "already_pending"]},
        })
        client.close()
        return count

    def already_invited(self, profile_url: str) -> bool:
        client = get_mongo_client()
        exists = client[DB_OUTREACH][COL_INVITES].find_one({
            "profileUrl": profile_url,
            "status": {"$in": ["sent", "accepted", "already_connected", "already_pending"]},
        })
        client.close()
        return exists is not None

    def save_profile(self, campaign_id: str, profile: dict):
        profile["campaignId"] = campaign_id
        profile["profileUrl"] = normalize_profile_url(profile.get("profileUrl", ""))
        profile["updatedAt"] = utc_now()

        client = get_mongo_client()
        client[DB_OUTREACH][COL_PROFILES].update_one(
            {"profileUrl": profile["profileUrl"]},
            {
                "$set": profile,
                "$setOnInsert": {"createdAt": utc_now()},
            },
            upsert=True,
        )
        client.close()

    def save_invite(
        self,
        campaign_id: str,
        profile: dict,
        status: str,
        error: str | None = None,
        post_like_enabled: bool = False,
        post_liked: bool = False,
        post_like_status: str | None = None,
        post_like_error: str | None = None,
    ):
        profile_url = normalize_profile_url(profile.get("profileUrl", ""))

        doc = {
            "campaignId": campaign_id,
            "name": profile.get("name", ""),
            "headline": profile.get("headline", ""),
            "location": profile.get("location", ""),
            "profileUrl": profile_url,
            "status": status,
            "error": error,
            "dateKey": today_key(),
            "invitedAt": utc_now() if status in ["sent", "already_connected", "already_pending"] else None,
            "postLikeEnabled": post_like_enabled,
            "postLiked": post_liked,
            "postLikedAt": utc_now() if post_liked else None,
            "postLikeStatus": post_like_status,
            "postLikeError": post_like_error,
            "updatedAt": utc_now(),
        }

        client = get_mongo_client()
        client[DB_OUTREACH][COL_INVITES].update_one(
            {"campaignId": campaign_id, "profileUrl": profile_url},
            {
                "$set": doc,
                "$setOnInsert": {"createdAt": utc_now()},
            },
            upsert=True,
        )
        client.close()

    async def preview_people(self, search_url: str, campaign_id: str | None = None, limit: int = 25):
        await self.ensure_browser()

        self.add_log(f"Opening people search URL: {search_url}")

        try:
            await self.page.goto(search_url, wait_until="domcontentloaded")
        except PWTimeout:
            self.add_log("Page load timed out. Continuing with partial page.")
        except Exception as error:
            self.add_log(f"Could not open search URL: {error}")
            return []

        await self.human_pause(4.0, 6.0)

        for _ in range(3):
            await self.page.mouse.wheel(0, random.randint(600, 1100))
            await self.human_pause(1.0, 2.0)

        if await self.should_stop_for_linkedin_warning("people preview"):
            return []

        people = await self.page.evaluate(
            """
            (limit) => {
                const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim();

                const cleanName = (text) => {
                    text = normalize(text);
                    text = text.replace(/^View\\s+/i, '');
                    text = text.replace(/'s profile$/i, '');
                    text = text.replace(/’s profile$/i, '');
                    return text;
                };

                const results = [];
                const seen = new Set();

                const cardSelectors = [
                    'li.reusable-search__result-container',
                    'div.entity-result',
                    'li[data-chameleon-result-urn]',
                    '.reusable-search__result-container',
                    '[class*="entity-result"]'
                ];

                let cards = [];

                for (const selector of cardSelectors) {
                    cards = Array.from(document.querySelectorAll(selector));
                    if (cards.length) break;
                }

                if (!cards.length) {
                    cards = Array.from(document.querySelectorAll('a[href*="/in/"]'))
                        .map(a => a.closest('li, div'))
                        .filter(Boolean);
                }

                for (const card of cards) {
                    if (results.length >= limit) break;

                    const link = card.querySelector('a[href*="/in/"]');
                    if (!link) continue;

                    const profileUrl = (link.href || '').split('?')[0];
                    if (!profileUrl || seen.has(profileUrl)) continue;
                    seen.add(profileUrl);

                    let name = '';

                    const nameSelectors = [
                        '.entity-result__title-text span[aria-hidden="true"]',
                        '.app-aware-link span[aria-hidden="true"]',
                        'span[aria-hidden="true"]',
                        '.entity-result__title-text',
                        'a[href*="/in/"]'
                    ];

                    for (const selector of nameSelectors) {
                        const el = card.querySelector(selector);
                        const candidate = cleanName(el ? el.innerText : '');
                        if (
                            candidate &&
                            candidate.length <= 80 &&
                            !candidate.toLowerCase().includes('linkedin member') &&
                            !candidate.toLowerCase().includes('view profile')
                        ) {
                            name = candidate;
                            break;
                        }
                    }

                    if (!name) {
                        name = cleanName(link.getAttribute('aria-label') || link.innerText || '');
                    }

                    const headlineEl = card.querySelector(
                        '.entity-result__primary-subtitle, [class*="primary-subtitle"], [class*="subtitle"]'
                    );

                    const locationEl = card.querySelector(
                        '.entity-result__secondary-subtitle, [class*="secondary-subtitle"]'
                    );

                    const buttons = Array.from(card.querySelectorAll('button'));
                    const connectButton = buttons.find(btn => {
                        const text = normalize(btn.innerText).toLowerCase();
                        const aria = normalize(btn.getAttribute('aria-label')).toLowerCase();
                        return text === 'connect' || aria.includes('connect') || aria.includes('invite');
                    });

                    const pendingButton = buttons.find(btn => {
                        const text = normalize(btn.innerText).toLowerCase();
                        const aria = normalize(btn.getAttribute('aria-label')).toLowerCase();
                        return text === 'pending' || aria.includes('pending');
                    });

                    results.push({
                        name,
                        headline: headlineEl ? normalize(headlineEl.innerText) : '',
                        location: locationEl ? normalize(locationEl.innerText) : '',
                        profileUrl,
                        canConnect: Boolean(connectButton),
                        isPending: Boolean(pendingButton),
                    });
                }

                return results;
            }
            """,
            limit,
        )

        cleaned = []
        seen = set()

        for person in people:
            profile_url = normalize_profile_url(person.get("profileUrl", ""))
            if not profile_url or profile_url in seen:
                continue

            seen.add(profile_url)
            person["profileUrl"] = profile_url
            cleaned.append(person)

            if campaign_id:
                self.save_profile(campaign_id, person)

        self.add_log(f"Preview found {len(cleaned)} people.")
        return cleaned

    async def click_connect_for_profile(self, profile_url: str):
        if await self.should_stop_for_linkedin_warning("before connect"):
            return False, "linkedin_safety_stop"

        await self.human_pause(2.0, 4.0)

        connect_button = await self.find_button_by_text(["connect"])

        if not connect_button:
            more_button = await self.find_button_by_text(["more"])
            if more_button:
                try:
                    await more_button.click()
                    await self.human_pause(1.0, 2.0)
                    connect_button = await self.find_button_by_text(["connect"])
                except Exception:
                    pass

        if not connect_button:
            body_text = await self.page_text()

            if "pending" in body_text:
                return False, "already_pending"

            if "message" in body_text and ("1st" in body_text or "1st degree" in body_text):
                return False, "possibly_already_connected"

            return False, "connect_button_not_found"

        try:
            await connect_button.scroll_into_view_if_needed()
            await self.human_pause(0.8, 1.5)
            await connect_button.click()
            await self.human_pause(1.5, 3.0)
        except Exception as error:
            return False, f"connect_click_failed:{error}"

        if await self.should_stop_for_linkedin_warning("after connect click"):
            return False, "linkedin_safety_stop"

        send_button = await self.find_button_by_text(["send", "send now"])

        if send_button:
            try:
                await send_button.click()
                await self.human_pause(1.5, 3.0)
                return True, "sent"
            except Exception as error:
                return False, f"send_click_failed:{error}"

        body_text = await self.page_text()

        if "invitation sent" in body_text or "pending" in body_text:
            return True, "sent"

        await self.close_dialog_if_open()

        return False, "send_button_not_found"

    async def like_recent_post_on_profile(self, profile_url: str):
        try:
            recent_activity_url = profile_url.rstrip("/") + "/recent-activity/all/"

            self.add_log(f"Opening recent activity: {recent_activity_url}")

            try:
                await self.page.goto(recent_activity_url, wait_until="domcontentloaded")
            except Exception:
                await self.page.goto(profile_url, wait_until="domcontentloaded")

            await self.human_pause(4.0, 6.0)

            for _ in range(3):
                await self.page.mouse.wheel(0, random.randint(700, 1200))
                await self.human_pause(1.0, 2.0)

            if await self.should_stop_for_linkedin_warning("post like"):
                return {
                    "liked": False,
                    "status": "linkedin_safety_stop",
                    "error": None,
                }

            buttons = await self.page.query_selector_all("button")

            for button in buttons:
                try:
                    aria_label = (await button.get_attribute("aria-label") or "").lower()
                    text = ""

                    try:
                        text = (await button.inner_text()).strip().lower()
                    except Exception:
                        pass

                    if "unlike" in aria_label or text == "liked":
                        return {
                            "liked": False,
                            "status": "already_liked",
                            "error": None,
                        }

                    is_like_button = (
                        aria_label.startswith("react like") or
                        aria_label.startswith("like ") or
                        aria_label == "like" or
                        text == "like"
                    )

                    if not is_like_button:
                        continue

                    await button.scroll_into_view_if_needed()
                    await self.human_pause(1.0, 2.0)
                    await button.click()
                    await self.human_pause(2.0, 3.5)

                    return {
                        "liked": True,
                        "status": "liked",
                        "error": None,
                    }

                except Exception:
                    continue

            return {
                "liked": False,
                "status": "no_recent_post_or_like_button_found",
                "error": None,
            }

        except Exception as error:
            return {
                "liked": False,
                "status": "failed",
                "error": str(error),
            }

    async def start_outreach(self, campaign_id: str, search_url: str, daily_limit: int = 10):
        if self.running:
            return {
                "ok": False,
                "message": "Outreach is already running.",
            }

        self.running = True
        self.stop_requested = False

        daily_limit = min(max(daily_limit, 1), 10)
        campaign = self.get_campaign(campaign_id)
        like_post_after_invite = bool(campaign.get("likePostAfterInvite")) if campaign else False

        self.update_campaign_status(campaign_id, "running")

        if like_post_after_invite:
            self.add_log("Post-like after invite is enabled.")
        else:
            self.add_log("Post-like after invite is disabled.")

        sent_today = self.get_sent_today_count(campaign_id)
        remaining_today = max(daily_limit - sent_today, 0)

        self.add_log(f"Daily invite limit selected by user: {daily_limit}")
        self.add_log(f"Already counted today: {sent_today}")
        self.add_log(f"Remaining today: {remaining_today}")

        if remaining_today <= 0:
            self.running = False
            self.update_campaign_status(campaign_id, "daily_limit_reached")
            return {
                "ok": True,
                "message": "Daily invite limit already reached.",
                "sent": 0,
                "skipped": 0,
                "failed": 0,
            }

        sent_count = 0
        skipped_count = 0
        failed_count = 0
        stop_reason = None

        try:
            people = await self.preview_people(search_url, campaign_id=campaign_id, limit=50)

            if self.stop_requested:
                stop_reason = "Safety stop during preview."
                self.update_campaign_status(campaign_id, "stopped", stop_reason)
                return {
                    "ok": False,
                    "message": stop_reason,
                    "sent": sent_count,
                    "skipped": skipped_count,
                    "failed": failed_count,
                }

            for person in people:
                if self.stop_requested:
                    stop_reason = "Outreach stopped."
                    self.add_log(stop_reason)
                    break

                if sent_count >= remaining_today:
                    stop_reason = "Daily invite limit reached."
                    self.add_log(stop_reason)
                    break

                profile_url = person["profileUrl"]

                if self.already_invited(profile_url):
                    skipped_count += 1
                    self.save_invite(campaign_id, person, "skipped_already_invited")
                    self.add_log(f"Skipped already invited: {person.get('name', profile_url)}")
                    continue

                if person.get("isPending") is True:
                    skipped_count += 1
                    self.save_invite(campaign_id, person, "already_pending")
                    self.add_log(f"Skipped pending invite: {person.get('name', profile_url)}")
                    continue

                self.add_log(f"Opening profile: {person.get('name', profile_url)}")

                try:
                    await self.page.goto(profile_url, wait_until="domcontentloaded")
                    await self.human_pause(3.0, 5.5)

                    if await self.should_stop_for_linkedin_warning("profile open"):
                        stop_reason = "Safety stop after opening profile."
                        break

                    success, status = await self.click_connect_for_profile(profile_url)

                    if self.stop_requested or status == "linkedin_safety_stop":
                        stop_reason = "Safety stop during connect flow."
                        break

                    if success:
                        sent_count += 1

                        post_liked = False
                        post_like_status = None
                        post_like_error = None

                        if like_post_after_invite:
                            self.add_log(f"Trying to like one recent post for {person.get('name', profile_url)}")
                            like_result = await self.like_recent_post_on_profile(profile_url)

                            post_liked = like_result.get("liked") is True
                            post_like_status = like_result.get("status")
                            post_like_error = like_result.get("error")

                            if self.stop_requested or post_like_status == "linkedin_safety_stop":
                                stop_reason = "Safety stop during post-like flow."

                            if post_liked:
                                self.add_log(f"Post liked for {person.get('name', profile_url)}")
                            else:
                                self.add_log(
                                    f"Post like skipped/failed for {person.get('name', profile_url)}: "
                                    f"{post_like_status}"
                                )

                        self.save_invite(
                            campaign_id,
                            person,
                            "sent",
                            post_like_enabled=like_post_after_invite,
                            post_liked=post_liked,
                            post_like_status=post_like_status,
                            post_like_error=post_like_error,
                        )

                        self.add_log(f"Invite sent: {person.get('name', profile_url)}")

                        if stop_reason:
                            break

                    elif status == "possibly_already_connected":
                        skipped_count += 1
                        self.save_invite(campaign_id, person, "already_connected")
                        self.add_log(f"Skipped already connected: {person.get('name', profile_url)}")

                    elif status == "already_pending":
                        skipped_count += 1
                        self.save_invite(campaign_id, person, "already_pending")
                        self.add_log(f"Skipped already pending: {person.get('name', profile_url)}")

                    elif status == "connect_button_not_found":
                        skipped_count += 1
                        self.save_invite(campaign_id, person, "skipped_no_connect_button")
                        self.add_log(f"Skipped no Connect button: {person.get('name', profile_url)}")

                    else:
                        failed_count += 1
                        self.save_invite(campaign_id, person, "failed", status)
                        self.add_log(f"Invite failed for {person.get('name', profile_url)}: {status}")

                    await self.human_pause(12.0, 25.0)

                except Exception as error:
                    failed_count += 1
                    self.save_invite(campaign_id, person, "failed", str(error))
                    self.add_log(f"Error inviting {person.get('name', profile_url)}: {error}")

            if stop_reason:
                self.update_campaign_status(campaign_id, "stopped", stop_reason)
            else:
                self.update_campaign_status(campaign_id, "completed")

            return {
                "ok": True,
                "message": stop_reason or "Outreach completed.",
                "sent": sent_count,
                "skipped": skipped_count,
                "failed": failed_count,
            }

        finally:
            self.running = False

    def stop(self):
        self.stop_requested = True
        return {
            "ok": True,
            "message": "Stop requested.",
        }

    async def check_accepted(self, campaign_id: str, limit: int = 50):
        await self.ensure_browser()

        client = get_mongo_client()
        invites = list(client[DB_OUTREACH][COL_INVITES].find({
            "campaignId": campaign_id,
            "status": "sent",
        }).limit(limit))
        client.close()

        accepted_count = 0

        for invite in invites:
            profile_url = invite.get("profileUrl")
            name = invite.get("name", profile_url)

            if not profile_url:
                continue

            self.add_log(f"Checking acceptance: {name}")

            try:
                await self.page.goto(profile_url, wait_until="domcontentloaded")
                await self.human_pause(3.0, 5.0)

                if await self.should_stop_for_linkedin_warning("accepted check"):
                    break

                body_text = await self.page_text()
                message_button = await self.find_button_by_text(["message"])
                connect_button = await self.find_button_by_text(["connect"])

                accepted = (
                    message_button is not None and
                    connect_button is None and
                    (
                        "1st" in body_text or
                        "1st degree" in body_text or
                        "message" in body_text
                    )
                )

                if accepted:
                    accepted_count += 1

                    client = get_mongo_client()
                    client[DB_OUTREACH][COL_INVITES].update_one(
                        {"_id": invite["_id"]},
                        {
                            "$set": {
                                "status": "accepted",
                                "acceptedAt": utc_now(),
                                "updatedAt": utc_now(),
                            }
                        },
                    )
                    client.close()

                    self.add_log(f"Accepted: {name}")
                else:
                    self.add_log(f"Not accepted yet: {name}")

                await self.human_pause(8.0, 15.0)

            except Exception as error:
                self.add_log(f"Could not check {name}: {error}")

        return {
            "ok": True,
            "checked": len(invites),
            "accepted": accepted_count,
        }

    async def send_first_messages(
        self,
        campaign_id: str,
        message_template: str | None = None,
        confirm_send: bool = False,
        limit: int = 10,
    ):
        if not confirm_send:
            return {
                "ok": False,
                "message": "Message sending requires confirm_send=true.",
            }

        campaign = self.get_campaign(campaign_id)
        if not message_template and campaign:
            message_template = campaign.get("messageTemplate", "")

        if not message_template:
            return {
                "ok": False,
                "message": "Message template is empty.",
            }

        await self.ensure_browser()

        client = get_mongo_client()
        invites = list(client[DB_OUTREACH][COL_INVITES].find({
            "campaignId": campaign_id,
            "status": "accepted",
            "messageSent": {"$ne": True},
        }).limit(limit))
        client.close()

        sent_count = 0
        failed_count = 0

        for invite in invites:
            profile_url = invite.get("profileUrl")
            name = invite.get("name", "")
            first_name = first_name_from_name(name)
            message = message_template.replace("{{first_name}}", first_name).replace("{{name}}", name)

            if not profile_url:
                continue

            self.add_log(f"Opening accepted profile for message: {name}")

            try:
                await self.page.goto(profile_url, wait_until="domcontentloaded")
                await self.human_pause(3.0, 5.0)

                if await self.should_stop_for_linkedin_warning("message sending"):
                    break

                message_button = await self.find_button_by_text(["message"])

                if not message_button:
                    failed_count += 1
                    self.add_log(f"Message button not found for {name}")
                    continue

                await message_button.click()
                await self.human_pause(2.0, 3.0)

                editor = None

                editor_selectors = [
                    'div[contenteditable="true"]',
                    '[role="textbox"]',
                    '.msg-form__contenteditable',
                ]

                for selector in editor_selectors:
                    editor = await self.page.query_selector(selector)
                    if editor:
                        break

                if not editor:
                    failed_count += 1
                    self.add_log(f"Message editor not found for {name}")
                    await self.close_dialog_if_open()
                    continue

                await editor.click()
                await self.page.keyboard.type(message, delay=random.randint(25, 80))
                await self.human_pause(1.0, 2.0)

                send_button = await self.find_button_by_text(["send"])

                if not send_button:
                    failed_count += 1
                    self.add_log(f"Send button not found for {name}")
                    await self.close_dialog_if_open()
                    continue

                await send_button.click()
                await self.human_pause(2.0, 3.0)

                sent_count += 1

                client = get_mongo_client()
                client[DB_OUTREACH][COL_INVITES].update_one(
                    {"_id": invite["_id"]},
                    {
                        "$set": {
                            "messageSent": True,
                            "messageSentAt": utc_now(),
                            "updatedAt": utc_now(),
                        }
                    },
                )
                client[DB_OUTREACH][COL_MESSAGES].insert_one({
                    "campaignId": campaign_id,
                    "profileUrl": profile_url,
                    "name": name,
                    "message": message,
                    "sentAt": utc_now(),
                })
                client.close()

                self.add_log(f"Message sent to {name}")

                await self.human_pause(15.0, 30.0)

            except Exception as error:
                failed_count += 1
                self.add_log(f"Message failed for {name}: {error}")
                await self.close_dialog_if_open()

        return {
            "ok": True,
            "sent": sent_count,
            "failed": failed_count,
        }

    def campaign_stats(self, campaign_id: str):
        client = get_mongo_client()
        invites = client[DB_OUTREACH][COL_INVITES]

        stats = {
            "sent": invites.count_documents({"campaignId": campaign_id, "status": "sent"}),
            "accepted": invites.count_documents({"campaignId": campaign_id, "status": "accepted"}),
            "failed": invites.count_documents({"campaignId": campaign_id, "status": "failed"}),
            "alreadyConnected": invites.count_documents({"campaignId": campaign_id, "status": "already_connected"}),
            "alreadyPending": invites.count_documents({"campaignId": campaign_id, "status": "already_pending"}),
            "skippedNoConnect": invites.count_documents({"campaignId": campaign_id, "status": "skipped_no_connect_button"}),
            "skippedAlreadyInvited": invites.count_documents({"campaignId": campaign_id, "status": "skipped_already_invited"}),
            "messagesSent": invites.count_documents({"campaignId": campaign_id, "messageSent": True}),
            "sentToday": invites.count_documents({
                "campaignId": campaign_id,
                "dateKey": today_key(),
                "status": {"$in": ["sent", "already_connected", "already_pending"]},
            }),
            "postsLiked": invites.count_documents({"campaignId": campaign_id, "postLiked": True}),
        }

        client.close()

        return {
            "ok": True,
            "campaignId": campaign_id,
            "stats": stats,
        }