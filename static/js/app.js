// ══════════════════════════════════════════════════════════
//  STATE
// ══════════════════════════════════════════════════════════
let suppliers = [];
let materials = [];
let logistics = [];
let facilities = [];

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
    if (type === 'material')  { materials.push({ commodity:'', region:'' });           renderMaterials(); }
    if (type === 'logistics') { logistics.push({ port:'', carrier:'', route:'' });     renderLogistics(); }
    if (type === 'facility')  { facilities.push({ name:'', location:'' });             renderFacilities(); }
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
//  RENDER FUNCTIONS
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
            <input class="input-field mb-1" placeholder="Supplier name" value="${esc(s.name)}"
                   oninput="updateSupplier(${i},'name',this.value)">
            <div class="input-row">
                <input class="input-field" placeholder="Material provided" value="${esc(s.material)}"
                       oninput="updateSupplier(${i},'material',this.value)">
                <input class="input-field" placeholder="Location / country" value="${esc(s.location)}"
                       oninput="updateSupplier(${i},'location',this.value)">
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
                <input class="input-field" placeholder="Commodity (e.g., lithium)" value="${esc(m.commodity)}"
                       oninput="updateMaterial(${i},'commodity',this.value)">
                <input class="input-field" placeholder="Source region / country" value="${esc(m.region)}"
                       oninput="updateMaterial(${i},'region',this.value)">
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
            <input class="input-field mb-1" placeholder="Port / terminal" value="${esc(l.port)}"
                   oninput="updateLogistics(${i},'port',this.value)">
            <div class="input-row">
                <input class="input-field" placeholder="Carrier / forwarder" value="${esc(l.carrier)}"
                       oninput="updateLogistics(${i},'carrier',this.value)">
                <input class="input-field" placeholder="Trade route (e.g., Red Sea)" value="${esc(l.route)}"
                       oninput="updateLogistics(${i},'route',this.value)">
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
                <input class="input-field" placeholder="Facility name" value="${esc(f.name)}"
                       oninput="updateFacility(${i},'name',this.value)">
                <input class="input-field" placeholder="Location / city" value="${esc(f.location)}"
                       oninput="updateFacility(${i},'location',this.value)">
            </div>
        </div>`).join('');
}

// ══════════════════════════════════════════════════════════
//  PIPELINE PROGRESS HELPERS
// ══════════════════════════════════════════════════════════
function stepActivate(n) {
    const step = document.getElementById(`step${n}`);
    const icon = document.getElementById(`icon${n}`);
    step.classList.remove('waiting');
    step.classList.add('active');
    icon.className = 'step-icon run pulse';
    icon.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
}

function stepDone(n) {
    const step = document.getElementById(`step${n}`);
    const icon = document.getElementById(`icon${n}`);
    step.classList.remove('active', 'waiting');
    step.classList.add('done');
    icon.className = 'step-icon ok';
    icon.innerHTML = '<i class="fas fa-check"></i>';
}

function resetPipeline() {
    for (let n = 1; n <= 7; n++) {
        const step = document.getElementById(`step${n}`);
        const icon = document.getElementById(`icon${n}`);
        step.className = 'pipeline-step waiting';
        icon.className = 'step-icon wait';
        icon.innerHTML = '<i class="fas fa-circle-dot"></i>';
    }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ══════════════════════════════════════════════════════════
//  MAIN ANALYZE FLOW
// ══════════════════════════════════════════════════════════
async function analyzeProfile() {
    const clientName = document.getElementById('clientName').value.trim() || 'Unnamed Client';

    // Hide old results, show pipeline
    document.getElementById('errorBox').style.display      = 'none';
    document.getElementById('resultsSection').style.display = 'none';
    document.getElementById('pipelineBox').style.display    = 'block';
    document.getElementById('analyzeBtn').disabled          = true;
    resetPipeline();

    // Scroll to pipeline
    document.getElementById('pipelineBox').scrollIntoView({ behavior: 'smooth', block: 'start' });

    // Animate steps 1-3 immediately (they are fast, done server-side in one call)
    stepActivate(1); await sleep(400);
    stepDone(1);
    stepActivate(2); await sleep(300);
    stepDone(2);
    stepActivate(3); await sleep(300);
    stepDone(3);
    stepActivate(4);  // fetching — this is the slow part

    // FIX: Include material field so it round-trips through save_client_profile
    // Maps UI shape {name, material, location} → backend {name, material, country, city}
    const tier1_suppliers = suppliers.map(s => ({
        name:     s.name,
        material: s.material,   // ← preserved so saved profiles reload correctly
        country:  s.location,
        city:     '',
    }));

    // Map logistics UI shape {port, carrier, route} → backend [{name, type}, ...]
    // A single logistics row can have both a port AND a route — emit both nodes
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

        stepDone(4);
        stepActivate(5); await sleep(300);

        const data = await res.json();

        if (data.status !== 'success') {
            throw new Error(data.message || 'Server returned an error');
        }

        _nlpRawData = data;   // store for NLP panel

        stepDone(5);
        stepActivate(6); // NLP preprocessing — handled by runNLPPreprocessingAuto

        document.getElementById('pipelineBox').style.display    = 'none';
        document.getElementById('resultsSection').style.display = 'block';
        displayResults(data);
        // Auto-run NLP preprocessing — articles are hidden until this completes
        await runNLPPreprocessingAuto();
        document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth', block: 'start' });

    } catch (err) {
        console.error(err);
        document.getElementById('pipelineBox').style.display = 'none';
        const eb  = document.getElementById('errorBox');
        const em  = document.getElementById('errorMsg');
        em.textContent = err.message || 'Could not reach the server. Is Flask running?';
        eb.style.display = 'block';
    } finally {
        document.getElementById('analyzeBtn').disabled = false;
    }
}

// ══════════════════════════════════════════════════════════
//  DISPLAY RESULTS
// ══════════════════════════════════════════════════════════
function displayResults(data) {

    // ── Risk header ──────────────────────────────────────
    document.getElementById('clientNameDisplay').textContent = data.client_name;
    document.getElementById('timestampDisplay').innerHTML =
        `<i class="far fa-clock me-1"></i>${data.analysis_timestamp}`;

    const riskColors = {
        CRITICAL: { bg:'var(--red-l)',    color:'var(--red)',    border:'#FECACA' },
        HIGH:     { bg:'var(--orange-l)', color:'var(--orange)', border:'#FED7AA' },
        MEDIUM:   { bg:'var(--amber-l)',  color:'var(--amber)',  border:'#FDE68A' },
        LOW:      { bg:'var(--green-l)',  color:'var(--green)',  border:'#A7F3D0' },
    };
    const rc = riskColors[data.overall_risk] || riskColors.LOW;
    const badge = document.getElementById('riskBadge');
    badge.innerHTML = `<i class="fas fa-shield-alt"></i> ${data.overall_risk} RISK`;
    badge.style.background = rc.bg;
    badge.style.color      = rc.color;
    badge.style.border     = `1px solid ${rc.border}`;

    document.getElementById('riskMessage').textContent = data.risk_message;

    const scoreMap = { LOW:18, MEDIUM:42, HIGH:72, CRITICAL:91 };
    document.getElementById('riskScore').innerHTML =
        `${scoreMap[data.overall_risk]||35}<span style="font-size:.65rem;font-family:'DM Mono',monospace;">/100</span>`;

    // ── Exposure map chips ───────────────────────────────
    const em = data.exposure_map;
    if (em && Object.values(em).some(v => v.length)) {
        const sec   = document.getElementById('exposureSection');
        const chips = document.getElementById('exposureChips');
        sec.style.display = 'block';
        let html = '';

        const renderGroup = (label, items, cls, icon) => {
            if (!items || !items.length) return '';
            return `<div class="exposure-group">
                <div class="exposure-group-label"><i class="${icon} me-1"></i>${label}</div>
                ${items.map(v => `<span class="chip ${cls}">${v}</span>`).join('')}
            </div>`;
        };

        html += renderGroup('Countries',    em.countries,  'chip-country',  'fas fa-globe');
        html += renderGroup('Materials',    em.materials,  'chip-material', 'fas fa-cubes');
        html += renderGroup('Ports',        em.ports,      'chip-port',     'fas fa-anchor');
        html += renderGroup('Trade Routes', em.routes,     'chip-route',    'fas fa-route');
        html += renderGroup('Suppliers',    em.suppliers,  'chip-supplier', 'fas fa-truck');
        chips.innerHTML = html;
    }

    // ── Stats row ────────────────────────────────────────
    if (data.stats) {
        const sr = document.getElementById('statsRow');
        sr.style.display = 'flex';
        document.getElementById('stSuppliers').textContent = data.stats.suppliers_count;
        document.getElementById('stMaterials').textContent = data.stats.materials_count;
        document.getElementById('stLogistics').textContent = data.stats.logistics_nodes_count;
        document.getElementById('stAlerts').textContent    =
            (data.stats.critical_alerts||0) + (data.stats.high_alerts||0);
        const clusterEl = document.getElementById('stClusters');
        if (clusterEl) {
            clusterEl.textContent = data.stats.event_clusters != null ? data.stats.event_clusters : '—';
        }
    }

    // ── Query breakdown ──────────────────────────────────
    if (data.query_breakdown && Object.keys(data.query_breakdown).length) {
        const bc   = document.getElementById('breakdownCard');
        const rows = document.getElementById('breakdownRows');
        bc.style.display = 'block';
        const maxVal = Math.max(...Object.values(data.query_breakdown), 1);
        rows.innerHTML = Object.entries(data.query_breakdown).map(([label, count]) => {
            const pct = Math.round((count / maxVal) * 100);
            return `
            <div class="breakdown-row">
                <span class="breakdown-label"><i class="fas fa-tag me-1" style="color:var(--blue);opacity:.5;"></i>${label}</span>
                <div class="breakdown-bar-wrap"><div class="breakdown-bar" style="width:${pct}%;"></div></div>
                <span class="breakdown-count">${count}</span>
            </div>`;
        }).join('');
    }

    // ── News feed ────────────────────────────────────────
    // Hide feed container until NLP preprocessing finishes
    const feedSection = document.getElementById('newsFeedSection');
    if (feedSection) feedSection.style.display = 'none';

    const feed = document.getElementById('newsFeed');
    document.getElementById('articleCountBadge').textContent =
        `${(data.news||[]).length} articles`;

    if (!data.news || !data.news.length) {
        feed.innerHTML = `
            <div class="text-center py-5" style="color:var(--text-3);">
                <i class="fas fa-newspaper fa-3x mb-3 opacity-50"></i>
                <p>No relevant news found for this supply chain profile.</p>
                <small>Tip: Add more suppliers, materials or logistics nodes, or check your .env API keys.</small>
            </div>`;
        return;
    }

    feed.innerHTML = data.news.map(a => {
        const level    = a.impact_level || 'LOW';
        const srcType  = (a.source_type || a.fetch_method || 'RSS').toUpperCase().replace('GOOGLE_NEWS_RSS','GNEWS').replace('RSS','RSS');
        const srcClass = srcType === 'GDELT' ? 'gdelt' : srcType === 'NEWSAPI' ? 'newsapi' : srcType === 'GNEWS' ? 'gnews' : '';
        const catTag   = a.category ? `<span class="category-tag ms-1">${a.category}</span>` : '';
        const score    = a.relevance_score || 0;

        let dateStr = '';
        try {
            const d = new Date(a.published_at || a.published || '');
            if (!isNaN(d)) dateStr = d.toLocaleDateString('en-US', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' });
        } catch(_) {}

        // Build score breakdown tooltip
        const bd = a.score_breakdown || {};
        const bdTip = bd && Object.keys(bd).length
            ? `title="Disruption:${bd.disruption||0} SC:${bd.supply_chain||0} Entity:${bd.entity||0} Geo:${bd.geographic||0} Trust:${bd.trust||0}${bd.pr_penalty ? ' PR:'+bd.pr_penalty : ''}"`
            : '';

        // matched entities chips
        const entityChips = (a.matched_entities || [])
            .slice(0, 5)
            .map(e => `<span class="matched-entity-tag">${e}</span>`)
            .join('');

        const isReal = a.url && a.url !== '#';
        const readBtn = isReal
            ? `<a href="${esc(a.url)}" target="_blank" rel="noopener" class="read-link">Read <i class="fas fa-arrow-right"></i></a>`
            : `<span class="read-link disabled">No link</span>`;

        return `
        <div class="news-item impact-${level}">
            <div class="d-flex justify-content-between align-items-start gap-2 mb-1">
                <div class="news-title">${esc(a.title) || '—'}</div>
                <div class="d-flex gap-1 flex-shrink-0 align-items-center">
                    <span class="impact-pill pill-${level}">${level}</span>
                    <span class="score-badge" ${bdTip} style="cursor:help;">${score}/100</span>
                </div>
            </div>
            ${(a.description || a.summary) ? `<p class="news-desc">${esc(a.description || a.summary)}</p>` : ''}
            ${entityChips ? `<div class="mb-1">${entityChips}</div>` : ''}
            <div class="d-flex justify-content-between align-items-center flex-wrap gap-1 mt-1">
                <div class="d-flex align-items-center gap-1 flex-wrap">
                    <span class="news-meta"><i class="far fa-building me-1"></i>${esc(a.source)||'—'}</span>
                    ${dateStr ? `<span class="news-meta">· ${dateStr}</span>` : ''}
                    <span class="api-source-tag ${srcClass}">${srcType}</span>
                    ${catTag}
                </div>
                ${readBtn}
            </div>
        </div>`;
    }).join('');

    // Show the NLP preprocessing panel
    document.getElementById('nlpPanel').style.display = 'block';
    // Reset NLP state for new results
    clearNLPResults(true);

    // ── Render event clusters ────────────────────────────
    renderClusters(data.clusters || []);
}

// ══════════════════════════════════════════════════════════
//  EVENT CLUSTERS (DBSCAN + LexRank summaries)
// ══════════════════════════════════════════════════════════

let _clusterData      = [];   // rendered cluster list (real clusters only)
let _clusterSingletons = [];  // noise/singleton articles collapsed into one row

// Build a URL→article lookup from the news array so cluster cards can show titles
let _urlToArticle = {};

function renderClusters(clusters) {
    const panel = document.getElementById('clustersPanel');
    const list  = document.getElementById('clustersList');
    const badge = document.getElementById('clusterCountBadge');

    // Build URL lookup from the news data already stored
    _urlToArticle = {};
    if (_nlpRawData && _nlpRawData.news) {
        for (const a of _nlpRawData.news) {
            if (a.url) _urlToArticle[a.url] = a;
        }
    }

    if (!clusters || !clusters.length) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = 'block';

    // Separate real clusters from singletons
    _clusterData       = clusters.filter(c => !c.is_noise && c.article_count > 1);
    _clusterSingletons = clusters.filter(c =>  c.is_noise || c.article_count <= 1);

    const allSingletons = _clusterData.length === 0;
    const totalArticles = clusters.reduce((s, c) => s + (c.article_count || 1), 0);

    badge.textContent = allSingletons
        ? `No multi-article clusters · ${totalArticles} articles`
        : `${_clusterData.length} event cluster${_clusterData.length !== 1 ? 's' : ''} · ${_clusterSingletons.length} unclustered`;

    // ── No real clusters: embeddings likely not computed yet ──────────────
    if (allSingletons) {
        list.innerHTML = `
        <div class="cluster-empty-notice">
            <div class="cluster-empty-icon"><i class="fas fa-brain"></i></div>
            <div>
                <div class="cluster-empty-title">No event clusters detected</div>
                <div class="cluster-empty-sub">
                    DBSCAN requires SBERT embeddings to group articles. Embeddings are computed
                    server-side on the next full run after <code>sentence-transformers</code>
                    is installed and <code>sbert_encoder.py</code> runs.
                    All ${totalArticles} articles were processed individually as singletons.
                </div>
                <div class="cluster-empty-tip">
                    <i class="fas fa-lightbulb me-1"></i>
                    Run <code>pip install sentence-transformers scikit-learn</code> then re-analyse.
                </div>
            </div>
        </div>
        <div class="cluster-singletons-summary" onclick="clusterToggle('singletons')">
            <span class="cluster-id-badge noise"><i class="fas fa-list me-1"></i>${totalArticles} articles (unclustered)</span>
            <span style="font-size:.75rem;color:var(--text-3);">Click to expand</span>
            <i class="fas fa-chevron-down" id="cluster-chevron-singletons" style="color:var(--text-3);font-size:.75rem;transition:transform .2s;margin-left:auto;"></i>
        </div>
        <div class="cluster-card-body" id="cluster-body-singletons" style="border:1px solid var(--border);border-radius:var(--radius-sm);background:#FAFBFD;padding:.625rem 1rem;">
            ${_renderSingletonList(_clusterSingletons)}
        </div>`;
        return;
    }

    // ── Render real clusters ──────────────────────────────────────────────
    let html = _clusterData.map((c, i) => _renderClusterCard(c, i)).join('');

    // Append collapsed singleton row at the bottom
    if (_clusterSingletons.length) {
        const sCount = _clusterSingletons.length;
        html += `
        <div class="cluster-singletons-summary" onclick="clusterToggle('singletons')">
            <span class="cluster-id-badge noise"><i class="fas fa-list me-1"></i>${sCount} unclustered article${sCount !== 1 ? 's' : ''}</span>
            <span style="font-size:.73rem;color:var(--text-3);">Not enough similarity to form an event group</span>
            <i class="fas fa-chevron-down" id="cluster-chevron-singletons" style="color:var(--text-3);font-size:.75rem;transition:transform .2s;margin-left:auto;"></i>
        </div>
        <div class="cluster-card-body" id="cluster-body-singletons" style="border:1px solid var(--border);border-radius:var(--radius-sm);background:#FAFBFD;padding:.625rem 1rem;">
            ${_renderSingletonList(_clusterSingletons)}
        </div>`;
    }

    list.innerHTML = html;
}

function _renderSingletonList(singletons) {
    if (!singletons.length) return '';
    // Show article titles from URL lookup, fallback to article_urls
    return singletons.map(c => {
        const urls = (c.article_urls || []).filter(Boolean);
        const art  = urls.length ? (_urlToArticle[urls[0]] || {}) : {};
        const title = art.title || art.clean_title || urls[0] || 'Untitled article';
        const level = art.impact_level || c.impact_level || 'LOW';
        const score = art.relevance_score || c.risk_score || 0;
        const url   = urls[0] || '#';
        const isReal = url !== '#';
        return `
        <div class="singleton-row">
            <span class="impact-pill pill-${level}" style="font-size:.6rem;">${level}</span>
            <span class="score-badge" style="font-size:.6rem;">${score}/100</span>
            <span class="singleton-title">${esc(title)}</span>
            ${isReal ? `<a href="${esc(url)}" target="_blank" rel="noopener" class="read-link ms-auto" style="font-size:.68rem;white-space:nowrap;">Read <i class="fas fa-arrow-right"></i></a>` : ''}
        </div>`;
    }).join('');
}

function _renderClusterCard(c, idx) {
    const level   = c.impact_level || 'LOW';
    const n       = c.article_count || 1;
    const score   = c.risk_score || 0;
    const summary = c.summary || '';
    const nodes   = (c.linked_nodes || []).slice(0, 8);
    const sources = (c.sources || []).slice(0, 4);
    const urls    = (c.article_urls || []).filter(Boolean).slice(0, 10);

    // Derive a headline: title of the highest-scoring article in the cluster
    let headline = '';
    for (const url of urls) {
        const art = _urlToArticle[url];
        if (art && (art.title || art.clean_title)) {
            headline = art.title || art.clean_title;
            break;
        }
    }

    // Node chips
    const nodeChips = nodes.map(node => {
        const colonIdx = node.indexOf(':');
        const type = colonIdx > -1 ? node.slice(0, colonIdx) : '';
        const name = colonIdx > -1 ? node.slice(colonIdx + 1) : node;
        const cls = { material:'chip-material', route:'chip-route', port:'chip-port', supplier:'chip-supplier' }[type] || 'chip-country';
        return `<span class="chip ${cls}" style="font-size:.63rem;padding:.12rem .45rem;">${esc(name)}</span>`;
    }).join('');

    // Source chips
    const srcChips = sources.map(s =>
        `<span class="api-source-tag" style="font-size:.62rem;">${esc(s)}</span>`
    ).join('');

    // Article rows with titles
    const articleRows = urls.map(url => {
        const art   = _urlToArticle[url] || {};
        const title = art.title || art.clean_title || url;
        const alevel = art.impact_level || level;
        const ascore = art.relevance_score || 0;
        const isReal = url && url !== '#';
        return `
        <div class="singleton-row">
            <span class="impact-pill pill-${alevel}" style="font-size:.6rem;">${alevel}</span>
            <span class="score-badge" style="font-size:.6rem;">${ascore}/100</span>
            <span class="singleton-title">${esc(title)}</span>
            ${isReal ? `<a href="${esc(url)}" target="_blank" rel="noopener" class="read-link ms-auto" style="font-size:.68rem;white-space:nowrap;">Read <i class="fas fa-arrow-right"></i></a>` : ''}
        </div>`;
    }).join('');

    return `
    <div class="cluster-card impact-${level}" data-cidx="${idx}" data-clevel="${level}" data-cnoise="false" data-csize="${n}">
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
            ${articleRows ? `
            <div class="cluster-detail-row" style="flex-direction:column;gap:.35rem;align-items:stretch;">
                <span class="cluster-detail-label"><i class="fas fa-newspaper me-1"></i>Articles in this event</span>
                <div style="display:flex;flex-direction:column;gap:.25rem;">${articleRows}</div>
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

function clustersExpandAll(open) {
    // Expand/collapse real cluster cards
    _clusterData.forEach((_, idx) => {
        const body = document.getElementById(`cluster-body-${idx}`);
        const chev = document.getElementById(`cluster-chevron-${idx}`);
        if (!body) return;
        body.classList.toggle('open', open);
        if (chev) chev.style.transform = open ? 'rotate(180deg)' : '';
    });
    // Also handle singletons drawer
    const sb = document.getElementById('cluster-body-singletons');
    const sc = document.getElementById('cluster-chevron-singletons');
    if (sb) { sb.classList.toggle('open', open); }
    if (sc) { sc.style.transform = open ? 'rotate(180deg)' : ''; }
}

function clusterFilter(el, filter) {
    document.querySelectorAll('[data-cfilter]').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    document.querySelectorAll('.cluster-card').forEach(card => {
        const level  = card.dataset.clevel;
        const size   = parseInt(card.dataset.csize) || 1;
        let show = true;
        if      (filter === 'HIGH')   show = (level === 'HIGH');
        else if (filter === 'MEDIUM') show = (level === 'MEDIUM');
        else if (filter === 'LOW')    show = (level === 'LOW');
        else if (filter === 'multi')  show = (size > 1);
        card.style.display = show ? '' : 'none';
    });
}

// ══════════════════════════════════════════════════════════
//  NLP PREPROCESSING ENGINE (CLIENT-SIDE)
//  Mirrors utils/article_preprocessor.py in JS
// ══════════════════════════════════════════════════════════

let _nlpResults   = [];   // preprocessed article objects
let _nlpRawData   = null; // last /analyze response
let _nlpFilter    = 'all';

// ── Text cleaning ──────────────────────────────────────────
const _BOILERPLATE_RE = new RegExp([
    'subscribe\\s+to\\s+our\\s+newsletter.*',
    'click\\s+here\\s+to\\s+(read|view|subscribe).*',
    'copyright\\s+©?\\s*\\d{4}.*',
    'all\\s+rights\\s+reserved.*',
    'this\\s+article\\s+(originally\\s+)?appeared.*',
    'read\\s+more\\s*:.*',
    'related\\s+articles?\\s*:.*',
    'advertisement\\s*',
    'sponsored\\s+content\\s*',
    '\\[\\+\\d+\\s+chars\\]',
    '<[^>]+>',
    '&[a-zA-Z]{2,6};',
    'https?://\\S+',
].join('|'), 'gi');

function _cleanText(raw) {
    if (!raw) return '';
    let t = raw;
    // Smart-quotes
    t = t.replace(/[\u2018\u2019]/g, "'").replace(/[\u201c\u201d]/g, '"')
         .replace(/[\u2013\u2014]/g, '-').replace(/\u00a0/g, ' ').replace(/\u2026/g, '...');
    // Boilerplate
    t = t.replace(_BOILERPLATE_RE, ' ');
    // Whitespace
    t = t.replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
    return t;
}

// ── Sentence segmentation ──────────────────────────────────
function _splitSentences(text, maxSents = 12, minChars = 40) {
    if (!text) return [];
    const raw = text.split(/(?<=[.!?])\s+(?=[A-Z])/);
    return raw
        .map(s => s.trim())
        .filter(s => s.length >= minChars)
        .slice(0, maxSents);
}

// ── Lightweight NER (rule-based JS heuristics) ─────────────
const _ORG_INDICATORS   = ['inc','corp','ltd','llc','gmbh','plc','co.','company','group','holdings','industries','manufacturing','semiconductor','technology','technologies','logistics','freight','shipping','airlines','ports'];
const _GPE_INDICATORS   = ['china','taiwan','japan','korea','india','germany','france','usa','uk','vietnam','malaysia','singapore','indonesia','thailand','mexico','brazil','chile','australia'];
const _LOC_INDICATORS   = ['strait','sea','ocean','gulf','canal','bay','river','lake','mountain','port','harbor','terminal'];
const _EVENT_INDICATORS = ['strike','earthquake','flood','typhoon','hurricane','embargo','sanctions','war','conflict','protest','shutdown'];
const _PROD_INDICATORS  = ['lithium','cobalt','nickel','copper','aluminium','aluminum','silicon','wafer','chip','semiconductor','battery','steel','iron ore','rare earth'];

function _inferLabel(text) {
    const t = text.toLowerCase();
    if (_PROD_INDICATORS.some(k => t.includes(k))) return 'PRODUCT';
    if (_EVENT_INDICATORS.some(k => t.includes(k))) return 'EVENT';
    if (_LOC_INDICATORS.some(k => t.includes(k)))   return 'LOC';
    if (_GPE_INDICATORS.some(k => t === k || t.startsWith(k + ' '))) return 'GPE';
    if (_ORG_INDICATORS.some(k => t.includes(k)))   return 'ORG';
    return 'ORG';
}

function _extractEntities(text, ruleMatched = [], exposure = {}) {
    const seen = new Set();
    const result = [];

    const supplierSet = new Set((exposure.suppliers || []).map(s => s.toLowerCase()));
    const materialSet = new Set((exposure.materials || []).map(m => m.toLowerCase()));
    const portSet     = new Set((exposure.ports     || []).map(p => p.toLowerCase()));
    const routeSet    = new Set((exposure.routes    || []).map(r => r.toLowerCase()));

    function nodeType(name) {
        const n = name.toLowerCase();
        if (supplierSet.has(n)) return 'supplier';
        if (materialSet.has(n)) return 'material';
        if (portSet.has(n))     return 'port';
        if (routeSet.has(n))    return 'route';
        return null;
    }

    for (const name of ruleMatched) {
        const key = name.toLowerCase();
        if (seen.has(key) || name.length < 2) continue;
        seen.add(key);
        result.push({ text: name, label: 'RULE', source: 'rule', node_type: nodeType(name) });
    }

    const capPhrase = /\b([A-Z][a-zA-Z&\-\.]{1,}(?:\s+[A-Z][a-zA-Z&\-\.]{1,}){0,4})\b/g;
    let m;
    while ((m = capPhrase.exec(text)) !== null) {
        const phrase = m[1].trim();
        if (phrase.length < 3) continue;
        const key = phrase.toLowerCase();
        if (seen.has(key)) continue;
        if (['The','A','An','In','On','At','As','By','For','To','Of','From','With','And','Or','But','Its','This','That','These','Those','It','Is','Are','Was','Were','Has','Have','Had','Be','Been','Not','No','More','New','All','Also','Both','Their','They','He','She','We','You','I'].includes(phrase)) continue;
        seen.add(key);
        const label = _inferLabel(phrase);
        result.push({ text: phrase, label, source: 'spacy_sim', node_type: nodeType(phrase) });
    }

    const final = [];
    const finalKeys = new Set();
    result.sort((a,b) => b.text.length - a.text.length);
    for (const ent of result) {
        const k = ent.text.toLowerCase();
        if (finalKeys.has(k)) continue;
        const dominated = [...finalKeys].some(fk => fk.includes(k) && fk !== k);
        if (!dominated) {
            finalKeys.add(k);
            final.push(ent);
        }
    }
    return final.slice(0, 25);
}

// ── Token estimate ─────────────────────────────────────────
function _tokenEst(text) { return Math.round(text.length * 0.75); }

// ── Build SBERT input ──────────────────────────────────────
function _buildInputText(title, sentences, maxChars = 512) {
    const body = sentences.join('  ');
    const truncBody = body.length > maxChars ? body.slice(0, maxChars).replace(/\s\S+$/, '') + '...' : body;
    return `[TITLE] ${title.trim()}  [BODY] ${truncBody}`;
}

function _buildEntityString(entities) {
    if (!entities.length) return '';
    return '[ENTITIES] ' + entities.slice(0, 10).map(e => `${e.text} (${e.label})`).join(' | ');
}

// ── Main preprocessing function ────────────────────────────
function _preprocessArticle(article, exposure) {
    try {
        const rawTitle = article.title   || '';
        const rawBody  = article.summary || article.description || '';

        const cleanTitle = _cleanText(rawTitle);
        const cleanBody  = _cleanText(rawBody);
        const sentences  = _splitSentences(cleanBody);
        const fullText   = `${cleanTitle}. ${cleanBody}`;

        const ruleMatched = article.matched_entities || [];
        const nerEnts     = _extractEntities(fullText, ruleMatched, exposure);

        const inputText      = _buildInputText(cleanTitle, sentences);
        const entityString   = _buildEntityString(nerEnts);
        const inputTextWEnt  = entityString ? `${entityString}  ${inputText}` : inputText;
        const tokenEstimate  = _tokenEst(inputText);

        return {
            ...article,
            clean_title:      cleanTitle,
            clean_body:       cleanBody,
            sentences,
            ner_entities:     nerEnts,
            entity_string:    entityString,
            input_text:       inputText,
            input_text_w_ent: inputTextWEnt,
            token_estimate:   tokenEstimate,
            preprocessing_ok: true,
        };
    } catch(err) {
        return {
            ...article,
            clean_title:      article.title   || '',
            clean_body:       article.summary || '',
            sentences:        [],
            ner_entities:     [],
            entity_string:    '',
            input_text:       article.title || '',
            input_text_w_ent: article.title || '',
            token_estimate:   0,
            preprocessing_ok: false,
            _err: String(err),
        };
    }
}

// ── Entity label → CSS class ───────────────────────────────
function _entClass(label) {
    const map = { ORG:'ORG', GPE:'GPE', LOC:'LOC', FAC:'FAC', PRODUCT:'PRODUCT', EVENT:'EVENT', NORP:'NORP', RULE:'RULE' };
    return 'nlp-ent-' + (map[label] || 'ORG');
}

// ── Render NLP card ────────────────────────────────────────
function _renderNLPCard(art, idx) {
    const ok     = art.preprocessing_ok;
    const level  = art.impact_level || 'LOW';
    const tokens = art.token_estimate || 0;
    const tokenPct = Math.min(Math.round((tokens / 512) * 100), 100);
    const tokenColor = tokenPct > 85 ? 'var(--red)' : tokenPct > 60 ? 'var(--amber)' : 'var(--green)';

    const entHTML = (art.ner_entities || []).map(e =>
        `<span class="nlp-ent-tag ${_entClass(e.label)}" title="source:${e.source}${e.node_type?' node:'+e.node_type:''}">${esc(e.text)} <span style="opacity:.65;font-size:.6rem;">${e.label}</span></span>`
    ).join('');

    const sentHTML = (art.sentences || []).map((s, i) =>
        `<div class="nlp-sent"><span style="font-size:.65rem;font-family:'DM Mono',monospace;color:var(--text-3);margin-right:.4rem;">${i+1}</span>${esc(s)}</div>`
    ).join('');

    const inputPreview = esc((art.input_text || '').slice(0, 260)) + ((art.input_text||'').length > 260 ? '…' : '');

    return `
    <div class="nlp-card ${ok ? 'nlp-ok' : 'nlp-err'}"
         data-level="${level}"
         data-ok="${ok}"
         data-idx="${idx}">
        <div class="nlp-card-top" onclick="nlpToggle(${idx})">
            <span class="nlp-card-idx">${idx+1}</span>
            <div class="nlp-card-title">${esc(art.clean_title || art.title || '—')}</div>
            <div class="nlp-card-badges">
                <span class="impact-pill pill-${level}" style="font-size:.63rem;">${level}</span>
                <span class="score-badge" style="font-size:.63rem;">${art.relevance_score||0}/100</span>
                ${ok
                    ? `<span style="font-size:.65rem;background:var(--green-l);color:var(--green);border:1px solid #A7F3D0;padding:.15rem .45rem;border-radius:1rem;font-family:'DM Mono',monospace;">✓ ${(art.sentences||[]).length}s·${(art.ner_entities||[]).length}e·${tokens}t</span>`
                    : `<span style="font-size:.65rem;background:var(--red-l);color:var(--red);border:1px solid #FECACA;padding:.15rem .45rem;border-radius:1rem;">⚠ error</span>`
                }
                <i class="fas fa-chevron-down" id="nlp-chevron-${idx}" style="color:var(--text-3);font-size:.7rem;transition:transform .2s;"></i>
            </div>
        </div>
        <div class="nlp-card-body" id="nlp-body-${idx}">

            ${!ok ? `<div class="nlp-stage" style="border-color:#FECACA;background:var(--red-l);">
                <div class="nlp-stage-label" style="color:var(--red);"><i class="fas fa-exclamation-triangle"></i>Preprocessing Error</div>
                <div class="nlp-clean-text" style="color:var(--red);">${esc(art._err||'Unknown error')}</div>
            </div>` : ''}

            <div class="nlp-stage">
                <div class="nlp-stage-label"><i class="fas fa-broom"></i>Stage 1 — Cleaned Text</div>
                <div class="nlp-clean-text">${esc((art.clean_body||'').slice(0,400))}${(art.clean_body||'').length > 400 ? '…' : ''}</div>
            </div>

            <div class="nlp-stage">
                <div class="nlp-stage-label"><i class="fas fa-align-left"></i>Stage 2 — Sentence Segments (${(art.sentences||[]).length})</div>
                <div class="nlp-sent-list">${sentHTML || '<div class="nlp-sent" style="color:var(--text-3);">No sentences extracted (body too short)</div>'}</div>
            </div>

            <div class="nlp-stage">
                <div class="nlp-stage-label"><i class="fas fa-tags"></i>Stage 3 — NER Entities (${(art.ner_entities||[]).length})</div>
                <div class="nlp-entity-row">${entHTML || '<span style="font-size:.75rem;color:var(--text-3);">No entities extracted</span>'}</div>
            </div>

            <div class="nlp-stage">
                <div class="nlp-stage-label"><i class="fas fa-microchip"></i>Stage 4 — SBERT Payload</div>
                <div class="nlp-sbert-box">${inputPreview}</div>
                <div class="nlp-token-bar">
                    <span>${tokens} / 512 tokens est.</span>
                    <div class="nlp-token-track"><div class="nlp-token-fill" style="width:${tokenPct}%;background:${tokenColor};"></div></div>
                    <span>${tokenPct}%</span>
                </div>
                ${art.entity_string ? `<div class="nlp-sbert-box" style="margin-top:.4rem;font-size:.68rem;color:#6EE7B7;">${esc(art.entity_string)}</div>` : ''}
            </div>

        </div>
    </div>`;
}

// ── Toggle card expand ─────────────────────────────────────
function nlpToggle(idx) {
    const body   = document.getElementById(`nlp-body-${idx}`);
    const chev   = document.getElementById(`nlp-chevron-${idx}`);
    const isOpen = body.classList.contains('open');
    body.classList.toggle('open', !isOpen);
    chev.style.transform = isOpen ? '' : 'rotate(180deg)';
}

function nlpExpandAll(open) {
    _nlpResults.forEach((_, idx) => {
        const body = document.getElementById(`nlp-body-${idx}`);
        const chev = document.getElementById(`nlp-chevron-${idx}`);
        if (!body) return;
        body.classList.toggle('open', open);
        if (chev) chev.style.transform = open ? 'rotate(180deg)' : '';
    });
}

// ── Filter ─────────────────────────────────────────────────
function nlpFilter(el, filter) {
    _nlpFilter = filter;
    document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
    el.classList.add('active');

    const cards = document.querySelectorAll('.nlp-card');
    cards.forEach(card => {
        const level = card.dataset.level;
        const ok    = card.dataset.ok === 'true';
        let show = false;
        if (filter === 'all')    show = true;
        else if (filter === 'ok')  show = ok;
        else if (filter === 'err') show = !ok;
        else show = (level === filter);
        card.style.display = show ? '' : 'none';
    });
}

// ── Auto-run preprocessing (called after analyze, returns Promise) ──
function runNLPPreprocessingAuto() {
    return new Promise(resolve => {
        if (!_nlpRawData || !_nlpRawData.news || !_nlpRawData.news.length) {
            resolve(); return;
        }

        // Update pipeline step 6 to show it's running
        stepActivate(6);

        const btn = document.getElementById('btnRunNLP');
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing…'; }

        const exposure = _nlpRawData.exposure_map || {};
        const articles = _nlpRawData.news || [];

        _nlpResults = [];
        const grid = document.getElementById('nlpArticleGrid');
        if (grid) grid.innerHTML = '<div class="text-center py-3" style="color:var(--text-3);font-size:.82rem;"><i class="fas fa-spinner fa-spin me-2"></i>Preprocessing articles…</div>';

        setTimeout(() => {
            for (const art of articles) {
                _nlpResults.push(_preprocessArticle(art, exposure));
            }

            if (grid) {
                const html = _nlpResults.map((a, i) => _renderNLPCard(a, i)).join('');
                grid.innerHTML = html || '<div class="text-center py-4" style="color:var(--text-3);">No articles to display.</div>';
            }

            const ok       = _nlpResults.filter(a => a.preprocessing_ok).length;
            const err      = _nlpResults.length - ok;
            const totalEnt = _nlpResults.reduce((s,a) => s + (a.ner_entities||[]).length, 0);
            const avgSent  = ok ? Math.round(_nlpResults.filter(a=>a.preprocessing_ok).reduce((s,a)=>s+(a.sentences||[]).length,0)/ok) : 0;
            const avgTok   = ok ? Math.round(_nlpResults.filter(a=>a.preprocessing_ok).reduce((s,a)=>s+(a.token_estimate||0),0)/ok) : 0;

            const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
            set('nlpStatTotal',  _nlpResults.length);
            set('nlpStatOk',     ok);
            set('nlpStatErr',    err);
            set('nlpStatEnts',   totalEnt);
            set('nlpStatSents',  avgSent);
            set('nlpStatTokens', avgTok);

            const showEl = (id, show) => { const el = document.getElementById(id); if (el) el.style.display = show ? '' : 'none'; };
            showEl('nlpStatusBar', true);
            showEl('nlpExportBar', true);

            ['btnExpandAll','btnCollapseAll','btnClearNLP','btnExportSBERT','btnExportCSV'].forEach(id => {
                const el = document.getElementById(id); if (el) el.disabled = false;
            });

            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-sync-alt"></i> Re-run'; }

            const activeChip = document.querySelector('.filter-chip.active');
            if (activeChip) nlpFilter(activeChip, activeChip.dataset.filter);

            // Mark step 6 done, complete step 7
            stepDone(6);
            stepActivate(7);
            setTimeout(() => {
                stepDone(7);

                // Now reveal the news feed section
                const feedSection = document.getElementById('newsFeedSection');
                if (feedSection) feedSection.style.display = '';

                resolve();
            }, 200);
        }, 50);
    });
}

// ── Run preprocessing (manual button — now just calls auto version) ──
function runNLPPreprocessing() {
    if (!_nlpRawData || !_nlpRawData.news || !_nlpRawData.news.length) {
        alert('Run an analysis first to fetch articles.');
        return;
    }

    const btn = document.getElementById('btnRunNLP');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing…';

    const exposure = _nlpRawData.exposure_map || {};
    const articles = _nlpRawData.news || [];

    _nlpResults = [];
    const grid = document.getElementById('nlpArticleGrid');
    grid.innerHTML = '<div class="text-center py-3" style="color:var(--text-3);font-size:.82rem;"><i class="fas fa-spinner fa-spin me-2"></i>Preprocessing articles…</div>';

    setTimeout(() => {
        for (const art of articles) {
            _nlpResults.push(_preprocessArticle(art, exposure));
        }

        const html = _nlpResults.map((a, i) => _renderNLPCard(a, i)).join('');
        grid.innerHTML = html || '<div class="text-center py-4" style="color:var(--text-3);">No articles to display.</div>';

        const ok       = _nlpResults.filter(a => a.preprocessing_ok).length;
        const err      = _nlpResults.length - ok;
        const totalEnt = _nlpResults.reduce((s,a) => s + (a.ner_entities||[]).length, 0);
        const avgSent  = ok ? Math.round(_nlpResults.filter(a=>a.preprocessing_ok).reduce((s,a)=>s+(a.sentences||[]).length,0)/ok) : 0;
        const avgTok   = ok ? Math.round(_nlpResults.filter(a=>a.preprocessing_ok).reduce((s,a)=>s+(a.token_estimate||0),0)/ok) : 0;

        document.getElementById('nlpStatTotal').textContent = _nlpResults.length;
        document.getElementById('nlpStatOk').textContent    = ok;
        document.getElementById('nlpStatErr').textContent   = err;
        document.getElementById('nlpStatEnts').textContent  = totalEnt;
        document.getElementById('nlpStatSents').textContent = avgSent;
        document.getElementById('nlpStatTokens').textContent = avgTok;
        document.getElementById('nlpStatusBar').style.display = '';
        document.getElementById('nlpExportBar').style.display = '';

        ['btnExpandAll','btnCollapseAll','btnClearNLP','btnExportSBERT','btnExportCSV'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.disabled = false;
        });

        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-sync-alt"></i> Re-run';

        const activeChip = document.querySelector('.filter-chip.active');
        if (activeChip) nlpFilter(activeChip, activeChip.dataset.filter);

        document.getElementById('nlpPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
}

// ── Clear NLP results ──────────────────────────────────────
function clearNLPResults(silent = false) {
    _nlpResults = [];
    const grid = document.getElementById('nlpArticleGrid');
    grid.innerHTML = `
        <div class="text-center py-5" style="color:var(--text-3);">
            <i class="fas fa-brain fa-3x mb-3 opacity-25"></i>
            <p style="font-size:.85rem;">Click <strong>Run Preprocessing</strong> to clean, segment and NER-tag the fetched articles.</p>
            <p style="font-size:.78rem;margin-top:.5rem;">Output is a Sentence-BERT–ready corpus with entity annotations.</p>
        </div>`;
    document.getElementById('nlpStatusBar').style.display   = 'none';
    document.getElementById('nlpExportBar').style.display   = 'none';
    ['btnExpandAll','btnCollapseAll','btnClearNLP','btnExportSBERT','btnExportCSV'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = true;
    });
    const btn = document.getElementById('btnRunNLP');
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-play"></i> Run Preprocessing'; }
    if (!silent) {
        document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
        const allChip = document.querySelector('.filter-chip[data-filter="all"]');
        if (allChip) allChip.classList.add('active');
    }
}

// ── Export helpers ─────────────────────────────────────────
function _download(filename, content, mime) {
    const blob = new Blob([content], { type: mime });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
}

function exportSBERT() {
    if (!_nlpResults.length) return;
    const payload = _nlpResults.map(a => ({
        title:            a.clean_title,
        input_text:       a.input_text,
        input_text_w_ent: a.input_text_w_ent,
        entity_string:    a.entity_string,
        sentences:        a.sentences,
        ner_entities:     a.ner_entities,
        token_estimate:   a.token_estimate,
        impact_level:     a.impact_level,
        relevance_score:  a.relevance_score,
        url:              a.url,
        source:           a.source,
        published:        a.published,
        linked_nodes:     a.linked_nodes,
        preprocessing_ok: a.preprocessing_ok,
    }));
    _download('sbert_corpus.json', JSON.stringify(payload, null, 2), 'application/json');
}

function exportCleanText() {
    if (!_nlpResults.length) return;
    const lines = _nlpResults
        .filter(a => a.preprocessing_ok)
        .map(a => `=== ${a.clean_title} ===\n${a.clean_body}\n`)
        .join('\n---\n\n');
    _download('clean_articles.txt', lines, 'text/plain');
}

function exportCSV() {
    if (!_nlpResults.length) return;
    const rows = [['article_title','entity_text','entity_label','entity_source','node_type']];
    _nlpResults.forEach(a => {
        (a.ner_entities||[]).forEach(e => {
            rows.push([
                `"${(a.clean_title||'').replace(/"/g,'""')}"`,
                `"${(e.text||'').replace(/"/g,'""')}"`,
                e.label, e.source,
                e.node_type||''
            ]);
        });
    });
    _download('entities.csv', rows.map(r=>r.join(',')).join('\n'), 'text/csv');
}

function exportSentences() {
    if (!_nlpResults.length) return;
    const lines = _nlpResults
        .filter(a => a.preprocessing_ok)
        .flatMap(a => (a.sentences||[]).map((s,i) => JSON.stringify({
            text:            s,
            sentence_idx:    i,
            article_title:   a.clean_title,
            impact_level:    a.impact_level,
            relevance_score: a.relevance_score,
            url:             a.url,
        })));
    _download('sentences.jsonl', lines.join('\n'), 'application/jsonl');
}

// ══════════════════════════════════════════════════════════
//  SCROLL TO TOP
// ══════════════════════════════════════════════════════════
window.addEventListener('scroll', () => {
    document.getElementById('scrollTop').classList.toggle('visible', window.scrollY > 350);
});

// ══════════════════════════════════════════════════════════
//  COLLAPSE ICON SYNC
// ══════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {

    // ── Bootstrap collapse sync ──────────────────────────
    document.querySelectorAll('[data-bs-toggle="collapse"]').forEach(trigger => {
        const target = document.querySelector(trigger.getAttribute('data-bs-target'));
        if (!target) return;
        target.addEventListener('show.bs.collapse', () => trigger.setAttribute('aria-expanded','true'));
        target.addEventListener('hide.bs.collapse', () => trigger.setAttribute('aria-expanded','false'));
    });

    // ── Profile modal buttons ────────────────────────────
    document.getElementById('btnUseExisting') .addEventListener('click', openExistingProfiles);
    document.getElementById('btnNewProfile')  .addEventListener('click', startNewProfile);
    document.getElementById('btnProfileBack') .addEventListener('click', () => toggleExistingList(false));

    // ── Save / Switch buttons in client card ────────────
    const btnSave   = document.getElementById('btnSaveProfile');
    const btnSwitch = document.getElementById('btnSwitchProfile');
    if (btnSave)   btnSave.addEventListener('click', saveCurrentProfile);
    if (btnSwitch) btnSwitch.addEventListener('click', showProfileModal);

    // ── Pre-populate one blank row each ──────────────────
    addEntity('supplier');
    addEntity('material');
    addEntity('logistics');
    updateCounters();

    // ── Show profile chooser modal last ──────────────────
    showProfileModal();
});

// ══════════════════════════════════════════════════════════
//  CLIENT PROFILE — SAVE / LOAD / DELETE  (server-backed)
// ══════════════════════════════════════════════════════════

function _nameToId(name) {
    return name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_\-]/g, '');
}

/** Collect current form state into a profile object */
function _collectCurrentProfile() {
    return {
        client_name:     document.getElementById('clientName').value.trim(),
        tier1_suppliers: suppliers.map(s => ({
            name:     s.name,
            material: s.material,
            location: s.location,
        })),
        raw_materials:   materials.map(m => ({
            commodity: m.commodity,
            region:    m.region,
        })),
        logistics_nodes: logistics.flatMap(l => {
            const nodes = [];
            if (l.port)  nodes.push({ port: l.port, carrier: l.carrier || '', route: l.route || '' });
            return nodes;
        }).filter(n => n.port.trim()),
        own_facilities:  facilities.map(f => ({
            name:     f.name,
            location: f.location,
        })),
    };
}

// ══════════════════════════════════════════════════════════
//  FIX: _applyProfile — handles ALL saved schema variants
//
//  Variant A  (UI / save_profile):
//    tier1_suppliers: [ { name, material, location } ]
//    logistics_nodes: [ { port, carrier, route } ]
//
//  Variant B  (backend /analyze auto-save):
//    tier1_suppliers: [ { name, material, country, city } ]
//    logistics_nodes: [ { name, type, carrier? } ]   ← type = 'port' | 'route'
// ══════════════════════════════════════════════════════════
function _applyProfile(profile) {
    document.getElementById('clientName').value = profile.client_name || '';

    // ── Suppliers ───────────────────────────────────────────
    // Variant A has `location`, Variant B has `country` (and optionally `city`).
    // Both variants may or may not have `material`.
    suppliers = (profile.tier1_suppliers || []).map(s => ({
        name:     s.name     || '',
        material: s.material || '',                          // present in both variants after fix
        location: s.location || s.country || s.city || '',  // fallback chain covers both variants
    }));

    // ── Materials ───────────────────────────────────────────
    // Schema is identical in both variants: { commodity, region }
    materials = (profile.raw_materials || []).map(m => ({
        commodity: m.commodity || '',
        region:    m.region    || '',
    }));

    // ── Logistics ───────────────────────────────────────────
    // Detect which variant is in use by checking the first node's shape.
    const rawNodes = profile.logistics_nodes || [];

    if (!rawNodes.length) {
        logistics = [];
    } else if (rawNodes[0].port !== undefined) {
        // ── Variant A: UI schema { port, carrier, route } ──
        logistics = rawNodes.map(l => ({
            port:    l.port    || '',
            carrier: l.carrier || '',
            route:   l.route   || '',
        }));
    } else {
        // ── Variant B: backend schema { name, type, carrier? } ──
        // Pair up port nodes and route nodes into single UI rows so each
        // row shows one port + its matching route (e.g. Kaohsiung + Taiwan Strait).
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

        // Fallback: unknown type nodes — show name in port field
        if (logistics.length === 0 && rawNodes.length) {
            logistics = rawNodes.map(n => ({
                port:    n.name    || '',
                carrier: n.carrier || '',
                route:   '',
            }));
        }
    }

    // ── Facilities ──────────────────────────────────────────
    // Schema is identical in both variants: { name, location }
    facilities = (profile.own_facilities || []).map(f => ({
        name:     f.name     || '',
        location: f.location || '',
    }));

    renderSuppliers();
    renderMaterials();
    renderLogistics();
    renderFacilities();
    updateCounters();
}

// ── Save current profile to server ────────────────────────
async function saveCurrentProfile() {
    const name = document.getElementById('clientName').value.trim();
    if (!name) { _showSaveMsg('Enter a client name before saving.', true); return; }

    const profile = _collectCurrentProfile();
    try {
        const res  = await fetch('/save_profile', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(profile),
        });
        const data = await res.json();
        if (data.status === 'success') {
            _showSaveMsg(`"${name}" saved to server.`, false);
        } else {
            _showSaveMsg(data.message || 'Save failed.', true);
        }
    } catch(e) {
        _showSaveMsg('Server unreachable — save failed.', true);
    }
}

function _showSaveMsg(text, isError) {
    const box  = document.getElementById('saveProfileMsg');
    const span = document.getElementById('saveProfileMsgText');
    span.textContent = text;
    box.style.color  = isError ? '#FCA5A5' : '#6EE7B7';
    box.style.display = '';
    clearTimeout(box._hideTimer);
    box._hideTimer = setTimeout(() => { box.style.display = 'none'; }, 3500);
}

// ══════════════════════════════════════════════════════════
//  PROFILE MODAL LOGIC
// ══════════════════════════════════════════════════════════
function showProfileModal() {
    const overlay = document.getElementById('profileModal');
    overlay.classList.remove('hidden');
    toggleExistingList(false);
}

function hideProfileModal() {
    document.getElementById('profileModal').classList.add('hidden');
}

function startNewProfile() {
    document.getElementById('clientName').value = '';
    suppliers  = [];
    materials  = [];
    logistics  = [];
    facilities = [];
    renderSuppliers();
    renderMaterials();
    renderLogistics();
    renderFacilities();
    updateCounters();
    addEntity('supplier');
    addEntity('material');
    addEntity('logistics');
    hideProfileModal();
}

function toggleExistingList(show) {
    document.getElementById('savedProfilesList').style.display = show ? '' : 'none';
    if (show) _renderProfileList();
}

function openExistingProfiles() {
    toggleExistingList(true);
}

// ── Render the saved-profiles list (fetches from server) ──
async function _renderProfileList() {
    const container = document.getElementById('profileListItems');
    container.innerHTML = '<div style="text-align:center;padding:.75rem;color:var(--text-3);font-size:.78rem;"><i class="fas fa-spinner fa-spin me-1"></i>Loading profiles…</div>';

    try {
        const res  = await fetch('/clients');
        const data = await res.json();

        if (data.status !== 'success' || !data.profiles.length) {
            container.innerHTML = '<div class="profile-empty-state"><i class="fas fa-folder-open fa-2x mb-2 opacity-30"></i><br>No saved profiles yet.<br>Fill in a profile and click <strong>Save Profile</strong>.</div>';
            return;
        }

        container.innerHTML = '';
        data.profiles.forEach(function(p) {
            const item = document.createElement('div');
            item.className = 'profile-list-item';

            item.innerHTML =
                '<div class="pli-icon"><i class="fas fa-building"></i></div>' +
                '<div class="pli-body">' +
                    '<div class="pli-name">' + esc(p.client_name) + '</div>' +
                    '<div class="pli-chips">' +
                        '<span class="pli-chip"><i class="fas fa-truck"></i> ' + p.supplier_count + ' suppliers</span>' +
                        '<span class="pli-chip"><i class="fas fa-cubes"></i> ' + p.material_count + ' materials</span>' +
                        '<span class="pli-chip"><i class="fas fa-ship"></i> ' + p.logistics_count + ' logistics</span>' +
                        '<span class="pli-chip"><i class="fas fa-industry"></i> ' + p.facility_count + ' facilities</span>' +
                    '</div>' +
                    '<div class="pli-meta">' +
                        '<i class="fas fa-clock" style="margin-right:.25rem;"></i>Last saved: ' + (p.saved_at || 'Unknown') +
                    '</div>' +
                '</div>' +
                '<div class="pli-actions">' +
                    '<button class="pli-load-btn" data-id="' + p.id + '"><i class="fas fa-arrow-right me-1"></i>Load</button>' +
                    '<button class="pli-del-btn"  data-id="' + p.id + '" data-name="' + esc(p.client_name) + '"><i class="fas fa-trash-alt"></i></button>' +
                '</div>';

            item.querySelector('.pli-load-btn').addEventListener('click', function(e) {
                e.stopPropagation();
                loadProfile(this.dataset.id);
            });
            item.querySelector('.pli-del-btn').addEventListener('click', function(e) {
                e.stopPropagation();
                deleteProfile(e, this.dataset.id, this.dataset.name);
            });

            container.appendChild(item);
        });

    } catch(e) {
        container.innerHTML = '<div class="profile-empty-state" style="color:var(--red);">Could not reach server.</div>';
    }
}

// ── Load profile from server and populate form ────────────
async function loadProfile(clientId) {
    try {
        const res  = await fetch('/clients/' + clientId);
        const data = await res.json();
        if (data.status !== 'success') {
            alert('Could not load profile: ' + (data.message || 'Unknown error'));
            return;
        }
        _applyProfile(data.profile);
        hideProfileModal();
    } catch(e) {
        alert('Server unreachable — could not load profile.');
    }
}

// ── Delete profile on server ──────────────────────────────
async function deleteProfile(e, clientId, clientName) {
    e.stopPropagation();
    if (!confirm('Delete profile "' + (clientName || clientId) + '"?')) return;
    try {
        const res  = await fetch('/clients/' + clientId, { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'success') {
            _renderProfileList();
        } else {
            alert('Delete failed: ' + (data.message || 'Unknown error'));
        }
    } catch(e) {
        alert('Server unreachable — could not delete profile.');
    }
}