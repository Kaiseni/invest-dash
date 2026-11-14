// Portefeuille : chargement, ajout / suppression / vente, en-tête, cartes d'actifs, ordres en attente.

async function fetchPortfolioData() {
    // Portefeuille et budget demandés en parallèle
    const [response, budgetRes, targetsRes] = await Promise.all([fetch(`${API_URL}/portfolio`), fetch(`${API_URL}/budget`), fetch(`${API_URL}/targets`)]);
    if (!response.ok) throw new Error(`/portfolio : ${response.status}`);
    const data = await response.json();
    const budgetData = await budgetRes.json();
    targets = (await targetsRes.json()).targets || [];
    
    data.assets.forEach((asset, index) => {
        const existing = portfolio.find(a => a.ticker === asset.ticker);
        asset.color = existing ? existing.color : CHART_COLORS[index % CHART_COLORS.length];
    });
    
    portfolio = data.assets;
    portfolioSummary = data.summary;
    unallocatedCash = portfolioSummary.available_cash || 0; // Le simulateur DCA utilisera le vrai cash dispo
    currentTotalWealth = portfolioSummary.total_wealth || 0;
    pendingOrders = portfolioSummary.pending_orders || [];

    monthlyBudget = budgetData.budget || 0;

    const budgetInputEl = document.getElementById('budgetInput');
    if (budgetInputEl && document.activeElement !== budgetInputEl) budgetInputEl.value = monthlyBudget === 0 ? '' : monthlyBudget;
    
    // Remplissage automatique du champ Total Versé
    const depInputEl = document.getElementById('depositedInput');
    if (depInputEl && document.activeElement !== depInputEl) depInputEl.value = portfolioSummary.total_deposited === 0 ? '' : portfolioSummary.total_deposited;
    const feesEl = document.getElementById('feesTotalInput');
    if (feesEl && document.activeElement !== feesEl) feesEl.value = portfolioSummary.other_fees ? portfolioSummary.other_fees : '';
}

async function updateBudget() {
    const budgetValue = document.getElementById('budgetInput').value || 0;
    try {
        await fetch(`${API_URL}/budget`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ budget: parseFloat(budgetValue) })
        });
        await fetchPortfolioData();
        renderDashboard();
    } catch(e) {
        console.error(e);
    }
}

async function updateFeesTotal() {
    const value = parseFloat(document.getElementById('feesTotalInput').value) || 0;
    try {
        await postJSON('/fees', { fees: value });
        await fetchPortfolioData();
        renderDashboard();
    } catch (e) { alert(e.message); }
}

async function updateDeposited() {
    const depValue = document.getElementById('depositedInput').value || 0;
    try {
        await fetch(`${API_URL}/deposited`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ deposited: parseFloat(depValue) })
        });
        await fetchPortfolioData();
        renderDashboard();
    } catch(e) { console.error(e); }
}

async function addAsset() {
    const ticker = document.getElementById('tickerInput').value;
    const qty = document.getElementById('qtyInput').value;
    const buyPrice = document.getElementById('buyPriceInput').value;
    const fees = parseFloat(document.getElementById('feesInput').value) || 0;

    if (!ticker || !qty || !buyPrice) return showToast("Remplissez tous les champs obligatoires.", true);

    const response = await fetch(`${API_URL}/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, qty: parseFloat(qty), buy_price: parseFloat(buyPrice), fees })
    });
    
    const data = await response.json();
    if (data.error) return showToast("Erreur: " + data.error, true);
    
    if (data.message) showToast(data.message, false);

    await fetchPortfolioData();
    renderDashboard();
    fetchNews(); 
    
    document.getElementById('tickerInput').value = '';
    document.getElementById('qtyInput').value = '';
    document.getElementById('buyPriceInput').value = '';
    document.getElementById('feesInput').value = '';
}

async function deleteCurrentAsset() {
    if (!currentModalTicker) return;
    if (!confirm(`Voulez-vous vraiment supprimer l'actif ${currentModalTicker} de votre portefeuille ?`)) {
        return;
    }
    try {
        const response = await fetch(`${API_URL}/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticker: currentModalTicker })
        });
        
        const data = await response.json().catch(() => ({}));
        if (!response.ok && !data.error) return showToast(`Erreur serveur (${response.status})`, true);
        if (data.success) {
            await fetchPortfolioData();
            closeModal();
            renderDashboard();
            fetchNews();
            showToast("Actif supprimé avec succès.", false);
        } else {
            showToast("Erreur lors de la suppression.", true);
        }
    } catch (e) {
        console.error("Erreur suppression:", e);
        showToast("Erreur de connexion avec le serveur.", true);
    }
}

async function sellCurrentAsset() {
    if (!currentModalTicker) return;
    const qty = document.getElementById('sellQtyInput').value;
    const sellPrice = document.getElementById('sellPriceInput').value;

    if (!qty || !sellPrice) return showToast("Remplissez la quantité et le prix de vente.", true);

    try {
        const response = await fetch(`${API_URL}/sell`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticker: currentModalTicker, qty: parseFloat(qty), sell_price: parseFloat(sellPrice) })
        });

        const data = await response.json();
        if (data.error) return showToast("Erreur: " + data.error, true);

        showToast(data.message, false);
        document.getElementById('sellQtyInput').value = '';
        document.getElementById('sellPriceInput').value = '';
        updateSellPreview();

        await fetchPortfolioData();
        closeModal();
        renderDashboard();
        fetchSoldHistory();
    } catch (e) {
        console.error("Erreur vente:", e);
        showToast("Erreur de connexion avec le serveur.", true);
    }
}

async function fetchSoldHistory() {
    try {
        const response = await fetch(`${API_URL}/sold`);
        const data = await response.json();
        sellCommissionRate = data.commission_rate ?? sellCommissionRate;

        const section = document.getElementById('soldSection');
        const container = document.getElementById('soldContent');

        if (!data.sales || data.sales.length === 0) {
            section.style.display = 'none';
            return;
        }
        section.style.display = 'block';

        const money = v => Number(v).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        const totalSign = data.total_realized_gl >= 0 ? '+' : '';
        const totalClass = data.total_realized_gl >= 0 ? 'perf-pos' : 'perf-neg';

        let html = `
            <p style="margin-bottom: 12px; font-size: 0.9rem;">
                Cumul net des ventes réalisées : <strong class="${totalClass}">${totalSign}${money(data.total_realized_gl)} €</strong>
                <span class="text-muted"> · commissions payées (${(sellCommissionRate * 100).toLocaleString('fr-FR')} %) : ${money(data.total_commission)} €</span>
            </p>
            <div style="background: rgba(255,255,255,0.02); border-radius: 8px; overflow-x: auto; border: 1px solid var(--border);">
            <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 0.85rem; white-space: nowrap;">
                <thead>
                    <tr style="background: rgba(255,255,255,0.05); border-bottom: 1px solid var(--border);">
                        <th style="padding: 10px;">Date</th>
                        <th style="padding: 10px;">Ticker</th>
                        <th style="padding: 10px;">Qté</th>
                        <th style="padding: 10px;">PRU d'achat</th>
                        <th style="padding: 10px;">Prix de vente</th>
                        <th style="padding: 10px;">Montant brut</th>
                        <th style="padding: 10px;">Commission</th>
                        <th style="padding: 10px;">Net reçu (brut − commission)</th>
                        <th style="padding: 10px; text-align: right;">+/- value réalisée</th>
                        <th style="padding: 10px; text-align: right;">Corriger</th>
                    </tr>
                </thead>
                <tbody>
        `;
        data.sales.forEach(s => {
            const sign = s.realized_gl >= 0 ? '+' : '';
            const cls = s.realized_gl >= 0 ? 'perf-pos' : 'perf-neg';
            html += `
                <tr style="border-bottom: 1px solid var(--border);">
                    <td style="padding: 10px;">${esc(s.sold_date)}</td>
                    <td style="padding: 10px; font-weight: bold;">${esc(s.ticker)}</td>
                    <td style="padding: 10px;">${s.qty}</td>
                    <td style="padding: 10px;">${s.buy_price.toFixed(4)} €</td>
                    <td style="padding: 10px;">${s.sell_price.toFixed(4)} €</td>
                    <td style="padding: 10px;">${money(s.gross)} €</td>
                    <td style="padding: 10px; color: var(--red);">− ${money(s.commission)} €</td>
                    <td style="padding: 10px;"><strong>${money(s.net)} €</strong></td>
                    <td style="padding: 10px; text-align: right;" class="${cls}"><strong>${sign}${money(s.realized_gl)} €</strong></td>
                    <td style="padding: 10px; text-align: right;">
                        <button class="btn-mini" title="Annuler la vente : les parts reviennent dans le portefeuille" onclick="cancelSale(${s.id}, true)">↩ Annuler</button>
                        <button class="btn-mini" title="Supprimer seulement la ligne (sans remettre les parts)" onclick="cancelSale(${s.id}, false)">🗑</button>
                    </td>
                </tr>
            `;
        });
        html += `</tbody></table></div>`;
        container.innerHTML = html;
    } catch (e) {
        console.error("Erreur historique ventes:", e);
    }
}

function updateHeaderStats(wealthVal, gainLossAmount, gainLossPct, updatePill = true) {
    document.getElementById('totalWealth').innerText = wealthVal.toLocaleString('fr-FR', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 });

    let glSign = gainLossAmount >= 0 ? '+' : '';
    let glClass = gainLossAmount >= 0 ? 'perf-pos' : 'perf-neg';
    let formattedGL = `${glSign}${gainLossAmount.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} € (${glSign}${gainLossPct.toFixed(2)}%)`;

    let glElement = document.getElementById('totalGainLoss');
    if (glElement) {
        glElement.innerHTML = `<span class="${glClass}">${formattedGL}</span>`;
    }

    // Au survol du graphique on ne touche pas à la pastille : sa largeur changeait et faisait sauter la mise en page
    let latentDetailEl = updatePill ? document.getElementById('latentGainLossDetail') : null;
    if (latentDetailEl) {
        latentDetailEl.className = glClass;
        latentDetailEl.innerText = formattedGL;
    }
}

function renderDashboard() {
    updateHeaderStats(portfolioSummary.total_wealth || 0, portfolioSummary.gain_loss_amount || 0, portfolioSummary.gain_loss_pct || 0);

    const setHtml = (id, val, formatOpts) => {
        const el = document.getElementById(id);
        if (el) el.innerText = val.toLocaleString('fr-FR', formatOpts);
    };
    
    setHtml('totalAssetsValue', portfolioSummary.total_assets_value || 0, { style: 'currency', currency: 'EUR' });
    setHtml('currentCashDisplay', portfolioSummary.available_cash || 0, { style: 'currency', currency: 'EUR' });
    const cashEl = document.getElementById('currentCashDisplay');
    if (cashEl && portfolioSummary.cash_inconsistent) {
        cashEl.innerText += ' ⚠';
        cashEl.title = "Total viré inférieur aux achats + ordres en attente : vérifiez le total viré ou vos prix d'achat.";
    } else if (cashEl) {
        cashEl.title = '';
    }
    setHtml('lockedCashDisplay', portfolioSummary.locked_cash || 0, { style: 'currency', currency: 'EUR' });

    let realizedEl = document.getElementById('realizedGLDisplay');
    if (realizedEl) {
        let rGL = portfolioSummary.total_realized_gl || 0;
        realizedEl.innerText = `${rGL > 0 ? '+' : ''}${rGL.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €`;
        realizedEl.style.color = rGL > 0 ? 'var(--green)' : (rGL < 0 ? 'var(--red)' : '#a78bfa');
    }

    if (portfolio.length === 0 && unallocatedCash === 0 && pendingOrders.length === 0) {
        document.getElementById('assetsGrid').innerHTML = '<p class="text-muted">Aucun actif.</p>';
        if (mainChartObj) mainChartObj.destroy();
        if (allocChartObj) allocChartObj.destroy();
        renderPendingOrders();
        return;
    }

    updateMainChartPeriod(currentMainChartPeriod);
    drawAllocationChart();
    renderAssetCards();
    renderPendingOrders();
    renderActionPlan();
    checkDrift();
}

function checkDrift() {
    // Alerte si une ligne s'écarte de plus de 5 points de la répartition cible choisie par l'utilisateur
    const alertEl = document.getElementById('driftAlert');
    if (!alertEl) return;
    const targets = mergedTargets();
    const values = targets.map(groupValue);
    const total = values.reduce((s, v) => s + v, 0);
    if (!targets.length || total === 0) { alertEl.style.display = 'none'; return; }
    const isDrifting = targets.some((t, i) => Math.abs(values[i] / total - t.pct / 100) > 0.05);
    alertEl.style.display = isDrifting ? 'block' : 'none';
}

function renderAssetCards() {
    const grid = document.getElementById('assetsGrid');
    sparklineCharts.forEach(ch => ch.destroy()); // évite d'accumuler des graphiques orphelins à chaque rafraîchissement
    sparklineCharts = [];
    grid.innerHTML = '';

    portfolio.forEach(asset => {
        const buyTotal = asset.invested_value !== undefined ? asset.invested_value : (asset.buy_price * asset.qty);
        const diff = asset.gain_loss !== undefined ? asset.gain_loss : (asset.total_value - buyTotal);
        const percent = asset.gain_loss_pct !== undefined ? asset.gain_loss_pct : (buyTotal > 0 ? (diff / buyTotal) * 100 : 0);
        const isPos = diff >= 0;
        const sign = isPos ? '+' : '';

        // Badge d'écart US/EU avec design Trading dynamique
        let gapHTML = '';
        if (asset.proxy_name && asset.estimated_gap_pct !== undefined) {
            let isZero = asset.estimated_gap_pct === 0;
            let gapSign = asset.estimated_gap_pct > 0 ? '+' : '';
            let gapColor = asset.estimated_gap_pct > 0 ? '#10b981' : (asset.estimated_gap_pct < 0 ? '#ef4444' : '#9ca3af');
            let gapBg = asset.estimated_gap_pct > 0 ? 'rgba(16, 185, 129, 0.15)' : (asset.estimated_gap_pct < 0 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(156, 163, 175, 0.15)');
            let gapIcon = asset.estimated_gap_pct > 0 ? '↗' : (asset.estimated_gap_pct < 0 ? '↘' : '→');
            
            let statusText = isZero ? `Synchronisé (${asset.proxy_name})` : `Live via ${esc(asset.proxy_name)}`;
            
            gapHTML = `
                <div style="margin-top: 18px; padding: 12px; width: 100%; box-sizing: border-box; background: linear-gradient(145deg, rgba(35,35,35,0.6) 0%, rgba(20,20,20,0.9) 100%); border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); transition: all 0.2s ease-in-out; cursor: default;" 
                     onmouseover="this.style.borderColor='${gapColor}60'; this.style.transform='translateY(-2px)'; this.style.boxShadow='0 4px 12px rgba(0,0,0,0.3)';" 
                     onmouseout="this.style.borderColor='rgba(255,255,255,0.05)'; this.style.transform='translateY(0)'; this.style.boxShadow='none';">
                    
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <div style="display: flex; align-items: center; gap: 6px; font-size: 0.75rem; color: #a1a1aa;">
                            <span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: ${gapColor}; box-shadow: 0 0 8px ${gapColor};"></span>
                            ${statusText}
                        </div>
                        <div style="font-size: 0.75rem; font-weight: bold; color: ${gapColor}; background: ${gapBg}; padding: 3px 6px; border-radius: 4px;">
                            ${gapIcon} ${gapSign}${asset.estimated_gap_pct.toFixed(2)}%
                        </div>
                    </div>
                    
                    <div style="display: flex; justify-content: space-between; align-items: baseline;">
                        <div style="font-size: 0.85rem; color: ${gapColor}; font-weight: 500;">
                            Écart : ${gapSign}${asset.estimated_gap_eur.toFixed(4)} €
                        </div>
                        <div style="font-size: 1.15rem; color: #ffffff; font-weight: bold; font-family: ui-monospace, monospace; letter-spacing: 0.5px;">
                            ≈ ${asset.estimated_price.toFixed(4)} €
                        </div>
                    </div>
                </div>
            `;
        }

        const card = document.createElement('div');
        card.className = 'asset-card';
        card.onclick = () => openModal(asset.ticker);

        card.innerHTML = `
            <!-- EN-TÊTE : Titre seul -->
            <div style="margin-bottom: 12px; width: 100%;">
                <div class="asset-name" title="${esc(asset.name)}" style="font-size: 0.95rem; font-weight: 600; line-height: 1.3; margin-bottom: 4px; display: flex; align-items: flex-start;">
                    <span class="color-dot" style="background-color: ${asset.color}; margin-top: 4px;"></span>
                    <span style="display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;">${esc(asset.name)}</span>
                </div>
                <div class="asset-ticker" style="margin-left: 18px; font-size: 0.75rem; color: var(--text-muted);">${esc(asset.ticker)}</div>
            </div>

            <!-- CORPS : Prix part, Valeur Totale, PRU -->
            <div style="display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px;">
                <div style="font-size: 1.6rem; font-weight: 600;">${asset.total_value.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €</div>
                <div style="font-size: 0.85rem; color: var(--text-muted);">(Part: <strong style="color: white;">${asset.current_price.toFixed(4)} €</strong>)</div>
            </div>
            
            <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 6px;">
                ${asset.qty} parts investies à ${asset.buy_price.toFixed(4)} €
            </div>

            <div class="asset-perf ${isPos ? 'perf-pos' : 'perf-neg'}" style="font-size: 0.9rem; font-weight: 600;">
                Plus-value : ${sign}${diff.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} € (${sign}${percent.toFixed(2)}%)
            </div>

            <!-- GRAPHIQUE EN DESSOUS (sur toute la largeur) -->
            <div class="mini-chart"><canvas id="sparkline-${esc(asset.ticker)}"></canvas></div>

            <!-- BADGE PRÉDICTION -->
            ${gapHTML}
        `;
        
        grid.appendChild(card);
        drawSparkline(`sparkline-${asset.ticker}`, asset.prices || [], isPos ? '#22c55e' : '#ef4444');
    });
}

async function addPendingOrder() {
    const ticker = document.getElementById('pendingTicker').value;
    const qty = document.getElementById('pendingQty').value;
    const price = document.getElementById('pendingPrice').value;
    if (!ticker || !qty || !price) return alert("Remplissez Ticker, Qté et Prix limite.");

    try {
        await fetch(`${API_URL}/pending`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticker, qty: parseFloat(qty), limit_price: parseFloat(price) })
        });
        document.getElementById('pendingTicker').value = '';
        document.getElementById('pendingQty').value = '';
        document.getElementById('pendingPrice').value = '';
        await fetchPortfolioData();
        renderDashboard();
    } catch(e) { console.error(e); }
}

async function deletePendingOrder(id) {
    try {
        await fetch(`${API_URL}/pending/delete`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id })
        });
        await fetchPortfolioData();
        renderDashboard();
    } catch(e) { console.error(e); }
}

function renderPendingOrders() {
    const grid = document.getElementById('pendingOrdersGrid');
    if (!grid) return;
    grid.innerHTML = '';
    
    if (pendingOrders.length === 0) {
        grid.innerHTML = '<p class="text-muted" style="grid-column: 1 / -1;">Aucun ordre en attente.</p>';
        return;
    }

    pendingOrders.forEach(o => {
        const card = document.createElement('div');
        card.className = 'asset-card';
        card.style.cursor = 'default';
        card.style.borderColor = 'rgba(251, 191, 36, 0.4)'; // Bordure jaune
        card.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                <div>
                    <div style="font-weight: bold; font-size: 1.1rem; color: #fbbf24;">${esc(o.ticker)}</div>
                    <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 5px;">Achat limite : <strong>${o.limit_price.toFixed(4)} €</strong></div>
                    <div style="font-size: 0.85rem; color: var(--text-muted);">Quantité : <strong>${o.qty}</strong></div>
                </div>
                <button onclick="deletePendingOrder(${o.id})" style="background: transparent; color: var(--red); border: none; font-size: 1.2rem; cursor: pointer; padding: 0 5px;">&times;</button>
            </div>
            <div style="margin-top: 15px; font-size: 0.85rem; font-weight: 600; padding-top: 10px; border-top: 1px solid var(--border);">
                Fonds bloqués : <span style="color: white;">${o.locked_cash.toLocaleString('fr-FR', {style:'currency', currency:'EUR'})}</span>
            </div>
        `;
        grid.appendChild(card);
    });
}


// Aperçu de la commission de revente pendant la saisie
function updateSellPreview() {
    const qty = parseFloat(document.getElementById('sellQtyInput').value);
    const price = parseFloat(document.getElementById('sellPriceInput').value);
    const el = document.getElementById('sellPreview');
    if (!el) return;
    if (!(qty > 0) || !(price > 0)) { el.innerText = `Commission de revente : ${(sellCommissionRate * 100).toLocaleString('fr-FR')} % du montant brut`; return; }
    const gross = Math.round(qty * price * 100) / 100;
    const commission = Math.round(gross * sellCommissionRate * 100) / 100;
    const f = v => v.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    el.innerText = `Brut ${f(gross)} € − commission ${f(commission)} € = net reçu ${f(gross - commission)} €`;
}

// Corriger une vente saisie par erreur : l'annuler (les parts reviennent) ou supprimer seulement la ligne
async function cancelSale(id, restore) {
    const message = restore
        ? "Annuler cette vente ?\n\nLes parts seront remises dans votre portefeuille (au prix de revient d'origine) et la ligne sera supprimée. Vous pourrez ensuite ressaisir la vente avec les bonnes valeurs."
        : "Supprimer seulement cette ligne de l'historique ?\n\nLes parts ne seront PAS remises dans le portefeuille, et la plus-value réalisée disparaît du calcul de votre liquidité.";
    if (!confirm(message)) return;
    try {
        await postJSON('/sold/delete', { id, restore });
        await fetchPortfolioData();
        renderDashboard();
        fetchSoldHistory();
    } catch (e) {
        alert(e.message);
    }
}