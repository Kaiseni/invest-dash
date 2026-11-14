// Crypto & matières premières : même présentation que la Synthèse (graphique, camembert, cartes) + cours en direct.
let altCatalog = null;
let altState = { items: [], total_value: 0, total_invested: 0, total_pl: 0 };
let altHistory = { dates: [], totals: [] };
let altPeriod = '1mo';
let altMainChart = null;
let altAllocChart = null;
let altHistoryRequestId = 0;

const altNum = (v, d = 2) => v == null ? '—' : Number(v).toLocaleString('fr-FR', { minimumFractionDigits: d, maximumFractionDigits: d });
const altPrice = v => v == null ? '—' : altNum(v, v < 1 ? 4 : 2) + ' €';
const altPct = v => v == null ? '<span class="text-muted">—</span>' : `<span class="${v >= 0 ? 'perf-pos' : 'perf-neg'}">${v >= 0 ? '+' : ''}${altNum(v)} %</span>`;
const altUSD = v => v == null ? '—' : Number(v).toLocaleString('fr-FR', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: v < 1 ? 4 : 2 });
const altPriceUsd = v => v == null ? '' : `<span class="text-muted" style="font-size: 0.75rem;">≈ ${altUSD(v)}</span>`;
const altEUR = v => Number(v).toLocaleString('fr-FR', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const altCash = () => altState.cash || 0;
const altWealth = () => (altState.total_value || 0) + altCash();   // positions + liquidités (comme « Bourse + Liquidité »)
// Base de la performance : total viré sur le wallet s'il est renseigné, sinon investi + liquidités
const altBase = () => (altState.deposited > 0) ? altState.deposited : (altState.total_invested || 0) + altCash();
function altShow(wealth) {
    const base = altBase();
    const gain = wealth - base;
    updateAltHeader(wealth, gain, base > 0 ? (gain / base) * 100 : 0);
}
function altHeaderReset() { altShow(altWealth()); }

async function updateAltDeposited() {
    const value = parseFloat(document.getElementById('altDepositedInput').value) || 0;
    try {
        await postJSON('/alt/deposited', { deposited: value });
        await loadAlt();
    } catch (e) { alert(e.message); }
}
// ---------------------------------------------------------------- chargement
async function loadAlt(quiet) {
    const status = document.getElementById('altStatus');
    if (!quiet) status.innerText = 'Chargement des cours…';
    try {
        const [holdingsRes, marketRes, soldRes] = await Promise.all([fetch(`${API_URL}/alt/holdings`), fetch(`${API_URL}/alt/market`), fetch(`${API_URL}/alt/sold`)]);
        const holdings = await holdingsRes.json();
        const market = await marketRes.json();
        renderAltSold(await soldRes.json());
        altCatalog = market.catalog;
        altState = holdings;
        renderAltMarket(market);
        renderAltHoldings(holdings);
        updateAltForm();
        if (!quiet || !altHistory.dates.length) await loadAltHistory();
        else refreshAltLastPoint();
        const missing = [...market.crypto, ...market.commodities].filter(q => q.price == null).length;
        status.innerText = (missing ? `${missing} cours indisponible(s) · ` : '') + `mis à jour à ${new Date().toLocaleTimeString('fr-FR')} (auto. 30 s)`;
    } catch (e) {
        status.innerText = 'Erreur de chargement des cours';
        console.error(e);
    }
}

async function updateAltChartPeriod(period) {
    altPeriod = period;
    document.querySelectorAll('#altFilters .filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-period') === period);
    });
    await loadAltHistory();
}

async function loadAltHistory() {
    const requestId = ++altHistoryRequestId;
    const empty = document.getElementById('altChartEmpty');
    if (!altState.items.length && altCash() <= 0.005) {
        altHistory = { dates: [], totals: [] };
        if (altMainChart) { altMainChart.destroy(); altMainChart = null; }
        empty.innerText = "Ajoutez une position pour voir l'évolution de votre patrimoine.";
        empty.style.display = 'flex';
        return;
    }
    try {
        const res = await fetch(`${API_URL}/alt/history?period=${altPeriod}`);
        const data = await res.json();
        if (requestId !== altHistoryRequestId) return;
        if (data.error || !data.dates || !data.dates.length) {
            empty.innerText = "Historique indisponible pour le moment.";
            empty.style.display = 'flex';
            return;
        }
        empty.style.display = 'none';
        data.totals = data.totals.map(v => v + altCash());       // on ajoute la liquidité à chaque point
        data.totals[data.totals.length - 1] = altWealth();       // dernier point = valeur actuelle exacte
        altHistory = data;
        drawAltMainChart(altHistory.dates, altHistory.totals);
    } catch (e) {
        console.error('Erreur historique crypto/matières:', e);
    }
}

// Rafraîchissement léger (toutes les 30 s) : on ne refait pas tout l'historique, on met juste à jour le dernier point.
function refreshAltLastPoint() {
    if (!altMainChart || !altHistory.totals.length) return;
    altHistory.totals[altHistory.totals.length - 1] = altWealth();
    altMainChart.data.datasets[0].data = altHistory.totals;
    altMainChart.update('none');
}

// ---------------------------------------------------------------- en-tête, cartes, camembert
function updateAltHeader(value, gain, pct) {
    document.getElementById('altTotal').innerText = altEUR(value);
    const sign = gain >= 0 ? '+' : '';
    const cls = gain >= 0 ? 'perf-pos' : 'perf-neg';
    document.getElementById('altGain').innerHTML = `<span class="${cls}">${sign}${altNum(gain)} € (${sign}${altNum(pct)}%)</span>`;
}

function renderAltHoldings(h) {
    const invested = h.total_invested || 0;
    altHeaderReset();
    const depEl = document.getElementById('altDepositedInput');
    if (depEl && document.activeElement !== depEl) depEl.value = h.deposited > 0 ? h.deposited : '';
    document.getElementById('altInvested').innerText = altEUR(invested);
    const plEl = document.getElementById('altPL');
    plEl.className = h.total_pl >= 0 ? 'perf-pos' : 'perf-neg';
    plEl.innerText = `${h.total_pl >= 0 ? '+' : ''}${altEUR(h.total_pl)}`;
    document.getElementById('altCount').innerText = h.items.length;
        document.getElementById('altCash').innerText = altEUR(h.cash || 0);
    document.getElementById('altValueUsd').innerText = h.items.length ? altUSD(h.total_value_usd) : '—';

    const grid = document.getElementById('altCards');
    if (!h.items.length) {
        grid.innerHTML = '<p class="text-muted alt-empty">Aucune position pour le moment : ajoutez-en une avec le formulaire ci-dessous.</p>';
    } else {
        // on garde ouvertes les listes d'entrées que l'utilisateur avait dépliées (le rafraîchissement auto reconstruit les cartes)
        const open = new Set([...document.querySelectorAll('#altCards details[open]')].map(d => d.dataset.id));
        grid.innerHTML = h.items.map((i, idx) => {
            const color = CHART_COLORS[idx % CHART_COLORS.length];
            const perfCls = (i.pl || 0) >= 0 ? 'perf-pos' : 'perf-neg';
            const unit = i.kind === 'commodity' ? (i.unit === 'g' ? ' g' : ' oz/unité') : '';
            const lots = (i.lots || []).map(l => `
                <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 0.78rem; padding: 5px 0; border-top: 1px solid var(--border);">
                    <span class="text-muted">${l.date ? esc(l.date) : 'ancienne saisie'}</span>
                    <span>${altNum(l.qty, 6).replace(/,?0+$/, '')}${unit} à ${altNum(l.price, l.price < 1 ? 4 : 2)} €</span>
                    <button class="btn-mini" style="padding: 2px 8px;" title="Supprimer cette entrée" onclick="deleteAltLot(${i.id}, ${l.id})">🗑</button>
                </div>`).join('');
            return `
            <div class="asset-card" style="cursor: default;">
                <div class="asset-info">
                    <div class="asset-name"><span class="color-dot" style="background: ${color};"></span>${esc(i.name)}</div>
                    <div class="asset-ticker">${esc(i.symbol)} · ${altPct(i.change_pct)} sur 24 h</div>
                    <div class="asset-invested">Prix : ${altPrice(i.price)} ${altPriceUsd(i.price_usd)}</div>
                    <div class="asset-invested">${altNum(i.qty, 6).replace(/,?0+$/, '')}${unit} à ${altNum(i.buy_price, i.buy_price < 1 ? 4 : 2)} € = ${altEUR(i.invested)} investis</div>
                    <div class="asset-perf ${perfCls}">${i.pl == null ? '—' : `${i.pl >= 0 ? '+' : ''}${altNum(i.pl)} € (${i.pl_pct >= 0 ? '+' : ''}${altNum(i.pl_pct)} %)`}</div>
                    <details data-id="${i.id}" ${open.has(String(i.id)) ? 'open' : ''} style="margin-top: 10px;">
                        <summary class="text-muted" style="cursor: pointer; font-size: 0.8rem;">Mes entrées d'achat (${(i.lots || []).length})</summary>
                        <div style="margin-top: 6px;">${lots}</div>
                    </details>
                    <div style="margin-top: 12px; display: flex; gap: 8px;">
                        <button class="btn-primary" style="padding: 6px 14px;" onclick="openAltSell(${i.id})">Vendre</button>
                        <button class="btn-mini" onclick="deleteAlt(${i.id})" title="Supprime toute la position sans l'enregistrer comme une vente">Supprimer tout</button>
                    </div>
                </div>
            </div>`;
        }).join('');
    }
    drawAltAllocation(h.items, h.cash || 0);
}

function drawAltAllocation(items, cash) {
    if (altAllocChart) altAllocChart.destroy();
    // une part par position valorisée + une part « Liquidités » (argent des ventes disponible)
    const slices = items
        .map((i, idx) => ({ label: i.symbol, value: i.value, color: CHART_COLORS[idx % CHART_COLORS.length] }))
        .filter(s => s.value != null && s.value > 0);
    if (cash > 0.005) slices.push({ label: 'Liquidités', value: cash, color: '#94a3b8' });

    altAllocChart = buildAllocChart(document.getElementById('altAllocChart'), slices.map(s => s.label), slices.map(s => s.value), slices.map(s => s.color));

    const crypto = items.filter(i => i.kind === 'crypto' && i.value).reduce((s, i) => s + i.value, 0);
    const commodities = items.filter(i => i.kind === 'commodity' && i.value).reduce((s, i) => s + i.value, 0);
    document.getElementById('altAllocNote').innerHTML = (items.length || cash > 0.005)
        ? `Crypto : <strong style="color: var(--text-main);">${altEUR(crypto)}</strong> · Matières premières : <strong style="color: var(--text-main);">${altEUR(commodities)}</strong> · Liquidités : <strong style="color: var(--text-main);">${altEUR(cash)}</strong>`
        : '—';
}

// ---------------------------------------------------------------- graphique d'évolution
function drawAltMainChart(labels, data) {
    if (altMainChart) altMainChart.destroy();
    altMainChart = buildWealthChart(document.getElementById('altMainChart'), labels, data, {
        onHover: (wealth) => altShow(wealth),
        onLeave: altHeaderReset
    });
}

// ---------------------------------------------------------------- cours du marché
function renderAltMarket(m) {
    const row = q => `<tr style="border-bottom: 1px solid var(--border);">
        <td style="padding: 9px 6px;"><strong>${esc(q.name)}</strong> <span class="text-muted" style="font-size: 0.75rem;">${esc(q.symbol)}</span></td>
        <td style="padding: 9px 6px; text-align: right;">${altPrice(q.price)}<br>${altPriceUsd(q.price_usd)}${q.price_per_g ? `<br><span class="text-muted" style="font-size: 0.75rem;">${altNum(q.price_per_g)} €/g · ${altUSD(q.price_per_g_usd)}/g</span>` : (q.kind === 'commodity' ? `<br><span class="text-muted" style="font-size: 0.75rem;">par ${esc(q.unit)}</span>` : '')}</td>
        <td style="padding: 9px 6px; text-align: right;">${altPct(q.change_pct)}</td></tr>`;
    const head = '<table style="width: 100%; border-collapse: collapse; font-size: 0.88rem;"><thead><tr class="text-muted" style="text-align: left;"><th style="padding: 6px;">Actif</th><th style="padding: 6px; text-align: right;">Prix</th><th style="padding: 6px; text-align: right;">24 h</th></tr></thead><tbody>';
    document.getElementById('altCrypto').innerHTML = head + m.crypto.map(row).join('') + '</tbody></table>';
    document.getElementById('altCommodities').innerHTML = head + m.commodities.map(row).join('') + '</tbody></table>';
}

// ---------------------------------------------------------------- formulaire
function updateAltForm() {
    const kind = document.getElementById('altKind').value;
    const symbolEl = document.getElementById('altSymbol');
    const commEl = document.getElementById('altCommodity');
    const unitEl = document.getElementById('altUnit');
    symbolEl.style.display = kind === 'crypto' ? 'block' : 'none';
    commEl.style.display = kind === 'commodity' ? 'block' : 'none';
    if (altCatalog) {
        document.getElementById('altSymbols').innerHTML = Object.entries(altCatalog.crypto).map(([s, n]) => `<option value="${esc(s)}">${esc(n)}</option>`).join('');
        if (!commEl.options.length) {
            commEl.innerHTML = Object.entries(altCatalog.commodities).map(([s, c]) => `<option value="${esc(s)}">${esc(c.name)} (par ${esc(c.unit)})</option>`).join('');
        }
    }
    const metal = kind === 'commodity' && altCatalog && altCatalog.commodities[commEl.value] && altCatalog.commodities[commEl.value].metal;
    unitEl.style.display = metal ? 'block' : 'none';
    if (!metal) unitEl.value = 'base';
}

async function addAlt() {
    const kind = document.getElementById('altKind').value;
    const msg = document.getElementById('altMsg');
    const symbol = kind === 'crypto' ? document.getElementById('altSymbol').value : document.getElementById('altCommodity').value;
    try {
        await postJSON('/alt/add', {
            kind, symbol,
            qty: parseFloat(document.getElementById('altQty').value),
            buy_price: parseFloat(document.getElementById('altPrice').value),
            fees: parseFloat(document.getElementById('altFees').value) || 0,
            unit: document.getElementById('altUnit').value,
            from_cash: document.getElementById('altFromCash').checked
        });
        ['altQty', 'altPrice', 'altFees'].forEach(id => { document.getElementById(id).value = ''; });
        document.getElementById('altFromCash').checked = false;
        msg.style.display = 'none';
        loadAlt();
    } catch (e) {
        msg.style.display = 'block';
        msg.style.color = 'var(--red)';
        msg.innerText = e.message;
    }
}

async function deleteAlt(id) {
    if (!confirm('Supprimer cette position ?')) return;
    await postJSON('/alt/delete', { id });
    loadAlt();
}

// Rafraîchissement automatique des cours tant que l'onglet est affiché (et la page visible)
setInterval(() => {
    const view = document.getElementById('view-alt');
    if (view && view.style.display !== 'none' && !document.hidden) loadAlt(true);
}, 30000);

// ---------------------------------------------------------------- ventes et plus-values réalisées
let altSellId = null;

function altUnitLabel(i) { return i.kind === 'commodity' ? (i.unit === 'g' ? 'gramme' : 'unité') : 'unité'; }

function openAltSell(id) {
    const item = altState.items.find(i => i.id === id);
    if (!item) return;
    altSellId = id;
    document.getElementById('altSellTitle').innerText = `Vendre ${item.name} (${item.symbol})`;
    document.getElementById('altSellInfo').innerText =
        `Vous détenez ${altNum(item.qty, 6).replace(/,?0+$/, '')} (${altUnitLabel(item)}), prix de revient ${altNum(item.buy_price, item.buy_price < 1 ? 4 : 2)} €. Le prix de vente se saisit par ${altUnitLabel(item)}, en euros.`;
    document.getElementById('altSellQty').value = item.qty;
    document.getElementById('altSellPrice').value = item.price != null ? Number(item.price).toFixed(item.price < 1 ? 6 : 4) : '';
    document.getElementById('altSellFees').value = '';
    document.getElementById('altSellError').innerText = '';
    updateAltSellPreview();
    document.getElementById('altSellModal').style.display = 'flex';
}

function closeAltSell() {
    document.getElementById('altSellModal').style.display = 'none';
    altSellId = null;
}

function updateAltSellPreview() {
    const item = altState.items.find(i => i.id === altSellId);
    const el = document.getElementById('altSellPreview');
    const qty = parseFloat(document.getElementById('altSellQty').value);
    const price = parseFloat(document.getElementById('altSellPrice').value);
    const fees = parseFloat(document.getElementById('altSellFees').value) || 0;
    if (!item || !(qty > 0) || !(price > 0)) { el.innerText = ''; return; }
    const gross = Math.round(qty * price * 100) / 100;
    const net = Math.round((gross - fees) * 100) / 100;
    const gl = Math.round(((price - item.buy_price) * qty - fees) * 100) / 100;
    el.style.color = 'var(--text-main)';
    el.innerHTML = `Brut ${altEUR(gross)} − frais ${altEUR(fees)} = <strong>${altEUR(net)}</strong> reçus<br>Plus-value réalisée : <strong class="${gl >= 0 ? 'perf-pos' : 'perf-neg'}">${gl >= 0 ? '+' : ''}${altEUR(gl)}</strong>`;
}

async function confirmAltSell() {
    try {
        const data = await postJSON('/alt/sell', {
            id: altSellId,
            qty: parseFloat(document.getElementById('altSellQty').value),
            sell_price: parseFloat(document.getElementById('altSellPrice').value),
            fees: parseFloat(document.getElementById('altSellFees').value) || 0
        });
        closeAltSell();
        alert(data.message);
        loadAlt();
    } catch (e) {
        document.getElementById('altSellError').innerText = e.message;
    }
}

function renderAltSold(data) {
    const section = document.getElementById('altSoldSection');
    const realizedEl = document.getElementById('altRealized');
    const total = data.total_realized_gl || 0;
    realizedEl.className = total >= 0 ? 'perf-pos' : 'perf-neg';
    realizedEl.innerText = `${total >= 0 ? '+' : ''}${altEUR(total)}`;
    if (!data.sales || !data.sales.length) { section.style.display = 'none'; return; }
    section.style.display = 'block';
    const rows = data.sales.map(s => {
        const cls = s.realized_gl >= 0 ? 'perf-pos' : 'perf-neg';
        const unit = s.unit === 'g' ? ' g' : '';
        return `<tr style="border-bottom: 1px solid var(--border);">
            <td style="padding: 9px 6px;">${esc(s.sold_date)}</td>
            <td style="padding: 9px 6px;"><strong>${esc(s.name)}</strong> <span class="text-muted" style="font-size: 0.75rem;">${esc(s.symbol)}</span></td>
            <td style="padding: 9px 6px;">${altNum(s.qty, 6).replace(/,?0+$/, '')}${unit}</td>
            <td style="padding: 9px 6px;">${altNum(s.buy_price, s.buy_price < 1 ? 4 : 2)} €</td>
            <td style="padding: 9px 6px;">${altNum(s.sell_price, s.sell_price < 1 ? 4 : 2)} €</td>
            <td style="padding: 9px 6px;">${altEUR(s.gross)}</td>
            <td style="padding: 9px 6px; color: var(--red);">− ${altEUR(s.fees || 0)}</td>
            <td style="padding: 9px 6px;"><strong>${altEUR(s.net)}</strong></td>
            <td style="padding: 9px 6px; text-align: right;" class="${cls}"><strong>${s.realized_gl >= 0 ? '+' : ''}${altEUR(s.realized_gl)}</strong></td>
            <td style="padding: 9px 6px; text-align: right; white-space: nowrap;">
                <button class="btn-mini" title="Annuler la vente : la quantité revient dans la position" onclick="cancelAltSale(${s.id}, true)">↩ Annuler</button>
                <button class="btn-mini" title="Supprimer seulement la ligne" onclick="cancelAltSale(${s.id}, false)">🗑</button>
            </td></tr>`;
    }).join('');
    document.getElementById('altSoldContent').innerHTML = `
        <p style="margin-bottom: 10px; font-size: 0.9rem;">Cumul des plus-values réalisées : <strong class="${total >= 0 ? 'perf-pos' : 'perf-neg'}">${total >= 0 ? '+' : ''}${altEUR(total)}</strong>
        <span class="text-muted"> · frais payés : ${altEUR(data.total_fees || 0)}</span></p>
        <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem; white-space: nowrap;">
            <thead><tr class="text-muted" style="text-align: left;"><th style="padding: 6px;">Date</th><th style="padding: 6px;">Actif</th><th style="padding: 6px;">Qté</th><th style="padding: 6px;">Prix de revient</th><th style="padding: 6px;">Prix de vente</th><th style="padding: 6px;">Brut</th><th style="padding: 6px;">Frais</th><th style="padding: 6px;">Net reçu</th><th style="padding: 6px; text-align: right;">+/- value</th><th></th></tr></thead>
            <tbody>${rows}</tbody></table>`;
}

async function cancelAltSale(id, restore) {
    const message = restore
        ? "Annuler cette vente ?\n\nLa quantité revient dans la position (au prix de revient d'origine) et la ligne est supprimée."
        : "Supprimer seulement cette ligne ?\n\nLa quantité ne revient PAS dans la position.";
    if (!confirm(message)) return;
    try {
        await postJSON('/alt/sold/delete', { id, restore });
        loadAlt();
    } catch (e) { alert(e.message); }
}

// Apport (montant positif) ou retrait (montant négatif) de liquidités
async function adjustAltCash() {
    const raw = prompt("Montant en € à ajouter à vos liquidités (positif) ou à retirer (négatif).\nEx : 500 pour un apport, -200 pour un retrait.");
    if (raw === null) return;
    const amount = parseFloat(String(raw).replace(',', '.'));
    if (!amount) return;
    try {
        await postJSON('/alt/cash', { amount });
        loadAlt();
    } catch (e) {
        alert(e.message);
    }
}

async function deleteAltLot(posId, lotId) {
    if (!confirm("Supprimer cette entrée d'achat ?\n\nLa quantité et le prix de revient de la position sont recalculés. Si cet achat avait été payé avec vos liquidités, elles vous sont rendues.\n(Pour une vente réelle, utilisez « Vendre ».)")) return;
    try {
        await postJSON('/alt/lots/delete', { id: posId, lot_id: lotId });
        loadAlt();
    } catch (e) {
        alert(e.message);
    }
}