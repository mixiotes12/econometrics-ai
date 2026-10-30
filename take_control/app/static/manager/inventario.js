/* Inventarios y Catálogo - Fase 2 */
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => "$" + Number(n || 0).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const num = (n, d = 2) => Number(n || 0).toLocaleString("es-MX", { maximumFractionDigits: d });
  const IVA = { iva16: 0.16, iva0: 0, exento: 0 };
  const PLACEHOLDER = "data:image/svg+xml;utf8," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect width="80" height="80" fill="#18181b"/><text x="40" y="48" font-size="28" text-anchor="middle" fill="#475569">📦</text></svg>');

  let token = sessionStorage.getItem("pos_token") || "";
  let me = JSON.parse(sessionStorage.getItem("pos_me") || "null");
  let rates = {};
  let products = [];
  let pendingImage = null;   // dataURL pendiente de subir (producto nuevo o foto cambiada)
  let removeImage = false;
  let charts = {};

  async function api(path, opts = {}) {
    const res = await fetch("/api/inv" + path, {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json", "X-POS-Token": token },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (res.status === 401) { sessionStorage.removeItem("pos_token"); showNoSession(); throw new Error("Sesión expirada"); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      let d = data.detail;
      if (Array.isArray(d)) d = d.map((e) => (e.loc || []).slice(1).join(".") + ": " + e.msg).join(" | ");
      throw new Error(d || "Error " + res.status);
    }
    return data;
  }
  const showNoSession = () => { $("app").classList.add("hidden"); $("noSession").classList.remove("hidden"); };
  const statusPill = (s) => ({
    ok: '<span class="pill bg-emerald-900 text-emerald-300">En stock</span>',
    reorden: '<span class="pill bg-amber-900 text-amber-300">Reordenar</span>',
    agotado: '<span class="pill bg-red-900 text-red-300">Agotado</span>',
    sin_control: '<span class="pill bg-zinc-700 text-zinc-300">Sin control</span>',
  }[s]);
  const marginColor = (m) => (m < 15 ? "text-red-400" : m < 30 ? "text-amber-300" : "text-emerald-400");

  // ---------- Tabs
  function switchTab(name) {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("hidden", p.id !== "tab-" + name));
    const loaders = { catalogo: loadCatalog, alertas: loadAlerts, kardex: loadKardex, divisas: loadRates, analisis: loadAnalysis };
    loaders[name]().catch((e) => alert(e.message));
  }

  // ---------- Catálogo
  async function loadCatalog() {
    const p = new URLSearchParams();
    if ($("fQ").value) p.set("q", $("fQ").value);
    if ($("fCat").value) p.set("category", $("fCat").value);
    if ($("fStatus").value) p.set("status", $("fStatus").value);
    if ($("fImp").value) p.set("imported", $("fImp").value);
    if ($("fInactive").checked) p.set("include_inactive", "true");
    products = await api("/products?" + p.toString());
    $("catalogEmpty").classList.toggle("hidden", products.length > 0);
    $("catalogBody").innerHTML = products.map((x) => `<tr class="${x.active ? "" : "opacity-50"}">
      <td><img class="thumb" src="${esc(x.image || PLACEHOLDER)}" alt=""></td>
      <td><b>${esc(x.name)}</b><div class="text-[10px] text-zinc-500">${esc(x.sku || "")} ${x.barcode ? "· " + esc(x.barcode) : ""}</div></td>
      <td>${esc(x.category || "—")}</td>
      <td>${fmt(x.cost)}${x.is_imported ? `<div class="text-[10px] text-sky-400">${num(x.foreign_cost, 4)} ${x.currency} @ ${num(x.exchange_rate, 4)}</div>` : ""}</td>
      <td>${fmt(x.price)}</td>
      <td class="${marginColor(x.margin_pct)}">${num(x.margin_pct, 1)}%</td><td>${num(x.markup_pct, 1)}%</td>
      <td>${x.track_stock ? num(x.stock) : "—"} ${statusPill(x.stock_status)}</td>
      <td>${x.track_stock ? num(x.min_stock) : "—"}</td>
      <td>${x.is_imported ? '<i class="fa-solid fa-plane text-sky-400" title="Importado"></i> ' + esc(x.origin_country) : "Nacional"}</td>
      <td class="whitespace-nowrap"><button class="btn btn-sec !py-0.5 admin-only" data-edit="${x.id}">Editar</button></td></tr>`).join("");
    applyRole();
    const cats = await api("/categories");
    const sel = $("fCat"), cur = sel.value;
    sel.innerHTML = '<option value="">Todas</option>' + cats.map((c) => `<option ${c === cur ? "selected" : ""}>${esc(c)}</option>`).join("");
    $("catList").innerHTML = cats.map((c) => `<option value="${esc(c)}">`).join("");
    refreshAlertBadge();
  }
  async function refreshAlertBadge() {
    try {
      const a = await api("/alerts");
      const b = $("alertBadge");
      b.classList.toggle("hidden", a.count === 0);
      b.textContent = `${a.count} por reordenar`;
      b.className = "pill cursor-pointer " + (a.out_of_stock ? "bg-red-800" : "bg-amber-800") + (a.count ? "" : " hidden");
    } catch {}
  }

  // ---------- Formulario de producto
  const val = (id) => $(id).value;
  const fnum = (id) => parseFloat($(id).value) || 0;
  async function loadRates() {
    const list = await api("/rates");
    rates = {}; list.forEach((r) => (rates[r.currency] = r));
    $("ratesBody").innerHTML = list.map((r) => `<tr><td><b>${r.currency}</b></td><td>${
      r.currency === "MXN" ? "1.0000" : `<input type="number" step="0.0001" min="0" class="inp !w-28 !py-0.5 admin-only" data-rate="${r.currency}" value="${r.rate_mxn}">`}</td>
      <td>${esc(r.source)}</td><td>${esc(r.updated_at)}</td>
      <td>${r.currency === "MXN" ? "" : `<button class="btn btn-sec !py-0.5 admin-only" data-saverate="${r.currency}">Guardar</button>`}</td></tr>`).join("");
    applyRole();
  }
  function updateImportUI() {
    const on = $("pImported").checked;
    $("importBox").classList.toggle("opacity-50", !on);
    $("importBox").querySelectorAll("input,select").forEach((el) => (el.disabled = !on));
    $("pCost").disabled = on;
    const cur = val("pCurrency");
    $("pRateHint").textContent = rates[cur] && cur !== "MXN" ? `(vigente ${num(rates[cur].rate_mxn, 4)})` : "";
    recalcLanded();
  }
  function recalcLanded() {
    if (!$("pImported").checked) return recalcMargin();
    const cur = val("pCurrency");
    const rate = fnum("pRate") || (rates[cur] ? rates[cur].rate_mxn : 1);
    const landed = fnum("pForeign") * rate * (1 + fnum("pDuties") / 100) + fnum("pFreight") + fnum("pOther");
    $("pLanded").textContent = fmt(landed);
    $("pCost").value = landed.toFixed(2);
    recalcMargin();
  }
  function recalcMargin() {
    const net = fnum("pPrice") / (1 + IVA[val("pIva")]);
    const cost = fnum("pCost");
    const profit = net - cost;
    const margin = net > 0 ? (profit / net) * 100 : 0;
    const markup = cost > 0 ? (profit / cost) * 100 : 0;
    $("pMarginView").innerHTML = `<div>Precio sin IVA: <b>${fmt(net)}</b></div><div>Utilidad/unidad: <b>${fmt(profit)}</b></div>
      <div>Margen: <b class="${marginColor(margin)}">${margin.toFixed(1)}%</b> · Markup: <b>${markup.toFixed(1)}%</b></div>`;
  }
  function applyMargin() {
    const m = fnum("pWantMargin");
    if (m <= 0 || m >= 100) return alert("Indica un margen entre 0 y 99%.");
    const net = fnum("pCost") / (1 - m / 100);
    $("pPrice").value = (net * (1 + IVA[val("pIva")])).toFixed(2);
    recalcMargin();
  }
  function setImagePreview(url) { $("pImg").src = url || PLACEHOLDER; }
  function openProductModal(p) {
    pendingImage = null; removeImage = false;
    $("pError").classList.add("hidden");
    const d = p || { name: "", sku: "", barcode: "", category: "", supplier: "", price: 0, cost: 0, iva_type: "iva16", stock: 0, track_stock: 1,
      min_stock: 0, max_stock: 0, reorder_qty: 0, is_imported: 0, currency: "USD", foreign_cost: 0, exchange_rate: "", duties_pct: 0,
      freight_cost: 0, other_cost: 0, origin_country: "", sat_product_key: "01010101", sat_unit_key: "H87", active: 1, image: null };
    $("pmTitle").textContent = p ? "Editar producto" : "Nuevo producto";
    $("pId").value = p ? p.id : "";
    $("pName").value = d.name; $("pSku").value = d.sku || ""; $("pBarcode").value = d.barcode || ""; $("pCategory").value = d.category || "";
    $("pSupplier").value = d.supplier || ""; $("pIva").value = d.iva_type; $("pTrack").checked = !!d.track_stock; $("pActive").checked = !!d.active;
    $("pPrice").value = d.price; $("pCost").value = d.cost; $("pWantMargin").value = "";
    $("pStock").value = d.stock; $("pStock").disabled = !!p; $("pStockNote").classList.toggle("hidden", !p);
    $("pMin").value = d.min_stock; $("pMax").value = d.max_stock; $("pReorderQty").value = d.reorder_qty;
    $("pImported").checked = !!d.is_imported; $("pCurrency").value = d.currency === "MXN" ? "USD" : d.currency;
    $("pForeign").value = d.foreign_cost; $("pRate").value = d.is_imported ? d.exchange_rate : ""; $("pDuties").value = d.duties_pct;
    $("pFreight").value = d.freight_cost; $("pOther").value = d.other_cost; $("pOrigin").value = d.origin_country || "";
    $("pSatP").value = d.sat_product_key; $("pSatU").value = d.sat_unit_key;
    setImagePreview(d.image);
    updateImportUI();
    $("productModal").classList.remove("hidden"); $("productModal").classList.add("flex");
  }
  const closeProductModal = () => { $("productModal").classList.add("hidden"); $("productModal").classList.remove("flex"); };

  function resizeImage(file, maxSide = 800) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        const k = Math.min(1, maxSide / Math.max(img.width, img.height));
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        resolve(c.toDataURL("image/jpeg", 0.82));
      };
      img.onerror = () => reject(new Error("No se pudo leer la imagen"));
      img.src = url;
    });
  }

  async function saveProduct(e) {
    e.preventDefault();
    const imported = $("pImported").checked;
    const body = {
      name: val("pName"), sku: val("pSku") || null, barcode: val("pBarcode") || null, category: val("pCategory"), supplier: val("pSupplier"),
      price: fnum("pPrice"), cost: fnum("pCost"), iva_type: val("pIva"), stock: fnum("pStock"), track_stock: $("pTrack").checked,
      min_stock: fnum("pMin"), max_stock: fnum("pMax"), reorder_qty: fnum("pReorderQty"),
      is_imported: imported, currency: imported ? val("pCurrency") : "MXN", foreign_cost: fnum("pForeign"),
      exchange_rate: imported && fnum("pRate") > 0 ? fnum("pRate") : null, duties_pct: fnum("pDuties"),
      freight_cost: fnum("pFreight"), other_cost: fnum("pOther"), origin_country: val("pOrigin"),
      sat_product_key: val("pSatP") || "01010101", sat_unit_key: val("pSatU") || "H87", active: $("pActive").checked,
    };
    try {
      const id = val("pId");
      const saved = await api(id ? "/products/" + id : "/products", { method: id ? "PUT" : "POST", body });
      if (pendingImage) await api(`/products/${saved.id}/image`, { method: "POST", body: { data_url: pendingImage } });
      else if (removeImage && id) await api(`/products/${saved.id}/image`, { method: "DELETE" });
      closeProductModal();
      await loadCatalog();
    } catch (er) { $("pError").textContent = er.message; $("pError").classList.remove("hidden"); }
  }

  // ---------- Alertas
  async function loadAlerts() {
    const a = await api("/alerts");
    $("alertCards").innerHTML = [
      ["Productos por reordenar", a.count, "text-amber-300"], ["Agotados", a.out_of_stock, "text-red-400"], ["Inversión estimada de reposición", fmt(a.estimated_cost), "text-sky-300"],
    ].map(([l, v, c]) => `<div class="card"><div class="text-[11px] text-zinc-400">${l}</div><div class="text-2xl font-bold ${c}">${v}</div></div>`).join("");
    $("alertsEmpty").classList.toggle("hidden", a.count > 0);
    $("alertsBody").innerHTML = a.items.map((x) => `<tr><td><img class="thumb" src="${esc(x.image || PLACEHOLDER)}" alt=""></td><td><b>${esc(x.name)}</b></td><td>${esc(x.supplier || "—")}</td>
      <td>${num(x.stock)}</td><td>${num(x.min_stock)}</td><td>${statusPill(x.stock_status)}</td><td><b>${num(x.reorder_suggest)}</b></td><td>${fmt(x.reorder_cost)}</td>
      <td><button class="btn btn-pri !py-0.5 admin-only" data-restock="${x.id}">Registrar entrada</button></td></tr>`).join("");
    applyRole();
    refreshAlertBadge();
  }

  // ---------- Kardex
  async function loadKardex() {
    const p = new URLSearchParams({ days: $("kDays").value || 30 });
    if ($("kType").value) p.set("type", $("kType").value);
    const list = await api("/movements?" + p);
    $("kardexBody").innerHTML = list.map((m) => `<tr><td>${esc(m.created_at)}</td><td>${esc(m.product_name)}</td>
      <td>${esc(m.type)}</td><td class="${m.delta < 0 ? "text-red-400" : "text-emerald-400"}">${m.delta > 0 ? "+" : ""}${num(m.delta)}</td>
      <td>${fmt(m.unit_cost)}</td><td>${num(m.stock_after)}</td><td>${esc(m.reason)} ${m.ref ? `<span class="text-zinc-500">${esc(m.ref)}</span>` : ""}</td><td>${esc(m.cashier_name || "")}</td></tr>`).join("");
  }
  async function openMoveModal(productId) {
    if (!products.length) products = await api("/products");
    $("mProduct").innerHTML = products.filter((p) => p.track_stock).map((p) => `<option value="${p.id}">${esc(p.name)} (stock ${num(p.stock)})</option>`).join("");
    if (productId) $("mProduct").value = productId;
    $("mQty").value = ""; $("mCost").value = ""; $("mReason").value = ""; $("mError").classList.add("hidden");
    updateMoveUI();
    $("moveModal").classList.remove("hidden"); $("moveModal").classList.add("flex");
  }
  function updateMoveUI() {
    const t = val("mType");
    $("mQtyLabel").textContent = t === "ajuste" ? "Existencia contada real" : "Cantidad";
    $("mCostBox").classList.toggle("hidden", t !== "entrada");
    $("mHint").textContent = { entrada: "Si indicas el costo de compra se recalcula el costo promedio ponderado (no aplica a importados).",
      merma: "Descuenta existencia. El motivo es obligatorio (caducidad, robo, daño...).", ajuste: "Fija la existencia al conteo físico; la diferencia queda registrada." }[t];
  }
  const closeMoveModal = () => { $("moveModal").classList.add("hidden"); $("moveModal").classList.remove("flex"); };
  async function saveMovement(e) {
    e.preventDefault();
    try {
      await api(`/products/${val("mProduct")}/movement`, { method: "POST", body: {
        type: val("mType"), qty: fnum("mQty"), unit_cost: val("mCost") === "" ? null : fnum("mCost"), reason: val("mReason") } });
      closeMoveModal(); products = [];
      const active = document.querySelector(".tab-btn.active").dataset.tab;
      switchTab(active);
    } catch (er) { $("mError").textContent = er.message; $("mError").classList.remove("hidden"); }
  }

  // ---------- Análisis
  async function loadAnalysis() {
    const a = await api("/analysis?days=" + $("aDays").value);
    const s = a.summary;
    const card = (l, v, c = "") => `<div class="card"><div class="text-[11px] text-zinc-400">${l}</div><div class="text-xl font-bold ${c}">${v}</div></div>`;
    $("aCards").innerHTML = card("Valor del inventario (costo)", fmt(s.inventory_value_cost), "text-sky-300") + card("Valor a precio de venta", fmt(s.inventory_value_sale)) +
      card("Utilidad potencial", fmt(s.potential_profit), "text-emerald-400") + card("Unidades en existencia", num(s.units_in_stock)) +
      card(`Ventas netas (${a.period_days} d)`, fmt(s.revenue_period)) + card("Costo de lo vendido", fmt(s.cogs_period)) +
      card("Rotación anualizada", s.turnover_annualized == null ? "—" : s.turnover_annualized + " veces", "text-amber-300") +
      card("Días de inventario", s.avg_days_inventory == null ? "—" : s.avg_days_inventory + " d") +
      card("Productos por reordenar", s.low_stock_count, s.low_stock_count ? "text-amber-300" : "") +
      card("Mermas (costo)", fmt(s.merma_value), s.merma_value ? "text-red-400" : "") + card("Mermas % del costo vendido", s.merma_pct_of_cogs + "%") + card("Productos activos", s.products);
    $("aBody").innerHTML = a.products.map((r) => `<tr><td><span class="pill ${{ A: "bg-emerald-800", B: "bg-sky-800", C: "bg-zinc-700" }[r.abc]}">${r.abc}</span></td><td>${esc(r.name)}</td>
      <td>${num(r.units_sold)}</td><td>${fmt(r.revenue)}</td><td class="${r.profit < 0 ? "text-red-400" : ""}">${fmt(r.profit)}</td><td>${num(r.stock)}</td><td>${fmt(r.stock_value_cost)}</td>
      <td>${r.days_cover == null ? "—" : r.days_cover}</td></tr>`).join("");
    $("slowBody").innerHTML = a.slow_movers.map((r) => `<tr><td>${esc(r.name)}</td><td>${num(r.stock)}</td><td>${fmt(r.stock_value_cost)}</td><td>${num(r.units_sold)}</td><td>${r.days_cover == null ? "Sin ventas" : r.days_cover}</td></tr>`).join("") ||
      '<tr><td colspan="5" class="text-zinc-500 text-center">Sin productos de baja rotación.</td></tr>';
    $("mermaList").innerHTML = a.merma_by_reason.map((m) => `<div class="flex justify-between"><span>${esc(m.reason || "Sin motivo")}</span><b>${fmt(m.value)}</b></div>`).join("") || '<p class="text-zinc-500 text-xs">Sin mermas registradas.</p>';
    drawChart("abcChart", "doughnut", ["A (≈80% ingresos)", "B", "C"], Object.values(a.abc_counts), ["#10b981", "#0ea5e9", "#64748b"]);
    drawChart("catChart", "bar", a.value_by_category.map((c) => c.category), a.value_by_category.map((c) => c.value), "#38bdf8");
  }
  function drawChart(id, type, labels, data, colors) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart($(id), { type, data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 0 }] },
      options: { plugins: { legend: { display: type === "doughnut", labels: { color: "#cbd5e1" } } },
        scales: type === "bar" ? { x: { ticks: { color: "#a1a1aa" } }, y: { ticks: { color: "#a1a1aa" } } } : {} } });
  }

  const can = (perm) => !!me && (me.is_admin || (me.permissions || []).includes(perm));
  const applyRole = () => document.querySelectorAll(".admin-only").forEach((el) => {
    if (!(can("products.manage") || can("inventory.move") || can("rates.manage"))) el.classList.add("hidden");
  });

  // ---------- Eventos
  function bind() {
    $("tabs").addEventListener("click", (e) => { const b = e.target.closest(".tab-btn"); if (b) switchTab(b.dataset.tab); });
    $("alertBadge").onclick = () => switchTab("alertas");
    ["fQ", "fCat", "fStatus", "fImp", "fInactive"].forEach((id) => $(id).addEventListener(id === "fQ" ? "input" : "change", () => loadCatalog().catch(() => {})));
    $("newProductBtn").onclick = () => openProductModal(null);
    $("catalogBody").addEventListener("click", (e) => { const b = e.target.closest("[data-edit]"); if (b) openProductModal(products.find((p) => p.id === +b.dataset.edit)); });
    $("pmClose").onclick = $("pCancel").onclick = closeProductModal;
    $("productForm").onsubmit = saveProduct;
    ["pPrice", "pCost", "pIva"].forEach((id) => $(id).addEventListener("input", recalcMargin));
    ["pForeign", "pRate", "pDuties", "pFreight", "pOther"].forEach((id) => $(id).addEventListener("input", recalcLanded));
    $("pCurrency").onchange = updateImportUI; $("pImported").onchange = updateImportUI;
    $("pApplyMargin").onclick = applyMargin;
    $("pPick").onclick = () => $("pFile").click();
    $("pFile").onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return;
      try { pendingImage = await resizeImage(f); removeImage = false; setImagePreview(pendingImage); } catch (er) { alert(er.message); }
      e.target.value = "";
    };
    $("pPhotoDel").onclick = () => { pendingImage = null; removeImage = true; setImagePreview(null); };

    $("alertsBody").addEventListener("click", (e) => { const b = e.target.closest("[data-restock]"); if (b) { $("mType").value = "entrada"; openMoveModal(b.dataset.restock); } });
    $("openMoveBtn").onclick = () => openMoveModal();
    $("mType").onchange = updateMoveUI; $("mCancel").onclick = closeMoveModal; $("moveForm").onsubmit = saveMovement;
    $("kRefresh").onclick = () => loadKardex().catch((e) => alert(e.message));
    $("kType").onchange = $("kRefresh").onclick;

    $("ratesBody").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-saverate]"); if (!b) return;
      const cur = b.dataset.saverate, v = parseFloat(document.querySelector(`[data-rate="${cur}"]`).value);
      try { await api("/rates/" + cur, { method: "PUT", body: { rate_mxn: v } }); await loadRates(); } catch (er) { alert(er.message); }
    });
    $("refreshRatesBtn").onclick = async () => { try { await api("/rates/refresh", { method: "POST" }); await loadRates(); $("applyResult").innerHTML = '<span class="text-emerald-400">Tipos de cambio actualizados.</span>'; } catch (er) { $("applyResult").innerHTML = `<span class="text-red-400">${esc(er.message)}</span>`; } };
    $("applyRatesBtn").onclick = async () => {
      try {
        const r = await api("/rates/apply", { method: "POST" });
        $("applyResult").innerHTML = `<span class="text-emerald-400">${r.updated} producto(s) importado(s) recalculado(s).</span>` +
          r.items.map((i) => `<div class="text-zinc-400">${esc(i.name)}: ${fmt(i.old_cost)} → ${fmt(i.new_cost)}</div>`).join("");
      } catch (er) { $("applyResult").innerHTML = `<span class="text-red-400">${esc(er.message)}</span>`; }
    };
    $("aRefresh").onclick = () => loadAnalysis().catch((e) => alert(e.message));
    $("aDays").onchange = $("aRefresh").onclick;
  }

  document.addEventListener("DOMContentLoaded", async () => {
    if (!token || !me) return showNoSession();
    $("whoami").textContent = `${me.name} · ${me.role_label || (me.is_admin ? "Administrador" : "Cajero")}`;
    bind();
    try { await loadRates(); await loadCatalog(); } catch {}
  });
})();
