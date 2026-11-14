// Échappe le texte venant de l'extérieur (noms Yahoo, titres d'articles, saisies) avant de l'insérer dans du HTML.
function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

// N'autorise que les liens http(s) (évite les "javascript:" venant d'un flux RSS).
function safeUrl(url) {
    return /^https?:\/\//i.test(url || '') ? esc(url) : '#';
}

// Appel POST JSON : lève une erreur si le serveur répond avec un statut d'erreur.
async function postJSON(path, payload) {
    const response = await fetch(`${API_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `Erreur ${response.status}`);
    return data;
}

function showToast(message, isError = false) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast ${isError ? 'toast-error' : 'toast-success'}`;
    toast.innerText = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('fade-out');
        toast.addEventListener('animationend', () => toast.remove());
    }, 4500);
}