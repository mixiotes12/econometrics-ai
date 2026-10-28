/* POS & Ventas - Fase 1 */
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => "$" + Number(n || 0).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const IVA_RATE = { iva16: 0.16, iva0: 0, exento: 0 };
  const IVA_LABEL = { iva16: "16%", iva0: "0%", exento: "Exento" };

  let token = sessionStorage.getItem("pos_token") || "";
  let me = JSON.parse(sessionStorage.getItem("pos_me") || "null");
  let cart = []; // {product, qty}
  let shift = null;
  let settings = {};
  let currentInvoiceSale = null;
  const can = (perm) => !!me && (me.is_admin || (me.permissions || []).includes(perm));

  // ---------- API
  async function api(path, opts = {}) {
    const res = await fetch("/api/pos" + path, {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json", "X-POS-Token": token },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (res.status === 401 && path !== "/login") { logoutLocal(); throw new Error("Sesión expirada"); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      let d = data.detail;
      if (Array.isArray(d)) d = d.map((e) => (e.loc || []).slice(1).join(".") + ": " + e.msg).join(" | ");
      throw new Error(d || "Error " + res.status);
    }
    return data;
  }
  const toast = (el, msg, ok = true) => { el.innerHTML = `<span class="${ok ? "text-emerald-400" : "text-red-400"}">${esc(msg)}</span>`; };

  // ---------- Login / sesión
  async function loadLogin() {
    const list = await fetch("/api/pos/cashiers/public").then((r) => r.json());
    $("loginCashier").innerHTML = list.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  }
  async function doLogin() {
    try {
      const r = await api("/login", { method: "POST", body: { cashier_id: +$("loginCashier").value, pin: $("loginPin").value } });
      token = r.token; me = r.cashier;
      sessionStorage.setItem("pos_token", token); sessionStorage.setItem("pos_me", JSON.stringify(me));
      $("loginPin").value = ""; $("loginError").classList.add("hidden");
      await startApp();
    } catch (e) { $("loginError").textContent = e.message; $("loginError").classList.remove("hidden"); }
  }
  function logoutLocal() {
    token = ""; me = null; cart = [];
    sessionStorage.removeItem("pos_token"); sessionStorage.removeItem("pos_me");
    $("loginOverlay").classList.remove("hidden");
    loadLogin();
  }
  async function startApp() {
    $("loginOverlay").classList.add("hidden");
    $("whoami").textContent = `${me.name} · ${me.role_label || (me.is_admin ? "Administrador" : "Cajero")}`;
    document.querySelectorAll("[data-perm]").forEach((b) => b.classList.toggle("hidden", !can(b.dataset.perm)));
    document.querySelectorAll(".admin-only").forEach((b) => b.classList.toggle("hidden", !can("settings.manage")));
    if (me.must_change_pin) await forcePinChange();
    settings = await api("/settings");
    await refreshShift();
    renderCart();
    switchTab("venta");
    $("scanInput").focus();
  }

  async function forcePinChange() {
    const cur = prompt("Por seguridad debes cambiar tu PIN inicial.\nPIN actual:");
    const nuevo = cur && prompt("Nuevo PIN (4 a 8 dígitos, no uses 1234):");
    if (!cur || !nuevo) return;
    try {
      const r = await fetch("/api/hr/me/pin", { method: "POST", headers: { "Content-Type": "application/json", "X-POS-Token": token },
        body: JSON.stringify({ current_pin: cur, new_pin: nuevo }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "PIN inválido (4 a 8 dígitos)");
      me.must_change_pin = false; sessionStorage.setItem("pos_me", JSON.stringify(me));
      alert("PIN actualizado.");
    } catch (e) { alert(e.message + "\nPodrás intentarlo de nuevo al volver a iniciar sesión."); }
  }

  // ---------- Tabs
  function switchTab(name) {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("hidden", p.id !== "tab-" + name));
    const loaders = { caja: loadCaja, ventas: loadSales, productos: loadProducts, cajeros: loadCashiers, config: fillSettings };
    if (loaders[name]) loaders[name]().catch((e) => alert(e.message));
    if (name === "venta") $("scanInput").focus();
  }

  // ---------- Turno
  async function refreshShift() {
    const r = await api("/shifts/current");
    shift = r.shift;
    const b = $("shiftBadge");
    b.textContent = shift ? `Turno #${shift.id} abierto` : "Sin turno";
    b.className = "text-[11px] px-2 py-0.5 rounded-full " + (shift ? "bg-emerald-700" : "bg-slate-700");
    return r;
  }
  function reportHtml(r) {
    const row = (l, v, cls = "") => `<div class="flex justify-between ${cls}"><span class="text-slate-400">${l}</span><b>${v}</b></div>`;
    return row("Ventas", r.sales_count) + row("Subtotal", fmt(r.subtotal)) + row("IVA", fmt(r.iva)) + row("Total ventas", fmt(r.total), "text-amber-300") +
      "<hr class='border-slate-800 my-1'>" +
      row("Efectivo", fmt(r.by_method.efectivo)) + row("Tarjeta", fmt(r.by_method.tarjeta)) + row("Transferencia", fmt(r.by_method.transferencia)) +
      "<hr class='border-slate-800 my-1'>" +
      row("Fondo inicial", fmt(r.shift.opening_float)) + row("Entradas", fmt(r.cash_in)) + row("Retiros", fmt(r.cash_out)) +
      row("Canceladas", `${r.cancelled_count} (${fmt(r.cancelled_total)})`) +
      row("Efectivo esperado en caja", fmt(r.expected_cash), "text-emerald-400");
  }
  async function loadCaja() {
    const r = await refreshShift();
    $("shiftOpenBox").classList.toggle("hidden", !!shift);
    $("shiftActiveBox").classList.toggle("hidden", !shift);
    if (shift) $("shiftReport").innerHTML = reportHtml(r.report);
    const list = await api("/shifts");
    $("shiftsBody").innerHTML = list.map((s) => `<tr><td>${s.id}</td><td>${esc(s.cashier_name)}</td><td>${esc(s.opened_at)}</td><td>${esc(s.closed_at || "-")}</td>
      <td>${fmt(s.opening_float)}</td><td>${s.expected_cash == null ? "-" : fmt(s.expected_cash)}</td><td>${s.counted_cash == null ? "-" : fmt(s.counted_cash)}</td>
      <td class="${s.difference < 0 ? "text-red-400" : s.difference > 0 ? "text-amber-400" : ""}">${s.difference == null ? "-" : fmt(s.difference)}</td><td>${esc(s.status)}</td></tr>`).join("");
  }

  // ---------- Carrito
  function cartTotals() {
    let subtotal = 0, iva = 0, total = 0;
    const byType = {};
    cart.forEach(({ product: p, qty }) => {
      const gross = Math.round(p.price * qty * 100) / 100;
      const net = gross / (1 + IVA_RATE[p.iva_type]);
      subtotal += net; iva += gross - net; total += gross;
      byType[p.iva_type] = (byType[p.iva_type] || 0) + (gross - net);
    });
    return { subtotal, iva, total, byType };
  }
  function renderCart() {
    $("cartEmpty").classList.toggle("hidden", cart.length > 0);
    $("cartBody").innerHTML = cart.map((l, i) => `<tr>
      <td>${esc(l.product.name)}<div class="text-[10px] text-slate-500">${esc(l.product.barcode || l.product.sku || "")} · IVA ${IVA_LABEL[l.product.iva_type]}</div></td>
      <td>${fmt(l.product.price)}</td>
      <td><div class="flex items-center gap-1"><button class="btn btn-sec !px-2 !py-0.5" data-dec="${i}">-</button>
        <input type="number" min="0.01" step="any" value="${l.qty}" data-qty="${i}" class="inp !w-16 !py-0.5 text-center">
        <button class="btn btn-sec !px-2 !py-0.5" data-inc="${i}">+</button></div></td>
      <td class="text-right">${fmt(l.product.price * l.qty)}</td>
      <td><button class="text-red-400" data-del="${i}"><i class="fa-solid fa-trash"></i></button></td></tr>`).join("");
    const t = cartTotals();
    const ivaRows = Object.entries(t.byType).map(([k, v]) => `<div class="flex justify-between text-slate-400"><span>IVA ${IVA_LABEL[k]}</span><span>${fmt(v)}</span></div>`).join("");
    $("totals").innerHTML = `<div class="flex justify-between text-slate-400"><span>Subtotal</span><span>${fmt(t.subtotal)}</span></div>${ivaRows}
      <div class="flex justify-between text-xl font-bold text-amber-300 pt-1"><span>Total</span><span>${fmt(t.total)}</span></div>`;
    updateChange();
  }
  function updateChange() {
    const t = cartTotals().total;
    const rec = parseFloat($("received").value) || 0;
    $("changeAmt").textContent = fmt(Math.max(0, rec - t));
    $("cashBox").classList.toggle("hidden", $("payMethod").value !== "efectivo");
  }
  function addToCart(p, qty = 1) {
    const ex = cart.find((l) => l.product.id === p.id);
    if (ex) ex.qty += qty; else cart.push({ product: p, qty });
    renderCart();
  }
  async function scan() {
    const code = $("scanInput").value.trim();
    if (!code) return;
    const box = $("searchResults");
    box.innerHTML = "";
    try {
      addToCart(await api("/products/barcode/" + encodeURIComponent(code)));
      $("scanInput").value = ""; $("saleMsg").innerHTML = "";
    } catch {
      const found = await api("/products?q=" + encodeURIComponent(code));
      if (!found.length) return toast($("saleMsg"), "Producto no encontrado: " + code, false);
      if (found.length === 1) { addToCart(found[0]); $("scanInput").value = ""; return; }
      box.innerHTML = found.slice(0, 10).map((p) => `<button class="btn btn-sec text-left" data-pick='${p.id}'>${esc(p.name)} <b class="float-right">${fmt(p.price)}</b></button>`).join("");
      box._found = found;
    }
  }
  async function charge() {
    if (!cart.length) return toast($("saleMsg"), "El carrito está vacío.", false);
    if (!shift) return toast($("saleMsg"), "Abre un turno en la pestaña Caja / Turno.", false);
    const total = cartTotals().total;
    const method = $("payMethod").value;
    const received = method === "efectivo" ? parseFloat($("received").value) || 0 : total;
    try {
      const sale = await api("/sales", { method: "POST", body: { items: cart.map((l) => ({ product_id: l.product.id, qty: l.qty })), payment_method: method, received } });
      cart = []; $("received").value = ""; renderCart();
      toast($("saleMsg"), `Venta ${sale.folio} registrada. Cambio: ${fmt(sale.change_given)}`);
      openTicket(sale.id, true);
      refreshShift();
    } catch (e) { toast($("saleMsg"), e.message, false); }
  }
  const openTicket = (id, print) => window.open(`/api/pos/sales/${id}/ticket?token=${token}${print ? "&print=true" : ""}`, "_blank", "width=420,height=700");

  // ---------- Ventas y facturas
  async function loadSales() {
    const d = $("salesDate").value;
    const sales = await api("/sales" + (d ? "?date=" + d : ""));
    $("salesBody").innerHTML = sales.map((s) => `<tr><td>${esc(s.folio)}</td><td>${esc(s.created_at)}</td><td>${esc(s.cashier_name)}</td><td>${esc(s.payment_method)}</td>
      <td>${fmt(s.total)}</td><td class="${s.status === "cancelada" ? "text-red-400" : ""}">${esc(s.status)}</td>
      <td class="space-x-1 whitespace-nowrap"><button class="btn btn-sec !py-0.5" data-ticket="${s.id}"><i class="fa-solid fa-print"></i></button>
      ${s.status === "completada" && !s.invoiced ? `<button class="btn btn-pri !py-0.5" data-invoice="${s.id}" data-folio="${esc(s.folio)}">Facturar</button>` : ""}
      ${can("sales.cancel") && s.status === "completada" && !s.invoiced ? `<button class="btn btn-red !py-0.5" data-cancel="${s.id}">Cancelar</button>` : ""}</td></tr>`).join("");
    const inv = await api("/invoices");
    $("invoicesBody").innerHTML = inv.map((i) => `<tr><td>${esc(i.serie)}-${esc(i.folio)}</td><td>${esc(i.sale_folio)}</td><td>${esc(i.rfc)}</td><td>${esc(i.razon_social)}</td>
      <td>${fmt(i.total)}</td><td>${esc(i.status.replace("_", " "))}</td>
      <td><a class="btn btn-sec !py-0.5 inline-block" href="/api/pos/invoices/${i.id}/xml?token=${token}">XML</a></td></tr>`).join("");
  }
  function openInvoiceModal(id, folio) {
    currentInvoiceSale = id; $("invSaleFolio").textContent = folio; $("invError").classList.add("hidden");
    $("invoiceModal").classList.remove("hidden"); $("invoiceModal").classList.add("flex"); $("iRfc").focus();
  }
  const closeInvoiceModal = () => { $("invoiceModal").classList.add("hidden"); $("invoiceModal").classList.remove("flex"); };

  // ---------- Productos
  async function loadProducts() {
    const list = await api("/products?include_inactive=true&q=" + encodeURIComponent($("pSearch").value));
    $("productsBody").innerHTML = list.map((p) => `<tr class="${p.active ? "" : "opacity-50"}"><td>${esc(p.name)}</td><td>${esc(p.sku || "")}</td><td>${esc(p.barcode || "")}</td>
      <td>${fmt(p.price)}</td><td>${fmt(p.cost)}</td><td>${IVA_LABEL[p.iva_type]}</td><td>${p.track_stock ? p.stock : "—"}</td>
      <td><button class="btn btn-sec !py-0.5" data-editp='${esc(JSON.stringify(p))}'>Editar</button></td></tr>`).join("");
  }
  function resetProductForm() {
    $("productForm").reset(); $("pId").value = ""; $("pTrack").checked = true; $("pActive").checked = true;
    $("pSatP").value = "01010101"; $("pSatU").value = "H87";
  }
  function fillProductForm(p) {
    $("pId").value = p.id; $("pName").value = p.name; $("pSku").value = p.sku || ""; $("pBarcode").value = p.barcode || "";
    $("pPrice").value = p.price; $("pCost").value = p.cost; $("pIva").value = p.iva_type; $("pStock").value = p.stock;
    $("pSatP").value = p.sat_product_key; $("pSatU").value = p.sat_unit_key; $("pTrack").checked = !!p.track_stock; $("pActive").checked = !!p.active;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // ---------- Cajeros
  async function loadCashiers() {
    const list = await api("/cashiers");
    $("cashiersBody").innerHTML = list.map((c) => `<tr><td>${esc(c.name)}</td><td>${c.is_admin ? "Administrador" : "Cajero"}</td><td>${c.active ? "Activo" : "Inactivo"}</td><td>${esc(c.created_at)}</td>
      <td><button class="btn btn-sec !py-0.5" data-editc='${esc(JSON.stringify(c))}'>Editar</button></td></tr>`).join("");
  }

  // ---------- Config
  const SETTING_KEYS = ["business_name", "legal_name", "rfc", "tax_regime", "address", "zip_code", "phone", "ticket_width", "invoice_series", "ticket_footer"];
  async function fillSettings() {
    settings = await api("/settings");
    SETTING_KEYS.forEach((k) => ($("s_" + k).value = settings[k] ?? ""));
  }

  // ---------- Eventos
  function bind() {
    $("loginBtn").onclick = doLogin;
    $("loginPin").addEventListener("keydown", (e) => e.key === "Enter" && doLogin());
    $("logoutBtn").onclick = async () => { try { await api("/logout", { method: "POST" }); } catch {} logoutLocal(); };
    $("tabs").addEventListener("click", (e) => { const b = e.target.closest(".tab-btn"); if (b && b.dataset.tab) switchTab(b.dataset.tab); });

    $("scanInput").addEventListener("keydown", (e) => e.key === "Enter" && scan());
    $("scanBtn").onclick = scan;
    $("searchResults").addEventListener("click", (e) => {
      const b = e.target.closest("[data-pick]"); if (!b) return;
      const p = $("searchResults")._found.find((x) => x.id === +b.dataset.pick);
      addToCart(p); $("searchResults").innerHTML = ""; $("scanInput").value = ""; $("scanInput").focus();
    });
    $("cartBody").addEventListener("click", (e) => {
      const t = e.target.closest("button"); if (!t) return;
      if (t.dataset.inc) cart[+t.dataset.inc].qty += 1;
      else if (t.dataset.dec) { const l = cart[+t.dataset.dec]; l.qty = Math.max(1, l.qty - 1); }
      else if (t.dataset.del) cart.splice(+t.dataset.del, 1);
      else return;
      renderCart();
    });
    $("cartBody").addEventListener("change", (e) => {
      if (e.target.dataset.qty === undefined) return;
      const v = parseFloat(e.target.value);
      if (v > 0) cart[+e.target.dataset.qty].qty = v;
      renderCart();
    });
    $("payMethod").onchange = updateChange;
    $("received").oninput = updateChange;
    $("chargeBtn").onclick = charge;
    $("clearCartBtn").onclick = () => { cart = []; renderCart(); };

    $("openShiftBtn").onclick = async () => {
      try { await api("/shifts/open", { method: "POST", body: { opening_float: parseFloat($("openFloat").value) || 0 } }); await loadCaja(); }
      catch (e) { alert(e.message); }
    };
    $("refreshReportBtn").onclick = loadCaja;
    $("mvBtn").onclick = async () => {
      try {
        await api("/shifts/movement", { method: "POST", body: { type: $("mvType").value, amount: parseFloat($("mvAmount").value), reason: $("mvReason").value } });
        $("mvAmount").value = ""; $("mvReason").value = ""; await loadCaja();
      } catch (e) { alert(e.message); }
    };
    $("closeShiftBtn").onclick = async () => {
      if (!confirm("¿Cerrar turno (Corte Z)? Ya no podrás vender en este turno.")) return;
      try {
        const r = await api("/shifts/close", { method: "POST", body: { counted_cash: parseFloat($("countedCash").value) || 0, notes: $("closeNotes").value } });
        alert(`Turno cerrado.\nEsperado: ${fmt(r.expected_cash)}\nContado: ${fmt(r.shift.counted_cash)}\nDiferencia: ${fmt(r.shift.difference)}`);
        $("countedCash").value = ""; $("closeNotes").value = ""; await loadCaja();
      } catch (e) { alert(e.message); }
    };

    $("salesDate").onchange = () => loadSales().catch((e) => alert(e.message));
    $("salesBody").addEventListener("click", async (e) => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.ticket) openTicket(b.dataset.ticket, true);
      else if (b.dataset.invoice) openInvoiceModal(b.dataset.invoice, b.dataset.folio);
      else if (b.dataset.cancel && confirm("¿Cancelar esta venta? El inventario será devuelto.")) {
        try { await api(`/sales/${b.dataset.cancel}/cancel`, { method: "POST" }); await loadSales(); } catch (er) { alert(er.message); }
      }
    });
    $("invCancel").onclick = closeInvoiceModal;
    $("invoiceForm").onsubmit = async (e) => {
      e.preventDefault();
      try {
        await api(`/sales/${currentInvoiceSale}/invoice`, { method: "POST", body: {
          rfc: $("iRfc").value, razon_social: $("iName").value, regimen_fiscal: $("iReg").value,
          codigo_postal: $("iZip").value, uso_cfdi: $("iUso").value || "G03", email: $("iMail").value || null } });
        closeInvoiceModal(); $("invoiceForm").reset(); $("iUso").value = "G03"; await loadSales();
      } catch (er) { $("invError").textContent = er.message; $("invError").classList.remove("hidden"); }
    };

    $("productForm").onsubmit = async (e) => {
      e.preventDefault();
      const body = { name: $("pName").value, sku: $("pSku").value || null, barcode: $("pBarcode").value || null,
        price: parseFloat($("pPrice").value) || 0, cost: parseFloat($("pCost").value) || 0, iva_type: $("pIva").value,
        stock: parseFloat($("pStock").value) || 0, track_stock: $("pTrack").checked, active: $("pActive").checked,
        sat_product_key: $("pSatP").value || "01010101", sat_unit_key: $("pSatU").value || "H87" };
      try {
        const id = $("pId").value;
        await api(id ? "/products/" + id : "/products", { method: id ? "PUT" : "POST", body });
        resetProductForm(); await loadProducts();
      } catch (er) { alert(er.message); }
    };
    $("pReset").onclick = resetProductForm;
    $("pSearch").oninput = () => loadProducts().catch(() => {});
    $("productsBody").addEventListener("click", (e) => { const b = e.target.closest("[data-editp]"); if (b) fillProductForm(JSON.parse(b.dataset.editp)); });

    $("cashierForm").onsubmit = async (e) => {
      e.preventDefault();
      const body = { name: $("cName").value, pin: $("cPin").value || null, is_admin: $("cAdmin").checked, active: $("cActive").checked };
      try {
        const id = $("cId").value;
        await api(id ? "/cashiers/" + id : "/cashiers", { method: id ? "PUT" : "POST", body });
        $("cashierForm").reset(); $("cId").value = ""; $("cActive").checked = true; await loadCashiers();
      } catch (er) { alert(er.message); }
    };
    $("cReset").onclick = () => { $("cashierForm").reset(); $("cId").value = ""; $("cActive").checked = true; };
    $("cashiersBody").addEventListener("click", (e) => {
      const b = e.target.closest("[data-editc]"); if (!b) return;
      const c = JSON.parse(b.dataset.editc);
      $("cId").value = c.id; $("cName").value = c.name; $("cPin").value = ""; $("cAdmin").checked = !!c.is_admin; $("cActive").checked = !!c.active;
    });

    $("settingsForm").onsubmit = async (e) => {
      e.preventDefault();
      const body = {}; SETTING_KEYS.forEach((k) => (body[k] = $("s_" + k).value));
      body.rfc = body.rfc.toUpperCase();
      try { settings = await api("/settings", { method: "PUT", body }); alert("Configuración guardada."); } catch (er) { alert(er.message); }
    };
  }

  // ---------- Init
  document.addEventListener("DOMContentLoaded", async () => {
    bind();
    if (token && me) { try { await startApp(); return; } catch { logoutLocal(); return; } }
    loadLogin();
  });
})();
