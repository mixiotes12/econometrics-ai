// EconoMetrics AI - Frontend Logic

let cashFlowChartInstance = null;
let breakEvenChartInstance = null;
let currentFinancialReport = null;

document.addEventListener("DOMContentLoaded", async () => {
  await initApiKey();
  initEventListeners();
  initEngineeringAndTrackerListeners();
  initProjectPersistence();
  await initTemplatesAndSavedProjects();
  restoreSavedStateOrDraft();
  
  const transferredInvestment = localStorage.getItem("econometrics_transfer_investment");
  if(transferredInvestment) {
    document.getElementById("initialInvestment").value = transferredInvestment;
    localStorage.removeItem("econometrics_transfer_investment");
    // Auto trigger quick calc
    const quickCalcBtn = document.getElementById("quickCalcBtn");
    if(quickCalcBtn) quickCalcBtn.click();
  }
});

// ----------------- TAB SWITCHING -----------------

function switchTab(tabIndex) {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.remove('active', 'text-white', 'border-purple-500/50', 'bg-zinc-800');
    btn.classList.add('text-zinc-300', 'border-zinc-800', 'bg-zinc-900');
    btn.querySelector('span:first-child').classList.remove('bg-purple-500', 'text-white');
    btn.querySelector('span:first-child').classList.add('bg-purple-500/30', 'text-purple-300');
  });

  const activeBtn = document.getElementById(`tabBtn${tabIndex}`);
  if (activeBtn) {
    activeBtn.classList.remove('text-zinc-300', 'border-zinc-800', 'bg-zinc-900');
    activeBtn.classList.add('active', 'text-white', 'border-purple-500/50', 'bg-zinc-800');
    activeBtn.querySelector('span:first-child').classList.remove('bg-purple-500/30', 'text-purple-300');
    activeBtn.querySelector('span:first-child').classList.add('bg-purple-500', 'text-white');
  }

  for (let i = 1; i <= 6; i++) {
    const section = document.getElementById(`tab${i}`);
    if (section) {
      if (i === tabIndex) {
        section.classList.remove('hidden');
      } else {
        section.classList.add('hidden');
      }
    }
  }
  if (tabIndex === 2 && typeof window.renderPendingMermaid === "function") {
    window.renderPendingMermaid();
  }
}
window.switchTab = switchTab;

let hasServerApiKey = false;

// ----------------- API KEY & SETTINGS -----------------
async function initApiKey() {
  const savedKey = localStorage.getItem("gemini_api_key") || "";
  let savedModel = localStorage.getItem("gemini_model") || "gemini-3.5-flash";
  if (savedModel === "gemini-2.5-flash" || savedModel === "gemini-3.8-flash") {
    savedModel = "gemini-3.5-flash";
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

  if (savedKey) {
    document.getElementById("geminiApiKeyInput").value = savedKey;
    updateApiKeyBadge(true, "API Key: Configurada");
  } else if (hasServerApiKey) {
    updateApiKeyBadge(true, "API Key: Servidor Activa");
  } else {
    updateApiKeyBadge(false, "Configurar API Key");
  }

  document.getElementById("geminiModelSelect").value = savedModel;
}

function updateApiKeyBadge(hasKey, labelText) {
  const label = document.getElementById("apiKeyStatusLabel");
  const btn = document.getElementById("apiKeyBtn");
  label.textContent = labelText || (hasKey ? "API Key: Configurada" : "Configurar API Key");
  if (hasKey) {
    btn.classList.add("border-emerald-500/40", "text-emerald-400");
    btn.classList.remove("border-zinc-700", "text-zinc-300");
  } else {
    btn.classList.remove("border-emerald-500/40", "text-emerald-400");
    btn.classList.add("border-zinc-700", "text-zinc-300");
  }
}

// ----------------- EVENT LISTENERS -----------------
function initEventListeners() {
  // API Key Modal
  const modal = document.getElementById("apiKeyModal");
  document.getElementById("apiKeyBtn").addEventListener("click", () => {
    modal.classList.remove("hidden");
  });
  document.getElementById("closeApiKeyModal").addEventListener("click", () => {
    modal.classList.add("hidden");
  });
  document.getElementById("saveApiKeyBtn").addEventListener("click", () => {
    const key = document.getElementById("geminiApiKeyInput").value.trim();
    const model = document.getElementById("geminiModelSelect").value;
    if (key) {
      localStorage.setItem("gemini_api_key", key);
      updateApiKeyBadge(true);
    } else {
      localStorage.removeItem("gemini_api_key");
      updateApiKeyBadge(false);
    }
    localStorage.setItem("gemini_model", model);
    modal.classList.add("hidden");
  });

  document.getElementById("toggleApiKeyVisibility").addEventListener("click", () => {
    const input = document.getElementById("geminiApiKeyInput");
    const icon = document.querySelector("#toggleApiKeyVisibility i");
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
  document.getElementById("quickCalcBtn").addEventListener("click", () => {
    runQuickCalculation().then(() => switchTab(6));
  });

  const calcAndGoBtn = document.getElementById("calcAndGoTab5Btn") || document.getElementById("calcAndGoTab3Btn");
  if (calcAndGoBtn) {
    calcAndGoBtn.addEventListener("click", () => {
      runQuickCalculation().then(() => switchTab(6));
    });
  }

  document.getElementById("runFullAnalysisBtn").addEventListener("click", () => {
    runFullGeminiAnalysis();
  });

  document.getElementById("reanalyzeBtn").addEventListener("click", () => {
    runFullGeminiAnalysis();
  });

  const exportPdfBtn = document.getElementById("exportPdfBtn");
  if (exportPdfBtn) {
    exportPdfBtn.addEventListener("click", () => {
      window.print();
    });
  }

  const exportCsvBtn = document.getElementById("exportCsvBtn");
  if (exportCsvBtn) {
    exportCsvBtn.addEventListener("click", () => {
      exportFinancialReportToCsv();
    });
  }

  const tab6ExportCsvBtn = document.getElementById("tab6ExportCsvBtn");
  if (tab6ExportCsvBtn) {
    tab6ExportCsvBtn.addEventListener("click", () => {
      exportFinancialReportToCsv();
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
  select.addEventListener("change", () => {
    const val = select.value;
    if (!val) return;

    if (val.startsWith("saved_")) {
      const savedList = getSavedProjects();
      const proj = savedList.find(p => p.id === val);
      if (proj) {
        applyFormData(proj);
        runQuickCalculation();
        scheduleAutoSave();
        showToast(`Proyecto cargado: "${proj.name}"`, true);
      }
    } else {
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
        runQuickCalculation();
        scheduleAutoSave();
        document.getElementById("templateSelect").value = "";
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

  return { business, financials, engineering };
}

// ----------------- QUICK FINANCIAL CALCULATION -----------------
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
    document.getElementById("exportPdfBtn").classList.remove("hidden");
    const exportCsvBtn = document.getElementById("exportCsvBtn");
    if (exportCsvBtn) exportCsvBtn.classList.remove("hidden");
  } catch (err) {
    console.error("Calculation error:", err);
  }
}

// ----------------- FULL GEMINI ANALYSIS -----------------
async function runFullGeminiAnalysis() {
  const key = localStorage.getItem("gemini_api_key") || document.getElementById("geminiApiKeyInput").value.trim();
  if (!key && !hasServerApiKey) {
    document.getElementById("apiKeyModal").classList.remove("hidden");
    alert("Por favor ingresa tu API Key de Gemini para continuar con el análisis estratégico.");
    return;
  }

  const model = document.getElementById("geminiModelSelect").value || localStorage.getItem("gemini_model") || "gemini-3.5-flash";
  const { business, financials } = getFormData();

  switchTab(6);
  const spinner = document.getElementById("aiLoadingSpinner");
  spinner.classList.remove("hidden");

  try {
    const headers = { "Content-Type": "application/json" };
    if (key) {
      headers["x-gemini-api-key"] = key;
    }
    const payload = {
      business,
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
    }
  } catch (err) {
    alert("Error de análisis: " + err.message);
  } finally {
    spinner.classList.add("hidden");
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
  let lastBudgetsData = null;
  let lastFlowchartData = null;
  let pendingMermaidCode = null;

  function createEquipmentRow(item = {}) {
    const div = document.createElement("div");
    div.className = "flex gap-2 equipment-item mt-2";
    div.innerHTML = `
      <select class="eq-category w-1/4 bg-zinc-900 border border-zinc-700 rounded-lg px-2 py-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none"><option value="Maquinaria">Maquinaria</option><option value="Servicios">Servicios</option><option value="Empleados">Empleados</option></select><input type="text" placeholder="Ej: Equipo" class="eq-name w-1/3 bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none">
      <input type="text" placeholder="Especificaciones" class="eq-desc flex-1 bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none">
      <button type="button" class="text-rose-400 hover:text-rose-300 px-2" onclick="this.parentElement.remove(); scheduleAutoSave();"><i class="fa-solid fa-xmark"></i></button>
    `;
    div.querySelector(".eq-category").value = item.category || "Maquinaria";
    div.querySelector(".eq-name").value = item.name || "";
    div.querySelector(".eq-desc").value = item.description || "";
    equipmentList.appendChild(div);
    return div;
  }

  addEqBtn.addEventListener("click", () => {
    createEquipmentRow();
    scheduleAutoSave();
  });

  // Autosave de las pestañas 1 y 2
  equipmentList.addEventListener("input", () => scheduleAutoSave());
  equipmentList.addEventListener("change", () => scheduleAutoSave());

  genBudgetsBtn.addEventListener("click", async () => {
    const items = [];
    document.querySelectorAll(".equipment-item").forEach(item => {
      const category = item.querySelector(".eq-category").value;
      const name = item.querySelector(".eq-name").value.trim();
      const desc = item.querySelector(".eq-desc").value.trim();
      if(name) items.push({category, name, description: desc});
    });

    if(items.length === 0) {
      alert("Añade al menos un equipo.");
      return;
    }

    budgetsOutput.classList.add("hidden");
    budgetsLoader.classList.remove("hidden");
    budgetsLoader.classList.add("flex");
    
    try {
      const apiKey = localStorage.getItem("gemini_api_key");
      const headers = { "Content-Type": "application/json" };
      if(apiKey) headers["x-gemini-api-key"] = apiKey;

      const res = await fetch("/api/generate-budgets", {
        method: "POST",
        headers,
        body: JSON.stringify({ items })
      });
      
      if(!res.ok) throw new Error(await res.text());
      const data = await res.json();
      
      renderBudgets(data);
    } catch (e) {
      alert("Error: " + e.message);
    } finally {
      budgetsLoader.classList.add("hidden");
      budgetsLoader.classList.remove("flex");
    }
  });

  function renderBudgets(data) {
    lastBudgetsData = data;
    selectedBudgetCost = 0;
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
        useInvestmentBtn.classList.remove("hidden");
      });
      
      budgetsGrid.appendChild(card);
    });

    // Auto-seleccionar tarjeta estándar o coincidente con inversión actual
    const currentInv = parseFloat(document.getElementById("initialInvestment")?.value || 0);
    const cards = budgetsGrid.querySelectorAll(":scope > div");
    let matchedCard = null;
    let matchedCost = 0;
    data.budgets.forEach((b, idx) => {
      if (Math.abs(b.total_cost - currentInv) < 1) {
        matchedCard = cards[idx];
        matchedCost = b.total_cost;
      } else if (!matchedCard && (b.budget_type.toLowerCase().includes("están") || b.budget_type.toLowerCase().includes("estan"))) {
        matchedCard = cards[idx];
        matchedCost = b.total_cost;
      }
    });
    if (!matchedCard && cards.length > 0) {
      matchedCard = cards[Math.min(1, cards.length - 1)];
      matchedCost = data.budgets[Math.min(1, cards.length - 1)].total_cost;
    }
    if (matchedCard) {
      matchedCard.classList.add("ring-2", "ring-emerald-500");
      selectedBudgetCost = matchedCost;
      useInvestmentBtn.classList.remove("hidden");
    }
    
    budgetsSummary.textContent = data.summary;
    budgetsOutput.classList.remove("hidden");
    scheduleAutoSave();
  }

  useInvestmentBtn.addEventListener("click", () => {
    document.getElementById("initialInvestment").value = selectedBudgetCost;
    document.getElementById("initialInvestment").setAttribute("readonly", true);
    document.getElementById("initialInvestment").classList.add("bg-zinc-800", "cursor-not-allowed");
    alert(`Inversión de $${selectedBudgetCost.toLocaleString('es-MX')} aplicada al modelo.`);
    scheduleAutoSave();
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

  genFlowchartBtn.addEventListener("click", async () => {
    const desc = processDesc.value.trim();
    if(!desc) { alert("Describe el proceso primero."); return; }

    flowOutput.classList.add("hidden");
    flowLoader.classList.remove("hidden");
    flowLoader.classList.add("flex");
    
    try {
      const apiKey = localStorage.getItem("gemini_api_key");
      const headers = { "Content-Type": "application/json" };
      if(apiKey) headers["x-gemini-api-key"] = apiKey;

      const res = await fetch("/api/generate-flowchart", {
        method: "POST",
        headers,
        body: JSON.stringify({ process_description: desc })
      });
      
      if(!res.ok) throw new Error(await res.text());
      const data = await res.json();
      
      renderFlowchart(data);
    } catch (e) {
      alert("Error: " + e.message);
    } finally {
      flowLoader.classList.add("hidden");
      flowLoader.classList.remove("flex");
    }
  });

  async function drawMermaid(code) {
    const holder = document.createElement("div");
    holder.className = "mermaid w-full";
    holder.textContent = code;
    mermaidContainer.innerHTML = "";
    mermaidContainer.appendChild(holder);
    try {
      if (!window.mermaid) throw new Error("Mermaid aún no está cargado");
      await window.mermaid.run({ nodes: [holder] });
      pendingMermaidCode = null;
      const svg = holder.querySelector("svg");
      if (svg) {
        const vb = (svg.getAttribute("viewBox") || "").split(/\s+/).map(Number);
        const naturalW = vb.length === 4 ? vb[2] : 0;
        const containerW = mermaidContainer.clientWidth || 800;
        const targetW = Math.max(Math.min(naturalW, containerW), naturalW * 0.85);
        svg.style.maxWidth = "none";
        svg.style.width = `${Math.round(targetW)}px`;
        svg.style.height = "auto";
        svg.style.margin = "0 auto";
        svg.style.display = "block";
      }
    } catch(e) {
      console.error("Mermaid error:", e);
      const pre = document.createElement("pre");
      pre.className = "text-[10px] text-rose-400 whitespace-pre-wrap";
      pre.textContent = "Error renderizando diagrama. Código:\n" + code;
      mermaidContainer.innerHTML = "";
      mermaidContainer.appendChild(pre);
    }
  }

  window.renderPendingMermaid = () => {
    if (pendingMermaidCode) drawMermaid(pendingMermaidCode);
  };

  async function renderFlowchart(data) {
    lastFlowchartData = data;
    // Mermaid
    let code = data.mermaid_code || "";
    if(code.startsWith("```mermaid")) code = code.substring(10);
    if(code.startsWith("```")) code = code.substring(3);
    if(code.endsWith("```")) code = code.substring(0, code.length-3);
    code = code.trim();

    const tab2 = document.getElementById("tab2");
    if (tab2 && tab2.classList.contains("hidden")) {
      // Se dibuja al abrir la pestaña Procesos
      pendingMermaidCode = code;
      mermaidContainer.innerHTML = "";
    } else {
      pendingMermaidCode = code;
      flowOutput.classList.remove("hidden");
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

  processDesc.addEventListener("input", () => scheduleAutoSave());

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
    // Pestaña 1: renglones de equipo
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
    // Resultados de presupuestos
    if (eng.budgets && Array.isArray(eng.budgets.budgets) && eng.budgets.budgets.length) {
      renderBudgets(eng.budgets);
    } else {
      lastBudgetsData = null;
      budgetsGrid.innerHTML = "";
      budgetsSummary.textContent = "";
      budgetsOutput.classList.add("hidden");
      useInvestmentBtn.classList.add("hidden");
    }
    // Pestaña 2: proceso y diagrama
    processDesc.value = eng.process_description || "";
    if (eng.flowchart && eng.flowchart.mermaid_code) {
      renderFlowchart(eng.flowchart);
    } else {
      lastFlowchartData = null;
      pendingMermaidCode = null;
      mermaidContainer.innerHTML = "";
      activitiesTable.innerHTML = "";
      consumablesTable.innerHTML = "";
      totalConsumablesCost.textContent = "$0";
      flowOutput.classList.add("hidden");
    }
  };


  const generateKeyBtn = document.getElementById("generateKeyBtn");
  const exportKeyInput = document.getElementById("exportKeyInput");
  const copyKeyBtn = document.getElementById("copyKeyBtn");
  
  if (generateKeyBtn) {
    generateKeyBtn.addEventListener("click", () => {
      const data = {
        name: document.getElementById("businessName").value,
        type: document.getElementById("businessType").value,
        investment: document.getElementById("initialInvestment").value,
        monthlyFixedCosts: document.getElementById("monthlyFixedCosts").value,
        price: document.getElementById("monthlyPrice").value,
        units: document.getElementById("monthlyUnits").value,
        varCost: document.getElementById("unitVariableCost").value,
        shrinkageLossPct: document.getElementById("shrinkageLossPct") ? document.getElementById("shrinkageLossPct").value : 2.0
      };
      const key = btoa(JSON.stringify(data));
      exportKeyInput.value = key;
    });
  }

  if (copyKeyBtn) {
    copyKeyBtn.addEventListener("click", () => {
      if (exportKeyInput.value) {
        navigator.clipboard.writeText(exportKeyInput.value);
        alert("Clave copiada al portapapeles.");
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
    custom_api_key: localStorage.getItem("gemini_api_key") || null,
    gemini_model: localStorage.getItem("gemini_model") || "gemini-3.5-flash"
  };

  try {
    const headers = { "Content-Type": "application/json" };
    const savedKey = localStorage.getItem("gemini_api_key");
    if (savedKey) headers["X-Gemini-API-Key"] = savedKey;

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
