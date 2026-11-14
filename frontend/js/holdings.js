// Composition des ETF (JustETF) + heatmap consolidée.

async function loadHoldings() {
    const grid = document.getElementById('holdingsGrid');
    grid.innerHTML = '<p class="text-muted" style="margin-left:20px;">Analyse de vos actifs et connexion au marché en cours... (Cela prend quelques secondes)</p>';
    
    try {
        const response = await fetch(`${API_URL}/holdings`);
        const assets = await response.json();
        
        grid.innerHTML = '';
        if (assets.length === 0) {
            grid.innerHTML = '<p class="text-muted" style="margin-left:20px;">Votre portefeuille est vide.</p>';
            if (heatmapChartObj) heatmapChartObj.destroy();
            return;
        }

        let globalHoldings = {};
        let totalPortfolioValue = 0;

        assets.forEach(asset => {
            totalPortfolioValue += asset.total_value;
            if (asset.holdings && asset.holdings.length > 0) {
                asset.holdings.forEach(h => {
                    // On regroupe les lignes d'une même société (ex. Alphabet (A) + Alphabet (C))
                    let cleanName = h.name.replace(/( Inc\.| Corp\.| Group| Platforms| Ltd\.| Holdings)/gi, '').replace(/\s*\((?:A|B|C|Class [A-C])\)/gi, '').trim();
                    if (!globalHoldings[cleanName]) {
                        globalHoldings[cleanName] = { value: 0, perf: h.live_perf || 0 };
                    }
                    globalHoldings[cleanName].value += h.value;
                });
            }
        });

        let treeData = Object.keys(globalHoldings)
            .map(name => ({
                name: name,
                value: globalHoldings[name].value,
                perf: globalHoldings[name].perf
            }))
            .sort((a, b) => b.value - a.value);

        const ctx = document.getElementById('holdingsHeatmap').getContext('2d');
        if (heatmapChartObj) heatmapChartObj.destroy();

        // Fonction sécurisée pour extraire l'objet d'origine depuis le noeud Treemap
        const getDataObj = (raw) => {
            if (!raw || !raw._data) return { name: '', value: 0, perf: 0 };
            if (Array.isArray(raw._data)) return raw._data[0];
            if (raw._data.children && Array.isArray(raw._data.children)) return raw._data.children[0];
            return raw._data;
        };

        heatmapChartObj = new Chart(ctx, {
            type: 'treemap',
            data: {
                datasets: [{
                    tree: treeData,
                    key: 'value',
                    groups: ['name'],
                    spacing: 2,
                    borderWidth: 1,
                    borderColor: '#0a0a0a',
                    backgroundColor: function(context) {
                        if (context.type !== 'data') return 'transparent';
                        
                        const dataObj = getDataObj(context.raw);
                        const perf = dataObj.perf || 0;
                        
                        if (perf === 0) return 'rgba(100, 100, 100, 0.4)';

                        if (perf > 0) {
                            const intensity = Math.min(0.2 + (perf / 4) * 0.8, 1);
                            return `rgba(34, 197, 94, ${intensity})`; 
                        } else {
                            const intensity = Math.min(0.2 + (Math.abs(perf) / 4) * 0.8, 1);
                            return `rgba(239, 68, 68, ${intensity})`; 
                        }
                    },
                    labels: {
                        display: true,
                        color: '#ffffff',
                        font: { family: '-apple-system, BlinkMacSystemFont, sans-serif', size: 12, weight: 'bold' },
                        formatter: (context) => {
                            const dataObj = getDataObj(context.raw);
                            const val = context.raw.v || 0;
                            const pct = ((val / totalPortfolioValue) * 100).toFixed(1);
                            
                            if (pct < 0.5) return []; 
                            
                            const perf = dataObj.perf || 0;
                            const perfStr = perf > 0 ? `+${perf.toFixed(2)}%` : `${perf.toFixed(2)}%`;
                            
                            return [dataObj.name, `${pct}%`, perfStr];
                        }
                    }
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    datalabels: { display: false },
                    tooltip: {
                        callbacks: {
                            title: (items) => {
                                return getDataObj(items[0].raw).name;
                            },
                            label: (item) => {
                                const dataObj = getDataObj(item.raw);
                                const val = item.raw.v || 0;
                                const pct = ((val / totalPortfolioValue) * 100).toFixed(2);
                                
                                const perf = dataObj.perf || 0;
                                const perfStr = perf > 0 ? `+${perf.toFixed(2)}%` : `${perf.toFixed(2)}%`;
                                
                                return [
                                    `Valeur consolidée : ${val.toLocaleString('fr-FR', {style: 'currency', currency: 'EUR'})} (${pct}%)`,
                                    `Performance du jour : ${perfStr}`
                                ];
                            }
                        }
                    }
                }
            }
        });

        // Rendu des tableaux d'actifs existants
        assets.forEach(asset => {
            const card = document.createElement('div');
            card.className = 'holdings-card';
            
            let contentHTML = `
                <h2 style="font-size: 1.2rem; color: var(--text-main); margin-bottom: 5px;">${esc(asset.name)}</h2>
                <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 5px;">
                    ${esc(asset.ticker)} • Valeur actuelle : <strong style="color:white;">${asset.total_value.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €</strong>
                </p>
            `;

            if (asset.holdings && asset.holdings.length > 0) {
                contentHTML += `
                    <table class="holdings-table">
                        <thead>
                            <tr>
                                <th style="text-align: left;">Entreprise</th>
                                <th style="text-align: right;">Poids (%)</th>
                                <th style="text-align: right;">Jour (%)</th>
                                <th style="text-align: right;">Valeur (€)</th>
                            </tr>
                        </thead>
                        <tbody>
                `;
                
                asset.holdings.forEach(h => {
                    const perfClass = h.live_perf > 0 ? 'perf-pos' : (h.live_perf < 0 ? 'perf-neg' : '');
                    const perfStr = h.live_perf > 0 ? `+${h.live_perf.toFixed(2)}%` : `${h.live_perf.toFixed(2)}%`;
                    
                    contentHTML += `
                        <tr>
                            <td class="col-name" title="${esc(h.name)}">${esc(h.name)}</td>
                            <td class="col-percent">${h.percent.toFixed(2)}%</td>
                            <td class="${perfClass}" style="text-align: right; font-size: 0.85rem; font-weight: bold;">${perfStr}</td>
                            <td class="col-value">${h.value.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €</td>
                        </tr>
                    `;
                });
                
                contentHTML += `</tbody></table>`;
            } else {
                contentHTML += `
                    <div class="empty-holdings">
                        Données de composition introuvables.
                    </div>
                `;
            }
            
            card.innerHTML = contentHTML;
            grid.appendChild(card);
        });
    } catch (error) {
        console.error("Erreur holdings:", error);
        grid.innerHTML = '<p class="perf-neg" style="margin-left:20px;">Erreur lors du chargement des données.</p>';
    }
}
