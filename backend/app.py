import contextlib
import os
import asyncio
from collections import deque
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

try:
    import scraper
except ImportError:
    from . import scraper


app = FastAPI(title="Plugs Backend", version="0.1.0")

logs = deque(maxlen=300)
scrape_task: asyncio.Task | None = None

state = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "error": None,
}


class StartRequest(BaseModel):
    search_urls: list[str] | None = None

class LogWriter:
    def __init__(self):
        self.buffer = ""

    def write(self, text: str):
        if not text:
            return

        self.buffer += text

        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            line = line.strip()

            if line:
                add_log(line)

    def flush(self):
        if self.buffer.strip():
            add_log(self.buffer.strip())
            self.buffer = ""

def add_log(message: str):
    logs.append({
        "time": datetime.utcnow().isoformat() + "Z",
        "message": message,
    })


def json_safe(value: Any):
    if isinstance(value, list):
        return [json_safe(item) for item in value]

    if isinstance(value, dict):
        return {key: json_safe(val) for key, val in value.items()}

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    return str(value)


async def run_scraper(search_urls: list[str] | None):
    global scrape_task

    state["status"] = "running"
    state["started_at"] = datetime.utcnow().isoformat() + "Z"
    state["finished_at"] = None
    state["error"] = None

    add_log("Scraper started.")

    log_writer = LogWriter()

    try:
        with contextlib.redirect_stdout(log_writer), contextlib.redirect_stderr(log_writer):
            await scraper.main(search_urls=search_urls)

        state["status"] = "completed"
        add_log("Scraper completed.")

    except asyncio.CancelledError:
        state["status"] = "stopped"
        add_log("Scraper stopped by user.")
        raise

    except Exception as error:
        state["status"] = "failed"
        state["error"] = str(error)
        add_log(f"Scraper failed: {error}")

    finally:
        log_writer.flush()
        state["finished_at"] = datetime.utcnow().isoformat() + "Z"
        scrape_task = None


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "plugs-backend",
        "status": state["status"],
    }


@app.post("/start")
async def start(request: StartRequest):
    global scrape_task

    if scrape_task and not scrape_task.done():
        raise HTTPException(status_code=409, detail="Scraper is already running.")

    scrape_task = asyncio.create_task(run_scraper(request.search_urls))

    return {
        "ok": True,
        "message": "Scraper started.",
        "status": state["status"],
    }


@app.post("/stop")
async def stop():
    global scrape_task

    if not scrape_task or scrape_task.done():
        state["status"] = "idle"
        return {
            "ok": True,
            "message": "No scraper is running.",
            "status": state["status"],
        }

    state["status"] = "stopping"
    add_log("Stop requested.")
    scrape_task.cancel()

    return {
        "ok": True,
        "message": "Stopping scraper.",
        "status": state["status"],
    }


@app.get("/progress")
def progress():
    return {
        "ok": True,
        "state": state,
        "running": scrape_task is not None and not scrape_task.done(),
    }


@app.get("/logs")
def get_logs():
    return {
        "ok": True,
        "logs": list(logs),
    }


@app.get("/results")
def get_results(limit: int = 50):
    try:
        client = scraper.get_mongo_client()
        collection = client[scraper.DB_LEADS][scraper.COL_REQUIREMENTS]
        docs = list(collection.find().sort("scraped_at", -1).limit(limit))
        client.close()

        return {
            "ok": True,
            "results": json_safe(docs),
        }
    except Exception as error:
        return {
            "ok": False,
            "error": str(error),
            "results": [],
        }


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("PLUGS_BACKEND_HOST", "127.0.0.1")
    port = int(os.environ.get("PLUGS_BACKEND_PORT", "8000"))

    uvicorn.run(app, host=host, port=port)
