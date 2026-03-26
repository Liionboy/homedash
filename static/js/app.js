// ─── Homedash — Frontend v2 ───────────────────────────────────────

const API = '';
let token = localStorage.getItem('homedash_token') || '';
let servicesCache = [];
let categoriesCache = [];
let widgetsCache = [];
let integrationsCache = [];
let integrationTypesCache = {};
let ws = null;

const SEARCH_ENGINES = [
  { name: 'Google', url: 'https://www.google.com/search?q=' },
  { name: 'DuckDuckGo', url: 'https://duckduckgo.com/?q=' },
  { name: 'Bing', url: 'https://www.bing.com/search?q=' },
  { name: 'Brave', url: 'https://search.brave.com/search?q=' },
];

let currentEngine = 0;
let collapsedSections = JSON.parse(localStorage.getItem('homedash_collapsed') || '{}');

// ─── Helpers ──────────────────────────────────────────────────────

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function getHeaders() {
  return { 'x-session': token, 'Content-Type': 'application/json' };
}

async function api(path, opts = {}) {
  const res = await fetch(API + path, { headers: getHeaders(), ...opts });
  if (res.status === 401) {
    localStorage.removeItem('homedash_token');
    location.href = '/login';
    return null;
  }
  return res;
}

// ─── Init ─────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  if (!token) { location.href = '/login'; return; }
  const auth = await api('/api/check-auth');
  if (!auth || !auth.ok) { location.href = '/login'; return; }

  await Promise.all([loadCategories(), loadServices(), loadWidgets(), loadIntegrationTypes()]);
  await loadIntegrations();
  connectWs();
  renderDashboard();
  startClock();
  initSearch();
});

// ─── Clock ────────────────────────────────────────────────────────

function startClock() {
  function update() {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    document.getElementById('header-time').textContent = h + ':' + m;
  }
  update();
  setInterval(update, 10000);
}

// ─── Search ───────────────────────────────────────────────────────

function initSearch() {
  const input = document.getElementById('search-input');
  const results = document.getElementById('search-results');
  const engineBtn = document.getElementById('search-engine-btn');

  engineBtn.textContent = SEARCH_ENGINES[currentEngine].name;
  engineBtn.addEventListener('click', () => {
    currentEngine = (currentEngine + 1) % SEARCH_ENGINES.length;
    engineBtn.textContent = SEARCH_ENGINES[currentEngine].name;
  });

  input.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase();
    if (!q) { results.classList.remove('active'); return; }

    const matches = servicesCache.filter(s =>
      s.name.toLowerCase().includes(q) ||
      (s.description || '').toLowerCase().includes(q) ||
      s.url.toLowerCase().includes(q)
    ).slice(0, 6);

    if (!matches.length) { results.classList.remove('active'); return; }

    results.innerHTML = matches.map(s =>
      '<a class="search-result-item" href="' + esc(s.url) + '" target="_blank" rel="noopener">' +
      '<span class="sr-icon">' + esc(s.icon || '🔗') + '</span>' +
      '<div><div class="sr-name">' + esc(s.name) + '</div>' +
      '<div class="sr-url">' + esc(s.url) + '</div></div></a>'
    ).join('');
    results.classList.add('active');
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const q = input.value.trim();
      if (q && !results.classList.contains('active')) {
        window.open(SEARCH_ENGINES[currentEngine].url + encodeURIComponent(q), '_blank');
        input.value = '';
      }
    }
    if (e.key === 'Escape') {
      results.classList.remove('active');
      input.blur();
    }
  });

  // Close on click outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-bar')) results.classList.remove('active');
  });

  // Global shortcut: Ctrl+K or /
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'k') {
      e.preventDefault();
      input.focus();
    }
    if (e.key === '/' && !e.target.closest('input, textarea, select')) {
      e.preventDefault();
      input.focus();
    }
  });
}

// ─── Categories ───────────────────────────────────────────────────

async function loadCategories() {
  const res = await api('/api/categories');
  if (res) categoriesCache = await res.json();
}

function fillCategorySelect(selectId) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  sel.innerHTML = '<option value="">— None —</option>' +
    categoriesCache.map(c =>
      '<option value="' + c.id + '">' + esc(c.icon) + ' ' + esc(c.name) + '</option>'
    ).join('');
}

// ─── Services ─────────────────────────────────────────────────────

async function loadServices() {
  const res = await api('/api/services');
  if (res) servicesCache = await res.json();
}

function renderDashboard() {
  renderQuickStats();
  renderFavorites();
  renderWidgets();
  renderDashboardServices();
}

function renderQuickStats() {
  let online = 0, offline = 0, unknown = 0;
  servicesCache.forEach(s => {
    if (s.online === true) online++;
    else if (s.online === false) offline++;
    else unknown++;
  });
  document.getElementById('stat-online').textContent = online;
  document.getElementById('stat-offline').textContent = offline;
  document.getElementById('stat-unknown').textContent = unknown;
  document.getElementById('stat-services').textContent = servicesCache.length;
}

function renderFavorites() {
  const el = document.getElementById('favorites-area');
  const favs = servicesCache.filter(s => s.is_favorite);
  if (!favs.length) { el.innerHTML = ''; return; }

  el.innerHTML = '<div class="favorites-row">' +
    favs.map(s =>
      '<a class="fav-btn" href="' + esc(s.url) + '" target="_blank" rel="noopener">' +
      '<span class="fav-icon">' + esc(s.icon || '⭐') + '</span>' +
      esc(s.name) + '</a>'
    ).join('') + '</div>';
}

function renderDashboardServices() {
  const el = document.getElementById('dashboard-services');
  const byCategory = {};

  servicesCache.forEach(s => {
    const catName = s.category_name || 'Uncategorized';
    if (!byCategory[catName]) byCategory[catName] = { icon: '', services: [], id: s.category_id };
    if (s.category_id) {
      const catObj = categoriesCache.find(c => c.id === s.category_id);
      if (catObj) byCategory[catName].icon = catObj.icon;
    }
    byCategory[catName].services.push(s);
  });

  let html = '';
  const entries = Object.entries(byCategory);

  if (!entries.length && !servicesCache.length) {
    html = '<div class="empty">No services yet. Click <strong>➕</strong> or <strong>🔍 Discover</strong> to add services.</div>';
  }

  for (const [catName, data] of entries) {
    const sectionId = 'cat-' + (data.id || 'uncat');
    const isCollapsed = collapsedSections[sectionId];
    const count = data.services.length;

    html += '<div class="section-header">';
    html += '<div class="section-title">' +
      (data.icon || '📂') + ' ' + esc(catName) +
      '<span class="count">' + count + '</span></div>';
    html += '<button class="section-toggle" onclick="toggleSection(\'' + sectionId + '\')">' +
      (isCollapsed ? '▶' : '▼') + '</button>';
    html += '</div>';

    html += '<div class="section-content' + (isCollapsed ? ' collapsed' : '') + '" id="section-' + sectionId + '">';
    html += '<div class="services-grid">';
    html += data.services.map(s => serviceCard(s)).join('');
    html += '</div></div>';
  }

  el.innerHTML = html;
}

function toggleSection(sectionId) {
  collapsedSections[sectionId] = !collapsedSections[sectionId];
  localStorage.setItem('homedash_collapsed', JSON.stringify(collapsedSections));

  const content = document.getElementById('section-' + sectionId);
  const toggle = content?.previousElementSibling?.querySelector('.section-toggle');
  if (content) content.classList.toggle('collapsed');
  if (toggle) toggle.textContent = collapsedSections[sectionId] ? '▶' : '▼';
}

function serviceCard(s) {
  const statusClass = s.online === true ? 'online' : s.online === false ? 'offline' : 'unknown';
  const ping = s.response_ms
    ? '<div class="card-ping"><span>' + s.response_ms + 'ms</span></div>'
    : '';
  const intg = getServiceIntegration(s.id);
  const intBadge = intg
    ? '<span class="integration-badge">' + (integrationTypesCache[intg.type]?.icon || '🔗') + ' ' + (integrationTypesCache[intg.type]?.name || intg.type) + '</span>'
    : '';
  const intStats = intg && intg.cached_data && !intg.cached_data.error
    ? '<div class="card-int-stats">' + getIntStatsHtml(intg.type, intg.cached_data) + '</div>'
    : '';
  const intBtn = '<button class="integration-config-btn" onclick="event.preventDefault();event.stopPropagation();openDetailModal(' + s.id + ')" title="Details">' + (intg ? '📊' : '🔗') + '</button>';

  return '<a class="service-card" href="' + esc(s.url) + '" target="_blank" rel="noopener"' +
    ' draggable="true" data-sid="' + s.id + '" data-cat="' + (s.category_id || '') + '">' +
    '<div class="status-indicator ' + statusClass + '"></div>' +
    '<div class="card-icon">' + esc(s.icon || '🔗') + '</div>' +
    '<div class="card-info">' +
    '<div class="card-name">' + esc(s.name) + '</div>' +
    (s.description ? '<div class="card-desc">' + esc(s.description) + '</div>' : '') +
    intStats + '</div>' + intBtn + '</a>';
}

function getIntStatsHtml(type, d) {
  switch (type) {
    case 'homeassistant':
      return (d.location ? '🏠 ' + esc(d.location) : '') +
        (d.state ? ' · ' + (d.state === 'RUNNING' ? '✅ Running' : '⚠️ ' + esc(d.state)) : '') +
        (d.version ? ' · v' + esc(d.version) : '');
    case 'unifi':
      return '👥 ' + (d.clients_total || 0) + ' clients · 📡 ' + (d.devices_total || 0) + ' devices' +
        (d.health ? ' · ' + (d.health.every(h => h.status === 'ok') ? '✅ All OK' : '⚠️ Issues') : '');
    case 'qbittorrent': case 'transmission': case 'deluge':
      return '📥 ' + (d.total_torrents || 0) + ' torrents' +
        (d.leeching ? ' · ⬇️ ' + d.leeching + ' active' : '') +
        (d.download_speed ? ' · ' + formatSpeed(d.download_speed) : '');
    case 'plex': case 'jellyfin': case 'emby':
      return (d.server_name ? '🖥️ ' + esc(d.server_name) : '') +
        (d.libraries ? ' · 📚 ' + d.libraries.length + ' libraries' : '') +
        (d.active_streams !== undefined ? ' · ▶️ ' + d.active_streams + ' streams' : '');
    case 'portainer':
      return '🐳 ' + (d.endpoints || 0) + ' endpoints · ' + (d.containers_total || 0) + ' containers' +
        (d.containers_running !== undefined ? ' (' + d.containers_running + ' running)' : '');
    case 'grafana':
      return '📊 ' + (d.dashboards || 0) + ' dashboards' +
        (d.health === 'ok' ? ' · ✅ Healthy' : '');
    case 'pihole': case 'adguard':
      const queries = d.dns_queries_today || d.queries_today || 0;
      const blocked = d.ads_blocked_today || d.blocked_today || 0;
      const pct2 = queries ? Math.round(blocked / queries * 100) : 0;
      return '🛡️ ' + queries + ' queries · ' + pct2 + '% blocked' +
        (d.status === 'enabled' ? ' · ✅ Active' : ' · ⏸️ Disabled');
    case 'sonarr': case 'radarr': case 'lidarr':
      return '📺 ' + (d.series_count || d.movies_count || d.artist_count || 0) + ' items' +
        (d.wanted_missing !== undefined ? ' · ' + d.wanted_missing + ' missing' : '');
    case 'proxmox':
      return '🖥️ ' + (d.nodes || 0) + ' nodes · ' + (d.vms_total || 0) + ' VMs' +
        (d.lxc_total ? ' · ' + d.lxc_total + ' LXC' : '') +
        (d.total_running !== undefined ? ' (' + d.total_running + ' on)' : '');
    case 'nextcloud':
      return '☁️ ' + esc(d.version || '') +
        (d.users !== undefined ? ' · 👥 ' + d.users + ' users' : '');
    case 'synology':
      return '💾 ' + (d.model || '') +
        (d.cpu_percent !== undefined ? ' · CPU ' + d.cpu_percent + '%' : '') +
        (d.ram_percent !== undefined ? ' · RAM ' + d.ram_percent + '%' : '');
    case 'tailscale':
      return '🔒 ' + (d.devices || 0) + ' devices' +
        (d.devices_online !== undefined ? ' (' + d.devices_online + ' online)' : '');
    case 'uptimekuma':
      const up = (d.monitors || []).filter(m => m.status === 'up').length;
      return '📡 ' + up + '/' + (d.monitors || []).length + ' up';
    case 'immich':
      return '📸 ' + (d.photos || 0) + ' photos · ' + (d.videos || 0) + ' videos';
    case 'gitea': case 'gitlab':
      return '🔧 ' + (d.repos || 0) + ' repos' +
        (d.users !== undefined ? ' · 👥 ' + d.users + ' users' : '');
    case 'authelia':
      return '🔑 ' + esc(d.authelia_version || '') +
        (d.authenticated ? ' · ✅ Authenticated' : '');
    case 'vaultwarden':
      return '🔐 v' + esc(d.version || '') +
        (d.users !== undefined ? ' · 👥 ' + d.users + ' users' : '');
    case 'syncthing':
      return '🔄 ' + esc(d.version || '') +
        (d.in_sync_files !== undefined ? ' · ' + d.in_sync_files + ' synced' : '');
    case 'tautulli':
      return '📺 ' + (d.stream_count || 0) + ' active streams' +
        (d.total_bandwidth ? ' · ' + formatSpeed(d.total_bandwidth * 1024) : '');
    case 'overseerr':
      return '🎬 ' + (d.requests_total || 0) + ' requests' +
        (d.version ? ' · v' + esc(d.version) : '');
    case 'gotify':
      return '🔔 ' + (d.messages_total || 0) + ' messages' +
        (d.latest_title ? ' · ' + esc(d.latest_title) : '');
    case 'netdata':
      return '📊 v' + esc(d.version || '') +
        (d.critical_alarms ? ' · 🔴 ' + d.critical_alarms + ' critical' : '') +
        (d.warning_alarms ? ' · 🟡 ' + d.warning_alarms + ' warnings' : '') +
        (!d.critical_alarms && !d.warning_alarms ? ' · ✅ All OK' : '');
    case 'traefik':
      return '🔀 ' + (d.http_routers || 0) + ' routers · ' + (d.http_services || 0) + ' services';
    case 'navidrome':
      return '🎵 ' + (d.folders || 0) + ' folders' +
        (d.scanning ? ' · 🔄 Scanning' : '');
    case 'audiobookshelf':
      return '📖 ' + (d.total_books || 0) + ' books · ' + (d.libraries || 0) + ' libraries';
    case 'mealie':
      return '🍳 ' + (d.categories || 0) + ' categories · ' + (d.tags || 0) + ' tags';
    case 'node-red':
      return '🔴 ' + (d.flows || 0) + ' flows';
    case 'duplicati':
      return '💾 v' + esc(d.version || '') +
        (d.scheduler_state ? ' · ' + esc(d.scheduler_state) : '') +
        (d.proposed_schedule ? ' · ' + d.proposed_schedule + ' scheduled' : '');
    case 'kavita':
      return '📚 ' + (d.libraries || 0) + ' libraries';
    case 'readarr':
      return '📚 ' + (d.authors || 0) + ' authors · ' + (d.books || 0) + ' books' +
        (d.missing ? ' · ' + d.missing + ' missing' : '');
    case 'homebridge':
      return '🏠 ' + (d.accessories || 0) + ' accessories';
    case 'octoprint':
      return '🖨️ ' + esc(d.state || '') + (d.version ? ' · v' + esc(d.version) : '');
    case 'jellyseerr':
      return '🎬 ' + (d.requests_total || 0) + ' requests' +
        (d.version ? ' · v' + esc(d.version) : '');
    case 'miniflux':
      return '📰 ' + (d.feeds || 0) + ' feeds · ' + (d.unread || 0) + ' unread';
    case 'stirling-pdf':
      return '📄 ' + esc(d.status || 'online');
    case 'watchtower':
      return '👁️ Monitoring active';
    case 'npm':
      return '🌐 ' + (d.proxy_hosts || 0) + ' proxies · ' + (d.ssl_certs || 0) + ' SSL' +
        (d.enabled_hosts !== undefined ? ' (' + d.enabled_hosts + ' active)' : '');
    case 'opnsense':
      return '🔥 ' + (d.states || 0) + ' states';
    case 'pfsense':
      return '🔥 v' + esc(d.version || '') +
        (d.cpu_usage ? ' · CPU ' + d.cpu_usage + '%' : '');
    case 'unraid':
      return '🟧 Array: ' + esc(d.array_status || '?') +
        (d.docker_containers !== undefined ? ' · 🐳 ' + d.docker_containers : '') +
        (d.vms !== undefined ? ' · 💻 ' + d.vms + ' VMs' : '');
    case 'frigate':
      return '📹 ' + (d.cameras || 0) + ' cameras' +
        (d.detection_fps ? ' · ' + d.detection_fps + ' FPS' : '');
    case 'mosquitto':
      return '📡 MQTT broker';
    case 'wireguard':
      return '🔒 WireGuard VPN';
    case 'code-server':
      return '💻 VS Code Server';
    case 'guacamole':
      return '🖥️ ' + (d.connections || 0) + ' connections';
    case 'truenas':
      return '💾 v' + esc(d.version || '') + ' · ' + (d.pools || 0) + ' pools';
    case 'omada':
      return '📡 ' + (d.clients || 0) + ' clients · ' + (d.devices || 0) + ' devices' +
        (d.devices_connected !== undefined ? ' (' + d.devices_connected + ' up)' : '');
    case 'caddy':
      return '🔒 ' + (d.routes || 0) + ' routes · ' + (d.servers || 0) + ' servers';
    case 'cockpit':
      return '🛩️ Server management';
    case 'changedetection':
      return '🔍 ' + (d.watches || 0) + ' watches';
    case 'healthchecks':
      return '💚 ' + (d.checks || 0) + ' checks' +
        (d.down ? ' · 🔴 ' + d.down + ' down' : ' · ✅ All up');
    case 'wallabag':
      return '📖 ' + (d.total || 0) + ' articles';
    case 'linkding':
      return '🔖 ' + (d.total || 0) + ' bookmarks';
    case 'romm':
      return '🎮 ' + (d.platforms || 0) + ' platforms';
    case 'it-tools':
      return '🛠️ Developer tools';
    case 'homepage':
      return '🏠 Dashboard';
    case 'nginx':
      return '🌐 Web server';
    case 'ddns-updater':
      return '🔄 Dynamic DNS';
    case 'statping':
      return '📊 ' + (d.services || 0) + ' services' +
        (d.online !== undefined ? ' · ' + d.online + ' up' : '');
    default:
      return '';
  }
}

function formatSpeed(bytes) {
  if (bytes > 1048576) return (bytes / 1048576).toFixed(1) + ' MB/s';
  if (bytes > 1024) return (bytes / 1024).toFixed(0) + ' KB/s';
  return bytes + ' B/s';
}

// ─── Widgets ──────────────────────────────────────────────────────

async function loadWidgets() {
  const res = await api('/api/widgets');
  if (res) widgetsCache = await res.json();
}

// ─── Integrations ─────────────────────────────────────────────────

async function loadIntegrationTypes() {
  const res = await api('/api/integrations/types');
  if (res) integrationTypesCache = await res.json();
}

async function loadIntegrations() {
  const res = await api('/api/integrations');
  if (res) integrationsCache = await res.json();
}

function getServiceIntegration(serviceId) {
  // Normalize: always return { type, cached_data (parsed object), enabled, service_id }
  const svc = servicesCache.find(s => s.id === serviceId);
  if (svc && svc.integration && svc.integration.data) {
    return { type: svc.integration.type, cached_data: svc.integration.data, enabled: svc.integration.enabled, service_id: serviceId };
  }
  const cached = integrationsCache.find(i => i.service_id === serviceId);
  if (cached) {
    let parsed = null;
    try { parsed = typeof cached.cached_data === 'string' ? JSON.parse(cached.cached_data) : cached.cached_data; } catch(e) {}
    return { type: cached.type, cached_data: parsed, enabled: cached.enabled, service_id: cached.service_id };
  }
  return null;
}

function openIntegrationModal(serviceId) {
  const svc = servicesCache.find(s => s.id === serviceId);
  if (!svc) return;
  document.getElementById('int-service-id').value = serviceId;
  document.getElementById('int-modal-title').textContent = '🔗 ' + svc.name + ' — Integration';

  // Fill type select
  const sel = document.getElementById('int-type');
  sel.innerHTML = '<option value="">— Select type —</option>' +
    Object.entries(integrationTypesCache).map(([k, v]) =>
      '<option value="' + k + '">' + v.icon + ' ' + v.name + '</option>'
    ).join('');

  // Load existing integration
  const existing = getServiceIntegration(serviceId);
  if (existing) {
    sel.value = existing.type;
    showIntegrationFields();
    // Pre-fill credential field names (we can't show actual values)
  }

  document.getElementById('integration-modal-overlay').classList.add('active');
}

function closeIntegrationModal() {
  document.getElementById('integration-modal-overlay').classList.remove('active');
}

function showIntegrationFields() {
  const type = document.getElementById('int-type').value;
  const el = document.getElementById('int-fields');
  if (!type || !integrationTypesCache[type]) {
    el.innerHTML = '';
    return;
  }
  const intType = integrationTypesCache[type];
  let html = '';
  for (const [field, info] of Object.entries(intType.fields)) {
    const fieldType = info.type === 'password' ? 'password' : 'text';
    html += '<label><span>' + info.label + (info.required ? ' *' : '') + '</span>' +
      '<input id="int-field-' + field + '" type="' + fieldType + '" placeholder="' + (info.required ? 'Required' : 'Optional') + '"></label>';
  }
  // Site field for UniFi
  if (type === 'unifi') {
    html += '<label><span>Site ID</span><input id="int-field-site" value="default" placeholder="default"></label>';
  }
  el.innerHTML = html;
}

async function saveIntegration() {
  const serviceId = parseInt(document.getElementById('int-service-id').value);
  const type = document.getElementById('int-type').value;
  if (!type) return alert('Select an integration type.');

  const intType = integrationTypesCache[type];
  const credentials = {};
  for (const field of Object.keys(intType.fields)) {
    const el = document.getElementById('int-field-' + field);
    if (el) credentials[field] = el.value;
  }
  // Site for UniFi
  const siteEl = document.getElementById('int-field-site');
  const config = siteEl ? { site: siteEl.value || 'default' } : {};

  const authType = intType.auth_type;
  const res = await api('/api/integrations', {
    method: 'POST',
    body: JSON.stringify({ service_id: serviceId, type, auth_type: authType, credentials, config, enabled: true })
  });
  if (!res || !res.ok) return alert('Error saving integration.');
  closeIntegrationModal();
  await loadIntegrations();
  renderDashboard();
}

async function deleteIntegration() {
  const serviceId = parseInt(document.getElementById('int-service-id').value);
  if (!serviceId) return;
  await api('/api/integrations/' + serviceId, { method: 'DELETE' });
  closeIntegrationModal();
  await loadIntegrations();
  renderDashboard();
}

// ─── Service Detail Modal ─────────────────────────────────────────

function openDetailModal(serviceId) {
  const svc = servicesCache.find(s => s.id === serviceId);
  if (!svc) return;
  const intg = getServiceIntegration(serviceId);

  document.getElementById('detail-modal-title').textContent = (svc.icon || '🔗') + ' ' + svc.name;

  let html = '<div class="detail-grid">';

  // Basic info
  html += '<div class="detail-stat"><span class="label">URL</span><a href="' + esc(svc.url) + '" target="_blank" style="color:var(--accent);font-size:12px">' + esc(svc.url) + '</a></div>';
  if (svc.description) html += '<div class="detail-stat"><span class="label">Description</span><span class="value">' + esc(svc.description) + '</span></div>';
  html += '<div class="detail-stat"><span class="label">Category</span><span class="value">' + esc(svc.category_name || '—') + '</span></div>';

  // Ping status
  if (svc.online !== null && svc.online !== undefined) {
    const statusText = svc.online ? '✅ Online' : '❌ Offline';
    const statusColor = svc.online ? 'var(--green)' : 'var(--red)';
    html += '<div class="detail-stat"><span class="label">Status</span><span class="value" style="color:' + statusColor + '">' + statusText + '</span></div>';
    if (svc.response_ms) html += '<div class="detail-stat"><span class="label">Response</span><span class="value">' + svc.response_ms + 'ms</span></div>';
  }

  // Integration data
  if (intg) {
    const intType = integrationTypesCache[intg.type];
    html += '<div class="detail-section-title">' + (intType ? intType.icon + ' ' + intType.name : intg.type) + ' Integration</div>';
    html += '<button class="secondary-btn" style="margin-bottom:10px" onclick="closeDetailModal();openIntegrationModal(' + serviceId + ')">⚙️ Configure</button>';

    if (intg.cached_data) {
      const data = intg.cached_data;
      if (data.error) {
        html += '<div class="detail-stat"><span class="label">Error</span><span class="value" style="color:var(--red)">' + esc(data.error) + '</span></div>';
      } else {
        html += renderIntegrationDetails(intg.type, data);
      }
    } else {
      html += '<div class="empty">No data yet. Will refresh automatically.</div>';
    }
  } else {
    html += '<div class="detail-section-title">Integration</div>';
    html += '<button class="secondary-btn" onclick="closeDetailModal();openIntegrationModal(' + serviceId + ')">🔗 Add Integration</button>';
  }

  html += '</div>';
  document.getElementById('detail-modal-body').innerHTML = html;
  document.getElementById('detail-modal-overlay').classList.add('active');
}

function closeDetailModal() {
  document.getElementById('detail-modal-overlay').classList.remove('active');
}

function renderIntegrationDetails(type, data) {
  let html = '';
  if (type === 'homeassistant') {
    html += '<div class="detail-stat"><span class="label">🏠 Location</span><span class="value">' + esc(data.location || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🔄 State</span><span class="value">' + esc(data.state || '—') + '</span></div>';
    if (data.safe_mode) html += '<div class="detail-stat"><span class="label">⚠️ Safe Mode</span><span class="value" style="color:var(--red)">Active</span></div>';
  } else if (type === 'unifi') {
    html += '<div class="detail-stat"><span class="label">👥 Clients</span><span class="value">' + (data.clients_total || 0) + ' (' + (data.clients_wireless || 0) + ' WiFi, ' + (data.clients_wired || 0) + ' wired)</span></div>';
    html += '<div class="detail-stat"><span class="label">📡 Devices</span><span class="value">' + (data.devices_total || 0) + ' (' + (data.devices_connected || 0) + ' connected)</span></div>';
    if (data.health && data.health.length) {
      html += '<div class="detail-section-title">System Health</div>';
      data.health.forEach(h => {
        const s = h.status === 'ok' ? '✅' : '❌';
        html += '<div class="detail-stat"><span class="label">' + s + ' ' + esc(h.subsystem) + '</span><span class="value">' + esc(h.status) + '</span></div>';
      });
    }
  } else if (type === 'plex') {
    html += '<div class="detail-stat"><span class="label">🖥️ Server</span><span class="value">' + esc(data.friendly_name || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📚 Libraries</span><span class="value">' + (data.library_count || 0) + '</span></div>';
    if (data.libraries && data.libraries.length) {
      html += '<div class="detail-section-title">Libraries</div>';
      data.libraries.forEach(l => {
        html += '<div class="detail-stat"><span class="label">' + esc(l.title) + ' (' + esc(l.type) + ')</span><span class="value">' + l.count + ' items</span></div>';
      });
    }
  } else if (type === 'grafana') {
    html += '<div class="detail-stat"><span class="label">📊 Status</span><span class="value">' + esc(data.status || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📈 Dashboards</span><span class="value">' + (data.dashboards || 0) + '</span></div>';
  } else if (type === 'portainer') {
    html += '<div class="detail-stat"><span class="label">🖥️ Endpoints</span><span class="value">' + (data.endpoints || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🐳 Containers</span><span class="value">' + (data.containers_running || 0) + ' / ' + (data.containers_total || 0) + '</span></div>';
  } else if (type === 'pihole') {
    html += '<div class="detail-stat"><span class="label">🔍 DNS Queries</span><span class="value">' + _fmt(data.dns_queries_today) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🚫 Blocked</span><span class="value">' + _fmt(data.ads_blocked_today) + ' (' + (data.ads_percentage_today || 0) + '%)</span></div>';
    html += '<div class="detail-stat"><span class="label">🛡️ Gravity</span><span class="value">' + _fmt(data.domains_being_blocked) + ' domains</span></div>';
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
  } else if (type === 'sonarr' || type === 'radarr' || type === 'lidarr') {
    const label = type === 'sonarr' ? '📺 Shows' : type === 'radarr' ? '🎬 Movies' : '🎵 Artists';
    html += '<div class="detail-stat"><span class="label">' + label + '</span><span class="value">' + (data.total || 0) + ' (' + (data.monitored || 0) + ' monitored)</span></div>';
    html += '<div class="detail-stat"><span class="label">📥 Queue</span><span class="value">' + (data.queue || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">❓ Missing</span><span class="value">' + (data.wanted || 0) + '</span></div>';
  } else if (type === 'prowlarr') {
    html += '<div class="detail-stat"><span class="label">🔍 Indexers</span><span class="value">' + (data.indexers || 0) + ' (' + (data.enabled || 0) + ' enabled)</span></div>';
  } else if (type === 'bazarr') {
    html += '<div class="detail-stat"><span class="label">📺 Series</span><span class="value">' + (data.series || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🎬 Movies</span><span class="value">' + (data.movies || 0) + '</span></div>';
  } else if (type === 'qbittorrent') {
    html += '<div class="detail-stat"><span class="label">📥 Download</span><span class="value">' + _fmtSpeed(data.download_speed) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📤 Upload</span><span class="value">' + _fmtSpeed(data.upload_speed) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📥 Torrents</span><span class="value">' + (data.total_torrents || 0) + ' (' + (data.completed || 0) + ' done, ' + (data.leeching || 0) + ' active)</span></div>';
  } else if (type === 'transmission') {
    html += '<div class="detail-stat"><span class="label">📥 Download</span><span class="value">' + _fmtSpeed(data.download_speed) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📤 Upload</span><span class="value">' + _fmtSpeed(data.upload_speed) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📥 Active</span><span class="value">' + (data.active_torrents || 0) + ' / ' + (data.torrent_count || 0) + '</span></div>';
  } else if (type === 'deluge') {
    html += '<div class="detail-stat"><span class="label">📥 Download</span><span class="value">' + _fmtSpeed(data.download_speed) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📤 Upload</span><span class="value">' + _fmtSpeed(data.upload_speed) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📥 Torrents</span><span class="value">' + (data.total_torrents || 0) + '</span></div>';
  } else if (type === 'jellyfin' || type === 'emby') {
    html += '<div class="detail-stat"><span class="label">🖥️ Server</span><span class="value">' + esc(data.server_name || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">👤 Users</span><span class="value">' + (data.users || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🔴 Active</span><span class="value">' + (data.active_sessions || 0) + ' sessions</span></div>';
    html += '<div class="detail-stat"><span class="label">🎬 Movies</span><span class="value">' + _fmt(data.movies) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📺 Series</span><span class="value">' + _fmt(data.series) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🎵 Music</span><span class="value">' + _fmt(data.music) + '</span></div>';
  } else if (type === 'proxmox') {
    html += '<div class="detail-stat"><span class="label">🖥️ Nodes</span><span class="value">' + (data.nodes || 0) + ' — ' + esc((data.node_names || []).join(', ')) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">💻 VMs</span><span class="value">' + (data.vms_running || 0) + ' running / ' + (data.vms_total || 0) + ' total</span></div>';
    if (data.lxc_total) html += '<div class="detail-stat"><span class="label">📦 LXC</span><span class="value">' + (data.lxc_running || 0) + ' running / ' + (data.lxc_total || 0) + ' total</span></div>';
  } else if (type === 'tailscale') {
    html += '<div class="detail-stat"><span class="label">🌐 Tailnet</span><span class="value">' + esc(data.tailnet || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📱 Devices</span><span class="value">' + (data.devices || 0) + ' (' + (data.online || 0) + ' online, ' + (data.offline || 0) + ' offline)</span></div>';
  } else if (type === 'uptimekuma') {
    html += '<div class="detail-stat"><span class="label">📡 Monitors</span><span class="value">' + (data.monitors || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">✅ Up</span><span class="value">' + (data.up || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">❌ Down</span><span class="value">' + (data.down || 0) + '</span></div>';
  } else if (type === 'nextcloud') {
    html += '<div class="detail-stat"><span class="label">👤 User</span><span class="value">' + esc(data.display_name || data.username || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
  } else if (type === 'adguard') {
    html += '<div class="detail-stat"><span class="label">🔍 DNS Queries</span><span class="value">' + _fmt(data.dns_queries) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🚫 Blocked</span><span class="value">' + _fmt(data.blocked) + ' (' + (data.blocked_pct || 0) + '%)</span></div>';
    html += '<div class="detail-stat"><span class="label">🛡️ Safe Browsing</span><span class="value">' + _fmt(data.safe_browsing) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
  } else if (type === 'sabnzbd') {
    html += '<div class="detail-stat"><span class="label">📥 Speed</span><span class="value">' + esc(data.download_speed || '0') + ' KB/s</span></div>';
    html += '<div class="detail-stat"><span class="label">📥 Queue</span><span class="value">' + (data.queue_count || 0) + ' — ' + esc(data.queue_size || '0 B') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📥 Status</span><span class="value">' + esc(data.status || '—') + '</span></div>';
  } else if (type === 'nzbget') {
    html += '<div class="detail-stat"><span class="label">📥 Speed</span><span class="value">' + _fmtSpeed(data.download_speed) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📥 Remaining</span><span class="value">' + (data.remaining_size || 0) + ' MB</span></div>';
  } else if (type === 'gitea') {
    html += '<div class="detail-stat"><span class="label">👤 User</span><span class="value">' + esc(data.full_name || data.username || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📁 Repos</span><span class="value">' + (data.repos || 0) + '</span></div>';
  } else if (type === 'gitlab') {
    html += '<div class="detail-stat"><span class="label">👤 User</span><span class="value">' + esc(data.name || data.username || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📁 Projects</span><span class="value">' + (data.projects || 0) + '</span></div>';
  } else if (type === 'immich') {
    html += '<div class="detail-stat"><span class="label">📸 Photos</span><span class="value">' + _fmt(data.photos) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🎥 Videos</span><span class="value">' + _fmt(data.videos) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">💾 Usage</span><span class="value">' + (data.usage || 0) + ' GB</span></div>';
  } else if (type === 'paperless') {
    html += '<div class="detail-stat"><span class="label">📄 Documents</span><span class="value">' + _fmt(data.documents) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">👤 Correspondents</span><span class="value">' + _fmt(data.correspondents) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🏷️ Tags</span><span class="value">' + _fmt(data.tags) + '</span></div>';
  } else if (type === 'freshrss') {
    html += '<div class="detail-stat"><span class="label">📰 Subscriptions</span><span class="value">' + (data.subscriptions || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📬 Unread</span><span class="value">' + _fmt(data.unread) + '</span></div>';
  } else if (type === 'synology') {
    html += '<div class="detail-stat"><span class="label">💾 Model</span><span class="value">' + esc(data.model || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🖥️ Hostname</span><span class="value">' + esc(data.hostname || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">💾 Volumes</span><span class="value">' + (data.volumes || 0) + '</span></div>';
  } else if (type === 'prometheus') {
    html += '<div class="detail-stat"><span class="label">📡 Targets</span><span class="value">' + (data.targets_total || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">✅ Up</span><span class="value">' + (data.targets_up || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">❌ Down</span><span class="value">' + (data.targets_down || 0) + '</span></div>';
  } else if (type === 'authelia') {
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.authelia_version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">👤 Authenticated</span><span class="value">' + (data.authenticated ? '✅ Yes' : '❌ No') + '</span></div>';
  } else if (type === 'vaultwarden') {
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">👥 Users</span><span class="value">' + (data.users || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🏢 Orgs</span><span class="value">' + (data.organizations || 0) + '</span></div>';
  } else if (type === 'syncthing') {
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🆔 ID</span><span class="value">' + esc(data.my_id || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📁 Synced Files</span><span class="value">' + _fmt(data.in_sync_files) + '</span></div>';
  } else if (type === 'tautulli') {
    html += '<div class="detail-stat"><span class="label">▶️ Active Streams</span><span class="value">' + (data.stream_count || 0) + '</span></div>';
    if (data.streams && data.streams.length) {
      html += '<div class="detail-section-title">Now Playing</div>';
      data.streams.forEach(s => {
        html += '<div class="detail-stat"><span class="label">' + esc(s.title) + '</span><span class="value">' + esc(s.user) + ' (' + esc(s.state) + ')</span></div>';
      });
    }
  } else if (type === 'overseerr') {
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📋 Requests</span><span class="value">' + (data.requests_total || 0) + '</span></div>';
  } else if (type === 'gotify') {
    html += '<div class="detail-stat"><span class="label">🔔 Messages</span><span class="value">' + (data.messages_total || 0) + '</span></div>';
    if (data.latest_title) html += '<div class="detail-stat"><span class="label">📬 Latest</span><span class="value">' + esc(data.latest_title) + '</span></div>';
  } else if (type === 'netdata') {
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🖥️ OS</span><span class="value">' + esc(data.os_name || '') + ' ' + esc(data.os_version || '') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">⚡ CPU Cores</span><span class="value">' + (data.cpu_cores || 0) + '</span></div>';
    if (data.critical_alarms) html += '<div class="detail-stat"><span class="label">🔴 Critical</span><span class="value" style="color:var(--red)">' + data.critical_alarms + '</span></div>';
    if (data.warning_alarms) html += '<div class="detail-stat"><span class="label">🟡 Warnings</span><span class="value" style="color:var(--yellow)">' + data.warning_alarms + '</span></div>';
  } else if (type === 'traefik') {
    html += '<div class="detail-stat"><span class="label">🔀 HTTP Routers</span><span class="value">' + (data.http_routers || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🎯 Services</span><span class="value">' + (data.http_services || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🛡️ Middlewares</span><span class="value">' + (data.http_middlewares || 0) + '</span></div>';
  } else if (type === 'navidrome') {
    html += '<div class="detail-stat"><span class="label">📁 Folders</span><span class="value">' + (data.folders || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🔄 Scanning</span><span class="value">' + (data.scanning ? 'Yes' : 'No') + '</span></div>';
  } else if (type === 'audiobookshelf') {
    html += '<div class="detail-stat"><span class="label">📚 Libraries</span><span class="value">' + (data.libraries || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📖 Books</span><span class="value">' + (data.total_books || 0) + '</span></div>';
  } else if (type === 'mealie') {
    html += '<div class="detail-stat"><span class="label">🏷️ Group</span><span class="value">' + esc(data.group_name || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📂 Categories</span><span class="value">' + (data.categories || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🏷️ Tags</span><span class="value">' + (data.tags || 0) + '</span></div>';
  } else if (type === 'node-red') {
    html += '<div class="detail-stat"><span class="label">🔴 Flows</span><span class="value">' + (data.flows || 0) + '</span></div>';
  } else if (type === 'duplicati') {
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📅 Scheduler</span><span class="value">' + esc(data.scheduler_state || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📋 Scheduled</span><span class="value">' + (data.proposed_schedule || 0) + ' jobs</span></div>';
  } else if (type === 'kavita') {
    html += '<div class="detail-stat"><span class="label">📚 Libraries</span><span class="value">' + (data.libraries || 0) + '</span></div>';
  } else if (type === 'readarr') {
    html += '<div class="detail-stat"><span class="label">👤 Authors</span><span class="value">' + (data.authors || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📚 Books</span><span class="value">' + (data.books || 0) + '</span></div>';
    if (data.missing) html += '<div class="detail-stat"><span class="label">❓ Missing</span><span class="value" style="color:var(--yellow)">' + data.missing + '</span></div>';
  } else if (type === 'homebridge') {
    html += '<div class="detail-stat"><span class="label">🏠 Accessories</span><span class="value">' + (data.accessories || 0) + '</span></div>';
  } else if (type === 'octoprint') {
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🖨️ State</span><span class="value">' + esc(data.state || '—') + '</span></div>';
  } else if (type === 'jellyseerr') {
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📋 Requests</span><span class="value">' + (data.requests_total || 0) + '</span></div>';
  } else if (type === 'miniflux') {
    html += '<div class="detail-stat"><span class="label">📰 Feeds</span><span class="value">' + (data.feeds || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📬 Unread</span><span class="value">' + (data.unread || 0) + '</span></div>';
  } else if (type === 'npm') {
    html += '<div class="detail-stat"><span class="label">🌐 Proxy Hosts</span><span class="value">' + (data.proxy_hosts || 0) + ' (' + (data.enabled_hosts || 0) + ' active)</span></div>';
    html += '<div class="detail-stat"><span class="label">🔀 Streams</span><span class="value">' + (data.streams || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🔒 SSL Certs</span><span class="value">' + (data.ssl_certs || 0) + '</span></div>';
  } else if (type === 'opnsense') {
    html += '<div class="detail-stat"><span class="label">🔥 States</span><span class="value">' + (data.states || 0) + '</span></div>';
  } else if (type === 'pfsense') {
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">⚡ CPU</span><span class="value">' + (data.cpu_usage || 0) + '%</span></div>';
    html += '<div class="detail-stat"><span class="label">💾 Memory</span><span class="value">' + (data.mem_usage || 0) + '%</span></div>';
  } else if (type === 'unraid') {
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.os_version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🟧 Array</span><span class="value">' + esc(data.array_status || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🐳 Docker</span><span class="value">' + (data.docker_containers || 0) + ' containers</span></div>';
    html += '<div class="detail-stat"><span class="label">💻 VMs</span><span class="value">' + (data.vms || 0) + '</span></div>';
  } else if (type === 'frigate') {
    html += '<div class="detail-stat"><span class="label">📹 Cameras</span><span class="value">' + (data.cameras || 0) + '</span></div>';
    if (data.camera_names && data.camera_names.length) {
      html += '<div class="detail-stat"><span class="label">🎥 Names</span><span class="value">' + esc(data.camera_names.join(', ')) + '</span></div>';
    }
    html += '<div class="detail-stat"><span class="label">📊 Detection FPS</span><span class="value">' + (data.detection_fps || 0) + '</span></div>';
  } else if (type === 'truenas') {
    html += '<div class="detail-stat"><span class="label">📦 Version</span><span class="value">' + esc(data.version || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🖥️ Hostname</span><span class="value">' + esc(data.hostname || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">💾 Pools</span><span class="value">' + (data.pools || 0) + '</span></div>';
  } else if (type === 'omada') {
    html += '<div class="detail-stat"><span class="label">👥 Clients</span><span class="value">' + (data.clients || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📡 Devices</span><span class="value">' + (data.devices || 0) + ' (' + (data.devices_connected || 0) + ' connected)</span></div>';
  } else if (type === 'caddy') {
    html += '<div class="detail-stat"><span class="label">🔀 Routes</span><span class="value">' + (data.routes || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">🖥️ Servers</span><span class="value">' + (data.servers || 0) + '</span></div>';
  } else if (type === 'healthchecks') {
    html += '<div class="detail-stat"><span class="label">💚 Checks</span><span class="value">' + (data.checks || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">✅ Up</span><span class="value">' + (data.up || 0) + '</span></div>';
    if (data.down) html += '<div class="detail-stat"><span class="label">❌ Down</span><span class="value" style="color:var(--red)">' + data.down + '</span></div>';
  } else if (type === 'linkding') {
    html += '<div class="detail-stat"><span class="label">🔖 Bookmarks</span><span class="value">' + (data.total || 0) + '</span></div>';
  } else if (type === 'statping') {
    html += '<div class="detail-stat"><span class="label">📊 Services</span><span class="value">' + (data.services || 0) + '</span></div>';
    html += '<div class="detail-stat"><span class="label">✅ Online</span><span class="value">' + (data.online || 0) + '</span></div>';
  } else {
    html += '<div class="empty">No details available for this integration type.</div>';
  }
  return html;
}

function _fmt(n) {
  if (n === undefined || n === null) return '—';
  return Number(n).toLocaleString();
}

function _fmtSpeed(bytes) {
  if (!bytes || bytes === 0) return '0 B/s';
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
  let i = 0;
  let b = parseFloat(bytes);
  while (b >= 1024 && i < units.length - 1) { b /= 1024; i++; }
  return b.toFixed(1) + ' ' + units[i];
}

function renderWidgets() {
  const el = document.getElementById('widgets-area');
  const enabled = widgetsCache.filter(w => w.enabled);
  if (!enabled.length) { el.innerHTML = ''; return; }
  el.innerHTML = enabled.map(w => renderWidget(w)).join('');
}

function renderWidget(w) {
  const data = w.cached_data || {};
  let content = '';

  if (w.type === 'weather') {
    content = '<div class="weather-widget">' +
      '<div class="temp">' + (data.icon || '🌤️') + ' ' +
      '<span>' + (data.temp_c || '—') + '</span>' +
      '<span class="unit">°C</span></div>' +
      '<div class="desc">' + esc(data.description || '') +
      ' · Feels like ' + (data.feels_like || '—') + '°C</div>' +
      '<div class="details">' +
      '<span>💧 ' + (data.humidity || '—') + '%</span>' +
      '<span>💨 ' + (data.wind_kmph || '—') + ' km/h</span>' +
      '<span>📍 ' + esc(data.city || '') + '</span></div></div>';

  } else if (w.type === 'system') {
    const ramColor = data.ram_percent > 90 ? 'var(--red)' : data.ram_percent > 70 ? 'var(--yellow)' : 'var(--green)';
    const diskColor = data.disk_percent > 90 ? 'var(--red)' : data.disk_percent > 70 ? 'var(--yellow)' : 'var(--green)';
    content = '<div class="system-widget">' +
      '<div class="stat"><span class="stat-label">⏱️ Uptime</span>' +
      '<span class="stat-value">' + (data.uptime_hours || '—') + 'h</span></div>' +
      '<div class="stat"><span class="stat-label">📊 Load</span>' +
      '<span class="stat-value">' + (data.load_1 || '—') + ' / ' + (data.load_5 || '—') + ' / ' + (data.load_15 || '—') + '</span></div>' +
      '<div class="stat"><span class="stat-label">🧠 RAM</span>' +
      '<span class="stat-value">' + (data.ram_used_gb || '—') + ' / ' + (data.ram_total_gb || '—') + ' GB (' + (data.ram_percent || '—') + '%)</span></div>' +
      '<div class="progress"><div class="progress-bar" style="width:' + (data.ram_percent || 0) + '%;background:' + ramColor + '"></div></div>' +
      '<div class="stat"><span class="stat-label">💾 Disk</span>' +
      '<span class="stat-value">' + (data.disk_used_gb || '—') + ' / ' + (data.disk_total_gb || '—') + ' GB (' + (data.disk_percent || '—') + '%)</span></div>' +
      '<div class="progress"><div class="progress-bar" style="width:' + (data.disk_percent || 0) + '%;background:' + diskColor + '"></div></div></div>';

  } else if (w.type === 'docker') {
    content = '<div class="docker-widget">';
    if (data.containers) {
      content += '<div class="summary">' +
        '<span class="summary-item"><span class="num">' + data.running + '</span> running</span>' +
        '<span class="summary-item"><span class="num">' + data.stopped + '</span> stopped</span>' +
        '<span class="summary-item"><span class="num">' + data.total + '</span> total</span></div>';
      content += data.containers.map(c =>
        '<div class="container-row"><span>' + esc(c.name) + '</span>' +
        (c.host && c.host !== 'local' ? '<span class="container-host">' + esc(c.host) + '</span>' : '') +
        '<span class="container-status ' + c.status + '">' + c.status + '</span></div>'
      ).join('');
      if (data.host_errors && data.host_errors.length) {
        content += data.host_errors.map(e =>
          '<div class="container-row" style="opacity:.6"><span>⚠️ ' + esc(e.host) + '</span><span class="container-status stopped">error</span></div>'
        ).join('');
      }
    } else if (data.error) {
      content += '<div class="empty">' + esc(data.error) + '</div>';
    }
    content += '</div>';

  } else if (w.type === 'clock') {
    content = '<div class="clock-widget">' +
      '<div class="time" id="clock-' + w.id + '">' + (data.time || '--:--:--') + '</div>' +
      '<div class="date">' + esc(data.date || '') + '</div>' +
      '<div class="timezone">' + esc(data.timezone || '') + '</div></div>';

  } else if (w.type === 'bookmarks') {
    content = '<div class="bookmarks-widget"><div class="bookmarks-grid">';
    const links = data.links || [];
    if (links.length) {
      content += links.map(l =>
        '<a class="bookmark-item" href="' + esc(l.url) + '" target="_blank" rel="noopener">' +
        '<div class="bookmark-icon">' + esc(l.icon || '🔗') + '</div>' +
        '<div class="bookmark-label">' + esc(l.name) + '</div></a>'
      ).join('');
    }
    content += '</div></div>';

  } else {
    content = '<div class="empty">Unknown widget type: ' + esc(w.type) + '</div>';
  }

  return '<div class="widget" data-widget-id="' + w.id + '">' +
    '<div class="widget-header">' +
    '<div class="widget-title">' + widgetEmoji(w.type) + ' ' + widgetLabel(w.type) + '</div>' +
    '<button class="widget-close" onclick="deleteWidget(' + w.id + ')" title="Remove">&times;</button>' +
    '</div>' + content + '</div>';
}

function widgetEmoji(t) {
  return { weather: '🌤️', system: '💻', docker: '🐳', clock: '🕐', bookmarks: '🔖' }[t] || '🧩';
}

function widgetLabel(t) {
  return { weather: 'Weather', system: 'System', docker: 'Docker', clock: 'Clock', bookmarks: 'Bookmarks' }[t] || t;
}

// ─── Widget Modal ─────────────────────────────────────────────────

function openWidgetModal() {
  document.getElementById('widget-modal-overlay').classList.add('active');
  showWidgetConfig();
}

function closeWidgetModal() {
  document.getElementById('widget-modal-overlay').classList.remove('active');
}

function showWidgetConfig() {
  const type = document.getElementById('w-type').value;
  document.getElementById('w-config-weather').classList.toggle('hidden', type !== 'weather');
  document.getElementById('w-config-clock').classList.toggle('hidden', type !== 'clock');
  document.getElementById('w-config-docker').classList.toggle('hidden', type !== 'docker');
}

let dockerHosts = [];
function addDockerHost() {
  const name = document.getElementById('dh-name').value.trim();
  const url = document.getElementById('dh-url').value.trim();
  if (!url) return;
  dockerHosts.push({ name: name || url, url });
  renderDockerHosts();
  document.getElementById('dh-name').value = '';
  document.getElementById('dh-url').value = '';
}
function removeDockerHost(i) {
  dockerHosts.splice(i, 1);
  renderDockerHosts();
}
function renderDockerHosts() {
  const el = document.getElementById('docker-hosts-list');
  el.innerHTML = dockerHosts.map((h, i) =>
    '<div class="docker-host-row"><span>🐳 ' + esc(h.name) + ' — <code>' + esc(h.url) + '</code></span>' +
    '<button class="icon-btn" onclick="removeDockerHost(' + i + ')">✕</button></div>'
  ).join('') || '<small style="opacity:.5">No remote hosts (will use local Docker)</small>';
}

async function saveWidget() {
  const type = document.getElementById('w-type').value;
  let config = {};
  if (type === 'weather') config = { city: document.getElementById('w-city').value };
  if (type === 'clock') config = { timezone: document.getElementById('w-tz').value };
  if (type === 'docker') config = { hosts: dockerHosts };
  if (type === 'bookmarks') config = { links: [] };

  const res = await api('/api/widgets', {
    method: 'POST',
    body: JSON.stringify({ type, config, enabled: true, sort_order: 0 })
  });
  if (!res || !res.ok) return alert('Error.');
  closeWidgetModal();
  await api('/api/widgets/reload');
  await loadWidgets();
  renderDashboard();
}

async function deleteWidget(id) {
  await api('/api/widgets/' + id, { method: 'DELETE' });
  await loadWidgets();
  renderDashboard();
}

// ─── Service Modal ────────────────────────────────────────────────

function openServiceModal(data = null) {
  fillCategorySelect('svc-category');
  document.getElementById('svc-modal-title').textContent = data ? 'Edit Service' : 'Add Service';
  document.getElementById('svc-id').value = data ? data.id : '';
  document.getElementById('svc-name').value = data ? data.name : '';
  document.getElementById('svc-url').value = data ? data.url : '';
  document.getElementById('svc-icon').value = data ? (data.icon || '') : '';
  document.getElementById('svc-desc').value = data ? (data.description || '') : '';
  document.getElementById('svc-category').value = data ? (data.category_id || '') : '';
  document.getElementById('svc-ping').value = data ? (data.ping_url || '') : '';
  document.getElementById('svc-fav').checked = data ? !!data.is_favorite : false;
  document.getElementById('service-modal-overlay').classList.add('active');
}

function closeServiceModal() {
  document.getElementById('service-modal-overlay').classList.remove('active');
}

function editService(s) {
  openServiceModal(s);
}

document.getElementById('service-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = document.getElementById('svc-id').value;
  const payload = {
    name: document.getElementById('svc-name').value.trim(),
    url: document.getElementById('svc-url').value.trim(),
    icon: document.getElementById('svc-icon').value.trim() || '🔗',
    description: document.getElementById('svc-desc').value.trim(),
    category_id: Number(document.getElementById('svc-category').value) || null,
    ping_url: document.getElementById('svc-ping').value.trim() || null,
    is_favorite: document.getElementById('svc-fav').checked ? 1 : 0,
    sort_order: 0,
  };
  const method = id ? 'PUT' : 'POST';
  const path = id ? '/api/services/' + id : '/api/services';
  const res = await api(path, { method, body: JSON.stringify(payload) });
  if (!res || !res.ok) return alert('Error saving service.');
  closeServiceModal();
  await loadServices();
  renderDashboard();
});

async function deleteService(id) {
  await api('/api/services/' + id, { method: 'DELETE' });
  await loadServices();
  renderDashboard();
  renderSettingsServices();
}

// ─── Settings Modal ───────────────────────────────────────────────

function openSettingsModal() {
  renderSettingsServices();
  renderSettingsWidgets();
  renderSettingsCategories();
  document.getElementById('settings-modal-overlay').classList.add('active');
}

function closeSettingsModal() {
  document.getElementById('settings-modal-overlay').classList.remove('active');
}

function renderSettingsServices() {
  const el = document.getElementById('settings-services');
  if (!servicesCache.length) {
    el.innerHTML = '<div class="empty">No services.</div>';
    return;
  }
  el.innerHTML = '<table class="detail-table"><thead><tr><th>Name</th><th>URL</th><th>Category</th><th></th></tr></thead><tbody>' +
    servicesCache.map(s =>
      '<tr><td>' + esc(s.icon) + ' ' + esc(s.name) + '</td>' +
      '<td style="color:var(--muted);font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(s.url) + '</td>' +
      '<td>' + esc(s.category_name || '—') + '</td>' +
      '<td style="white-space:nowrap">' +
      '<button class="icon-btn" onclick=\'editService(' + JSON.stringify(s).replace(/'/g, "&#39;") + ')\'>✏️</button> ' +
      '<button class="icon-btn danger" onclick="deleteService(' + s.id + ')">🗑️</button></td></tr>'
    ).join('') + '</tbody></table>';
}

function renderSettingsWidgets() {
  const el = document.getElementById('settings-widgets');
  if (!widgetsCache.length) {
    el.innerHTML = '<div class="empty">No widgets.</div>';
    return;
  }
  el.innerHTML = '<table class="detail-table"><thead><tr><th>Type</th><th>Config</th><th></th></tr></thead><tbody>' +
    widgetsCache.map(w =>
      '<tr><td>' + widgetEmoji(w.type) + ' ' + widgetLabel(w.type) + '</td>' +
      '<td style="font-size:11px;color:var(--muted)">' + esc(JSON.stringify(w.config)) + '</td>' +
      '<td><button class="icon-btn danger" onclick="deleteWidget(' + w.id + ');renderSettingsWidgets()">🗑️</button></td></tr>'
    ).join('') + '</tbody></table>';
}

function renderSettingsCategories() {
  const el = document.getElementById('settings-categories');
  if (!categoriesCache.length) {
    el.innerHTML = '<div class="empty">No categories.</div>';
    return;
  }
  el.innerHTML = '<table class="detail-table"><thead><tr><th>Name</th><th></th></tr></thead><tbody>' +
    categoriesCache.map(c =>
      '<tr><td>' + esc(c.icon) + ' ' + esc(c.name) + '</td>' +
      '<td><button class="icon-btn danger" onclick="deleteCategory(' + c.id + ')">🗑️</button></td></tr>'
    ).join('') + '</tbody></table>';
}

async function addCategory() {
  const name = document.getElementById('new-cat-name').value.trim();
  const icon = document.getElementById('new-cat-icon').value.trim() || '📂';
  if (!name) return;
  const res = await api('/api/categories', { method: 'POST', body: JSON.stringify({ name, icon }) });
  if (res && res.ok) {
    document.getElementById('new-cat-name').value = '';
    document.getElementById('new-cat-icon').value = '';
    await loadCategories();
    renderSettingsCategories();
  }
}

async function deleteCategory(id) {
  await api('/api/categories/' + id, { method: 'DELETE' });
  await loadCategories();
  await loadServices();
  renderSettingsCategories();
  renderDashboard();
}

// ─── Discovery ────────────────────────────────────────────────────

function openDiscoverModal() {
  document.getElementById('discover-modal-overlay').classList.add('active');
}

function closeDiscoverModal() {
  document.getElementById('discover-modal-overlay').classList.remove('active');
}

async function runDockerDiscover() {
  const el = document.getElementById('discover-results');
  el.innerHTML = '<div class="empty">Scanning Docker containers...</div>';
  const res = await api('/api/discover/docker');
  if (!res) return;
  const data = await res.json();
  if (!data.length) { el.innerHTML = '<div class="empty">No containers found.</div>'; return; }

  el.innerHTML = data.map(d =>
    '<div class="discover-item">' +
    '<div class="info"><span class="icon">' + esc(d.icon || '🐳') + '</span>' +
    '<div><div class="name">' + esc(d.name) + '</div>' +
    '<div class="host">Container: ' + esc(d.container || '—') + ' · Port: ' + (d.detected_port || '—') + '</div></div></div>' +
    '<button class="icon-btn" onclick=\'addDiscovered("' + esc(d.name) + '","http://localhost:' + (d.detected_port || '') + '","' + (d.icon || '🐳') + '")\'>+ Add</button></div>'
  ).join('');
}

async function runNetworkDiscover() {
  const el = document.getElementById('discover-results');
  el.innerHTML = '<div class="empty">Scanning network... (this may take 10-15 seconds)</div>';
  const res = await api('/api/discover/network', {
    method: 'POST',
    body: JSON.stringify({ hosts: [], ports: [] })
  });
  if (!res) return;
  const data = await res.json();
  if (!data.length) { el.innerHTML = '<div class="empty">No web services found.</div>'; return; }

  el.innerHTML = data.map(d =>
    '<div class="discover-item">' +
    '<div class="info"><span class="icon">🌐</span>' +
    '<div><div class="name">' + esc(d.title || d.host + ':' + d.port) + '</div>' +
    '<div class="host">' + esc(d.url) + ' · HTTP ' + d.status + '</div></div></div>' +
    '<button class="icon-btn" onclick=\'addDiscovered("' + esc(d.title || d.host + ':' + d.port) + '","' + esc(d.url) + '","🌐")\'>+ Add</button></div>'
  ).join('');
}

async function addDiscovered(name, url, icon) {
  const res = await api('/api/discover/add', {
    method: 'POST',
    body: JSON.stringify({ name, url, icon })
  });
  if (res && res.ok) {
    await loadServices();
    renderDashboard();
  }
}

// ─── WebSocket ────────────────────────────────────────────────────

function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(proto + '://' + location.host + '/ws');

  ws.onopen = () => {
    ws.send(JSON.stringify({ token }));
    const dot = document.getElementById('ws-dot');
    dot.className = 'conn-dot connected';
    dot.title = 'Connected';
  };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'status_update') {
      servicesCache = msg.data.services || servicesCache;
      renderDashboard();
    }
    if (msg.type === 'widgets_update') {
      loadWidgets().then(renderDashboard);
    }
  };

  ws.onclose = () => {
    const dot = document.getElementById('ws-dot');
    dot.className = 'conn-dot disconnected';
    dot.title = 'Disconnected';
    setTimeout(connectWs, 3000);
  };
}

// ─── Drag and Drop ────────────────────────────────────────────────

let dragSrcEl = null;
let dragCategoryId = null;

function initDragAndDrop() {
  document.querySelectorAll('.services-grid').forEach(grid => {
    grid.querySelectorAll('.service-card').forEach(card => {
      card.addEventListener('dragstart', handleDragStart);
      card.addEventListener('dragend', handleDragEnd);
      card.addEventListener('dragover', handleDragOver);
      card.addEventListener('dragenter', handleDragEnter);
      card.addEventListener('dragleave', handleDragLeave);
      card.addEventListener('drop', handleDrop);
    });
  });
}

function handleDragStart(e) {
  dragSrcEl = this;
  dragCategoryId = this.dataset.cat;
  this.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', this.dataset.sid);
  e.preventDefault();
}

function handleDragEnd() {
  this.classList.remove('dragging');
  document.querySelectorAll('.service-card').forEach(c => c.classList.remove('drag-over'));
}

function handleDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
}

function handleDragEnter(e) {
  e.preventDefault();
  if (this !== dragSrcEl) this.classList.add('drag-over');
}

function handleDragLeave() {
  this.classList.remove('drag-over');
}

async function handleDrop(e) {
  e.preventDefault();
  e.stopPropagation();
  this.classList.remove('drag-over');
  if (dragSrcEl === this) return;

  const srcId = parseInt(dragSrcEl.dataset.sid);
  const targetId = parseInt(this.dataset.sid);
  const targetCat = this.dataset.cat;

  const srcIdx = servicesCache.findIndex(s => s.id === srcId);
  const targetIdx = servicesCache.findIndex(s => s.id === targetId);
  if (srcIdx < 0 || targetIdx < 0) return;

  const [moved] = servicesCache.splice(srcIdx, 1);
  const newTargetIdx = servicesCache.findIndex(s => s.id === targetId);
  servicesCache.splice(newTargetIdx, 0, moved);

  if (targetCat && targetCat !== dragCategoryId) {
    moved.category_id = parseInt(targetCat) || null;
  }

  const catId = parseInt(targetCat) || null;
  const orderPayload = [];
  let sort = 0;
  servicesCache.filter(s => (s.category_id || null) === catId).forEach(s => {
    orderPayload.push({ id: s.id, sort_order: sort++, category_id: catId });
  });

  await api('/api/services/reorder', {
    method: 'PUT',
    body: JSON.stringify({ order: orderPayload })
  });

  renderDashboard();
}

// Patch renderDashboard to init drag
const _origRender = renderDashboard;
renderDashboard = function () {
  _origRender();
  setTimeout(initDragAndDrop, 50);
};

// ─── Logout ───────────────────────────────────────────────────────

function logout() {
  localStorage.removeItem('homedash_token');
  location.href = '/login';
}

// Prevent link click during drag
document.addEventListener('click', (e) => {
  const card = e.target.closest('.service-card');
  if (card && card.classList.contains('dragging')) {
    e.preventDefault();
    e.stopPropagation();
  }
}, true);

// ─── Modal overlay close on background click ──────────────────────

['service-modal-overlay', 'widget-modal-overlay', 'discover-modal-overlay', 'settings-modal-overlay', 'integration-modal-overlay', 'detail-modal-overlay'].forEach(id => {
  document.getElementById(id)?.addEventListener('click', (e) => {
    if (e.target.id === id) e.target.classList.remove('active');
  });
});

// ─── Keyboard Shortcuts ───────────────────────────────────────────

document.addEventListener('keydown', (e) => {
  // Escape to close modals
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
  }
  // Ctrl+N to add service
  if (e.ctrlKey && e.key === 'n') {
    e.preventDefault();
    openServiceModal();
  }
});
