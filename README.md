# My AI — Groq powered (plain HTML / CSS / JS)

Fully publish-ready chat UI with **Groq API**, local **JSON user accounts**, and **all original animations** preserved.

No React, no Node, no bundler. One Python file serves everything.

---

## Quick start

```bash
# 1. Put your Groq key in .env
cp .env.example .env
# edit .env → GROQ_API_KEY=gsk_...

# 2. Run
python3 server.py

# 3. Open
# http://127.0.0.1:8080
```

---

## Features

| Feature | Detail |
|--------|--------|
| **Auth** | Email + password register / login. Saved in `data/users.json` |
| **Sessions** | HttpOnly cookie, 30-day TTL, stored in `data/sessions.json` |
| **Chats** | Full history per user in `data/chats.json` |
| **AI** | Groq OpenAI-compatible API (`GROQ_API_KEY` from `.env`) |
| **Demo mode** | One-click demo workspace (no password) |
| **UI** | Original orbits, thinking dots, drawer transitions, theme toggle — untouched |

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | **Yes** | — | Key from [console.groq.com](https://console.groq.com/keys) |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Any Groq chat model |
| `PORT` | No | `8080` | HTTP port |

---

## Deploy (any VPS / Railway / Render / Fly)

1. Clone or upload this folder.
2. Set `GROQ_API_KEY` (and optional `PORT`) in the host environment or `.env`.
3. Start: `python3 server.py`
4. Point your domain / reverse proxy to the port.

Data files live in `./data/` — mount a volume if you want persistence across restarts.

---

## API surface (same-origin)

```
GET    /api/auth/me
POST   /api/auth/register   { email, password, name? }
POST   /api/auth/login      { email, password }
POST   /api/auth/demo-login
POST   /api/auth/logout
GET    /api/chats
POST   /api/chats           { title }
GET    /api/chats/:id
DELETE /api/chats/:id
DELETE /api/chats
POST   /chat                { chat_id, message } | { chat_id, regenerate: true }
```

---

## Security notes

- Passwords are PBKDF2-SHA256 (120k iterations) + unique salt.
- Session tokens are random 32-byte values in HttpOnly cookies.
- Groq key never leaves the server — never appears in browser code.
- For production behind HTTPS, consider adding `Secure` flag to the cookie.
