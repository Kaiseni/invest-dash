// Graphiques de la synthèse : patrimoine, allocation, mini-courbes.

async function updateMainChartPeriod(period) {
    currentMainChartPeriod = period;
    document.querySelectorAll('#mainChartFilters .filter-btn').forEach(btn => {
        btn.classList.remove('active');
        if(btn.getAttribute('data-period') === period) btn.classList.add('active');
    });

    const requestId = ++mainChartRequestId;
    try {
        const response = await fetch(`${API_URL}/portfolio_history?period=${period}`);
        const data = await response.json();
        if (requestId !== mainChartRequestId) return; // une requête plus récente est partie
        if (data.error || !data.dates || data.dates.length === 0) return;

        // L'historique ne contient que les titres : on ajoute la liquidité (dispo + bloquée)
        // pour que la courbe soit sur la même base que le "Patrimoine brut" affiché.
        const cashPart = (portfolioSummary.available_cash || 0) + (portfolioSummary.locked_cash || 0);
        const totals = data.totals.map(v => v + cashPart);

        // Dernier point = valeur live (Boursorama)
        const lastHist = totals[totals.length - 1];
        if (currentTotalWealth > 0 && lastHist > 0 && Math.abs(currentTotalWealth - lastHist) / lastHist > 0.03) {
            console.warn(`Écart historique (${lastHist.toFixed(2)}) vs live (${currentTotalWealth.toFixed(2)}) > 3% : vérifiez /api/portfolio_history`);
        }
        totals[totals.length - 1] = currentTotalWealth;

        drawMainChart(data.dates, totals);
    } catch (e) {
        console.error("Erreur historique global:", e);
    }
}

function drawMainChart(labels, data) {
    if (mainChartObj) mainChartObj.destroy();
    const resetHeader = () => updateHeaderStats(portfolioSummary.total_wealth || 0, portfolioSummary.gain_loss_amount || 0, portfolioSummary.gain_loss_pct || 0);
    mainChartObj = buildWealthChart(document.getElementById('mainChart'), labels, data, {
        onHover: (wealth) => {
            const invested = portfolioSummary.total_invested || 0;
            const gl = wealth - invested;
            updateHeaderStats(wealth, gl, invested > 0 ? (gl / invested) * 100 : 0, false);
        },
        onLeave: resetHeader
    });
}

function drawAllocationChart() {
    if (allocChartObj) allocChartObj.destroy();
    const labels = portfolio.map(a => a.ticker);
    const data = portfolio.map(a => a.total_value);
    const colors = portfolio.map(a => a.color);
    if (unallocatedCash > 0) { labels.push("Liquidité"); data.push(unallocatedCash); colors.push("#4b5563"); }
    allocChartObj = buildAllocChart(document.getElementById('allocationChart'), labels, data, colors);
    updateDashboardSavings();
}

function drawSparkline(canvasId, data, color) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const chart = new Chart(ctx, {
        type: 'line',
        data: { labels: data.map((_, i) => i), datasets: [{ data: data, borderColor: color, borderWidth: 1.5, pointRadius: 0, tension: 0.3 }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false }, datalabels: { display: false } },
            scales: { x: { display: false }, y: { display: false } }, layout: { padding: 0 }
        }
    });
    sparklineCharts.push(chart);
}

// ---- Fabriques partagées (Bourse + Crypto & Matières) : même rendu, mêmes comportements
function buildWealthChart(canvas, labels, data, { onHover, onLeave }) {
    const fmtEUR = v => v.toLocaleString('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 });
    const chart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels,
            datasets: [{
                data, borderColor: '#c89a74',
                backgroundColor: (context) => {
                    const { chart } = context;
                    if (!chart.chartArea) return 'rgba(200,154,116,0.2)';
                    const g = chart.ctx.createLinearGradient(0, chart.chartArea.top, 0, chart.chartArea.bottom);
                    g.addColorStop(0, 'rgba(200, 154, 116, 0.4)');
                    g.addColorStop(1, 'rgba(200, 154, 116, 0.0)');
                    return g;
                },
                borderWidth: 2, fill: true, pointRadius: 0, pointHoverRadius: 5, tension: 0.2
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            layout: { padding: { top: 8, right: 4, bottom: 0, left: 0 } },
            interaction: { mode: 'index', intersect: false },
            onHover: (e, els, ch) => { if (els.length && onHover) onHover(ch.data.datasets[0].data[els[0].index]); },
            plugins: {
                legend: { display: false },
                tooltip: { mode: 'index', intersect: false, callbacks: { label: c => ' ' + c.parsed.y.toLocaleString('fr-FR', { style: 'currency', currency: 'EUR' }) } },
                datalabels: { display: false }
            },
            scales: {
                x: { display: true, offset: false, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#8b8d96', maxTicksLimit: 7, maxRotation: 0, autoSkip: true } },
                y: { display: true, position: 'right', grace: '5%', grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#8b8d96', callback: v => fmtEUR(v) } }
            }
        }
    });
    canvas.onmouseout = () => { if (onLeave) onLeave(); };
    return chart;
}

function buildAllocChart(canvas, labels, data, colors) {
    return new Chart(canvas.getContext('2d'), {
        type: 'doughnut',
        data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 3, borderColor: '#141414' }] },
        options: {
            responsive: true, maintainAspectRatio: false, cutout: '70%',
            plugins: {
                legend: { display: false },
                datalabels: {
                    color: '#ffffff', font: { weight: 'bold', size: 10.5 }, textAlign: 'center',
                    formatter: (value, ctx) => {
                        const sum = ctx.chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
                        const pct = (value * 100 / sum).toFixed(0);
                        if (pct < 5) return '';
                        return `${ctx.chart.data.labels[ctx.dataIndex].split('.')[0]}\n${pct}%`;
                    },
                    rotation: (ctx) => {
                        const arc = ctx.chart.getDatasetMeta(0).data[ctx.dataIndex];
                        if (!arc) return 0;
                        let deg = ((arc.startAngle + arc.endAngle) / 2) * (180 / Math.PI) + 90;
                        if (deg > 90 && deg < 270) deg -= 180;
                        return deg;
                    }
                }
            }
        }
    });
}