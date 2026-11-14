// Session, compte, droits RGPD (export / suppression) et administration.
let sessionInfo = { authenticated: false, username: '', is_admin: false };

async function initSession() {
    const res = await fetch(`${API_URL}/auth/status`);
    sessionInfo = await res.json();
    if (!sessionInfo.authenticated) {
        window.location.href = '/login.html';
        return false;
    }
    document.getElementById('sidebarUser').innerText = '👤 ' + sessionInfo.username;
    return true;
}

async function logout() {
    try { await postJSON('/auth/logout', {}); } catch (e) { /* on quitte quand même */ }
    window.location.href = '/login.html';
}

function showAccountMsg(id, text, ok) {
    const el = document.getElementById(id);
    el.style.display = 'block';
    el.style.color = ok ? 'var(--green)' : 'var(--red)';
    el.innerText = text;
}

async function loadAccount() {
    document.getElementById('accountName').innerText = sessionInfo.username;
    document.getElementById('adminCard').style.display = sessionInfo.is_admin ? 'block' : 'none';
    if (sessionInfo.is_admin) loadUsers();
    const note = document.getElementById('commonCodeNote');
    if (note) note.innerText = sessionInfo.common_code_active
        ? "Un code d'inscription commun est actif (variable SIGNUP_CODE du serveur) : toute personne qui le connaît peut créer un compte. Changez-le dans la configuration pour le renouveler."
        : "Aucun code commun défini : seules les invitations à usage unique permettent de créer un compte.";
}

async function changePassword() {
    try {
        await postJSON('/auth/change-password', {
            old_password: document.getElementById('oldPassword').value,
            new_password: document.getElementById('newPassword').value
        });
        document.getElementById('oldPassword').value = '';
        document.getElementById('newPassword').value = '';
        showAccountMsg('accountMsg', 'Mot de passe modifié. Vos autres sessions ont été fermées.', true);
    } catch (e) {
        showAccountMsg('accountMsg', e.message, false);
    }
}

function downloadMyData() {
    window.location.href = `${API_URL}/account/export`;
}

async function deleteMyAccount() {
    if (!confirm("Supprimer définitivement votre compte et toutes vos données ? Cette action est irréversible.")) return;
    const password = prompt("Confirmez avec votre mot de passe :");
    if (!password) return;
    try {
        const res = await fetch(`${API_URL}/account`, {
            method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Erreur');
        window.location.href = '/login.html';
    } catch (e) {
        showAccountMsg('accountMsg', e.message, false);
    }
}

async function createInvite() {
    try {
        const data = await postJSON('/admin/invite', {});
        const box = document.getElementById('inviteBox');
        box.style.display = 'block';
        box.style.color = 'var(--text-main)';
        box.innerHTML = `Code à transmettre (affiché une seule fois) :<br><strong style="font-size: 1.3rem; letter-spacing: 1px;">${esc(data.code)}</strong>`;
    } catch (e) {
        showAccountMsg('inviteBox', e.message, false);
    }
}

async function loadUsers() {
    const res = await fetch(`${API_URL}/admin/users`);
    if (!res.ok) return;
    const users = await res.json();
    document.getElementById('usersList').innerHTML = users.map(u => `
        <div class="user-line">
            <span>${esc(u.username)}${u.is_admin ? ' <small class="text-muted">(admin)</small>' : ''}</span>
            <span class="text-muted" style="font-size: 0.75rem;">dernière connexion : ${u.last_login ? new Date(u.last_login).toLocaleDateString('fr-FR') : '—'}</span>
            ${u.id === sessionInfo.user_id || u.username === sessionInfo.username ? '' : `<button class="btn-mini" onclick="deleteUser(${u.id})">Supprimer</button>`}
        </div>`).join('');
}

async function deleteUser(id) {
    if (!confirm("Supprimer ce compte et toutes ses données ?")) return;
    const res = await fetch(`${API_URL}/admin/users/${id}`, { method: 'DELETE' });
    if (res.ok) loadUsers();
}
