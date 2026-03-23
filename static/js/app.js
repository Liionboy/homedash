// ─── Homedash — Frontend ──────────────────────────────────────────

const API = '';
let token = localStorage.getItem('homedash_token') || '';
let servicesCache = [];
let categoriesCache = [];
let widgetsCache = [];
let ws = null;

// ─── Helpers ──────────────────────────────────────────────────────

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
function getHeaders() { return { 'x-session': token, 'Content-Type': 'application/json' }; }
async function api(path, opts = {}) {
    const res = await fetch(API + path, { headers: getHeaders(), ...opts });
    if (res.status === 401) { localStorage.removeItem('homedash_token'); location.href = '/login'; return null; }
    return res;
}

// ─── Init ─────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
    if (!token) { location.href = '/login'; return; }
    const auth = await api('/api/check-auth');
    if (!auth || !auth.ok) { location.href = '/login'; return; }
    await Promise.all([loadCategories(), loadServices(), loadWidgets()]);
    connectWs();
    renderDashboard();
});

// ─── Tabs ─────────────────────────────────────────────────────────

function switchTab(name) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    ['dashboard', 'services', 'widgets'].forEach(t => {
        const el = document.getElementById('tab-' + t);
        if (el) el.classList.toggle('hidden', t !== name);
    });
    if (name === 'services') renderServicesManager();
    if (name === 'widgets') renderWidgetsManager();
}

// ─── Categories ───────────────────────────────────────────────────

async function loadCategories() {
    const res = await api('/api/categories');
    if (res) categoriesCache = await res.json();
}
function fillCategorySelect(selectId) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    sel.innerHTML = '<option value="">— None —</option>' + categoriesCache.map(c => '<option value="' + c.id + '">' + esc(c.icon) + ' ' + esc(c.name) + '</option>').join('');
}

// ─── Services ─────────────────────────────────────────────────────

async function loadServices() {
    const res = await api('/api/services');
    if (res) servicesCache = await res.json();
}

function renderDashboard() {
    renderWidgets();
    renderDashboardServices();
}

function renderDashboardServices() {
    const el = document.getElementById('dashboard-services');
    const favs = servicesCache.filter(s => s.is_favorite);
    const byCategory = {};
    servicesCache.forEach(s => {
        const cat = s.category_name || 'Uncategorized';
        if (!byCategory[cat]) byCategory[cat] = { icon: '', services: [] };
        if (s.category_id) {
            const catObj = categoriesCache.find(c => c.id === s.category_id);
            if (catObj) byCategory[cat].icon = catObj.icon;
        }
        byCategory[cat].services.push(s);
    });

    let html = '';

    // Favorites
    if (favs.length) {
        html += '<div class="category-section"><div class="category-title">⭐ Favorites</div><div class="services-grid">';
        html += favs.map(s => serviceCard(s)).join('');
        html += '</div></div>';
    }

    // By category
    for (const [catName, data] of Object.entries(byCategory)) {
        html += '<div class="category-section"><div class="category-title">' + (data.icon || '📂') + ' ' + esc(catName) + '</div><div class="services-grid">';
        html += data.services.map(s => serviceCard(s)).join('');
        html += '</div></div>';
    }

    if (!servicesCache.length) {
        html = '<div class="empty">No services yet. Click <strong>➕ Service</strong> or <strong>🔍 Discover</strong> to get started.</div>';
    }
    el.innerHTML = html;
}

function serviceCard(s) {
    const statusClass = s.online === true ? 'online' : s.online === false ? 'offline' : 'unknown';
    const ping = s.response_ms ? '<span class="ping">' + s.response_ms + 'ms</span>' : '';
    return '<a class="service-card" href="' + esc(s.url) + '" target="_blank" rel="noopener" draggable="true" data-sid="' + s.id + '" data-cat="' + (s.category_id || '') + '">' +
        '<div class="status-dot ' + statusClass + '"></div>' +
        '<div class="icon">' + esc(s.icon || '🔗') + '</div>' +
        '<div class="name">' + esc(s.name) + '</div>' +
        (s.description ? '<div class="desc">' + esc(s.description) + '</div>' : '') +
        ping + '</a>';
}

// ─── Services Manager ─────────────────────────────────────────────

function renderServicesManager() {
    const el = document.getElementById('services-manager');
    if (!servicesCache.length) { el.innerHTML = '<div class="empty">No services. Add one or use Discover.</div>'; return; }
    el.innerHTML = '<table class="detail-table"><thead><tr><th>Name</th><th>URL</th><th>Category</th><th>Ping</th><th></th></tr></thead><tbody>' +
        servicesCache.map(s =>
            '<tr draggable="true" data-id="' + s.id + '">' +
            '<td>' + esc(s.icon) + ' ' + esc(s.name) + '</td>' +
            '<td style="color:var(--muted);font-size:12px">' + esc(s.url) + '</td>' +
            '<td>' + esc(s.category_name || '—') + '</td>' +
            '<td>' + (s.ping_url ? '✅' : '—') + '</td>' +
            '<td><button class="icon-btn" onclick=\'editService(' + JSON.stringify(s).replace(/'/g, "\\'") + ')\'>Edit</button> <button class="icon-btn danger" onclick="deleteService(' + s.id + ')">Del</button></td></tr>'
        ).join('') +
        '</tbody></table>';
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
function closeServiceModal() { document.getElementById('service-modal-overlay').classList.remove('active'); }
function editService(s) { openServiceModal(s); }

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
    renderServicesManager();
});

async function deleteService(id) {
    if (!confirm('Delete this service?')) return;
    await api('/api/services/' + id, { method: 'DELETE' });
    await loadServices();
    renderDashboard();
    renderServicesManager();
}

// ─── Widgets ──────────────────────────────────────────────────────

async function loadWidgets() {
    const res = await api('/api/widgets');
    if (res) widgetsCache = await res.json();
}

function renderWidgets() {
    const el = document.getElementById('widgets-area');
    if (!widgetsCache.length) { el.innerHTML = ''; return; }
    el.innerHTML = widgetsCache.filter(w => w.enabled).map(w => renderWidget(w)).join('');
}

function renderWidget(w) {
    const data = w.cached_data || {};
    let content = '';

    if (w.type === 'weather') {
        content = '<div class="weather-widget">' +
            '<div class="temp">' + (data.icon || '🌤️') + ' ' + (data.temp_c || '—') + '°C</div>' +
            '<div class="desc">' + esc(data.description || '') + ' · Feels like ' + (data.feels_like || '—') + '°C</div>' +
            '<div class="details"><span>💧 ' + (data.humidity || '—') + '%</span><span>💨 ' + (data.wind_kmph || '—') + ' km/h</span></div></div>';
    } else if (w.type === 'system') {
        content = '<div class="system-widget">' +
            '<div class="stat"><span class="stat-label">Uptime</span><span class="stat-value">' + (data.uptime_hours || '—') + 'h</span></div>' +
            '<div class="stat"><span class="stat-label">Load</span><span class="stat-value">' + (data.load_1 || '—') + ' / ' + (data.load_5 || '—') + ' / ' + (data.load_15 || '—') + '</span></div>' +
            '<div class="stat"><span class="stat-label">RAM</span><span class="stat-value">' + (data.ram_used_gb || '—') + ' / ' + (data.ram_total_gb || '—') + ' GB (' + (data.ram_percent || '—') + '%)</span></div>' +
            '<div class="progress"><div class="progress-bar" style="width:' + (data.ram_percent || 0) + '%;background:' + (data.ram_percent > 90 ? 'var(--red)' : data.ram_percent > 70 ? 'var(--yellow)' : 'var(--green)') + '"></div></div>' +
            '<div class="stat"><span class="stat-label">Disk</span><span class="stat-value">' + (data.disk_used_gb || '—') + ' / ' + (data.disk_total_gb || '—') + ' GB (' + (data.disk_percent || '—') + '%)</span></div>' +
            '<div class="progress"><div class="progress-bar" style="width:' + (data.disk_percent || 0) + '%;background:' + (data.disk_percent > 90 ? 'var(--red)' : data.disk_percent > 70 ? 'var(--yellow)' : 'var(--green)') + '"></div></div></div>';
    } else if (w.type === 'docker') {
        content = '<div class="docker-widget">';
        if (data.containers) {
            content += '<div style="margin-bottom:8px;font-size:13px"><b>' + data.running + '</b> running · <b>' + data.stopped + '</b> stopped · <b>' + data.total + '</b> total</div>';
            content += data.containers.map(c =>
                '<div class="container-row"><span>' + esc(c.name) + '</span><span class="container-status ' + c.status + '">' + c.status + '</span></div>'
            ).join('');
        } else if (data.error) {
            content += '<div class="empty">' + esc(data.error) + '</div>';
        }
        content += '</div>';
    } else if (w.type === 'clock') {
        content = '<div class="clock-widget"><div class="time" id="clock-' + w.id + '">' + (data.time || '--:--:--') + '</div><div class="date">' + esc(data.date || '') + '</div></div>';
    } else {
        content = '<div class="empty">Unknown widget type: ' + esc(w.type) + '</div>';
    }

    return '<div class="widget" data-widget-id="' + w.id + '">' +
        '<div class="widget-header"><div class="widget-title">' + widgetEmoji(w.type) + ' ' + widgetLabel(w.type) + '</div>' +
        '<button class="widget-close" onclick="deleteWidget(' + w.id + ')" title="Remove">&times;</button></div>' +
        content + '</div>';
}

function widgetEmoji(t) { return { weather: '🌤️', system: '💻', docker: '🐳', clock: '🕐' }[t] || '🧩'; }
function widgetLabel(t) { return { weather: 'Weather', system: 'System', docker: 'Docker', clock: 'Clock' }[t] || t; }

// ─── Widget Modal ─────────────────────────────────────────────────

function openWidgetModal() { document.getElementById('widget-modal-overlay').classList.add('active'); showWidgetConfig(); }
function closeWidgetModal() { document.getElementById('widget-modal-overlay').classList.remove('active'); }
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
    const res = await api('/api/widgets', { method: 'POST', body: JSON.stringify({ type, config, enabled: true, sort_order: 0 }) });
    if (!res || !res.ok) return alert('Error.');
    closeWidgetModal();
    await loadWidgets();
    // Force reload widget data
    await api('/api/widgets/reload');
    await loadWidgets();
    renderDashboard();
}

async function deleteWidget(id) {
    if (!confirm('Remove this widget?')) return;
    await api('/api/widgets/' + id, { method: 'DELETE' });
    await loadWidgets();
    renderDashboard();
}

// ─── Widgets Manager ──────────────────────────────────────────────

function renderWidgetsManager() {
    const el = document.getElementById('widgets-manager');
    if (!widgetsCache.length) { el.innerHTML = '<div class="empty">No widgets. Click <strong>➕ Widget</strong> to add one.</div>'; return; }
    el.innerHTML = '<table class="detail-table"><thead><tr><th>Type</th><th>Config</th><th>Status</th><th></th></tr></thead><tbody>' +
        widgetsCache.map(w =>
            '<tr><td>' + widgetEmoji(w.type) + ' ' + widgetLabel(w.type) + '</td>' +
            '<td style="font-size:12px;color:var(--muted)">' + esc(JSON.stringify(w.config)) + '</td>' +
            '<td>' + (w.enabled ? '✅ Active' : '❌ Disabled') + '</td>' +
            '<td><button class="icon-btn danger" onclick="deleteWidget(' + w.id + ')">Del</button></td></tr>'
        ).join('') +
        '</tbody></table>';
}

// ─── Discovery ────────────────────────────────────────────────────

function openDiscoverModal() { document.getElementById('discover-modal-overlay').classList.add('active'); }
function closeDiscoverModal() { document.getElementById('discover-modal-overlay').classList.remove('active'); }

async function runDockerDiscover() {
    const el = document.getElementById('discover-results');
    el.innerHTML = '<div class="empty">Scanning Docker containers...</div>';
    const res = await api('/api/discover/docker');
    if (!res) return;
    const data = await res.json();
    if (!data.length) { el.innerHTML = '<div class="empty">No containers found.</div>'; return; }
    fillCategorySelect(''); // ensure categories loaded
    el.innerHTML = data.map(d =>
        '<div class="discover-item">' +
        '<div class="info"><span class="icon">' + esc(d.icon || '🐳') + '</span><div><div class="name">' + esc(d.name) + '</div><div class="host">Container: ' + esc(d.container || '—') + ' · Port: ' + (d.detected_port || '—') + '</div></div></div>' +
        '<button class="icon-btn" onclick=\'addDiscovered("' + esc(d.name) + '","http://localhost:' + (d.detected_port || '') + '","' + (d.icon || '🐳') + '")\'>+ Add</button></div>'
    ).join('');
}

async function runNetworkDiscover() {
    const el = document.getElementById('discover-results');
    el.innerHTML = '<div class="empty">Scanning network... (this may take 10-15 seconds)</div>';
    const res = await api('/api/discover/network', { method: 'POST', body: JSON.stringify({ hosts: [], ports: [] }) });
    if (!res) return;
    const data = await res.json();
    if (!data.length) { el.innerHTML = '<div class="empty">No web services found.</div>'; return; }
    el.innerHTML = data.map(d =>
        '<div class="discover-item">' +
        '<div class="info"><span class="icon">🌐</span><div><div class="name">' + esc(d.title || d.host + ':' + d.port) + '</div><div class="host">' + esc(d.url) + ' · HTTP ' + d.status + '</div></div></div>' +
        '<button class="icon-btn" onclick=\'addDiscovered("' + esc(d.title || d.host + ':' + d.port) + '","' + esc(d.url) + '","🌐")\'>+ Add</button></div>'
    ).join('');
}

async function addDiscovered(name, url, icon) {
    const res = await api('/api/discover/add', { method: 'POST', body: JSON.stringify({ name, url, icon }) });
    if (res && res.ok) {
        await loadServices();
        renderDashboard();
        alert('Added: ' + name);
    }
}

// ─── WebSocket ────────────────────────────────────────────────────

function connectWs() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(proto + '://' + location.host + '/ws');
    ws.onopen = () => {
        ws.send(JSON.stringify({ token }));
        document.getElementById('ws-dot').className = 'conn-dot connected';
        document.getElementById('ws-dot').title = 'Connected';
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
        document.getElementById('ws-dot').className = 'conn-dot disconnected';
        document.getElementById('ws-dot').title = 'Disconnected';
        setTimeout(connectWs, 3000);
    };
}

// ─── Logout ───────────────────────────────────────────────────────

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
    // Prevent link navigation while dragging
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

    // Get parent grid to find all cards in order
    const grid = this.closest('.services-grid');
    const cards = [...grid.querySelectorAll('.service-card')];

    // Reorder in cache
    const srcIdx = servicesCache.findIndex(s => s.id === srcId);
    const targetIdx = servicesCache.findIndex(s => s.id === targetId);
    if (srcIdx < 0 || targetIdx < 0) return;

    // Move in array
    const [moved] = servicesCache.splice(srcIdx, 1);
    const newTargetIdx = servicesCache.findIndex(s => s.id === targetId);
    servicesCache.splice(newTargetIdx, 0, moved);

    // Update category if dropped in different grid
    if (targetCat && targetCat !== dragCategoryId) {
        moved.category_id = parseInt(targetCat) || null;
    }

    // Build order payload for the category
    const catId = parseInt(targetCat) || null;
    const orderPayload = [];
    let sort = 0;
    servicesCache.filter(s => (s.category_id || null) === catId).forEach(s => {
        orderPayload.push({ id: s.id, sort_order: sort++, category_id: catId });
    });

    // Send to API
    await api('/api/services/reorder', { method: 'PUT', body: JSON.stringify({ order: orderPayload }) });

    // Re-render
    renderDashboard();
    renderServicesManager();
}

// Initialize drag after each render
const origRenderDashboard = renderDashboardServices;
// Patch: call initDragAndDrop after rendering
const _origRender = renderDashboard;
renderDashboard = function() {
    _origRender();
    setTimeout(initDragAndDrop, 50);
};

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

['service-modal-overlay','widget-modal-overlay','discover-modal-overlay'].forEach(id => {
    document.getElementById(id)?.addEventListener('click', (e) => { if (e.target.id === id) e.target.classList.remove('active'); });
});
