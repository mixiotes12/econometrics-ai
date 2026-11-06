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
  let lastSaleId = null;
  let quickProductsCache = [];
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
    window.location.href = "index.html";
  }
  async function startApp() {
    $("loginOverlay").classList.add("hidden");
    const branchObj = JSON.parse(sessionStorage.getItem("pos_branch") || "null");
    if ($("posBranchBadge") && branchObj && branchObj.name) {
      $("posBranchBadge").textContent = `${branchObj.business_name ? branchObj.business_name + " · " : ""}${branchObj.name}`;
    }
    $("whoami").textContent = `${me.name} · ${me.role_label || (me.is_admin ? "Administrador" : "Cajero")}`;
    const isEmpOnly = sessionStorage.getItem("econometrics_emp_only") === "1";
    document.querySelectorAll("[data-perm]").forEach((b) => {
      if (isEmpOnly && (b.id === "posBackToOwner" || b.id === "posHubLink" || b.id === "posOwnerLink")) {
        b.classList.add("hidden");
      } else {
        b.classList.toggle("hidden", !can(b.dataset.perm));
      }
    });
    document.querySelectorAll(".admin-only").forEach((b) => b.classList.toggle("hidden", !can("settings.manage")));
    if (me.must_change_pin) await forcePinChange();
    settings = await api("/settings");
    await refreshShift();
    await loadQuickProducts();
    renderCart();
    await loadCachedProducts();
    switchTab("venta");
    $("scanInput").focus();
  }

  async function loadQuickProducts() {
    const bar = $("quickProductsBar");
    if (!bar) return;
    try {
      const list = await api("/products?q=");
      quickProductsCache = (list || []).filter((p) => p.active !== false).slice(0, 12);
      if (!quickProductsCache.length) {
        bar.innerHTML = `<span class="text-xs text-zinc-500 col-span-full">No hay productos activos en el catálogo.</span>`;
        return;
      }
      bar.innerHTML = quickProductsCache
        .map(
          (p) => `
        <button type="button" data-quick-pick="${p.id}" class="bg-zinc-950 hover:bg-zinc-800 border border-zinc-800 hover:border-[#c5a059]/60 rounded-xl p-2.5 text-left transition-all flex flex-col justify-between gap-1 group">
          <span class="text-xs font-semibold text-zinc-200 group-hover:text-white line-clamp-1">${esc(p.name)}</span>
          <div class="flex items-center justify-between w-full">
            <span class="text-xs font-mono font-bold text-[#d4b26f]">${fmt(p.price)}</span>
            <span class="text-[10px] text-zinc-500 group-hover:text-[#d4b26f]"><i class="fa-solid fa-plus-circle"></i></span>
          </div>
        </button>`
        )
        .join("");
    } catch {
      bar.innerHTML = "";
    }
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
    b.className = "text-[11px] px-2 py-0.5 rounded-full " + (shift ? "bg-emerald-700" : "bg-zinc-700");
    return r;
  }
  function reportHtml(r) {
    const row = (l, v, cls = "") => `<div class="flex justify-between ${cls}"><span class="text-zinc-400">${l}</span><b>${v}</b></div>`;
    return row("Ventas", r.sales_count) + row("Subtotal", fmt(r.subtotal)) + row("IVA", fmt(r.iva)) + row("Total ventas", fmt(r.total), "text-amber-300") +
      "<hr class='border-zinc-800 my-1'>" +
      row("Efectivo", fmt(r.by_method.efectivo)) + row("Tarjeta", fmt(r.by_method.tarjeta)) + row("Transferencia", fmt(r.by_method.transferencia)) +
      "<hr class='border-zinc-800 my-1'>" +
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
      <td>${esc(l.product.name)}<div class="text-[10px] text-zinc-500">${esc(l.product.barcode || l.product.sku || "")} · IVA ${IVA_LABEL[l.product.iva_type]}</div></td>
      <td>${fmt(l.product.price)}</td>
      <td><div class="flex items-center gap-1"><button class="btn btn-sec !px-2 !py-0.5" data-dec="${i}">-</button>
        <input type="number" min="0.01" step="any" value="${l.qty}" data-qty="${i}" class="inp !w-16 !py-0.5 text-center">
        <button class="btn btn-sec !px-2 !py-0.5" data-inc="${i}">+</button></div></td>
      <td class="text-right">${fmt(l.product.price * l.qty)}</td>
      <td><button class="text-red-400" data-del="${i}"><i class="fa-solid fa-trash"></i></button></td></tr>`).join("");
    const t = cartTotals();
    const ivaRows = Object.entries(t.byType).map(([k, v]) => `<div class="flex justify-between text-zinc-400"><span>IVA ${IVA_LABEL[k]}</span><span>${fmt(v)}</span></div>`).join("");
    $("totals").innerHTML = `<div class="flex justify-between text-zinc-400"><span>Subtotal</span><span>${fmt(t.subtotal)}</span></div>${ivaRows}
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
  // ---------- Autocompletado inteligente de productos
  let cachedProducts = [];
  let currentMatches = [];
  let currentSuggestionIndex = -1;

  async function loadCachedProducts() {
    try {
      cachedProducts = await api("/products?include_inactive=false");
    } catch (e) {
      console.warn("No se pudo pre-cargar catálogo de productos:", e);
    }
  }

  function normStr(str) {
    return (str || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .trim();
  }

  function highlightMatches(text, tokens) {
    if (!tokens || !tokens.length) return esc(text);
    const escaped = tokens.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).filter(Boolean);
    if (!escaped.length) return esc(text);
    try {
      const re = new RegExp(`(${escaped.join("|")})`, "gi");
      return esc(text).replace(re, '<span class="text-amber-400 font-extrabold underline decoration-amber-500/50">$1</span>');
    } catch {
      return esc(text);
    }
  }

  function filterProducts(query) {
    const q = normStr(query);
    if (q.length < 2) return [];

    const tokens = q.split(/\s+/).filter(Boolean);
    if (!tokens.length) return [];

    const list = cachedProducts.filter((p) => {
      const pName = normStr(p.name);
      const pWords = pName.split(/\s+/).filter(Boolean);
      const pSku = normStr(p.sku);
      const pBarcode = normStr(p.barcode);

      // Cada palabra escrita por el usuario debe coincidir con el inicio de alguna palabra
      // del producto (ej: 'caf' -> 'cafe', 'g' -> 'grande'), o coincidir con SKU/barcode
      return tokens.every((tok) => {
        if (pWords.some((w) => w.startsWith(tok))) return true;
        if (pSku.startsWith(tok) || pBarcode.startsWith(tok)) return true;
        if (tok.length >= 3 && pName.includes(tok)) return true;
        return false;
      });
    });

    list.sort((a, b) => {
      const aName = normStr(a.name);
      const bName = normStr(b.name);
      const aStarts = aName.startsWith(q);
      const bStarts = bName.startsWith(q);
      if (aStarts && !bStarts) return -1;
      if (!aStarts && bStarts) return 1;
      return aName.localeCompare(bName);
    });

    return list;
  }

  function renderSuggestions(matches, tokens) {
    const box = $("searchResults");
    if (!matches || !matches.length) {
      box.innerHTML = `
        <div class="p-3 text-center text-xs text-zinc-500">
          <i class="fa-solid fa-magnifying-glass mr-1.5 opacity-60"></i>
          Sin coincidencias en el inventario para tu búsqueda.
        </div>`;
      box.classList.remove("hidden");
      currentMatches = [];
      currentSuggestionIndex = -1;
      return;
    }

    currentMatches = matches.slice(0, 15);
    currentSuggestionIndex = -1;

    const listHtml = currentMatches.map((p, idx) => `
      <div class="suggestion-item p-3 cursor-pointer flex items-center justify-between transition-colors hover:bg-zinc-800/90 text-left select-none"
           data-pick="${p.id}" data-index="${idx}">
        <div class="flex items-center gap-3 min-w-0">
          <div class="w-8 h-8 rounded-lg bg-zinc-800 border border-zinc-700/70 flex items-center justify-center text-xs font-bold text-[#c5a059] flex-shrink-0">
            <i class="fa-solid fa-tag"></i>
          </div>
          <div class="min-w-0">
            <div class="font-bold text-sm text-zinc-100 truncate">${highlightMatches(p.name, tokens)}</div>
            <div class="text-[11px] text-zinc-400 flex items-center gap-2 mt-0.5 flex-wrap">
              <span class="font-mono bg-zinc-800 px-1.5 py-0.2 rounded text-[10px] text-zinc-300">SKU: ${esc(p.sku || 'S/N')}</span>
              ${p.track_stock ? `<span class="text-emerald-400 font-medium text-[10px]"><i class="fa-solid fa-cubes text-[9px] mr-0.5"></i> Stock: ${p.stock}</span>` : ''}
            </div>
          </div>
        </div>
        <div class="text-right flex-shrink-0 ml-3">
          <div class="font-mono font-bold text-amber-300 text-sm">${fmt(p.price)}</div>
          <span class="text-[9px] text-zinc-500 uppercase tracking-wider block">IVA incl.</span>
        </div>
      </div>
    `).join("");

    const footerHtml = `
      <div class="px-3 py-1.5 bg-zinc-950/90 text-[10px] text-zinc-400 flex items-center justify-between border-t border-zinc-800">
        <span class="flex items-center gap-1">
          <kbd class="px-1 py-0.2 bg-zinc-800 border border-zinc-700 rounded text-[9px] text-zinc-300 font-mono">Tab</kbd> o 
          <kbd class="px-1 py-0.2 bg-zinc-800 border border-zinc-700 rounded text-[9px] text-zinc-300 font-mono">↓↑</kbd> para elegir
        </span>
        <span class="flex items-center gap-1">
          <kbd class="px-1 py-0.2 bg-zinc-800 border border-zinc-700 rounded text-[9px] text-zinc-300 font-mono">Enter</kbd> para agregar al carrito
        </span>
      </div>
    `;

    box.innerHTML = listHtml + footerHtml;
    box.classList.remove("hidden");
  }

  function closeSuggestions() {
    const box = $("searchResults");
    box.classList.add("hidden");
    box.innerHTML = "";
    currentMatches = [];
    currentSuggestionIndex = -1;
  }

  function updateSuggestionHighlight() {
    const box = $("searchResults");
    const items = box.querySelectorAll(".suggestion-item");
    items.forEach((item, idx) => {
      if (idx === currentSuggestionIndex) {
        item.classList.add("bg-[#c5a059]/25", "border-l-4", "border-[#c5a059]");
        item.scrollIntoView({ block: "nearest" });
      } else {
        item.classList.remove("bg-[#c5a059]/25", "border-l-4", "border-[#c5a059]");
      }
    });

    if (currentSuggestionIndex >= 0 && currentSuggestionIndex < currentMatches.length) {
      $("scanInput").value = currentMatches[currentSuggestionIndex].name;
    }
  }

  function handleScanInput() {
    const raw = $("scanInput").value;
    if ($("scanClearBtn")) $("scanClearBtn").classList.toggle("hidden", !raw);

    const q = normStr(raw);
    if (q.length < 2) {
      closeSuggestions();
      return;
    }

    if (!cachedProducts.length) {
      loadCachedProducts().then(() => {
        const matches = filterProducts(raw);
        renderSuggestions(matches, normStr(raw).split(/\s+/).filter(Boolean));
      });
      return;
    }

    const matches = filterProducts(raw);
    renderSuggestions(matches, normStr(raw).split(/\s+/).filter(Boolean));
  }

  function handleScanKeyDown(e) {
    const box = $("searchResults");
    const isOpen = !box.classList.contains("hidden") && currentMatches.length > 0;

    if (e.key === "Tab") {
      if (isOpen) {
        e.preventDefault();
        if (e.shiftKey) {
          currentSuggestionIndex = (currentSuggestionIndex - 1 + currentMatches.length) % currentMatches.length;
        } else {
          currentSuggestionIndex = (currentSuggestionIndex + 1) % currentMatches.length;
        }
        updateSuggestionHighlight();
        return;
      }
    }

    if (e.key === "ArrowDown") {
      if (isOpen) {
        e.preventDefault();
        currentSuggestionIndex = (currentSuggestionIndex + 1) % currentMatches.length;
        updateSuggestionHighlight();
        return;
      }
    }

    if (e.key === "ArrowUp") {
      if (isOpen) {
        e.preventDefault();
        currentSuggestionIndex = (currentSuggestionIndex - 1 + currentMatches.length) % currentMatches.length;
        updateSuggestionHighlight();
        return;
      }
    }

    if (e.key === "Enter") {
      e.preventDefault();
      if (isOpen && currentSuggestionIndex >= 0 && currentSuggestionIndex < currentMatches.length) {
        addToCart(currentMatches[currentSuggestionIndex]);
        $("scanInput").value = "";
        closeSuggestions();
        if ($("scanClearBtn")) $("scanClearBtn").classList.add("hidden");
        $("scanInput").focus();
        return;
      }

      if (isOpen && currentMatches.length === 1) {
        addToCart(currentMatches[0]);
        $("scanInput").value = "";
        closeSuggestions();
        if ($("scanClearBtn")) $("scanClearBtn").classList.add("hidden");
        $("scanInput").focus();
        return;
      }

      scan();
      closeSuggestions();
      return;
    }

    if (e.key === "Escape") {
      closeSuggestions();
      return;
    }
  }

  async function scan() {
    const code = $("scanInput").value.trim();
    if (!code) return;
    try {
      addToCart(await api("/products/barcode/" + encodeURIComponent(code)));
      $("scanInput").value = ""; $("saleMsg").innerHTML = "";
      closeSuggestions();
    } catch {
      const found = await api("/products?q=" + encodeURIComponent(code));
      if (!found.length) return toast($("saleMsg"), "Producto no encontrado: " + code, false);
      if (found.length === 1) { addToCart(found[0]); $("scanInput").value = ""; closeSuggestions(); return; }
      renderSuggestions(found, normStr(code).split(/\s+/).filter(Boolean));
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
      lastSaleId = sale.id;
      cart = []; $("received").value = ""; renderCart();
      toast($("saleMsg"), `Venta ${sale.folio} registrada. Cambio: ${fmt(sale.change_given)}`);
      openTicket(sale.id, true);
      refreshShift();
    } catch (e) { toast($("saleMsg"), e.message, false); }
  }
  const openTicket = (id, print) => window.open(`/api/pos/sales/${id}/ticket?token=${token}${print ? "&print=true" : ""}`, "_blank", "width=420,height=700");

  async function reprintLastTicket() {
    try {
      if (lastSaleId) {
        openTicket(lastSaleId, true);
        return;
      }
      const sales = await api("/sales");
      const lastCompleted = (sales || []).find((s) => s.status === "completada") || (sales || [])[0];
      if (!lastCompleted) {
        return toast($("saleMsg"), "No hay ventas registradas para reimprimir.", false);
      }
      lastSaleId = lastCompleted.id;
      openTicket(lastCompleted.id, true);
    } catch (e) {
      toast($("saleMsg"), e.message, false);
    }
  }

  // ---------- Ventas y facturas
  let currentSaleMethod = "efectivo";

  async function loadSales() {
    const d = $("salesDate").value;
    const sales = await api("/sales" + (d ? "?date=" + d : ""));
    $("salesBody").innerHTML = sales.map((s) => `<tr>
      <td class="font-bold">${esc(s.folio)}</td>
      <td>${esc(s.created_at)}</td>
      <td>${esc(s.cashier_name)}</td>
      <td>${esc(s.payment_method)}</td>
      <td class="font-bold">${fmt(s.total)}</td>
      <td class="${s.status === "cancelada" ? "text-red-400" : ""}">${esc(s.status)}</td>
      <td class="space-x-1 whitespace-nowrap">
        <button class="btn btn-sec !py-0.5" data-ticket="${s.id}" title="Imprimir ticket"><i class="fa-solid fa-print"></i></button>
        ${s.status === "completada" && !s.invoiced ? `<button class="btn btn-pri !py-0.5" data-invoice="${s.id}" data-folio="${esc(s.folio)}" data-method="${esc(s.payment_method)}"><i class="fa-solid fa-bolt mr-1"></i>Facturar</button>` : ""}
        ${can("sales.cancel") && s.status === "completada" && !s.invoiced ? `<button class="btn btn-red !py-0.5" data-cancel="${s.id}">Cancelar</button>` : ""}
      </td></tr>`).join("");

    const inv = await api("/invoices");
    $("invoicesBody").innerHTML = inv.map((i) => {
      const shortUuid = i.uuid ? (i.uuid.substring(0, 8) + "...") : "—";
      return `<tr>
        <td>
          <div class="font-mono text-xs font-bold text-amber-400" title="${esc(i.uuid || '')}">${esc(shortUuid)}</div>
          <div class="text-[10px] text-zinc-500">${esc(i.fecha_timbrado || i.created_at)}</div>
        </td>
        <td class="font-bold">${esc(i.serie)}-${esc(i.folio)}</td>
        <td class="font-mono text-xs text-zinc-400">${esc(i.sale_folio)}</td>
        <td>
          <div class="font-bold text-zinc-200">${esc(i.rfc)}</div>
          <div class="text-[11px] text-zinc-400 truncate max-w-[180px]">${esc(i.razon_social)}</div>
        </td>
        <td class="font-bold">${fmt(i.total)}</td>
        <td>
          <span class="bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 font-bold px-2 py-0.5 rounded text-[10px] uppercase inline-flex items-center gap-1">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> Timbrada
          </span>
        </td>
        <td class="space-x-1 whitespace-nowrap text-right">
          <button class="btn btn-pri !py-1 !px-2.5 text-xs inline-flex items-center gap-1" data-viewinv="${i.id}" data-serie="${esc(i.serie)}" data-folio="${esc(i.folio)}">
            <i class="fa-solid fa-file-invoice"></i> Ver Factura
          </button>
          <a class="btn btn-sec !py-1 !px-2.5 text-xs inline-flex items-center gap-1" href="/api/pos/invoices/${i.id}/xml?token=${token}" download="CFDI_${esc(i.serie)}${esc(i.folio)}.xml">
            <i class="fa-solid fa-code"></i> XML
          </a>
        </td>
      </tr>`;
    }).join("");
  }

  function openInvoiceModal(id, folio, method) {
    currentInvoiceSale = id;
    currentSaleMethod = method || "efectivo";
    $("invSaleFolio").textContent = folio;
    $("invError").classList.add("hidden");

    // Pre-seleccionar forma de pago según método de venta
    const methodSatMap = { efectivo: "01", tarjeta: "04", transferencia: "03" };
    if ($("iFormaPago")) $("iFormaPago").value = methodSatMap[currentSaleMethod] || "01";
    if ($("iMetodoPago")) $("iMetodoPago").value = "PUE";

    $("iRfc").value = "";
    $("iName").value = "";
    $("iZip").value = (settings && settings.zip_code) ? settings.zip_code : "";
    $("iReg").value = "601";
    $("iUso").value = "G03";
    $("iMail").value = "";
    updateRfcValidation();

    $("invoiceModal").classList.remove("hidden");
    $("invoiceModal").classList.add("flex");
    $("iRfc").focus();
  }

  function fillGenericInvoice() {
    $("iRfc").value = "XAXX010101000";
    $("iName").value = "PÚBLICO EN GENERAL";
    $("iReg").value = "616";
    $("iUso").value = "S01";
    $("iZip").value = (settings && settings.zip_code) ? settings.zip_code : "06700";
    updateRfcValidation();
  }

  function updateRfcValidation() {
    const val = $("iRfc").value.trim().toUpperCase();
    $("iRfc").value = val;
    const badge = $("rfcTypeBadge");
    if (!badge) return;

    if (val === "XAXX010101000" || val === "XEXX010101000") {
      badge.textContent = "Público en General (SAT 616 / S01)";
      badge.className = "text-[10px] text-amber-400 font-bold font-mono";
      $("iReg").value = "616";
      $("iUso").value = "S01";
    } else if (val.length === 12) {
      badge.textContent = "Persona Moral (12 caracteres)";
      badge.className = "text-[10px] text-emerald-400 font-mono";
      if ($("iReg").value === "616" || $("iReg").value === "605" || $("iReg").value === "612") {
        $("iReg").value = "601";
      }
      if ($("iUso").value === "S01") {
        $("iUso").value = "G03";
      }
    } else if (val.length === 13) {
      badge.textContent = "Persona Física (13 caracteres)";
      badge.className = "text-[10px] text-emerald-400 font-mono";
      if ($("iReg").value === "601" || $("iReg").value === "603") {
        $("iReg").value = "612";
      }
      if ($("iUso").value === "S01") {
        $("iUso").value = "G03";
      }
    } else {
      badge.textContent = `${val.length}/13 caracteres`;
      badge.className = "text-[10px] text-zinc-400 font-mono";
    }
  }

  function openInvoicePrintModal(invoiceId, serie, folio) {
    $("printModalTitle").textContent = `Factura ${serie}-${folio}`;
    $("invoicePrintFrame").src = `/api/pos/invoices/${invoiceId}/print?token=${token}`;
    $("btnModalXmlLink").href = `/api/pos/invoices/${invoiceId}/xml?token=${token}`;
    $("btnModalXmlLink").setAttribute("download", `CFDI_${serie}${folio}.xml`);
    $("invoicePrintModal").classList.remove("hidden");
    $("invoicePrintModal").classList.add("flex");
  }

  const closeInvoiceModal = () => { $("invoiceModal").classList.add("hidden"); $("invoiceModal").classList.remove("flex"); };
  const closeInvoicePrintModal = () => {
    $("invoicePrintModal").classList.add("hidden");
    $("invoicePrintModal").classList.remove("flex");
    $("invoicePrintFrame").src = "about:blank";
  };

  // ---------- Productos
  async function loadProducts() {
    const list = await api("/products?include_inactive=true&q=" + encodeURIComponent($("pSearch").value));
    $("productsBody").innerHTML = list.map((p) => `<tr class="${p.active ? "" : "opacity-50"}"><td>${esc(p.name)}</td><td>${esc(p.sku || "")}</td><td>${esc(p.barcode || "")}</td>
      <td>${fmt(p.price)}</td><td>${fmt(p.cost)}</td><td>${IVA_LABEL[p.iva_type]}</td><td>${p.track_stock ? p.stock : "—"}</td>
      <td><button class="btn btn-sec !py-0.5" data-editp='${esc(JSON.stringify(p))}'>Editar</button></td></tr>`).join("");
    await loadQuickProducts();
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

    $("scanInput").addEventListener("input", handleScanInput);
    $("scanInput").addEventListener("keydown", handleScanKeyDown);
    $("scanBtn").onclick = () => {
      const box = $("searchResults");
      const isOpen = !box.classList.contains("hidden") && currentMatches.length > 0;
      if (isOpen && currentSuggestionIndex >= 0 && currentSuggestionIndex < currentMatches.length) {
        addToCart(currentMatches[currentSuggestionIndex]);
        $("scanInput").value = "";
        closeSuggestions();
        if ($("scanClearBtn")) $("scanClearBtn").classList.add("hidden");
        $("scanInput").focus();
      } else if (isOpen && currentMatches.length === 1) {
        addToCart(currentMatches[0]);
        $("scanInput").value = "";
        closeSuggestions();
        if ($("scanClearBtn")) $("scanClearBtn").classList.add("hidden");
        $("scanInput").focus();
      } else {
        scan();
      }
    };

    if ($("scanClearBtn")) {
      $("scanClearBtn").onclick = () => {
        $("scanInput").value = "";
        $("scanClearBtn").classList.add("hidden");
        closeSuggestions();
        $("scanInput").focus();
      };
    }

    $("searchResults").addEventListener("click", (e) => {
      const b = e.target.closest(".suggestion-item") || e.target.closest("[data-pick]");
      if (!b) return;
      const id = +b.dataset.pick;
      const p = currentMatches.find((x) => x.id === id) || cachedProducts.find((x) => x.id === id);
      if (p) {
        addToCart(p);
        $("scanInput").value = "";
        closeSuggestions();
        if ($("scanClearBtn")) $("scanClearBtn").classList.add("hidden");
        $("scanInput").focus();
      }
    });

    document.addEventListener("click", (e) => {
      if (!e.target.closest("#scanInput") && !e.target.closest("#searchResults") && !e.target.closest("#scanClearBtn")) {
        closeSuggestions();
      }
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
    if ($("reprintLastBtn")) $("reprintLastBtn").onclick = reprintLastTicket;

    if ($("quickProductsBar")) {
      $("quickProductsBar").addEventListener("click", (e) => {
        const b = e.target.closest("[data-quick-pick]");
        if (!b) return;
        const p = quickProductsCache.find((x) => x.id === +b.dataset.quickPick);
        if (p) {
          addToCart(p, 1);
          toast($("saleMsg"), `Agregado: ${p.name}`);
        }
      });
    }

    if ($("cashBox")) {
      $("cashBox").addEventListener("click", (e) => {
        const b = e.target.closest("[data-cash-denom]");
        if (!b) return;
        const val = b.dataset.cashDenom;
        if (val === "exact") {
          $("received").value = cartTotals().total.toFixed(2);
        } else {
          $("received").value = parseFloat(val).toFixed(2);
        }
        updateChange();
      });
    }

    window.addEventListener("keydown", (e) => {
      if (!$("loginOverlay").classList.contains("hidden")) return;
      if (e.key === "F2") {
        e.preventDefault();
        switchTab("venta");
        $("scanInput").focus();
        $("scanInput").select();
      } else if (e.key === "F4") {
        e.preventDefault();
        charge();
      } else if (e.key === "F8") {
        e.preventDefault();
        cart = [];
        renderCart();
      } else if (e.key === "F9") {
        e.preventDefault();
        reprintLastTicket();
      }
    });

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
      else if (b.dataset.invoice) openInvoiceModal(b.dataset.invoice, b.dataset.folio, b.dataset.method);
      else if (b.dataset.cancel && confirm("¿Cancelar esta venta? El inventario será devuelto.")) {
        try { await api(`/sales/${b.dataset.cancel}/cancel`, { method: "POST" }); await loadSales(); } catch (er) { alert(er.message); }
      }
    });

    $("invoicesBody").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.viewinv) openInvoicePrintModal(b.dataset.viewinv, b.dataset.serie, b.dataset.folio);
    });

    $("btnFillGenericInvoice").onclick = fillGenericInvoice;
    $("invCancel").onclick = closeInvoiceModal;
    if ($("invModalTopClose")) $("invModalTopClose").onclick = closeInvoiceModal;

    $("iRfc").oninput = updateRfcValidation;
    $("iReg").onchange = () => {
      if ($("iReg").value === "616") {
        $("iUso").value = "S01";
      } else if ($("iUso").value === "S01") {
        $("iUso").value = "G03";
      }
    };

    $("btnClosePrintModal").onclick = closeInvoicePrintModal;
    $("btnDoPrintInvoice").onclick = () => {
      const iframe = $("invoicePrintFrame");
      if (iframe && iframe.contentWindow) {
        iframe.contentWindow.focus();
        iframe.contentWindow.print();
      }
    };

    $("invoiceForm").onsubmit = async (e) => {
      e.preventDefault();
      try {
        const res = await api(`/sales/${currentInvoiceSale}/invoice`, { method: "POST", body: {
          rfc: $("iRfc").value.trim().toUpperCase(),
          razon_social: $("iName").value.trim().toUpperCase(),
          regimen_fiscal: $("iReg").value,
          codigo_postal: $("iZip").value.trim(),
          uso_cfdi: $("iUso").value || "G03",
          forma_pago: $("iFormaPago") ? $("iFormaPago").value : "01",
          metodo_pago: $("iMetodoPago") ? $("iMetodoPago").value : "PUE",
          email: $("iMail").value.trim() || null
        } });
        closeInvoiceModal();
        $("invoiceForm").reset();
        await loadSales();
        // Abrir inmediatamente la factura visual para el cajero y el cliente
        if (res && res.id) {
          openInvoicePrintModal(res.id, res.serie, res.folio);
        }
      } catch (er) {
        $("invError").textContent = er.message;
        $("invError").classList.remove("hidden");
      }
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
        resetProductForm(); await loadProducts(); await loadCachedProducts();
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
