// Page de connexion : connexion, création de compte (code d'invitation), mot de passe oublié (clé de récupération).
let mode = 'login';
let firstUser = false;
let codeRequired = false;
const card = document.getElementById('authCard');

function setMode(m) { mode = m; render(); }

function render() {
    const tabs = `
        <div class="auth-tabs">
            <button class="${mode === 'login' ? 'active' : ''}" onclick="setMode('login')">Connexion</button>
            <button class="${mode === 'signup' ? 'active' : ''}" onclick="setMode('signup')">Créer un compte</button>
            <button class="${mode === 'recover' ? 'active' : ''}" onclick="setMode('recover')">Oublié ?</button>
        </div>`;
    let form = '';
    if (mode === 'login') {
        form = `
            <input class="field" id="f_user" placeholder="Identifiant" autocomplete="username">
            <input class="field" id="f_pass" type="password" placeholder="Mot de passe" autocomplete="current-password">
            <div class="auth-error" id="f_err"></div>
            <button class="btn-primary" onclick="doLogin()">Se connecter</button>`;
    } else if (mode === 'signup') {
        form = `
            ${firstUser ? `<p class="text-muted" style="font-size:.85rem;margin-bottom:12px;">Premier démarrage : ce compte sera l'<strong>administrateur</strong> et reprendra les données déjà présentes sur cette installation, en les chiffrant.</p>` : ''}
            ${codeRequired ? `<input class="field" id="f_invite" placeholder="Code d'inscription ou d'invitation" autocomplete="off">` : ''}
            <input class="field" id="f_user" placeholder="Identifiant (3 à 32 caractères)" autocomplete="username">
            <input class="field" id="f_pass" type="password" placeholder="Mot de passe (10 caractères minimum)" autocomplete="new-password">
            <p class="text-muted" style="font-size:.8rem;margin-bottom:8px;">Vos données sont chiffrées avec une clé dérivée de ce mot de passe : personne, pas même l'administrateur, ne peut les lire. Une <strong>clé de récupération</strong> vous sera donnée une seule fois.</p>
            <div class="auth-error" id="f_err"></div>
            <button class="btn-primary" onclick="doSignup()">Créer mon compte</button>`;
    } else {
        form = `
            <p class="text-muted" style="font-size:.85rem;margin-bottom:12px;">Saisissez la clé de récupération reçue à l'inscription. Sans elle et sans mot de passe, les données sont irrécupérables (c'est le prix du chiffrement).</p>
            <input class="field" id="f_user" placeholder="Identifiant" autocomplete="username">
            <input class="field" id="f_key" placeholder="Clé de récupération" autocomplete="off">
            <input class="field" id="f_pass" type="password" placeholder="Nouveau mot de passe (10 caractères minimum)" autocomplete="new-password">
            <div class="auth-error" id="f_err"></div>
            <button class="btn-primary" onclick="doRecover()">Réinitialiser le mot de passe</button>`;
    }
    card.innerHTML = `<h1>Investment Dashboard</h1><div class="text-muted" style="font-size:.9rem;">Vos données sont privées et chiffrées.</div>${tabs}${form}`;
    const first = card.querySelector('input');
    if (first) first.focus();
    card.querySelectorAll('input').forEach(i => i.addEventListener('keydown', e => {
        if (e.key === 'Enter') ({ login: doLogin, signup: doSignup, recover: doRecover })[mode]();
    }));
}

function val(id) { const el = document.getElementById(id); return el ? el.value : ''; }
function showErr(msg) { document.getElementById('f_err').innerText = msg; }

async function doLogin() {
    try {
        await postJSON('/auth/login', { username: val('f_user'), password: val('f_pass') });
        window.location.href = '/';
    } catch (e) { showErr(e.message); }
}

async function doSignup() {
    try {
        const data = await postJSON('/auth/signup', { username: val('f_user'), password: val('f_pass'), invite: val('f_invite') });
        showRecovery(data.recovery_key, '/', data.imported_legacy ? "Vos données existantes ont été reprises et chiffrées." : '');
    } catch (e) { showErr(e.message); }
}

async function doRecover() {
    try {
        const data = await postJSON('/auth/recover', { username: val('f_user'), recovery_key: val('f_key'), new_password: val('f_pass') });
        showRecovery(data.recovery_key, 'login', "Mot de passe réinitialisé. Votre ancienne clé de récupération n'est plus valable : conservez la nouvelle.");
    } catch (e) { showErr(e.message); }
}

function showRecovery(key, next, note) {
    card.innerHTML = `
        <h1>Conservez cette clé</h1>
        ${note ? `<p class="text-muted" style="font-size:.85rem;">${esc(note)}</p>` : ''}
        <p style="margin-top:12px;font-size:.9rem;">Voici votre <strong>clé de récupération</strong>. Elle ne sera <strong>plus jamais affichée</strong>. Si vous oubliez votre mot de passe, elle est le seul moyen de retrouver vos données.</p>
        <div class="recovery-key" id="recKey">${esc(key)}</div>
        <div style="display:flex;gap:8px;margin-bottom:14px;">
            <button class="btn-mini" style="flex:1" onclick="copyKey()">Copier</button>
            <button class="btn-mini" style="flex:1" onclick="saveKey()">Télécharger (.txt)</button>
        </div>
        <label style="font-size:.85rem;display:flex;gap:8px;align-items:center;margin-bottom:14px;">
            <input type="checkbox" id="saved" onchange="document.getElementById('goBtn').disabled = !this.checked"> J'ai conservé cette clé en lieu sûr
        </label>
        <button class="btn-primary" id="goBtn" disabled onclick="${next === '/' ? "window.location.href='/'" : "setMode('login')"}">Continuer</button>`;
    window.recoveryKeyValue = key;
}

function copyKey() { navigator.clipboard.writeText(window.recoveryKeyValue).catch(() => {}); }
function saveKey() {
    const blob = new Blob([`Investment Dashboard – clé de récupération\n${window.recoveryKeyValue}\n`], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'invest-dash-cle-de-recuperation.txt';
    a.click();
}

(async function init() {
    try {
        const status = await (await fetch(`${API_URL}/auth/status`)).json();
        if (status.authenticated) { window.location.href = '/'; return; }
        firstUser = status.needs_setup;
        codeRequired = status.signup_code_required;
        mode = firstUser ? 'signup' : 'login';
    } catch (e) { /* serveur injoignable : on affiche quand même le formulaire */ }
    render();
})();
