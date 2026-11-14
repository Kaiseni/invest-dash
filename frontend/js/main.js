// Point d'entrée : chargement initial, rafraîchissement automatique, fermeture des fenêtres modales.
let refreshInProgress = false;

async function refreshAll() {
    if (refreshInProgress) return; // évite d'empiler les requêtes si le serveur est lent
    refreshInProgress = true;
    try {
        await Promise.all([fetchPortfolioData(), loadSavings()]);
        renderDashboard();
        fetchSoldHistory();
    } finally {
        refreshInProgress = false;
    }
}

window.onload = async () => {
    try {
        if (!(await initSession())) return; // non connecté : redirection vers la page de connexion
        await refreshAll();
        fetchNews();
        setInterval(() => refreshAll().catch(e => console.error("Erreur rafraîchissement:", e)), 300000);
    } catch (error) {
        console.error("Erreur API:", error);
    }
};

// Fermeture des fenêtres modales au clic sur le fond
window.onclick = function (event) {
    if (event.target === document.getElementById('assetModal')) closeModal();
    if (event.target === document.getElementById('editSavingModal')) closeEditSavingModal();
    if (event.target === document.getElementById('altSellModal')) closeAltSell();
};
