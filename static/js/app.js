/* ══════════════════════════════════════════════════════════════════════════
   Ventas x Dia x Mes — Dashboard (Odoo 18 Enterprise)
   ══════════════════════════════════════════════════════════════════════════ */

const API = "";
let currentPage = "dashboard";
let charts = {};

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmt(n) {
    return new Intl.NumberFormat("es-PA", {
        style: "currency", currency: "USD", minimumFractionDigits: 2,
    }).format(n || 0);
}

function getCompanyId() {
    return document.getElementById("companySelect").value;
}

function getMonthYear() {
    const val = document.getElementById("monthSelect").value;
    const [y, m] = val.split("-");
    return { year: parseInt(y), month: parseInt(m) };
}

async function api(endpoint) {
    const { year, month } = getMonthYear();
    const companyId = getCompanyId();
    const sep = endpoint.includes("?") ? "&" : "?";
    let url = `${API}${endpoint}${sep}year=${year}&month=${month}`;
    if (companyId && companyId !== "all") url += `&company_id=${companyId}`;
    const res = await fetch(url);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    return data;
}

function showError(msg) {
    const el = document.getElementById("globalError");
    el.innerHTML = `<div class="error-msg">${msg}</div>`;
    setTimeout(() => el.innerHTML = "", 8000);
}

function setConnected(ok) {
    document.getElementById("statusDot").className = "status-dot" + (ok ? " connected" : "");
    document.getElementById("statusText").textContent = ok ? "Conectado a Odoo" : "Sin conexion";
}

// ── Month selector ──────────────────────────────────────────────────────────

(function initMonthSelect() {
    const sel = document.getElementById("monthSelect");
    const now = new Date();
    const meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
    for (let i = 0; i < 12; i++) {
        const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
        const opt = document.createElement("option");
        opt.value = `${d.getFullYear()}-${d.getMonth() + 1}`;
        opt.textContent = `${meses[d.getMonth()]} ${d.getFullYear()}`;
        sel.appendChild(opt);
    }
    sel.addEventListener("change", refreshData);
})();

// ── Navigation ──────────────────────────────────────────────────────────────

const titles = {
    dashboard: "Dashboard",
    dia: "Ventas del Dia",
    mes: "Ventas del Mes",
    empresas: "Ventas por Empresa",
    detalle: "Detalle de Ordenes",
    vendedor: "Mi Detalle",
};

document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", () => {
        const page = item.dataset.page;
        if (!page) return;
        document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
        item.classList.add("active");
        document.querySelectorAll(".page-section").forEach(s => s.classList.remove("active"));
        const section = document.getElementById("page-" + page);
        if (section) { section.classList.add("active"); section.classList.add("fade-in"); }
        document.getElementById("pageTitle").textContent = titles[page] || page;
        currentPage = page;
        loadPageData(page);
    });
});

// ── Chart config ────────────────────────────────────────────────────────────

Chart.defaults.color = "#6b7280";
Chart.defaults.borderColor = "#e2e5eb";
Chart.defaults.font.family = "Inter, sans-serif";

const COLORS = ["#6366f1","#10b981","#f59e0b","#ef4444","#3b82f6","#8b5cf6","#ec4899","#14b8a6","#f97316","#06b6d4"];

// ── Rank position class ─────────────────────────────────────────────────────

function rankClass(i) {
    if (i === 0) return "gold";
    if (i === 1) return "silver";
    if (i === 2) return "bronze";
    return "normal";
}

// ── Render ranking ──────────────────────────────────────────────────────────

function renderRanking(containerId, data) {
    const el = document.getElementById(containerId);
    if (!data.length) {
        el.innerHTML = '<div style="padding:16px;color:var(--text-muted);font-size:13px">Sin ventas</div>';
        return;
    }
    const max = Math.max(...data.map(d => d.monto));
    el.innerHTML = data.map((d, i) => `
        <div class="rank-item">
            <div class="rank-pos ${rankClass(i)}">${i + 1}</div>
            <div class="rank-info">
                <div class="rank-name">${d.vendedor}</div>
                <div class="rank-bar-wrap">
                    <div class="rank-bar" style="width:${max ? (d.monto / max * 100) : 0}%; background:${COLORS[i % COLORS.length]}"></div>
                </div>
            </div>
            <div style="text-align:right">
                <div class="rank-amount">${fmt(d.monto)}</div>
                <div class="rank-orders">${d.ordenes} orden${d.ordenes !== 1 ? 'es' : ''}</div>
            </div>
        </div>
    `).join("");
}

// ── Render table with bars ──────────────────────────────────────────────────

function renderVendedorTable(tbId, data) {
    const tb = document.getElementById(tbId);
    if (!data.length) {
        tb.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">Sin ventas</td></tr>';
        return;
    }
    const max = Math.max(...data.map(d => d.monto));
    tb.innerHTML = data.map((d, i) => `
        <tr>
            <td style="font-weight:700;color:var(--primary)">${i + 1}</td>
            <td style="font-weight:600">${d.vendedor}</td>
            <td style="text-align:right">${d.ordenes}</td>
            <td style="text-align:right;font-weight:700">${fmt(d.monto)}</td>
            <td>
                <div class="inline-bar">
                    <div class="inline-bar-fill" style="width:${max ? (d.monto / max * 100) : 0}%"></div>
                </div>
            </td>
        </tr>
    `).join("");
}

// ── Data loaders ────────────────────────────────────────────────────────────

async function loadResumen() {
    try {
        const d = await api("/api/ventas/resumen");
        document.getElementById("kpiDia").textContent = fmt(d.venta_dia);
        document.getElementById("kpiMes").textContent = fmt(d.venta_mes);
        document.getElementById("kpiMeta").textContent = fmt(d.meta);
        document.getElementById("kpiMesOrdenes").textContent = `${d.ordenes_mes} ordenes`;

        const falta = Math.max(0, d.meta - d.venta_mes);
        const faltaEl = document.getElementById("kpiFalta");
        faltaEl.textContent = fmt(falta);
        faltaEl.className = "kpi-value " + (falta > 0 ? "negative" : "positive");

        const pct = d.porcentaje_meta;
        document.getElementById("kpiMetaPct").textContent = `${pct}% alcanzado`;
        document.getElementById("kpiMetaPct").style.color = pct >= 100 ? "var(--success)" : pct >= 70 ? "var(--warning)" : "var(--danger)";

        setConnected(true);
        return d;
    } catch (e) {
        setConnected(false);
        showError("Error cargando resumen: " + e.message);
        return null;
    }
}

async function loadGauge() {
    try {
        const d = await api("/api/ventas/resumen");
        const pct = Math.min(d.porcentaje_meta, 150);

        if (charts.gauge) charts.gauge.destroy();

        const gaugeColor = pct >= 100 ? "#059669" : pct >= 70 ? "#d97706" : "#dc2626";
        const remaining = Math.max(0, 100 - pct);

        charts.gauge = new Chart(document.getElementById("gaugeChart"), {
            type: "doughnut",
            data: {
                datasets: [{
                    data: [Math.min(pct, 100), remaining],
                    backgroundColor: [gaugeColor, "#e5e7eb"],
                    borderWidth: 0,
                    circumference: 180,
                    rotation: 270,
                }]
            },
            options: {
                responsive: true,
                cutout: "75%",
                plugins: { legend: { display: false }, tooltip: { enabled: false } },
            },
        });

        document.getElementById("gaugeLabel").textContent = `${d.porcentaje_meta}%`;
        document.getElementById("gaugeLabel").style.color = gaugeColor;
    } catch (e) {
        console.error("Gauge error", e);
    }
}

async function loadChartDiario() {
    try {
        const d = await api("/api/ventas/diario");
        if (charts.diario) charts.diario.destroy();

        // Acumular ventas
        let acum = 0;
        const acumulado = d.montos.map(m => { acum += m; return acum; });

        charts.diario = new Chart(document.getElementById("chartDiario"), {
            type: "bar",
            data: {
                labels: d.dias.map(dia => dia.replace(/\s\d{4}$/, "")),
                datasets: [
                    {
                        label: "Venta del Dia",
                        data: d.montos,
                        backgroundColor: "rgba(99, 102, 241, 0.6)",
                        borderRadius: 4,
                        order: 2,
                    },
                    {
                        label: "Acumulado",
                        data: acumulado,
                        type: "line",
                        borderColor: "#059669",
                        backgroundColor: "rgba(5, 150, 105, 0.1)",
                        fill: true,
                        tension: 0.3,
                        pointRadius: 3,
                        order: 1,
                    },
                ],
            },
            options: {
                responsive: true,
                plugins: { legend: { position: "top" } },
                scales: {
                    y: { ticks: { callback: v => fmt(v) }, grid: { color: "#e2e5eb" } },
                    x: { grid: { display: false } },
                },
            },
        });
    } catch (e) {
        console.error("Chart diario error", e);
    }
}

async function loadRankingDia() {
    try {
        const data = await api("/api/ventas/dia");
        renderRanking("rankingDia", data);
    } catch (e) { console.error(e); }
}

async function loadRankingMes() {
    try {
        const data = await api("/api/ventas/mes");
        renderRanking("rankingMes", data);
    } catch (e) { console.error(e); }
}

async function loadTablaDia() {
    try {
        const data = await api("/api/ventas/dia");
        renderVendedorTable("tbDia", data);
    } catch (e) { showError("Error: " + e.message); }
}

async function loadTablaMes() {
    try {
        const data = await api("/api/ventas/mes");
        renderVendedorTable("tbMes", data);
    } catch (e) { showError("Error: " + e.message); }
}

async function loadEmpresas() {
    try {
        const data = await api("/api/ventas/por-empresa");
        const el = document.getElementById("empresasGrid");
        el.className = "empresa-grid";

        el.innerHTML = data.map(e => {
            const pct = e.meta ? Math.min(e.porcentaje, 100) : 0;
            const color = e.porcentaje >= 100 ? "var(--success)" : e.porcentaje >= 70 ? "var(--warning)" : "var(--danger)";
            return `
                <div class="empresa-card">
                    <div class="empresa-name">${e.empresa}</div>
                    <div class="empresa-amount" style="color:${color}">${fmt(e.monto)}</div>
                    <div class="empresa-meta">
                        ${e.meta ? `Meta: ${fmt(e.meta)} | ${e.ordenes} ordenes` : `${e.ordenes} ordenes | Sin meta definida`}
                    </div>
                    ${e.meta ? `
                        <div class="empresa-progress">
                            <div class="empresa-progress-fill" style="width:${pct}%;background:${color}"></div>
                        </div>
                        <div class="empresa-pct" style="color:${color}">${e.porcentaje}%</div>
                    ` : ""}
                </div>
            `;
        }).join("") || '<div style="color:var(--text-muted)">Sin datos</div>';
    } catch (e) {
        showError("Error: " + e.message);
    }
}

async function loadDetalle() {
    try {
        const data = await api("/api/ventas/detalle");
        document.getElementById("tbDetalle").innerHTML = data.map(o => `
            <tr>
                <td style="font-weight:600">${o.numero}</td>
                <td>${o.cliente}</td>
                <td>${o.vendedor}</td>
                <td style="font-size:12px;color:var(--text-muted)">${o.empresa}</td>
                <td>${o.fecha}</td>
                <td style="text-align:right;font-weight:700">${fmt(o.monto)}</td>
            </tr>
        `).join("") || '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Sin ordenes</td></tr>';
    } catch (e) {
        showError("Error: " + e.message);
    }
}

// ── Vendedor Detail ─────────────────────────────────────────────────────────

async function loadVendedorResumen() {
    try {
        const vendedorId = document.getElementById("vendedorSelect").value;
        const { year, month } = getMonthYear();
        const companyId = getCompanyId();
        let url = `/api/vendedor/resumen?year=${year}&month=${month}&vendedor_id=${vendedorId}`;
        if (companyId !== "all") url += `&company_id=${companyId}`;

        const res = await fetch(url);
        const d = await res.json();
        if (d.error) return;

        // Hoy
        document.getElementById("vkHoyTotal").textContent = d.hoy_total;
        document.getElementById("vkHoyCerradas").textContent = d.hoy_cerradas;
        document.getElementById("vkHoyMonto").textContent = fmt(d.hoy_monto);

        // Mes
        document.getElementById("vkMesTotal").textContent = d.mes_total;
        document.getElementById("vkMesCerradas").textContent = d.mes_cerradas;
        document.getElementById("vkMesPendientes").textContent = d.mes_pendientes;
        document.getElementById("vkTasa").textContent = d.tasa_cierre + "%";
        document.getElementById("vkMesMonto").textContent = fmt(d.mes_monto_cerrado);
    } catch (e) { console.error(e); }
}

async function loadVendedorCotizaciones() {
    try {
        const vendedorId = document.getElementById("vendedorSelect").value;
        const estado = document.getElementById("estadoSelect").value;
        const periodo = document.getElementById("periodoSelect").value;
        const { year, month } = getMonthYear();
        const companyId = getCompanyId();
        let url = `/api/vendedor/cotizaciones?year=${year}&month=${month}&vendedor_id=${vendedorId}&estado=${estado}&periodo=${periodo}`;
        if (companyId !== "all") url += `&company_id=${companyId}`;

        document.getElementById("cotTitulo").textContent = periodo === "hoy" ? "Cotizaciones de Hoy" : "Cotizaciones del Mes";

        const res = await fetch(url);
        const data = await res.json();
        if (data.error) return;

        const el = document.getElementById("cotizacionesList");
        if (!data.length) {
            el.innerHTML = '<div style="padding:30px;text-align:center;color:var(--text-muted)">Sin cotizaciones para este periodo</div>';
            return;
        }

        el.innerHTML = data.map(c => `
            <div class="cot-item fade-in">
                <div class="cot-header" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">
                    <div>
                        <span class="cot-num">${c.numero}</span>
                        <span class="cot-cliente">${c.cliente}</span>
                        <div class="cot-fecha">${c.fecha} | ${c.vendedor} | ${c.empresa}</div>
                    </div>
                    <div class="cot-right">
                        <span class="cot-monto" style="color:${c.estado_key==='sale'?'var(--success)':c.estado_key==='cancel'?'var(--danger)':'var(--text)'}">${fmt(c.monto)}</span>
                        <span class="cot-badge ${c.estado_key}">${c.estado}</span>
                    </div>
                </div>
                <div class="cot-body" style="display:none">
                    <div class="cot-products">
                        <div class="cot-prod-row cot-prod-header">
                            <span>Producto</span>
                            <span style="text-align:center">Cant</span>
                            <span style="text-align:right">P. Unit</span>
                            <span style="text-align:right">Subtotal</span>
                        </div>
                        ${c.productos.map(p => `
                            <div class="cot-prod-row">
                                <span style="font-weight:500">${p.producto}</span>
                                <span style="text-align:center">${p.cantidad}</span>
                                <span style="text-align:right">${fmt(p.precio_unit)}</span>
                                <span style="text-align:right;font-weight:700">${fmt(p.subtotal)}</span>
                            </div>
                        `).join("") || '<div style="padding:8px 0;color:var(--text-muted);font-size:12px">Sin productos</div>'}
                    </div>
                </div>
            </div>
        `).join("");
    } catch (e) { console.error(e); }
}

async function loadVendedorPage() {
    await Promise.all([loadVendedorResumen(), loadVendedorCotizaciones()]);
}

// ── Page loader ─────────────────────────────────────────────────────────────

async function loadPageData(page) {
    switch (page) {
        case "dashboard":
            await Promise.all([loadResumen(), loadGauge(), loadChartDiario(), loadRankingDia(), loadRankingMes()]);
            break;
        case "dia":
            await loadTablaDia();
            break;
        case "mes":
            await loadTablaMes();
            break;
        case "empresas":
            await loadEmpresas();
            break;
        case "detalle":
            await loadDetalle();
            break;
        case "vendedor":
            await loadVendedorPage();
            break;
    }
}

// ── Refresh ─────────────────────────────────────────────────────────────────

async function refreshData() {
    const btn = document.getElementById("btnRefresh");
    const icon = document.getElementById("refreshIcon");
    btn.classList.add("loading");
    icon.classList.add("spin");
    try { await loadPageData(currentPage); }
    finally { btn.classList.remove("loading"); icon.classList.remove("spin"); }
}

// ── Auto-refresh every 5s ────────────────────────────────────────────────────

setInterval(() => loadPageData(currentPage), 5000);

// ── Init ────────────────────────────────────────────────────────────────────

async function logout() {
    await fetch(`${API}/api/logout`, { method: "POST" });
    window.location.href = "/login";
}

async function init() {
    // Load user info
    try {
        const me = await fetch(`${API}/api/me`);
        const user = await me.json();
        if (user.error) { window.location.href = "/login"; return; }
        document.getElementById("userName").textContent = user.name;
    } catch (e) {
        window.location.href = "/login";
        return;
    }

    // Load companies
    try {
        const res = await fetch(`${API}/api/empresas`);
        const companies = await res.json();
        const sel = document.getElementById("companySelect");
        companies.forEach(c => {
            const opt = document.createElement("option");
            opt.value = c.id;
            opt.textContent = c.nombre;
            sel.appendChild(opt);
        });
        sel.addEventListener("change", refreshData);
    } catch (e) {
        console.error("Error cargando empresas", e);
    }

    // Load vendedores
    try {
        const res = await fetch(`${API}/api/vendedores`);
        const vendedores = await res.json();
        const sel = document.getElementById("vendedorSelect");
        vendedores.forEach(v => {
            const opt = document.createElement("option");
            opt.value = v.id;
            opt.textContent = v.nombre;
            sel.appendChild(opt);
        });
        sel.addEventListener("change", () => { if (currentPage === "vendedor") loadVendedorPage(); });
        document.getElementById("estadoSelect").addEventListener("change", () => { if (currentPage === "vendedor") loadVendedorCotizaciones(); });
        document.getElementById("periodoSelect").addEventListener("change", () => { if (currentPage === "vendedor") loadVendedorCotizaciones(); });
    } catch (e) {
        console.error("Error cargando vendedores", e);
    }

    await loadPageData("dashboard");
}

init();
