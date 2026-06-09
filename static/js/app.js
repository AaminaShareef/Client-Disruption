// ══════════════════════════════════════════════════════════
//  STATE
// ══════════════════════════════════════════════════════════
let suppliers  = [];
let materials  = [];
let logistics  = [];
let facilities = [];
let _lastData  = null;   // last /analyze response (for export)

// ══════════════════════════════════════════════════════════
//  ENTITY MANAGEMENT
// ══════════════════════════════════════════════════════════
function updateCounters() {
    document.getElementById('supplierCount').textContent  = suppliers.length;
    document.getElementById('materialCount').textContent  = materials.length;
    document.getElementById('logisticsCount').textContent = logistics.length;
    document.getElementById('facilityCount').textContent  = facilities.length;
}

function addEntity(type) {
    if (type === 'supplier')  { suppliers.push({ name:'', material:'', location:'' }); renderSuppliers(); }
    if (type === 'material')  { materials.push({ commodity:'', region:'' });            renderMaterials(); }
    if (type === 'logistics') { logistics.push({ port:'', carrier:'', route:'' });      renderLogistics(); }
    if (type === 'facility')  { facilities.push({ name:'', location:'' });              renderFacilities(); }
    updateCounters();
}

function removeEntity(type, idx) {
    if (type === 'supplier')  { suppliers.splice(idx,1);  renderSuppliers(); }
    if (type === 'material')  { materials.splice(idx,1);  renderMaterials(); }
    if (type === 'logistics') { logistics.splice(idx,1);  renderLogistics(); }
    if (type === 'facility')  { facilities.splice(idx,1); renderFacilities(); }
    updateCounters();
}

function updateSupplier(i,f,v)  { suppliers[i][f] = v; }
function updateMaterial(i,f,v)  { materials[i][f] = v; }
function updateLogistics(i,f,v) { logistics[i][f] = v; }
function updateFacility(i,f,v)  { facilities[i][f] = v; }

function esc(s) {
    if (!s) return '';
    return String(s).replace(/[&<>"']/g, c =>
        ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}

// ══════════════════════════════════════════════════════════
//  RENDER ENTITY FORMS
// ══════════════════════════════════════════════════════════
function renderSuppliers() {
    const el = document.getElementById('suppliersList');
    if (!suppliers.length) { el.innerHTML = '<div class="empty-state">No suppliers added</div>'; return; }
    el.innerHTML = suppliers.map((s,i) => `
        <div class="detail-item">
            <div class="detail-header">
                <span class="detail-index">${i+1}</span>
                <button class="btn-remove" onclick="removeEntity('supplier',${i})"><i class="fas fa-trash-alt"></i></button>
            </div>
            <input class="input-field mb-1" placeholder="Supplier name" value="${esc(s.name)}" oninput="updateSupplier(${i},'name',this.value)">
            <div class="input-row">
                <input class="input-field" placeholder="Material provided" value="${esc(s.material)}" oninput="updateSupplier(${i},'material',this.value)">
                <input class="input-field" placeholder="Country / location" value="${esc(s.location)}" oninput="updateSupplier(${i},'location',this.value)">
            </div>
        </div>`).join('');
}

function renderMaterials() {
    const el = document.getElementById('materialsList');
    if (!materials.length) { el.innerHTML = '<div class="empty-state">No materials added</div>'; return; }
    el.innerHTML = materials.map((m,i) => `
        <div class="detail-item">
            <div class="detail-header">
                <span class="detail-index">${i+1}</span>
                <button class="btn-remove" onclick="removeEntity('material',${i})"><i class="fas fa-trash-alt"></i></button>
            </div>
            <div class="input-row">
                <input class="input-field" placeholder="Commodity (e.g., lithium)" value="${esc(m.commodity)}" oninput="updateMaterial(${i},'commodity',this.value)">
                <input class="input-field" placeholder="Source region / country" value="${esc(m.region)}" oninput="updateMaterial(${i},'region',this.value)">
            </div>
        </div>`).join('');
}

function renderLogistics() {
    const el = document.getElementById('logisticsList');
    if (!logistics.length) { el.innerHTML = '<div class="empty-state">No logistics nodes added</div>'; return; }
    el.innerHTML = logistics.map((l,i) => `
        <div class="detail-item">
            <div class="detail-header">
                <span class="detail-index">${i+1}</span>
                <button class="btn-remove" onclick="removeEntity('logistics',${i})"><i class="fas fa-trash-alt"></i></button>
            </div>
            <input class="input-field mb-1" placeholder="Port / terminal" value="${esc(l.port)}" oninput="updateLogistics(${i},'port',this.value)">
            <div class="input-row">
                <input class="input-field" placeholder="Carrier / forwarder" value="${esc(l.carrier)}" oninput="updateLogistics(${i},'carrier',this.value)">
                <input class="input-field" placeholder="Trade route (e.g., Red Sea)" value="${esc(l.route)}" oninput="updateLogistics(${i},'route',this.value)">
            </div>
        </div>`).join('');
}

function renderFacilities() {
    const el = document.getElementById('facilitiesList');
    if (!facilities.length) { el.innerHTML = '<div class="empty-state">No facilities added</div>'; return; }
    el.innerHTML = facilities.map((f,i) => `
        <div class="detail-item">
            <div class="detail-header">
                <span class="detail-index">${i+1}</span>
                <button class="btn-remove" onclick="removeEntity('facility',${i})"><i class="fas fa-trash-alt"></i></button>
            </div>
            <div class="input-row">
                <input class="input-field" placeholder="Facility name" value="${esc(f.name)}" oninput="updateFacility(${i},'name',this.value)">
                <input class="input-field" placeholder="Location / city" value="${esc(f.location)}" oninput="updateFacility(${i},'location',this.value)">
            </div>
        </div>`).join('');
}

// ══════════════════════════════════════════════════════════
//  LOADING OVERLAY STEPPER
// ══════════════════════════════════════════════════════════
let _stepTimer = null;

const _LOADING_STEPS = [
    { id: 'ls1', pct: 8,  sub: 'Mapping your supply chain exposure…'   },
    { id: 'ls2', pct: 30, sub: 'Pulling news from multiple sources…'   },
    { id: 'ls3', pct: 55, sub: 'Ranking articles by disruption signal…'},
    { id: 'ls4', pct: 78, sub: 'Running NLP pipeline…'                 },
    { id: 'ls5', pct: 95, sub: 'Almost done…'                          },
];
// Cumulative delays (ms) at which each step becomes active
const _STEP_DELAYS = [0, 1800, 4000, 7000, 11000];

function _applyStep(idx) {
    const step = _LOADING_STEPS[idx];
    if (!step) return;

    // Mark previous step done
    if (idx > 0) {
        const prev = document.getElementById(_LOADING_STEPS[idx - 1].id);
        if (prev) { prev.classList.remove('active'); prev.classList.add('done'); }
    }

    // Activate current step
    const curr = document.getElementById(step.id);
    if (curr) curr.classList.add('active');

    // Advance progress bar
    const bar = document.getElementById('loadingProgressBar');
    if (bar) bar.style.width = step.pct + '%';

    // Update subtitle
    const sub = document.getElementById('loadingSubtitle');
    if (sub) sub.textContent = step.sub;
}

function showLoading() {
    // Reset all steps
    _LOADING_STEPS.forEach(s => {
        const el = document.getElementById(s.id);
        if (el) el.classList.remove('active', 'done');
    });

    // Reset progress bar and subtitle
    const bar = document.getElementById('loadingProgressBar');
    const sub = document.getElementById('loadingSubtitle');
    if (bar) bar.style.width = '0%';
    if (sub) sub.textContent = 'This typically takes 15–30 seconds';

    document.getElementById('loadingOverlay').style.display = 'flex';

    // Activate step 0 immediately, schedule the rest
    _applyStep(0);

    _stepTimer = [];
    for (let i = 1; i < _LOADING_STEPS.length; i++) {
        const idx = i;
        _stepTimer.push(setTimeout(() => _applyStep(idx), _STEP_DELAYS[i]));
    }
}

function hideLoading() {
    if (_stepTimer) { _stepTimer.forEach(clearTimeout); _stepTimer = null; }

    // Flash all steps green before hiding
    _LOADING_STEPS.forEach(s => {
        const el = document.getElementById(s.id);
        if (el) { el.classList.remove('active'); el.classList.add('done'); }
    });
    const bar = document.getElementById('loadingProgressBar');
    if (bar) bar.style.width = '100%';
    const sub = document.getElementById('loadingSubtitle');
    if (sub) sub.textContent = 'Done!';

    setTimeout(() => {
        document.getElementById('loadingOverlay').style.display = 'none';
    }, 350);
}

// ══════════════════════════════════════════════════════════
//  MAIN ANALYZE FLOW  — fully automated, no user steps
// ══════════════════════════════════════════════════════════
async function analyzeProfile() {
    const clientName = document.getElementById('clientName').value.trim() || 'Unnamed Client';

    // Reset UI
    document.getElementById('errorBox').style.display       = 'none';
    document.getElementById('resultsSection').style.display = 'none';
    document.getElementById('analyzeBtn').disabled          = true;

    showLoading();
    document.getElementById('loadingOverlay').scrollIntoView({ behavior: 'smooth', block: 'center' });

    // Build payload
    const tier1_suppliers = suppliers.map(s => ({
        name:     s.name,
        material: s.material,
        country:  s.location,
        city:     '',
    }));

    const logistics_nodes = logistics.flatMap(l => {
        const nodes = [];
        if (l.port)  nodes.push({ name: l.port,  type: 'port',  carrier: l.carrier || '' });
        if (l.route) nodes.push({ name: l.route, type: 'route' });
        return nodes;
    }).filter(n => n.name.trim());

    const payload = {
        client_name:     clientName,
        tier1_suppliers: tier1_suppliers,
        raw_materials:   materials,
        logistics_nodes: logistics_nodes,
        own_facilities:  facilities,
    };

    try {
        const res  = await fetch('/analyze', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(payload),
        });

        const data = await res.json();

        if (data.status !== 'success') {
            throw new Error(data.message || 'Server returned an error');
        }

        _lastData = data;

        hideLoading();

        // Show results
        document.getElementById('resultsSection').style.display = 'block';
        displayResults(data);
        document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth', block: 'start' });

    } catch (err) {
        console.error(err);
        hideLoading();
        const eb = document.getElementById('errorBox');
        document.getElementById('errorMsg').textContent = err.message || 'Could not reach the server. Is Flask running?';
        eb.style.display = 'block';
        eb.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } finally {
        document.getElementById('analyzeBtn').disabled = false;
    }
}

// ══════════════════════════════════════════════════════════
//  DISPLAY RESULTS  — renders everything automatically
// ══════════════════════════════════════════════════════════
function displayResults(data) {

    // ── Risk header ──────────────────────────────────────
    document.getElementById('clientNameDisplay').textContent = data.client_name;
    document.getElementById('timestampDisplay').innerHTML =
        `<i class="far fa-clock me-1"></i>${data.analysis_timestamp}`;

    const riskColors = {
        HIGH:   { bg:'var(--orange-l)', color:'var(--orange)', border:'#FED7AA' },
        MEDIUM: { bg:'var(--amber-l)',  color:'var(--amber)',  border:'#FDE68A' },
        LOW:    { bg:'var(--green-l)',  color:'var(--green)',  border:'#A7F3D0' },
    };
    const rc = riskColors[data.overall_risk] || riskColors.LOW;
    const badge = document.getElementById('riskBadge');
    badge.innerHTML = `<i class="fas fa-shield-alt"></i> ${data.overall_risk} RISK`;
    badge.style.cssText = `background:${rc.bg};color:${rc.color};border:1px solid ${rc.border};`;
    document.getElementById('riskMessage').textContent = data.risk_message;
    document.getElementById('riskScore').innerHTML =
        `${data.risk_score}<span style="font-size:.65rem;font-family:'DM Mono',monospace;">/100</span>`;

    // ── Exposure map chips ───────────────────────────────
    const em = data.exposure_map;
    if (em && Object.values(em).some(v => Array.isArray(v) && v.length)) {
        const sec   = document.getElementById('exposureSection');
        const chips = document.getElementById('exposureChips');
        sec.style.display = 'block';
        const renderGroup = (label, items, cls, icon) => {
            if (!items || !items.length) return '';
            return `<div class="exposure-group">
                <div class="exposure-group-label"><i class="${icon} me-1"></i>${label}</div>
                ${items.map(v => `<span class="chip ${cls}">${esc(v)}</span>`).join('')}
            </div>`;
        };
        chips.innerHTML =
            renderGroup('Countries',    em.countries,  'chip-country',  'fas fa-globe')  +
            renderGroup('Materials',    em.materials,  'chip-material', 'fas fa-cubes')  +
            renderGroup('Ports',        em.ports,      'chip-port',     'fas fa-anchor') +
            renderGroup('Trade Routes', em.routes,     'chip-route',    'fas fa-route')  +
            renderGroup('Suppliers',    em.suppliers,  'chip-supplier', 'fas fa-truck');
    }

    // ── Stats row ────────────────────────────────────────
    if (data.stats) {
        const sr = document.getElementById('statsRow');
        sr.style.display = 'flex';
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set('stTotal',    data.stats.total_articles      || 0);
        set('stDeduped',  data.stats.deduplicated_articles || data.stats.preprocessed_articles || 0);
        set('stAlerts',   (data.stats.high_alerts || 0) + (data.stats.medium_alerts || 0));
        set('stClusters', data.stats.event_clusters != null ? data.stats.event_clusters : '—');
    }

    // ── Event clusters ───────────────────────────────────
    renderClusters(data.clusters || []);

    // ── News feed ────────────────────────────────────────
    renderNewsFeed(data.news || []);
}

// ══════════════════════════════════════════════════════════
//  NEWS FEED RENDERER
// ══════════════════════════════════════════════════════════
function renderNewsFeed(articles) {
    const feed  = document.getElementById('newsFeed');
    const badge = document.getElementById('articleCountBadge');
    badge.textContent = `${articles.length} articles`;

    if (!articles.length) {
        feed.innerHTML = `
            <div class="text-center py-5" style="color:var(--text-3);">
                <i class="fas fa-newspaper fa-3x mb-3 opacity-50"></i>
                <p>No relevant news found for this supply chain profile.</p>
                <small>Tip: Add more suppliers, materials or logistics nodes, or check your .env API keys.</small>
            </div>`;
        return;
    }

    feed.innerHTML = articles.map(a => _renderNewsCard(a)).join('');
}

function _renderNewsCard(a) {
    const level   = a.impact_level || 'LOW';
    const score   = a.relevance_score || 0;
    const srcType = (a.fetch_method || 'RSS').toUpperCase()
        .replace('GOOGLE_NEWS_RSS', 'GNEWS');
    const srcCls  = { NEWSAPI:'newsapi', GNEWS:'gnews', GDELT:'gdelt' }[srcType] || '';

    let dateStr = '';
    try {
        const d = new Date(a.published || '');
        if (!isNaN(d)) dateStr = d.toLocaleDateString('en-US', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' });
    } catch(_) {}

    const entityChips = (a.matched_entities || []).slice(0, 5)
        .map(e => `<span class="matched-entity-tag">${esc(e)}</span>`).join('');

    const clusterBadge = a.cluster_size > 1
        ? `<span class="cluster-size-chip" style="font-size:.62rem;"><i class="fas fa-layer-group me-1"></i>${a.cluster_size} in cluster</span>`
        : '';

    const semanticBadge = a.semantic_category && a.semantic_category !== 'unknown'
        ? `<span class="api-source-tag" style="font-size:.62rem;background:#F5F3FF;color:var(--purple);border-color:#DDD6FE;">${esc(a.semantic_category.replace('_',' '))}</span>`
        : '';

    const summary = a.summary || a.description || a.clean_body || '';

    const isReal = a.url && a.url !== '#';
    const readBtn = isReal
        ? `<a href="${esc(a.url)}" target="_blank" rel="noopener" class="read-link">Read <i class="fas fa-arrow-right"></i></a>`
        : `<span class="read-link disabled">No link</span>`;

    return `
    <div class="news-item impact-${level}" data-level="${level}">
        <div class="d-flex justify-content-between align-items-start gap-2 mb-1">
            <div class="news-title">${esc(a.title || a.clean_title || '—')}</div>
            <div class="d-flex gap-1 flex-shrink-0 align-items-center">
                <span class="impact-pill pill-${level}">${level}</span>
                <span class="score-badge">${score}/100</span>
            </div>
        </div>
        ${summary ? `<p class="news-desc">${esc(summary.slice(0, 200))}${summary.length > 200 ? '…' : ''}</p>` : ''}
        ${entityChips ? `<div class="mb-1">${entityChips}</div>` : ''}
        <div class="d-flex justify-content-between align-items-center flex-wrap gap-1 mt-1">
            <div class="d-flex align-items-center gap-1 flex-wrap">
                <span class="news-meta"><i class="far fa-building me-1"></i>${esc(a.source || '—')}</span>
                ${dateStr ? `<span class="news-meta">· ${dateStr}</span>` : ''}
                <span class="api-source-tag ${srcCls}">${srcType}</span>
                ${clusterBadge}
                ${semanticBadge}
            </div>
            ${readBtn}
        </div>
    </div>`;
}

// ── News filter chips ──────────────────────────────────────
function newsFilter(el, filter) {
    document.querySelectorAll('[data-nfilter]').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    document.querySelectorAll('.news-item').forEach(item => {
        const show = filter === 'all' || item.dataset.level === filter;
        item.style.display = show ? '' : 'none';
    });
}

// ══════════════════════════════════════════════════════════
//  CLUSTER RENDERER
// ══════════════════════════════════════════════════════════
let _clusterData = [];

function renderClusters(clusters) {
    const panel = document.getElementById('clustersPanel');
    const list  = document.getElementById('clustersList');
    const badge = document.getElementById('clusterCountBadge');

    const realClusters = clusters.filter(c => !c.is_noise && c.article_count > 1);
    _clusterData = realClusters;

    if (!realClusters.length) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = 'block';
    badge.textContent   = `${realClusters.length} event cluster${realClusters.length !== 1 ? 's' : ''}`;

    list.innerHTML = realClusters.map((c, idx) => _renderClusterCard(c, idx)).join('');
}

function _renderClusterCard(c, idx) {
    const level   = c.impact_level || 'LOW';
    const n       = c.article_count || 1;
    const score   = c.risk_score || 0;
    const summary = c.summary || '';

    const nodeChips = (c.linked_nodes || []).slice(0, 6).map(node => {
        const ci   = node.indexOf(':');
        const type = ci > -1 ? node.slice(0, ci) : '';
        const name = ci > -1 ? node.slice(ci + 1) : node;
        const cls  = { material:'chip-material', route:'chip-route', port:'chip-port', supplier:'chip-supplier' }[type] || 'chip-country';
        return `<span class="chip ${cls}" style="font-size:.63rem;padding:.12rem .45rem;">${esc(name)}</span>`;
    }).join('');

    const srcChips = (c.sources || []).slice(0, 4).map(s =>
        `<span class="api-source-tag" style="font-size:.62rem;">${esc(s)}</span>`
    ).join('');

    // Use the rich articles array now sent from backend
    const artItems = (c.articles || []).map(a => {
        const alevel = a.impact_level || level;
        const ascore = a.relevance_score || 0;
        const title  = a.title || '—';
        const url    = a.url   || '#';
        const isReal = url !== '#';
        const sem    = a.semantic_category && a.semantic_category !== 'unknown'
            ? `<span style="font-size:.58rem;background:#F5F3FF;color:var(--purple);border:1px solid #DDD6FE;padding:.1rem .35rem;border-radius:1rem;">${esc(a.semantic_category.replace('_',' '))}</span>`
            : '';
        return `
        <div class="singleton-row">
            <span class="impact-pill pill-${alevel}" style="font-size:.6rem;">${alevel}</span>
            <span class="score-badge" style="font-size:.6rem;">${ascore}/100</span>
            <span class="singleton-title">${esc(title)}</span>
            ${sem}
            ${isReal ? `<a href="${esc(url)}" target="_blank" rel="noopener" class="read-link ms-auto" style="font-size:.68rem;white-space:nowrap;">Read <i class="fas fa-arrow-right"></i></a>` : ''}
        </div>`;
    }).join('');

    // Headline from first article
    const headline = c.articles && c.articles[0] ? (c.articles[0].title || '') : '';

    return `
    <div class="cluster-card impact-${level}" data-cidx="${idx}" data-clevel="${level}" data-csize="${n}">
        <div class="cluster-card-top" onclick="clusterToggle(${idx})">
            <div style="flex:1;min-width:0;">
                <div class="d-flex align-items-center gap-2 flex-wrap mb-1">
                    <span class="cluster-id-badge">Event #${idx + 1}</span>
                    <span class="impact-pill pill-${level}" style="font-size:.63rem;">${level}</span>
                    <span class="cluster-size-chip">${n} article${n !== 1 ? 's' : ''}</span>
                    <span class="score-badge" style="font-size:.63rem;">${score}/100</span>
                </div>
                ${headline ? `<div class="cluster-headline">${esc(headline)}</div>` : ''}
            </div>
            <i class="fas fa-chevron-down cluster-chevron" id="cluster-chevron-${idx}"
               style="color:var(--text-3);font-size:.75rem;transition:transform .2s;flex-shrink:0;margin-left:.75rem;"></i>
        </div>
        ${summary ? `
        <div class="cluster-summary-bar">
            <i class="fas fa-align-left" style="color:var(--purple);flex-shrink:0;margin-top:.15rem;font-size:.75rem;"></i>
            <span>${esc(summary)}</span>
        </div>` : ''}
        <div class="cluster-card-body" id="cluster-body-${idx}">
            ${nodeChips ? `
            <div class="cluster-detail-row">
                <span class="cluster-detail-label"><i class="fas fa-link me-1"></i>Linked Nodes</span>
                <div class="d-flex flex-wrap gap-1">${nodeChips}</div>
            </div>` : ''}
            ${srcChips ? `
            <div class="cluster-detail-row">
                <span class="cluster-detail-label"><i class="fas fa-rss me-1"></i>Sources</span>
                <div class="d-flex flex-wrap gap-1">${srcChips}</div>
            </div>` : ''}
            ${artItems ? `
            <div class="cluster-detail-row" style="flex-direction:column;gap:.35rem;align-items:stretch;">
                <span class="cluster-detail-label"><i class="fas fa-newspaper me-1"></i>Articles in this event</span>
                <div style="display:flex;flex-direction:column;gap:.25rem;">${artItems}</div>
            </div>` : ''}
        </div>
    </div>`;
}

function clusterToggle(idx) {
    const body = document.getElementById(`cluster-body-${idx}`);
    const chev = document.getElementById(`cluster-chevron-${idx}`);
    if (!body) return;
    const open = body.classList.contains('open');
    body.classList.toggle('open', !open);
    if (chev) chev.style.transform = open ? '' : 'rotate(180deg)';
}

function clusterFilter(el, filter) {
    document.querySelectorAll('[data-cfilter]').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    document.querySelectorAll('.cluster-card').forEach(card => {
        const level = card.dataset.clevel;
        const show  = filter === 'all' || level === filter;
        card.style.display = show ? '' : 'none';
    });
}

// ══════════════════════════════════════════════════════════
//  SCROLL TO TOP
// ══════════════════════════════════════════════════════════
window.addEventListener('scroll', () => {
    document.getElementById('scrollTop').classList.toggle('visible', window.scrollY > 350);
});

// ══════════════════════════════════════════════════════════
//  COLLAPSE ICON SYNC + INIT
// ══════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {

    document.querySelectorAll('[data-bs-toggle="collapse"]').forEach(trigger => {
        const target = document.querySelector(trigger.getAttribute('data-bs-target'));
        if (!target) return;
        target.addEventListener('show.bs.collapse', () => trigger.setAttribute('aria-expanded','true'));
        target.addEventListener('hide.bs.collapse', () => trigger.setAttribute('aria-expanded','false'));
    });

    document.getElementById('btnUseExisting') .addEventListener('click', openExistingProfiles);
    document.getElementById('btnNewProfile')  .addEventListener('click', startNewProfile);
    document.getElementById('btnProfileBack') .addEventListener('click', () => toggleExistingList(false));

    const btnSave   = document.getElementById('btnSaveProfile');
    const btnSwitch = document.getElementById('btnSwitchProfile');
    if (btnSave)   btnSave.addEventListener('click', saveCurrentProfile);
    if (btnSwitch) btnSwitch.addEventListener('click', showProfileModal);

    addEntity('supplier');
    addEntity('material');
    addEntity('logistics');
    updateCounters();

    showProfileModal();
});

// ══════════════════════════════════════════════════════════
//  CLIENT PROFILE  — SAVE / LOAD / DELETE
// ══════════════════════════════════════════════════════════
function _collectCurrentProfile() {
    return {
        client_name:     document.getElementById('clientName').value.trim(),
        tier1_suppliers: suppliers.map(s => ({ name:s.name, material:s.material, location:s.location })),
        raw_materials:   materials.map(m => ({ commodity:m.commodity, region:m.region })),
        logistics_nodes: logistics.flatMap(l => {
            const nodes = [];
            if (l.port)  nodes.push({ port:l.port, carrier:l.carrier||'', route:l.route||'' });
            return nodes;
        }).filter(n => n.port.trim()),
        own_facilities:  facilities.map(f => ({ name:f.name, location:f.location })),
    };
}

function _applyProfile(profile) {
    document.getElementById('clientName').value = profile.client_name || '';

    suppliers = (profile.tier1_suppliers || []).map(s => ({
        name:     s.name     || '',
        material: s.material || '',
        location: s.location || s.country || s.city || '',
    }));

    materials = (profile.raw_materials || []).map(m => ({
        commodity: m.commodity || '',
        region:    m.region    || '',
    }));

    const rawNodes = profile.logistics_nodes || [];
    if (!rawNodes.length) {
        logistics = [];
    } else if (rawNodes[0].port !== undefined) {
        logistics = rawNodes.map(l => ({ port:l.port||'', carrier:l.carrier||'', route:l.route||'' }));
    } else {
        const ports  = rawNodes.filter(n => n.type === 'port');
        const routes = rawNodes.filter(n => n.type === 'route');
        const maxLen = Math.max(ports.length, routes.length);
        logistics = [];
        for (let i = 0; i < maxLen; i++) {
            logistics.push({
                port:    ports[i]  ? (ports[i].name    || '') : '',
                carrier: ports[i]  ? (ports[i].carrier || '') : '',
                route:   routes[i] ? (routes[i].name   || '') : '',
            });
        }
        if (!logistics.length && rawNodes.length) {
            logistics = rawNodes.map(n => ({ port:n.name||'', carrier:n.carrier||'', route:'' }));
        }
    }

    facilities = (profile.own_facilities || []).map(f => ({ name:f.name||'', location:f.location||'' }));

    renderSuppliers(); renderMaterials(); renderLogistics(); renderFacilities();
    updateCounters();
}

async function saveCurrentProfile() {
    const name = document.getElementById('clientName').value.trim();
    if (!name) { _showSaveMsg('Enter a client name before saving.', true); return; }
    try {
        const res  = await fetch('/save_profile', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify(_collectCurrentProfile()),
        });
        const data = await res.json();
        if (data.status === 'success') _showSaveMsg(`"${name}" saved.`, false);
        else _showSaveMsg(data.message || 'Save failed.', true);
    } catch(e) { _showSaveMsg('Server unreachable.', true); }
}

function _showSaveMsg(text, isError) {
    const box  = document.getElementById('saveProfileMsg');
    const span = document.getElementById('saveProfileMsgText');
    span.textContent = text;
    box.style.color  = isError ? '#FCA5A5' : '#6EE7B7';
    box.style.display = '';
    clearTimeout(box._t);
    box._t = setTimeout(() => { box.style.display = 'none'; }, 3500);
}

// ── Profile modal ──────────────────────────────────────────
function showProfileModal() {
    document.getElementById('profileModal').classList.remove('hidden');
    toggleExistingList(false);
}
function hideProfileModal() {
    document.getElementById('profileModal').classList.add('hidden');
}
function startNewProfile() {
    document.getElementById('clientName').value = '';
    suppliers=[]; materials=[]; logistics=[]; facilities=[];
    renderSuppliers(); renderMaterials(); renderLogistics(); renderFacilities();
    updateCounters();
    addEntity('supplier'); addEntity('material'); addEntity('logistics');
    hideProfileModal();
}
function toggleExistingList(show) {
    document.getElementById('savedProfilesList').style.display = show ? '' : 'none';
    if (show) _renderProfileList();
}
function openExistingProfiles() { toggleExistingList(true); }

async function _renderProfileList() {
    const container = document.getElementById('profileListItems');
    container.innerHTML = '<div style="text-align:center;padding:.75rem;color:var(--text-3);font-size:.78rem;"><i class="fas fa-spinner fa-spin me-1"></i>Loading…</div>';
    try {
        const res  = await fetch('/clients');
        const data = await res.json();
        if (data.status !== 'success' || !data.profiles.length) {
            container.innerHTML = '<div class="profile-empty-state"><i class="fas fa-folder-open fa-2x mb-2 opacity-30"></i><br>No saved profiles yet.</div>';
            return;
        }
        container.innerHTML = '';
        data.profiles.forEach(p => {
            const item = document.createElement('div');
            item.className = 'profile-list-item';
            item.innerHTML =
                '<div class="pli-icon"><i class="fas fa-building"></i></div>' +
                '<div class="pli-body">' +
                    '<div class="pli-name">' + esc(p.client_name) + '</div>' +
                    '<div class="pli-chips">' +
                        '<span class="pli-chip"><i class="fas fa-truck"></i> ' + p.supplier_count  + '</span>' +
                        '<span class="pli-chip"><i class="fas fa-cubes"></i> ' + p.material_count  + '</span>' +
                        '<span class="pli-chip"><i class="fas fa-ship"></i> '  + p.logistics_count + '</span>' +
                    '</div>' +
                    '<div class="pli-meta"><i class="fas fa-clock" style="margin-right:.25rem;"></i>' + (p.saved_at||'') + '</div>' +
                '</div>' +
                '<div class="pli-actions">' +
                    '<button class="pli-load-btn" data-id="' + p.id + '"><i class="fas fa-arrow-right me-1"></i>Load</button>' +
                    '<button class="pli-del-btn"  data-id="' + p.id + '" data-name="' + esc(p.client_name) + '"><i class="fas fa-trash-alt"></i></button>' +
                '</div>';
            item.querySelector('.pli-load-btn').addEventListener('click', function(e) {
                e.stopPropagation(); loadProfile(this.dataset.id);
            });
            item.querySelector('.pli-del-btn').addEventListener('click', function(e) {
                e.stopPropagation(); deleteProfile(e, this.dataset.id, this.dataset.name);
            });
            container.appendChild(item);
        });
    } catch(e) {
        container.innerHTML = '<div class="profile-empty-state" style="color:var(--red);">Could not reach server.</div>';
    }
}

async function loadProfile(clientId) {
    try {
        const res  = await fetch('/clients/' + clientId);
        const data = await res.json();
        if (data.status !== 'success') { alert('Could not load profile: ' + (data.message||'')); return; }
        _applyProfile(data.profile);
        hideProfileModal();
    } catch(e) { alert('Server unreachable.'); }
}

async function deleteProfile(e, clientId, clientName) {
    e.stopPropagation();
    if (!confirm('Delete profile "' + (clientName||clientId) + '"?')) return;
    try {
        const res  = await fetch('/clients/' + clientId, { method:'DELETE' });
        const data = await res.json();
        if (data.status === 'success') _renderProfileList();
        else alert('Delete failed: ' + (data.message||''));
    } catch(e) { alert('Server unreachable.'); }
}