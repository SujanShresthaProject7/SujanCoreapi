import os
import uuid
import time
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

OPENROUTER_API_KEY="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"
OPENROUTER_URL="https://openrouter.ai/api/v1/chat/completions"
MODEL=os.environ.get("MODEL","openai/gpt-4o")
SYSTEM_PROMPT=("You are Proxima, a helpful and friendly AI assistant. "
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

SESSION_TTL=60*60*6
START_TIME=time.time()
sessions={}
lock=threading.Lock()

def cleanup_sessions():
    now=time.time()
    with lock:
        for sid in list(sessions):
            if now-sessions[sid]["last_active"]>SESSION_TTL:
                del sessions[sid]

def get_or_create_session(session_id):
    with lock:
        if session_id and session_id in sessions:
            return session_id,sessions[session_id]
        sid=session_id or str(uuid.uuid4())
        sessions[sid]={"history":[],"last_active":time.time()}
        return sid,sessions[sid]

def call_model(history):
    headers={"Authorization":f"Bearer {OPENROUTER_API_KEY}","Content-Type":"application/json"}
    r=requests.post(OPENROUTER_URL,headers=headers,json={
        "model":MODEL,
        "messages":[{"role":"system","content":SYSTEM_PROMPT}]+history
    },timeout=30)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

def handle_chat(message,session_id):
    cleanup_sessions()
    sid,s=get_or_create_session(session_id)
    s["history"].append({"role":"user","content":message})
    try:
        reply=call_model(s["history"])
    except Exception as e:
        reply=f"Sorry, I had trouble reaching the model. ({e})"
    s["history"].append({"role":"assistant","content":reply})
    s["last_active"]=time.time()
    return {"reply":reply,"session_id":sid,"message_count":len(s["history"])},200

@app.route("/chat",methods=["POST"])
def chat():
    body=request.get_json(silent=True) or {}
    result,status=handle_chat((body.get("message") or "").strip(),body.get("session_id"))
    return jsonify(result),status

@app.route("/")
def index():
    return jsonify({"status":"ok"})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)))
