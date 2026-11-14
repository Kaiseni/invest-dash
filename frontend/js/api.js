// Toutes les requêtes vers /api : cookie de session + en-tête anti-CSRF, retour à la page de connexion si la session a expiré.
(function () {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async function (url, opts) {
        const isApi = typeof url === 'string' && url.startsWith('/api');
        if (isApi) {
            opts = Object.assign({ credentials: 'same-origin' }, opts || {});
            opts.headers = Object.assign({ 'X-Requested-With': 'invest-dash' }, opts.headers || {});
        }
        const response = await nativeFetch(url, opts);
        if (isApi && response.status === 401 && !url.startsWith('/api/auth/')) {
            window.location.href = '/login.html';
        }
        return response;
    };
})();
