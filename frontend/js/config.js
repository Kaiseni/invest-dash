// Configuration et état global partagé entre les fichiers (chargés dans l'ordre par index.html).
Chart.register(ChartDataLabels);

// L'interface est servie par Flask (même origine) : l'API est toujours sur /api.
const API_URL = "/api";
const CHART_COLORS = ['#60a5fa', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#e879f9', '#2dd4bf', '#f472b6', '#a3e635'];

let portfolio = [];
let portfolioSummary = {};
let unallocatedCash = 0;
let monthlyBudget = 0;
let currentTotalWealth = 0;
let mainChartObj = null;
let allocChartObj = null;
let modalChartObj = null;
let mcChartObj = null;
let currentModalTicker = '';
let savings = [];
let savingsChartObj = null;
let currentMainChartPeriod = '1mo';
let currentModalChartPeriod = '1mo';
let heatmapChartObj = null;
let pendingOrders = [];
let targets = [];          // répartition cible choisie par l'utilisateur [{label, tickers, buy, pct}]
let sellCommissionRate = 0.005; // commission de revente (reçue du serveur)
let quotes = {};           // prix des ETF cibles que l'on ne détient pas encore
let sparklineCharts = [];   // mini-graphiques des cartes (détruits à chaque rafraîchissement)
let mainChartRequestId = 0; // évite qu'une vieille réponse écrase une plus récente
