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
DB_PATH = Path(os.environ.get("HOMEDASH_DB", str(BASE_DIR / "homedash.db")))
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
        CREATE TABLE IF NOT EXISTS integrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL UNIQUE,
            type TEXT NOT NULL,
            auth_type TEXT NOT NULL DEFAULT 'bearer',
            credentials TEXT DEFAULT '{}',
            config TEXT DEFAULT '{}',
            enabled INTEGER DEFAULT 1,
            cached_data TEXT DEFAULT NULL,
            cache_updated_at REAL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE CASCADE
        );
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

# ─── Integration Fetchers ─────────────────────────────────────────

INTEGRATION_TYPES = {
    "homeassistant": {
        "name": "Home Assistant",
        "icon": "🏠",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "Long-Lived Access Token", "type": "password", "required": True},
        },
    },
    "unifi": {
        "name": "UniFi Controller",
        "icon": "📡",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "Password", "type": "password", "required": True},
            "site": {"label": "Site ID", "type": "text", "required": False, "default": "default"},
        },
    },
    "plex": {
        "name": "Plex",
        "icon": "🎬",
        "auth_type": "token",
        "fields": {
            "token": {"label": "X-Plex-Token", "type": "password", "required": True},
        },
    },
    "grafana": {
        "name": "Grafana",
        "icon": "📊",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "portainer": {
        "name": "Portainer",
        "icon": "🐳",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "JWT Token", "type": "password", "required": True},
        },
    },
    "pihole": {
        "name": "Pi-hole",
        "icon": "🛡️",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "App Password (v6) or API Token (v5)", "type": "password", "required": False},
            "version": {"label": "Version (5 or 6)", "type": "text", "required": False, "default": "5"},
        },
    },
    "sonarr": {
        "name": "Sonarr",
        "icon": "📺",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "radarr": {
        "name": "Radarr",
        "icon": "🎬",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "lidarr": {
        "name": "Lidarr",
        "icon": "🎵",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "prowlarr": {
        "name": "Prowlarr",
        "icon": "🔍",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "bazarr": {
        "name": "Bazarr",
        "icon": "📝",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "qbittorrent": {
        "name": "qBittorrent",
        "icon": "📥",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "transmission": {
        "name": "Transmission",
        "icon": "📥",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": False},
            "password": {"label": "Password", "type": "password", "required": False},
        },
    },
    "deluge": {
        "name": "Deluge",
        "icon": "📥",
        "auth_type": "basic",
        "fields": {
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "jellyfin": {
        "name": "Jellyfin",
        "icon": "🎬",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "emby": {
        "name": "Emby",
        "icon": "🎬",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "proxmox": {
        "name": "Proxmox",
        "icon": "🖥️",
        "auth_type": "token",
        "fields": {
            "api_token": {"label": "API Token (user@realm!tokenid=secret)", "type": "password", "required": False},
            "username": {"label": "Username (user@realm)", "type": "text", "required": False},
            "password": {"label": "Password", "type": "password", "required": False},
        },
    },
    "tailscale": {
        "name": "Tailscale",
        "icon": "🔒",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "API Key", "type": "password", "required": True},
            "tailnet": {"label": "Tailnet (org.github)", "type": "text", "required": True},
        },
    },
    "uptimekuma": {
        "name": "Uptime Kuma",
        "icon": "📡",
        "auth_type": "none",
        "fields": {},
    },
    "nextcloud": {
        "name": "Nextcloud",
        "icon": "☁️",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "App Password", "type": "password", "required": True},
        },
    },
    "adguard": {
        "name": "AdGuard Home",
        "icon": "🛡️",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": False},
            "password": {"label": "Password", "type": "password", "required": False},
        },
    },
    "sabnzbd": {
        "name": "SABnzbd",
        "icon": "📦",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "nzbget": {
        "name": "NZBGet",
        "icon": "📦",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "gitea": {
        "name": "Gitea",
        "icon": "🔧",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "Access Token", "type": "password", "required": True},
        },
    },
    "gitlab": {
        "name": "GitLab",
        "icon": "🦊",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "Personal Access Token", "type": "password", "required": True},
        },
    },
    "immich": {
        "name": "Immich",
        "icon": "📸",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "paperless": {
        "name": "Paperless-ngx",
        "icon": "📄",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "API Token", "type": "password", "required": True},
        },
    },
    "freshrss": {
        "name": "FreshRSS",
        "icon": "📰",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Password / Token", "type": "password", "required": True},
            "username": {"label": "Username", "type": "text", "required": True},
        },
    },
    "synology": {
        "name": "Synology",
        "icon": "💾",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "prometheus": {
        "name": "Prometheus",
        "icon": "📈",
        "auth_type": "none",
        "fields": {},
    },
    "authelia": {
        "name": "Authelia",
        "icon": "🔑",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "API Token", "type": "password", "required": True},
        },
    },
    "vaultwarden": {
        "name": "Vaultwarden",
        "icon": "🔐",
        "auth_type": "apikey",
        "fields": {
            "admin_token": {"label": "Admin Token", "type": "password", "required": True},
        },
    },
    "syncthing": {
        "name": "Syncthing",
        "icon": "🔄",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "tautulli": {
        "name": "Tautulli",
        "icon": "📺",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "overseerr": {
        "name": "Overseerr",
        "icon": "🎬",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "gotify": {
        "name": "Gotify",
        "icon": "🔔",
        "auth_type": "token",
        "fields": {
            "token": {"label": "Client Token", "type": "password", "required": True},
        },
    },
    "netdata": {
        "name": "Netdata",
        "icon": "📊",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "API Token", "type": "password", "required": False},
        },
    },
    "traefik": {
        "name": "Traefik",
        "icon": "🔀",
        "auth_type": "none",
        "fields": {},
    },
    "navidrome": {
        "name": "Navidrome",
        "icon": "🎵",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "audiobookshelf": {
        "name": "Audiobookshelf",
        "icon": "📖",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "API Token", "type": "password", "required": True},
        },
    },
    "mealie": {
        "name": "Mealie",
        "icon": "🍳",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "API Token", "type": "password", "required": True},
        },
    },
    "node-red": {
        "name": "Node-RED",
        "icon": "🔴",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "Auth Token", "type": "password", "required": True},
        },
    },
    "duplicati": {
        "name": "Duplicati",
        "icon": "💾",
        "auth_type": "none",
        "fields": {},
    },
    "kavita": {
        "name": "Kavita",
        "icon": "📚",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "readarr": {
        "name": "Readarr",
        "icon": "📚",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "homebridge": {
        "name": "Homebridge",
        "icon": "🏠",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "octoprint": {
        "name": "OctoPrint",
        "icon": "🖨️",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "jellyseerr": {
        "name": "Jellyseerr",
        "icon": "🎬",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "miniflux": {
        "name": "Miniflux",
        "icon": "📰",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "stirling-pdf": {
        "name": "Stirling PDF",
        "icon": "📄",
        "auth_type": "none",
        "fields": {},
    },
    "watchtower": {
        "name": "Watchtower",
        "icon": "👁️",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Token (optional)", "type": "password", "required": False},
        },
    },
    "npm": {
        "name": "Nginx Proxy Manager",
        "icon": "🌐",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "opnsense": {
        "name": "OPNsense",
        "icon": "🔥",
        "auth_type": "basic",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
            "api_secret": {"label": "API Secret", "type": "password", "required": True},
        },
    },
    "pfsense": {
        "name": "pfSense",
        "icon": "🔥",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
            "api_secret": {"label": "API Secret", "type": "password", "required": True},
        },
    },
    "unraid": {
        "name": "Unraid",
        "icon": "🟧",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "frigate": {
        "name": "Frigate",
        "icon": "📹",
        "auth_type": "none",
        "fields": {},
    },
    "mosquitto": {
        "name": "Mosquitto MQTT",
        "icon": "📡",
        "auth_type": "none",
        "fields": {},
    },
    "wireguard": {
        "name": "WireGuard",
        "icon": "🔒",
        "auth_type": "none",
        "fields": {},
    },
    "code-server": {
        "name": "Code Server",
        "icon": "💻",
        "auth_type": "password",
        "fields": {
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "guacamole": {
        "name": "Apache Guacamole",
        "icon": "🖥️",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "truenas": {
        "name": "TrueNAS",
        "icon": "💾",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "omada": {
        "name": "TP-Link Omada",
        "icon": "📡",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "caddy": {
        "name": "Caddy",
        "icon": "🔒",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key (optional)", "type": "password", "required": False},
        },
    },
    "cockpit": {
        "name": "Cockpit",
        "icon": "🛩️",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "changedetection": {
        "name": "Change Detection",
        "icon": "🔍",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": False},
        },
    },
    "healthchecks": {
        "name": "Healthchecks",
        "icon": "💚",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": True},
        },
    },
    "wallabag": {
        "name": "Wallabag",
        "icon": "📖",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "linkding": {
        "name": "Linkding",
        "icon": "🔖",
        "auth_type": "bearer",
        "fields": {
            "token": {"label": "API Token", "type": "password", "required": True},
        },
    },
    "romm": {
        "name": "RomM",
        "icon": "🎮",
        "auth_type": "basic",
        "fields": {
            "username": {"label": "Username", "type": "text", "required": True},
            "password": {"label": "Password", "type": "password", "required": True},
        },
    },
    "it-tools": {
        "name": "IT-Tools",
        "icon": "🛠️",
        "auth_type": "none",
        "fields": {},
    },
    "homepage": {
        "name": "Homepage",
        "icon": "🏠",
        "auth_type": "none",
        "fields": {},
    },
    "nginx": {
        "name": "Nginx",
        "icon": "🌐",
        "auth_type": "none",
        "fields": {},
    },
    "ddns-updater": {
        "name": "DDNS Updater",
        "icon": "🔄",
        "auth_type": "none",
        "fields": {},
    },
    "statping": {
        "name": "Statping",
        "icon": "📊",
        "auth_type": "apikey",
        "fields": {
            "api_key": {"label": "API Key", "type": "password", "required": False},
        },
    },
}

async def fetch_integration_data(itype: str, credentials: dict, base_url: str, config: dict = None) -> dict:
    """Fetch live data from a service integration."""
    config = config or {}
    try:
        fetchers = {
            "homeassistant": _fetch_homeassistant,
            "unifi": _fetch_unifi,
            "plex": _fetch_plex,
            "grafana": _fetch_grafana,
            "portainer": _fetch_portainer,
            "pihole": _fetch_pihole,
            "sonarr": _fetch_sonarr_radarr,
            "radarr": _fetch_sonarr_radarr,
            "lidarr": _fetch_sonarr_radarr,
            "prowlarr": _fetch_prowlarr,
            "bazarr": _fetch_bazarr,
            "qbittorrent": _fetch_qbittorrent,
            "transmission": _fetch_transmission,
            "deluge": _fetch_deluge,
            "jellyfin": _fetch_jellyfin,
            "emby": _fetch_jellyfin,
            "proxmox": _fetch_proxmox,
            "tailscale": _fetch_tailscale,
            "uptimekuma": _fetch_uptimekuma,
            "nextcloud": _fetch_nextcloud,
            "adguard": _fetch_adguard,
            "sabnzbd": _fetch_sabnzbd,
            "nzbget": _fetch_nzbget,
            "gitea": _fetch_gitea,
            "gitlab": _fetch_gitlab,
            "immich": _fetch_immich,
            "paperless": _fetch_paperless,
            "freshrss": _fetch_freshrss,
            "synology": _fetch_synology,
            "prometheus": _fetch_prometheus,
            "authelia": _fetch_authelia,
            "vaultwarden": _fetch_vaultwarden,
            "syncthing": _fetch_syncthing,
            "tautulli": _fetch_tautulli,
            "overseerr": _fetch_overseerr,
            "gotify": _fetch_gotify,
            "netdata": _fetch_netdata,
            "traefik": _fetch_traefik,
            "navidrome": _fetch_navidrome,
            "audiobookshelf": _fetch_audiobookshelf,
            "mealie": _fetch_mealie,
            "node-red": _fetch_node_red,
            "duplicati": _fetch_duplicati,
            "kavita": _fetch_kavita,
            "readarr": _fetch_readarr,
            "homebridge": _fetch_homebridge,
            "octoprint": _fetch_octoprint,
            "jellyseerr": _fetch_jellyseerr,
            "miniflux": _fetch_miniflux,
            "stirling-pdf": _fetch_stirling_pdf,
            "watchtower": _fetch_watchtower,
            "npm": _fetch_npm,
            "opnsense": _fetch_opnsense,
            "pfsense": _fetch_pfsense,
            "unraid": _fetch_unraid,
            "frigate": _fetch_frigate,
            "mosquitto": _fetch_mosquitto,
            "wireguard": _fetch_wireguard,
            "code-server": _fetch_code_server,
            "guacamole": _fetch_guacamole,
            "truenas": _fetch_truenas,
            "omada": _fetch_omada,
            "caddy": _fetch_caddy,
            "cockpit": _fetch_cockpit,
            "changedetection": _fetch_changedetection,
            "healthchecks": _fetch_healthchecks,
            "wallabag": _fetch_wallabag,
            "linkding": _fetch_linkding,
            "romm": _fetch_romm,
            "it-tools": _fetch_it_tools,
            "homepage": _fetch_homepage,
            "nginx": _fetch_nginx,
            "ddns-updater": _fetch_ddns_updater,
            "statping": _fetch_statping,
        }
        if itype in fetchers:
            return await fetchers[itype](credentials, base_url, config)
    except Exception as e:
        return {"error": str(e)[:200]}
    return {"error": "Unknown integration type"}

async def _fetch_homeassistant(creds, base_url, config={}):
    token = creds.get("token", "")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        # Get states count
        r = await client.get(f"{base_url}/api/states", headers=headers)
        if r.status_code != 200:
            return {"error": f"HA API error: {r.status_code}"}
        states = r.json()

        # Get config
        rc = await client.get(f"{base_url}/api/config", headers=headers)
        config_data = rc.json() if rc.status_code == 200 else {}

        # Count by domain
        domains = {}
        for s in states:
            domain = s["entity_id"].split(".")[0]
            domains[domain] = domains.get(domain, 0) + 1

        # Top 5 domains
        top_domains = sorted(domains.items(), key=lambda x: -x[1])[:5]

        return {
            "entities": len(states),
            "version": config_data.get("version", "—"),
            "state": config_data.get("state", "—"),
            "location": config_data.get("location_name", "—"),
            "unit_system": config_data.get("unit_system", {}).get("name", "—"),
            "top_domains": [{"domain": d, "count": c} for d, c in top_domains],
            "safe_mode": config_data.get("safe_mode", False),
        }

async def _fetch_unifi(creds, base_url, config={}) -> dict:
    username = creds.get("username", "")
    password = creds.get("password", "")
    site = config.get("site") or creds.get("site") or "default"
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        # Try UniFi OS login first (Cloud Gateway, UDM, etc.)
        login = await client.post(f"{base_url}/api/auth/login", json={"username": username, "password": password})
        if login.status_code != 200:
            # Fallback to standalone controller login
            login = await client.post(f"{base_url}/api/login", json={"username": username, "password": password})
            if login.status_code != 200:
                return {"error": f"UniFi login failed: {login.status_code}"}
            # Standalone controller — direct API paths
            api_prefix = f"/api/s/{site}"
            logout_url = f"{base_url}/logout"
        else:
            # UniFi OS — proxy through /proxy/network
            api_prefix = f"/proxy/network/api/s/{site}"
            logout_url = f"{base_url}/api/auth/logout"

        # Get clients
        r = await client.get(f"{base_url}{api_prefix}/stat/sta")
        clients = r.json().get("data", []) if r.status_code == 200 else []

        # Get devices
        rd = await client.get(f"{base_url}{api_prefix}/stat/device")
        devices = rd.json().get("data", []) if rd.status_code == 200 else []

        # Get health
        rh = await client.get(f"{base_url}{api_prefix}/stat/health")
        health = rh.json().get("data", []) if rh.status_code == 200 else []

        # Logout
        await client.get(logout_url)

        wired = sum(1 for c in clients if c.get("is_wired"))
        wireless = len(clients) - wired
        device_status = {
            "adopted": sum(1 for d in devices if d.get("adopted")),
            "connected": sum(1 for d in devices if d.get("state") == 1),
            "disconnected": sum(1 for d in devices if d.get("state") != 1 and d.get("adopted")),
        }

        return {
            "clients_total": len(clients),
            "clients_wired": wired,
            "clients_wireless": wireless,
            "devices_total": len(devices),
            "devices_adopted": device_status["adopted"],
            "devices_connected": device_status["connected"],
            "devices_disconnected": device_status["disconnected"],
            "health": [{"subsystem": h.get("subsystem"), "status": h.get("status")} for h in health],
        }

async def _fetch_plex(creds, base_url, config={}) -> dict:
    token = creds.get("token", "")
    base_url = base_url.rstrip("/")
    headers = {"X-Plex-Token": token, "Accept": "application/json"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/library/sections", headers=headers)
        if r.status_code != 200:
            return {"error": f"Plex API error: {r.status_code}"}
        data = r.json()
        sections = data.get("MediaContainer", {}).get("Directory", [])

        libraries = []
        for s in sections:
            key = s.get("key")
            count = s.get("childCount") or s.get("totalSize", 0)
            # Fetch real count if not provided
            if not count and key:
                rc = await client.get(f"{base_url}/library/sections/{key}/all", headers=headers,
                                      params={"X-Plex-Container-Start": 0, "X-Plex-Container-Size": 0})
                if rc.status_code == 200:
                    count = rc.json().get("MediaContainer", {}).get("totalSize", 0)
            libraries.append({
                "title": s.get("title", "—"),
                "type": s.get("type", "—"),
                "count": count or 0,
            })

        # Server info
        ri = await client.get(f"{base_url}/", headers=headers)
        server_info = {}
        if ri.status_code == 200:
            mc = ri.json().get("MediaContainer", {})
            server_info = {
                "version": mc.get("version", "—"),
                "platform": mc.get("platform", "—"),
                "friendly_name": mc.get("friendlyName", "—"),
            }

        return {
            "libraries": libraries,
            "library_count": len(libraries),
            **server_info,
        }

async def _fetch_grafana(creds, base_url, config={}) -> dict:
    api_key = creds.get("api_key", "")
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/health", headers=headers)
        health = r.json() if r.status_code == 200 else {}

        rd = await client.get(f"{base_url}/api/dashboards/home", headers=headers)
        dashboards = 0
        if rd.status_code == 200:
            rd2 = await client.get(f"{base_url}/api/search?type=dash-db&limit=1", headers=headers)
            if rd2.status_code == 200:
                dashboards = len(rd2.json())

        return {
            "status": health.get("database", "—"),
            "version": health.get("version", "—"),
            "dashboards": dashboards,
        }

async def _fetch_portainer(creds, base_url, config={}) -> dict:
    token = creds.get("token", "")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        # Get endpoints
        re = await client.get(f"{base_url}/api/endpoints", headers=headers)
        endpoints = re.json() if re.status_code == 200 else []

        # Get containers for first endpoint
        containers = []
        if endpoints:
            eid = endpoints[0].get("Id", 1)
            rc = await client.get(f"{base_url}/api/endpoints/{eid}/docker/containers/json?all=true", headers=headers)
            if rc.status_code == 200:
                containers = rc.json()

        running = sum(1 for c in containers if c.get("State") == "running")

        return {
            "endpoints": len(endpoints),
            "containers_total": len(containers),
            "containers_running": running,
            "containers_stopped": len(containers) - running,
        }

async def _fetch_pihole(creds, base_url, config={}):
    version = int(config.get("version", creds.get("version", "5")))
    base_url = base_url.rstrip("/")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        if version >= 6:
            # Pi-hole v6 — try app password login (bypasses TOTP)
            key = creds.get("api_key", "")
            headers = {}
            sid = None
            if key:
                login = await client.post(f"{base_url}/api/auth", json={"password": key})
                if login.status_code == 200:
                    session_data = login.json().get("session", {})
                    sid = session_data.get("sid")
                    if sid:
                        headers["X-FTL-SID"] = sid
                # If login failed, try token as SID directly
                if not sid:
                    headers["X-FTL-SID"] = key
            # Fetch stats
            r = await client.get(f"{base_url}/api/stats/summary", headers=headers)
            if r.status_code != 200:
                # Fallback: try without auth (some setups allow it)
                r = await client.get(f"{base_url}/api/stats/summary")
            # Clean up session to free max_sessions slot
            if sid:
                await client.delete(f"{base_url}/api/auth", headers={"X-FTL-SID": sid})
            if r.status_code != 200:
                return {"error": f"Pi-hole v6 API error: {r.status_code}"}
            data = r.json()
            return {
                "dns_queries_today": data.get("queries", {}).get("total", 0),
                "ads_blocked_today": data.get("queries", {}).get("blocked", 0),
                "ads_percentage_today": round(data.get("queries", {}).get("percent_blocked", 0), 2),
                "domains_being_blocked": data.get("gravity", {}).get("domains_being_blocked", 0),
                "version": "v6",
            }
        else:
            # Pi-hole v5
            r = await client.get(f"{base_url}/admin/api.php?summaryRaw")
            if r.status_code != 200:
                return {"error": f"Pi-hole API error: {r.status_code}"}
            data = r.json()
            return {
                "dns_queries_today": int(data.get("dns_queries_today", 0)),
                "ads_blocked_today": int(data.get("ads_blocked_today", 0)),
                "ads_percentage_today": round(float(data.get("ads_percentage_today", 0)), 2),
                "domains_being_blocked": int(data.get("domains_being_blocked", 0)),
                "version": "v5",
            }

async def _fetch_sonarr_radarr(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"X-Api-Key": api_key}
    is_series = "sonarr" in base_url.lower() or config.get("type") == "sonarr"
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        if is_series:
            r = await client.get(f"{base_url}/api/v3/series", headers=headers)
            items = r.json() if r.status_code == 200 else []
            rq = await client.get(f"{base_url}/api/v3/queue", headers=headers)
            queue = rq.json() if rq.status_code == 200 else {}
            rw = await client.get(f"{base_url}/api/v3/wanted/missing", headers=headers)
            wanted = rw.json() if rw.status_code == 200 else {}
            return {
                "total": len(items),
                "monitored": sum(1 for s in items if s.get("monitored")),
                "queue": queue.get("totalRecords", 0),
                "wanted": wanted.get("totalRecords", 0),
                "type": "series",
            }
        else:
            r = await client.get(f"{base_url}/api/v3/movie", headers=headers)
            items = r.json() if r.status_code == 200 else []
            rq = await client.get(f"{base_url}/api/v3/queue", headers=headers)
            queue = rq.json() if rq.status_code == 200 else {}
            rw = await client.get(f"{base_url}/api/v3/wanted/missing", headers=headers)
            wanted = rw.json() if rw.status_code == 200 else {}
            return {
                "total": len(items),
                "monitored": sum(1 for m in items if m.get("monitored")),
                "queue": queue.get("totalRecords", 0),
                "wanted": wanted.get("totalRecords", 0),
                "type": "movies",
            }

async def _fetch_prowlarr(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"X-Api-Key": api_key}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        ri = await client.get(f"{base_url}/api/v1/indexer", headers=headers)
        indexers = ri.json() if ri.status_code == 200 else []
        rh = await client.get(f"{base_url}/api/v1/indexerstatus", headers=headers)
        statuses = rh.json() if rh.status_code == 200 else []
        return {
            "indexers": len(indexers),
            "enabled": sum(1 for i in indexers if i.get("enable")),
            "statuses": len(statuses),
        }

async def _fetch_bazarr(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"X-API-KEY": api_key}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/series", headers=headers)
        series = r.json().get("data", []) if r.status_code == 200 else []
        rm = await client.get(f"{base_url}/api/movies", headers=headers)
        movies = rm.json().get("data", []) if rm.status_code == 200 else []
        return {
            "series": len(series),
            "movies": len(movies),
            "total": len(series) + len(movies),
        }

async def _fetch_qbittorrent(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        # Login
        await client.post(f"{base_url}/api/v2/auth/login",
                          data={"username": creds.get("username", ""), "password": creds.get("password", "")},
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        # Transfer info
        rt = await client.get(f"{base_url}/api/v2/transfer/info")
        transfer = rt.json() if rt.status_code == 200 else {}
        # Torrent count
        rc = await client.get(f"{base_url}/api/v2/torrents/info?filter=all")
        all_torrents = rc.json() if rc.status_code == 200 else []
        rco = await client.get(f"{base_url}/api/v2/torrents/info?filter=completed")
        completed = rco.json() if rco.status_code == 200 else []
        return {
            "download_speed": transfer.get("dl_info_speed", 0),
            "upload_speed": transfer.get("up_info_speed", 0),
            "total_torrents": len(all_torrents),
            "completed": len(completed),
            "leeching": len(all_torrents) - len(completed),
            "downloaded": transfer.get("dl_info_data", 0),
            "uploaded": transfer.get("up_info_data", 0),
        }

async def _fetch_transmission(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True,
                                 auth=(creds.get("username", ""), creds.get("password", ""))) as client:
        r = await client.post(f"{base_url}/transmission/rpc",
                              json={"method": "session-stats"},
                              headers={"Content-Type": "application/json"})
        if r.status_code == 409:
            sid = r.headers.get("X-Transmission-Session-Id", "")
            r = await client.post(f"{base_url}/transmission/rpc",
                                  json={"method": "session-stats"},
                                  headers={"Content-Type": "application/json", "X-Transmission-Session-Id": sid})
        data = r.json().get("arguments", {}) if r.status_code == 200 else {}
        return {
            "download_speed": data.get("downloadSpeed", 0),
            "upload_speed": data.get("uploadSpeed", 0),
            "active_torrents": data.get("activeTorrentCount", 0),
            "torrent_count": data.get("torrentCount", 0),
            "downloaded": data.get("currentStats", {}).get("downloadedBytes", 0),
            "uploaded": data.get("currentStats", {}).get("uploadedBytes", 0),
        }

async def _fetch_deluge(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.post(f"{base_url}/json", json={"method": "auth.login", "params": [creds.get("password", "")], "id": 1})
        if r.status_code == 200 and r.json().get("result"):
            r2 = await client.post(f"{base_url}/json", json={"method": "web.update_ui", "params": [["state", "download_payload_rate", "upload_payload_rate", "num_connections"], {}], "id": 2})
            data = r2.json().get("result", {}) if r2.status_code == 200 else {}
            torrents = data.get("torrents", {})
            return {
                "download_speed": data.get("download_payload_rate", 0),
                "upload_speed": data.get("upload_payload_rate", 0),
                "total_torrents": len(torrents),
                "connected": data.get("connected", False),
            }
        return {"error": "Login failed"}

async def _fetch_jellyfin(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"Authorization": f'MediaBrowser Token="{api_key}", Client="Homedash", Device="Homedash", DeviceId="homedash", Version="1.0.0"'}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        rs = await client.get(f"{base_url}/System/Info", headers=headers)
        info = rs.json() if rs.status_code == 200 else {}
        ru = await client.get(f"{base_url}/Users", headers=headers)
        users = ru.json() if ru.status_code == 200 else []
        # Count items by type
        items_count = {}
        for lib_type in ["Movie", "Series", "Audio", "Photo"]:
            ri = await client.get(f"{base_url}/Items?IncludeItemTypes={lib_type}&Limit=0", headers=headers)
            if ri.status_code == 200:
                items_count[lib_type.lower()] = ri.json().get("TotalRecordCount", 0)
        # Active sessions
        rse = await client.get(f"{base_url}/Sessions?ActiveWithinSeconds=300", headers=headers)
        sessions = rse.json() if rse.status_code == 200 else []
        return {
            "server_name": info.get("ServerName", "—"),
            "version": info.get("Version", "—"),
            "users": len(users),
            "active_sessions": len(sessions),
            "movies": items_count.get("movie", 0),
            "series": items_count.get("series", 0),
            "music": items_count.get("audio", 0),
            "photos": items_count.get("photo", 0),
        }

async def _fetch_proxmox(creds, base_url, config={}):
    api_token = creds.get("api_token", "")
    username = creds.get("username", "")
    password = creds.get("password", "")
    base_url = base_url.rstrip("/")

    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        headers = {}

        if api_token and "=" in api_token:
            # API Token: user@realm!tokenid=secret
            token_parts = api_token.split("=", 1)
            user, secret = token_parts
            headers["Authorization"] = f"PVEAPIToken={user}={secret}"
        elif username and password:
            # Username+password login
            login = await client.post(f"{base_url}/api2/json/access/ticket", data={
                "username": username, "password": password
            })
            if login.status_code == 200:
                ticket_data = login.json().get("data", {})
                ticket = ticket_data.get("ticket", "")
                csrf = ticket_data.get("CSRFPreventionToken", "")
                headers["Cookie"] = f"PVEAuthCookie={ticket}"
                if csrf:
                    headers["CSRFPreventionToken"] = csrf
            else:
                return {"error": f"Proxmox login failed: {login.status_code}"}
        else:
            return {"error": "Provide API Token (user@realm!tokenid=secret) or Username+Password"}

        # Get nodes
        rn = await client.get(f"{base_url}/api2/json/nodes", headers=headers)
        if rn.status_code != 200:
            return {"error": f"Proxmox API error: {rn.status_code}"}

        nodes = rn.json().get("data", [])
        vms = []
        lxc = []

        for node in nodes:
            node_name = node["node"]
            # QEMU VMs
            rv = await client.get(f"{base_url}/api2/json/nodes/{node_name}/qemu", headers=headers)
            if rv.status_code == 200:
                vms.extend(rv.json().get("data", []))
            # LXC containers
            rl = await client.get(f"{base_url}/api2/json/nodes/{node_name}/lxc", headers=headers)
            if rl.status_code == 200:
                lxc.extend(rl.json().get("data", []))

        all_vms = vms + lxc
        running = sum(1 for v in all_vms if v.get("status") == "running")

        return {
            "nodes": len(nodes),
            "node_names": [n["node"] for n in nodes],
            "node_status": {n["node"]: n.get("status", "?") for n in nodes},
            "vms_total": len(vms),
            "vms_running": sum(1 for v in vms if v.get("status") == "running"),
            "lxc_total": len(lxc),
            "lxc_running": sum(1 for v in lxc if v.get("status") == "running"),
            "total_running": running,
            "total_stopped": len(all_vms) - running,
        }

async def _fetch_tailscale(creds, base_url, config={}):
    token = creds.get("token", "")
    tailnet = creds.get("tailnet", config.get("tailnet", ""))
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"https://api.tailscale.com/api/v2/tailnet/{tailnet}/devices", headers=headers)
        if r.status_code != 200:
            return {"error": f"Tailscale API error: {r.status_code}"}
        devices = r.json().get("devices", [])
        online = sum(1 for d in devices if d.get("online"))
        return {
            "devices": len(devices),
            "online": online,
            "offline": len(devices) - online,
            "tailnet": tailnet,
        }

async def _fetch_uptimekuma(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/summary")
        if r.status_code != 200:
            return {"error": f"Uptime Kuma API error: {r.status_code}"}
        data = r.json()
        hearts = data.get("heartbeatList", {})
        monitors = data.get("uptimeList", {})
        total = 0
        up = 0
        for mid, beats in hearts.items():
            if beats:
                total += 1
                if beats[-1].get("status") == 1:
                    up += 1
        return {
            "monitors": total,
            "up": up,
            "down": total - up,
            "heartbeats": len(hearts),
        }

async def _fetch_nextcloud(creds, base_url, config={}):
    import base64
    auth = base64.b64encode(f"{creds.get('username', '')}:{creds.get('password', '')}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "OCS-APIRequest": "true"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/ocs/v2.php/cloud/users/{creds.get('username', '')}?format=json", headers=headers)
        if r.status_code == 200:
            userdata = r.json().get("ocs", {}).get("data", {})
        else:
            userdata = {}
        rs = await client.get(f"{base_url}/status.php")
        status = rs.json() if rs.status_code == 200 else {}
        # Storage
        ra = await client.get(f"{base_url}/ocs/v1.php/apps/files/api/v1/local?format=json", headers=headers)
        return {
            "version": status.get("version", "—"),
            "edition": status.get("edition", "—"),
            "username": userdata.get("id", "—"),
            "display_name": userdata.get("displayname", "—"),
            "email": userdata.get("email", "—"),
            "storage_used": userdata.get("quota", {}).get("used", 0),
            "storage_total": userdata.get("quota", {}).get("quota", 0),
        }

async def _fetch_adguard(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        auth = (creds.get("username", ""), creds.get("password", "")) if creds.get("username") else None
        rs = await client.get(f"{base_url}/control/status", auth=auth)
        status = rs.json() if rs.status_code == 200 else {}
        rsq = await client.get(f"{base_url}/control/stats", auth=auth)
        stats = rsq.json() if rsq.status_code == 200 else {}
        return {
            "dns_queries": stats.get("num_dns_queries", 0),
            "blocked": stats.get("num_blocked_filtering", 0),
            "blocked_pct": round(stats.get("num_blocked_filtering", 0) / max(stats.get("num_dns_queries", 1), 1) * 100, 2),
            "safe_browsing": stats.get("num_replaced_safebrowsing", 0),
            "parental": stats.get("num_replaced_parental", 0),
            "version": status.get("version", "—"),
            "protection_enabled": status.get("protection_enabled", False),
        }

async def _fetch_sabnzbd(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/sabnzbd/api?mode=queue&output=json&apikey={api_key}")
        queue = r.json().get("queue", {}) if r.status_code == 200 else {}
        rh = await client.get(f"{base_url}/sabnzbd/api?mode=history&output=json&limit=0&apikey={api_key}")
        history = rh.json().get("history", {}) if rh.status_code == 200 else {}
        return {
            "download_speed": queue.get("kbpersec", "0"),
            "queue_count": int(queue.get("noofslots_total", 0)),
            "queue_size": queue.get("size", "0 B"),
            "history_total": int(history.get("noofslots", 0)),
            "status": queue.get("status", "—"),
            "paused": queue.get("paused", False),
        }

async def _fetch_nzbget(creds, base_url, config={}):
    import base64
    auth = base64.b64encode(f"{creds.get('username', '')}:{creds.get('password', '')}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/jsonrpc/status", headers=headers)
        status = r.json().get("result", {}) if r.status_code == 200 else {}
        return {
            "download_speed": status.get("DownloadRate", 0),
            "download_paused": status.get("DownloadPaused", False),
            "remaining_size": status.get("RemainingSizeMB", 0),
            "downloaded_size": status.get("DownloadedSizeMB", 0),
            "article_cache": status.get("ArticleCacheMB", 0),
        }

async def _fetch_gitea(creds, base_url, config={}):
    token = creds.get("token", "")
    headers = {"Authorization": f"token {token}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        ru = await client.get(f"{base_url}/api/v1/user", headers=headers)
        user = ru.json() if ru.status_code == 200 else {}
        rr = await client.get(f"{base_url}/api/v1/repos/search?limit=1", headers=headers)
        repo_count = rr.json().get("ok", 0) if rr.status_code == 200 else 0
        # Get actual count from paginate
        ra = await client.get(f"{base_url}/api/v1/repos/search?limit=5000", headers=headers)
        repos = ra.json().get("data", []) if ra.status_code == 200 else []
        return {
            "username": user.get("login", "—"),
            "full_name": user.get("full_name", "—"),
            "repos": len(repos),
        }

async def _fetch_gitlab(creds, base_url, config={}):
    token = creds.get("token", "")
    headers = {"PRIVATE-TOKEN": token}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        ru = await client.get(f"{base_url}/api/v4/user", headers=headers)
        user = ru.json() if ru.status_code == 200 else {}
        rp = await client.get(f"{base_url}/api/v4/projects?per_page=1&statistics=true", headers=headers)
        projects = rp.json() if rp.status_code == 200 else []
        return {
            "username": user.get("username", "—"),
            "name": user.get("name", "—"),
            "projects": len(projects),
        }

async def _fetch_immich(creds, base_url, config={}):
    token = creds.get("token", "")
    headers = {"x-api-key": token}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        # Try v2.x endpoints first, fall back to legacy
        rs = await client.get(f"{base_url}/api/server/statistics", headers=headers)
        if rs.status_code != 200:
            rs = await client.get(f"{base_url}/api/server-info/statistics", headers=headers)
        stats = rs.json() if rs.status_code == 200 else {}
        rv = await client.get(f"{base_url}/api/server/version", headers=headers)
        if rv.status_code != 200:
            rv = await client.get(f"{base_url}/api/server-info/version", headers=headers)
        version = rv.json() if rv.status_code == 200 else {}
        return {
            "photos": stats.get("photos", 0),
            "videos": stats.get("videos", 0),
            "total": stats.get("total", 0),
            "usage": round(stats.get("usage", 0) / (1024**3), 2) if stats.get("usage") else 0,
            "version": f"{version.get('major', '')}.{version.get('minor', '')}.{version.get('patch', '')}" if version.get("major") else "—",
        }

async def _fetch_paperless(creds, base_url, config={}):
    token = creds.get("token", "")
    headers = {"Authorization": f"Token {token}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        rd = await client.get(f"{base_url}/api/documents/?page_size=1", headers=headers)
        doc_count = rd.json().get("count", 0) if rd.status_code == 200 else 0
        rc = await client.get(f"{base_url}/api/correspondents/?page_size=1", headers=headers)
        corr_count = rc.json().get("count", 0) if rc.status_code == 200 else 0
        rt = await client.get(f"{base_url}/api/tags/?page_size=1", headers=headers)
        tag_count = rt.json().get("count", 0) if rt.status_code == 200 else 0
        return {
            "documents": doc_count,
            "correspondents": corr_count,
            "tags": tag_count,
        }

async def _fetch_freshrss(creds, base_url, config={}):
    import base64
    auth = base64.b64encode(f"{creds.get('username', '')}:{creds.get('api_key', '')}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/greader.php/reader/api/0/subscription/list?output=json", headers=headers)
        subs = r.json().get("subscriptions", []) if r.status_code == 200 else []
        ru = await client.get(f"{base_url}/api/greader.php/reader/api/0/unread-count?output=json", headers=headers)
        unread_data = ru.json() if ru.status_code == 200 else {}
        unread = 0
        for item in unread_data.get("unreadcounts", []):
            unread += item.get("count", 0)
        return {
            "subscriptions": len(subs),
            "unread": unread,
        }

async def _fetch_synology(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        # Login
        lr = await client.get(f"{base_url}/webapi/auth.cgi?api=SYNO.API.Auth&version=3&method=login&account={creds.get('username', '')}&passwd={creds.get('password', '')}&session=FileStation&format=cookie")
        if lr.status_code == 200 and lr.json().get("success"):
            sid = lr.json().get("data", {}).get("sid", "")
            # System info
            sr = await client.get(f"{base_url}/webapi/entry.cgi?api=SYNO.Core.System&version=1&method=info&_sid={sid}")
            sysinfo = sr.json().get("data", {}) if sr.status_code == 200 else {}
            # Storage
            st = await client.get(f"{base_url}/webapi/entry.cgi?api=SYNO.Storage.CGI.Storage&version=1&method=load_info&_sid={sid}")
            storage = st.json().get("data", {}) if st.status_code == 200 else {}
            return {
                "model": sysinfo.get("model", "—"),
                "version": sysinfo.get("firmware_ver", "—"),
                "hostname": sysinfo.get("hostname", "—"),
                "uptime": sysinfo.get("up_time", "—"),
                "volumes": len(storage.get("volumes", [])),
            }
        return {"error": "Synology login failed"}

async def _fetch_prometheus(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        # Try PromQL API
        r = await client.get(f"{base_url}/api/v1/query?query=up")
        if r.status_code == 200:
            data = r.json().get("data", {}).get("result", [])
            up_count = sum(1 for item in data if item.get("value", [None, "0"])[1] == "1")
            return {
                "targets_total": len(data),
                "targets_up": up_count,
                "targets_down": len(data) - up_count,
            }
        # Fallback: try /-/healthy
        rh = await client.get(f"{base_url}/-/healthy")
        return {"status": "healthy" if rh.status_code == 200 else "unhealthy"}

async def _fetch_authelia(creds, base_url, config={}):
    token = creds.get("token", "")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/state", headers=headers)
        if r.status_code == 200:
            data = r.json()
            return {
                "authelia_version": data.get("authelia_version", "—"),
                "authenticated": data.get("authenticated", False),
                "username": data.get("username", "—"),
                "display_name": data.get("display_name", "—"),
                "emails": data.get("emails", []),
            }
        return {"error": f"Authelia API error: {r.status_code}"}

async def _fetch_vaultwarden(creds, base_url, config={}):
    admin_token = creds.get("admin_token", "")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/admin/diagnostics", headers={"Authorization": f"Bearer {admin_token}"})
        if r.status_code == 200:
            data = r.json()
            return {
                "version": data.get("server_alive", {}).get("version", "—"),
                "users": data.get("user_count", 0),
                "organizations": data.get("org_count", 0),
                "vaults": data.get("send_count", 0),
            }
        return {"error": f"Vaultwarden admin error: {r.status_code}"}

async def _fetch_syncthing(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"X-API-Key": api_key}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/rest/system/status", headers=headers)
        if r.status_code == 200:
            data = r.json()
            rf = await client.get(f"{base_url}/rest/db/status?folder=default", headers=headers)
            folder_data = rf.json() if rf.status_code == 200 else {}
            return {
                "version": data.get("version", "—"),
                "uptime": data.get("uptime", 0),
                "my_id": data.get("myID", "")[:12] + "...",
                "folders": folder_data.get("globalFiles", 0),
                "in_sync_files": folder_data.get("inSyncFiles", 0),
            }
        return {"error": f"Syncthing API error: {r.status_code}"}

async def _fetch_tautulli(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/v2?apikey={api_key}&cmd=get_activity")
        if r.status_code == 200:
            data = r.json().get("response", {}).get("data", {})
            streams = data.get("sessions", [])
            return {
                "stream_count": data.get("stream_count", 0),
                "total_bandwidth": data.get("total_bandwidth", 0),
                "streams": [{
                    "title": s.get("full_title", "—"),
                    "user": s.get("username", "—"),
                    "state": s.get("state", "—"),
                } for s in streams[:5]],
            }
        return {"error": f"Tautulli API error: {r.status_code}"}

async def _fetch_overseerr(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"X-Api-Key": api_key}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/v1/status", headers=headers)
        if r.status_code == 200:
            rr = await client.get(f"{base_url}/api/v1/request?take=0", headers=headers)
            req_count = 0
            if rr.status_code == 200:
                req_count = rr.json().get("pageInfo", {}).get("results", 0)
            return {
                "version": r.json().get("version", "—"),
                "requests_total": req_count,
            }
        return {"error": f"Overseerr API error: {r.status_code}"}

async def _fetch_gotify(creds, base_url, config={}):
    token = creds.get("token", "")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/message?token={token}")
        if r.status_code == 200:
            msgs = r.json().get("messages", [])
            return {
                "messages_total": len(msgs),
                "latest_title": msgs[0].get("title", "—") if msgs else "—",
                "latest_message": msgs[0].get("message", "")[:80] if msgs else "",
            }
        return {"error": f"Gotify API error: {r.status_code}"}

async def _fetch_netdata(creds, base_url, config={}):
    token = creds.get("token", "")
    headers = {"X-Auth-Token": token} if token else {}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/v1/info", headers=headers)
        if r.status_code == 200:
            info = r.json()
            # Get alarms
            ra = await client.get(f"{base_url}/api/v1/alarms?active&status=CRITICAL", headers=headers)
            critical = len(ra.json().get("alarms", {}).keys()) if ra.status_code == 200 else 0
            rw = await client.get(f"{base_url}/api/v1/alarms?active&status=WARNING", headers=headers)
            warnings = len(rw.json().get("alarms", {}).keys()) if rw.status_code == 200 else 0
            return {
                "version": info.get("version", "—"),
                "os_name": info.get("os_name", "—"),
                "os_version": info.get("os_version", "—"),
                "cpu_cores": info.get("cpu_cores", 0),
                "ram_total": info.get("ram_total", 0),
                "critical_alarms": critical,
                "warning_alarms": warnings,
            }
        return {"error": f"Netdata API error: {r.status_code}"}

async def _fetch_traefik(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/overview")
        if r.status_code == 200:
            data = r.json()
            return {
                "http_routers": data.get("http", {}).get("routers", {}).get("total", 0),
                "http_services": data.get("http", {}).get("services", {}).get("total", 0),
                "http_middlewares": data.get("http", {}).get("middlewares", {}).get("total", 0),
            }
        return {"error": f"Traefik API error: {r.status_code}"}

async def _fetch_navidrome(creds, base_url, config={}):
    username = creds.get("username", "")
    password = creds.get("password", "")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/rest/getMusicFolders.view", params={
            "u": username, "p": password, "v": "1.16.1", "c": "homedash", "f": "json"
        })
        if r.status_code == 200:
            sub = r.json().get("subsonic-response", {})
            if sub.get("status") == "ok":
                # Get scan status
                rs = await client.get(f"{base_url}/rest/getScanStatus.view", params={
                    "u": username, "p": password, "v": "1.16.1", "c": "homedash", "f": "json"
                })
                scan = rs.json().get("subsonic-response", {}).get("scanStatus", {}) if rs.status_code == 200 else {}
                return {
                    "folders": len(sub.get("musicFolders", {}).get("musicFolder", [])),
                    "scanning": scan.get("scanning", False),
                    "last_scan": scan.get("lastScan", "—"),
                }
        return {"error": f"Navidrome API error: {r.status_code}"}

async def _fetch_audiobookshelf(creds, base_url, config={}):
    token = creds.get("token", "")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/libraries", headers=headers)
        if r.status_code == 200:
            libs = r.json().get("libraries", [])
            total_books = sum(lib.get("stats", {}).get("totalItems", 0) for lib in libs)
            return {
                "libraries": len(libs),
                "total_books": total_books,
                "library_names": [lib.get("name", "—") for lib in libs],
            }
        return {"error": f"Audiobookshelf API error: {r.status_code}"}

async def _fetch_mealie(creds, base_url, config={}):
    token = creds.get("token", "")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/groups/self", headers=headers)
        if r.status_code == 200:
            data = r.json()
            return {
                "group_name": data.get("name", "—"),
                "categories": len(data.get("categories", [])),
                "tags": len(data.get("tags", [])),
                "tools": len(data.get("tools", [])),
            }
        # Fallback: try about endpoint
        ra = await client.get(f"{base_url}/api/about")
        if ra.status_code == 200:
            return {"version": ra.json().get("version", "—")}
        return {"error": f"Mealie API error: {r.status_code}"}

async def _fetch_node_red(creds, base_url, config={}):
    token = creds.get("token", "")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/flows", headers=headers)
        if r.status_code == 200:
            flows = r.json()
            return {
                "flows": len(flows) if isinstance(flows, list) else 0,
            }
        # Try /api/flows
        r2 = await client.get(f"{base_url}/api/flows", headers=headers)
        if r2.status_code == 200:
            data = r2.json()
            return {"flows": data.get("length", 0)}
        return {"error": f"Node-RED API error: {r.status_code}"}

async def _fetch_duplicati(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/v1/serverstate")
        if r.status_code == 200:
            data = r.json()
            return {
                "version": data.get("ServerVersion", "—"),
                "active_task": data.get("ActiveTask", "—") if data.get("ActiveTask") else "None",
                "scheduler_state": data.get("SchedulerState", "—"),
                "proposed_schedule": len(data.get("ProposedSchedule", [])),
            }
        return {"error": f"Duplicati API error: {r.status_code}"}

async def _fetch_kavita(creds, base_url, config={}):
    token = creds.get("token", "")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/library/libraries", headers=headers)
        if r.status_code == 200:
            libs = r.json()
            return {
                "libraries": len(libs),
                "library_names": [lib.get("name", "—") for lib in libs],
            }
        return {"error": f"Kavita API error: {r.status_code}"}

async def _fetch_readarr(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"X-Api-Key": api_key}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/v1/author", headers=headers)
        authors = r.json() if r.status_code == 200 else []
        rb = await client.get(f"{base_url}/api/v1/book", headers=headers)
        books = rb.json() if rb.status_code == 200 else []
        return {
            "authors": len(authors),
            "books": len(books),
            "missing": sum(1 for b in books if b.get("statistics", {}).get("bookFileCount", 0) == 0),
        }

async def _fetch_homebridge(creds, base_url, config={}):
    username = creds.get("username", "")
    password = creds.get("password", "")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/auth/check")
        if r.status_code == 200:
            # Try accessories
            ra = await client.get(f"{base_url}/api/accessories")
            accessories = ra.json() if ra.status_code == 200 else []
            return {
                "accessories": len(accessories) if isinstance(accessories, list) else 0,
            }
        return {"error": f"Homebridge API error: {r.status_code}"}

async def _fetch_octoprint(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"X-Api-Key": api_key}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/version", headers=headers)
        if r.status_code == 200:
            ver = r.json()
            rp = await client.get(f"{base_url}/api/printer?exclude=temperature", headers=headers)
            state = "operational"
            if rp.status_code == 200:
                state = rp.json().get("state", {}).get("text", "operational")
            return {
                "version": ver.get("server", "—"),
                "api_version": ver.get("api", "—"),
                "state": state,
            }
        return {"error": f"OctoPrint API error: {r.status_code}"}

async def _fetch_jellyseerr(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"X-Api-Key": api_key}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/v1/status", headers=headers)
        if r.status_code == 200:
            rr = await client.get(f"{base_url}/api/v1/request?take=0", headers=headers)
            req_count = rr.json().get("pageInfo", {}).get("results", 0) if rr.status_code == 200 else 0
            return {
                "version": r.json().get("version", "—"),
                "requests_total": req_count,
            }
        return {"error": f"Jellyseerr API error: {r.status_code}"}

async def _fetch_miniflux(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"X-Auth-Token": api_key}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/v1/feeds/counters", headers=headers)
        if r.status_code == 200:
            data = r.json()
            ru = await client.get(f"{base_url}/v1/feeds/counters", headers=headers, params={"status": "unread"})
            unread = ru.json().get("unread", 0) if ru.status_code == 200 else 0
            return {
                "feeds": len(data.get("reads", {})) + len(data.get("unreads", {})),
                "unread": unread,
            }
        return {"error": f"Miniflux API error: {r.status_code}"}

async def _fetch_stirling_pdf(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/v1/info/status")
        if r.status_code == 200:
            return {"status": "operational", **r.json()}
        # Fallback
        r2 = await client.get(f"{base_url}")
        return {"status": "online" if r2.status_code == 200 else "offline"}

async def _fetch_watchtower(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/v1/update", headers=headers)
        if r.status_code == 200:
            return {"last_scan": r.text[:50]}
        # Try metrics
        rm = await client.get(f"{base_url}/v1/metrics", headers=headers)
        if rm.status_code == 200:
            return {"metrics_available": True}
        return {"status": "running"}

async def _fetch_npm(creds, base_url, config={}):
    username = creds.get("username", "")
    password = creds.get("password", "")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        login = await client.post(f"{base_url}/api/tokens", json={"identity": username, "secret": password})
        if login.status_code != 200:
            return {"error": f"NPM login failed: {login.status_code}"}
        token = login.json().get("token", "")
        headers = {"Authorization": f"Bearer {token}"}
        rp = await client.get(f"{base_url}/api/nginx/proxy-hosts", headers=headers)
        proxies = rp.json() if rp.status_code == 200 else []
        rs = await client.get(f"{base_url}/api/nginx/streams", headers=headers)
        streams = rs.json() if rs.status_code == 200 else []
        rc = await client.get(f"{base_url}/api/nginx/ssl", headers=headers)
        certs = rc.json() if rc.status_code == 200 else []
        return {
            "proxy_hosts": len(proxies),
            "streams": len(streams),
            "ssl_certs": len(certs),
            "enabled_hosts": sum(1 for p in proxies if p.get("enabled")),
        }

async def _fetch_opnsense(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    api_secret = creds.get("api_secret", "")
    auth = httpx.BasicAuth(api_key, api_secret)
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True, auth=auth) as client:
        r = await client.get(f"{base_url}/api/diagnostics/firewall/stats")
        if r.status_code == 200:
            data = r.json()
            return {"states": data.get("states", 0), "dstates": data.get("dstates", 0)}
        return {"error": f"OPNsense API error: {r.status_code}"}

async def _fetch_pfsense(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    api_secret = creds.get("api_secret", "")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/v1/status", headers={"Authorization": f"Bearer {api_key}.{api_secret}"})
        if r.status_code == 200:
            data = r.json().get("data", {})
            return {"version": data.get("version", "—"), "cpu_usage": data.get("cpu_usage", 0), "mem_usage": data.get("mem_usage", 0)}
        return {"error": f"pfSense API error: {r.status_code}"}

async def _fetch_unraid(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/v1/info", headers={"x-api-key": api_key})
        if r.status_code == 200:
            data = r.json()
            rd = await client.get(f"{base_url}/api/v1/docker", headers={"x-api-key": api_key})
            docker = rd.json() if rd.status_code == 200 else {}
            rv = await client.get(f"{base_url}/api/v1/vms", headers={"x-api-key": api_key})
            vms = rv.json() if rv.status_code == 200 else {}
            return {
                "os_version": data.get("os_version", "—"),
                "array_status": data.get("array_status", "—"),
                "docker_containers": len(docker.get("docker", [])) if isinstance(docker.get("docker"), list) else 0,
                "vms": len(vms.get("domains", [])) if isinstance(vms.get("domains"), list) else 0,
            }
        return {"error": f"Unraid API error: {r.status_code}"}

async def _fetch_frigate(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/stats")
        if r.status_code == 200:
            data = r.json()
            cameras = data.get("cameras", {})
            return {"cameras": len(cameras), "camera_names": list(cameras.keys()), "detection_fps": data.get("detection_fps", 0)}
        r2 = await client.get(f"{base_url}/api/version")
        if r2.status_code == 200:
            return {"version": r2.text.strip()}
        return {"error": f"Frigate API error: {r.status_code}"}

async def _fetch_mosquitto(creds, base_url, config={}):
    return {"status": "MQTT broker"}

async def _fetch_wireguard(creds, base_url, config={}):
    return {"status": "WireGuard VPN"}

async def _fetch_code_server(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/")
        return {"status": "running" if r.status_code == 200 else "offline"}

async def _fetch_guacamole(creds, base_url, config={}):
    username = creds.get("username", "")
    password = creds.get("password", "")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.post(f"{base_url}/api/tokens", data={"username": username, "password": password})
        if r.status_code == 200:
            token = r.json().get("authToken", "")
            rc = await client.get(f"{base_url}/api/session/data/mysql/connections", params={"token": token})
            connections = rc.json() if rc.status_code == 200 else {}
            return {"connections": len(connections)}
        return {"error": f"Guacamole API error: {r.status_code}"}

async def _fetch_truenas(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/v2.0/system/info", headers=headers)
        if r.status_code == 200:
            data = r.json()
            rp = await client.get(f"{base_url}/api/v2.0/pool", headers=headers)
            pools = rp.json() if rp.status_code == 200 else []
            return {"version": data.get("version", "—"), "hostname": data.get("hostname", "—"), "pools": len(pools)}
        return {"error": f"TrueNAS API error: {r.status_code}"}

async def _fetch_omada(creds, base_url, config={}):
    username = creds.get("username", "")
    password = creds.get("password", "")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        login = await client.post(f"{base_url}/api/v2/login", json={"username": username, "password": password})
        if login.status_code == 200:
            token = login.json().get("result", {}).get("token", "")
            headers = {"Csrf-Token": token}
            rc = await client.get(f"{base_url}/api/v2/sites/default/clients", headers=headers)
            clients = rc.json().get("result", {}).get("data", []) if rc.status_code == 200 else []
            rd = await client.get(f"{base_url}/api/v2/sites/default/devices", headers=headers)
            devices = rd.json().get("result", {}).get("data", []) if rd.status_code == 200 else []
            return {"clients": len(clients), "devices": len(devices), "devices_connected": sum(1 for d in devices if d.get("status") == 1)}
        return {"error": f"Omada login failed: {login.status_code}"}

async def _fetch_caddy(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/config/")
        if r.status_code == 200:
            config_data = r.json()
            routes = config_data.get("apps", {}).get("http", {}).get("servers", {})
            total_routes = sum(len(s.get("routes", [])) for s in routes.values())
            return {"routes": total_routes, "servers": len(routes)}
        return {"error": f"Caddy API error: {r.status_code}"}

async def _fetch_cockpit(creds, base_url, config={}):
    username = creds.get("username", "")
    password = creds.get("password", "")
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/system", auth=httpx.BasicAuth(username, password))
        return {"status": "running" if r.status_code == 200 else "offline"}

async def _fetch_changedetection(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    params = {"api_key": api_key} if api_key else {}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/v1/watch", params=params)
        if r.status_code == 200:
            watches = r.json().get("watches", [])
            return {"watches": len(watches)}
        return {"error": f"ChangeDetection API error: {r.status_code}"}

async def _fetch_healthchecks(creds, base_url, config={}):
    api_key = creds.get("api_key", "")
    headers = {"X-Api-Key": api_key}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/v3/checks/", headers=headers)
        if r.status_code == 200:
            checks = r.json().get("checks", [])
            return {"checks": len(checks), "up": sum(1 for c in checks if c.get("status") == "up"), "down": sum(1 for c in checks if c.get("status") == "down")}
        return {"error": f"Healthchecks API error: {r.status_code}"}

async def _fetch_wallabag(creds, base_url, config={}):
    return {"status": "Wallabag reader"}

async def _fetch_linkding(creds, base_url, config={}):
    token = creds.get("token", "")
    headers = {"Authorization": f"Token {token}"}
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/bookmarks/", headers=headers, params={"limit": 1})
        if r.status_code == 200:
            return {"total": r.json().get("count", 0)}
        return {"error": f"Linkding API error: {r.status_code}"}

async def _fetch_romm(creds, base_url, config={}):
    return {"status": "RomM - Retro game manager"}

async def _fetch_it_tools(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/")
        return {"status": "online" if r.status_code == 200 else "offline"}

async def _fetch_homepage(creds, base_url, config={}):
    return {"status": "Homepage dashboard"}

async def _fetch_nginx(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/nginx_status")
        if r.status_code == 200:
            return {"status": "active"}
        return {"status": "running"}

async def _fetch_ddns_updater(creds, base_url, config={}):
    return {"status": "DDNS active"}

async def _fetch_statping(creds, base_url, config={}):
    async with httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True) as client:
        r = await client.get(f"{base_url}/api/services")
        if r.status_code == 200:
            services = r.json()
            return {"services": len(services), "online": sum(1 for s in services if s.get("online"))}
        return {"error": f"Statping API error: {r.status_code}"}

# ─── Monitor Loop ──────────────────────────────────────────────────

latest_status = {"services": [], "timestamp": 0}

async def run_monitor_loop():
    global latest_status
    while True:
        try:
            db = get_db()
            db_int = get_db()
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
                # Fetch integration data
                intg = db_int.execute("SELECT * FROM integrations WHERE service_id=? AND enabled=1", (svc["id"],)).fetchone()
                if intg:
                    creds = json.loads(intg["credentials"] or "{}")
                    cfg = json.loads(intg["config"] or "{}")
                    int_data = await fetch_integration_data(intg["type"], creds, svc["url"], cfg)
                    svc["integration"] = {"type": intg["type"], "data": int_data}
                    db_int.execute("UPDATE integrations SET cached_data=?, cache_updated_at=? WHERE id=?",
                                   (json.dumps(int_data), time.time(), intg["id"]))
                else:
                    svc["integration"] = None
                results.append(svc)
            db_int.commit(); db_int.close()

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
    # Attach integration data
    for row in rows:
        intg = db.execute("SELECT * FROM integrations WHERE service_id=?", (row["id"],)).fetchone()
        if intg:
            cached = json.loads(intg["cached_data"]) if intg["cached_data"] else None
            row["integration"] = {
                "type": intg["type"],
                "data": cached,
                "enabled": bool(intg["enabled"]),
            }
        else:
            row["integration"] = None
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
        elif wtype == "bookmarks":
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

# ─── Integrations API ──────────────────────────────────────────────

@app.get("/api/integrations/types")
async def list_integration_types(request: Request):
    """List available integration types and their config fields."""
    is_authed(request)
    return INTEGRATION_TYPES

@app.get("/api/integrations")
async def list_integrations(request: Request):
    """List all integrations (credentials masked)."""
    is_authed(request)
    db = get_db()
    rows = [dict(r) for r in db.execute("SELECT * FROM integrations").fetchall()]
    db.close()
    # Mask credentials
    for row in rows:
        creds = json.loads(row.get("credentials") or "{}")
        masked = {}
        for k, v in creds.items():
            if v and len(str(v)) > 4:
                masked[k] = str(v)[:4] + "****"
            else:
                masked[k] = "****"
        row["credentials_masked"] = masked
        row["credentials"] = None  # Don't expose
    return rows

@app.get("/api/integrations/{service_id}")
async def get_integration(request: Request, service_id: int):
    """Get integration for a specific service (credentials masked)."""
    is_authed(request)
    db = get_db()
    row = db.execute("SELECT * FROM integrations WHERE service_id=?", (service_id,)).fetchone()
    db.close()
    if not row:
        return None
    result = dict(row)
    creds = json.loads(result.get("credentials") or "{}")
    masked = {}
    for k, v in creds.items():
        if v and len(str(v)) > 4:
            masked[k] = str(v)[:4] + "****"
        else:
            masked[k] = "****"
    result["credentials_masked"] = masked
    result["credentials"] = None
    return result

class IntegrationIn(BaseModel):
    service_id: int
    type: str
    auth_type: str = "bearer"
    credentials: dict = {}
    config: dict = {}
    enabled: bool = True

@app.post("/api/integrations")
async def create_integration(request: Request, intg: IntegrationIn):
    """Create or update integration for a service."""
    is_authed(request)
    now = time.time()
    db = get_db()
    # Check if exists
    existing = db.execute("SELECT id FROM integrations WHERE service_id=?", (intg.service_id,)).fetchone()
    if existing:
        db.execute(
            "UPDATE integrations SET type=?, auth_type=?, credentials=?, config=?, enabled=?, updated_at=? WHERE service_id=?",
            (intg.type, intg.auth_type, json.dumps(intg.credentials), json.dumps(intg.config), int(intg.enabled), now, intg.service_id))
    else:
        db.execute(
            "INSERT INTO integrations(service_id,type,auth_type,credentials,config,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (intg.service_id, intg.type, intg.auth_type, json.dumps(intg.credentials), json.dumps(intg.config), int(intg.enabled), now, now))
    db.commit(); db.close()
    return {"ok": True}

@app.delete("/api/integrations/{service_id}")
async def delete_integration(request: Request, service_id: int):
    """Remove integration for a service."""
    is_authed(request)
    db = get_db()
    db.execute("DELETE FROM integrations WHERE service_id=?", (service_id,))
    db.commit(); db.close()
    return {"ok": True}

@app.get("/api/integrations/{service_id}/refresh")
async def refresh_integration(request: Request, service_id: int):
    """Force refresh integration data."""
    is_authed(request)
    db = get_db()
    intg = db.execute("SELECT * FROM integrations WHERE service_id=? AND enabled=1", (service_id,)).fetchone()
    svc = db.execute("SELECT url FROM services WHERE id=?", (service_id,)).fetchone()
    db.close()
    if not intg or not svc:
        raise HTTPException(404, "Integration or service not found")
    creds = json.loads(intg["credentials"] or "{}")
    cfg = json.loads(intg["config"] or "{}")
    data = await fetch_integration_data(intg["type"], creds, svc["url"], cfg)
    # Update cache
    db = get_db()
    db.execute("UPDATE integrations SET cached_data=?, cache_updated_at=? WHERE id=?",
               (json.dumps(data), time.time(), intg["id"]))
    db.commit(); db.close()
    return data

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
