# 🏠 Homedash

> Self-hosted dashboard with auto-discovery, drag-and-drop, and live widgets.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-green.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-teal.svg)](https://fastapi.tiangolo.com)

<p align="center">
  <img src="static/favicon.svg" alt="Homedash Logo" width="80" height="80">
</p>

## ✨ Features

- **📊 Live Dashboard** — Real-time service monitoring with drag-and-drop reordering
- **🐳 Docker Auto-Discovery** — Automatically detect running Docker containers
- **🌐 Network Discovery** — Probe network hosts to find web services
- **📈 Widgets** — Weather, System Stats, Docker Containers, Clock
- **🔄 WebSocket Updates** — Live status updates without page refresh
- **🔐 Authentication** — Session-based auth with bcrypt password hashing
- **📱 Responsive UI** — Clean, modern interface that works on all devices
- **🔍 Ping Monitoring** — Automatic health checks every 30 seconds

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker (optional, for auto-discovery)

### Installation

```bash
# Clone the repository
git clone https://github.com/Liionboy/homedash.git
cd homedash

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Run the application
python server.py
```

The dashboard will be available at `http://localhost:9876`

### Default Credentials

| Username | Password | Role  |
|----------|----------|-------|
| admin    | admin    | Admin |

> ⚠️ **Change the default password after first login!**

## ⚙️ Configuration

Edit `.env` file:

```env
# Server
HOMEDASH_PORT=9876

# Authentication
HOMEDASH_USER=admin
HOMEDASH_PASS=your_secure_password
```

## 📦 Dependencies

```
fastapi>=0.110
uvicorn>=0.29
python-dotenv>=1.0
bcrypt>=4.1
paramiko>=3.4
aiohttp>=3.9
websockets>=12.0
docker>=7.0
httpx>=0.27
```

## 🏗️ Architecture

```
homedash/
├── server.py          # FastAPI backend (API + WebSocket)
├── homedash.db        # SQLite database
├── requirements.txt   # Python dependencies
├── .env.example       # Environment configuration template
├── homedash.service   # Systemd service file
└── static/
    ├── index.html     # Main dashboard
    ├── login.html     # Login page
    ├── css/           # Stylesheets
    ├── js/            # JavaScript
    └── icons/         # Icons
```

### Database Schema

- **users** — User accounts with bcrypt passwords
- **categories** — Service categories (Media, Infrastructure, Cloud, etc.)
- **services** — Configured services with ping URLs
- **widgets** — Dashboard widgets with cached data
- **discovered** — Auto-discovered services

## 🔌 API Endpoints

| Method   | Endpoint                   | Description               |
|----------|----------------------------|---------------------------|
| `POST`   | `/api/login`               | Authenticate user         |
| `GET`    | `/api/check-auth`          | Verify session            |
| `GET`    | `/api/categories`          | List categories           |
| `POST`   | `/api/categories`          | Create category           |
| `PUT`    | `/api/categories/{id}`     | Update category           |
| `DELETE` | `/api/categories/{id}`     | Delete category           |
| `GET`    | `/api/services`            | List services             |
| `POST`   | `/api/services`            | Create service            |
| `PUT`    | `/api/services/{id}`       | Update service            |
| `DELETE` | `/api/services/{id}`       | Delete service            |
| `PUT`    | `/api/services/reorder`    | Reorder services          |
| `GET`    | `/api/widgets`             | List widgets              |
| `POST`   | `/api/widgets`             | Create widget             |
| `PUT`    | `/api/widgets/{id}`        | Update widget             |
| `DELETE` | `/api/widgets/{id}`        | Delete widget             |
| `GET`    | `/api/widgets/reload`      | Refresh all widgets       |
| `GET`    | `/api/discover/docker`     | Discover Docker containers|
| `POST`   | `/api/discover/network`    | Discover network services |
| `POST`   | `/api/discover/add`        | Add discovered service    |
| `GET`    | `/api/status`              | Get current status        |
| `GET`    | `/api/ping?url=`           | Ping a URL                |
| `GET`    | `/api/health`              | Health check              |
| `WS`     | `/ws`                      | WebSocket (live updates)  |

## 🐳 Docker Services Supported

The app auto-discovers these services when running in Docker:

| Service              | Icon | Default Port |
|----------------------|------|--------------|
| Nginx Proxy Manager  | 🌐   | 81           |
| Portainer            | 🐳   | 9000         |
| Nextcloud            | ☁️   | 443          |
| Plex                 | 🎬   | 32400        |
| Jellyfin             | 🎬   | 8096         |
| Sonarr               | 📺   | 8989         |
| Radarr               | 🎬   | 7878         |
| qBittorrent          | 📥   | 8080         |
| Home Assistant        | 🏠   | 8123         |
| Grafana              | 📊   | 3000         |
| Prometheus           | 📈   | 9090         |
| Uptime Kuma          | 📡   | 3001         |
| And more...          | —    | —            |

## 📊 Widgets

### Available Widget Types

- **⛅ Weather** — Current weather conditions via wttr.in
- **💻 System** — CPU load, RAM usage, disk space, uptime
- **🐳 Docker** — Container status overview
- **⏰ Clock** — Current time with timezone support
- **🔗 Quick Links** — Customizable link shortcuts

## 🔒 Security

- Bcrypt password hashing
- Session-based authentication (24h expiry)
- Admin/User role separation
- Cookie + header token support

## 🛠️ Development

```bash
# Run in development mode with auto-reload
uvicorn server:app --reload --host 0.0.0.0 --port 9876
```

### Systemd Service

```bash
# Install as system service
sudo cp homedash.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now homedash
```

## 📝 License

MIT License — see [LICENSE](LICENSE) for details.

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📧 Contact

- GitHub: [@Liionboy](https://github.com/Liionboy)

---

<p align="center">Made with ❤️ for self-hosted enthusiasts</p>
