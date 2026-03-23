# Homedash — Self-hosted dashboard with auto-discovery, drag-and-drop, live widgets.
# https://github.com/Liionboy/homedash

import asyncio
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import bcrypt
import docker
import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ─── Config ────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "homedash.db"
SESSIONS = {}
CHECK_INTERVAL = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("homedash")

# ─── Database ──────────────────────────────────────────────────────

def get_db():
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            icon TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            icon TEXT DEFAULT '',
            description TEXT DEFAULT '',
            category_id INTEGER,
            is_favorite INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            ping_url TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        );
        CREATE TABLE IF NOT EXISTS widgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            config TEXT DEFAULT '{}',
            sort_order INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS widget_cache (
            widget_id INTEGER PRIMARY KEY,
            data TEXT,
            updated_at REAL,
            FOREIGN KEY(widget_id) REFERENCES widgets(id)
        );
        CREATE TABLE IF NOT EXISTS discovered (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            host TEXT NOT NULL,
            port INTEGER,
            service_type TEXT,
            status TEXT DEFAULT 'unknown',
            last_seen REAL
        );
        CREATE INDEX IF NOT EXISTS idx_services_cat ON services(category_id);
        CREATE INDEX IF NOT EXISTS idx_discovered_host ON discovered(host, port);
    """)
    # Default admin
    existing = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not existing:
        pw_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
        db.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                   ("admin", pw_hash, "admin", time.time()))
    # Default categories
    existing_cats = db.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    if existing_cats == 0:
        for name, icon in [("Media", "🎬"), ("Infrastructure", "🖥️"), ("Cloud", "☁️"), ("Development", "💻"), ("Smart Home", "🏠")]:
            db.execute("INSERT INTO categories(name,icon) VALUES(?,?)", (name, icon))
    db.commit(); db.close()

# ─── Auth ──────────────────────────────────────────────────────────

def is_authed(request: Request) -> dict:
    token = request.headers.get("x-session") or request.cookies.get("homedash_token")
    if token and token in SESSIONS:
        session = SESSIONS[token]
        if session["expires"] > time.time():
            return session
    raise HTTPException(401, "Unauthorized")

def require_admin(request: Request):
    session = is_authed(request)
    if session["role"] != "admin":
        raise HTTPException(403, "Admin access required")

# ─── WebSocket ─────────────────────────────────────────────────────

class WSManager:
    def __init__(self):
        self.connections = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        self.connections = [c for c in self.connections if c != ws]

    async def broadcast(self, payload: dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = WSManager()

# ─── Docker Discovery ──────────────────────────────────────────────

DOCKER_SERVICES = {
    "nginx-proxy-manager": {"name": "Nginx Proxy Manager", "port": 81, "icon": "🌐"},
    "portainer": {"name": "Portainer", "port": 9000, "icon": "🐳"},
    "nextcloud": {"name": "Nextcloud", "port": 443, "icon": "☁️"},
    "plex": {"name": "Plex", "port": 32400, "icon": "🎬"},
    "jellyfin": {"name": "Jellyfin", "port": 8096, "icon": "🎬"},
    "sonarr": {"name": "Sonarr", "port": 8989, "icon": "📺"},
    "radarr": {"name": "Radarr", "port": 7878, "icon": "🎬"},
    "qbittorrent": {"name": "qBittorrent", "port": 8080, "icon": "📥"},
    "homeassistant": {"name": "Home Assistant", "port": 8123, "icon": "🏠"},
    "grafana": {"name": "Grafana", "port": 3000, "icon": "📊"},
    "prometheus": {"name": "Prometheus", "port": 9090, "icon": "📈"},
    "uptime-kuma": {"name": "Uptime Kuma", "port": 3001, "icon": "📡"},
    "gitea": {"name": "Gitea", "port": 3000, "icon": "🔧"},
    "pihole": {"name": "Pi-hole", "port": 80, "icon": "🛡️"},
    "adguard": {"name": "AdGuard Home", "port": 3000, "icon": "🛡️"},
    "vaultwarden": {"name": "Vaultwarden", "port": 80, "icon": "🔐"},
    "syncthing": {"name": "Syncthing", "port": 8384, "icon": "🔄"},
    "immich": {"name": "Immich", "port": 2283, "icon": "📸"},
    "paperless": {"name": "Paperless", "port": 8000, "icon": "📄"},
    "freshrss": {"name": "FreshRSS", "port": 80, "icon": "📰"},
    "authelia": {"name": "Authelia", "port": 9091, "icon": "🔑"},
}

async def discover_docker():
    """Discover running Docker containers and match to known services."""
    results = []
    try:
        loop = asyncio.get_event_loop()
        client = docker.from_env()
        containers = await loop.run_in_executor(None, lambda: client.containers.list(filters={"status": "running"}))
        for c in containers:
            name = c.name.lower().replace("-", "").replace("_", "")
            image = (c.image.tags[0] if c.image.tags else c.image.short_id).lower().replace("-", "")
            ports = {}
            for port_def, bindings in (c.ports or {}).items():
                if bindings:
                    host_port = int(bindings[0]["HostPort"])
                    container_port = int(port_def.split("/")[0])
                    ports[container_port] = host_port

            matched = None
            for key, info in DOCKER_SERVICES.items():
                if key.replace("-", "") in name or key.replace("-", "") in image:
                    matched = info.copy()
                    matched["container"] = c.name
                    host_port = ports.get(info["port"], info["port"])
                    matched["detected_port"] = host_port
                    break

            if not matched:
                matched = {
                    "name": c.name.replace("-", " ").replace("_", " ").title(),
                    "port": list(ports.values())[0] if ports else None,
                    "icon": "🐳",
                    "container": c.name,
                    "detected_port": list(ports.values())[0] if ports else None,
                }
            matched["status"] = c.status
            results.append(matched)
    except Exception as e:
        logger.warning(f"Docker discovery failed: {e}")
    return results

async def discover_network(hosts: list[str] = None, ports: list[int] = None):
    """Probe common ports on hosts to find web services."""
    if not hosts:
        hosts = ["192.168.1.1", "192.168.1.2", "192.168.1.3"]
    if not ports:
        ports = [80, 443, 8080, 8443, 3000, 32400, 8123, 9000]
    results = []
    sem = asyncio.Semaphore(20)

    async def probe(host, port):
        async with sem:
            try:
                async with httpx.AsyncClient(verify=False, timeout=3, follow_redirects=True) as client:
                    proto = "https" if port in (443, 8443) else "http"
                    url = f"{proto}://{host}:{port}"
                    r = await client.get(url)
                    if r.status_code < 500:
                        title = ""
                        if "<title>" in r.text.lower():
                            start = r.text.lower().find("<title>") + 7
                            end = r.text.lower().find("</title>", start)
                            if end > start:
                                title = r.text[start:end].strip()[:80]
                        return {"host": host, "port": port, "url": url, "status": r.status_code, "title": title}
            except Exception:
                pass
            return None

    tasks = [probe(h, p) for h in hosts for p in ports]
    results = [r for r in await asyncio.gather(*tasks) if r]
    return results

# ─── Ping Check ────────────────────────────────────────────────────

async def ping_service(url: str) -> dict:
    """Check if a service URL is reachable."""
    try:
        async with httpx.AsyncClient(verify=False, timeout=5, follow_redirects=True) as client:
            start = time.time()
            r = await client.get(url)
            ms = round((time.time() - start) * 1000, 1)
            return {"online": True, "status": r.status_code, "response_ms": ms}
    except Exception as e:
        return {"online": False, "status": None, "response_ms": None, "error": str(e)[:100]}

# ─── Monitor Loop ──────────────────────────────────────────────────

latest_status = {"services": [], "timestamp": 0}

async def run_monitor_loop():
    global latest_status
    while True:
        try:
            db = get_db()
            services = [dict(r) for r in db.execute(
                "SELECT s.*, c.name as category_name FROM services s LEFT JOIN categories c ON s.category_id=c.id ORDER BY s.sort_order, s.name"
            ).fetchall()]
            db.close()

            results = []
            for svc in services:
                if svc.get("ping_url"):
                    ping = await ping_service(svc["ping_url"])
                    svc.update(ping)
                else:
                    svc["online"] = None
                results.append(svc)

            latest_status = {"services": results, "timestamp": time.time()}
            await manager.broadcast({"type": "status_update", "data": latest_status})
            await asyncio.sleep(CHECK_INTERVAL)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"monitor: {e}")
            await asyncio.sleep(5)

# ─── Pydantic Models ──────────────────────────────────────────────

class LoginIn(BaseModel):
    username: str
    password: str

class CategoryIn(BaseModel):
    name: str
    icon: str = ""

class ServiceIn(BaseModel):
    name: str
    url: str
    icon: str = ""
    description: str = ""
    category_id: int | None = None
    is_favorite: int = 0
    sort_order: int = 0
    ping_url: str | None = None

class WidgetIn(BaseModel):
    type: str
    config: dict = {}
    sort_order: int = 0
    enabled: bool = True

class DiscoverIn(BaseModel):
    hosts: list[str] = []
    ports: list[int] = []

# ─── App ───────────────────────────────────────────────────────────

monitor_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global monitor_task
    init_db()
    monitor_task = asyncio.create_task(run_monitor_loop())
    logger.info("Homedash started")
    yield
    if monitor_task:
        monitor_task.cancel()

app = FastAPI(
    title="Homedash API",
    description="Self-hosted dashboard with auto-discovery, drag-and-drop, and live widgets.",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ─── Pages ─────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index():
    return (BASE_DIR / "static" / "index.html").read_text()

@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page():
    return (BASE_DIR / "static" / "login.html").read_text()

# ─── Auth API ──────────────────────────────────────────────────────

@app.post("/api/login")
async def api_login(body: LoginIn):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    db.close()
    if not user or not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "Invalid credentials")
    token = secrets.token_hex(32)
    SESSIONS[token] = {"user_id": user["id"], "username": user["username"], "role": user["role"], "expires": time.time() + 86400}
    return {"token": token, "username": user["username"], "role": user["role"]}

@app.get("/api/check-auth")
async def check_auth(request: Request):
    session = is_authed(request)
    return {"ok": True, "username": session["username"], "role": session["role"]}

# ─── Categories API ────────────────────────────────────────────────

@app.get("/api/categories")
async def list_categories(request: Request):
    is_authed(request)
    db = get_db()
    rows = [dict(r) for r in db.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()]
    db.close()
    return rows

@app.post("/api/categories")
async def create_category(request: Request, cat: CategoryIn):
    is_authed(request)
    db = get_db()
    cur = db.execute("INSERT INTO categories(name,icon) VALUES(?,?)", (cat.name, cat.icon))
    db.commit(); new_id = cur.lastrowid; db.close()
    return {"ok": True, "id": new_id}

@app.put("/api/categories/{cid}")
async def update_category(request: Request, cid: int, cat: CategoryIn):
    is_authed(request)
    db = get_db()
    db.execute("UPDATE categories SET name=?, icon=? WHERE id=?", (cat.name, cat.icon, cid))
    db.commit(); db.close()
    return {"ok": True}

@app.delete("/api/categories/{cid}")
async def delete_category(request: Request, cid: int):
    is_authed(request)
    db = get_db()
    db.execute("UPDATE services SET category_id=NULL WHERE category_id=?", (cid,))
    db.execute("DELETE FROM categories WHERE id=?", (cid,))
    db.commit(); db.close()
    return {"ok": True}

# ─── Services API ──────────────────────────────────────────────────

@app.get("/api/services")
async def list_services(request: Request):
    is_authed(request)
    db = get_db()
    rows = [dict(r) for r in db.execute(
        "SELECT s.*, c.name as category_name FROM services s LEFT JOIN categories c ON s.category_id=c.id ORDER BY c.sort_order, s.sort_order, s.name"
    ).fetchall()]
    db.close()
    return rows

@app.post("/api/services")
async def create_service(request: Request, svc: ServiceIn):
    is_authed(request)
    now = time.time()
    db = get_db()
    cur = db.execute(
        "INSERT INTO services(name,url,icon,description,category_id,is_favorite,sort_order,ping_url,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (svc.name, svc.url, svc.icon, svc.description, svc.category_id, svc.is_favorite, svc.sort_order, svc.ping_url, now, now))
    db.commit(); new_id = cur.lastrowid; db.close()
    return {"ok": True, "id": new_id}

@app.put("/api/services/{sid}")
async def update_service(request: Request, sid: int, svc: ServiceIn):
    is_authed(request)
    db = get_db()
    db.execute(
        "UPDATE services SET name=?,url=?,icon=?,description=?,category_id=?,is_favorite=?,sort_order=?,ping_url=?,updated_at=? WHERE id=?",
        (svc.name, svc.url, svc.icon, svc.description, svc.category_id, svc.is_favorite, svc.sort_order, svc.ping_url, time.time(), sid))
    db.commit(); db.close()
    return {"ok": True}

@app.delete("/api/services/{sid}")
async def delete_service(request: Request, sid: int):
    is_authed(request)
    db = get_db()
    db.execute("DELETE FROM services WHERE id=?", (sid,))
    db.commit(); db.close()
    return {"ok": True}

@app.put("/api/services/reorder")
async def reorder_services(request: Request):
    """Update sort order for multiple services."""
    is_authed(request)
    body = await request.json()
    db = get_db()
    for item in body.get("order", []):
        db.execute("UPDATE services SET sort_order=?, category_id=? WHERE id=?",
                   (item["sort_order"], item.get("category_id"), item["id"]))
    db.commit(); db.close()
    return {"ok": True}

# ─── Widgets API ───────────────────────────────────────────────────

@app.get("/api/widgets")
async def list_widgets(request: Request):
    is_authed(request)
    db = get_db()
    rows = [dict(r) for r in db.execute("SELECT * FROM widgets ORDER BY sort_order").fetchall()]
    # Attach cached data
    for row in rows:
        cache = db.execute("SELECT data, updated_at FROM widget_cache WHERE widget_id=?", (row["id"],)).fetchone()
        row["cached_data"] = json.loads(cache["data"]) if cache else None
        row["cache_age"] = time.time() - cache["updated_at"] if cache else None
    db.close()
    return rows

@app.post("/api/widgets")
async def create_widget(request: Request, widget: WidgetIn):
    is_authed(request)
    db = get_db()
    cur = db.execute("INSERT INTO widgets(type,config,sort_order,enabled,created_at) VALUES(?,?,?,?,?)",
                     (widget.type, json.dumps(widget.config), widget.sort_order, int(widget.enabled), time.time()))
    db.commit(); new_id = cur.lastrowid; db.close()
    return {"ok": True, "id": new_id}

@app.put("/api/widgets/{wid}")
async def update_widget(request: Request, wid: int, widget: WidgetIn):
    is_authed(request)
    db = get_db()
    db.execute("UPDATE widgets SET type=?,config=?,sort_order=?,enabled=? WHERE id=?",
               (widget.type, json.dumps(widget.config), widget.sort_order, int(widget.enabled), wid))
    db.commit(); db.close()
    return {"ok": True}

@app.delete("/api/widgets/{wid}")
async def delete_widget(request: Request, wid: int):
    is_authed(request)
    db = get_db()
    db.execute("DELETE FROM widget_cache WHERE widget_id=?", (wid,))
    db.execute("DELETE FROM widgets WHERE id=?", (wid,))
    db.commit(); db.close()
    return {"ok": True}

@app.get("/api/widgets/reload")
async def reload_widgets(request: Request):
    """Force-reload all widget data."""
    is_authed(request)
    await refresh_widgets()
    return {"ok": True}

async def refresh_widgets():
    """Refresh data for all enabled widgets."""
    db = get_db()
    widgets = [dict(r) for r in db.execute("SELECT * FROM widgets WHERE enabled=1").fetchall()]
    for w in widgets:
        config = json.loads(w["config"] or "{}")
        data = await fetch_widget_data(w["type"], config)
        existing = db.execute("SELECT widget_id FROM widget_cache WHERE widget_id=?", (w["id"],)).fetchone()
        if existing:
            db.execute("UPDATE widget_cache SET data=?, updated_at=? WHERE widget_id=?",
                       (json.dumps(data), time.time(), w["id"]))
        else:
            db.execute("INSERT INTO widget_cache(widget_id, data, updated_at) VALUES(?,?,?)",
                       (w["id"], json.dumps(data), time.time()))
    db.commit(); db.close()
    await manager.broadcast({"type": "widgets_update"})

async def fetch_widget_data(wtype: str, config: dict) -> dict:
    """Fetch fresh data for a widget type."""
    try:
        if wtype == "weather":
            city = config.get("city", "Bucharest")
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"https://wttr.in/{city}?format=j1")
                data = r.json()
                current = data.get("current_condition", [{}])[0]
                return {
                    "city": city,
                    "temp_c": current.get("temp_C"),
                    "feels_like": current.get("FeelsLikeC"),
                    "humidity": current.get("humidity"),
                    "description": current.get("weatherDesc", [{}])[0].get("value", ""),
                    "wind_kmph": current.get("windspeedKmph"),
                    "icon": weather_emoji(current.get("weatherCode")),
                }
        elif wtype == "system":
            import shutil
            disk = shutil.disk_usage("/")
            with open("/proc/uptime") as f:
                uptime_sec = float(f.read().split()[0])
            with open("/proc/loadavg") as f:
                load = f.read().split()
            with open("/proc/meminfo") as f:
                meminfo = {line.split(":")[0]: int(line.split(":")[1].strip().split()[0]) for line in f if ":" in line}
            total_mem = meminfo.get("MemTotal", 1)
            avail_mem = meminfo.get("MemAvailable", 0)
            return {
                "uptime_hours": round(uptime_sec / 3600, 1),
                "load_1": float(load[0]),
                "load_5": float(load[1]),
                "load_15": float(load[2]),
                "ram_total_gb": round(total_mem / 1048576, 1),
                "ram_used_gb": round((total_mem - avail_mem) / 1048576, 1),
                "ram_percent": round((total_mem - avail_mem) / total_mem * 100, 1),
                "disk_total_gb": round(disk.total / (1024**3), 1),
                "disk_used_gb": round(disk.used / (1024**3), 1),
                "disk_percent": round(disk.used / disk.total * 100, 1),
            }
        elif wtype == "docker":
            try:
                loop = asyncio.get_event_loop()
                client = docker.from_env()
                containers = await loop.run_in_executor(None, lambda: client.containers.list(all=True))
                running = sum(1 for c in containers if c.status == "running")
                return {
                    "total": len(containers),
                    "running": running,
                    "stopped": len(containers) - running,
                    "containers": [{"name": c.name, "status": c.status, "image": c.image.tags[0] if c.image.tags else c.image.short_id} for c in containers[:20]],
                }
            except Exception as e:
                return {"error": str(e)}
        elif wtype == "clock":
            from zoneinfo import ZoneInfo
            tz = config.get("timezone", "Europe/Bucharest")
            now = datetime.now(ZoneInfo(tz))
            return {"time": now.strftime("%H:%M:%S"), "date": now.strftime("%A, %B %d, %Y"), "timezone": tz}
        elif wtype == "quick-links":
            return {"links": config.get("links", [])}
    except Exception as e:
        return {"error": str(e)}
    return {}

def weather_emoji(code):
    code = str(code or "")
    if code in ("113",): return "☀️"
    if code in ("116",): return "⛅"
    if code in ("119", "122"): return "☁️"
    if code in ("176", "263", "266", "293", "296", "299", "302", "305", "308", "353", "356", "359"): return "🌧️"
    if code in ("200", "386", "389", "392", "395"): return "⛈️"
    if code in ("179", "323", "326", "329", "332", "335", "338", "368", "371"): return "🌨️"
    return "🌤️"

# ─── Discovery API ─────────────────────────────────────────────────

@app.get("/api/discover/docker")
async def discover_docker_api(request: Request):
    is_authed(request)
    results = await discover_docker()
    return results

@app.post("/api/discover/network")
async def discover_network_api(request: Request, body: DiscoverIn):
    is_authed(request)
    results = await discover_network(body.hosts or None, body.ports or None)
    return results

@app.post("/api/discover/add")
async def add_discovered(request: Request):
    """Add a discovered service to the dashboard."""
    is_authed(request)
    body = await request.json()
    now = time.time()
    db = get_db()
    db.execute(
        "INSERT INTO services(name,url,icon,description,category_id,ping_url,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (body.get("name", "Unknown"), body.get("url", ""), body.get("icon", "🔗"),
         body.get("description", ""), body.get("category_id"), body.get("ping_url"), now, now))
    db.commit(); db.close()
    return {"ok": True}

# ─── Status API ────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status(request: Request):
    is_authed(request)
    return latest_status

# ─── Ping API ──────────────────────────────────────────────────────

@app.get("/api/ping")
async def ping_url(request: Request, url: str):
    is_authed(request)
    return await ping_service(url)

# ─── Health ────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat(), "version": "0.1.0"}

# ─── WebSocket ─────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
        token = msg.get("token")
        if not token or token not in SESSIONS or SESSIONS[token]["expires"] < time.time():
            await ws.send_json({"type": "auth_error"})
            await ws.close()
            return
        await ws.send_json({"type": "status_update", "data": latest_status})
        manager.connections.append(ws)
        while True:
            try:
                data = await ws.receive_json()
                if data.get("type") == "refresh_widgets":
                    await refresh_widgets()
            except Exception:
                break
    except Exception:
        pass
    finally:
        manager.disconnect(ws)

# ─── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("HOMEDASH_PORT", "9876"))
    uvicorn.run(app, host="0.0.0.0", port=port)
