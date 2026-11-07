// EconoMetrics AI - Frontend Logic

let cashFlowChartInstance = null;
let breakEvenChartInstance = null;
let currentFinancialReport = null;

document.addEventListener("DOMContentLoaded", async () => {
  if (window.Chart && window.Chart.defaults) {
    window.Chart.defaults.font.size = 14;
    window.Chart.defaults.color = "#d4d4d8";
  }
  await initApiKey();
  initEventListeners();
  initEngineeringAndTrackerListeners();
  initMultiProductCatalog();
  initProjectPersistence();
  await initTemplatesAndSavedProjects();
  restoreSavedStateOrDraft();
  initOpsBridgeListeners();

  // Si viene de regreso desde el Portal del Dueño (/owner.html) con datos reales actualizados
  const liveRecalcStr = localStorage.getItem("econometrics_live_recalc_payload");
  if (liveRecalcStr) {
    try {
      const payload = JSON.parse(liveRecalcStr);
      localStorage.removeItem("econometrics_live_recalc_payload");
      if (payload && payload.financials) {
        const f = payload.financials;
        const setVal = (id, val) => {
          const el = document.getElementById(id);
          if (el && val !== undefined && val !== null) el.value = val;
        };
        if (typeof setCatalogInputMode === "function") {
          setCatalogInputMode("simple");
        }
        if (payload.project_name) setVal("businessName", payload.project_name);
        if (payload.business_type) setVal("businessType", payload.business_type);
        setVal("initialInvestment", f.initial_investment);
        setVal("discountRate", f.discount_rate_pct);
        setVal("bankRiskFreeRate", f.bank_risk_free_rate_pct);
        setVal("shrinkageLossPct", f.shrinkage_risk_loss_pct);
        setVal("projectionYears", f.projection_years);
        setVal("monthlyPrice", f.monthly_price);
        setVal("monthlyUnits", f.monthly_units);
        setVal("unitVariableCost", f.unit_variable_cost);
        setVal("monthlyFixedCosts", f.monthly_fixed_costs);
        setVal("monthlyMaintenanceCost", f.monthly_maintenance_cost);
        setVal("annualGrowth", f.annual_sales_growth_pct);
        setVal("annualInflation", f.annual_inflation_pct);
        setVal("taxRate", f.tax_rate_pct);
        setVal("depreciationYears", f.depreciation_years);
        updateSuggestedReserveHelper();
        updateBankAndShrinkageHelpers();
        scheduleAutoSave();
        switchTab(5);
        await runQuickCalculation();
        showToast("Parámetros reales del establecimiento importados desde el Portal del Dueño.", true);
      }
    } catch (e) {
      console.warn("Error al importar datos de operación:", e);
    }
  }
  
  const transferredInvestment = localStorage.getItem("econometrics_transfer_investment");
  if(transferredInvestment) {
    const invEl = document.getElementById("initialInvestment");
    if (invEl) invEl.value = transferredInvestment;
    localStorage.removeItem("econometrics_transfer_investment");
    await runQuickCalculation();
  }
});

// ----------------- TAB SWITCHING -----------------

function switchTab(tabIndex) {
  const idx = Number(tabIndex) || 1;
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.remove('active', 'text-white', 'border-purple-500/50', 'border-[#c5a059]/60', 'bg-zinc-800');
    btn.classList.add('text-zinc-300', 'border-zinc-800', 'bg-zinc-900');
    const badge = btn.querySelector('span:first-child');
    if (badge) {
      badge.classList.remove('bg-purple-500', 'bg-[#c5a059]', 'text-white', 'text-zinc-950');
      badge.classList.add('bg-zinc-800', 'text-[#d4b26f]');
    }
  });

  const activeBtn = document.getElementById(`tabBtn${idx}`);
  if (activeBtn) {
    activeBtn.classList.remove('text-zinc-300', 'border-zinc-800', 'bg-zinc-900');
    activeBtn.classList.add('active', 'text-white', 'border-[#c5a059]/60', 'bg-zinc-800');
    const activeBadge = activeBtn.querySelector('span:first-child');
    if (activeBadge) {
      activeBadge.classList.remove('bg-zinc-800', 'text-[#d4b26f]', 'bg-purple-500/30', 'text-purple-300');
      activeBadge.classList.add('bg-[#c5a059]', 'text-zinc-950');
    }
  }

  for (let i = 1; i <= 6; i++) {
    const section = document.getElementById(`tab${i}`);
    if (section) {
      if (i === idx) {
        section.classList.remove('hidden');
      } else {
        section.classList.add('hidden');
      }
    }
  }
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (idx === 2 && typeof window.renderPendingMermaid === "function") {
    window.renderPendingMermaid();
  }
  if (idx === 6 && typeof runQuickCalculation === "function") {
    runQuickCalculation();
  }
}
window.switchTab = switchTab;

let hasServerApiKey = false;

function getActiveGeminiApiKey() {
  const fromStorage = (localStorage.getItem("gemini_api_key") || "").trim();
  const fromInput = (document.getElementById("geminiApiKeyInput")?.value || "").trim();
  const key = fromStorage || fromInput;
  if (key && !fromStorage) {
    localStorage.setItem("gemini_api_key", key);
  }
  return key;
}

const VALID_GEMINI_MODELS = [
  "gemini-3.8-flash",
  "gemini-3.6-flash",
  "gemini-3.5-flash-lite",
  "gemini-3.1-flash-lite",
  "gemini-3-flash",
  "gemini-2.5-flash",
  "gemini-2.5-flash-lite"
];

function getActiveGeminiModel() {
  let raw = document.getElementById("geminiModelSelect")?.value || localStorage.getItem("gemini_model") || "gemini-3.8-flash";
  if (raw === "gemini-3.5-flash") raw = "gemini-3.5-flash-lite";
  return VALID_GEMINI_MODELS.includes(raw) ? raw : "gemini-3.8-flash";
}

// ----------------- API KEY & SETTINGS -----------------
async function initApiKey() {
  const savedKey = localStorage.getItem("gemini_api_key") || "";
  let savedModel = localStorage.getItem("gemini_model") || "gemini-3.8-flash";
  if (savedModel === "gemini-3.5-flash") savedModel = "gemini-3.5-flash-lite";
  if (!VALID_GEMINI_MODELS.includes(savedModel)) {
    savedModel = "gemini-3.8-flash";
    localStorage.setItem("gemini_model", savedModel);
  }

  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      const cfg = await res.json();
      hasServerApiKey = !!cfg.has_server_api_key;
    }
  } catch (e) {
    console.warn("No se pudo verificar /api/config", e);
  }

  const keyInput = document.getElementById("geminiApiKeyInput");
  if (savedKey) {
    if (keyInput) keyInput.value = savedKey;
    updateApiKeyBadge(true, "API Key: Configurada");
  } else if (hasServerApiKey) {
    updateApiKeyBadge(true, "API Key: Servidor Activa");
  } else {
    updateApiKeyBadge(false, "API Key: Inactiva");
  }

  const modelSelect = document.getElementById("geminiModelSelect");
  if (modelSelect) modelSelect.value = savedModel;
  updateGeminiHeaderBadge(savedModel);
  resetGeminiReportSectionStatus();
}

function updateGeminiHeaderBadge(modelName) {
  const badge = document.getElementById("geminiModelHeaderBadge");
  if (badge) {
    badge.textContent = modelName || "Gemini AI";
  }
}

function resetGeminiReportSectionStatus() {
  const badge = document.getElementById("geminiSectionStatusBadge");
  const iconBox = document.getElementById("geminiSectionIconBox");
  const section = document.getElementById("geminiReportSection");
  if (badge) {
    badge.textContent = "Pendiente de análisis";
    badge.className = "text-[10px] font-semibold px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400 border border-zinc-700";
  }
  if (iconBox) {
    iconBox.className = "w-10 h-10 rounded-xl bg-zinc-800 flex items-center justify-center text-zinc-400 shadow";
  }
  if (section) {
    section.classList.remove("glow-primary");
  }
}

function updateApiKeyBadge(hasKey, labelText) {
  const label = document.getElementById("apiKeyStatusLabel");
  const btn = document.getElementById("apiKeyBtn");
  if (label) label.textContent = labelText || (hasKey ? "API Key: Configurada" : "API Key: Inactiva");
  if (btn) {
    if (hasKey) {
      btn.classList.add("border-emerald-500/40", "text-emerald-400");
      btn.classList.remove("border-zinc-700", "text-zinc-300");
    } else {
      btn.classList.remove("border-emerald-500/40", "text-emerald-400");
      btn.classList.add("border-zinc-700", "text-zinc-300");
    }
  }
}

// ----------------- EVENT LISTENERS -----------------
function initEventListeners() {
  // Bind tab buttons explicitly in addition to inline onclick
  for (let i = 1; i <= 6; i++) {
    const tBtn = document.getElementById(`tabBtn${i}`);
    if (tBtn) {
      tBtn.addEventListener("click", () => switchTab(i));
    }
  }

  // API Key Modal
  const modal = document.getElementById("apiKeyModal");
  document.getElementById("apiKeyBtn")?.addEventListener("click", () => {
    modal?.classList.remove("hidden");
  });
  document.getElementById("closeApiKeyModal")?.addEventListener("click", () => {
    modal?.classList.add("hidden");
  });
  document.getElementById("saveApiKeyBtn")?.addEventListener("click", () => {
    const key = document.getElementById("geminiApiKeyInput")?.value.trim() || "";
    const model = getActiveGeminiModel();
    if (key) {
      localStorage.setItem("gemini_api_key", key);
      updateApiKeyBadge(true, "API Key: Configurada");
      showToast("API Key de Gemini guardada correctamente.", true);
    } else {
      localStorage.removeItem("gemini_api_key");
      updateApiKeyBadge(hasServerApiKey, hasServerApiKey ? "API Key: Servidor Activa" : "API Key: Inactiva");
    }
    localStorage.setItem("gemini_model", model);
    updateGeminiHeaderBadge(model);
    modal?.classList.add("hidden");
  });

  document.getElementById("toggleApiKeyVisibility")?.addEventListener("click", () => {
    const input = document.getElementById("geminiApiKeyInput");
    const icon = document.querySelector("#toggleApiKeyVisibility i");
    if (!input || !icon) return;
    if (input.type === "password") {
      input.type = "text";
      icon.classList.remove("fa-eye");
      icon.classList.add("fa-eye-slash");
    } else {
      input.type = "password";
      icon.classList.remove("fa-eye-slash");
      icon.classList.add("fa-eye");
    }
  });

  // Action Buttons
  const calcAndGoBtn = document.getElementById("calcAndGoTab5Btn") || document.getElementById("calcAndGoTab3Btn");
  if (calcAndGoBtn) {
    calcAndGoBtn.addEventListener("click", () => {
      switchTab(6);
    });
  }

  document.getElementById("runFullAnalysisBtn")?.addEventListener("click", () => {
    runFullGeminiAnalysis();
  });

  document.getElementById("reanalyzeBtn")?.addEventListener("click", () => {
    runFullGeminiAnalysis();
  });

  const exportPdfBtn = document.getElementById("exportPdfBtn");
  if (exportPdfBtn) {
    exportPdfBtn.addEventListener("click", () => {
      printFullStudioReport();
    });
  }

  // Live calculation & auto-save on financial inputs
  const liveInputs = [
    "initialInvestment", "discountRate", "bankRiskFreeRate", "shrinkageLossPct", "projectionYears",
    "monthlyPrice", "monthlyUnits", "unitVariableCost", "monthlyFixedCosts", "monthlyMaintenanceCost",
    "annualGrowth", "annualInflation", "taxRate", "depreciationYears"
  ];
  liveInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", () => {
        scheduleAutoSave();
        runQuickCalculation();
        if (id === "initialInvestment" || id === "depreciationYears") {
          updateSuggestedReserveHelper();
        }
        if (id === "initialInvestment" || id === "bankRiskFreeRate" || id === "monthlyPrice" || id === "monthlyUnits" || id === "shrinkageLossPct") {
          updateBankAndShrinkageHelpers();
        }
      });
      el.addEventListener("change", () => {
        scheduleAutoSave();
        runQuickCalculation();
        if (id === "initialInvestment" || id === "depreciationYears") {
          updateSuggestedReserveHelper();
        }
        if (id === "initialInvestment" || id === "bankRiskFreeRate" || id === "monthlyPrice" || id === "monthlyUnits" || id === "shrinkageLossPct") {
          updateBankAndShrinkageHelpers();
        }
      });
    }
  });

  // Apply suggested reserve button
  const applyReserveBtn = document.getElementById("applySuggestedReserveBtn");
  if (applyReserveBtn) {
    applyReserveBtn.addEventListener("click", () => {
      const inv = parseFloat(document.getElementById("initialInvestment")?.value || 0);
      const yrs = parseFloat(document.getElementById("depreciationYears")?.value || 5);
      if (inv > 0 && yrs > 0) {
        const suggested = Math.round(inv / (yrs * 12));
        const inputEl = document.getElementById("monthlyMaintenanceCost");
        if (inputEl) {
          inputEl.value = suggested;
          scheduleAutoSave();
          runQuickCalculation();
          showToast(`Reserva sugerida aplicada: $${suggested.toLocaleString()}/mes`, true);
        }
      }
    });
  }

  // Auto-save on business profile inputs
  const businessInputs = [
    "businessName", "businessType", "businessDescription", "targetMarket",
    "location", "locationDetails", "competitionLevel", "competitionDetails", "competitiveAdvantage",
    "sectorSelect", "economicActivity", "geoState", "geoMunicipality", "geoZoneType"
  ];

  // Geolocation & Acquisition Modal listeners (Fase 4)
  const geoModal = document.getElementById("geoAcquisitionModal");
  const btnOpenGeoModal = document.getElementById("btnOpenGeoModal");
  const closeGeoModalBtn = document.getElementById("closeGeoModalBtn");
  const closeGeoModalFooterBtn = document.getElementById("closeGeoModalFooterBtn");

  if (btnOpenGeoModal && geoModal) {
    btnOpenGeoModal.addEventListener("click", () => {
      openGeoAcquisitionModal();
    });
  }
  if (closeGeoModalBtn && geoModal) {
    closeGeoModalBtn.addEventListener("click", () => {
      geoModal.classList.add("hidden");
      geoModal.classList.remove("flex");
    });
  }
  if (closeGeoModalFooterBtn && geoModal) {
    closeGeoModalFooterBtn.addEventListener("click", () => {
      geoModal.classList.add("hidden");
      geoModal.classList.remove("flex");
    });
  }
  if (geoModal) {
    geoModal.addEventListener("click", (e) => {
      if (e.target === geoModal) {
        geoModal.classList.add("hidden");
        geoModal.classList.remove("flex");
      }
    });
  }
  businessInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", () => scheduleAutoSave());
      el.addEventListener("change", () => scheduleAutoSave());
    }
  });
  updateSuggestedReserveHelper();
  updateBankAndShrinkageHelpers();
}

function updateSuggestedReserveHelper() {
  const helperEl = document.getElementById("suggestedReserveHelper");
  if (!helperEl) return;
  const inv = parseFloat(document.getElementById("initialInvestment")?.value || 0);
  const yrs = parseFloat(document.getElementById("depreciationYears")?.value || 5);
  if (inv > 0 && yrs > 0) {
    const suggested = Math.round(inv / (yrs * 12));
    helperEl.textContent = `Sugerido: $${suggested.toLocaleString()}/mes ($${inv.toLocaleString()} ÷ ${yrs} años)`;
  } else {
    helperEl.textContent = `Sugerido: $0/mes`;
  }
}

function updateBankAndShrinkageHelpers() {
  const bankHint = document.getElementById("bankPassiveIncomeHint");
  const shrinkageHint = document.getElementById("shrinkageLossHelper");

  const inv = parseFloat(document.getElementById("initialInvestment")?.value || 0);
  const bankRate = parseFloat(document.getElementById("bankRiskFreeRate")?.value || 10.5);
  const price = parseFloat(document.getElementById("monthlyPrice")?.value || 0);
  const units = parseFloat(document.getElementById("monthlyUnits")?.value || 0);
  const shrinkPct = parseFloat(document.getElementById("shrinkageLossPct")?.value || 0);

  if (bankHint) {
    const monthlyPassive = Math.round((inv * (bankRate / 100.0)) / 12.0);
    bankHint.textContent = `Pasivo: $${monthlyPassive.toLocaleString()}/mes sin riesgo`;
  }

  if (shrinkageHint) {
    const monthlySales = price * units;
    const monthlyLoss = Math.round(monthlySales * (shrinkPct / 100.0));
    shrinkageHint.textContent = `Descuento: -$${monthlyLoss.toLocaleString()}/mes (${shrinkPct}%)`;
  }
}

// ----------------- TOAST NOTIFICATIONS -----------------
let toastTimer = null;
function showToast(message, isSuccess = true) {
  const toast = document.getElementById("notificationToast");
  const msgEl = document.getElementById("toastMessage");
  const icon = document.getElementById("toastIcon");
  if (!toast || !msgEl) return;

  msgEl.textContent = message;
  if (isSuccess) {
    icon.className = "fa-solid fa-circle-check text-emerald-400 text-sm";
    toast.className = "fixed bottom-6 right-6 z-50 bg-zinc-900 border border-emerald-500/40 text-zinc-100 text-xs font-medium px-4 py-3 rounded-xl shadow-2xl flex items-center gap-2.5 transition-all duration-300";
  } else {
    icon.className = "fa-solid fa-circle-exclamation text-amber-400 text-sm";
    toast.className = "fixed bottom-6 right-6 z-50 bg-zinc-900 border border-amber-500/40 text-zinc-100 text-xs font-medium px-4 py-3 rounded-xl shadow-2xl flex items-center gap-2.5 transition-all duration-300";
  }

  toast.classList.remove("hidden");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.add("hidden");
  }, 3500);
}

// ----------------- PROJECT PERSISTENCE (AUTOSAVE & NAMED PROJECTS) -----------------
let serverTemplates = [];
let autoSaveTimer = null;

function scheduleAutoSave() {
  if (autoSaveTimer) clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(() => {
    const data = getFormData();
    localStorage.setItem("econometrics_current_draft", JSON.stringify(data));
  }, 400);
}

function restoreSavedStateOrDraft() {
  const draftStr = localStorage.getItem("econometrics_current_draft");
  if (draftStr) {
    try {
      const data = JSON.parse(draftStr);
      if (data && data.business && data.financials) {
        applyFormData(data);
        // Si el borrador no tenía datos de ingeniería (guardado antes de la actualización),
        // buscamos si coincide con una plantilla para auto-completar las pestañas 1 y 2
        if (!data.engineering || !data.engineering.equipment_items || data.engineering.equipment_items.length === 0) {
          const match = serverTemplates.find(t => 
            (t.name && data.business.name && t.name.toLowerCase() === data.business.name.toLowerCase()) ||
            (t.business && t.business.name && data.business.name && t.business.name.toLowerCase() === data.business.name.toLowerCase())
          );
          if (match && match.engineering && typeof window.applyEngineeringData === "function") {
            window.applyEngineeringData(match.engineering);
            const select = document.getElementById("templateSelect");
            if (select) select.value = match.id;
          }
        }
        runQuickCalculation();
        showToast("Tu configuración anterior fue restaurada automáticamente.", true);
        return;
      }
    } catch (e) {
      console.warn("No se pudo restaurar el borrador:", e);
    }
  }
  // Si no hay borrador previo, precargar plantilla de ejemplo por defecto
  if (serverTemplates.length > 0) {
    const defaultTmpl = serverTemplates[0];
    applyFormData(defaultTmpl);
    const select = document.getElementById("templateSelect");
    if (select) select.value = defaultTmpl.id;
  }
  runQuickCalculation();
}

function applyFormData(data) {
  if (!data) return;
  const b = data.business || {};
  const f = data.financials || {};

  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el && val !== undefined && val !== null) el.value = val;
  };

  setVal("businessName", b.name);
  setVal("businessType", b.business_type);
  setVal("businessDescription", b.description);
  setVal("targetMarket", b.target_market);
  setVal("location", b.location);
  setVal("locationDetails", b.location_details || "");
  setVal("competitionLevel", b.competition_level || "Media");
  setVal("competitionDetails", b.competition_details || "");
  setVal("competitiveAdvantage", b.competitive_advantage || "");
  setVal("sectorSelect", b.sector);
  setVal("economicActivity", b.economic_activity || "");
  setVal("geoState", b.state);
  setVal("geoMunicipality", b.municipality || "");
  setVal("geoZoneType", b.zone_type);

  setVal("initialInvestment", f.initial_investment);
  const invEl = document.getElementById("initialInvestment");
  if (invEl) {
    invEl.removeAttribute("readonly");
    invEl.classList.remove("bg-zinc-800", "cursor-not-allowed");
  }
  setVal("discountRate", f.discount_rate_pct);
  setVal("bankRiskFreeRate", f.bank_risk_free_rate_pct !== undefined ? f.bank_risk_free_rate_pct : 10.5);
  setVal("shrinkageLossPct", f.shrinkage_risk_loss_pct !== undefined ? f.shrinkage_risk_loss_pct : 2.0);
  setVal("projectionYears", f.projection_years);
  setVal("monthlyPrice", f.monthly_price);
  setVal("monthlyUnits", f.monthly_units);
  setVal("unitVariableCost", f.unit_variable_cost);
  setVal("monthlyFixedCosts", f.monthly_fixed_costs);
  setVal("monthlyMaintenanceCost", f.monthly_maintenance_cost !== undefined ? f.monthly_maintenance_cost : 0);
  setVal("annualGrowth", f.annual_sales_growth_pct);
  setVal("annualInflation", f.annual_inflation_pct);
  setVal("taxRate", f.tax_rate_pct);
  setVal("depreciationYears", f.depreciation_years);
  if (typeof updateSuggestedReserveHelper === "function") updateSuggestedReserveHelper();
  if (typeof updateBankAndShrinkageHelpers === "function") updateBankAndShrinkageHelpers();

  // Cargar Catálogo Multiproducto si viene en los datos o generar ejemplo para la plantilla
  if (data.product_catalog && Array.isArray(data.product_catalog) && data.product_catalog.length > 0) {
    if (typeof applyMultiProductCatalogData === "function") {
      applyMultiProductCatalogData(data.product_catalog, data.catalog_mode || "multi");
    }
  } else if (typeof applyDefaultMultiProductForTemplate === "function") {
    applyDefaultMultiProductForTemplate(data.id || b.name, f.monthly_price, f.unit_variable_cost, f.monthly_units);
  }

  if (data.engineering && typeof window.applyEngineeringData === "function") {
    window.applyEngineeringData(data.engineering);
  }
  if (data.id) {
    const sel = document.getElementById("templateSelect");
    if (sel) sel.value = data.id;
  }
}

function getSavedProjects() {
  try {
    const saved = localStorage.getItem("econometrics_saved_projects");
    return saved ? JSON.parse(saved) : [];
  } catch (e) {
    return [];
  }
}

function saveProjectsList(list) {
  localStorage.setItem("econometrics_saved_projects", JSON.stringify(list));
}

function saveNamedProject(name) {
  const data = getFormData();
  const projName = (name || data.business.name || "Mi Proyecto Guardado").trim();
  const list = getSavedProjects();

  const existingIdx = list.findIndex(p => p.name.toLowerCase() === projName.toLowerCase());
  const projectItem = {
    id: "saved_" + Date.now(),
    name: projName,
    business: data.business,
    financials: data.financials,
    engineering: data.engineering,
    product_catalog: data.product_catalog,
    catalog_mode: data.catalog_mode,
    project_key: window.currentProjectKey || null,
    savedAt: new Date().toISOString()
  };

  if (existingIdx >= 0) {
    list[existingIdx] = projectItem;
  } else {
    list.unshift(projectItem);
  }

  saveProjectsList(list);
  localStorage.setItem("econometrics_current_draft", JSON.stringify(data));
  updateTemplateSelectDropdown(projectItem.id);
  showToast(`¡Configuración "${projName}" guardada exitosamente!`, true);
}

function updateTemplateSelectDropdown(selectedId = "") {
  const select = document.getElementById("templateSelect");
  if (!select) return;
  select.innerHTML = '<option value="">-- Cargar Proyecto o Plantilla --</option>';

  const savedProjects = getSavedProjects();
  if (savedProjects.length > 0) {
    const groupSaved = document.createElement("optgroup");
    groupSaved.label = "⭐ Mis Proyectos Guardados";
    savedProjects.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = `★ ${p.name}`;
      if (p.id === selectedId) opt.selected = true;
      groupSaved.appendChild(opt);
    });
    select.appendChild(groupSaved);
  }

  if (serverTemplates.length > 0) {
    const groupTmpl = document.createElement("optgroup");
    groupTmpl.label = "📋 Plantillas de Ejemplo";
    serverTemplates.forEach(t => {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = t.name;
      if (t.id === selectedId) opt.selected = true;
      groupTmpl.appendChild(opt);
    });
    select.appendChild(groupTmpl);
  }
}

async function initTemplatesAndSavedProjects() {
  try {
    const res = await fetch("/api/templates");
    if (res.ok) {
      serverTemplates = await res.json();
    }
  } catch (err) {
    console.error("Error cargando plantillas:", err);
  }

  updateTemplateSelectDropdown();

  const select = document.getElementById("templateSelect");
  select?.addEventListener("change", () => {
    const val = select.value;
    if (!val) return;

    if (val.startsWith("saved_")) {
      const savedList = getSavedProjects();
      const proj = savedList.find(p => p.id === val);
      if (proj) {
        if (proj.project_key) {
          window.currentProjectKey = proj.project_key;
          localStorage.setItem("econometrics_current_project_key", proj.project_key);
          if (typeof updateProjectKeyBadge === "function") updateProjectKeyBadge(proj.project_key);
        } else {
          window.currentProjectKey = null;
          if (typeof updateProjectKeyBadge === "function") updateProjectKeyBadge(null);
        }
        applyFormData(proj);
        runQuickCalculation();
        scheduleAutoSave();
        showToast(`Proyecto cargado: "${proj.name}"`, true);
      }
    } else {
      window.currentProjectKey = null;
      if (typeof updateProjectKeyBadge === "function") updateProjectKeyBadge(null);
      const tmpl = serverTemplates.find(t => t.id === val);
      if (tmpl) {
        applyFormData(tmpl);
        runQuickCalculation();
        scheduleAutoSave();
        showToast(`Plantilla cargada: "${tmpl.name}"`, true);
      }
    }
  });
}

function initProjectPersistence() {
  // Save Project Modal Triggers
  const saveBtn = document.getElementById("saveProjectBtn");
  const modal = document.getElementById("saveProjectModal");
  const closeBtn = document.getElementById("closeSaveProjectModal");
  const cancelBtn = document.getElementById("cancelSaveProjectBtn");
  const confirmBtn = document.getElementById("confirmSaveProjectBtn");
  const nameInput = document.getElementById("saveProjectNameInput");

  if (saveBtn && modal) {
    saveBtn.addEventListener("click", () => {
      const currentName = document.getElementById("businessName")?.value.trim() || "Mi Proyecto";
      if (nameInput) nameInput.value = currentName;
      modal.classList.remove("hidden");
      if (nameInput) nameInput.focus();
    });

    closeBtn?.addEventListener("click", () => modal.classList.add("hidden"));
    cancelBtn?.addEventListener("click", () => modal.classList.add("hidden"));

    confirmBtn?.addEventListener("click", () => {
      const name = nameInput ? nameInput.value.trim() : "";
      saveNamedProject(name);
      modal.classList.add("hidden");
    });
  }

  // New Clean Project Button
  const newBtn = document.getElementById("newProjectBtn");
  if (newBtn) {
    newBtn.addEventListener("click", () => {
      if (confirm("¿Deseas iniciar una nueva configuración limpia? Los cambios no guardados con nombre se reemplazarán.")) {
        const blank = {
          business: {
            name: "Nuevo Proyecto",
            business_type: "",
            description: "",
            target_market: "",
            location: "",
            location_details: "",
            competition_level: "Media",
            competition_details: "",
            competitive_advantage: ""
          },
          financials: {
            initial_investment: 100000,
            discount_rate_pct: 12,
            bank_risk_free_rate_pct: 10.5,
            shrinkage_risk_loss_pct: 2.0,
            projection_years: 5,
            monthly_price: 100,
            monthly_units: 500,
            unit_variable_cost: 30,
            monthly_fixed_costs: 20000,
            monthly_maintenance_cost: 1500,
            annual_sales_growth_pct: 5,
            annual_inflation_pct: 4,
            tax_rate_pct: 30,
            depreciation_years: 5
          },
          engineering: { equipment_items: [], process_description: "", budgets: null, flowchart: null }
        };
        applyFormData(blank);
        resetGeminiReportSectionStatus();
        document.getElementById("viabilityScoreBadge")?.classList.add("hidden");
        const execSum = document.getElementById("geminiExecutiveSummary");
        if (execSum) execSum.innerHTML = 'Presiona el botón <strong>"Dictamen Estratégico IA"</strong> para generar el diagnóstico cualitativo profundo.';
        const locAn = document.getElementById("geminiLocationAnalysis");
        if (locAn) locAn.innerHTML = 'Pendiente de generación.';
        const compAn = document.getElementById("geminiCompetitionAnalysis");
        if (compAn) compAn.innerHTML = 'Pendiente de generación.';
        const costAn = document.getElementById("geminiCostAnalysis");
        if (costAn) costAn.innerHTML = 'Pendiente de generación.';
        const risksTb = document.getElementById("geminiRisksTableBody");
        if (risksTb) risksTb.innerHTML = '';
        const actList = document.getElementById("geminiActionPlanList");
        if (actList) actList.innerHTML = '';
        const tsBadge = document.getElementById("geminiTimestampBadge");
        if (tsBadge) tsBadge.textContent = '';
        runQuickCalculation();
        scheduleAutoSave();
        const tmplSel = document.getElementById("templateSelect");
        if (tmplSel) tmplSel.value = "";
        window.currentProjectKey = null;
        localStorage.removeItem("econometrics_current_project_key");
        if (typeof updateProjectKeyBadge === "function") updateProjectKeyBadge(null);
        showToast("Formulario listo para nuevo proyecto", true);
        switchTab(1);
      }
    });
  }
}

function formatApiError(err) {
  if (!err) return "Error desconocido";
  if (typeof err === "string") return err;
  if (typeof err.detail === "string") return err.detail;
  if (Array.isArray(err.detail)) {
    return err.detail.map(d => {
      const loc = Array.isArray(d.loc) ? d.loc.filter(x => x !== "body").join(".") : "";
      return loc ? `${loc}: ${d.msg}` : (d.msg || JSON.stringify(d));
    }).join(" | ");
  }
  if (err.detail && typeof err.detail === "object") {
    return JSON.stringify(err.detail);
  }
  return err.message || JSON.stringify(err);
}

// ----------------- GET FORM DATA -----------------
function getFormData() {
  const getText = (id, defaultVal = "") => {
    const el = document.getElementById(id);
    return el && el.value ? el.value.trim() : defaultVal;
  };

  const business = {
    name: getText("businessName", "Mi Proyecto"),
    business_type: getText("businessType", "Comercio / Servicios"),
    description: getText("businessDescription", "Propuesta de valor y venta de productos o servicios."),
    target_market: getText("targetMarket", "Clientes potenciales y público objetivo."),
    location: getText("location", "Zona comercial urbana."),
    location_details: getText("locationDetails", ""),
    competition_level: getText("competitionLevel", "Media"),
    competition_details: getText("competitionDetails", ""),
    competitive_advantage: getText("competitiveAdvantage", ""),
    sector: getText("sectorSelect", "Comercio al por menor"),
    commercial_branch: getText("businessType", "Comercio / Servicios"),
    economic_activity: getText("economicActivity", ""),
    state: getText("geoState", "Ciudad de México"),
    municipality: getText("geoMunicipality", ""),
    zone_type: getText("geoZoneType", "Corredor comercial de alto flujo peatonal")
  };

  const getNum = (id, defaultVal) => {
    const el = document.getElementById(id);
    if (!el || el.value === undefined || el.value === null || el.value === "") return defaultVal;
    let raw = String(el.value).replace(/[$, ]/g, "").trim();
    const val = parseFloat(raw);
    return isNaN(val) ? defaultVal : val;
  };

  const financials = {
    initial_investment: Math.max(0, getNum("initialInvestment", 100000)),
    discount_rate_pct: Math.max(0, getNum("discountRate", 12.0)),
    bank_risk_free_rate_pct: Math.max(0, getNum("bankRiskFreeRate", 10.5)),
    shrinkage_risk_loss_pct: Math.max(0, Math.min(100, getNum("shrinkageLossPct", 2.0))),
    projection_years: Math.max(1, Math.min(20, Math.round(getNum("projectionYears", 5)))),
    monthly_price: Math.max(0, getNum("monthlyPrice", 100)),
    monthly_units: Math.max(0, getNum("monthlyUnits", 500)),
    unit_variable_cost: Math.max(0, getNum("unitVariableCost", 30)),
    monthly_fixed_costs: Math.max(0, getNum("monthlyFixedCosts", 20000)),
    monthly_maintenance_cost: Math.max(0, getNum("monthlyMaintenanceCost", 0.0)),
    annual_sales_growth_pct: getNum("annualGrowth", 5.0),
    annual_inflation_pct: Math.max(0, getNum("annualInflation", 4.0)),
    tax_rate_pct: Math.max(0, Math.min(100, getNum("taxRate", 30.0))),
    depreciation_years: Math.max(1, Math.min(50, Math.round(getNum("depreciationYears", 5))))
  };

  const engineering = typeof window.getEngineeringData === "function" ? window.getEngineeringData() : null;
  const product_catalog = typeof getMultiProductCatalogData === "function" ? getMultiProductCatalogData() : [];
  const catalog_mode = typeof getCatalogInputMode === "function" ? getCatalogInputMode() : "multi";

  return { business, financials, engineering, product_catalog, catalog_mode };
}

// ----------------- QUICK FINANCIAL CALCULATION & FULL PDF PRINT -----------------
async function printFullStudioReport() {
  await runQuickCalculation();
  if (typeof window.renderPendingMermaid === "function") {
    await window.renderPendingMermaid();
  }
  const detailsEls = Array.from(document.querySelectorAll("details.advanced-panel"));
  const prevOpen = detailsEls.map(d => d.open);
  detailsEls.forEach(d => { d.open = true; });

  if (cashFlowChartInstance) cashFlowChartInstance.resize();
  if (breakEvenChartInstance) breakEvenChartInstance.resize();

  setTimeout(() => {
    window.print();
    detailsEls.forEach((d, idx) => { d.open = prevOpen[idx]; });
  }, 200);
}
window.printFullStudioReport = printFullStudioReport;

async function runQuickCalculation() {
  const { financials } = getFormData();
  try {
    const res = await fetch("/api/calc-financials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(financials)
    });

    if (!res.ok) {
      let errData;
      try { errData = await res.json(); } catch(e) { errData = { detail: res.statusText }; }
      throw new Error(formatApiError(errData));
    }

    const report = await res.json();
    currentFinancialReport = report;
    renderFinancialReport(report);
    const pdfBtn = document.getElementById("exportPdfBtn");
    if (pdfBtn) pdfBtn.classList.remove("hidden");
  } catch (err) {
    console.error("Calculation error:", err);
  }
}

// ----------------- FULL GEMINI ANALYSIS -----------------
async function runFullGeminiAnalysis() {
  const key = getActiveGeminiApiKey();
  if (!key && !hasServerApiKey) {
    document.getElementById("apiKeyModal")?.classList.remove("hidden");
    showToast("Ingresa tu API Key de Gemini para ejecutar el Dictamen Estratégico con IA.", false);
    return;
  }

  const model = getActiveGeminiModel();
  const { business, financials, engineering } = getFormData();
  // Enriquecer descripción del negocio con datos de ingeniería/procesos si existen
  const enrichedBusiness = { ...business };
  if (engineering && engineering.process_description) {
    enrichedBusiness.description = `${business.description || ""} | Proceso productivo: ${engineering.process_description}`.trim();
  }

  switchTab(6);
  const spinner = document.getElementById("aiLoadingSpinner");
  if (spinner) spinner.classList.remove("hidden");

  try {
    const headers = { "Content-Type": "application/json" };
    if (key) {
      headers["x-gemini-api-key"] = key;
    }
    const payload = {
      business: enrichedBusiness,
      financials,
      gemini_model: model
    };
    if (key) {
      payload.custom_api_key = key;
    }

    const res = await fetch("/api/full-analysis", {
      method: "POST",
      headers,
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      let errData;
      try { errData = await res.json(); } catch(e) { errData = { detail: res.statusText }; }
      throw new Error(formatApiError(errData));
    }

    const fullData = await res.json();
    currentFinancialReport = fullData.financial_report;
    renderFinancialReport(fullData.financial_report);
    if (fullData.strategic_advice) {
      renderStrategicAdvice(fullData.strategic_advice, fullData.generated_at);
      showToast("Dictamen Estratégico generado con éxito por Gemini AI.", true);
    }
  } catch (err) {
    showToast("Error en Gemini AI: " + err.message, false);
    alert("No se pudo generar el dictamen con Gemini AI:\n\n" + err.message);
  } finally {
    if (spinner) spinner.classList.add("hidden");
  }
}

// ----------------- RENDER FINANCIAL DATA -----------------
function renderFinancialReport(report) {
  // Format currency helper in MXN
  const fmt = (val) => new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN', maximumFractionDigits: 0 }).format(val);
  const fmtPct = (val) => `${val?.toFixed(1) || 0}%`;

  // Status Banner
  const statusText = document.getElementById("viabilityStatusText");
  const verdictSub = document.getElementById("viabilityVerdictSub");
  const iconBox = document.getElementById("viabilityIconBox");

  statusText.textContent = report.viability_status;
  if (report.summary_bullets && report.summary_bullets.length > 0) {
    verdictSub.textContent = report.summary_bullets.join(" ");
  }

  if (report.viability_color === "emerald") {
    iconBox.className = "w-12 h-12 rounded-xl flex items-center justify-center text-xl shadow-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
    iconBox.innerHTML = '<i class="fa-solid fa-circle-check"></i>';
  } else if (report.viability_color === "amber" || report.viability_color === "orange") {
    iconBox.className = "w-12 h-12 rounded-xl flex items-center justify-center text-xl shadow-lg bg-amber-500/20 text-amber-400 border border-amber-500/30";
    iconBox.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i>';
  } else {
    iconBox.className = "w-12 h-12 rounded-xl flex items-center justify-center text-xl shadow-lg bg-rose-500/20 text-rose-400 border border-rose-500/30";
    iconBox.innerHTML = '<i class="fa-solid fa-circle-xmark"></i>';
  }

  // KPIs
  const npvEl = document.getElementById("kpiNpv");
  npvEl.textContent = fmt(report.npv);
  npvEl.className = `text-xl sm:text-2xl font-black font-mono ${report.npv >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;

  const irrEl = document.getElementById("kpiIrr");
  irrEl.textContent = report.irr_pct !== null ? `${report.irr_pct.toFixed(1)}%` : "N/D";
  document.getElementById("kpiIrrSub").textContent = `Tasa de descuento: ${report.discount_rate_pct}%`;

  document.getElementById("kpiPayback").textContent = report.payback_years !== null ? `${report.payback_years.toFixed(1)} años` : "No recupera";
  document.getElementById("kpiDiscountedPayback").textContent = report.discounted_payback_years !== null ? `Descontado: ${report.discounted_payback_years.toFixed(1)} años` : "Descontado: > horizonte";

  document.getElementById("kpiBreakevenUnits").textContent = `${Math.round(report.break_even.monthly_breakeven_units).toLocaleString()} unidades/mes`;
  document.getElementById("kpiBreakevenRevenue").textContent = `${fmt(report.break_even.monthly_breakeven_revenue)} MXN / mes`;

  const mosEl = document.getElementById("kpiMarginOfSafety");
  mosEl.textContent = fmtPct(report.break_even.margin_of_safety_pct);
  mosEl.className = `text-lg sm:text-xl font-bold font-mono ${report.break_even.margin_of_safety_pct > 20 ? 'text-emerald-400' : (report.break_even.margin_of_safety_pct > 0 ? 'text-amber-400' : 'text-rose-400')}`;

  document.getElementById("kpiContributionMargin").textContent = `${fmt(report.break_even.unit_contribution_margin)} (${report.break_even.contribution_margin_ratio_pct.toFixed(1)}%)`;
  document.getElementById("kpiBenefitCost").textContent = `${report.benefit_cost_ratio.toFixed(2)}x`;
  document.getElementById("kpiRoiAvg").textContent = `${report.roi_annual_avg_pct.toFixed(1)}%`;

  // Bank Opportunity Cost Comparison Card
  const comp = report.bank_comparison;
  if (comp) {
    const bankRateEl = document.getElementById("bankRateLabel");
    if (bankRateEl) bankRateEl.textContent = `${comp.bank_risk_free_rate_pct}% anual`;

    const bankPassAnnEl = document.getElementById("bankPassiveAnnual");
    if (bankPassAnnEl) bankPassAnnEl.textContent = fmt(comp.bank_passive_annual_income);

    const bankPassMoEl = document.getElementById("bankPassiveMonthly");
    if (bankPassMoEl) bankPassMoEl.textContent = fmt(comp.bank_passive_monthly_income);

    const bizRoiEl = document.getElementById("businessRoiLabel");
    if (bizRoiEl) bizRoiEl.textContent = `ROI: ${report.roi_annual_avg_pct?.toFixed(1) || 0}%`;

    const bizAnnNetEl = document.getElementById("businessAnnualNet");
    if (bizAnnNetEl) bizAnnNetEl.textContent = fmt(comp.business_net_annual_income);

    const bizMoNetEl = document.getElementById("businessMonthlyNet");
    if (bizMoNetEl) bizMoNetEl.textContent = fmt(comp.business_net_monthly_income);

    const shrinkDeductEl = document.getElementById("shrinkageDeductedMonthly");
    if (shrinkDeductEl) shrinkDeductEl.textContent = `-${fmt(report.shrinkage_monthly_loss || 0)}/mes`;

    const riskSpreadPctEl = document.getElementById("riskSpreadPct");
    if (riskSpreadPctEl) {
      riskSpreadPctEl.textContent = `${comp.risk_premium_pct >= 0 ? '+' : ''}${comp.risk_premium_pct.toFixed(1)}%`;
      riskSpreadPctEl.className = `text-xl font-black font-mono ${comp.risk_premium_pct >= 5 ? 'text-emerald-400' : (comp.risk_premium_pct >= 0 ? 'text-amber-400' : 'text-rose-400')}`;
    }

    const riskSpreadMoEl = document.getElementById("riskSpreadMonthlyDiff");
    if (riskSpreadMoEl) {
      riskSpreadMoEl.textContent = `(${comp.monthly_difference >= 0 ? '+' : ''}${fmt(comp.monthly_difference)}/mes)`;
      riskSpreadMoEl.className = `text-xs font-bold font-mono ${comp.monthly_difference >= 0 ? 'text-zinc-300' : 'text-rose-400'}`;
    }

    const riskVerdictEl = document.getElementById("riskSpreadVerdict");
    if (riskVerdictEl) riskVerdictEl.textContent = comp.verdict;

    const badgeEl = document.getElementById("bankComparisonBadge");
    const badgeTextEl = document.getElementById("bankComparisonBadgeText");
    const badgeIconEl = document.getElementById("bankComparisonIcon");

    if (badgeEl && badgeTextEl && badgeIconEl) {
      if (comp.verdict_color === "emerald") {
        badgeEl.className = "text-xs font-bold px-3 py-1.5 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center gap-1.5 self-start sm:self-auto";
        badgeIconEl.className = "fa-solid fa-shield-halved";
        badgeTextEl.textContent = "Negocio Supera al Banco";
      } else if (comp.verdict_color === "amber") {
        badgeEl.className = "text-xs font-bold px-3 py-1.5 rounded-lg bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center gap-1.5 self-start sm:self-auto";
        badgeIconEl.className = "fa-solid fa-scale-balanced";
        badgeTextEl.textContent = "Premio de Riesgo Ajustado";
      } else {
        badgeEl.className = "text-xs font-bold px-3 py-1.5 rounded-lg bg-rose-500/20 text-rose-300 border border-rose-500/30 flex items-center gap-1.5 self-start sm:self-auto";
        badgeIconEl.className = "fa-solid fa-triangle-exclamation";
        badgeTextEl.textContent = "Inviable: Banco Rinde Más";
      }
    }
  }

  // Render Scenarios Table
  renderScenariosTable(report.scenarios);

  // Render Pro Forma Table
  renderProFormaTable(report.yearly_cash_flows);

  // Render Charts
  renderCharts(report);

  // Render Financial Ratios 360° (Fase 4)
  if (report.ratios) {
    renderFinancialRatios(report.ratios);
  }

  // Render Síntesis Cuantitativa Automática (incorporada en los cálculos normales sin requerir IA)
  const rentEl = document.getElementById("autoQuantRentabilidadText");
  const costEl = document.getElementById("autoQuantCostosText");
  const riskEl = document.getElementById("autoQuantRiesgoText");
  if (rentEl) {
    const irrTxt = report.irr_pct !== null ? `${report.irr_pct.toFixed(1)}%` : "N/D";
    const pbTxt = report.payback_years !== null ? `${report.payback_years.toFixed(1)} años` : "mayor al horizonte";
    rentEl.innerHTML = report.npv >= 0
      ? `El modelo crea valor neto positivo por <strong>${fmt(report.npv)}</strong> con una TIR de <strong>${irrTxt}</strong> (superando el WACC de ${report.discount_rate_pct}%). La inversión inicial de ${fmt(report.initial_investment)} se recupera en <strong>${pbTxt}</strong> con un ROI anual promedio de <strong>${report.roi_annual_avg_pct.toFixed(1)}%</strong>.`
      : `Con los parámetros actuales el VAN es de <strong>${fmt(report.npv)}</strong> (TIR: ${irrTxt} vs WACC: ${report.discount_rate_pct}%). Se requiere ajustar margen unitario, volumen o inversión inicial para superar el costo de capital.`;
  }
  if (costEl && report.break_even) {
    const be = report.break_even;
    costEl.innerHTML = `Cada unidad vendida aporta <strong>${fmt(be.unit_contribution_margin)}</strong> (${be.contribution_margin_ratio_pct.toFixed(1)}% de margen de contribución). Necesitas vender <strong>${Math.round(be.monthly_breakeven_units).toLocaleString()} uds/mes</strong> (${fmt(be.monthly_breakeven_revenue)}/mes) para cubrir todos los gastos fijos y reservas.`;
  }
  if (riskEl && report.break_even) {
    const mos = report.break_even.margin_of_safety_pct;
    const pessNpv = report.scenarios?.pessimistic?.npv ?? 0;
    riskEl.innerHTML = `Tu margen de seguridad operativo es de <strong>${mos.toFixed(1)}%</strong> sobre el punto de equilibrio, absorbiendo una merma mensual estimada de <strong>${fmt(report.shrinkage_monthly_loss || 0)}</strong>. En un escenario pesimista (-20% ventas), el VAN sería de <strong>${fmt(pessNpv)}</strong>.`;
  }
}

function renderScenariosTable(scenarios) {
  const tbody = document.getElementById("scenariosTableBody");
  tbody.innerHTML = "";
  const fmt = (val) => new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN', maximumFractionDigits: 0 }).format(val);

  const list = [scenarios.pessimistic, scenarios.base, scenarios.optimistic];
  list.forEach(sc => {
    if (!sc) return;
    const tr = document.createElement("tr");
    const npvColor = sc.npv >= 0 ? "text-emerald-400 font-semibold" : "text-rose-400 font-semibold";
    tr.innerHTML = `
      <td class="py-2.5 px-3 font-bold">${sc.name}</td>
      <td class="py-2.5 px-3 text-zinc-400">${sc.description}</td>
      <td class="py-2.5 px-3 ${npvColor} font-mono">${fmt(sc.npv)}</td>
      <td class="py-2.5 px-3 font-mono">${sc.irr_pct !== null ? sc.irr_pct.toFixed(1) + '%' : 'N/D'}</td>
      <td class="py-2.5 px-3 font-mono">${sc.payback_years !== null ? sc.payback_years.toFixed(1) + ' años' : '> 5 años'}</td>
      <td class="py-2.5 px-3 font-mono font-semibold">${sc.roi_annual_avg_pct.toFixed(1)}%</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderProFormaTable(flows) {
  const tbody = document.getElementById("proformaTableBody");
  tbody.innerHTML = "";
  const fmt = (val) => new Intl.NumberFormat('es-MX', { maximumFractionDigits: 0 }).format(val);

  const rows = [
    { label: "Unidades Vendidas", key: "units_sold", isFmtNumber: true },
    { label: "Precio Promedio ($)", key: "price_unit" },
    { label: "Ingresos Brutos ($)", key: "revenue", bold: true },
    { label: "(-) Mermas, Robos y Riesgos ($)", key: "shrinkage_loss", color: "text-rose-400" },
    { label: "(=) Ingresos Netos ($)", key: "net_revenue", color: "text-zinc-200", bold: true },
    { label: "(-) Costos Variables ($)", key: "variable_costs" },
    { label: "(=) Margen Bruto ($)", key: "gross_margin", bold: true, color: "text-purple-300" },
    { label: "(-) Costos Fijos ($)", key: "fixed_costs" },
    { label: "(=) EBITDA ($)", key: "ebitda", bold: true },
    { label: "(-) Depreciación ($)", key: "depreciation" },
    { label: "(=) EBIT / Utilidad Operativa ($)", key: "ebit" },
    { label: "(-) Impuestos ($)", key: "taxes" },
    { label: "(=) Utilidad Neta ($)", key: "net_income", bold: true, color: "text-emerald-400" },
    { label: "Flujo de Caja Libre ($)", key: "free_cash_flow", bold: true, color: "text-cyan-400" },
    { label: "Flujo Descontado ($)", key: "discounted_cash_flow" },
    { label: "Flujo Acumulado ($)", key: "cumulative_cash_flow", bold: true }
  ];

  rows.forEach(r => {
    const tr = document.createElement("tr");
    let html = `<td class="text-left py-2 px-3 ${r.bold ? 'font-bold' : ''} ${r.color || 'text-zinc-300'}">${r.label}</td>`;
    flows.forEach(f => {
      const val = f[r.key];
      const displayVal = r.isFmtNumber ? fmt(val) : `$${fmt(val)}`;
      html += `<td class="py-2 px-3 ${r.bold ? 'font-bold' : ''} ${r.color || ''}">${displayVal}</td>`;
    });
    tr.innerHTML = html;
    tbody.appendChild(tr);
  });
}

// ----------------- CHARTS -----------------
function renderCharts(report) {
  const flows = report.yearly_cash_flows;
  const labels = flows.map(f => `Año ${f.year}`);
  const revenues = flows.map(f => f.revenue);
  const ebitda = flows.map(f => f.ebitda);
  const netIncomes = flows.map(f => f.net_income);
  const discFlows = flows.map(f => f.discounted_cash_flow);

  // 1. CASH FLOW CHART
  const ctx1 = document.getElementById("cashFlowChart").getContext("2d");
  if (cashFlowChartInstance) cashFlowChartInstance.destroy();

  cashFlowChartInstance = new Chart(ctx1, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Ingresos Totales',
          data: revenues,
          backgroundColor: 'rgba(99, 102, 241, 0.4)',
          borderColor: 'rgba(99, 102, 241, 1)',
          borderWidth: 1.5,
          borderRadius: 6,
          order: 2
        },
        {
          label: 'EBITDA',
          data: ebitda,
          backgroundColor: 'rgba(14, 165, 233, 0.5)',
          borderColor: 'rgba(14, 165, 233, 1)',
          borderWidth: 1.5,
          borderRadius: 6,
          order: 2
        },
        {
          label: 'Utilidad Neta',
          data: netIncomes,
          type: 'line',
          borderColor: '#10b981',
          backgroundColor: '#10b981',
          borderWidth: 3,
          pointRadius: 4,
          fill: false,
          tension: 0.3,
          order: 1
        },
        {
          label: 'Flujo Descontado',
          data: discFlows,
          type: 'line',
          borderColor: '#f59e0b',
          backgroundColor: '#f59e0b',
          borderWidth: 2,
          borderDash: [5, 5],
          pointRadius: 3,
          fill: false,
          tension: 0.3,
          order: 1
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: '#a1a1aa', font: { size: 10 } }
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: $${Math.round(ctx.parsed.y).toLocaleString()} MXN`
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: { color: '#a1a1aa', font: { size: 11 } }
        },
        y: {
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: {
            color: '#a1a1aa',
            font: { size: 10 },
            callback: (val) => `$${(val / 1000).toFixed(0)}k MXN`
          }
        }
      }
    }
  });

  // 2. BREAK EVEN CHART
  const ctx2 = document.getElementById("breakEvenChart").getContext("2d");
  if (breakEvenChartInstance) breakEvenChartInstance.destroy();

  const beUnits = report.break_even.monthly_breakeven_units;
  const currentUnits = flows[0].units_sold / 12.0;
  const maxUnits = Math.max(beUnits * 1.8, currentUnits * 1.5, 500);

  const price = flows[0].price_unit;
  const varCost = (flows[0].variable_costs / 12.0) / (flows[0].units_sold / 12.0);
  const fixedCost = flows[0].fixed_costs / 12.0;

  const stepCount = 10;
  const beLabels = [];
  const revPoints = [];
  const totalCostPoints = [];
  const fixedCostPoints = [];

  for (let i = 0; i <= stepCount; i++) {
    const u = (maxUnits / stepCount) * i;
    beLabels.push(Math.round(u));
    revPoints.push(u * price);
    totalCostPoints.push(fixedCost + (u * varCost));
    fixedCostPoints.push(fixedCost);
  }

  breakEvenChartInstance = new Chart(ctx2, {
    type: 'line',
    data: {
      labels: beLabels,
      datasets: [
        {
          label: 'Ingresos Mensuales',
          data: revPoints,
          borderColor: '#10b981',
          borderWidth: 2.5,
          pointRadius: 0,
          tension: 0.1
        },
        {
          label: 'Costos Totales',
          data: totalCostPoints,
          borderColor: '#ef4444',
          borderWidth: 2.5,
          pointRadius: 0,
          tension: 0.1
        },
        {
          label: 'Costos Fijos',
          data: fixedCostPoints,
          borderColor: '#a1a1aa',
          borderWidth: 1.5,
          borderDash: [6, 4],
          pointRadius: 0
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: '#a1a1aa', font: { size: 10 } }
        },
        tooltip: {
          callbacks: {
            title: (ctx) => `Volumen: ${ctx[0].label} unidades/mes`,
            label: (ctx) => `${ctx.dataset.label}: $${Math.round(ctx.parsed.y).toLocaleString()} MXN`
          }
        }
      },
      scales: {
        x: {
          title: { display: true, text: 'Unidades Vendidas / Mes', color: '#a1a1aa', font: { size: 10 } },
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: { color: '#a1a1aa', font: { size: 10 } }
        },
        y: {
          title: { display: true, text: 'Monto Mensual ($ MXN)', color: '#a1a1aa', font: { size: 10 } },
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: {
            color: '#a1a1aa',
            font: { size: 10 },
            callback: (val) => `$${(val / 1000).toFixed(0)}k MXN`
          }
        }
      }
    }
  });
}

// ----------------- RENDER STRATEGIC ADVICE (GEMINI) -----------------
function renderStrategicAdvice(advice, timestamp) {
  // Score Badge
  const scoreBadge = document.getElementById("viabilityScoreBadge");
  scoreBadge.classList.remove("hidden");
  scoreBadge.textContent = `Score IA: ${advice.viability_score}/100`;

  // Update Gemini Section Status & Appearance
  const sectionBadge = document.getElementById("geminiSectionStatusBadge");
  const sectionIconBox = document.getElementById("geminiSectionIconBox");
  const reportSection = document.getElementById("geminiReportSection");
  if (sectionBadge) {
    sectionBadge.textContent = "Análisis Activo";
    sectionBadge.className = "text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30";
  }
  if (sectionIconBox) {
    sectionIconBox.className = "w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-cyan-400 flex items-center justify-center text-white shadow";
  }
  if (reportSection) {
    reportSection.classList.add("glow-primary");
  }

  document.getElementById("geminiTimestampBadge").textContent = `Generado: ${timestamp}`;
  document.getElementById("geminiExecutiveSummary").innerHTML = advice.executive_summary.replace(/\n/g, '<br/>');
  document.getElementById("geminiLocationAnalysis").innerHTML = advice.location_analysis.replace(/\n/g, '<br/>');
  document.getElementById("geminiCompetitionAnalysis").innerHTML = advice.competition_analysis.replace(/\n/g, '<br/>');
  document.getElementById("geminiCostAnalysis").innerHTML = advice.cost_structure_analysis.replace(/\n/g, '<br/>');

  // Risks Table
  const risksTbody = document.getElementById("geminiRisksTableBody");
  risksTbody.innerHTML = "";
  (advice.risks_matrix || []).forEach(r => {
    const tr = document.createElement("tr");
    const severityColor = r.severity.toLowerCase().includes("alta") 
      ? "bg-rose-500/20 text-rose-300 border-rose-500/30"
      : (r.severity.toLowerCase().includes("media") ? "bg-amber-500/20 text-amber-300 border-amber-500/30" : "bg-emerald-500/20 text-emerald-300 border-emerald-500/30");

    tr.innerHTML = `
      <td class="py-2.5 px-3 font-semibold text-zinc-200">${r.category}</td>
      <td class="py-2.5 px-3 text-zinc-300">${r.risk}</td>
      <td class="py-2.5 px-3">
        <span class="px-2 py-0.5 rounded text-[10px] font-bold border ${severityColor}">${r.severity}</span>
      </td>
      <td class="py-2.5 px-3 text-zinc-300">${r.mitigation}</td>
    `;
    risksTbody.appendChild(tr);
  });

  // Action Plan
  const actionList = document.getElementById("geminiActionPlanList");
  actionList.innerHTML = "";
  (advice.action_plan_steps || []).forEach((step, idx) => {
    const li = document.createElement("li");
    li.className = "flex items-start gap-2 bg-zinc-950/60 p-2.5 rounded-lg border border-zinc-800";
    li.innerHTML = `
      <span class="w-5 h-5 rounded-full bg-purple-500/20 text-purple-400 font-bold flex items-center justify-center text-[10px] shrink-0 mt-0.5">${idx + 1}</span>
      <span>${step}</span>
    `;
    actionList.appendChild(li);
  });

  // Growth Tactics
  const growthList = document.getElementById("geminiGrowthList");
  growthList.innerHTML = "";
  (advice.growth_tactics || []).forEach((tac) => {
    const li = document.createElement("li");
    li.className = "flex items-start gap-2 bg-zinc-950/60 p-2.5 rounded-lg border border-zinc-800";
    li.innerHTML = `
      <i class="fa-solid fa-circle-check text-cyan-400 text-xs shrink-0 mt-1"></i>
      <span>${tac}</span>
    `;
    growthList.appendChild(li);
  });
}

function initEngineeringAndTrackerListeners() {
  // --- 1. PRESTUPUESTOS DE INVERSIÓN ---
  const addEqBtn = document.getElementById("addEqBtn");
  const equipmentList = document.getElementById("equipmentList");
  const genBudgetsBtn = document.getElementById("genBudgetsBtn");
  const budgetsLoader = document.getElementById("budgetsLoader");
  const budgetsOutput = document.getElementById("budgetsOutput");
  const budgetsGrid = document.getElementById("budgetsGrid");
  const budgetsSummary = document.getElementById("budgetsSummary");
  const useInvestmentBtn = document.getElementById("useInvestmentBtn");
  
  let selectedBudgetCost = 0;
  let selectedBudgetOption = null;
  let lastBudgetsData = null;
  let lastFlowchartData = null;
  let pendingMermaidCode = null;
  window.getSelectedBudgetOption = () => selectedBudgetOption;

  function invalidateBudgetsOutput() {
    lastBudgetsData = null;
    selectedBudgetCost = 0;
    selectedBudgetOption = null;
    if (budgetsGrid) budgetsGrid.innerHTML = "";
    if (budgetsSummary) budgetsSummary.textContent = "";
    budgetsOutput?.classList.add("hidden");
    useInvestmentBtn?.classList.add("hidden");
  }

  function invalidateFlowchartOutput() {
    lastFlowchartData = null;
    pendingMermaidCode = null;
    if (mermaidContainer) mermaidContainer.innerHTML = "";
    if (activitiesTable) activitiesTable.innerHTML = "";
    if (consumablesTable) consumablesTable.innerHTML = "";
    if (totalConsumablesCost) totalConsumablesCost.textContent = "$0";
    flowOutput?.classList.add("hidden");
  }
  window.invalidateBudgetsOutput = invalidateBudgetsOutput;
  window.invalidateFlowchartOutput = invalidateFlowchartOutput;

  function createEquipmentRow(item = {}) {
    const div = document.createElement("div");
    div.className = "flex gap-2 equipment-item mt-2";
    div.innerHTML = `
      <select class="eq-category w-1/4 bg-zinc-900 border border-zinc-700 rounded-lg px-2 py-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none"><option value="Maquinaria">Maquinaria</option><option value="Servicios">Servicios</option><option value="Empleados">Empleados</option></select><input type="text" placeholder="Ej: Equipo" class="eq-name w-1/3 bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none">
      <input type="text" placeholder="Especificaciones" class="eq-desc flex-1 bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none">
      <button type="button" class="text-rose-400 hover:text-rose-300 px-2" onclick="this.parentElement.remove(); if(window.invalidateBudgetsOutput) window.invalidateBudgetsOutput(); scheduleAutoSave();"><i class="fa-solid fa-xmark"></i></button>
    `;
    div.querySelector(".eq-category").value = item.category || "Maquinaria";
    div.querySelector(".eq-name").value = item.name || "";
    div.querySelector(".eq-desc").value = item.description || "";
    equipmentList.appendChild(div);
    return div;
  }

  addEqBtn?.addEventListener("click", () => {
    createEquipmentRow();
    invalidateBudgetsOutput();
    scheduleAutoSave();
  });

  // Autosave de las pestañas 1 y 2; si cambian los equipos, limpiar presupuestos desactualizados
  equipmentList?.addEventListener("input", () => {
    invalidateBudgetsOutput();
    scheduleAutoSave();
  });
  equipmentList?.addEventListener("change", () => {
    invalidateBudgetsOutput();
    scheduleAutoSave();
  });

  genBudgetsBtn?.addEventListener("click", async () => {
    const items = [];
    document.querySelectorAll(".equipment-item").forEach(item => {
      const category = item.querySelector(".eq-category").value;
      const name = item.querySelector(".eq-name").value.trim();
      const desc = item.querySelector(".eq-desc").value.trim();
      if(name) items.push({category, name, description: desc});
    });

    if(items.length === 0) {
      showToast("Añade al menos un equipo para cotizar presupuestos.", false);
      return;
    }

    const apiKey = getActiveGeminiApiKey();
    if (!hasServerApiKey && !apiKey) {
      showToast("Configura tu API Key de Google Gemini para generar presupuestos con IA.", false);
      document.getElementById("apiKeyModal")?.classList.remove("hidden");
      return;
    }

    const origBtnHtml = genBudgetsBtn.innerHTML;
    genBudgetsBtn.disabled = true;
    genBudgetsBtn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> <span>Cotizando 3 Presupuestos con IA...</span>`;
    budgetsOutput.classList.add("hidden");
    budgetsLoader.classList.remove("hidden");
    budgetsLoader.classList.add("flex");
    
    try {
      const headers = { "Content-Type": "application/json" };
      if(apiKey) headers["x-gemini-api-key"] = apiKey;

      const res = await fetch("/api/generate-budgets", {
        method: "POST",
        headers,
        body: JSON.stringify({
          items,
          custom_api_key: apiKey || null,
          gemini_model: getActiveGeminiModel()
        })
      });
      
      if(!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(formatApiError(errData) || `Error del servidor (${res.status})`);
      }
      const data = await res.json();
      
      renderBudgets(data);
      showToast("3 opciones de presupuesto generadas con Gemini AI.", true);
    } catch (e) {
      if (lastBudgetsData) budgetsOutput.classList.remove("hidden");
      showToast("Error al cotizar con IA: " + e.message, false);
    } finally {
      genBudgetsBtn.disabled = false;
      genBudgetsBtn.innerHTML = origBtnHtml;
      budgetsLoader.classList.add("hidden");
      budgetsLoader.classList.remove("flex");
    }
  });

  function renderBudgets(data) {
    lastBudgetsData = data;
    selectedBudgetCost = 0;
    selectedBudgetOption = null;
    useInvestmentBtn.classList.add("hidden");
    budgetsGrid.innerHTML = "";
    
    data.budgets.forEach(b => {
      let icon = "fa-star";
      let color = "text-purple-400";
      if(b.budget_type.toLowerCase().includes("econ")) { icon = "fa-piggy-bank"; color = "text-emerald-400"; }
      if(b.budget_type.toLowerCase().includes("prem") || b.budget_type.toLowerCase().includes("alt")) { icon = "fa-gem"; color = "text-amber-400"; }

      const detailsHtml = b.details.map(d => `<li class="text-[10px] text-zinc-300 mb-1 border-b border-zinc-800 pb-1">${d}</li>`).join('');

      const card = document.createElement("div");
      card.className = "bg-zinc-900 rounded-xl border border-zinc-800 p-4 relative cursor-pointer hover:border-emerald-500 transition group";
      card.innerHTML = `
        <div class="text-xs font-bold text-zinc-300 uppercase mb-2 flex items-center gap-1.5 ${color}">
          <i class="fa-solid ${icon}"></i> ${b.budget_type}
        </div>
        <div class="text-lg font-black text-white font-mono mb-3">$${b.total_cost.toLocaleString('es-MX')}</div>
        <ul class="list-none p-0 m-0">${detailsHtml}</ul>
        <div class="absolute inset-0 border-2 border-emerald-500 rounded-xl opacity-0 group-hover:opacity-10 pointer-events-none transition"></div>
      `;
      
      card.addEventListener("click", () => {
        document.querySelectorAll("#budgetsGrid > div").forEach(c => c.classList.remove("ring-2", "ring-emerald-500"));
        card.classList.add("ring-2", "ring-emerald-500");
        selectedBudgetCost = b.total_cost;
        selectedBudgetOption = b;
        useInvestmentBtn.classList.remove("hidden");
      });
      
      budgetsGrid.appendChild(card);
    });

    // Auto-seleccionar tarjeta estándar o coincidente con inversión actual
    const currentInv = parseFloat(document.getElementById("initialInvestment")?.value || 0);
    const cards = budgetsGrid.querySelectorAll(":scope > div");
    let matchedCard = null;
    let matchedBudget = null;
    data.budgets.forEach((b, idx) => {
      if (Math.abs(b.total_cost - currentInv) < 1) {
        matchedCard = cards[idx];
        matchedBudget = b;
      } else if (!matchedCard && (b.budget_type.toLowerCase().includes("están") || b.budget_type.toLowerCase().includes("estan"))) {
        matchedCard = cards[idx];
        matchedBudget = b;
      }
    });
    if (!matchedCard && cards.length > 0) {
      const idx = Math.min(1, cards.length - 1);
      matchedCard = cards[idx];
      matchedBudget = data.budgets[idx];
    }
    if (matchedCard && matchedBudget) {
      matchedCard.classList.add("ring-2", "ring-emerald-500");
      selectedBudgetCost = matchedBudget.total_cost;
      selectedBudgetOption = matchedBudget;
      useInvestmentBtn.classList.remove("hidden");
    }
    
    budgetsSummary.textContent = data.summary;
    budgetsOutput.classList.remove("hidden");
    scheduleAutoSave();
  }

  useInvestmentBtn?.addEventListener("click", async () => {
    const invInput = document.getElementById("initialInvestment");
    if (invInput) {
      invInput.value = selectedBudgetCost;
      invInput.removeAttribute("readonly");
      invInput.classList.remove("bg-zinc-800", "cursor-not-allowed");
    }
    updateSuggestedReserveHelper();
    updateBankAndShrinkageHelpers();
    scheduleAutoSave();
    await runQuickCalculation();

    // Sincronizar automáticamente la inversión y maquinaria del presupuesto con el ERP del Dueño
    if (typeof window.syncPlanToErpBaseline === "function") {
      await window.syncPlanToErpBaseline({ replaceAssets: true, silent: true });
    }

    const budgetName = selectedBudgetOption?.budget_type || "Seleccionado";
    showToast(`Presupuesto "${budgetName}" ($${selectedBudgetCost.toLocaleString('es-MX')}) cargado al modelo y sincronizado con el ERP.`, true);
    switchTab(5);
  });


  // --- 2. DIAGRAMA DE FLUJO Y ENERGÍA ---
  const genFlowchartBtn = document.getElementById("genFlowchartBtn");
  const processDesc = document.getElementById("processDesc");
  const flowLoader = document.getElementById("flowLoader");
  const flowOutput = document.getElementById("flowOutput");
  const mermaidContainer = document.getElementById("mermaidContainer");
  const activitiesTable = document.getElementById("activitiesTable");
  const consumablesTable = document.getElementById("consumablesTable");
  const totalConsumablesCost = document.getElementById("totalConsumablesCost");

  genFlowchartBtn?.addEventListener("click", async () => {
    const desc = processDesc.value.trim();
    if(!desc) {
      showToast("Describe el proceso operativo primero.", false);
      return;
    }

    const apiKey = getActiveGeminiApiKey();
    if (!hasServerApiKey && !apiKey) {
      showToast("Configura tu API Key de Google Gemini para generar el diagrama de procesos con IA.", false);
      document.getElementById("apiKeyModal")?.classList.remove("hidden");
      return;
    }

    const origFlowBtnHtml = genFlowchartBtn.innerHTML;
    genFlowchartBtn.disabled = true;
    genFlowchartBtn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> <span>Diseñando Proceso y Tabla Kw/h...</span>`;
    flowOutput.classList.add("hidden");
    flowLoader.classList.remove("hidden");
    flowLoader.classList.add("flex");
    
    try {
      const headers = { "Content-Type": "application/json" };
      if(apiKey) headers["x-gemini-api-key"] = apiKey;

      const res = await fetch("/api/generate-flowchart", {
        method: "POST",
        headers,
        body: JSON.stringify({
          process_description: desc,
          custom_api_key: apiKey || null,
          gemini_model: getActiveGeminiModel()
        })
      });
      
      if(!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(formatApiError(errData) || `Error del servidor (${res.status})`);
      }
      const data = await res.json();
      
      await renderFlowchart(data);
      showToast("Diagrama de procesos y tabla de suministros generados con IA.", true);
    } catch (e) {
      if (lastFlowchartData) flowOutput.classList.remove("hidden");
      showToast("Error al generar ingeniería de procesos: " + e.message, false);
    } finally {
      genFlowchartBtn.disabled = false;
      genFlowchartBtn.innerHTML = origFlowBtnHtml;
      flowLoader.classList.add("hidden");
      flowLoader.classList.remove("flex");
    }
  });

  function sanitizeMermaidCode(raw) {
    let code = String(raw || "").trim();
    if (code.startsWith("```mermaid")) code = code.substring(10);
    if (code.startsWith("```")) code = code.substring(3);
    if (code.endsWith("```")) code = code.substring(0, code.length - 3);
    code = code.trim();

    // Asegurar encabezado válido
    if (!/^(flowchart|graph)\s+(LR|TD|TB|RL|BT)/i.test(code)) {
      code = "flowchart LR\n" + code;
    }

    // Envolver etiquetas de nodos sin comillas en comillas dobles para que signos como ¿ ? ° ( ) / no rompan Mermaid
    // 1. ([texto]) -> (["texto"])
    code = code.replace(/(\b[A-Za-z0-9_]+)\(\[\s*(?!"|')([^\]]+?)\s*\]\)/g, (_, id, lbl) => `${id}(["${lbl.replace(/"/g, "'")}"])`);
    // 2. [(texto)] -> [("texto")]
    code = code.replace(/(\b[A-Za-z0-9_]+)\[\(\s*(?!"|')([^\)]+?)\s*\)\]/g, (_, id, lbl) => `${id}[("${lbl.replace(/"/g, "'")}")]`);
    // 3. ((texto)) -> (("texto"))
    code = code.replace(/(\b[A-Za-z0-9_]+)\(\(\s*(?!"|')([^\)]+?)\s*\)\)/g, (_, id, lbl) => `${id}(("${lbl.replace(/"/g, "'")}"))`);
    // 4. {texto} -> {"texto"}
    code = code.replace(/(\b[A-Za-z0-9_]+)\{\s*(?!"|')([^\}]+?)\s*\}/g, (_, id, lbl) => `${id}{"${lbl.replace(/"/g, "'")}"}`);
    // 5. [texto] -> ["texto"] (evitando tocar [("../..")] ya procesados)
    code = code.replace(/(\b[A-Za-z0-9_]+)\[\s*(?!"|'|\()([^\]]+?)\s*\]/g, (_, id, lbl) => `${id}["${lbl.replace(/"/g, "'")}"]`);

    return code;
  }

  function renderFallbackHtmlFlowchart(code) {
    // Extraer pasos desde lastFlowchartData.activities o desde los nodos del código Mermaid
    const acts = Array.isArray(lastFlowchartData?.activities) ? lastFlowchartData.activities : [];
    const nodes = [];
    if (acts.length > 0) {
      nodes.push({ type: "terminal", label: "Inicio" });
      acts.forEach((a) => {
        const isDecision = /\?|¿|verifica|control|calidad|ok|correct/i.test(a.activity);
        const isStorage = /almac[eé]n|reposo|inventario|base de datos|insumo/i.test(a.activity);
        nodes.push({
          type: isDecision ? "decision" : (isStorage ? "storage" : "process"),
          label: a.activity,
          sub: a.time_estimate || ""
        });
      });
      nodes.push({ type: "terminal", label: "Fin" });
    } else {
      const regex = /\b([A-Za-z0-9_]+)\s*(?:\(\[|\[|\{|\(\()\s*"?([^"\]\}\)]+)"?/g;
      const seen = new Set();
      let m;
      while ((m = regex.exec(code)) !== null) {
        if (!seen.has(m[1])) {
          seen.add(m[1]);
          nodes.push({ type: "process", label: m[2].trim(), sub: "" });
        }
      }
    }

    const htmlItems = nodes.map((n, idx) => {
      let shapeClass = "rounded-xl border-[#c5a059] bg-zinc-900 text-zinc-100";
      let badge = "Operación";
      if (n.type === "terminal") {
        shapeClass = "rounded-full border-emerald-500/70 bg-emerald-950/30 text-emerald-300";
        badge = idx === 0 ? "Inicio" : "Cierre";
      } else if (n.type === "decision") {
        shapeClass = "rounded-xl border-amber-400/80 bg-amber-950/20 text-amber-200 ring-1 ring-amber-500/20";
        badge = "Decisión / Control";
      } else if (n.type === "storage") {
        shapeClass = "rounded-xl border-cyan-500/60 bg-zinc-900/90 text-zinc-100";
        badge = "Almacenamiento";
      }
      const arrow = idx < nodes.length - 1
        ? `<div class="flex items-center justify-center text-[#d4b26f] px-1"><i class="fa-solid fa-arrow-right text-sm"></i></div>`
        : "";
      return `
        <div class="flex items-center">
          <div class="border-2 ${shapeClass} px-3.5 py-2.5 min-w-[135px] max-w-[190px] text-center shadow-md">
            <div class="text-[9px] uppercase tracking-wider font-mono opacity-75 mb-0.5">${badge}</div>
            <div class="text-xs font-bold leading-snug">${escapeHtml(n.label)}</div>
            ${n.sub ? `<div class="text-[10px] font-mono text-[#d4b26f] mt-1">${escapeHtml(n.sub)}</div>` : ""}
          </div>
          ${arrow}
        </div>
      `;
    }).join("");

    mermaidContainer.innerHTML = `
      <div class="w-full overflow-x-auto py-3 px-2">
        <div class="inline-flex items-center gap-1 min-w-max mx-auto">${htmlItems}</div>
      </div>
    `;
  }

  let currentFlowZoomPct = 125;
  let baseFlowSvgWidth = 1250;
  let baseFlowSvgHeight = 320;
  let isFlowFullscreen = false;

  function applyFlowchartZoom(newZoomPct) {
    currentFlowZoomPct = Math.max(50, Math.min(350, Math.round(newZoomPct)));
    const labelEl = document.getElementById("flowZoomLabel");
    if (labelEl) labelEl.textContent = `${currentFlowZoomPct}%`;

    const scale = currentFlowZoomPct / 100;
    const svgEl = mermaidContainer?.querySelector("svg");
    if (svgEl) {
      const scaledW = Math.round(baseFlowSvgWidth * scale);
      const scaledH = Math.round(baseFlowSvgHeight * scale);
      svgEl.style.maxWidth = "none";
      svgEl.style.maxHeight = "none";
      svgEl.style.width = `${scaledW}px`;
      svgEl.style.height = `${scaledH}px`;
      svgEl.style.margin = "0";
      svgEl.style.display = "block";
    } else if (mermaidContainer?.firstElementChild) {
      mermaidContainer.firstElementChild.style.zoom = `${currentFlowZoomPct}%`;
      mermaidContainer.firstElementChild.style.transformOrigin = "top left";
    }
  }

  function initFlowchartZoomAndPanControls() {
    const zoomInBtn = document.getElementById("flowZoomInBtn");
    const zoomOutBtn = document.getElementById("flowZoomOutBtn");
    const zoomResetBtn = document.getElementById("flowZoomResetBtn");
    const fullscreenBtn = document.getElementById("flowFullscreenBtn");
    const viewport = document.getElementById("mermaidViewport");
    const cardWrapper = document.getElementById("flowchartCardWrapper");

    zoomInBtn?.addEventListener("click", () => applyFlowchartZoom(currentFlowZoomPct + 25));
    zoomOutBtn?.addEventListener("click", () => applyFlowchartZoom(currentFlowZoomPct - 25));
    zoomResetBtn?.addEventListener("click", () => {
      applyFlowchartZoom(125);
      if (viewport) {
        viewport.scrollLeft = 0;
        viewport.scrollTop = 0;
      }
    });

    fullscreenBtn?.addEventListener("click", () => {
      if (!cardWrapper || !viewport) return;
      isFlowFullscreen = !isFlowFullscreen;
      if (isFlowFullscreen) {
        cardWrapper.classList.add("fixed", "inset-4", "z-[120]", "flex", "flex-col", "shadow-2xl", "border-[#c5a059]");
        viewport.classList.remove("max-h-[600px]");
        viewport.classList.add("flex-1", "max-h-none");
        fullscreenBtn.innerHTML = `<i class="fa-solid fa-compress"></i> <span class="hidden sm:inline">Salir</span>`;
        applyFlowchartZoom(Math.max(currentFlowZoomPct, 150));
      } else {
        cardWrapper.classList.remove("fixed", "inset-4", "z-[120]", "flex", "flex-col", "shadow-2xl", "border-[#c5a059]");
        viewport.classList.remove("flex-1", "max-h-none");
        viewport.classList.add("max-h-[600px]");
        fullscreenBtn.innerHTML = `<i class="fa-solid fa-expand"></i> <span class="hidden sm:inline">Expandir</span>`;
      }
    });

    if (viewport) {
      // Zoom con rueda del ratón al mantener Ctrl o Alt, o botones
      viewport.addEventListener("wheel", (e) => {
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault();
          const delta = e.deltaY < 0 ? 20 : -20;
          applyFlowchartZoom(currentFlowZoomPct + delta);
        }
      }, { passive: false });

      // Arrastrar con el mouse (Panning) en todas las direcciones (arriba, abajo, izquierda, derecha)
      let isDragging = false;
      let startClientX = 0;
      let startClientY = 0;
      let startScrollLeft = 0;
      let startScrollTop = 0;

      viewport.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        isDragging = true;
        startClientX = e.clientX;
        startClientY = e.clientY;
        startScrollLeft = viewport.scrollLeft;
        startScrollTop = viewport.scrollTop;
      });
      window.addEventListener("mouseup", () => {
        isDragging = false;
      });
      window.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        e.preventDefault();
        const dx = e.clientX - startClientX;
        const dy = e.clientY - startClientY;
        viewport.scrollLeft = startScrollLeft - dx * 1.25;
        viewport.scrollTop = startScrollTop - dy * 1.25;
      });
    }
  }
  initFlowchartZoomAndPanControls();

  async function drawMermaid(rawCode, retryCount = 0) {
    const code = sanitizeMermaidCode(rawCode);
    pendingMermaidCode = code;

    if (!window.mermaid) {
      if (retryCount < 15) {
        setTimeout(() => drawMermaid(code, retryCount + 1), 200);
        return;
      }
      renderFallbackHtmlFlowchart(code);
      return;
    }

    try {
      const renderId = "mermaidSvg_" + Date.now() + "_" + Math.floor(Math.random() * 1000);
      const { svg } = await window.mermaid.render(renderId, code);
      mermaidContainer.innerHTML = svg;
      pendingMermaidCode = code;
      const svgEl = mermaidContainer.querySelector("svg");
      if (svgEl) {
        const vb = (svgEl.getAttribute("viewBox") || "").split(/\s+/).map(Number);
        const naturalW = vb.length === 4 && vb[2] > 0 ? vb[2] : 1000;
        const naturalH = vb.length === 4 && vb[3] > 0 ? vb[3] : 260;
        const aspect = naturalH / naturalW;
        baseFlowSvgWidth = Math.max(naturalW * 1.25, 1100);
        baseFlowSvgHeight = Math.max(Math.round(baseFlowSvgWidth * aspect), 220);
        svgEl.removeAttribute("width");
        svgEl.removeAttribute("height");
        applyFlowchartZoom(currentFlowZoomPct);
        const viewport = document.getElementById("mermaidViewport");
        if (viewport) {
          viewport.scrollTop = 0;
          viewport.scrollLeft = 0;
        }
      }
    } catch (e) {
      console.warn("Mermaid render fallback activado:", e);
      renderFallbackHtmlFlowchart(code);
      applyFlowchartZoom(currentFlowZoomPct);
    }
  }

  window.renderPendingMermaid = () => {
    if (pendingMermaidCode) drawMermaid(pendingMermaidCode);
  };

  async function renderFlowchart(data) {
    lastFlowchartData = data;
    const code = sanitizeMermaidCode(data.mermaid_code || "");
    pendingMermaidCode = code;
    flowOutput.classList.remove("hidden");

    const tab2 = document.getElementById("tab2");
    if (!tab2 || !tab2.classList.contains("hidden")) {
      await drawMermaid(code);
    } else {
      // Incluso si tab2 está oculta, renderizar con mermaid.render para que esté listo al abrir o imprimir PDF
      await drawMermaid(code);
    }

    // Activities
    activitiesTable.innerHTML = "";
    data.activities.forEach(a => {
      activitiesTable.innerHTML += `
        <tr>
          <td class="p-2 text-center text-zinc-400 font-bold">${a.step_number}</td>
          <td class="p-2">
            <div class="font-medium text-zinc-200">${a.activity}</div>
            <div class="text-[10px] text-zinc-500">${a.movements}</div>
          </td>
          <td class="p-2 font-mono text-cyan-400">${a.time_estimate}</td>
        </tr>
      `;
    });

    // Energy
    consumablesTable.innerHTML = "";
    data.consumables_table.forEach(e => {
      consumablesTable.innerHTML += `
        <tr>
          <td class="p-2 font-medium text-zinc-200">${e.item_name}</td>
          <td class="p-2 text-right font-mono">${e.quantity_monthly}</td>
          <td class="p-2 text-right font-mono text-amber-300">$${e.monthly_cost_estimate.toLocaleString('es-MX')}</td>
        </tr>
      `;
    });
    totalConsumablesCost.textContent = `$${data.total_monthly_consumables_cost.toLocaleString('es-MX')}`;

    flowOutput.classList.remove("hidden");
    scheduleAutoSave();
  }

  processDesc?.addEventListener("input", () => {
    invalidateFlowchartOutput();
    scheduleAutoSave();
  });

  // --- Estado de Presupuestos/Procesos para plantillas y proyectos guardados ---
  window.getEngineeringData = () => {
    const equipment_items = [];
    document.querySelectorAll("#equipmentList .equipment-item").forEach(row => {
      const name = row.querySelector(".eq-name").value.trim();
      const description = row.querySelector(".eq-desc").value.trim();
      if (name || description) {
        equipment_items.push({ category: row.querySelector(".eq-category").value, name, description });
      }
    });
    return {
      equipment_items,
      process_description: processDesc.value.trim(),
      budgets: lastBudgetsData,
      flowchart: lastFlowchartData
    };
  };

  window.applyEngineeringData = (eng) => {
    if (!eng) return;
    // Pestaña 3: renglones de equipo
    equipmentList.innerHTML = "";
    const items = Array.isArray(eng.equipment_items) ? eng.equipment_items : [];
    if (items.length === 0) {
      createEquipmentRow().classList.remove("mt-2");
    } else {
      items.forEach((it, i) => {
        const row = createEquipmentRow(it);
        if (i === 0) row.classList.remove("mt-2");
      });
    }
    // Resultados de presupuestos: descartar predefinidos estáticos de plantilla ("Plantilla de ejemplo")
    const isRealBudgets = eng.budgets && Array.isArray(eng.budgets.budgets) && eng.budgets.budgets.length > 0 && eng.budgets.generated_at !== "Plantilla de ejemplo";
    if (isRealBudgets) {
      renderBudgets(eng.budgets);
    } else {
      invalidateBudgetsOutput();
    }
    // Pestaña 2: proceso y diagrama: descartar predefinidos estáticos de plantilla ("Plantilla de ejemplo")
    processDesc.value = eng.process_description || "";
    const isRealFlowchart = eng.flowchart && eng.flowchart.mermaid_code && eng.flowchart.generated_at !== "Plantilla de ejemplo";
    if (isRealFlowchart) {
      renderFlowchart(eng.flowchart);
    } else {
      invalidateFlowchartOutput();
    }
  };


  const generateKeyBtn = document.getElementById("generateKeyBtn");
  const exportKeyInput = document.getElementById("exportKeyInput");
  const copyKeyBtn = document.getElementById("copyKeyBtn");
  
  if (generateKeyBtn) {
    generateKeyBtn.addEventListener("click", async () => {
      const origHtml = generateKeyBtn.innerHTML;
      generateKeyBtn.disabled = true;
      generateKeyBtn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin text-xs"></i><span>Generando...</span>`;
      try {
        const res = await window.syncPlanToErpBaseline({ replaceAssets: true, silent: false });
        if (res && res.project_key && exportKeyInput) {
          exportKeyInput.value = res.project_key;
        }
      } catch (err) {
        showToast(err.message || "Error al generar clave de proyecto", false);
      } finally {
        generateKeyBtn.disabled = false;
        generateKeyBtn.innerHTML = origHtml;
      }
    });
  }

  if (copyKeyBtn) {
    copyKeyBtn.addEventListener("click", () => {
      if (exportKeyInput && exportKeyInput.value) {
        navigator.clipboard.writeText(exportKeyInput.value);
        showToast(`Clave ${exportKeyInput.value} copiada al portapapeles`, true);
      }
    });
  }

}


// ----------------- RAZONES FINANCIERAS 360° (FASE 4) -----------------
function renderFinancialRatios(ratios) {
  const container = document.getElementById("financialRatiosGrid");
  if (!container) return;
  container.innerHTML = "";

  if (!ratios || !ratios.items || ratios.items.length === 0) {
    container.innerHTML = `
      <div class="col-span-full text-center py-6 text-zinc-500 text-xs">
        <i class="fa-solid fa-calculator mb-1 text-lg"></i>
        <p>No se han calculado razones financieras para este escenario.</p>
      </div>`;
    return;
  }

  const categoryIcons = {
    "Liquidez": "fa-water",
    "Rentabilidad": "fa-chart-line",
    "Eficiencia": "fa-arrows-rotate",
    "Solvencia": "fa-shield-halved"
  };

  ratios.items.forEach(item => {
    const icon = categoryIcons[item.category] || "fa-scale-balanced";
    
    let badgeStyle = "bg-emerald-500/20 text-emerald-300 border-emerald-500/30";
    let valStyle = "text-emerald-400";
    let cardBorder = "border-zinc-800 hover:border-emerald-500/40";

    if (item.status_color === "blue") {
      badgeStyle = "bg-blue-500/20 text-blue-300 border-blue-500/30";
      valStyle = "text-blue-400";
      cardBorder = "border-zinc-800 hover:border-blue-500/40";
    } else if (item.status_color === "amber") {
      badgeStyle = "bg-amber-500/20 text-amber-300 border-amber-500/30";
      valStyle = "text-amber-400";
      cardBorder = "border-zinc-800 hover:border-amber-500/40";
    } else if (item.status_color === "rose") {
      badgeStyle = "bg-rose-500/20 text-rose-300 border-rose-500/30";
      valStyle = "text-rose-400";
      cardBorder = "border-zinc-800 hover:border-rose-500/40";
    }

    let formattedVal = "";
    if (item.unit === "%") {
      formattedVal = `${item.value.toFixed(1)}%`;
    } else if (item.unit === "MXN") {
      formattedVal = new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN', maximumFractionDigits: 0 }).format(item.value);
    } else if (item.unit === "días") {
      formattedVal = `${Math.round(item.value)} días`;
    } else if (item.unit === "veces/año" || item.unit === "x") {
      formattedVal = `${item.value.toFixed(2)}${item.unit === 'x' ? 'x' : ' v/a'}`;
    } else {
      formattedVal = `${item.value} ${item.unit}`;
    }

    const card = document.createElement("div");
    card.className = `p-4 rounded-xl bg-zinc-900/90 border ${cardBorder} flex flex-col justify-between transition shadow-sm`;
    card.innerHTML = `
      <div>
        <div class="flex items-center justify-between mb-2">
          <span class="text-[11px] font-semibold text-zinc-400 flex items-center gap-1.5">
            <i class="fa-solid ${icon} text-zinc-500"></i> ${item.category}
          </span>
          <span class="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${badgeStyle}">
            ${item.status}
          </span>
        </div>
        <div class="text-sm font-bold text-white mb-1">${item.name}</div>
        <div class="flex items-baseline gap-2 mb-2">
          <span class="text-2xl font-black font-mono ${valStyle}">${formattedVal}</span>
          <span class="text-[11px] text-zinc-500 font-mono">Meta: ${item.benchmark}</span>
        </div>
      </div>
      <p class="text-xs text-zinc-400 mt-2 pt-2 border-t border-zinc-800/80 leading-relaxed">
        ${item.interpretation}
      </p>
    `;
    container.appendChild(card);
  });
}

// ----------------- GEOLOCALIZACIÓN Y SUGERENCIAS DE ADQUISICIÓN (FASE 4) -----------------
async function openGeoAcquisitionModal() {
  const modal = document.getElementById("geoAcquisitionModal");
  const content = document.getElementById("geoModalContent");
  const badge = document.getElementById("geoModalBadge");
  const subtitle = document.getElementById("geoModalSubtitle");
  if (!modal || !content) return;

  modal.classList.remove("hidden");
  modal.classList.add("flex");

  content.innerHTML = `
    <div class="flex flex-col items-center justify-center py-12 text-center space-y-4">
      <div class="w-12 h-12 rounded-full border-4 border-purple-500/20 border-t-purple-500 animate-spin"></div>
      <div>
        <h4 class="text-sm font-bold text-white">Analizando Cadena de Suministro Territorial...</h4>
        <p class="text-xs text-zinc-400 mt-1">Evaluando geolocalización, fletes, hubs logísticos y ventajas de compra local vs. importación.</p>
      </div>
    </div>
  `;

  const state = document.getElementById("geoState")?.value || "Ciudad de México";
  const sector = document.getElementById("sectorSelect")?.value || "Comercio al por menor (Retail)";
  const branch = document.getElementById("businessType")?.value || "Comercio / Servicios";
  const activity = document.getElementById("economicActivity")?.value || "";
  const municipality = document.getElementById("geoMunicipality")?.value || "";
  const zoneType = document.getElementById("geoZoneType")?.value || "Corredor comercial";
  const name = document.getElementById("businessName")?.value || "Mi Negocio";
  const description = document.getElementById("businessDescription")?.value || "";
  const targetMarket = document.getElementById("targetMarket")?.value || "";
  const location = document.getElementById("location")?.value || "";
  const competitiveAdvantage = document.getElementById("competitiveAdvantage")?.value || "";

  if (badge) badge.textContent = `${state} • ${sector.split(' ')[0]}`;
  if (subtitle) subtitle.textContent = `Estrategia de abastecimiento y adquisición para ${branch} en ${state}`;

  const activeKey = getActiveGeminiApiKey();
  const activeModel = getActiveGeminiModel();

  const payload = {
    business: {
      name,
      business_type: branch,
      description,
      target_market: targetMarket,
      location,
      competitive_advantage: competitiveAdvantage,
      sector,
      commercial_branch: branch,
      economic_activity: activity,
      state,
      municipality,
      zone_type: zoneType
    },
    custom_api_key: activeKey || null,
    gemini_model: activeModel
  };

  try {
    const headers = { "Content-Type": "application/json" };
    if (activeKey) headers["X-Gemini-API-Key"] = activeKey;

    const res = await fetch("/api/geo/acquisition-suggestions", {
      method: "POST",
      headers,
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Error del servidor (${res.status})`);
    }

    const data = await res.json();
    renderGeoModalContent(data);
  } catch (err) {
    content.innerHTML = `
      <div class="p-6 rounded-xl bg-rose-500/10 border border-rose-500/30 text-center space-y-3">
        <i class="fa-solid fa-triangle-exclamation text-rose-400 text-2xl"></i>
        <h4 class="text-sm font-bold text-white">No se pudieron cargar las sugerencias de adquisición</h4>
        <p class="text-xs text-rose-300">${err.message || "Error al conectar con el servicio de geolocalización."}</p>
        <button type="button" onclick="openGeoAcquisitionModal()" class="px-3.5 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold transition">
          Reintentar
        </button>
      </div>
    `;
  }
}

function renderGeoModalContent(data) {
  const content = document.getElementById("geoModalContent");
  if (!content) return;

  let productsRows = "";
  if (data.recommended_key_products && data.recommended_key_products.length > 0) {
    productsRows = data.recommended_key_products.map(p => {
      let sourceBadge = "bg-blue-500/20 text-blue-300 border-blue-500/30";
      if (p.suggested_source.includes("Importación")) {
        sourceBadge = "bg-amber-500/20 text-amber-300 border-amber-500/30";
      } else if (p.suggested_source.includes("Local")) {
        sourceBadge = "bg-emerald-500/20 text-emerald-300 border-emerald-500/30";
      }

      return `
        <tr class="border-b border-zinc-800 hover:bg-zinc-800/40 transition">
          <td class="py-3 px-3">
            <div class="font-bold text-zinc-100">${p.name}</div>
            <div class="text-[11px] text-zinc-400">${p.category}</div>
          </td>
          <td class="py-3 px-3 text-center font-mono font-bold text-emerald-400">
            ${p.target_margin_pct.toFixed(0)}%
          </td>
          <td class="py-3 px-3 text-center">
            <span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-300 border border-zinc-700">
              ${p.turnover_speed}
            </span>
          </td>
          <td class="py-3 px-3 text-xs text-zinc-300 leading-snug">
            ${p.local_advantage}
          </td>
          <td class="py-3 px-3 text-right">
            <span class="text-[10px] font-bold px-2.5 py-1 rounded-lg border ${sourceBadge} whitespace-nowrap">
              ${p.suggested_source}
            </span>
          </td>
        </tr>
      `;
    }).join("");
  } else {
    productsRows = `<tr><td colspan="5" class="py-4 text-center text-xs text-zinc-500">No hay productos sugeridos.</td></tr>`;
  }

  let calendarCards = "";
  if (data.seasonal_buying_calendar && data.seasonal_buying_calendar.length > 0) {
    calendarCards = data.seasonal_buying_calendar.map(c => `
      <div class="p-3.5 rounded-xl bg-zinc-950/60 border border-zinc-800 flex flex-col justify-between">
        <div>
          <div class="flex items-center justify-between mb-1.5">
            <span class="text-xs font-black text-purple-300">${c.season_period}</span>
            <span class="text-[10px] font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
              ${c.discount_opportunity}
            </span>
          </div>
          <div class="text-xs font-bold text-white mb-1">${c.recommended_focus}</div>
          <p class="text-[11px] text-zinc-400 leading-relaxed">${c.action}</p>
        </div>
      </div>
    `).join("");
  }

  content.innerHTML = `
    <!-- Top verdicts -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="p-4 rounded-xl bg-zinc-950/60 border border-purple-500/30">
        <div class="flex items-center gap-2 text-purple-400 font-bold text-xs uppercase tracking-wider mb-2">
          <i class="fa-solid fa-map-location-dot"></i>
          <span>Estrategia Regional de Abastecimiento</span>
        </div>
        <p class="text-xs text-zinc-200 leading-relaxed">${data.regional_supply_strategy}</p>
      </div>

      <div class="p-4 rounded-xl bg-zinc-950/60 border border-emerald-500/30">
        <div class="flex items-center gap-2 text-emerald-400 font-bold text-xs uppercase tracking-wider mb-2">
          <i class="fa-solid fa-scale-balanced"></i>
          <span>Veredicto: Abastecimiento Local vs. Importación</span>
        </div>
        <p class="text-xs text-zinc-200 leading-relaxed">${data.local_vs_import_verdict}</p>
      </div>
    </div>

    <!-- Middle Logistics & Pricing Insights -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="p-4 rounded-xl bg-zinc-950/40 border border-zinc-800">
        <div class="flex items-center gap-2 text-amber-400 font-bold text-xs uppercase tracking-wider mb-2">
          <i class="fa-solid fa-truck-fast"></i>
          <span>Logística, Fletes y Hubs de Distribución</span>
        </div>
        <p class="text-xs text-zinc-300 leading-relaxed">${data.logistics_and_freight_insights}</p>
      </div>

      <div class="p-4 rounded-xl bg-zinc-950/40 border border-zinc-800">
        <div class="flex items-center gap-2 text-purple-400 font-bold text-xs uppercase tracking-wider mb-2">
          <i class="fa-solid fa-tags"></i>
          <span>Competitividad y Políticas de Precios Locales</span>
        </div>
        <p class="text-xs text-zinc-300 leading-relaxed">${data.local_competitive_pricing}</p>
      </div>
    </div>

    <!-- Key Products Table -->
    <div class="glass-panel p-4 rounded-xl border border-zinc-800">
      <div class="flex items-center justify-between mb-3">
        <h4 class="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
          <i class="fa-solid fa-boxes-stacked text-purple-400"></i>
          <span>Productos Clave Sugeridos para Adquisición (${data.sector})</span>
        </h4>
        <span class="text-[10px] text-zinc-400">Márgenes y Rotación Esperada</span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-left border-collapse text-xs">
          <thead>
            <tr class="border-b border-zinc-800 text-[11px] font-semibold text-zinc-400 uppercase">
              <th class="py-2 px-3">Producto / Especialidad</th>
              <th class="py-2 px-3 text-center">Margen Meta</th>
              <th class="py-2 px-3 text-center">Rotación</th>
              <th class="py-2 px-3">Ventaja Geográfica</th>
              <th class="py-2 px-3 text-right">Fuente de Compra</th>
            </tr>
          </thead>
          <tbody>
            ${productsRows}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Seasonal Buying Calendar -->
    <div class="glass-panel p-4 rounded-xl border border-zinc-800">
      <div class="flex items-center justify-between mb-3">
        <h4 class="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
          <i class="fa-solid fa-calendar-days text-amber-400"></i>
          <span>Calendario Estacional de Compras y Negociación</span>
        </h4>
        <span class="text-[10px] text-zinc-400">Optimización de Inventario por Temporalidad</span>
      </div>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        ${calendarCards}
      </div>
    </div>
  `;
}


// ----------------- EXPORTACIÓN DE MODELO FINANCIERO A EXCEL / CSV (FASE 5) -----------------
function exportFinancialReportToCsv() {
  if (!currentFinancialReport) {
    showToast("Primero calcula o carga un reporte financiero para exportar.", false);
    return;
  }

  const r = currentFinancialReport;
  const b = getFormData().business;
  const f = getFormData().financials;

  const now = new Date();
  const dateStr = now.toLocaleDateString("es-MX", { year: "numeric", month: "2-digit", day: "2-digit" });
  const timeStr = now.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });

  const escapeCsv = (str) => {
    if (str === null || str === undefined) return '""';
    const s = String(str).replace(/"/g, '""');
    return `"${s}"`;
  };

  const rows = [];
  rows.push(["ECONOMETRICS AI - MODELO FINANCIERO Y EVALUACIÓN DE PROYECTO 360°"]);
  rows.push(["Fecha y Hora de Emisión", `${dateStr} ${timeStr}`]);
  rows.push(["Dictamen de Viabilidad Global", r.viability_status]);
  rows.push([]);

  rows.push(["1. IDENTIDAD DEL NEGOCIO Y GEOLOCALIZACIÓN"]);
  rows.push(["Nombre del Proyecto / Negocio", b.name]);
  rows.push(["Sector Económico", b.sector]);
  rows.push(["Giro Comercial Específico", b.business_type]);
  rows.push(["Actividad Económica", b.economic_activity || "No especificada"]);
  rows.push(["Entidad Federativa (Estado)", b.state]);
  rows.push(["Municipio / Alcaldía", b.municipality || "No especificada"]);
  rows.push(["Tipo de Zona Comercial", b.zone_type]);
  rows.push(["Ubicación Detallada", b.location]);
  rows.push(["Ventaja Competitiva / Moat", b.competitive_advantage || "No especificada"]);
  rows.push([]);

  rows.push(["2. PARÁMETROS OPERATIVOS Y FINANCIEROS CLAVE"]);
  rows.push(["Inversión Inicial Total (MXN)", f.initial_investment]);
  rows.push(["Precio de Venta Promedio (MXN)", f.monthly_price]);
  rows.push(["Demanda Estimada Mensual (unidades)", f.monthly_units]);
  rows.push(["Costo Variable Unitario (MXN)", f.unit_variable_cost]);
  rows.push(["Costos Fijos Operativos Mensuales (MXN)", f.monthly_fixed_costs]);
  rows.push(["Fondo Mensual Mantenimiento/Capex (MXN)", f.monthly_maintenance_cost]);
  rows.push(["Tasa de Descuento Anual / WACC (%)", f.discount_rate_pct]);
  rows.push(["Tasa Pasiva Libre de Riesgo CETES/Banco (%)", f.bank_risk_free_rate_pct]);
  rows.push(["Tasa de Mermas, Robos y Desperdicios (%)", f.shrinkage_risk_loss_pct]);
  rows.push(["Crecimiento Anual de Ventas (%)", f.annual_sales_growth_pct]);
  rows.push(["Inflación Anual Proyectada (%)", f.annual_inflation_pct]);
  rows.push(["Tasa Impositiva ISR (%)", f.tax_rate_pct]);
  rows.push(["Años de Depreciación de Activos", f.depreciation_years]);
  rows.push([]);

  // Catálogo Multiproducto y Precios Mixtos
  const catalog = typeof getMultiProductCatalogData === "function" ? getMultiProductCatalogData() : [];
  if (Array.isArray(catalog) && catalog.length > 0) {
    rows.push(["2.1 CATÁLOGO DE PRODUCTOS / SERVICIOS (MEZCLA DE VENTAS)"]);
    rows.push(["Producto / Servicio", "Precio Venta (MXN)", "Costo Directo (MXN)", "Demanda Mes (Uds)", "Margen Unitario ($)", "Margen Unitario (%)", "Facturación Mensual (MXN)"]);
    catalog.forEach(item => {
      const p = parseFloat(item.price || 0);
      const c = parseFloat(item.cost || 0);
      const u = parseFloat(item.units || 0);
      const m = p - c;
      const mPct = p > 0 ? (m / p * 100).toFixed(1) + "%" : "0.0%";
      const sub = p * u;
      rows.push([item.name || "Sin nombre", p, c, u, m, mPct, sub]);
    });
    rows.push([]);
  }

  rows.push(["3. MÉTRICAS DE RENTABILIDAD Y EVALUACIÓN DE INVERSIÓN"]);
  rows.push(["Métrica", "Valor", "Unidad", "Veredicto"]);
  rows.push(["Valor Actual Neto (VAN / NPV)", r.npv, "MXN", r.npv >= 0 ? "Viable (Crea Valor Económico)" : "Inviable (Destruye Valor)"]);
  rows.push(["Tasa Interna de Retorno (TIR / IRR)", r.irr_pct !== null ? `${r.irr_pct.toFixed(2)}%` : "N/D", "%", r.irr_pct && r.irr_pct >= r.discount_rate_pct ? "Supera Tasa de Descuento" : "Inferior a Tasa de Descuento"]);
  rows.push(["Periodo de Recuperación Simple (Payback)", r.payback_years !== null ? `${r.payback_years.toFixed(2)} años` : "No recupera", "años", "Recuperación de inversión inicial"]);
  rows.push(["Periodo de Recuperación Descontado", r.discounted_payback_years !== null ? `${r.discounted_payback_years.toFixed(2)} años` : "> Horizonte", "años", "Recuperación a valor presente"]);
  rows.push(["Punto de Equilibrio Mensual (Unidades)", Math.round(r.break_even.monthly_breakeven_units), "unidades/mes", "Volumen mínimo para no perder"]);
  rows.push(["Punto de Equilibrio Mensual (Ingresos)", r.break_even.monthly_breakeven_revenue, "MXN/mes", "Facturación mínima de sobrevivencia"]);
  rows.push(["Margen de Seguridad Operativo", `${r.break_even.margin_of_safety_pct.toFixed(1)}%`, "%", "Colchón de ventas sobre el equilibrio"]);
  rows.push(["Razón Beneficio / Costo (B/C)", r.benefit_cost_ratio.toFixed(2), "veces", r.benefit_cost_ratio >= 1.0 ? "Beneficios superan los costos" : "Costos superan beneficios"]);
  rows.push(["Retorno Anual Promedio (ROI)", `${r.roi_annual_avg_pct.toFixed(1)}%`, "%", "Rendimiento neto anual sobre inversión"]);
  if (r.bank_comparison) {
    rows.push(["Premio de Riesgo vs CETES/Banco", `${r.bank_comparison.risk_premium_pct.toFixed(1)}%`, "%", r.bank_comparison.verdict]);
    rows.push(["Diferencial Mensual vs Banco", r.bank_comparison.monthly_difference, "MXN/mes", "Ganancia adicional mensual"]);
  }
  rows.push([]);

  // Pro-Forma
  if (r.yearly_cash_flows && r.yearly_cash_flows.length > 0) {
    rows.push(["4. ESTADO DE RESULTADOS Y PROYECCIÓN DE FLUJOS (PRO-FORMA A 5 AÑOS)"]);
    const yearsHeader = ["Concepto Financiero", ...r.yearly_cash_flows.map(y => `Año ${y.year}`)];
    rows.push(yearsHeader);

    const proformaFields = [
      { label: "Unidades Vendidas", key: "units_sold" },
      { label: "Precio Promedio Unitario ($)", key: "price_unit" },
      { label: "Ingresos Brutos ($)", key: "revenue" },
      { label: "(-) Mermas, Robos y Desperdicios ($)", key: "shrinkage_loss" },
      { label: "(=) Ingresos Netos ($)", key: "net_revenue" },
      { label: "(-) Costos Variables ($)", key: "variable_costs" },
      { label: "(=) Margen Bruto ($)", key: "gross_margin" },
      { label: "(-) Costos Fijos ($)", key: "fixed_costs" },
      { label: "(=) EBITDA ($)", key: "ebitda" },
      { label: "(-) Depreciación ($)", key: "depreciation" },
      { label: "(=) EBIT / Utilidad Operativa ($)", key: "ebit" },
      { label: "(-) Impuestos ISR ($)", key: "taxes" },
      { label: "(=) Utilidad Neta ($)", key: "net_income" },
      { label: "(+) Depreciación Recuperada ($)", key: "depreciation" },
      { label: "(=) Flujo de Caja Libre ($)", key: "free_cash_flow" },
      { label: "Flujo de Caja Libre Descontado ($)", key: "discounted_fcf" },
      { label: "Flujo Acumulado Descontado ($)", key: "cumulative_discounted_fcf" }
    ];

    proformaFields.forEach(field => {
      const line = [field.label];
      r.yearly_cash_flows.forEach(y => {
        const val = y[field.key];
        line.push(typeof val === "number" ? Math.round(val) : val);
      });
      rows.push(line);
    });
    rows.push([]);
  }

  // Ratios 360
  if (r.ratios && r.ratios.items && r.ratios.items.length > 0) {
    rows.push(["5. RAZONES FINANCIERAS INTEGRALES 360° (DIAGNÓSTICO CUANTITATIVO)"]);
    rows.push(["Razón Financiera", "Categoría", "Valor Calculado", "Unidad", "Meta / Benchmark", "Estado", "Interpretación Ejecutiva"]);
    r.ratios.items.forEach(it => {
      rows.push([it.name, it.category, it.value, it.unit, it.benchmark, it.status.toUpperCase(), it.interpretation]);
    });
    rows.push([]);
  }

  // Scenarios
  if (r.scenarios) {
    rows.push(["6. ANÁLISIS DE SENSIBILIDAD POR ESCENARIOS"]);
    rows.push(["Escenario", "Descripción", "VAN / NPV (MXN)", "TIR / IRR (%)", "Payback (Años)", "ROI Anual Promedio (%)"]);
    [r.scenarios.pessimistic, r.scenarios.base, r.scenarios.optimistic].forEach(sc => {
      if (sc) {
        rows.push([
          sc.name,
          sc.description,
          sc.npv,
          sc.irr_pct !== null ? `${sc.irr_pct.toFixed(2)}%` : "N/D",
          sc.payback_years !== null ? `${sc.payback_years.toFixed(2)}` : "> 5",
          `${sc.roi_annual_avg_pct.toFixed(1)}%`
        ]);
      }
    });
  }

  const csvContent = "\uFEFF" + rows.map(row => row.map(cell => escapeCsv(cell)).join(",")).join("\r\n");
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const safeName = (b.name || "Proyecto").replace(/[^a-zA-Z0-9_-]/g, "_");
  link.setAttribute("href", url);
  link.setAttribute("download", `Modelo_Financiero_EconoMetrics_${safeName}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  showToast("Modelo Financiero exportado a Excel / CSV exitosamente.", true);
}

// ----------------- PUENTE CON EL PORTAL DEL DUEÑO (OPS / ERP) -----------------
function buildAssetsToExportFromStudio(f, eng) {
  const eqItems = Array.isArray(eng?.equipment_items) ? eng.equipment_items : [];
  const selectedBudget = typeof window.getSelectedBudgetOption === "function" ? window.getSelectedBudgetOption() : null;
  const detailsList = Array.isArray(selectedBudget?.details) ? selectedBudget.details : [];

  // Si hay un presupuesto IA seleccionado con desglose de costos ("Horno: $45,000 MXN"), extraer costos reales
  const parsedDetailCosts = detailsList.map((line) => {
    const match = String(line).match(/\$\s*([\d,]+(?:\.\d+)?)/);
    if (!match) return null;
    const cost = parseFloat(match[1].replace(/,/g, ""));
    const label = String(line).split(/[:$-]/)[0].trim();
    return !isNaN(cost) && cost > 0 ? { label, cost } : null;
  });

  if (eqItems.length > 0) {
    const totalInv = parseFloat(f.initial_investment || 0);
    const count = eqItems.length;
    const fallbackUnitCost = count > 0 && totalInv > 0 ? Math.round((totalInv * 0.65) / count) : 15000;

    return eqItems.map((it, idx) => {
      const parsed = parsedDetailCosts[idx];
      const explicitCost = (parseFloat(it.price_standard || 0) * parseFloat(it.qty || 1));
      const cost = (parsed && parsed.cost) || explicitCost || fallbackUnitCost;
      return {
        name: `${it.name || parsed?.label || "Equipo"} (${it.category || "Maquinaria"})`,
        category: it.category || "Maquinaria Presupuestada",
        purchase_cost: Math.round(cost),
        useful_life_years: f.depreciation_years || 5,
        monthly_maintenance: 0
      };
    }).filter(a => a.purchase_cost > 0);
  }

  // Si no hay renglones pero sí detalles del presupuesto IA seleccionado
  const validParsed = parsedDetailCosts.filter(Boolean);
  if (validParsed.length > 0) {
    return validParsed.map(p => ({
      name: p.label || "Equipo Presupuestado",
      category: "Maquinaria Presupuestada",
      purchase_cost: Math.round(p.cost),
      useful_life_years: f.depreciation_years || 5,
      monthly_maintenance: 0
    }));
  }

  return [];
}

function updateProjectKeyBadge(key) {
  const container = document.getElementById("projectKeyBadgeContainer");
  const display = document.getElementById("projectKeyDisplay");
  const exportInput = document.getElementById("exportKeyInput");
  if (key) {
    if (display) display.textContent = key;
    if (container) {
      container.classList.remove("hidden");
      container.classList.add("flex");
    }
    if (exportInput) exportInput.value = key;
  } else {
    if (container) {
      container.classList.add("hidden");
      container.classList.remove("flex");
    }
    if (exportInput && exportInput.value.startsWith("EM-")) exportInput.value = "";
  }
}
window.updateProjectKeyBadge = updateProjectKeyBadge;

window.syncPlanToErpBaseline = async function({ replaceAssets = true, silent = false } = {}) {
  const data = getFormData();
  const b = data.business || {};
  const f = data.financials || {};
  const eng = data.engineering || {};
  const cat = typeof getMultiProductCatalogData === "function" ? getMultiProductCatalogData() : (data.product_catalog || []);
  const assetsToExport = buildAssetsToExportFromStudio(f, eng);
  const shouldReplace = Boolean(replaceAssets && assetsToExport.length > 0);

  const payload = {
    project_key: window.currentProjectKey || localStorage.getItem("econometrics_current_project_key") || null,
    business: b,
    financials: f,
    engineering: eng,
    catalog: cat,
    replace_assets: shouldReplace,
    assets: shouldReplace ? assetsToExport : null
  };

  const res = await fetch("/api/ops/sync-from-studio", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(formatApiError(err) || "No se pudo sincronizar el proyecto con el ERP.");
  }
  const result = await res.json();
  if (result.project_key) {
    window.currentProjectKey = result.project_key;
    localStorage.setItem("econometrics_current_project_key", result.project_key);
    if (result.business_id) {
      localStorage.setItem("econometrics_active_business_id", String(result.business_id));
    }
    if (result.branch_id) {
      localStorage.setItem("econometrics_active_branch_id", String(result.branch_id));
    }
    updateProjectKeyBadge(result.project_key);
  }
  if (!silent) {
    showToast(`¡Proyecto "${result.project_name || b.name || 'Mi Proyecto'}" aprovisionado con clave ${result.project_key || ''}!`, true);
  }
  return result;
};

function initOpsBridgeListeners() {
  const publishBtn = document.getElementById("publishBaselineBtn");
  const copyBtn = document.getElementById("copyProjectKeyBtn");

  if (copyBtn) {
    copyBtn.addEventListener("click", () => {
      const key = window.currentProjectKey || localStorage.getItem("econometrics_current_project_key");
      if (key) {
        navigator.clipboard.writeText(key);
        showToast(`Clave ${key} copiada al portapapeles`, true);
      }
    });
  }

  // Restore badge if project key was previously active
  const storedKey = localStorage.getItem("econometrics_current_project_key");
  if (storedKey) {
    window.currentProjectKey = storedKey;
    updateProjectKeyBadge(storedKey);
  }

  if (!publishBtn) return;

  publishBtn.addEventListener("click", async () => {
    const data = getFormData();
    const b = data.business || {};
    const f = data.financials || {};
    const eng = data.engineering || {};
    const assetsToExport = buildAssetsToExportFromStudio(f, eng);

    let replaceAssets = false;
    if (assetsToExport.length > 0) {
      replaceAssets = confirm(
        `¿Deseas aprovisionar y actualizar el inventario y maquinaria del Portal del Dueño con las ${assetsToExport.length} partidas registradas en "${b.name || 'Mi Proyecto'}"?\n\n• Aceptar: Sincroniza metas financieras + activos + catálogo + personal.\n• Cancelar: Actualiza únicamente las metas financieras del Plan Base.`
      );
    }

    const originalHtml = publishBtn.innerHTML;
    publishBtn.disabled = true;
    publishBtn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin text-xs"></i><span>Sincronizando...</span>`;

    try {
      await window.syncPlanToErpBaseline({ replaceAssets, silent: false });
    } catch (e) {
      showToast(e.message || "Error al conectar con el Portal del Dueño", false);
    } finally {
      publishBtn.disabled = false;
      publishBtn.innerHTML = originalHtml;
    }
  });
}

// ----------------- CATÁLOGO MULTIPRODUCTO & MEZCLA DE PRECIOS -----------------
let currentProductCatalog = [
  { name: "Producto Entrada (Económico)", price: 30, cost: 10, units: 500 },
  { name: "Producto Estándar / Servicio", price: 150, cost: 50, units: 200 },
  { name: "Producto Premium / Especial", price: 500, cost: 210, units: 40 }
];
let catalogInputMode = "multi"; // "multi" | "simple"

function initMultiProductCatalog() {
  const multiBtn = document.getElementById("catalogModeMultiBtn");
  const simpleBtn = document.getElementById("catalogModeSimpleBtn");
  const addBtn = document.getElementById("addProductRowBtn");
  const exampleBtn = document.getElementById("loadExampleProductsBtn");
  const inventoryBtn = document.getElementById("importFromInventoryBtn");

  if (multiBtn) {
    multiBtn.addEventListener("click", () => setCatalogInputMode("multi"));
  }
  if (simpleBtn) {
    simpleBtn.addEventListener("click", () => setCatalogInputMode("simple"));
  }
  if (addBtn) {
    addBtn.addEventListener("click", () => addProductCatalogRow());
  }
  if (exampleBtn) {
    exampleBtn.addEventListener("click", () => loadMultiProductExample());
  }
  if (inventoryBtn) {
    inventoryBtn.addEventListener("click", () => importProductsFromInventory());
  }

  // Render inicial
  renderProductCatalogTable();
  setCatalogInputMode(catalogInputMode);
}

function setCatalogInputMode(mode) {
  catalogInputMode = mode;
  const multiBtn = document.getElementById("catalogModeMultiBtn");
  const simpleBtn = document.getElementById("catalogModeSimpleBtn");
  const simpleContainer = document.getElementById("simplePriceInputsContainer");
  const multiContainer = document.getElementById("multiProductContainer");

  const monthlyPrice = document.getElementById("monthlyPrice");
  const monthlyUnits = document.getElementById("monthlyUnits");
  const unitVariableCost = document.getElementById("unitVariableCost");
  const priceBadge = document.getElementById("priceModeBadge");
  const unitsBadge = document.getElementById("unitsModeBadge");
  const costBadge = document.getElementById("costModeBadge");
  const priceHelper = document.getElementById("monthlyPriceHelper");
  const unitsHelper = document.getElementById("monthlyUnitsHelper");
  const costHelper = document.getElementById("unitVariableCostHelper");

  if (mode === "multi") {
    if (multiBtn) {
      multiBtn.className = "px-3 py-1.5 rounded-lg font-medium transition-all bg-[#c5a059] text-zinc-950 shadow-sm flex items-center gap-1.5 cursor-pointer";
    }
    if (simpleBtn) {
      simpleBtn.className = "px-3 py-1.5 rounded-lg font-medium transition-all text-zinc-400 hover:text-white flex items-center gap-1.5 cursor-pointer";
    }
    if (simpleContainer) simpleContainer.classList.add("hidden");
    if (multiContainer) multiContainer.classList.remove("opacity-60");

    if (monthlyPrice) {
      monthlyPrice.readOnly = true;
      monthlyPrice.classList.add("bg-zinc-800/60", "cursor-not-allowed", "text-[#d4b26f]");
    }
    if (monthlyUnits) {
      monthlyUnits.readOnly = true;
      monthlyUnits.classList.add("bg-zinc-800/60", "cursor-not-allowed", "text-emerald-400");
    }
    if (unitVariableCost) {
      unitVariableCost.readOnly = true;
      unitVariableCost.classList.add("bg-zinc-800/60", "cursor-not-allowed", "text-rose-400");
    }

    if (priceBadge) {
      priceBadge.textContent = "Ponderado Catálogo";
      priceBadge.className = "text-[10px] font-mono text-[#d4b26f] bg-[#c5a059]/15 border border-[#c5a059]/40 px-1.5 py-0.5 rounded";
    }
    if (unitsBadge) {
      unitsBadge.textContent = "Suma Catálogo";
      unitsBadge.className = "text-[10px] font-mono text-emerald-400 bg-emerald-500/15 border border-emerald-500/40 px-1.5 py-0.5 rounded";
    }
    if (costBadge) {
      costBadge.textContent = "Ponderado Catálogo";
      costBadge.className = "text-[10px] font-mono text-rose-400 bg-rose-500/15 border border-rose-500/40 px-1.5 py-0.5 rounded";
    }

    if (priceHelper) priceHelper.textContent = "Ticket promedio ponderado calculado en tiempo real desde tu catálogo de productos.";
    if (unitsHelper) unitsHelper.textContent = "Suma acumulada de unidades vendidas al mes de todos tus productos.";
    if (costHelper) costHelper.textContent = "Costo unitario directo promedio ponderado de tu mezcla de ventas.";

    recalculateMultiProductTotals();
  } else {
    if (multiBtn) {
      multiBtn.className = "px-3 py-1.5 rounded-lg font-medium transition-all text-zinc-400 hover:text-white flex items-center gap-1.5 cursor-pointer";
    }
    if (simpleBtn) {
      simpleBtn.className = "px-3 py-1.5 rounded-lg font-medium transition-all bg-[#c5a059] text-zinc-950 shadow-sm flex items-center gap-1.5 cursor-pointer";
    }
    if (simpleContainer) simpleContainer.classList.remove("hidden");
    if (multiContainer) multiContainer.classList.add("opacity-60");

    if (monthlyPrice) {
      monthlyPrice.readOnly = false;
      monthlyPrice.classList.remove("bg-zinc-800/60", "cursor-not-allowed", "text-[#d4b26f]");
    }
    if (monthlyUnits) {
      monthlyUnits.readOnly = false;
      monthlyUnits.classList.remove("bg-zinc-800/60", "cursor-not-allowed", "text-emerald-400");
    }
    if (unitVariableCost) {
      unitVariableCost.readOnly = false;
      unitVariableCost.classList.remove("bg-zinc-800/60", "cursor-not-allowed", "text-rose-400");
    }

    if (priceBadge) {
      priceBadge.textContent = "Manual Global";
      priceBadge.className = "text-[10px] font-mono text-zinc-400 bg-zinc-800 border border-zinc-700 px-1.5 py-0.5 rounded";
    }
    if (unitsBadge) {
      unitsBadge.textContent = "Manual Global";
      unitsBadge.className = "text-[10px] font-mono text-zinc-400 bg-zinc-800 border border-zinc-700 px-1.5 py-0.5 rounded";
    }
    if (costBadge) {
      costBadge.textContent = "Manual Global";
      costBadge.className = "text-[10px] font-mono text-zinc-400 bg-zinc-800 border border-zinc-700 px-1.5 py-0.5 rounded";
    }

    if (priceHelper) priceHelper.textContent = "Ticket promedio global por cliente atendido o producto vendido.";
    if (unitsHelper) unitsHelper.textContent = "Volumen estimado mensual único de unidades o transacciones.";
    if (costHelper) costHelper.textContent = "Costo variable promedio unitario de tu operación.";

    runQuickCalculation();
  }
}

function renderProductCatalogTable() {
  const tbody = document.getElementById("productCatalogTableBody");
  if (!tbody) return;

  tbody.innerHTML = "";

  if (!currentProductCatalog || currentProductCatalog.length === 0) {
    currentProductCatalog = [{ name: "Producto Principal", price: 100, cost: 30, units: 100 }];
  }

  currentProductCatalog.forEach((item, index) => {
    const tr = document.createElement("tr");
    tr.className = "hover:bg-zinc-900/50 transition-colors group";

    const price = parseFloat(item.price || 0);
    const cost = parseFloat(item.cost || 0);
    const units = parseFloat(item.units || 0);
    const margin = price - cost;
    const marginPct = price > 0 ? (margin / price * 100) : 0;
    const subtotal = price * units;

    const marginColor = margin >= 0 ? "text-emerald-400" : "text-rose-400";
    const marginBadgeClass = margin >= 0 ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/20" : "bg-rose-500/10 text-rose-300 border-rose-500/20";

    tr.innerHTML = `
      <td class="py-2.5 px-3.5">
        <input type="text" value="${escapeHtml(item.name || '')}" placeholder="ej. Café Espresso, Playera, Combo..." 
          data-index="${index}" data-field="name"
          class="mp-input mp-name w-full bg-zinc-900/90 border border-zinc-800 rounded-lg px-2.5 py-1.5 text-xs text-zinc-100 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-[#c5a059] focus:border-[#c5a059]">
      </td>
      <td class="py-2.5 px-3.5">
        <div class="relative">
          <span class="absolute left-2.5 top-1.5 text-zinc-500 text-[10px] font-mono">$</span>
          <input type="number" step="0.5" min="0" value="${price}" 
            data-index="${index}" data-field="price"
            class="mp-input mp-price w-full bg-zinc-900/90 border border-zinc-800 rounded-lg pl-6 pr-2 py-1.5 text-xs text-zinc-100 font-mono focus:outline-none focus:ring-1 focus:ring-[#c5a059] focus:border-[#c5a059]">
        </div>
      </td>
      <td class="py-2.5 px-3.5">
        <div class="relative">
          <span class="absolute left-2.5 top-1.5 text-zinc-500 text-[10px] font-mono">$</span>
          <input type="number" step="0.5" min="0" value="${cost}" 
            data-index="${index}" data-field="cost"
            class="mp-input mp-cost w-full bg-zinc-900/90 border border-zinc-800 rounded-lg pl-6 pr-2 py-1.5 text-xs text-zinc-100 font-mono focus:outline-none focus:ring-1 focus:ring-[#c5a059] focus:border-[#c5a059]">
        </div>
      </td>
      <td class="py-2.5 px-3.5">
        <input type="number" step="1" min="0" value="${units}" 
          data-index="${index}" data-field="units"
          class="mp-input mp-units w-full bg-zinc-900/90 border border-zinc-800 rounded-lg px-2.5 py-1.5 text-xs text-zinc-100 font-mono focus:outline-none focus:ring-1 focus:ring-[#c5a059] focus:border-[#c5a059]">
      </td>
      <td class="py-2.5 px-3.5 text-center">
        <div class="inline-flex flex-col items-center">
          <span class="text-xs font-mono font-bold ${marginColor} mp-row-margin-val">${margin >= 0 ? '+' : ''}$${margin.toFixed(2)}</span>
          <span class="text-[10px] font-mono px-1.5 py-0.2 rounded-full border ${marginBadgeClass} mp-row-margin-pct">${marginPct.toFixed(1)}%</span>
        </div>
      </td>
      <td class="py-2.5 px-3.5 text-right font-mono text-xs font-bold text-[#d4b26f] mp-row-subtotal">
        $${Math.round(subtotal).toLocaleString()}
      </td>
      <td class="py-2.5 px-2 text-center">
        <button type="button" data-index="${index}" class="mp-delete-btn p-1.5 rounded-lg text-zinc-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors cursor-pointer" title="Eliminar producto">
          <i class="fa-solid fa-trash-can text-xs"></i>
        </button>
      </td>
    `;

    tbody.appendChild(tr);
  });

  // Listeners de los inputs dentro de la tabla
  tbody.querySelectorAll(".mp-input").forEach(input => {
    input.addEventListener("input", onProductInput);
  });

  tbody.querySelectorAll(".mp-delete-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.getAttribute("data-index"), 10);
      deleteProductCatalogRow(idx);
    });
  });
}

function onProductInput(e) {
  const input = e.target;
  const idx = parseInt(input.getAttribute("data-index"), 10);
  const field = input.getAttribute("data-field");
  if (isNaN(idx) || !currentProductCatalog[idx]) return;

  if (field === "name") {
    currentProductCatalog[idx].name = input.value;
  } else {
    currentProductCatalog[idx][field] = Math.max(0, parseFloat(input.value) || 0);
  }

  // Actualizar margen y subtotal de la fila inmediatamente
  const row = input.closest("tr");
  if (row) {
    const item = currentProductCatalog[idx];
    const price = item.price || 0;
    const cost = item.cost || 0;
    const units = item.units || 0;
    const margin = price - cost;
    const marginPct = price > 0 ? (margin / price * 100) : 0;
    const subtotal = price * units;

    const marginVal = row.querySelector(".mp-row-margin-val");
    const marginBadge = row.querySelector(".mp-row-margin-pct");
    const subtotalEl = row.querySelector(".mp-row-subtotal");

    if (marginVal) {
      marginVal.textContent = (margin >= 0 ? '+' : '') + "$" + margin.toFixed(2);
      marginVal.className = `text-xs font-mono font-bold ${margin >= 0 ? "text-emerald-400" : "text-rose-400"} mp-row-margin-val`;
    }
    if (marginBadge) {
      marginBadge.textContent = marginPct.toFixed(1) + "%";
      marginBadge.className = `text-[10px] font-mono px-1.5 py-0.2 rounded-full border ${margin >= 0 ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/20" : "bg-rose-500/10 text-rose-300 border-rose-500/20"} mp-row-margin-pct`;
    }
    if (subtotalEl) {
      subtotalEl.textContent = "$" + Math.round(subtotal).toLocaleString();
    }
  }

  recalculateMultiProductTotals();
}

function recalculateMultiProductTotals() {
  let totalUnits = 0;
  let totalRevenue = 0;
  let totalCost = 0;
  const count = currentProductCatalog.length;

  currentProductCatalog.forEach(item => {
    const p = Math.max(0, parseFloat(item.price) || 0);
    const c = Math.max(0, parseFloat(item.cost) || 0);
    const u = Math.max(0, parseFloat(item.units) || 0);

    totalUnits += u;
    totalRevenue += (p * u);
    totalCost += (c * u);
  });

  const weightedPrice = totalUnits > 0 ? (totalRevenue / totalUnits) : 0;
  const weightedCost = totalUnits > 0 ? (totalCost / totalUnits) : 0;
  const grossMarginPct = totalRevenue > 0 ? ((totalRevenue - totalCost) / totalRevenue * 100) : 0;

  // Actualizar barra de resumen
  const countEl = document.getElementById("mpSummaryCount");
  const unitsEl = document.getElementById("mpSummaryUnits");
  const revEl = document.getElementById("mpSummaryRevenue");
  const costEl = document.getElementById("mpSummaryCost");
  const avgPriceEl = document.getElementById("mpSummaryAvgPrice");
  const marginPctEl = document.getElementById("mpSummaryMarginPct");

  if (countEl) countEl.textContent = count;
  if (unitsEl) unitsEl.textContent = Math.round(totalUnits).toLocaleString();
  if (revEl) revEl.textContent = "$" + Math.round(totalRevenue).toLocaleString();
  if (costEl) costEl.textContent = "$" + Math.round(totalCost).toLocaleString();
  if (avgPriceEl) avgPriceEl.textContent = "$" + weightedPrice.toFixed(2);
  if (marginPctEl) marginPctEl.textContent = grossMarginPct.toFixed(1) + "%";

  // Si está en modo multiproducto, sincronizar a los inputs de la máquina financiera
  if (catalogInputMode === "multi") {
    const monthlyPrice = document.getElementById("monthlyPrice");
    const monthlyUnits = document.getElementById("monthlyUnits");
    const unitVariableCost = document.getElementById("unitVariableCost");

    if (monthlyPrice) monthlyPrice.value = weightedPrice.toFixed(2);
    if (monthlyUnits) monthlyUnits.value = Math.round(totalUnits);
    if (unitVariableCost) unitVariableCost.value = weightedCost.toFixed(2);

    updateBankAndShrinkageHelpers();
    runQuickCalculation();
    scheduleAutoSave();
  }
}

function addProductCatalogRow(item = null) {
  const prod = item || {
    name: `Producto ${currentProductCatalog.length + 1}`,
    price: 120,
    cost: 40,
    units: 50
  };
  currentProductCatalog.push(prod);
  renderProductCatalogTable();
  recalculateMultiProductTotals();
}

function deleteProductCatalogRow(index) {
  if (currentProductCatalog.length <= 1) {
    showToast("Debes conservar al menos 1 producto en el catálogo.", false);
    return;
  }
  currentProductCatalog.splice(index, 1);
  renderProductCatalogTable();
  recalculateMultiProductTotals();
}

function loadMultiProductExample() {
  currentProductCatalog = [
    { name: "Producto Entrada (Económico)", price: 30, cost: 10, units: 500 },
    { name: "Producto Estándar / Servicio", price: 150, cost: 50, units: 200 },
    { name: "Producto Premium / Especial", price: 500, cost: 210, units: 40 }
  ];
  setCatalogInputMode("multi");
  renderProductCatalogTable();
  recalculateMultiProductTotals();
  showToast("Ejemplo con productos de $30, $150 y $500 cargado exitosamente.", true);
}

async function importProductsFromInventory() {
  try {
    const token = sessionStorage.getItem("pos_token");
    const headers = token ? { "X-POS-Token": token } : {};
    let res = await fetch("/api/pos/products", { headers });
    if (!res.ok) {
      res = await fetch("/api/inv/products", { headers });
    }
    if (!res.ok) throw new Error("No se pudo conectar con el catálogo de inventario.");

    const items = await res.json();
    if (!Array.isArray(items) || items.length === 0) {
      alert("No hay productos dados de alta en el inventario todavía. Puedes capturarlos directamente aquí en el catálogo multiproducto.");
      return;
    }

    currentProductCatalog = items.map(it => {
      const p = parseFloat(it.price || it.retail_price || 100);
      const c = parseFloat(it.cost_price || it.cost || (p * 0.45));
      return {
        name: it.name || it.description || "Producto",
        price: p,
        cost: c,
        units: 100
      };
    });

    setCatalogInputMode("multi");
    renderProductCatalogTable();
    recalculateMultiProductTotals();
    showToast(`¡${items.length} productos importados desde tu Inventario / POS!`, true);
  } catch (err) {
    alert("No se pudo importar del inventario: " + err.message);
  }
}

function getMultiProductCatalogData() {
  return currentProductCatalog;
}

function getCatalogInputMode() {
  return catalogInputMode;
}

function applyMultiProductCatalogData(catalog, mode = "multi") {
  if (Array.isArray(catalog) && catalog.length > 0) {
    currentProductCatalog = JSON.parse(JSON.stringify(catalog));
    renderProductCatalogTable();
    setCatalogInputMode(mode);
  }
}

function applyDefaultMultiProductForTemplate(tmplId, avgPrice = 95, avgCost = 28, totalUnits = 2800) {
  const str = String(tmplId || "").toLowerCase();

  if (str.includes("cafe") || str.includes("cafetería") || str.includes("brunch")) {
    currentProductCatalog = [
      { name: "Café Americano / Espresso", price: 45, cost: 10, units: 1200 },
      { name: "Bebida Especial / Latte de Autor", price: 85, cost: 24, units: 900 },
      { name: "Repostería / Panadería Artesanal", price: 65, cost: 20, units: 500 },
      { name: "Bolsa Café de Especialidad (250g)", price: 250, cost: 95, units: 200 }
    ];
  } else if (str.includes("ecommerce") || str.includes("skincare") || str.includes("cosmetica")) {
    currentProductCatalog = [
      { name: "Limpiador Facial Suave", price: 280, cost: 75, units: 220 },
      { name: "Sérum Hidratante Anti-edad", price: 490, cost: 120, units: 180 },
      { name: "Kit Rutina Completa 3 Pasos", price: 890, cost: 260, units: 80 }
    ];
  } else if (str.includes("fitness") || str.includes("gym") || str.includes("pilates")) {
    currentProductCatalog = [
      { name: "Pase por Clase Individual", price: 250, cost: 30, units: 60 },
      { name: "Paquete 10 Clases Mensual", price: 1800, cost: 150, units: 80 },
      { name: "Membresía Ilimitada VIP", price: 2800, cost: 200, units: 20 }
    ];
  } else {
    // Escenario genérico mixto representativo de productos económicos y altos
    const p = Math.max(10, parseFloat(avgPrice) || 100);
    const c = Math.max(5, parseFloat(avgCost) || (p * 0.35));
    const u = Math.max(10, parseFloat(totalUnits) || 500);

    const uLow = Math.round(u * 0.55);
    const uMid = Math.round(u * 0.35);
    const uHigh = Math.max(1, u - uLow - uMid);

    currentProductCatalog = [
      { name: "Línea Básica / Accesorio", price: Math.round(p * 0.4), cost: Math.round(c * 0.4), units: uLow },
      { name: "Línea Estándar / Servicio", price: Math.round(p * 1.0), cost: Math.round(c * 1.0), units: uMid },
      { name: "Línea Premium / Especial", price: Math.round(p * 2.8), cost: Math.round(c * 2.5), units: uHigh }
    ];
  }

  setCatalogInputMode("multi");
  renderProductCatalogTable();
  recalculateMultiProductTotals();
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
