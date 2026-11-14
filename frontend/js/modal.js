// Fenêtre détaillée d'un actif.

function openModal(ticker) {
    const asset = portfolio.find(a => a.ticker === ticker);
    if (!asset) return;
    
    currentModalTicker = ticker;

    document.getElementById('modalTitle').innerText = asset.name;
    document.getElementById('modalTicker').innerText = asset.ticker;
    document.getElementById('modalPrice').innerText = `${asset.current_price.toFixed(4)} ${asset.currency_symbol}`;
    
    document.getElementById('sellPriceInput').value = asset.current_price.toFixed(4);
    document.getElementById('sellQtyInput').value = asset.qty;

    const perfDay = asset.current_price - asset.prev_close;
    const perfDayPct = asset.prev_close > 0 ? (perfDay / asset.prev_close) * 100 : 0;
    const perfEl = document.getElementById('modalPerf');
    perfEl.innerText = `${perfDay >= 0 ? '+' : ''}${perfDayPct.toFixed(2)}% aujourd'hui`;
    perfEl.className = `modal-perf ${perfDay >= 0 ? 'perf-pos' : 'perf-neg'}`;

    const buyTotal = asset.invested_value !== undefined ? asset.invested_value : (asset.buy_price * asset.qty);
    const diff = asset.gain_loss !== undefined ? asset.gain_loss : (asset.total_value - buyTotal);
    const percent = asset.gain_loss_pct !== undefined ? asset.gain_loss_pct : (buyTotal > 0 ? (diff / buyTotal) * 100 : 0);
    const sign = diff >= 0 ? '+' : '';

    document.getElementById('modalQty').innerText = `${asset.qty} parts`;
    document.getElementById('modalBuyPrice').innerText = `${asset.buy_price.toFixed(4)} ${asset.currency_symbol}`;
    document.getElementById('modalInvested').innerText = `${buyTotal.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${asset.currency_symbol}`;
    
    const modalGLEl = document.getElementById('modalGainLoss');
    modalGLEl.innerText = `${sign}${diff.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${asset.currency_symbol} (${sign}${percent.toFixed(2)}%)`;
    modalGLEl.className = diff >= 0 ? 'perf-pos' : 'perf-neg';

    document.getElementById('modalOpen').innerText = `${asset.open_price.toFixed(4)} ${asset.currency_symbol}`;
    document.getElementById('modalPrev').innerText = `${asset.prev_close.toFixed(4)} ${asset.currency_symbol}`;
    document.getElementById('modalHigh').innerText = `${asset.day_high.toFixed(4)} ${asset.currency_symbol}`;
    document.getElementById('modalLow').innerText = `${asset.day_low.toFixed(4)} ${asset.currency_symbol}`;
    document.getElementById('modalSummaryText').innerText = asset.summary;
    
    renderModalLots(asset);
    document.getElementById('assetModal').style.display = 'flex';
    updateChartPeriod(currentModalChartPeriod);
}

async function updateChartPeriod(period) {
    currentModalChartPeriod = period;
    document.querySelectorAll('#assetModal .filter-btn').forEach(btn => {
        btn.classList.remove('active');
        if(btn.getAttribute('data-period') === period) btn.classList.add('active');
    });

    if (!currentModalTicker) return;

    try {
        const response = await fetch(`${API_URL}/history?ticker=${currentModalTicker}&period=${period}`);
        const data = await response.json();
        if (data.error) return;

        const ctx = document.getElementById('modalChart').getContext('2d');
        if (modalChartObj) modalChartObj.destroy();
        
        const isPos = data.prices[data.prices.length - 1] >= data.prices[0];
        const chartColor = isPos ? '#22c55e' : '#ef4444';
        const bgColor = isPos ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)';

        modalChartObj = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.dates,
                datasets: [{
                    data: data.prices, borderColor: chartColor, backgroundColor: bgColor,
                    borderWidth: 2, fill: true, pointRadius: 0, pointHoverRadius: 6, tension: 0.1 
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: { legend: { display: false }, datalabels: { display: false } },
                scales: {
                    x: { display: true, grid: { display: false }, ticks: { color: '#8b8d96', maxTicksLimit: 6 } },
                    y: { display: true, position: 'right', grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#8b8d96' } }
                }
            }
        });
    } catch (e) {
        console.error("Erreur historique:", e);
    }
}

function closeModal() {
    document.getElementById('assetModal').style.display = 'none';
}

function renderModalLots(asset) {
    const box = document.getElementById('modalLots');
    const lots = asset.lots || [];
    if (!lots.length) { box.innerHTML = '<p class="text-muted" style="font-size: 0.85rem;">Aucune entrée.</p>'; return; }
    const f = v => Number(v).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    box.innerHTML = `
        <div style="background: #0a0a0a; border: 1px solid var(--border); border-radius: 12px; overflow-x: auto;">
        <table style="width: 100%; border-collapse: collapse; font-size: 0.82rem; white-space: nowrap;">
            <thead><tr class="text-muted" style="text-align: left;">
                <th style="padding: 8px 10px;">Date</th><th style="padding: 8px 10px;">Qté</th>
                <th style="padding: 8px 10px;">Prix (frais inclus)</th><th style="padding: 8px 10px;">Coût</th><th></th>
            </tr></thead>
            <tbody>${lots.map(l => `
                <tr style="border-top: 1px solid var(--border);">
                    <td style="padding: 8px 10px;">${l.date ? esc(l.date) : '<span class="text-muted">ancienne saisie</span>'}</td>
                    <td style="padding: 8px 10px;">${l.qty}</td>
                    <td style="padding: 8px 10px;">${Number(l.price).toFixed(4)} €</td>
                    <td style="padding: 8px 10px;">${f(l.qty * l.price)} €</td>
                    <td style="padding: 8px 10px; text-align: right;"><button class="btn-mini" title="Supprimer cette entrée" onclick="deleteLot(${l.id})">🗑</button></td>
                </tr>`).join('')}
            </tbody>
        </table></div>`;
}

async function deleteLot(lotId) {
    if (!currentModalTicker) return;
    if (!confirm("Supprimer cette entrée d'achat ?\n\nLa quantité et le PRU de la ligne sont recalculés et le coût de cet achat revient dans votre liquidité disponible.\n(Pour une vente réelle, utilisez « Vendre ».)")) return;
    try {
        const data = await postJSON('/lots/delete', { ticker: currentModalTicker, lot_id: lotId });
        await fetchPortfolioData();
        renderDashboard();
        if (data.position_deleted) {
            closeModal();
            showToast("Dernière entrée supprimée : l'actif a été retiré.", false);
        } else {
            openModal(currentModalTicker);
            showToast('Entrée supprimée.', false);
        }
    } catch (e) {
        showToast(e.message, true);
    }
}