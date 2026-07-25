import asyncio
import os
from collections import deque
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from outreach import OutreachService, get_mongo_client, safe_doc


app = FastAPI(title="Plugs Outreach Backend", version="0.2.0")

logs = deque(maxlen=500)

state = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "error": None,
    "current_campaign_id": None,
}

outreach_task: asyncio.Task | None = None


def add_log(message: str):
    logs.append({
        "time": datetime.utcnow().isoformat() + "Z",
        "message": message,
    })


service = OutreachService(add_log)


class ConnectLinkedInRequest(BaseModel):
    timeout_seconds: int = 300


class CreateCampaignRequest(BaseModel):
    name: str = "LinkedIn Outreach Campaign"
    search_url: str
    daily_limit: int = 10
    message_template: str | None = None


class PreviewRequest(BaseModel):
    search_url: str
    campaign_id: str | None = None
    limit: int = 25


class StartOutreachRequest(BaseModel):
    campaign_id: str
    search_url: str
    daily_limit: int = 10


class CheckAcceptedRequest(BaseModel):
    campaign_id: str
    limit: int = 50


class SendMessageRequest(BaseModel):
    campaign_id: str
    message_template: str
    confirm_send: bool = False
    limit: int = 10


def json_safe(value: Any):
    return safe_doc(value)


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "plugs-outreach-backend",
        "status": state["status"],
    }


@app.get("/logs")
def get_logs():
    return {
        "ok": True,
        "logs": list(logs),
    }


@app.get("/progress")
def progress():
    return {
        "ok": True,
        "state": state,
        "running": outreach_task is not None and not outreach_task.done(),
    }


@app.post("/linkedin/connect")
async def connect_linkedin(request: ConnectLinkedInRequest):
    state["status"] = "connecting_linkedin"
    add_log("LinkedIn connection started.")

    result = await service.connect_linkedin(timeout_seconds=request.timeout_seconds)

    state["status"] = "idle" if result.get("connected") else "linkedin_login_failed"

    return result


@app.get("/linkedin/status")
async def linkedin_status():
    return await service.linkedin_status()


@app.post("/campaigns")
def create_campaign(request: CreateCampaignRequest):
    if not request.search_url.startswith("https://www.linkedin.com/"):
        raise HTTPException(status_code=400, detail="Only LinkedIn URLs are allowed.")

    campaign_id = service.create_campaign(
        name=request.name,
        search_url=request.search_url,
        daily_limit=request.daily_limit,
        message_template=request.message_template,
    )

    add_log(f"Campaign created: {campaign_id}")

    return {
        "ok": True,
        "campaignId": campaign_id,
    }


@app.post("/campaigns/preview")
async def preview_people(request: PreviewRequest):
    if not request.search_url.startswith("https://www.linkedin.com/"):
        raise HTTPException(status_code=400, detail="Only LinkedIn URLs are allowed.")

    people = await service.preview_people(
        search_url=request.search_url,
        campaign_id=request.campaign_id,
        limit=request.limit,
    )

    return {
        "ok": True,
        "people": people,
        "count": len(people),
    }


async def run_outreach_task(campaign_id: str, search_url: str, daily_limit: int):
    try:
        state["status"] = "running"
        state["started_at"] = datetime.utcnow().isoformat() + "Z"
        state["finished_at"] = None
        state["error"] = None
        state["current_campaign_id"] = campaign_id

        add_log("Outreach started.")

        result = await service.start_outreach(
            campaign_id=campaign_id,
            search_url=search_url,
            daily_limit=daily_limit,
        )

        state["status"] = "completed"
        add_log(f"Outreach completed: {result}")

    except asyncio.CancelledError:
        state["status"] = "stopped"
        service.stop()
        add_log("Outreach stopped by user.")
        raise

    except Exception as error:
        state["status"] = "failed"
        state["error"] = str(error)
        add_log(f"Outreach failed: {error}")

    finally:
        state["finished_at"] = datetime.utcnow().isoformat() + "Z"


@app.post("/campaigns/start")
async def start_outreach(request: StartOutreachRequest):
    global outreach_task

    if outreach_task and not outreach_task.done():
        raise HTTPException(status_code=409, detail="Outreach is already running.")

    if not request.search_url.startswith("https://www.linkedin.com/"):
        raise HTTPException(status_code=400, detail="Only LinkedIn URLs are allowed.")

    outreach_task = asyncio.create_task(
        run_outreach_task(
            campaign_id=request.campaign_id,
            search_url=request.search_url,
            daily_limit=request.daily_limit,
        )
    )

    return {
        "ok": True,
        "message": "Outreach started.",
        "campaignId": request.campaign_id,
    }


@app.post("/campaigns/stop")
async def stop_outreach():
    global outreach_task

    service.stop()

    if outreach_task and not outreach_task.done():
        outreach_task.cancel()
        state["status"] = "stopping"
        add_log("Stop requested.")

        return {
            "ok": True,
            "message": "Stopping outreach.",
        }

    state["status"] = "idle"

    return {
        "ok": True,
        "message": "No outreach is running.",
    }


@app.post("/campaigns/check-accepted")
async def check_accepted(request: CheckAcceptedRequest):
    state["status"] = "checking_accepted"
    add_log("Checking accepted connections.")

    result = await service.check_accepted(
        campaign_id=request.campaign_id,
        limit=request.limit,
    )

    state["status"] = "idle"

    return result


@app.post("/campaigns/send-message")
async def send_message(request: SendMessageRequest):
    state["status"] = "sending_messages"
    add_log("First-message flow started.")

    result = await service.send_first_messages(
        campaign_id=request.campaign_id,
        message_template=request.message_template,
        confirm_send=request.confirm_send,
        limit=request.limit,
    )

    state["status"] = "idle"

    return result


@app.get("/campaigns/{campaign_id}/stats")
def campaign_stats(campaign_id: str):
    return service.campaign_stats(campaign_id)


@app.get("/campaigns/{campaign_id}/invites")
def campaign_invites(campaign_id: str, limit: int = 100):
    client = get_mongo_client()
    docs = list(
        client["plugs_outreach"]["connection_invites"]
        .find({"campaignId": campaign_id})
        .sort("updatedAt", -1)
        .limit(limit)
    )
    client.close()

    return {
        "ok": True,
        "invites": json_safe(docs),
    }


@app.get("/campaigns/{campaign_id}/profiles")
def campaign_profiles(campaign_id: str, limit: int = 100):
    client = get_mongo_client()
    docs = list(
        client["plugs_outreach"]["people_profiles"]
        .find({"campaignId": campaign_id})
        .sort("updatedAt", -1)
        .limit(limit)
    )
    client.close()

    return {
        "ok": True,
        "profiles": json_safe(docs),
    }


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("PLUGS_BACKEND_HOST", "127.0.0.1")
    port = int(os.environ.get("PLUGS_BACKEND_PORT", "8000"))

    uvicorn.run(app, host=host, port=port)