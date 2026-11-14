// Actualités (Google News).

async function fetchNews() {
    if (portfolio.length === 0) return;
    try {
        const response = await fetch(`${API_URL}/news`);
        const newsData = await response.json();
        const grid = document.getElementById('newsGrid');
        grid.innerHTML = '';

        if(newsData.length === 0) {
            grid.innerHTML = '<p class="text-muted">Aucune actualité récente trouvée.</p>';
            return;
        }

        grid.innerHTML = newsData.map(news => {
            const dateObj = new Date(news.time_str);
            const dateStr = isNaN(dateObj) ? '' : dateObj.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
            const assetInfo = portfolio.find(a => a.ticker === news.ticker);
            const badgeColor = assetInfo ? assetInfo.color : '#c89a74';

            let sentClass = 'sentiment-neu'; let sentIcon = '•';
            if (news.sentiment === 'pos') { sentClass = 'sentiment-pos'; sentIcon = '↗'; }
            if (news.sentiment === 'neg') { sentClass = 'sentiment-neg'; sentIcon = '↘'; }

            return `
                <div class="news-item" style="background: var(--bg-card); padding: 15px; border-radius: 10px; border: 1px solid var(--border);">
                    <a href="${safeUrl(news.link)}" target="_blank" rel="noopener noreferrer" style="color: var(--text-main); text-decoration: none; font-weight: 600; line-height: 1.4;">${esc(news.title)}</a>
                    <div class="news-meta" style="display: flex; align-items: center; flex-wrap: wrap; gap: 8px;">
                        <span class="news-badge" style="color: ${badgeColor}; border: 1px solid ${badgeColor}33;">${esc(news.display_badge)}</span>
                        <span>${esc(news.publisher)} • ${dateStr}</span>
                        <span class="sentiment-badge ${sentClass}">${sentIcon}</span>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        console.error("Erreur news:", e);
    }
}
