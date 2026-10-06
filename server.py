#!/usr/bin/env python3
"""My AI — self-contained server with Groq API, JSON auth & chat storage."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PORT = int(os.environ.get("PORT", "8080"))
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
USERS_FILE = DATA / "users.json"
CHATS_FILE = DATA / "chats.json"
SESSIONS_FILE = DATA / "sessions.json"
STATIC_EXTS = {".html", ".css", ".js", ".png", ".jpg", ".svg", ".ico", ".woff2", ".json"}

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
SESSION_TTL = 60 * 60 * 24 * 30  # 30 days
COOKIE_NAME = "myai_session"


def load_dotenv():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
    global GROQ_API_KEY, GROQ_MODEL
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
    GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()


load_dotenv()
DATA.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# JSON storage helpers
# ---------------------------------------------------------------------------
def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def get_users() -> dict:
    return _read_json(USERS_FILE, {})


def save_users(users: dict) -> None:
    _write_json(USERS_FILE, users)


def get_chats_db() -> dict:
    return _read_json(CHATS_FILE, {})


def save_chats_db(db: dict) -> None:
    _write_json(CHATS_FILE, db)


def get_sessions() -> dict:
    return _read_json(SESSIONS_FILE, {})


def save_sessions(sessions: dict) -> None:
    _write_json(SESSIONS_FILE, sessions)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return salt, digest.hex()


def verify_password(password: str, salt: str, stored_hash: str) -> bool:
    _, check = hash_password(password, salt)
    return hmac.compare_digest(check, stored_hash)


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    sessions = get_sessions()
    sessions[token] = {"user_id": user_id, "created": time.time()}
    # prune expired
    now = time.time()
    sessions = {k: v for k, v in sessions.items() if now - v.get("created", 0) < SESSION_TTL}
    sessions[token] = {"user_id": user_id, "created": time.time()}
    save_sessions(sessions)
    return token


def resolve_session(token: str | None) -> dict | None:
    if not token:
        return None
    sessions = get_sessions()
    entry = sessions.get(token)
    if not entry:
        return None
    if time.time() - entry.get("created", 0) > SESSION_TTL:
        sessions.pop(token, None)
        save_sessions(sessions)
        return None
    users = get_users()
    user = users.get(entry["user_id"])
    if not user:
        return None
    return {
        "id": entry["user_id"],
        "name": user.get("name", "User"),
        "email": user.get("email", ""),
    }


def destroy_session(token: str | None) -> None:
    if not token:
        return
    sessions = get_sessions()
    sessions.pop(token, None)
    save_sessions(sessions)


# ---------------------------------------------------------------------------
# Chat helpers
# ---------------------------------------------------------------------------
def user_chats(user_id: str) -> list:
    db = get_chats_db()
    chats = db.get(user_id, {}).get("chats", [])
    return sorted(chats, key=lambda c: c.get("updatedAt", ""), reverse=True)


def get_chat(user_id: str, chat_id: str) -> dict | None:
    db = get_chats_db()
    for chat in db.get(user_id, {}).get("chats", []):
        if chat["id"] == chat_id:
            return chat
    return None


def save_chat(user_id: str, chat: dict) -> None:
    db = get_chats_db()
    bucket = db.setdefault(user_id, {"chats": []})
    chats = bucket["chats"]
    for i, c in enumerate(chats):
        if c["id"] == chat["id"]:
            chats[i] = chat
            break
    else:
        chats.insert(0, chat)
    save_chats_db(db)


def delete_chat(user_id: str, chat_id: str) -> bool:
    db = get_chats_db()
    bucket = db.get(user_id)
    if not bucket:
        return False
    before = len(bucket["chats"])
    bucket["chats"] = [c for c in bucket["chats"] if c["id"] != chat_id]
    save_chats_db(db)
    return len(bucket["chats"]) < before


def clear_all_chats(user_id: str) -> None:
    db = get_chats_db()
    if user_id in db:
        db[user_id]["chats"] = []
        save_chats_db(db)


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------
def call_groq(messages: list[dict]) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is missing. Create a .env file with GROQ_API_KEY=your_key"
        )
    payload = json.dumps({
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096,
    }).encode()
    req = Request(
        GROQ_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "MyAI/1.0 (compatible; +https://github.com/local/myai)",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode())
    except HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code == 403 and "1010" in body:
            raise RuntimeError(
                "Groq blocked the request (Cloudflare 1010). "
                "Restart the server after updating — User-Agent is now set. "
                "If it continues, check GROQ_API_KEY in .env"
            ) from e
        try:
            err = json.loads(body).get("error", {})
            msg = err.get("message") if isinstance(err, dict) else body
        except Exception:
            msg = body or str(e)
        raise RuntimeError(f"Groq API error ({e.code}): {msg}") from e
    except URLError as e:
        raise RuntimeError(f"Cannot reach Groq API: {e.reason}") from e

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Groq returned empty response")
    return choices[0]["message"]["content"]


SYSTEM_PROMPT = (
    "You are My AI — a sharp, calm, helpful assistant. "
    "Answer clearly. Use markdown when useful (code blocks, lists, headings). "
    "Be concise unless the user asks for depth."
)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")

    # -- helpers --
    def _json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode())
        except Exception:
            return {}

    def _cookie_token(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        if not raw:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        morsel = cookie.get(COOKIE_NAME)
        return morsel.value if morsel else None

    def _set_session_cookie(self, token: str):
        self.send_header(
            "Set-Cookie",
            f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL}",
        )

    def _clear_session_cookie(self):
        self.send_header(
            "Set-Cookie",
            f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        )

    def _current_user(self):
        return resolve_session(self._cookie_token())

    def _require_user(self):
        user = self._current_user()
        if not user:
            self._json(401, {"error": "Not authenticated"})
            return None
        return user

    # -- routing --
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/auth/me":
            return self._auth_me()
        if path == "/api/chats":
            return self._list_chats()
        if path.startswith("/api/chats/"):
            return self._get_chat(path.split("/api/chats/", 1)[1])
        if path in ("/", "/index.html"):
            return self._serve_index()
        # static
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/auth/register":
            return self._register()
        if path == "/api/auth/login":
            return self._login()
        if path == "/api/auth/demo-login":
            return self._demo_login()
        if path == "/api/auth/logout":
            return self._logout()
        if path == "/api/chats":
            return self._create_chat()
        if path == "/chat":
            return self._chat()
        self._json(404, {"error": "Not found"})

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if path == "/api/chats":
            return self._clear_chats()
        if path.startswith("/api/chats/"):
            return self._delete_chat(path.split("/api/chats/", 1)[1])
        self._json(404, {"error": "Not found"})

    def _serve_index(self):
        index = ROOT / "index.html"
        data = index.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- auth endpoints --
    def _auth_me(self):
        user = self._current_user()
        self._json(200, {
            "user": user,
            "demoAvailable": True,
            "groqConfigured": bool(GROQ_API_KEY),
        })

    def _register(self):
        body = self._read_body()
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        name = str(body.get("name", "")).strip() or email.split("@")[0] or "User"
        if not email or not password:
            return self._json(400, {"error": "Email and password required"})
        if len(password) < 4:
            return self._json(400, {"error": "Password must be at least 4 characters"})
        users = get_users()
        for uid, u in users.items():
            if u.get("email") == email:
                return self._json(409, {"error": "Account already exists — please sign in"})
        user_id = str(uuid.uuid4())
        salt, pw_hash = hash_password(password)
        users[user_id] = {
            "email": email,
            "name": name,
            "salt": salt,
            "password_hash": pw_hash,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        save_users(users)
        token = create_session(user_id)
        body_out = json.dumps({
            "user": {"id": user_id, "name": name, "email": email},
            "ok": True,
        }).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_out)))
        self._set_session_cookie(token)
        self.end_headers()
        self.wfile.write(body_out)

    def _login(self):
        body = self._read_body()
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        if not email or not password:
            return self._json(400, {"error": "Email and password required"})
        users = get_users()
        found_id = None
        found = None
        for uid, u in users.items():
            if u.get("email") == email:
                found_id, found = uid, u
                break
        if not found or not verify_password(password, found["salt"], found["password_hash"]):
            return self._json(401, {"error": "Invalid email or password"})
        token = create_session(found_id)
        out = json.dumps({
            "user": {"id": found_id, "name": found["name"], "email": found["email"]},
            "ok": True,
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self._set_session_cookie(token)
        self.end_headers()
        self.wfile.write(out)

    def _demo_login(self):
        users = get_users()
        demo_id = "demo-user"
        if demo_id not in users:
            salt, pw_hash = hash_password(secrets.token_hex(8))
            users[demo_id] = {
                "email": "demo@myai.local",
                "name": "Demo User",
                "salt": salt,
                "password_hash": pw_hash,
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "demo": True,
            }
            save_users(users)
        token = create_session(demo_id)
        out = json.dumps({
            "user": {"id": demo_id, "name": "Demo User", "email": "demo@myai.local"},
            "ok": True,
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self._set_session_cookie(token)
        self.end_headers()
        self.wfile.write(out)

    def _logout(self):
        destroy_session(self._cookie_token())
        out = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self._clear_session_cookie()
        self.end_headers()
        self.wfile.write(out)

    # -- chat endpoints --
    def _list_chats(self):
        user = self._require_user()
        if not user:
            return
        chats = user_chats(user["id"])
        # strip messages for list
        light = [{k: v for k, v in c.items() if k != "messages"} for c in chats]
        self._json(200, {"chats": light})

    def _get_chat(self, chat_id: str):
        user = self._require_user()
        if not user:
            return
        chat = get_chat(user["id"], chat_id)
        if not chat:
            return self._json(404, {"error": "Chat not found"})
        self._json(200, {"chat": chat, "messages": chat.get("messages", [])})

    def _create_chat(self):
        user = self._require_user()
        if not user:
            return
        body = self._read_body()
        title = str(body.get("title", "New chat")).strip()[:80] or "New chat"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        chat = {
            "id": str(uuid.uuid4()),
            "title": title,
            "createdAt": now,
            "updatedAt": now,
            "messages": [],
        }
        save_chat(user["id"], chat)
        self._json(201, {"chat": {k: v for k, v in chat.items() if k != "messages"}})

    def _delete_chat(self, chat_id: str):
        user = self._require_user()
        if not user:
            return
        ok = delete_chat(user["id"], chat_id)
        if not ok:
            return self._json(404, {"error": "Chat not found"})
        self._json(200, {"ok": True})

    def _clear_chats(self):
        user = self._require_user()
        if not user:
            return
        clear_all_chats(user["id"])
        self._json(200, {"ok": True})

    def _chat(self):
        user = self._require_user()
        if not user:
            return
        body = self._read_body()
        chat_id = body.get("chat_id")
        message = str(body.get("message", "")).strip()
        regenerate = bool(body.get("regenerate"))

        if not chat_id:
            return self._json(400, {"error": "chat_id required"})

        chat = get_chat(user["id"], chat_id)
        if not chat:
            return self._json(404, {"error": "Chat not found"})

        messages = list(chat.get("messages") or [])

        if regenerate:
            # drop last assistant message
            while messages and messages[-1].get("role") == "assistant":
                messages.pop()
            if not messages or messages[-1].get("role") != "user":
                return self._json(400, {"error": "Nothing to regenerate"})
        else:
            if not message:
                return self._json(400, {"error": "message required"})
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            messages.append({
                "id": str(uuid.uuid4()),
                "role": "user",
                "content": message,
                "createdAt": now,
            })

        # build Groq history
        history = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in messages:
            role = m.get("role")
            if role in ("user", "assistant"):
                history.append({"role": role, "content": m.get("content", "")})

        try:
            reply_text = call_groq(history)
        except RuntimeError as e:
            return self._json(502, {"error": str(e)})

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        assistant_msg = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": reply_text,
            "createdAt": now,
        }
        messages.append(assistant_msg)
        chat["messages"] = messages
        chat["updatedAt"] = now
        # auto-title from first user message if still generic
        if chat.get("title") in ("New chat", "New conversation") and messages:
            first_user = next((m for m in messages if m["role"] == "user"), None)
            if first_user:
                chat["title"] = first_user["content"][:56]
        save_chat(user["id"], chat)

        light_chat = {k: v for k, v in chat.items() if k != "messages"}
        self._json(200, {"message": assistant_msg, "chat": light_chat})


def main():
    print(f"My AI server → http://127.0.0.1:{PORT}")
    if GROQ_API_KEY:
        print(f"Groq model  → {GROQ_MODEL}")
        print("GROQ_API_KEY loaded from environment / .env")
    else:
        print("⚠  GROQ_API_KEY not set — put it in .env before chatting")
    print(f"Data dir    → {DATA}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
