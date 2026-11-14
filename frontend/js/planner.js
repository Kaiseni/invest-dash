// Plan d'investissement mensuel selon LA répartition cible choisie par l'utilisateur (menu « Ma répartition »).
const PLAN_COLORS = ['var(--green)', '#60a5fa', '#f59e0b', '#f472b6', '#a78bfa', '#2dd4bf', '#fb923c', '#a3e635', '#e879f9', '#38bdf8', '#facc15', '#f87171'];
const CASH_LEFT_MAX = 10; // on cherche à laisser moins de 10 € non investis (sauf si courtier fractionné, on vise 0)

// Définition des règles par courtier
const BROKERS = {
    'boursobank': { minOrder: 100, fraction: false, name: 'BoursoBank' },
    'traderepublic': { minOrder: 1, fraction: true, name: 'Trade Republic' },
    'xtb': { minOrder: 10, fraction: true, name: 'XTB' },
    'etoro': { minOrder: 10, fraction: true, name: 'eToro' },
    'ibkr': { minOrder: 0.01, fraction: true, name: 'Interactive Brokers' },
    'ig': { minOrder: 0.01, fraction: false, name: 'IG' },
    'saxo': { minOrder: 0.01, fraction: false, name: 'Saxo Banque' }
};

// Familles d'ETF qui répliquent le même indice (comparaison sur le ticker sans suffixe de place)
const INDEX_FAMILIES = {
    WORLD:    ['WPEA', 'DCAM', 'CW8', 'EWLD', 'IWDA', 'VWCE', 'SWRD', 'URTH', 'MWRD'],
    NASDAQ:   ['PNAS', 'LQQ', 'QQQ', 'EQQQ', 'CNDX', 'ANX', 'SXRV'],
    SP500:    ['PSP5', 'CSPX', 'SXR8', 'VUSA', 'VUAA', 'ESE', 'SPY', 'VOO', 'CSSPX'],
    EMERGING: ['PAASI', 'PAEEM', 'EMIM', 'AEEM', 'IEEM', 'EEM']
};

function indexFamily(ticker) {
    const base = String(ticker || '').toUpperCase().split('.')[0];
    for (const [fam, list] of Object.entries(INDEX_FAMILIES)) if (list.includes(base)) return fam;
    return null;
}

// Fusionne les lignes de la répartition qui suivent le même indice : pourcentages additionnés, un seul ticker d'achat (de préférence .PA)
function mergedTargets() {
    const out = [], byFam = {};
    (targets || []).forEach(t => {
        const fam = indexFamily(t.buy) || (t.tickers || []).map(indexFamily).find(Boolean) || null;
        if (fam && byFam[fam]) {
            const m = byFam[fam];
            m.pct = Math.round((m.pct + t.pct) * 100) / 100;
            m.tickers = [...new Set([...m.tickers, ...(t.tickers || []), t.buy])];
            m.labels.push(t.label);
            if (!m.buy.endsWith('.PA') && t.buy.endsWith('.PA')) m.buy = t.buy;
        } else {
            const m = { ...t, tickers: [...new Set([...(t.tickers || []), t.buy])], labels: [t.label], fam };
            out.push(m);
            if (fam) byFam[fam] = m;
        }
    });
    out.forEach(m => { if (m.labels.length > 1) m.label = m.labels.join(' + '); });
    return out;
}

function groupValue(group) {
    const fam = group.fam || indexFamily(group.buy);
    return portfolio
        .filter(a => (group.tickers || []).includes(a.ticker) || (fam && indexFamily(a.ticker) === fam))
        .reduce((s, a) => s + a.total_value, 0);
}

function groupPrice(group) {
    const held = portfolio.find(a => a.ticker === group.buy);
    if (held && held.current_price > 0) return held.current_price;
    return quotes[group.buy] || Infinity; // prix inconnu : on n'achète pas cette ligne (jamais de division par zéro)
}

// Récupère le prix des ETF cibles non détenus (une seule fois), puis recalcule le plan.
async function ensureQuotes() {
    const targets = mergedTargets();
    const missing = targets.map(t => t.buy).filter(t => !portfolio.some(a => a.ticker === t) && !(t in quotes));
    if (!missing.length) return;
    await Promise.all([...new Set(missing)].map(async ticker => {
        try {
            const res = await fetch(`${API_URL}/quote?ticker=${encodeURIComponent(ticker)}`);
            quotes[ticker] = (await res.json()).price || 0;
        } catch (e) { quotes[ticker] = 0; }
    }));
    renderActionPlan();
}

function renderActionPlan() {
    const targets = mergedTargets();
    const container = document.getElementById('actionPlanContent');
    const title = document.getElementById('planTitle');
    const brokerSelect = document.getElementById('brokerSelect');
    
    if (!container) return;
    if (title) title.innerText = targets.length ? `Plan d'investissement mensuel (Cible : ${targets.map(t => `${t.pct} % ${t.label}`).join(' / ')})` : "Plan d'investissement mensuel";

    if (!targets.length) {
        container.innerHTML = '<p class="text-muted">Choisissez d\'abord votre répartition cible avec « ⚙️ Ma répartition ».</p>';
        return;
    }
    if (monthlyBudget <= 0) {
        container.innerHTML = '<p class="text-muted">Définissez un montant à investir chaque mois pour voir la projection.</p>';
        return;
    }
    ensureQuotes();

    // Récupération des règles du courtier sélectionné
    const brokerKey = brokerSelect ? brokerSelect.value : 'boursobank';
    const currentBroker = BROKERS[brokerKey] || BROKERS['boursobank'];
    const min_order = currentBroker.minOrder;
    const can_fraction = currentBroker.fraction;

    const prices = targets.map(groupPrice);
    let simVals = targets.map(groupValue);
    let simCash = unallocatedCash;
    let currentDate = new Date();
    currentDate.setDate(1);
    
    // Si fractions possibles, on ne laisse quasiment aucun cash sur la table.
    const targetCashLeft = can_fraction ? 0.05 : CASH_LEFT_MAX;

    let htmlTable = `
        <p class="text-muted" style="margin-bottom: 15px; font-size: 0.85rem;">
            💡 <strong>Algorithme multi-ordres (${targets.map(t => `${t.pct} % ${esc(t.label)}`).join(' · ')}) :</strong> 
            Achat via ${currentBroker.name} (${can_fraction ? 'Fractions autorisées' : 'Parts entières'}, min ${min_order} € par ordre). 
            Le calculateur répartit le budget sur un ou plusieurs ETF en retard.
        </p>
        <div style="background: rgba(255,255,255,0.02); border-radius: 8px; overflow-x: auto; border: 1px solid var(--border);">
        <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 0.9rem;">
            <thead>
                <tr style="background: rgba(255,255,255,0.05); border-bottom: 1px solid var(--border);">
                    <th style="padding: 12px;">Mois</th>
                    ${targets.map((t, i) => `<th style="padding: 12px; color: ${PLAN_COLORS[i % PLAN_COLORS.length]};">Achat ${esc(t.label)}</th>`).join('')}
                    <th style="padding: 12px; color: var(--text-muted);">Cash reporté</th>
                    <th style="padding: 12px; text-align: right;">Ratio estimé</th>
                </tr>
            </thead>
            <tbody>
    `;

    for (let i = 1; i <= 6; i++) {
        simCash += monthlyBudget;
        
        let targetTotal = simVals.reduce((s, v) => s + v, 0) + simCash;
        let buckets = targets.map((t, idx) => {
            const target = targetTotal * t.pct / 100;
            return { idx, val: simVals[idx], target, deficit: Math.max(0, target - simVals[idx]), price: prices[idx], shares: 0, order: 0 };
        });

        // Tri par déficit décroissant : on sert en priorité l'actif le plus en retard
        buckets.sort((a, b) => b.deficit - a.deficit);

        // ÉTAPE 1 : Allocation multi-actifs intelligente
        for (let idx = 0; idx < buckets.length; idx++) {
            let b = buckets[idx];
            if (simCash < min_order) break;

            let desiredSpend = Math.max(min_order, b.deficit);
            
            let nextHasDeficit = buckets.slice(idx + 1).some(nextB => nextB.deficit >= min_order);
            if (nextHasDeficit && (simCash - desiredSpend) < min_order && simCash >= 2 * min_order) {
                desiredSpend = simCash - min_order;
            } else if (!nextHasDeficit) {
                desiredSpend = simCash;
            }

            let spendCap = Math.min(simCash, desiredSpend);
            
            // Calcul des parts (entières ou fractionnées)
            let shares = can_fraction ? (spendCap / b.price) : Math.floor(spendCap / b.price);
            let cost = shares * b.price;

            // Si parts entières et le prix > plafond, on tente avec tout le cash
            if (!can_fraction && cost < min_order) {
                shares = Math.floor(simCash / b.price);
                cost = shares * b.price;
            }

            if (cost >= min_order) {
                b.shares += shares;
                b.order += cost;
                simCash -= cost;
            }
        }

        // ÉTAPE 2 : Épongeage du reliquat (si on n'a pas atteint l'objectif de cash laissé)
        if (simCash > targetCashLeft) {
            
            // Si fractions, on ajoute directement le cash restant aux ordres existants
            if (can_fraction) {
                let activeOrders = buckets.filter(b => b.order >= min_order).sort((a, b) => b.deficit - a.deficit);
                if (activeOrders.length > 0) {
                     let b = activeOrders[0];
                     let extraShares = simCash / b.price;
                     b.shares += extraShares;
                     b.order += simCash;
                     simCash = 0;
                } else if (simCash >= min_order) {
                     // S'il n'y avait aucun ordre, on crée le premier
                     let bestFallback = buckets.sort((a, b) => b.deficit - a.deficit)[0];
                     if (bestFallback) {
                         bestFallback.shares = simCash / bestFallback.price;
                         bestFallback.order = simCash;
                         simCash = 0;
                     }
                }
            } else {
                // PARTS ENTIÈRES (logique classique)
                let activeOrders = buckets.filter(b => b.order >= min_order).sort((a, b) => a.price - b.price);
                for (let b of activeOrders) {
                    let extraShares = Math.floor(simCash / b.price);
                    if (extraShares > 0) {
                        let extraCost = extraShares * b.price;
                        b.shares += extraShares;
                        b.order += extraCost;
                        simCash -= extraCost;
                    }
                }

                if (simCash > targetCashLeft) {
                    let totalAvailable = simCash + buckets.reduce((sum, b) => sum + b.order, 0);
                    let bestFallback = buckets
                        .map(b => {
                            let s = Math.floor(totalAvailable / b.price);
                            let c = s * b.price;
                            return { bucket: b, shares: s, cost: c, left: totalAvailable - c };
                        })
                        .filter(x => x.cost >= min_order && x.left <= targetCashLeft)
                        .sort((a, b) => b.bucket.deficit - a.bucket.deficit)[0];

                    if (bestFallback) {
                        buckets.forEach(b => { b.shares = 0; b.order = 0; });
                        bestFallback.bucket.shares = bestFallback.shares;
                        bestFallback.bucket.order = bestFallback.cost;
                        simCash = bestFallback.left;
                    }
                }
            }
        }


        buckets.forEach(b => { simVals[b.idx] += b.order; });
        let totalAssets = simVals.reduce((s, v) => s + v, 0);
        let ratios = simVals.map(v => totalAssets > 0 ? ((v / totalAssets) * 100) : 0);
        let ordersByIdx = [];
        buckets.forEach(b => { ordersByIdx[b.idx] = b; });

        let moisLabel = currentDate.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' });
        moisLabel = moisLabel.charAt(0).toUpperCase() + moisLabel.slice(1);
        let cashColor = simCash > targetCashLeft ? 'var(--red)' : 'var(--text-muted)';
        
        // Affichage des parts : 4 décimales si fractions, entier sinon
        const formatShares = s => can_fraction ? s.toFixed(4) : s;

        htmlTable += `
            <tr style="border-bottom: 1px solid var(--border);">
                <td style="padding: 12px; font-weight: bold; text-transform: capitalize;">${moisLabel}</td>
                ${ordersByIdx.map((b, i) => `<td style="padding: 12px;">${b.order >= min_order ? `<strong style="color: ${PLAN_COLORS[i % PLAN_COLORS.length]};">+${b.order.toFixed(2)} €</strong> <br><span style="font-size:0.75rem;color:#888;">(${formatShares(b.shares)} parts)</span>` : '<span style="color: #444;">0 €</span>'}</td>`).join('')}
                <td style="padding: 12px; color: ${cashColor}; font-weight: bold;">${Math.max(0, simCash).toFixed(2)} €</td>
                <td style="padding: 12px; text-align: right;">${ratios.map(v => v.toFixed(0) + '%').join(' / ')}</td>
            </tr>
        `;

        currentDate.setMonth(currentDate.getMonth() + 1);
    }

    htmlTable += `</tbody></table></div>`;
    container.innerHTML = htmlTable;
    
    // Attachement de l'événement sur le select (s'il ne l'est pas déjà)
    if (brokerSelect && !brokerSelect.hasAttribute('data-bound')) {
        brokerSelect.addEventListener('change', renderActionPlan);
        brokerSelect.setAttribute('data-bound', 'true');
    }
}

// ---------------------------------------------------------------- éditeur de la répartition cible
function toggleTargetsEditor(forceOpen) {
    const panel = document.getElementById('targetsEditor');
    const open = forceOpen !== undefined ? forceOpen : panel.style.display === 'none';
    panel.style.display = open ? 'block' : 'none';
    if (open) renderTargetsEditor(targets.length ? targets : defaultTargets());
}

function defaultTargets() {
    // Proposition de départ : les ETF détenus, à parts égales (modifiable avant d'enregistrer)
    const held = portfolio.map(a => a.ticker);
    if (!held.length) return [{ label: 'ETF 1', tickers: [''], buy: '', pct: 100 }];
    const each = Math.floor(10000 / held.length) / 100;
    return held.map((t, i) => ({ label: t.replace('.PA', ''), tickers: [t], buy: t, pct: i === held.length - 1 ? Math.round((100 - each * (held.length - 1)) * 100) / 100 : each }));
}

function renderTargetsEditor(list) {
    const rows = list.map(t => `
        <div class="target-row">
            <input type="text" class="t-label" placeholder="Nom (ex: Monde)" value="${esc(t.label)}">
            <input type="text" class="t-tickers" placeholder="Tickers (ex: DCAM.PA, WPEA.PA)" value="${esc((t.tickers || []).join(', '))}">
            <input type="text" class="t-buy" placeholder="Ticker acheté" value="${esc(t.buy)}">
            <input type="number" class="t-pct" step="0.01" min="0" max="100" placeholder="%" value="${esc(t.pct)}" oninput="updateTargetsTotal()">
            <button class="btn-mini" onclick="this.parentElement.remove(); updateTargetsTotal();" title="Supprimer cette ligne">✕</button>
        </div>`).join('');
    document.getElementById('targetsEditor').innerHTML = `
        <p class="text-muted" style="font-size: 0.82rem; margin-bottom: 10px;">
            Chaque ligne = un « bloc » de votre portefeuille : son nom, les tickers qui en font partie (la valeur de tous ces tickers compte dans le bloc),
            le ticker sur lequel acheter, et le pourcentage visé. Le total doit faire 100 %.
        </p>
        <div id="targetRows">${rows}</div>
        <div style="display: flex; gap: 10px; align-items: center; margin-top: 12px; flex-wrap: wrap;">
            <button class="btn-mini" onclick="addTargetRow()">+ Ajouter une ligne</button>
            <button class="btn-mini" onclick="splitTargetsEvenly()">Répartir à parts égales</button>
            <strong id="targetsTotal" style="margin-left: auto;"></strong>
            <button class="btn-primary" onclick="saveTargets()">Enregistrer</button>
            <button class="btn-mini" onclick="toggleTargetsEditor(false)">Annuler</button>
        </div>
        <div id="targetsError" style="color: var(--red); font-size: 0.85rem; margin-top: 8px;"></div>`;
    updateTargetsTotal();
}

function readTargetRows() {
    return [...document.querySelectorAll('#targetRows .target-row')].map(row => ({
        label: row.querySelector('.t-label').value.trim(),
        tickers: row.querySelector('.t-tickers').value.split(',').map(s => s.trim()).filter(Boolean),
        buy: row.querySelector('.t-buy').value.trim(),
        pct: parseFloat(row.querySelector('.t-pct').value)
    }));
}

function updateTargetsTotal() {
    const total = readTargetRows().reduce((s, t) => s + (isNaN(t.pct) ? 0 : t.pct), 0);
    const el = document.getElementById('targetsTotal');
    if (!el) return;
    const ok = Math.abs(total - 100) < 0.01;
    el.innerText = `Total : ${Math.round(total * 100) / 100} %`;
    el.style.color = ok ? 'var(--green)' : 'var(--red)';
}

function addTargetRow() {
    renderTargetsEditor([...readTargetRows(), { label: '', tickers: [], buy: '', pct: 0 }]);
}

function splitTargetsEvenly() {
    const rows = readTargetRows();
    if (!rows.length) return;
    const each = Math.floor(10000 / rows.length) / 100;
    rows.forEach((r, i) => { r.pct = i === rows.length - 1 ? Math.round((100 - each * (rows.length - 1)) * 100) / 100 : each; });
    renderTargetsEditor(rows);
}

async function saveTargets() {
    const errEl = document.getElementById('targetsError');
    errEl.innerText = '';
    try {
        const data = await postJSON('/targets', { targets: readTargetRows() });
        targets = data.targets;
        toggleTargetsEditor(false);
        renderActionPlan();
        checkDrift();
    } catch (e) {
        errEl.innerText = e.message;
    }
}