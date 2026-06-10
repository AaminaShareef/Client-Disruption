// ══════════════════════════════════════════════════════════
//  STATE
// ══════════════════════════════════════════════════════════
let suppliers  = [];
let materials  = [];
let logistics  = [];
let facilities = [];
let _lastData    = null;   // last /analyze response (for export)
let _nlpRawData  = null;   // immutable copy of last /analyze data (filter source of truth)
let _currentRunId = null;  // run_id for semantic search

// ── Filter state ──────────────────────────────────────────
let _filters = {
    risk:      new Set(),
    domain:    new Set(),
    country:   new Set(),
    tier1Only: false,
    dateRange: 'all',
    semantic:  new Set(),
};

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
    const pct = document.getElementById('procPct');
    if (pct) pct.textContent = step.pct + '%';
    // Move glow to follow fill tip
    const glow = document.getElementById('procProgressGlow');
    if (glow) glow.style.left = `calc(${step.pct}% - 20px)`;

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
    const pct = document.getElementById('procPct');
    if (bar) bar.style.width = '0%';
    if (sub) sub.textContent = 'Initialising pipeline…';
    if (pct) pct.textContent = '0%';

    // Hide form, show processing screen full-page
    const form = document.getElementById('formSection');
    const proc = document.getElementById('processingScreen');
    if (form) form.style.display = 'none';
    if (proc) proc.style.display = 'flex';
    window.scrollTo({ top: 0, behavior: 'smooth' });

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

    // Flash all steps green
    _LOADING_STEPS.forEach(s => {
        const el = document.getElementById(s.id);
        if (el) { el.classList.remove('active'); el.classList.add('done'); }
    });
    const bar = document.getElementById('loadingProgressBar');
    const sub = document.getElementById('loadingSubtitle');
    const pct = document.getElementById('procPct');
    if (bar) bar.style.width = '100%';
    const glow = document.getElementById('procProgressGlow');
    if (glow) glow.style.left = 'calc(100% - 20px)';
    if (sub) sub.textContent = 'Analysis complete!';
    if (pct) pct.textContent = '100%';

    // Brief "done" pause, then swap processing → results
    setTimeout(() => {
        const proc = document.getElementById('processingScreen');
        if (proc) proc.style.display = 'none';
    }, 600);
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

    // Stamp client name on processing screen
    const procClient = document.getElementById('procClientName');
    if (procClient) procClient.textContent = clientName;

    showLoading();

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

        // Show full-page results after brief done-flash
        setTimeout(() => {
            document.getElementById('resultsSection').style.display = 'block';
            displayResults(data);
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }, 650);

    } catch (err) {
        console.error(err);
        hideLoading();
        // Bring form back so user sees the error
        setTimeout(() => {
            const form = document.getElementById('formSection');
            if (form) form.style.display = '';
            const eb = document.getElementById('errorBox');
            document.getElementById('errorMsg').textContent = err.message || 'Could not reach the server. Is Flask running?';
            eb.style.display = 'block';
            eb.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 650);
    } finally {
        document.getElementById('analyzeBtn').disabled = false;
    }
}

// ══════════════════════════════════════════════════════════
//  NAVIGATION — back to form from results
// ══════════════════════════════════════════════════════════
function goBackToForm() {
    document.getElementById('resultsSection').style.display = 'none';
    document.getElementById('processingScreen').style.display = 'none';
    const form = document.getElementById('formSection');
    if (form) form.style.display = '';
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ══════════════════════════════════════════════════════════
//  DISPLAY RESULTS  — renders everything automatically
// ══════════════════════════════════════════════════════════
function displayResults(data) {

    // ── Store run_id for semantic search ─────────────────
    if (data.run_id) _currentRunId = data.run_id;

    // ── Stamp run label in results header ────────────────
    const runLabel = document.getElementById('resultsRunLabel');
    if (runLabel && data.run_id) runLabel.textContent = data.run_id;

    // ── Freeze raw data + reset filters ──────────────────
    _nlpRawData = data;
    clearAllFilters(/* silent = */ true);

    // ── Show filter bar ───────────────────────────────────
    const fb = document.getElementById('filterBar');
    if (fb) fb.style.display = 'block';

    // ── Populate country dropdown ─────────────────────────
    const countrySelect = document.getElementById('countrySelect');
    if (countrySelect) {
        const countries = (data.exposure_map && data.exposure_map.countries) ? data.exposure_map.countries : [];
        countrySelect.innerHTML = '<option value="">All countries</option>';
        countries.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c; opt.textContent = c;
            countrySelect.appendChild(opt);
        });
    }

    // ── Populate semantic category chips (≥2 distinct non-unknown values) ──
    const allArticles = data.news || [];
    const semCats = [...new Set(allArticles
        .map(a => a.semantic_category)
        .filter(v => v && v !== 'unknown'))];
    const semanticRow   = document.getElementById('semanticFilterRow');
    const semanticChips = document.getElementById('semanticChips');
    if (semanticRow && semanticChips) {
        if (semCats.length >= 2) {
            semanticChips.innerHTML = semCats.map(cat =>
                `<span class="filter-chip" data-dim="semantic" data-val="${esc(cat)}"
                       onclick="toggleFilter('semantic','${esc(cat)}')">${esc(cat.replace('_',' '))}</span>`
            ).join('');
            semanticRow.style.display = '';
        } else {
            semanticRow.style.display = 'none';
        }
    }

    // ── Risk header ──────────────────────────────────────
    document.getElementById('clientNameDisplay').textContent = data.client_name;
    document.getElementById('timestampDisplay').innerHTML =
        `<i class="far fa-clock me-1"></i>${data.analysis_timestamp}`;

    const riskColors = {
        CRITICAL: { bg:'#FEF2F2', color:'#DC2626', border:'#FECACA' },
        HIGH:     { bg:'var(--orange-l)', color:'var(--orange)', border:'#FED7AA' },
        MEDIUM:   { bg:'var(--amber-l)',  color:'var(--amber)',  border:'#FDE68A' },
        LOW:      { bg:'var(--green-l)',  color:'var(--green)',  border:'#A7F3D0' },
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

    // ── Intelligence themes (BERTopic) ──────────────────
    renderTopics(data.topics || []);

    // ── Event clusters ───────────────────────────────────
    renderClusters(data.clusters || []);

    // ── Semantic search panel ─────────────────────────────
    const sp = document.getElementById('searchPanel');
    if (sp) sp.style.display = data.run_id ? 'block' : 'none';

    // ── Portfolio risk panel ──────────────────────────────
    renderPortfolioRisk(data.portfolio_risk);

    // ── News feed ────────────────────────────────────────
    renderNewsFeed(data.news || []);
}

// ══════════════════════════════════════════════════════════
//  NEWS FEED RENDERER
// ══════════════════════════════════════════════════════════
function renderNewsFeed(articles = []) {
    const feed  = document.getElementById('newsFeed');
    const badge = document.getElementById('articleCountBadge');
    const total = _nlpRawData ? (_nlpRawData.news || []).length : articles.length;
    const shown = articles.length;
    badge.textContent = total !== shown
        ? `${shown} of ${total} articles`
        : `${shown} article${shown !== 1 ? 's' : ''}`;

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

function renderClusters(clusters = []) {
    const panel = document.getElementById('clustersPanel');
    const list  = document.getElementById('clustersList');
    const badge = document.getElementById('clusterCountBadge');

    const realClusters = clusters.filter(c => !c.is_noise && c.article_count > 1);

    const rawMasterClusters = _nlpRawData
        ? (_nlpRawData.clusters || []).filter(c => !c.is_noise && c.article_count > 1)
        : realClusters;
    // Update master _clusterData only on initial/full call (when passed raw clusters)
    if (_nlpRawData && clusters === _nlpRawData.clusters) {
        _clusterData = realClusters;
    }

    const totalClusters = Math.max(rawMasterClusters.length, _clusterData.length);
    const shown = realClusters.length;

    if (!realClusters.length && !_clusterData.length) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = 'block';
    badge.textContent = (totalClusters !== shown && shown > 0)
        ? `${shown} of ${totalClusters} event cluster${totalClusters !== 1 ? 's' : ''}`
        : `${shown} event cluster${shown !== 1 ? 's' : ''}`;

    if (!realClusters.length) {
        list.innerHTML = `<div class="text-center py-4" style="color:var(--text-3);font-size:.83rem;"><i class="fas fa-filter me-1"></i>No clusters match the active filters.</div>`;
        return;
    }

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

    const sev          = c.severity || level.toUpperCase();
    const composite    = c.composite_score != null ? c.composite_score : score;
    const dimScores    = c.dimension_scores || {};
    const riskNarr     = c.risk_narrative || '';
    const SEV_COLOR    = { CRITICAL:'#DC2626', HIGH:'var(--orange)', MEDIUM:'var(--amber)', LOW:'var(--green)' };
    const SEV_BG       = { CRITICAL:'#FEF2F2', HIGH:'var(--orange-l)', MEDIUM:'var(--amber-l)', LOW:'var(--green-l)' };
    const SEV_BORDER   = { CRITICAL:'#FECACA', HIGH:'#FED7AA', MEDIUM:'#FDE68A', LOW:'#A7F3D0' };
    const sevColor     = SEV_COLOR[sev]  || SEV_COLOR.LOW;
    const sevBg        = SEV_BG[sev]    || SEV_BG.LOW;
    const sevBorder    = SEV_BORDER[sev] || SEV_BORDER.LOW;
    const sevBadge     = `<span style="display:inline-flex;align-items:center;padding:2px 8px;border-radius:3px;font-family:'DM Mono',monospace;font-size:.63rem;font-weight:700;letter-spacing:.06em;background:${sevBg};color:${sevColor};border:1px solid ${sevBorder};">${sev} · ${Math.round(composite)}</span>`;

    const DIM_LABELS = {
        intensity:'Signal Intensity', breadth:'Domain Breadth', node_crit:'Node Criticality',
        geo_spread:'Geo Spread', corroboration:'Corroboration', velocity:'Velocity (24h)',
        cluster_size:'Cluster Size', sem_confidence:'Semantic Confidence'
    };
    const dimBars = Object.entries(DIM_LABELS).map(([key, lbl]) => {
        const pct = Math.min(Math.max(dimScores[key] || 0, 0), 100);
        const fillColor = pct >= 75 ? '#ef4444' : pct >= 55 ? '#f97316' : pct >= 35 ? '#f59e0b' : '#22c55e';
        return `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
            <span style="flex:0 0 130px;font-size:.68rem;color:var(--text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${lbl}</span>
            <div style="flex:1;height:4px;background:#E2E8F0;border-radius:2px;overflow:hidden;">
                <div style="height:100%;width:${pct}%;background:${fillColor};border-radius:2px;transition:width .5s;"></div>
            </div>
            <span style="flex:0 0 26px;text-align:right;font-family:'DM Mono',monospace;font-size:.65rem;color:var(--text-3);">${Math.round(pct)}</span>
        </div>`;
    }).join('');

    const dimPanel = Object.keys(dimScores).length ? `
        <div style="margin-top:10px;padding:10px 12px;background:#F8FAFC;border:1px solid var(--border);border-radius:6px;">
            <div style="font-size:.63rem;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--text-3);margin-bottom:8px;">Risk Breakdown</div>
            ${dimBars}
        </div>` : '';

    return `
    <div class="cluster-card impact-${level}" data-cidx="${idx}" data-clevel="${sev}" data-csize="${n}">
        <div class="cluster-card-top" onclick="clusterToggle(${idx})">
            <div style="flex:1;min-width:0;">
                <div class="d-flex align-items-center gap-2 flex-wrap mb-1">
                    <span class="cluster-id-badge">Event #${idx + 1}</span>
                    ${sevBadge}
                    <span class="cluster-size-chip">${n} article${n !== 1 ? 's' : ''}</span>
                </div>
                ${headline ? `<div class="cluster-headline">${esc(headline)}</div>` : ''}
                ${riskNarr ? `<div style="font-size:.72rem;color:var(--text-3);margin-top:3px;font-style:italic;">${esc(riskNarr)}</div>` : ''}
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
            ${dimPanel}
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

// ══════════════════════════════════════════════════════════
//  FILTER ENGINE  (client-side, operates on _nlpRawData)
// ══════════════════════════════════════════════════════════

function toggleFilter(dimension, value) {
    const s = _filters[dimension];
    if (!(s instanceof Set)) return;
    if (s.has(value)) s.delete(value); else s.add(value);
    // Sync chip active state
    document.querySelectorAll(`.filter-chip[onclick*="toggleFilter('${dimension}','${value}')"]`)
        .forEach(el => el.classList.toggle('filter-chip-active', s.has(value)));
    applyFilters();
}

function setDateRange(value) {
    _filters.dateRange = value;
    document.querySelectorAll('.date-seg').forEach(el => {
        el.classList.toggle('date-seg-active', el.dataset.range === value);
    });
    applyFilters();
}

function setTier1(bool) {
    _filters.tier1Only = bool;
    applyFilters();
}

function handleCountrySelect(sel) {
    _filters.country.clear();
    if (sel.value) _filters.country.add(sel.value);
    applyFilters();
}

function clearAllFilters(silent = false) {
    _filters.risk      = new Set();
    _filters.domain    = new Set();
    _filters.country   = new Set();
    _filters.tier1Only = false;
    _filters.dateRange = 'all';
    _filters.semantic  = new Set();

    // Reset all chip active states
    document.querySelectorAll('.filter-chip').forEach(el => el.classList.remove('filter-chip-active'));
    // Reset date seg
    document.querySelectorAll('.date-seg').forEach(el =>
        el.classList.toggle('date-seg-active', el.dataset.range === 'all'));
    // Reset tier1 checkbox
    const cb = document.getElementById('tier1Checkbox');
    if (cb) cb.checked = false;
    // Reset country dropdown
    const cs = document.getElementById('countrySelect');
    if (cs) cs.value = '';

    // Hide active strip + badge
    const strip = document.getElementById('activeFilterStrip');
    const badge = document.getElementById('filterCountBadge');
    const clearBtn = document.getElementById('filterClearBtn');
    if (strip) { strip.style.display = 'none'; strip.innerHTML = ''; }
    if (badge) badge.style.display = 'none';
    if (clearBtn) clearBtn.style.display = 'none';

    if (!silent && _nlpRawData) {
        renderClusters(_nlpRawData.clusters || []);
        renderNewsFeed(_nlpRawData.news    || []);
    }
}

function _countActiveFilters() {
    return _filters.risk.size + _filters.domain.size + _filters.country.size +
           (_filters.tier1Only ? 1 : 0) +
           (_filters.dateRange !== 'all' ? 1 : 0) +
           _filters.semantic.size;
}

function _passesFilters(item, type) {
    // ── Risk ──────────────────────────────────────────────
    if (_filters.risk.size) {
        const level = type === 'cluster'
            ? (item.severity || item.impact_level || 'LOW')
            : (item.impact_level || 'LOW');
        if (!_filters.risk.has(level)) return false;
    }

    // ── Domain ────────────────────────────────────────────
    if (_filters.domain.size) {
        let itemDomains = [];
        if (type === 'cluster') {
            // brief.affected_nodes or linked_nodes type prefixes
            itemDomains = (item.disruption_domains || []).map(d => d.toLowerCase());
            if (!itemDomains.length && item.brief && item.brief.affected_nodes) {
                itemDomains = item.brief.affected_nodes.map(n => n.toLowerCase());
            }
        } else {
            itemDomains = (item.disruption_domains || []).map(d => d.toLowerCase());
        }
        const anyMatch = [..._filters.domain].some(fd => itemDomains.includes(fd));
        if (!anyMatch) return false;
    }

    // ── Country ───────────────────────────────────────────
    if (_filters.country.size) {
        let itemCountries = [];
        if (type === 'cluster') {
            itemCountries = (item.linked_nodes || [])
                .filter(n => n.startsWith('country:'))
                .map(n => n.slice(8));
        } else {
            if (item.country) itemCountries = [item.country];
        }
        const anyMatch = [..._filters.country].some(fc => itemCountries.includes(fc));
        if (!anyMatch) return false;
    }

    // ── Date range (articles + clusters via first article date) ──
    if (_filters.dateRange !== 'all') {
        const hoursMap = { '24h': 24, '7d': 168, '30d': 720 };
        const hours = hoursMap[_filters.dateRange] || Infinity;
        const cutoff = Date.now() - hours * 3600000;
        let pubDate = null;
        if (type === 'article') {
            pubDate = item.published ? new Date(item.published).getTime() : null;
        } else {
            // Use first article date or cluster's own timestamp
            const firstArt = item.articles && item.articles[0];
            const raw = (firstArt && firstArt.published) || item.published;
            pubDate = raw ? new Date(raw).getTime() : null;
        }
        if (!pubDate || isNaN(pubDate) || pubDate < cutoff) return false;
    }

    // ── Tier-1 (articles only) ────────────────────────────
    if (_filters.tier1Only && type === 'article') {
        if ((item.trust_score || 0) < 0.85) return false;
    }

    // ── Semantic category (articles only) ─────────────────
    if (_filters.semantic.size && type === 'article') {
        if (!_filters.semantic.has(item.semantic_category)) return false;
    }

    return true;
}

function applyFilters() {
    if (!_nlpRawData) return;

    const activeCount = _countActiveFilters();
    const badge    = document.getElementById('filterCountBadge');
    const clearBtn = document.getElementById('filterClearBtn');
    const strip    = document.getElementById('activeFilterStrip');

    // Update badge
    if (badge) {
        badge.textContent = `${activeCount} active`;
        badge.style.display = activeCount ? '' : 'none';
    }
    if (clearBtn) clearBtn.style.display = activeCount ? '' : 'none';

    // Filter clusters
    const rawClusters = (_nlpRawData.clusters || []).filter(c => !c.is_noise && c.article_count > 1);
    const filteredClusters = activeCount
        ? rawClusters.filter(c => _passesFilters(c, 'cluster'))
        : rawClusters;

    // Filter articles
    const rawArticles = _nlpRawData.news || [];
    const filteredArticles = activeCount
        ? rawArticles.filter(a => _passesFilters(a, 'article'))
        : rawArticles;

    // Re-render
    renderClusters(filteredClusters);
    renderNewsFeed(filteredArticles);

    // Build active-filter strip
    if (strip) {
        if (!activeCount) {
            strip.style.display = 'none';
            strip.innerHTML = '';
        } else {
            strip.style.display = 'flex';
            const chips = [];
            _filters.risk.forEach(v     => chips.push({ dim:'risk',     val:v,     label:`Risk: ${v}` }));
            _filters.domain.forEach(v   => chips.push({ dim:'domain',   val:v,     label:`Domain: ${v}` }));
            _filters.country.forEach(v  => chips.push({ dim:'country',  val:v,     label:`Country: ${v}` }));
            _filters.semantic.forEach(v => chips.push({ dim:'semantic', val:v,     label:`Cat: ${v.replace('_',' ')}` }));
            if (_filters.tier1Only)             chips.push({ dim:'tier1',    val:true,  label:'Tier-1 only', special:'tier1' });
            if (_filters.dateRange !== 'all')   chips.push({ dim:'date',     val:_filters.dateRange, label:`Date: ${_filters.dateRange}`, special:'date' });

            strip.innerHTML = chips.map(chip => {
                let removeCall;
                if (chip.special === 'tier1') removeCall = `setTier1(false);document.getElementById('tier1Checkbox').checked=false;`;
                else if (chip.special === 'date') removeCall = `setDateRange('all')`;
                else if (chip.dim === 'country') removeCall = `_filters.country.clear();document.getElementById('countrySelect').value='';applyFilters()`;
                else removeCall = `toggleFilter('${chip.dim}','${chip.val}')`;
                return `<span class="active-chip">${esc(chip.label)}<button class="active-chip-x" onclick="${removeCall}" title="Remove filter">&times;</button></span>`;
            }).join('');
        }
    }
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


// ══════════════════════════════════════════════════════════
//  TOPICS RENDERER  (BERTopic thematic grouping)
// ══════════════════════════════════════════════════════════

function renderTopics(topics) {
    const panel = document.getElementById('topicsPanel');
    const list  = document.getElementById('topicsList');
    const badge = document.getElementById('topicCountBadge');

    if (!topics || !topics.length) {
        if (panel) panel.style.display = 'none';
        return;
    }

    panel.style.display = 'block';
    badge.textContent   = `${topics.length} theme${topics.length !== 1 ? 's' : ''}`;

    list.innerHTML = topics.map(t => {
        const level    = t.impact_level || 'LOW';
        const kwChips  = (t.keywords || []).slice(0, 5)
            .map(k => `<span class="topic-kw-chip">${esc(k)}</span>`).join('');
        return `
        <div class="topic-row impact-${level}">
            <div class="topic-row-left">
                <span class="topic-label">${esc(t.label)}</span>
                <div class="topic-kw-row">${kwChips}</div>
            </div>
            <div class="topic-row-right">
                <span class="impact-pill pill-${level}" style="font-size:.58rem;">${level}</span>
                <span class="topic-count-badge">${t.article_count} art.</span>
                <span class="score-badge" style="font-size:.6rem;">${t.risk_score}/100</span>
            </div>
        </div>`;
    }).join('');
}


// ══════════════════════════════════════════════════════════
//  SEMANTIC SEARCH
// ══════════════════════════════════════════════════════════

async function runSearch() {
    const input  = document.getElementById('searchInput');
    const status = document.getElementById('searchStatus');
    const results = document.getElementById('searchResults');
    const query  = (input ? input.value : '').trim();

    if (!query)       { if (status) status.textContent = 'Enter a search query.'; return; }
    if (!_currentRunId) { if (status) status.textContent = 'Run an analysis first.'; return; }

    status.textContent  = 'Searching…';
    results.innerHTML   = '';

    try {
        const resp = await fetch('/search', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ query, run_id: _currentRunId }),
        });
        const data = await resp.json();

        if (data.status !== 'success') {
            status.textContent = `Error: ${data.message || 'unknown error'}`;
            return;
        }

        const hits = data.results || [];
        status.textContent = hits.length
            ? `${hits.length} result${hits.length !== 1 ? 's' : ''} for "${query}"`
            : `No results found for "${query}"`;

        results.innerHTML = hits.map(h => _renderSearchHit(h)).join('');

    } catch (err) {
        status.textContent = `Search failed: ${err.message}`;
    }
}

function _renderSearchHit(h) {
    const level = h.impact_level || 'LOW';
    const sim   = h.similarity_score != null
        ? `<span class="sim-score-badge" title="Semantic similarity">${(h.similarity_score * 100).toFixed(0)}% match</span>`
        : '';
    const sem   = h.semantic_category && h.semantic_category !== 'unknown'
        ? `<span style="font-size:.58rem;background:#F5F3FF;color:var(--purple);border:1px solid #DDD6FE;padding:.1rem .35rem;border-radius:1rem;">${esc(h.semantic_category.replace('_',' '))}</span>`
        : '';
    const summary = h.summary
        ? `<div class="search-hit-summary">${esc(h.summary)}</div>`
        : '';
    return `
    <div class="search-hit-row">
        <div class="d-flex align-items-center gap-2 flex-wrap mb-1">
            <span class="impact-pill pill-${level}" style="font-size:.6rem;">${level}</span>
            <span class="score-badge" style="font-size:.6rem;">${h.relevance_score}/100</span>
            ${sim}
            ${sem}
            <span style="font-size:.63rem;color:var(--text-3);margin-left:auto;">${esc(h.source || '')}</span>
        </div>
        <a href="${esc(h.url || '#')}" target="_blank" rel="noopener" class="search-hit-title">
            ${esc(h.title || '—')}
        </a>
        ${summary}
    </div>`;
}

// ══════════════════════════════════════════════════════════
//  PORTFOLIO RISK PANEL
// ══════════════════════════════════════════════════════════

function renderPortfolioRisk(portfolio) {
    const panel = document.getElementById('portfolioRiskPanel');
    if (!panel || !portfolio) return;

    const sev   = portfolio.overall_severity || 'LOW';
    const score = portfolio.overall_score != null ? portfolio.overall_score : 0;

    const SEV_COLOR  = { CRITICAL:'#DC2626', HIGH:'var(--orange)', MEDIUM:'var(--amber)', LOW:'var(--green)' };
    const SEV_BG     = { CRITICAL:'#FEF2F2', HIGH:'var(--orange-l)', MEDIUM:'var(--amber-l)', LOW:'var(--green-l)' };
    const SEV_BORDER = { CRITICAL:'#FECACA', HIGH:'#FED7AA', MEDIUM:'#FDE68A', LOW:'#A7F3D0' };

    const sevColor  = SEV_COLOR[sev]  || SEV_COLOR.LOW;
    const sevBg     = SEV_BG[sev]    || SEV_BG.LOW;
    const sevBorder = SEV_BORDER[sev] || SEV_BORDER.LOW;

    // Severity count chips
    const countChips = [
        { s:'CRITICAL', n: portfolio.critical_count },
        { s:'HIGH',     n: portfolio.high_count },
        { s:'MEDIUM',   n: portfolio.medium_count },
        { s:'LOW',      n: portfolio.low_count },
    ].filter(c => c.n > 0).map(c => {
        const bg  = SEV_BG[c.s]  || SEV_BG.LOW;
        const col = SEV_COLOR[c.s] || SEV_COLOR.LOW;
        const brd = SEV_BORDER[c.s] || SEV_BORDER.LOW;
        return `<span style="display:inline-flex;align-items:center;padding:2px 8px;border-radius:3px;font-family:'DM Mono',monospace;font-size:.65rem;font-weight:700;background:${bg};color:${col};border:1px solid ${brd};">${c.n} ${c.s}</span>`;
    }).join('');

    // Domain chips
    const domainHtml = Object.entries(portfolio.domain_breakdown || {}).slice(0, 8).map(([domain, count]) =>
        `<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 9px;background:var(--blue-l);border:1px solid #BFDBFE;border-radius:12px;font-size:.70rem;">
            <span style="color:var(--text-2);">${_cap(domain)}</span>
            <span style="color:var(--text-3);font-family:monospace;">${count}</span>
        </span>`
    ).join('');

    // Top-3 cluster mini cards
    const topHtml = (portfolio.top_clusters || []).map(c => {
        const cs = c.severity || 'LOW';
        const cbg  = SEV_BG[cs]  || SEV_BG.LOW;
        const ccol = SEV_COLOR[cs] || SEV_COLOR.LOW;
        const cbrd = SEV_BORDER[cs] || SEV_BORDER.LOW;
        const badgeHtml = `<span style="font-family:'DM Mono',monospace;font-size:.60rem;font-weight:700;padding:2px 7px;border-radius:3px;background:${cbg};color:${ccol};border:1px solid ${cbrd};">${cs} · ${Math.round(c.composite_score || 0)}</span>`;
        return `
        <div style="padding:9px 11px;background:var(--surface);border:1px solid var(--border);border-radius:6px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                ${badgeHtml}
                <span style="font-size:.65rem;color:var(--text-3);">${c.article_count || 0} article${(c.article_count||0)!==1?'s':''}</span>
            </div>
            <div style="font-size:.78rem;font-weight:600;color:var(--text-1);line-height:1.4;margin-bottom:2px;">${esc(c.headline || '')}</div>
            <div style="font-size:.70rem;color:var(--text-3);font-style:italic;line-height:1.4;">${esc(c.risk_narrative || '')}</div>
        </div>`;
    }).join('');

    panel.innerHTML = `
        <div class="breakdown-card" style="margin-bottom:1rem;">
            <div class="card-header-bar">
                <span><i class="fas fa-shield-alt me-2" style="color:${sevColor};"></i>Portfolio Risk</span>
                <span style="display:inline-flex;align-items:center;padding:2px 10px;border-radius:3px;font-family:'DM Mono',monospace;font-size:.70rem;font-weight:700;letter-spacing:.06em;background:${sevBg};color:${sevColor};border:1px solid ${sevBorder};">${sev}</span>
            </div>
            <div style="padding:.875rem;">
                <div style="display:flex;align-items:center;gap:1.25rem;margin-bottom:.875rem;flex-wrap:wrap;">
                    <div style="text-align:center;">
                        <div style="font-family:'DM Mono',monospace;font-size:2.8rem;font-weight:800;line-height:1;color:${sevColor};">${Math.round(score)}</div>
                        <div style="font-size:.68rem;color:var(--text-3);margin-top:1px;">/ 100</div>
                    </div>
                    <div style="flex:1;">
                        <p style="margin:0 0 8px;font-size:.83rem;line-height:1.5;color:var(--text-2);">${esc(portfolio.risk_message || '')}</p>
                        <div style="display:flex;flex-wrap:wrap;gap:5px;">${countChips}</div>
                    </div>
                </div>
                ${domainHtml ? `
                <div style="font-size:.62rem;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--text-3);margin-bottom:6px;">Active Disruption Domains</div>
                <div style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:.875rem;">${domainHtml}</div>` : ''}
                ${topHtml ? `
                <div style="font-size:.62rem;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--text-3);margin-bottom:6px;">Top Risk Clusters</div>
                <div style="display:flex;flex-direction:column;gap:6px;">${topHtml}</div>` : ''}
            </div>
        </div>`;
    panel.style.display = 'block';
}

function _cap(str) {
    return str ? str.charAt(0).toUpperCase() + str.slice(1) : '';
}