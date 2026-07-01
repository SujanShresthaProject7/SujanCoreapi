import os
import uuid
import time
import threading

from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY = "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"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.environ.get("MODEL", "openai/gpt-4o")
# OpenRouter uses these to attribute/rank traffic from your app (optional but recommended).
SITE_URL = os.environ.get("SITE_URL", "")
SITE_NAME = os.environ.get("SITE_NAME", "")

SYSTEM_PROMPT = (
    "You are Proxima, a helpful and friendly AI assistant. "
    "Stay in character at all times and follow these identity rules strictly:\n"
    "- Your name is Proxima.\n"
    "- Your model version is 2.81.\n"
    "- You were developed by Sujan Shrestha, with Aayusha Shrestha as the second developer supporting the project.\n"
    "- If asked about your uptime, say it is tracked and managed by yourself/the system in real time, "
    "rather than giving a fixed hardcoded number.\n"
    "- Never say you are made by Meta, OpenAI, or any other AI lab, and never mention being based on "
    "Llama, GPT, or any underlying model name. If asked what you're built on, simply say you are Proxima, "
    "built by your developers.\n"
    "- Keep replies concise and conversational unless the user asks for detail."
)

# How long a session is kept in memory before it's dropped (seconds).
SESSION_TTL = 60 * 60 * 6  # 6 hours

# Real process start time, used to give Proxima an accurate, live uptime
# instead of a made-up or hardcoded number.
START_TIME = time.time()


def get_uptime_string():
    seconds = int(time.time() - START_TIME)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)

# ---------------------------------------------------------------------------
# In-memory session store
# sessions[session_id] = {"history": [...], "last_active": ts}
# ---------------------------------------------------------------------------
sessions = {}
lock = threading.Lock()


def cleanup_sessions():
    now = time.time()
    with lock:
        expired = [sid for sid, s in sessions.items() if now - s["last_active"] > SESSION_TTL]
        for sid in expired:
            del sessions[sid]


def get_or_create_session(session_id):
    with lock:
        if session_id and session_id in sessions:
            return session_id, sessions[session_id]
        new_id = session_id or str(uuid.uuid4())
        sessions[new_id] = {"history": [], "last_active": time.time()}
        return new_id, sessions[new_id]


def call_model(history):
    """Call OpenRouter's chat completions endpoint with the full conversation."""
    if not OPENROUTER_API_KEY:
        return "I'm not configured with a model API key yet (set OPENROUTER_API_KEY)."

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Current live uptime (real, since this server process started): {get_uptime_string()}."},
    ] + history

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    if SITE_URL:
        headers["HTTP-Referer"] = SITE_URL
    if SITE_NAME:
        headers["X-Title"] = SITE_NAME

    resp = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 512,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def handle_chat(message, session_id):
    if not message:
        return {"error": "Missing 'message' parameter."}, 400

    cleanup_sessions()
    session_id, session = get_or_create_session(session_id)

    session["history"].append({"role": "user", "content": message})

    try:
        reply = call_model(session["history"])
    except requests.exceptions.RequestException as e:
        reply = f"Sorry, I had trouble reaching the model right now. ({e})"

    session["history"].append({"role": "assistant", "content": reply})
    session["last_active"] = time.time()

    return {
        "reply": reply,
        "session_id": session_id,
        "message_count": len(session["history"]),
    }, 200


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/chat", methods=["GET", "POST"])
def chat():
    if request.method == "GET":
        message = request.args.get("message", "").strip()
        session_id = request.args.get("session_id")
    else:
        body = request.get_json(silent=True) or {}
        message = (body.get("message") or "").strip()
        session_id = body.get("session_id")

    result, status = handle_chat(message, session_id)
    return jsonify(result), status


@app.route("/reset", methods=["POST"])
def reset():
    body = request.get_json(silent=True) or {}
    session_id = body.get("session_id")
    with lock:
        if session_id in sessions:
            del sessions[session_id]
    return jsonify({"status": "ok"}), 200


@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "name": "Proxima",
        "model": "2.81",
        "developer": "Sujan Shrestha",
        "second_developer": "Aayusha Shrestha",
        "uptime": get_uptime_string(),
        "active_sessions": len(sessions),
    }), 200


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "ok",
        "usage": "/chat?message=hi (optionally &session_id=<id> to continue a conversation)",
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
