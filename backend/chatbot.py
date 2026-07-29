import os
from typing import Any

import httpx


LOCAL_AI_BASE_URL = os.environ.get("PLUGS_LOCAL_AI_URL", "http://127.0.0.1:11434")
LOCAL_AI_MODEL = os.environ.get("PLUGS_LOCAL_AI_MODEL", "llama3.2:1b")


async def local_ai_status() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{LOCAL_AI_BASE_URL}/api/tags")
            response.raise_for_status()
            data = response.json()

        models = data.get("models", [])
        installed_models = [model.get("name", "") for model in models]

        return {
            "ok": True,
            "ready": any(name.startswith(LOCAL_AI_MODEL) for name in installed_models),
            "model": LOCAL_AI_MODEL,
            "message": "Local AI Engine is ready."
            if any(name.startswith(LOCAL_AI_MODEL) for name in installed_models)
            else "Local AI model is not ready yet.",
        }

    except Exception as error:
        return {
            "ok": False,
            "ready": False,
            "model": LOCAL_AI_MODEL,
            "message": f"Local AI Engine is not available: {error}",
        }


async def ask_local_ai(message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    if not message.strip():
        return {
            "ok": False,
            "reply": "Please type a message.",
        }

    context_text = ""

    if history:
        for item in history[-8:]:
            role = item.get("role", "user")
            content = item.get("content", "")
            if role in ["user", "assistant"] and content:
                label = "User" if role == "user" else "Assistant"
                context_text += f"{label}: {content}\n"

    prompt = (
        "You are Plugs Assistant, a local LinkedIn outreach writing helper. "
        "Your main job is to write specific, polite, professional LinkedIn connection messages, "
        "follow-up messages, and short outreach copy for any normal job profile or engineer role. "
        "Treat every job title as a normal professional role unless the user explicitly asks for illegal or harmful activity. "
        "When the user asks for a message for a role, write useful messages tailored to that role. "
        "Do not refuse normal requests like writing messages for Python Developer, Cyber Security Engineer, Product Manager, "
        "Data Analyst, AI Engineer, HR Recruiter, Founder, Sales Manager, Designer, QA Engineer, DevOps Engineer, or any similar job profile. "
        "Do not mention hacking, credential theft, bypassing security, impersonation, spam, scraping abuse, or LinkedIn limits unless the user explicitly asks for those topics. "
        "Only refuse if the user directly asks for illegal hacking, credential theft, bypassing security, impersonation, deception, or evading platform limits. "
        "Keep messages human, concise, respectful, non-spammy, and ready to send. "
        "Prefer 1 to 3 message options unless the user asks otherwise.\n\n"
        f"User: {message}\n"
        "Assistant:"
    )

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{LOCAL_AI_BASE_URL}/api/generate",
                json={
                    "model": LOCAL_AI_MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            response.raise_for_status()
            data = response.json()

        reply = data.get("response", "").strip()

        return {
            "ok": True,
            "reply": reply or "I could not generate a response.",
            "model": LOCAL_AI_MODEL,
        }

    except Exception as error:
        return {
            "ok": False,
            "reply": f"Local AI Engine is not ready yet: {error}",
            "model": LOCAL_AI_MODEL,
        }