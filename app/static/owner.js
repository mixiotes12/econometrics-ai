/* Portal del Dueño - Centro de Mando, Maquinaria, Gastos Fijos y Recálculo Dinámico */
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtMoney = (n) => "$" + Number(n || 0).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtNum = (n, d = 1) => Number(n || 0).toLocaleString("es-MX", { minimumFractionDigits: d, maximumFractionDigits: d });

  let token = sessionStorage.getItem("pos_token") || "";
  let me = JSON.parse(sessionStorage.getItem("pos_me") || "null");
  let lastLiveData = null;
  let lastRecalcData = null;

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      method: opts.method || "GET",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { "X-POS-Token": token } : {}),
      },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (res.status === 401 && opts.requireAuth) {
      showLoginModal();
      throw new Error("Inicia sesión con tu PIN de Administrador o Gerente para guardar cambios.");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "Error en la solicitud (" + res.status + ")");
    }
    return data;
  }

  // ---------- Autenticación para acciones de escritura
  async function showLoginModal() {
    const list = await fetch("/api/pos/cashiers/public").then((r) => r.json()).catch(() => []);
    $("loginCashier").innerHTML = list.map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.role_label || c.role)})</option>`).join("");
    $("loginOverlay").classList.remove("hidden");
  }

  async function doLogin() {
    try {
      const r = await api("/api/pos/login", {
        method: "POST",
        body: { cashier_id: +$("loginCashier").value, pin: $("loginPin").value },
      });
      if (r.cashier.role === "cajero" && !r.cashier.is_admin) {
        throw new Error("El rol de Cajero sólo tiene acceso a la Terminal POS (/pos.html), no al Portal del Dueño.");
      }
      token = r.token;
      me = r.cashier;
      sessionStorage.setItem("pos_token", token);
      sessionStorage.setItem("pos_me", JSON.stringify(me));
      $("loginPin").value = "";
      $("loginError").classList.add("hidden");
      $("loginOverlay").classList.add("hidden");
      updateWhoami();
      await loadAll();
    } catch (e) {
      $("loginError").textContent = e.message;
      $("loginError").classList.remove("hidden");
    }
  }

  function updateWhoami() {
    if (me) {
      $("whoamiBadge").innerHTML = `<i class="fa-solid fa-user-check text-emerald-400 mr-1"></i>${esc(me.name)} (${esc(me.role_label || "Dueño/Admin")})`;
    } else {
      $("whoamiBadge").innerHTML = `<button onclick="window._ownerLogin()" class="text-amber-400 hover:underline"><i class="fa-solid fa-lock mr-1"></i>Autenticar PIN</button>`;
    }
  }
  window._ownerLogin = showLoginModal;

  // ---------- Navegación de Pestañas
  function switchOwnerTab(tabName) {
    document.querySelectorAll("#ownerTabs .tab-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === tabName);
    });
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.classList.toggle("hidden", p.id !== "tab-" + tabName);
    });
  }

  // ---------- Carga Principal y Recálculo
  async function loadAll() {
    const days = +$("daysWindowSelect").value || 30;
    const useRealVol = $("useRealSalesVolumeChk").checked;

    const [liveData, recalcData] = await Promise.all([
      api(`/api/ops/live-parameters?days=${days}`),
      api(`/api/ops/recalculate`, {
        method: "POST",
        body: { days_window: days, use_real_sales_volume: useRealVol },
      }),
    ]);

    lastLiveData = liveData;
    lastRecalcData = recalcData;

    renderDashboardAndComparison(liveData, recalcData);
    renderAssetsTable(liveData.assets || [], liveData.breakdown);
    renderExpensesAndPayroll(liveData.expenses || [], liveData.breakdown);
    populateSimulatorInputs(recalcData.current_inputs);
  }

  function renderDashboardAndComparison(liveData, recalcData) {
    const b = liveData.baseline;
    const brk = liveData.breakdown;
    const curRep = recalcData.current_report;
    const baseRep = recalcData.baseline_report;

    $("bannerProjectTitle").textContent = `${b.project_name} · (${b.business_type})`;
    $("recalcTimestamp").textContent = `Actualizado: ${recalcData.generated_at}`;

    // KPIs superiores
    $("kpiCapital").textContent = fmtMoney(brk.total_capital_deployed);
    $("kpiCapitalSub").textContent = `Maquinaria: ${fmtMoney(brk.total_assets_value)} | Stock: ${fmtMoney(brk.inventory_cost_value)}`;

    $("kpiPriceCost").textContent = `${fmtMoney(brk.catalog_avg_net_price)} / ${fmtMoney(brk.catalog_avg_unit_cost)}`;
    $("kpiMarginSub").textContent = `Margen bruto catálogo: ${fmtNum(brk.catalog_gross_margin_pct, 1)}% (${brk.catalog_products_count} prods)`;

    $("kpiFixedReal").textContent = fmtMoney(brk.monthly_fixed_costs_total);
    $("kpiFixedSub").textContent = `Nómina: ${fmtMoney(brk.monthly_payroll_total)} + Gastos: ${fmtMoney(brk.monthly_non_payroll_expenses)}`;

    const beUnits = curRep.break_even.monthly_breakeven_units;
    const beRev = curRep.break_even.monthly_breakeven_revenue;
    $("kpiNewBreakeven").textContent = `${fmtNum(beUnits, 0)} uds/mes`;
    $("kpiNewBreakevenRev").textContent = `${fmtMoney(beRev)} / mes (Antes: ${fmtNum(baseRep.break_even.monthly_breakeven_units, 0)} uds)`;

    // Alertas prescriptivas
    const severityStyles = {
      critica: "border-rose-500/50 bg-rose-950/30 text-rose-200",
      alta: "border-amber-500/50 bg-amber-950/30 text-amber-200",
      media: "border-yellow-500/40 bg-yellow-950/20 text-yellow-100",
      info: "border-cyan-500/40 bg-cyan-950/20 text-cyan-100",
      ok: "border-emerald-500/40 bg-emerald-950/25 text-emerald-200",
    };
    const severityIcons = {
      critica: "fa-circle-xmark text-rose-400",
      alta: "fa-triangle-exclamation text-amber-400",
      media: "fa-circle-exclamation text-yellow-400",
      info: "fa-circle-info text-cyan-400",
      ok: "fa-circle-check text-emerald-400",
    };

    $("alertsContainer").innerHTML = (recalcData.alerts || [])
      .map(
        (al) => `
      <div class="p-3.5 rounded-xl border ${severityStyles[al.severity] || severityStyles.info} flex gap-3 items-start">
        <i class="fa-solid ${severityIcons[al.severity] || severityIcons.info} text-base mt-0.5"></i>
        <div class="space-y-1">
          <div class="font-bold text-xs">${esc(al.title)}</div>
          <div class="text-xs opacity-90 leading-relaxed">${esc(al.detail)}</div>
        </div>
      </div>`
      )
      .join("");

    // Tabla Comparativa
    $("comparisonTableBody").innerHTML = (recalcData.comparisons || [])
      .map((row) => {
        const formatVal = (v) => {
          if (row.unit.includes("MXN")) return fmtMoney(v);
          if (row.unit === "%") return fmtNum(v, 2) + "%";
          return fmtNum(v, 1) + " " + row.unit;
        };

        const deltaSign = row.delta > 0 ? "+" : "";
        const pctSign = row.delta_pct > 0 ? "+" : "";

        // Determinar si el cambio es favorable o desfavorable para el negocio
        let isGood = true;
        if (Math.abs(row.delta) < 0.01) {
          isGood = null;
        } else if (row.inverse_good) {
          isGood = row.delta < 0; // En costos y punto de equilibrio, bajar es bueno
        } else {
          isGood = row.delta > 0; // En precio, VAN y TIR, subir es bueno
        }

        const badge =
          isGood === null
            ? `<span class="pill bg-zinc-800 text-zinc-400">Sin cambio</span>`
            : isGood
            ? `<span class="pill bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">Favorable</span>`
            : `<span class="pill bg-amber-500/20 text-amber-300 border border-amber-500/30">Atención / Desvío</span>`;

        const colorClass = isGood === null ? "text-zinc-400" : isGood ? "text-emerald-400" : "text-amber-400";

        return `
        <tr class="hover:bg-zinc-900/50">
          <td class="font-medium text-zinc-200">${esc(row.label)}</td>
          <td class="text-right font-mono text-zinc-400">${formatVal(row.baseline)}</td>
          <td class="text-right font-mono font-bold text-white">${formatVal(row.current)}</td>
          <td class="text-right font-mono ${colorClass}">${deltaSign}${formatVal(row.delta)}</td>
          <td class="text-right font-mono ${colorClass}">${pctSign}${fmtNum(row.delta_pct, 1)}%</td>
          <td class="text-center">${badge}</td>
        </tr>`;
      })
      .join("");
  }

  // ---------- Pestaña 2: Maquinaria y Activos Fijos
  function renderAssetsTable(assets, brk) {
    $("assetsSummaryText").textContent = `${brk.assets_count} equipos activos · Valor total en planta: ${fmtMoney(brk.total_assets_value)} · Depreciación: ${fmtMoney(brk.monthly_depreciation_real)}/mes · Mantenimiento: ${fmtMoney(brk.monthly_maintenance_real)}/mes`;

    const statusBadge = {
      activo: `<span class="pill bg-emerald-500/20 text-emerald-300">Activo</span>`,
      en_reparacion: `<span class="pill bg-amber-500/20 text-amber-300">En reparación</span>`,
      baja: `<span class="pill bg-rose-500/20 text-rose-300">Baja</span>`,
    };

    $("assetsTableBody").innerHTML = assets
      .map(
        (a) => `
      <tr>
        <td>
          <div class="font-semibold text-zinc-100">${esc(a.name)}</div>
          <div class="text-[11px] text-zinc-500">Compra: ${esc(a.purchase_date)} · Vida útil: ${a.useful_life_years} años ${a.notes ? "· " + esc(a.notes) : ""}</div>
        </td>
        <td class="text-xs text-zinc-300">${esc(a.category)}</td>
        <td class="text-right font-mono">${fmtMoney(a.purchase_cost)}</td>
        <td class="text-right font-mono text-zinc-400">${fmtMoney(a.monthly_depreciation)}</td>
        <td class="text-right font-mono text-amber-300">${fmtMoney(a.monthly_maintenance)}</td>
        <td>${statusBadge[a.status] || a.status}</td>
        <td class="text-right whitespace-nowrap space-x-1">
          <button onclick="window._editAsset(${a.id})" class="btn btn-sec !px-2 !py-1 text-xs" title="Editar"><i class="fa-solid fa-pen"></i></button>
          <button onclick="window._deleteAsset(${a.id})" class="btn btn-red !px-2 !py-1 text-xs" title="Eliminar"><i class="fa-solid fa-trash"></i></button>
        </td>
      </tr>`
      )
      .join("");
  }

  window._editAsset = (id) => {
    const a = (lastLiveData?.assets || []).find((x) => x.id === id);
    if (!a) return;
    $("assetId").value = a.id;
    $("assetName").value = a.name;
    $("assetCategory").value = a.category;
    $("assetStatus").value = a.status;
    $("assetCost").value = a.purchase_cost;
    $("assetLife").value = a.useful_life_years;
    $("assetMaint").value = a.monthly_maintenance;
    $("assetDate").value = a.purchase_date;
    $("assetNotes").value = a.notes || "";
    $("assetFormTitle").textContent = "Editar Maquinaria #" + a.id;
  };

  window._deleteAsset = async (id) => {
    if (!confirm("¿Eliminar este equipo/activo del registro de planta?")) return;
    try {
      await api(`/api/ops/assets/${id}`, { method: "DELETE", requireAuth: true });
      await loadAll();
    } catch (e) {
      alert(e.message);
    }
  };

  function resetAssetForm() {
    $("assetForm").reset();
    $("assetId").value = "";
    $("assetDate").valueAsDate = new Date();
    $("assetFormTitle").textContent = "Registrar Maquinaria / Activo Fijo";
  }

  // ---------- Pestaña 3: Gastos Fijos y Nómina
  function renderExpensesAndPayroll(expenses, brk) {
    $("payrollTotalBadge").textContent = `${fmtMoney(brk.monthly_payroll_total)} / mes`;
    $("payrollDetailText").textContent = `Plantilla activa: ${brk.labor_headcount} empleados registrados en RRHH (incluye sueldo bruto, carga patronal y provisiones de ley).`;
    $("expensesTotalBadge").textContent = `Gastos no laborales: ${fmtMoney(brk.monthly_non_payroll_expenses)} / mes`;

    $("expensesTableBody").innerHTML = expenses
      .map(
        (e) => `
      <tr>
        <td class="font-semibold text-zinc-100">${esc(e.concept)}</td>
        <td class="text-xs text-zinc-300">${esc(e.category)}</td>
        <td class="text-right font-mono font-bold text-white">${fmtMoney(e.monthly_amount)}</td>
        <td>${e.active ? `<span class="pill bg-emerald-500/20 text-emerald-300">Activo</span>` : `<span class="pill bg-zinc-800 text-zinc-400">Inactivo</span>`}</td>
        <td class="text-xs text-zinc-400">${esc(e.notes || "")}</td>
        <td class="text-right whitespace-nowrap space-x-1">
          <button onclick="window._editExpense(${e.id})" class="btn btn-sec !px-2 !py-1 text-xs"><i class="fa-solid fa-pen"></i></button>
          <button onclick="window._deleteExpense(${e.id})" class="btn btn-red !px-2 !py-1 text-xs"><i class="fa-solid fa-trash"></i></button>
        </td>
      </tr>`
      )
      .join("");
  }

  window._editExpense = (id) => {
    const e = (lastLiveData?.expenses || []).find((x) => x.id === id);
    if (!e) return;
    $("expId").value = e.id;
    $("expConcept").value = e.concept;
    $("expCategory").value = e.category;
    $("expAmount").value = e.monthly_amount;
    $("expNotes").value = e.notes || "";
    $("expActive").checked = !!e.active;
    $("expenseFormTitle").textContent = "Editar Gasto Fijo #" + e.id;
  };

  window._deleteExpense = async (id) => {
    if (!confirm("¿Eliminar este gasto fijo mensual?")) return;
    try {
      await api(`/api/ops/expenses/${id}`, { method: "DELETE", requireAuth: true });
      await loadAll();
    } catch (e) {
      alert(e.message);
    }
  };

  function resetExpenseForm() {
    $("expenseForm").reset();
    $("expId").value = "";
    $("expActive").checked = true;
    $("expenseFormTitle").textContent = "Agregar / Ajustar Gasto Fijo Mensual";
  }

  // ---------- Pestaña 4: Simulador y Envío a EconoMetrics Studio
  function populateSimulatorInputs(fin) {
    if (!fin) return;
    $("simInvestment").value = fin.initial_investment;
    $("simPrice").value = fin.monthly_price;
    $("simUnits").value = fin.monthly_units;
    $("simVarCost").value = fin.unit_variable_cost;
    $("simFixedCosts").value = fin.monthly_fixed_costs;
    $("simMaintCost").value = fin.monthly_maintenance_cost;
    $("simShrinkage").value = fin.shrinkage_risk_loss_pct;
    $("simDepYears").value = fin.depreciation_years;
  }

  function readSimulatorInputs() {
    const b = lastLiveData?.baseline || {};
    return {
      initial_investment: +$("simInvestment").value || 0,
      discount_rate_pct: b.discount_rate_pct ?? 14.0,
      bank_risk_free_rate_pct: b.bank_risk_free_rate_pct ?? 10.5,
      shrinkage_risk_loss_pct: +$("simShrinkage").value || 0,
      projection_years: b.projection_years ?? 5,
      monthly_price: +$("simPrice").value || 0,
      monthly_units: +$("simUnits").value || 0,
      unit_variable_cost: +$("simVarCost").value || 0,
      monthly_fixed_costs: +$("simFixedCosts").value || 0,
      monthly_maintenance_cost: +$("simMaintCost").value || 0,
      annual_sales_growth_pct: b.annual_sales_growth_pct ?? 10.0,
      annual_inflation_pct: b.annual_inflation_pct ?? 4.5,
      tax_rate_pct: b.tax_rate_pct ?? 30.0,
      depreciation_years: +$("simDepYears").value || 5,
    };
  }

  function sendFinancialsToStudio(finObj) {
    const b = lastLiveData?.baseline || {};
    const payload = {
      project_name: b.project_name || "Negocio en Operación (Datos Reales)",
      business_type: b.business_type || "Comercio / Servicios",
      financials: finObj,
      exported_at: new Date().toISOString(),
    };
    localStorage.setItem("econometrics_live_recalc_payload", JSON.stringify(payload));
    window.location.href = "studio.html?from_ops=1";
  }

  // ---------- Eventos
  document.addEventListener("DOMContentLoaded", async () => {
    $("assetDate").valueAsDate = new Date();
    updateWhoami();

    // Si un cajero sin permisos intenta abrir owner.html, bloquear y pedir login de dueño
    if (me && (me.role === "cajero" || me.role === "cashier") && !me.is_admin) {
      await showLoginModal();
    }

    document.querySelectorAll("#ownerTabs .tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchOwnerTab(btn.dataset.tab));
    });

    $("loginBtn").addEventListener("click", doLogin);
    $("loginPin").addEventListener("keydown", (e) => {
      if (e.key === "Enter") doLogin();
    });

    $("refreshRecalcBtn").addEventListener("click", loadAll);
    $("daysWindowSelect").addEventListener("change", loadAll);
    $("useRealSalesVolumeChk").addEventListener("change", loadAll);

    // Botón rápido para enviar los datos reales actuales a EconoMetrics Studio
    $("sendToStudioBtn").addEventListener("click", () => {
      if (!lastRecalcData) return;
      sendFinancialsToStudio(lastRecalcData.current_inputs);
    });

    // Formulario de Maquinaria
    $("assetForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const id = $("assetId").value;
      const body = {
        name: $("assetName").value,
        category: $("assetCategory").value,
        status: $("assetStatus").value,
        purchase_cost: +$("assetCost").value,
        useful_life_years: +$("assetLife").value,
        monthly_maintenance: +$("assetMaint").value,
        purchase_date: $("assetDate").value || new Date().toISOString().slice(0, 10),
        notes: $("assetNotes").value,
      };
      try {
        if (id) {
          await api(`/api/ops/assets/${id}`, { method: "PUT", body, requireAuth: true });
        } else {
          await api(`/api/ops/assets`, { method: "POST", body, requireAuth: true });
        }
        resetAssetForm();
        await loadAll();
      } catch (err) {
        alert(err.message);
      }
    });
    $("assetResetBtn").addEventListener("click", resetAssetForm);

    // Formulario de Gastos Fijos
    $("expenseForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const id = $("expId").value;
      const body = {
        concept: $("expConcept").value,
        category: $("expCategory").value,
        monthly_amount: +$("expAmount").value,
        notes: $("expNotes").value,
        active: $("expActive").checked,
      };
      try {
        if (id) {
          await api(`/api/ops/expenses/${id}`, { method: "PUT", body, requireAuth: true });
        } else {
          await api(`/api/ops/expenses`, { method: "POST", body, requireAuth: true });
        }
        resetExpenseForm();
        await loadAll();
      } catch (err) {
        alert(err.message);
      }
    });
    $("expResetBtn").addEventListener("click", resetExpenseForm);

    // Botones del Simulador (Tab 4)
    $("loadLiveToSimBtn").addEventListener("click", () => {
      if (lastLiveData) populateSimulatorInputs(lastLiveData.live_inputs);
    });

    $("runCustomSimBtn").addEventListener("click", async () => {
      try {
        const customFin = readSimulatorInputs();
        const days = +$("daysWindowSelect").value || 30;
        const recalcData = await api(`/api/ops/recalculate`, {
          method: "POST",
          body: { days_window: days, custom_financials: customFin },
        });
        lastRecalcData = recalcData;
        renderDashboardAndComparison(lastLiveData, recalcData);
        switchOwnerTab("recalculo");
      } catch (err) {
        alert(err.message);
      }
    });

    $("saveSimAsBaselineBtn").addEventListener("click", async () => {
      if (!confirm("¿Actualizar el Plan Base (Baseline) oficial con estos parámetros?")) return;
      try {
        const customFin = readSimulatorInputs();
        const b = lastLiveData?.baseline || {};
        await api(`/api/ops/baseline`, {
          method: "POST",
          body: {
            project_name: b.project_name || "Mi Negocio",
            business_type: b.business_type || "Comercio / Servicios",
            financials: customFin,
            replace_assets: false,
          },
        });
        await loadAll();
        switchOwnerTab("recalculo");
      } catch (err) {
        alert(err.message);
      }
    });

    $("exportSimToStudioBtn").addEventListener("click", () => {
      sendFinancialsToStudio(readSimulatorInputs());
    });

    await loadAll();
  });
})();
