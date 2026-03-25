# 🏠 Homedash

> Self-hosted dashboard with auto-discovery, drag-and-drop, and **75+ service integrations** with live data.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-green.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-teal.svg)](https://fastapi.tiangolo.com)

<p align="center">
  <img src="static/favicon.svg" alt="Homedash Logo" width="80" height="80">
</p>

## ✨ Features

- **📊 Live Dashboard** — Real-time service monitoring with drag-and-drop reordering
- **🔗 75+ Integrations** — Live data from services directly on cards (Homepage-style)
- **🐳 Docker Auto-Discovery** — Automatically detect running Docker containers
- **🌐 Network Discovery** — Probe network hosts to find web services
- **📈 Widgets** — Weather, System Stats, Docker Containers, Clock
- **🔄 WebSocket Updates** — Live status updates without page refresh
- **🔐 Authentication** — Session-based auth with bcrypt password hashing
- **📱 Responsive UI** — Glassmorphism design, search bar, favorites, collapsible sections
- **🔍 Ping Monitoring** — Automatic health checks every 30 seconds

## 🚀 Quick Start

### Docker (Recommended)

```bash
git clone https://github.com/Liionboy/homedash.git
cd homedash
docker compose up -d
```

Dashboard: `http://localhost:9876`

### Manual Install

```bash
git clone https://github.com/Liionboy/homedash.git
cd homedash
pip install -r requirements.txt
cp .env.example .env
python server.py
```

### Default Credentials

| Username | Password |
|----------|----------|
| admin    | admin    |

> ⚠️ **Change the default password after first login!**

## 📊 Supported Integrations (75+)

Each integration connects to a service and shows live data on the dashboard card. Click 📊 for detailed view.

### 🏠 Smart Home
| Service | Auth | Data Shown |
|---------|------|------------|
| **Home Assistant** | Bearer Token | Location, State, Version |
| **Homebridge** | Basic Auth | Accessories count |
| **Frigate** | None | Cameras, Detection FPS |
| **Mosquitto MQTT** | None | Broker status |
| **ESPHome / Zigbee2MQTT** | None | Device count |

### 📡 Networking
| Service | Auth | Data Shown |
|---------|------|------------|
| **UniFi Controller** | Basic Auth | Clients, Devices, Health |
| **Nginx Proxy Manager** | Basic Auth | Proxy hosts, SSL certs |
| **Pi-hole** (v5/v6) | API Key | Queries, Blocked % |
| **AdGuard Home** | Basic Auth | DNS queries, Blocked |
| **OPNsense** | API Key+Secret | Firewall states |
| **pfSense** | API Key+Secret | Version, CPU, Memory |
| **Traefik** | None | Routers, Services |
| **Caddy** | None | Routes, Servers |
| **Nginx** | None | Status |
| **Tailscale** | Bearer Token | Devices, Online count |
| **WireGuard** | None | VPN status |
| **TP-Link Omada** | Basic Auth | Clients, Devices |
| **Cloudflare** | API Key | DNS records |

### 🖥️ Infrastructure
| Service | Auth | Data Shown |
|---------|------|------------|
| **Proxmox** | Token/Password | Nodes, VMs, LXC containers |
| **Portainer** | Bearer Token | Endpoints, Containers |
| **Unraid** | API Key | Array status, Docker, VMs |
| **TrueNAS** | API Key | Version, Pools |
| **Docker (generic)** | None | Container status |
| **Synology** | Basic Auth | Model, Volumes, CPU |
| **Prometheus** | None | Targets up/down |
| **Grafana** | API Key | Dashboards, Health |
| **Netdata** | Bearer Token | Alarms, CPU, OS info |
| **Uptime Kuma** | None | Monitors up/down |
| **Statping** | API Key | Services, Online count |
| **Healthchecks** | API Key | Checks, Up/Down |
| **Watchtower** | API Key | Container monitoring |
| **Duplicati** | None | Version, Scheduler |
| **Cockpit** | Basic Auth | Server status |

### 🎬 Media
| Service | Auth | Data Shown |
|---------|------|------------|
| **Plex** | Token | Server, Libraries with counts |
| **Jellyfin** | API Key | Libraries, Server info |
| **Emby** | API Key | Libraries, Server info |
| **Tautulli** | API Key | Active streams, Bandwidth |
| **Navidrome** | Basic Auth | Music folders, Scanning |
| **Audiobookshelf** | Bearer Token | Libraries, Books |

### 📥 Downloads
| Service | Auth | Data Shown |
|---------|------|------------|
| **qBittorrent** | Basic Auth | Torrents, Speed |
| **Transmission** | Basic Auth | Torrents, Speed |
| **Deluge** | Password | Torrents, Speed |
| **SABnzbd** | API Key | Queue, Speed |
| **NZBGet** | Basic Auth | Queue, Speed |

### 📺 Media Management (arr stack)
| Service | Auth | Data Shown |
|---------|------|------------|
| **Sonarr** | API Key | Series count, Missing |
| **Radarr** | API Key | Movies count, Missing |
| **Lidarr** | API Key | Artists, Missing |
| **Readarr** | API Key | Authors, Books, Missing |
| **Prowlarr** | API Key | Indexers |
| **Bazarr** | API Key | Subtitles |

### 🎬 Media Requests
| Service | Auth | Data Shown |
|---------|------|------------|
| **Overseerr** | API Key | Requests count |
| **Jellyseerr** | API Key | Requests count |

### ☁️ Cloud & Storage
| Service | Auth | Data Shown |
|---------|------|------------|
| **Nextcloud** | Basic Auth | Version, Users |
| **Immich** | Bearer Token | Photos, Videos |
| **Paperless-ngx** | Bearer Token | Documents, Tags |
| **Syncthing** | API Key | Synced files |

### 🔐 Security & Auth
| Service | Auth | Data Shown |
|---------|------|------------|
| **Authelia** | Bearer Token | Version, Auth status |
| **Vaultwarden** | Admin Token | Version, Users, Orgs |
| **Apache Guacamole** | Basic Auth | Connections |

### 📰 RSS & Reading
| Service | Auth | Data Shown |
|---------|------|------------|
| **FreshRSS** | API Key | Subscriptions, Unread |
| **Miniflux** | API Key | Feeds, Unread |
| **Wallabag** | Basic Auth | Articles count |
| **Linkding** | Token | Bookmarks count |

### 🔧 Development
| Service | Auth | Data Shown |
|---------|------|------------|
| **Gitea** | Bearer Token | Repos, Users |
| **GitLab** | Bearer Token | Projects, Users |
| **Code Server** | Password | Status |
| **IT-Tools** | None | Status |
| **Node-RED** | Bearer Token | Flows count |

### 🎮 Gaming
| Service | Auth | Data Shown |
|---------|------|------------|
| **RomM** | Basic Auth | Platforms |

### 🍳 Lifestyle
| Service | Auth | Data Shown |
|---------|------|------------|
| **Mealie** | Bearer Token | Categories, Tags |
| **OctoPrint** | API Key | Printer state, Version |
| **Kavita** | API Key | Libraries |
| **Stirling PDF** | None | Status |

### 🔄 Other
| Service | Auth | Data Shown |
|---------|------|------------|
| **Homepage** | None | Dashboard status |
| **Change Detection** | API Key | Watches count |
| **DDNS Updater** | None | DNS status |

## ⚙️ Configuration

```env
# Server
HOMEDASH_PORT=9876

# Authentication
HOMEDASH_USER=admin
HOMEDASH_PASS=your_secure_password

# Database (Docker)
HOMEDASH_DB=/app/data/homedash.db
```

## 📦 Dependencies

```
fastapi>=0.110
uvicorn>=0.29
python-dotenv>=1.0
bcrypt>=4.1
websockets>=12.0
docker>=7.0
httpx>=0.27
```

## 🏗️ Architecture

```
homedash/
├── server.py          # FastAPI backend (API + WebSocket + 75+ integrations)
├── Dockerfile         # Docker build
├── docker-compose.yml # Docker Compose config
├── homedash.db        # SQLite database (persistent in volume)
├── requirements.txt   # Python dependencies
├── .env.example       # Environment configuration template
├── static/
│   ├── index.html     # Main dashboard (glassmorphism UI)
│   ├── login.html     # Login page
│   ├── css/style.css  # Stylesheets
│   └── js/app.js      # Frontend logic
└── CHANGELOG.md       # Version history
```

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/login` | Authenticate user |
| `GET` | `/api/check-auth` | Verify session |
| `GET` | `/api/categories` | List categories |
| `POST` | `/api/categories` | Create category |
| `GET` | `/api/services` | List services (with integration data) |
| `POST` | `/api/services` | Create service |
| `PUT` | `/api/services/{id}` | Update service |
| `DELETE` | `/api/services/{id}` | Delete service |
| `PUT` | `/api/services/reorder` | Reorder services (drag-and-drop) |
| `GET` | `/api/integrations/types` | List all 75+ integration types |
| `GET` | `/api/integrations` | List configured integrations |
| `POST` | `/api/integrations` | Add integration to service |
| `DELETE` | `/api/integrations/{id}` | Remove integration |
| `GET` | `/api/integrations/{id}/refresh` | Force refresh integration data |
| `GET` | `/api/widgets` | List widgets |
| `GET` | `/api/discover/docker` | Discover Docker containers |
| `POST` | `/api/discover/network` | Discover network services |
| `GET` | `/api/health` | Health check |
| `WS` | `/ws` | WebSocket (live updates) |

## 🐳 Docker

```bash
# Build and run
docker compose up -d

# View logs
docker compose logs -f

# Update
git pull
docker compose up -d --build
```

### Docker Compose

```yaml
services:
  homedash:
    build: .
    container_name: homedash
    restart: unless-stopped
    ports:
      - "9876:9876"
    volumes:
      - homedash-data:/app/data
    environment:
      - HOMEDASH_PORT=9876
      - HOMEDASH_USER=admin
      - HOMEDASH_PASS=admin

volumes:
  homedash-data:
```

## 📊 Widgets

- **⛅ Weather** — Current weather via wttr.in
- **💻 System** — CPU, RAM, disk, uptime
- **🐳 Docker** — Container status overview
- **⏰ Clock** — Time with timezone support
- **🔗 Quick Links** — Custom bookmarks

## 🔒 Security

- Bcrypt password hashing
- Session-based authentication (24h expiry)
- Admin/User role separation
- Cookie + header token support
- API tokens stored encrypted in SQLite

## 🛠️ Development

```bash
# Run with auto-reload
uvicorn server:app --reload --host 0.0.0.0 --port 9876
```

### Systemd Service

```bash
sudo cp homedash.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now homedash
```

## 📝 Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

| Version | Date | Highlights |
|---------|------|------------|
| 0.9.1 | 2026-03-26 | Proxmox username+password auth |
| 0.9.0 | 2026-03-25 | 74 integrations (NPM, OPNsense, Unraid...) |
| 0.8.0 | 2026-03-25 | 51 integrations (Netdata, Traefik...) |
| 0.7.0 | 2026-03-25 | Docker support |
| 0.6.0 | 2026-03-25 | Mini-stats on cards |
| 0.5.1 | 2026-03-25 | UniFi OS login fix |
| 0.5.0 | 2026-03-25 | 30 integrations (Homepage-style) |

## 📝 License

MIT License

---

<p align="center">Made with ❤️ for self-hosted enthusiasts</p>
