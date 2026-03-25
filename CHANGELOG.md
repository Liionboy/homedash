# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.0] - 2026-03-25

### Added
- **25 new integrations** — now **74 total**
- Networking: Nginx Proxy Manager, OPNsense, pfSense, WireGuard, Caddy, Nginx, Omada
- Infrastructure: Unraid, TrueNAS, Frigate, Code Server, Cockpit, Mosquitto MQTT
- Tools: ChangeDetection, Healthchecks, Wallabag, Linkding, RomM, IT-Tools, Homepage, DDNS Updater, Statping
- Remote: Apache Guacamole

## [0.8.0] - 2026-03-25

### Added
- **15 new integrations** from Homepage — now **51 total**
- Netdata, Traefik, Navidrome, Audiobookshelf, Mealie, Node-RED, Duplicati, Kavita, Readarr, Homebridge, OctoPrint, Jellyseerr, Miniflux, Stirling PDF, Watchtower

## [0.6.0] - 2026-03-25

### Added
- **Mini-stats on service cards** — integration data now visible directly on cards (no need to click 📊)
- **6 new integrations**: Authelia, Vaultwarden, Syncthing, Tautulli, Overseerr, Gotify
- Now **36 integration types** total (up from 30)

### Changed
- Home Assistant detail modal simplified: shows Location, State, Version (removed entity counts)

## [0.5.1] - 2026-03-25

### Fixed
- **UniFi OS login support** — auto-detects UniFi OS (Cloud Gateway, UDM) vs standalone controller
  - UniFi OS: `POST /api/auth/login` + `/proxy/network/api/s/{site}/...`
  - Standalone fallback: `POST /api/login` + `/api/s/{site}/...`
- **Integration data not showing on UI** — `getServiceIntegration()` now normalizes output from both
  `svc.integration` and `integrationsCache` into a consistent shape
- Default site to `default` when empty in UniFi config

## [0.5.0] - 2026-03-25

### Added
- **30 service integrations** inspired by Homepage
- Media: Plex, Jellyfin, Emby
- Automation: Sonarr, Radarr, Lidarr, Bazarr, Prowlarr
- Downloads: qBittorrent, Transmission, Deluge, SABnzbd, NZBGet
- Network: Pi-hole (v5/v6), AdGuard Home, Tailscale
- Infra: Portainer, Proxmox, Synology, Prometheus, Grafana
- Monitoring: Uptime Kuma
- Cloud: Nextcloud, Immich, Paperless-ngx
- Dev: Gitea, GitLab
- News: FreshRSS
- Helper functions for formatting numbers and speeds

### Added
- **Service Integrations** — connect services with credentials to see live data
- **Home Assistant** integration (Long-Lived Token): entities count, version, state, top domains
- **UniFi Controller** integration (username/password): clients, devices, system health
- **Plex** integration (X-Plex-Token): server info, libraries
- **Grafana** integration (API Key): health, dashboards
- **Portainer** integration (JWT): endpoints, containers
- **Service Detail Modal** — click 📊 on any card to see details
- **Integration Modal** — configure credentials per service
- **Integration badges** on service cards
- API: `/api/integrations/types`, `/api/integrations`, `/api/integrations/{id}/refresh`

## [0.3.0] - 2026-03-24

### Added
- **Glassmorphism design** with backdrop blur and subtle gradients
- **Search bar** — search services by name/description/URL
- **Search engine switcher** — Google, DuckDuckGo, Bing, Brave
- **Keyboard shortcuts**: Ctrl+K or / for search, Ctrl+N for new service, Escape to close modals
- **Header clock** — real-time display in header
- **Quick stats bar** — online/offline/unknown service counts
- **Favorites row** — pinned services shown at top
- **Collapsible sections** — collapse/expand categories (persisted)
- **Bookmarks widget** — grid of quick links
- **Settings modal** — unified services/widgets/categories manager
- Service cards redesigned with icon boxes and animated status indicators
- Progress bars for system widget with color coding
- Responsive improvements for mobile

### Changed
- Complete CSS overhaul — modern glassmorphism style
- Better widget styling with gradients and depth
- Improved search results overlay
- Better modal design with blur backdrop

## [0.2.0] - 2026-03-24

### Added
- Drag-and-drop service reordering
- Running service indicator (real-time status)
- `.gitignore` for cleaner repository

### Changed
- Improved WebSocket message handling
- Better UI responsiveness

## [0.1.0] - 2026-03-24

### Added
- Initial release
- FastAPI backend with SQLite database
- User authentication (bcrypt + sessions)
- Service management (CRUD operations)
- Category organization (Media, Infrastructure, Cloud, Development, Smart Home)
- Docker auto-discovery
- Network discovery with port probing
- Ping monitoring (30s interval)
- WebSocket for live updates
- Dashboard widgets:
  - ⛅ Weather (wttr.in)
  - 💻 System stats (CPU, RAM, disk, uptime)
  - 🐳 Docker containers overview
  - ⏰ Clock with timezone support
  - 🔗 Quick links
- Responsive web UI
- Login page with session management
- Health check endpoint (`/api/health`)
- Systemd service file for production deployment

### Security
- Bcrypt password hashing
- Session-based authentication (24h expiry)
- Admin/User role separation
- Secure cookie + header token support

---

## Version History

| Version | Date       | Description              |
|---------|------------|--------------------------|
| 0.6.0   | 2026-03-25 | Mini-stats + 6 new integrations |
| 0.5.1   | 2026-03-25 | UniFi OS + UI fix        |
| 0.5.0   | 2026-03-25 | 30 service integrations  |
| 0.4.0   | 2026-03-25 | Service integrations     |
| 0.3.0   | 2026-03-24 | Homepage-style UI v2     |
| 0.2.0   | 2026-03-24 | Drag-and-drop + status   |
| 0.1.0   | 2026-03-24 | Initial release          |

---

*For more details, see the [commit history](https://github.com/Liionboy/homedash/commits/main).*
