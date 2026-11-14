// Simulation Monte-Carlo.

async function runMonteCarlo() {
    const yearsInput = document.getElementById('mcYearsInput');
    if (!yearsInput) return;
    const years = yearsInput.value || 10;
    
    const btn = document.querySelector('button[onclick="runMonteCarlo()"]');
    if (btn) { btn.innerText = "Calcul..."; btn.disabled = true; }

    try {
        const response = await fetch(`${API_URL}/simulation`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ years: parseInt(years), monthly: parseFloat(document.getElementById('mcMonthlyInput').value) || 0 })        });
        const data = await response.json();
        
        if (data.error) {
            document.getElementById('mcStats').innerHTML = `<span style="color:var(--red);">Erreur: ${data.error}</span>`;
            if (btn) { btn.innerText = "Simuler"; btn.disabled = false; }
            return;
        }

        document.getElementById('mcStats').innerHTML = `Généré à partir de 1000 scénarios. Rendement espéré : <strong style="color:white;">${data.mu}%/an</strong> | Volatilité : <strong style="color:white;">${data.sigma}%</strong> | Chute max hist. : <strong style="color:var(--red);">-${data.max_drawdown}%</strong> | Ratio de Sharpe : <strong style="color:white;">${data.sharpe}</strong>`;

        const ctx = document.getElementById('mcChart').getContext('2d');
        if (mcChartObj) mcChartObj.destroy();

        mcChartObj = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: 'Optimiste (Top 10%)',
                        data: data.optimistic,
                        borderColor: '#34d399',
                        borderDash: [5, 5],
                        borderWidth: 2,
                        // Rempli l'espace jusqu'au 3ème dataset (Pessimiste)
                        fill: 2, 
                        backgroundColor: 'rgba(96, 165, 250, 0.08)',
                        pointRadius: 0,
                        tension: 0.2
                    },
                    {
                        label: 'Médian (Cœur de probabilité)',
                        data: data.median,
                        borderColor: '#60a5fa',
                        borderWidth: 3,
                        fill: false,
                        pointRadius: 0,
                        tension: 0.2
                    },
                    {
                        label: 'Pessimiste (Bottom 10%)',
                        data: data.pessimistic,
                        borderColor: '#ef4444',
                        borderDash: [5, 5],
                        borderWidth: 2,
                        fill: false,
                        pointRadius: 0,
                        tension: 0.2
                    },
                    {
                        label: 'Capital versé',
                        data: data.contributed,
                        borderColor: '#9ca3af',
                        borderDash: [2, 4],
                        borderWidth: 1.5,
                        fill: false,
                        pointRadius: 0,
                        tension: 0
                    }
                    
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: true, labels: { color: '#ffffff', usePointStyle: true, boxWidth: 8 } },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return context.dataset.label + ' : ' + context.parsed.y.toLocaleString('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 });
                            }
                        }
                    },
                    datalabels: { display: false }
                },
                scales: {
                    x: { 
                        grid: { color: 'rgba(255,255,255,0.05)' }, 
                        ticks: { color: '#8b8d96', maxTicksLimit: 12 } 
                    },
                    y: { 
                        position: 'right', 
                        beginAtZero: false, // Évite d'écraser le graphique vers le bas
                        grid: { color: 'rgba(255,255,255,0.05)' }, 
                        ticks: { 
                            color: '#8b8d96',
                            // Formatage pour raccourcir les grands nombres
                            callback: function(value) {
                                if (value >= 1000000) return (value / 1000000).toFixed(2) + ' M €';
                                if (value >= 1000) return (value / 1000).toFixed(0) + ' k €';
                                return value + ' €';
                            }
                        } 
                    }
                }
            }
        });

    } catch (e) {
        console.error(e);
        document.getElementById('mcStats').innerHTML = `<span style="color:var(--red);">Échec du calcul.</span>`;
    }
    
    if (btn) { btn.innerText = "Simuler"; btn.disabled = false; }
}
