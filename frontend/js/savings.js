// Comptes sur livret.

async function loadSavings() {
    try {
        const response = await fetch(`${API_URL}/savings`);
        savings = await response.json();
        renderSavings();
        updateDashboardSavings();
    } catch(e) { console.error(e); }
}

function updateDashboardSavings() {
    const el = document.getElementById('dashboardSavingsVal');
    if (!el) return;
    const total = (savings || []).reduce((sum, s) => sum + (s.balance || 0), 0);
    el.innerText = total.toLocaleString('fr-FR', { style: 'currency', currency: 'EUR' });
}

function renderSavings() {
    const grid = document.getElementById('savingsGrid');
    if (grid) {
        grid.innerHTML = '';
        if (savings.length === 0) {
            grid.innerHTML = '<p class="text-muted">Aucun compte enregistré pour le moment.</p>';
        } else {
            savings.forEach((s, idx) => {
                const color = CHART_COLORS[idx % CHART_COLORS.length];
                const card = document.createElement('div');
                card.className = 'asset-card';
                card.style.cursor = 'default';
                
                card.innerHTML = `
                    <div class="asset-info" style="width: 100%;">
                        <div class="asset-name" style="font-size: 1.1rem; margin-bottom: 5px;">
                            <span class="color-dot" style="background-color: ${color};"></span>${esc(s.name)}
                        </div>
                        <div class="asset-ticker" style="color: #60a5fa; font-size: 0.85rem; font-weight: bold; margin-bottom: 10px;">🏦 ${esc(s.bank)} • Taux : ${s.rate}%</div>
                        <div class="asset-value" style="font-size: 1.4rem; margin-bottom: 8px;">${s.balance.toLocaleString('fr-FR', {style: 'currency', currency: 'EUR'})}</div>
                        
                        <div style="font-size: 0.8rem; color: var(--green); margin-bottom: 15px; background: rgba(34,197,94,0.08); padding: 8px; border-radius: 6px;">
                            📈 Intérêts acquis : <strong>+${s.earned_interest.toLocaleString('fr-FR', {minimumFractionDigits: 2})} €</strong> <br>
                            <span style="color: var(--text-muted); font-size: 0.75rem;">Projection : +${s.annual_interest.toLocaleString('fr-FR', {minimumFractionDigits: 2})} €/an (~${s.monthly_interest.toLocaleString('fr-FR', {minimumFractionDigits: 2})} €/mois)</span>
                        </div>

                        <div style="display: flex; gap: 8px;">
                            <button onclick="openEditSavingModal(${s.id})" style="background: transparent; color: #60a5fa; border: 1px solid rgba(96, 165, 250, 0.4); padding: 8px; border-radius: 6px; cursor: pointer; font-size: 0.75rem; font-weight: bold; width: 100%; transition: 0.2s;">
                                Modifier
                            </button>
                            <button onclick="deleteSaving(${s.id})" style="background: transparent; color: var(--red); border: 1px solid rgba(239, 68, 68, 0.3); padding: 8px; border-radius: 6px; cursor: pointer; font-size: 0.75rem; font-weight: bold; width: 100%; transition: 0.2s;">
                                Retirer
                            </button>
                        </div>
                    </div>
                `;
                grid.appendChild(card);
            });
        }
    }
    drawSavingsChart();
    updateDashboardSavings();
}

function drawSavingsChart() {
    const canvas = document.getElementById('savingsChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (savingsChartObj) savingsChartObj.destroy();

    const totalValEl = document.getElementById('savingsTotalVal');
    const headerEl = document.getElementById('savingsTotalHeader');
    const earnedValEl = document.getElementById('savingsEarnedVal');
    const interestValEl = document.getElementById('savingsInterestVal');
    const miniListEl = document.getElementById('savingsMiniList');

    if (!savings || savings.length === 0) {
        if (totalValEl) totalValEl.innerText = "0,00 €";
        if (headerEl) headerEl.innerText = "";
        if (earnedValEl) earnedValEl.innerText = "+0,00 €";
        if (interestValEl) interestValEl.innerText = "Projection : +0,00 € / an";
        if (miniListEl) miniListEl.innerHTML = '<span class="text-muted">Aucun compte enregistré</span>';
        return;
    }

    const totalBalance = savings.reduce((sum, s) => sum + s.balance, 0);
    const totalEarned = savings.reduce((sum, s) => sum + (s.earned_interest || 0), 0);
    const totalAnnualInterest = savings.reduce((sum, s) => sum + (s.annual_interest || 0), 0);

    if (totalValEl) totalValEl.innerText = totalBalance.toLocaleString('fr-FR', { style: 'currency', currency: 'EUR' });
    if (headerEl) headerEl.innerText = `Total : ${totalBalance.toLocaleString('fr-FR', { style: 'currency', currency: 'EUR' })}`;
    if (earnedValEl) earnedValEl.innerText = `+${totalEarned.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
    if (interestValEl) interestValEl.innerText = `Projection : +${totalAnnualInterest.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} € / an`;

    if (miniListEl) {
        miniListEl.innerHTML = savings.map((s, i) => {
            const color = CHART_COLORS[i % CHART_COLORS.length];
            const pct = totalBalance > 0 ? ((s.balance / totalBalance) * 100).toFixed(1) : 0;
            return `
                <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        <span class="color-dot" style="background-color: ${color}; width: 8px; height: 8px; margin: 0; flex-shrink: 0;"></span>
                        <span title="${esc(s.bank)} - ${esc(s.name)}" style="color: var(--text-main); font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${esc(s.name)}</span>
                    </div>
                    <span style="color: var(--text-muted); font-size: 0.75rem; white-space: nowrap; font-weight: 500;">${s.balance.toLocaleString('fr-FR')} € <span style="color: #60a5fa;">(${pct}%)</span></span>
                </div>
            `;
        }).join('');
    }

    const labels = savings.map(s => `${s.bank} - ${s.name}`);
    const data = savings.map(s => s.balance);
    const colors = savings.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]);

    savingsChartObj = new Chart(ctx, {
        type: 'doughnut',
        data: { labels: labels, datasets: [{ data: data, backgroundColor: colors, borderWidth: 3, borderColor: '#141414' }] },
        options: {
            responsive: true, maintainAspectRatio: false, cutout: '65%',
            plugins: { 
                legend: { display: false },
                datalabels: {
                    color: '#ffffff', font: { weight: 'bold', size: 10.5 }, textAlign: 'center',
                    formatter: (value, ctx) => {
                        let sum = ctx.chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
                        let pct = (value * 100 / sum).toFixed(0);
                        if (pct < 5) return ''; 
                        const parts = ctx.chart.data.labels[ctx.dataIndex].split('-');
                        const shortName = parts.length > 1 ? parts[1].trim() : parts[0].trim();
                        return `${shortName}\n${pct}%`;
                    }
                }
            }
        }
    });
}

async function addSaving() {
    const bank = document.getElementById('saveBankInput').value;
    const name = document.getElementById('saveNameInput').value;
    const balance = document.getElementById('saveBalanceInput').value;
    const rate = document.getElementById('saveRateInput').value || 1.7;
    const earned = document.getElementById('saveEarnedInput').value || 0;
    
    if(!bank || !name || !balance) return alert("Veuillez remplir la banque, le nom et le solde.");
    
    try {
        await fetch(`${API_URL}/savings`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bank, name, balance: parseFloat(balance), rate: parseFloat(rate), earned_interest: parseFloat(earned) })
        });
        
        document.getElementById('saveBankInput').value = '';
        document.getElementById('saveNameInput').value = '';
        document.getElementById('saveBalanceInput').value = '';
        document.getElementById('saveRateInput').value = '';
        document.getElementById('saveEarnedInput').value = '';
        await loadSavings();
    } catch(e) { console.error(e); }
}

function openEditSavingModal(id) {
    const saving = savings.find(s => s.id === id);
    if (!saving) return;
    
    document.getElementById('editSavingId').value = saving.id;
    document.getElementById('editSavingBank').value = saving.bank;
    document.getElementById('editSavingName').value = saving.name;
    document.getElementById('editSavingBalance').value = saving.balance;
    document.getElementById('editSavingRate').value = saving.rate;
    document.getElementById('editSavingEarned').value = saving.earned_interest || 0;
    
    document.getElementById('editSavingModal').style.display = 'flex';
}

function closeEditSavingModal() {
    document.getElementById('editSavingModal').style.display = 'none';
}

async function saveEditedSaving() {
    const id = document.getElementById('editSavingId').value;
    const bank = document.getElementById('editSavingBank').value;
    const name = document.getElementById('editSavingName').value;
    const balance = document.getElementById('editSavingBalance').value;
    const rate = document.getElementById('editSavingRate').value;
    const earned = document.getElementById('editSavingEarned').value;

    if(!bank || !name || !balance) return alert("Remplissez les champs obligatoires (Banque, Nom, Solde).");

    try {
        await fetch(`${API_URL}/savings/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                id: parseInt(id), 
                bank, name, 
                balance: parseFloat(balance), 
                rate: parseFloat(rate),
                earned_interest: parseFloat(earned || 0)
            })
        });
        closeEditSavingModal();
        await loadSavings();
    } catch(e) {
        console.error(e);
    }
}

async function deleteSaving(id) {
    if(!confirm("Êtes-vous sûr de vouloir supprimer ce compte ?")) return;
    try {
        await fetch(`${API_URL}/savings/delete`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id })
        });
        await loadSavings();
    } catch(e) { console.error(e); }
}
