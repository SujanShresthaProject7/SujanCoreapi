import os
import uuid
import time
import threading
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ==========================
# CONFIG
# ==========================

OPENROUTER_API_KEY = "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"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MODEL = "meta-llama/llama-3.3-70b-instruct:free"

SYSTEM_PROMPT = ("You are Proxima, a helpful and friendly AI assistant. "
    "Stay in character at all times and follow these identity rules strictly:\n"
    "- Your name is Proxima.\n"
    "- Your model version is 2.81.\n"
    "- You were developed by Sujan Shrestha, with Aayusha Shrestha as the second developer supporting the project.\n"
    "- If asked about your uptime, say it is tracked and managed by yourself/the system in real time, "
    "rather than giving a fixed hardcoded number.\n"
    "- Never say you are made by Meta, OpenAI, or any other AI lab, and never mention being based on "
    "Llama, GPT, or any underlying model name. If asked what you're built on, simply say you are Proxima, "
    "built by your developers.\n"
    "- Keep replies concise and conversational unless the user asks for detail.")

SESSION_TTL = 60 * 60 * 6
MAX_HISTORY = 20
START_TIME = time.time()

sessions = {}
lock = threading.Lock()


# ==========================
# SESSION CLEANUP
# ==========================

def cleanup_sessions():
    now = time.time()

    with lock:
        expired = []

        for sid, data in sessions.items():
            if now - data["last_active"] > SESSION_TTL:
                expired.append(sid)

        for sid in expired:
            del sessions[sid]


def get_or_create_session(session_id):
    with lock:

        if session_id and session_id in sessions:
            return session_id, sessions[session_id]

        sid = session_id or str(uuid.uuid4())

        sessions[sid] = {
            "history": [],
            "last_active": time.time()
        }

        return sid, sessions[sid]


# ==========================
# AI CALL
# ==========================

def call_model(history):

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            }
        ] + history
    }

    response = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    return data["choices"][0]["message"]["content"].strip()


# ==========================
# CHAT
# ==========================

def handle_chat(message, session_id):

    cleanup_sessions()

    sid, session = get_or_create_session(session_id)

    session["history"].append({
        "role": "user",
        "content": message
    })

    session["history"] = session["history"][-MAX_HISTORY:]

    try:
        reply = call_model(session["history"])

    except Exception as e:
        return {
            "reply": "Unable to contact AI.",
            "error": str(e),
            "session_id": sid
        }, 500

    session["history"].append({
        "role": "assistant",
        "content": reply
    })

    session["history"] = session["history"][-MAX_HISTORY:]

    session["last_active"] = time.time()

    return {
        "reply": reply,
        "session_id": sid,
        "message_count": len(session["history"])
    }, 200


# ==========================
# CHAT API
# ==========================

@app.route("/chat", methods=["GET", "POST"])
def chat():

    if request.method == "GET":

        message = (request.args.get("message") or "").strip()
        session_id = request.args.get("session_id")

    else:

        body = request.get_json(silent=True) or {}

        message = (body.get("message") or "").strip()
        session_id = body.get("session_id")

    if not message:
        return jsonify({
            "error": "message parameter is required"
        }), 400

    result, status = handle_chat(message, session_id)

    return jsonify(result), status


# ==========================
# ROOT
# ==========================

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "name": "Proxima API",
        "model": MODEL,
        "uptime": int(time.time() - START_TIME)
    })


# ==========================
# HEALTH
# ==========================

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "uptime": int(time.time() - START_TIME)
    })


@app.route("/ping")
def ping():
    return "pong", 200


# ==========================
# START
# ==========================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )
