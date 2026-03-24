# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- README.md documentation
- CHANGELOG.md

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
| 0.2.0   | 2026-03-24 | Drag-and-drop + status   |
| 0.1.0   | 2026-03-24 | Initial release          |

---

*For more details, see the [commit history](https://github.com/Liionboy/homedash/commits/main).*
