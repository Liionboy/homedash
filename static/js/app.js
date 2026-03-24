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
  const intBtn = '<button class="integration-config-btn" onclick="event.preventDefault();event.stopPropagation();openDetailModal(' + s.id + ')" title="Details">' + (intg ? '📊' : '🔗') + '</button>';

  return '<a class="service-card" href="' + esc(s.url) + '" target="_blank" rel="noopener"' +
    ' draggable="true" data-sid="' + s.id + '" data-cat="' + (s.category_id || '') + '">' +
    '<div class="status-indicator ' + statusClass + '"></div>' +
    '<div class="card-icon">' + esc(s.icon || '🔗') + '</div>' +
    '<div class="card-info">' +
    '<div class="card-name">' + esc(s.name) + '</div>' +
    (s.description ? '<div class="card-desc">' + esc(s.description) + '</div>' : '') +
    ping + intBadge + '</div>' + intBtn + '</a>';
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
  // Check integrationsCache first (for credentials/config), then service data
  const cached = integrationsCache.find(i => i.service_id === serviceId);
  const svc = servicesCache.find(s => s.id === serviceId);
  if (svc && svc.integration && svc.integration.data) {
    return { ...svc.integration, service_id: serviceId };
  }
  return cached || null;
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
    html += '<div class="detail-stat"><span class="label">📊 Entities</span><span class="value">' + (data.entities || '—') + '</span></div>';
    html += '<div class="detail-stat"><span class="label">📐 Units</span><span class="value">' + esc(data.unit_system || '—') + '</span></div>';
    if (data.top_domains && data.top_domains.length) {
      html += '<div class="detail-section-title">Top Entity Domains</div>';
      data.top_domains.forEach(d => {
        html += '<div class="detail-stat"><span class="label">' + esc(d.domain) + '</span><span class="value">' + d.count + '</span></div>';
      });
    }
  } else if (type === 'unifi') {
    html += '<div class="detail-stat"><span class="label">👥 Clients</span><span class="value">' + (data.clients_total || 0) + ' (' + (data.clients_wireless || 0) + ' WiFi, ' + (data.clients_wired || 0) + ' wired)</span></div>';
    html += '<div class="detail-stat"><span class="label">📡 Devices</span><span class="value">' + (data.devices_total || 0) + ' (' + (data.devices_connected || 0) + ' connected)</span></div>';
    if (data.health && data.health.length) {
      html += '<div class="detail-section-title">System Health</div>';
      data.health.forEach(h => {
        const status = h.status === 'ok' ? '✅' : '❌';
        html += '<div class="detail-stat"><span class="label">' + status + ' ' + esc(h.subsystem) + '</span><span class="value">' + esc(h.status) + '</span></div>';
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
  }
  return html;
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
        '<span class="container-status ' + c.status + '">' + c.status + '</span></div>'
      ).join('');
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
}

async function saveWidget() {
  const type = document.getElementById('w-type').value;
  let config = {};
  if (type === 'weather') config = { city: document.getElementById('w-city').value };
  if (type === 'clock') config = { timezone: document.getElementById('w-tz').value };
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
