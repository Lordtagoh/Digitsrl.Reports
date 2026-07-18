/* Report Vendite — decifratura client-side (AES-256-GCM + PBKDF2-SHA-256)
   e rendering. Nessun backend: i dati arrivano da data/report.enc.json. */

'use strict';

const STORAGE_KEY = 'daily-report-password';
const DATA_URL = 'data/report.enc.json';

const CATEGORY_LABELS = {
    mobile: 'Mobile',
    fisso: 'Fisso',
    sky_nm: 'Sky TV/Wifi',
    sky_m: 'Sky Mobile',
    altro: 'Altro',
};

const CATEGORY_DOTS = {
    mobile: '#FFA500',
    fisso: '#90EE90',
    sky_nm: '#87CEFA',
    sky_m: '#20B2AA',
    altro: '#9a9aa0',
};

const $ = (id) => document.getElementById(id);

/* ── Crittografia ────────────────────────────────────────────── */

function b64ToBytes(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
}

async function decryptReport(payload, password) {
    const baseKey = await crypto.subtle.importKey(
        'raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveKey']);
    const key = await crypto.subtle.deriveKey(
        {
            name: 'PBKDF2',
            salt: b64ToBytes(payload.salt),
            iterations: payload.iterations,
            hash: 'SHA-256',
        },
        baseKey,
        { name: 'AES-GCM', length: 256 },
        false, ['decrypt']);
    const plaintext = await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: b64ToBytes(payload.iv) },
        key, b64ToBytes(payload.ciphertext));
    return JSON.parse(new TextDecoder().decode(plaintext));
}

/* ── Rendering ───────────────────────────────────────────────── */

function fmtMult(n) {
    return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, '').replace('.', ',');
}

function isDarkColor(hex) {
    const n = parseInt(hex.slice(1), 16);
    const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return (0.299 * r + 0.587 * g + 0.114 * b) < 140;
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function renderSummaryGroup(container, title, entries) {
    container.textContent = '';
    if (!Object.keys(entries).length) return;
    container.appendChild(el('span', 'mini-title', title));
    for (const [name, v] of Object.entries(entries)) {
        const item = el('span', 'mini-item');
        item.appendChild(el('b', '', name));
        item.appendChild(document.createTextNode(
            ` ${v.count} (${fmtMult(v.mult)} pt)`));
        container.appendChild(item);
    }
}

function renderSaleCard(sale) {
    const card = el('article', 'sale-card');
    card.style.backgroundColor = sale.color;
    if (isDarkColor(sale.color)) card.classList.add('on-dark');

    const top = el('div', 'sale-top');
    const icon = document.createElement('img');
    icon.src = `img/providers/${sale.icon}.png`;
    icon.alt = sale.provider || '';
    top.appendChild(icon);
    top.appendChild(el('span', 'sale-time', sale.time));
    top.appendChild(el('span', 'sale-customer', sale.customer || '—'));
    top.appendChild(el('span', 'sale-mult', `×${fmtMult(sale.mult)}`));
    card.appendChild(top);

    const detailParts = [sale.contract, sale.options].filter(
        (x) => x && x !== '???');
    if (detailParts.length)
        card.appendChild(el('div', 'sale-detail', detailParts.join(' — ')));

    const meta = el('div', 'sale-meta');
    meta.appendChild(el('span', 'tag', `${sale.pos} · ${sale.seller || '?'}`));
    if (sale.kind) meta.appendChild(el('span', 'tag', sale.kind));
    if (sale.mnp) meta.appendChild(el('span', 'tag', 'MNP'));
    if (sale.business) meta.appendChild(el('span', 'tag', 'Business'));
    if (sale.fwa) meta.appendChild(el('span', 'tag', 'FWA'));
    else if (sale.landline) meta.appendChild(el('span', 'tag', 'Fisso'));
    if (sale.notInTarget) meta.appendChild(el('span', 'tag', 'Fuori target'));
    if (sale.recharge) meta.appendChild(el('span', 'tag', `Ricarica ${sale.recharge}€`));
    if (sale.leasing) {
        const parts = [sale.leasing.brand, sale.leasing.model]
            .filter(Boolean).join(' ');
        const value = sale.leasing.value
            ? ` ${Number(sale.leasing.value).toFixed(2).replace('.', ',')}€` : '';
        meta.appendChild(el('span', 'tag', `📱 ${parts}${value}`));
    }
    card.appendChild(meta);
    return card;
}

function renderReport(report) {
    const date = new Date(report.reportDate + 'T00:00:00');
    $('report-date').textContent = date.toLocaleDateString('it-IT', {
        weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    });

    // KPI
    const kpis = $('kpi-row');
    kpis.textContent = '';
    for (const [value, label] of [
        [String(report.totals.count), 'Vendite'],
        [fmtMult(report.totals.mult), 'Punti'],
    ]) {
        const tile = el('div', 'kpi');
        tile.appendChild(el('div', 'kpi-value', value));
        tile.appendChild(el('div', 'kpi-label', label));
        kpis.appendChild(tile);
    }

    // Categorie
    const chips = $('category-summary');
    chips.textContent = '';
    for (const [cat, v] of Object.entries(report.totals.byCategory)) {
        if (!v.count) continue;
        const chip = el('span', 'chip');
        const dot = el('span', 'dot');
        dot.style.backgroundColor = CATEGORY_DOTS[cat] || '#9a9aa0';
        chip.appendChild(dot);
        chip.appendChild(el('b', '', `${CATEGORY_LABELS[cat] || cat} ${v.count}`));
        chip.appendChild(el('span', 'chip-mult', `${fmtMult(v.mult)} pt`));
        chips.appendChild(chip);
    }

    renderSummaryGroup($('pos-summary'), 'Negozi', report.totals.byPos);
    renderSummaryGroup($('seller-summary'), 'Venditori', report.totals.bySeller);

    // Lista vendite
    const list = $('sales-list');
    list.textContent = '';
    if (!report.sales.length) {
        list.appendChild(el('p', 'empty-day', 'Nessuna vendita registrata oggi.'));
    } else {
        for (const sale of report.sales) list.appendChild(renderSaleCard(sale));
    }

    $('generated-at').textContent = `Report generato il ${report.generatedAt}`;

    $('loading-screen').classList.add('hidden');
    $('unlock-screen').classList.add('hidden');
    $('report').classList.remove('hidden');
}

/* ── Flusso di sblocco ───────────────────────────────────────── */

function showUnlock(withError) {
    $('loading-screen').classList.add('hidden');
    $('report').classList.add('hidden');
    $('unlock-screen').classList.remove('hidden');
    $('unlock-error').classList.toggle('hidden', !withError);
    $('password-input').focus();
}

async function init() {
    let payload;
    try {
        const res = await fetch(DATA_URL, { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        payload = await res.json();
    } catch (err) {
        $('loading-screen').querySelector('.unlock-hint').textContent =
            'Impossibile caricare i dati del report. Riprova più tardi.';
        return;
    }

    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
        try {
            renderReport(await decryptReport(payload, saved));
            return;
        } catch {
            localStorage.removeItem(STORAGE_KEY);
        }
    }
    showUnlock(false);

    $('unlock-form').addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const btn = $('unlock-btn');
        const password = $('password-input').value;
        btn.disabled = true;
        btn.textContent = 'Sblocco…';
        try {
            const report = await decryptReport(payload, password);
            if ($('remember-check').checked)
                localStorage.setItem(STORAGE_KEY, password);
            renderReport(report);
        } catch {
            showUnlock(true);
        } finally {
            btn.disabled = false;
            btn.textContent = 'Sblocca';
        }
    });
}

$('forget-btn').addEventListener('click', () => {
    localStorage.removeItem(STORAGE_KEY);
    location.reload();
});

init();
