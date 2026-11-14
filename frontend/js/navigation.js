// Navigation entre les vues.
const VIEWS = { dashboard: 'flex', holdings: 'block', savings: 'block', simulators: 'block', news: 'block', alt: 'flex', account: 'flex' };

function switchView(view) {
    for (const [name, display] of Object.entries(VIEWS)) {
        document.getElementById('view-' + name).style.display = name === view ? display : 'none';
        document.getElementById('nav-' + name).className = name === view ? 'active' : '';
    }
    if (view === 'holdings') loadHoldings();
    if (view === 'savings') loadSavings();
    if (view === 'simulators') renderActionPlan();
    if (view === 'alt') loadAlt();
    if (view === 'account') loadAccount();
}
