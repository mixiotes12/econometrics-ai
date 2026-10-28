document.addEventListener("DOMContentLoaded", () => {
  const projectSelect = document.getElementById("projectSelect");
  const recordForm = document.getElementById("recordForm");
  const recordsTableBody = document.getElementById("recordsTableBody");
  
  // Elements for goals
  const projectGoals = document.getElementById("projectGoals");
  const goalUnits = document.getElementById("goalUnits");
  const goalPrice = document.getElementById("goalPrice");
  const goalShrinkage = document.getElementById("goalShrinkage");
  const goalVariableCost = document.getElementById("goalVariableCost");
  
  // Elements for stats
  const statTotalUnits = document.getElementById("statTotalUnits");
  const statTotalRevenue = document.getElementById("statTotalRevenue");
  const statTotalShrinkage = document.getElementById("statTotalShrinkage");
  const statTotalExpenses = document.getElementById("statTotalExpenses");
  const analysisInsights = document.getElementById("analysisInsights");
  
  const clearDataBtn = document.getElementById("clearDataBtn");
  
  // Default date to today
  document.getElementById("recordDate").valueAsDate = new Date();

  // Load projects from EconoMetrics
  let savedProjects = [];
  try {
    savedProjects = JSON.parse(localStorage.getItem("econometrics_saved_projects")) || [];
  } catch(e) {}
  
  // Load tracker records
  let trackerRecords = {};
  try {
    trackerRecords = JSON.parse(localStorage.getItem("econometrics_tracker_records")) || {};
  } catch(e) {}

  // Populate select
  savedProjects.forEach(proj => {
    const opt = document.createElement("option");
    opt.value = proj.id;
    opt.textContent = `${proj.name} - ${new Date(proj.savedAt).toLocaleDateString()}`;
    projectSelect.appendChild(opt);
  });

  // Handle project selection
  projectSelect.addEventListener("change", (e) => {
    const projectId = e.target.value;
    if (!projectId) {
      projectGoals.classList.add("hidden");
      renderRecords(null);
      return;
    }
    
    const proj = savedProjects.find(p => p.id === projectId);
    if(proj) {
      projectGoals.classList.remove("hidden");
      projectGoals.classList.add("grid");
      
      const fin = proj.financials;
      
      // Calculate goals
      const monthlyRevenue = fin.monthly_units * fin.monthly_price;
      const monthlyShrinkageGoal = monthlyRevenue * (fin.shrinkage_risk_loss_pct / 100);
      
      goalUnits.textContent = `${fin.monthly_units.toLocaleString('es-MX')} uds`;
      goalPrice.textContent = `$${fin.monthly_price.toLocaleString('es-MX')}`;
      goalShrinkage.textContent = `$${monthlyShrinkageGoal.toLocaleString('es-MX')} (${fin.shrinkage_risk_loss_pct}%)`;
      goalVariableCost.textContent = `$${fin.unit_variable_cost.toLocaleString('es-MX')} / ud`;
      
      renderRecords(projectId);
    }
  });
  
  // Calculate analytics
  function formatMoney(num) {
    return '$' + num.toLocaleString('es-MX', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }

  function renderRecords(projectId) {
    recordsTableBody.innerHTML = "";
    
    if(!projectId) {
      statTotalUnits.textContent = "0";
      statTotalRevenue.textContent = "$0";
      statTotalShrinkage.textContent = "$0";
      statTotalExpenses.textContent = "$0";
      analysisInsights.innerHTML = `<p class="text-slate-400 italic text-xs">Selecciona un proyecto y agrega registros para ver el análisis de desviaciones.</p>`;
      return;
    }
    
    const records = trackerRecords[projectId] || [];
    
    // Sort records descending by date
    records.sort((a,b) => new Date(b.date) - new Date(a.date));
    
    let sumUnits = 0;
    let sumRev = 0;
    let sumShrink = 0;
    let sumExp = 0;
    
    records.forEach((r, idx) => {
      sumUnits += r.units;
      sumRev += r.revenue;
      sumShrink += r.shrinkage;
      sumExp += r.expenses;
      
      const tr = document.createElement("tr");
      tr.className = "hover:bg-slate-800/30 transition";
      tr.innerHTML = `
        <td class="px-4 py-2">${r.date}</td>
        <td class="px-4 py-2 text-right font-mono">${r.units}</td>
        <td class="px-4 py-2 text-right font-mono text-emerald-300">${formatMoney(r.revenue)}</td>
        <td class="px-4 py-2 text-right font-mono text-rose-300">${formatMoney(r.shrinkage)}</td>
        <td class="px-4 py-2 text-right font-mono text-amber-300">${formatMoney(r.expenses)}</td>
        <td class="px-4 py-2 text-center">
          <button onclick="deleteRecord('${projectId}', ${idx})" class="text-rose-500 hover:text-rose-400"><i class="fa-solid fa-trash"></i></button>
        </td>
      `;
      recordsTableBody.appendChild(tr);
    });
    
    if(records.length === 0) {
      recordsTableBody.innerHTML = `<tr><td colspan="6" class="px-4 py-4 text-center text-slate-500">No hay registros para este proyecto.</td></tr>`;
    }
    
    statTotalUnits.textContent = sumUnits;
    statTotalRevenue.textContent = formatMoney(sumRev);
    statTotalShrinkage.textContent = formatMoney(sumShrink);
    statTotalExpenses.textContent = formatMoney(sumExp);
    
    generateInsights(projectId, records, sumUnits, sumRev, sumShrink, sumExp);
  }
  
  function generateInsights(projectId, records, sumUnits, sumRev, sumShrink, sumExp) {
    if(records.length === 0) {
       analysisInsights.innerHTML = `<p class="text-slate-400 italic text-xs">Agrega registros para ver el análisis de desviaciones.</p>`;
       return;
    }
    
    const proj = savedProjects.find(p => p.id === projectId);
    const fin = proj.financials;
    
    const daysTracked = new Set(records.map(r => r.date)).size;
    const projectedDailyUnits = fin.monthly_units / 30;
    const projectedDailyRev = (fin.monthly_units * fin.monthly_price) / 30;
    
    const expectedUnits = projectedDailyUnits * daysTracked;
    const expectedRev = projectedDailyRev * daysTracked;
    
    const realPrice = sumUnits > 0 ? sumRev / sumUnits : 0;
    
    // Mermas check
    const maxShrinkageAllowed = sumRev * (fin.shrinkage_risk_loss_pct / 100);
    const shrinkStatus = sumShrink > maxShrinkageAllowed ? 
      `<span class="text-rose-400 font-bold"><i class="fa-solid fa-triangle-exclamation"></i> ALERTA: Mermas y robos ($${sumShrink}) superan el límite proyectado ($${maxShrinkageAllowed.toFixed(2)}). Revisa controles y seguridad.</span>` :
      `<span class="text-emerald-400"><i class="fa-solid fa-check"></i> Mermas bajo control.</span>`;
      
    // Variable cost check
    const expectedExpenses = sumUnits * fin.unit_variable_cost;
    const expStatus = sumExp > expectedExpenses ?
       `<span class="text-amber-400 font-bold"><i class="fa-solid fa-triangle-exclamation"></i> TUS COSTOS SON ALTOS: Gastaste ${formatMoney(sumExp)} pero tu presupuesto variable era de ${formatMoney(expectedExpenses)} para ${sumUnits} uds.</span>` :
       `<span class="text-emerald-400"><i class="fa-solid fa-check"></i> Gastos operativos dentro de presupuesto.</span>`;
       
    // Sales check
    const salesStatus = sumUnits < expectedUnits ?
       `<span class="text-rose-400"><i class="fa-solid fa-arrow-trend-down"></i> Ventas por debajo de meta (${sumUnits} vs ${expectedUnits.toFixed(1)} uds esperadas en ${daysTracked} días).</span>` :
       `<span class="text-emerald-400"><i class="fa-solid fa-arrow-trend-up"></i> ¡Ventas superan expectativas! (${sumUnits} vs ${expectedUnits.toFixed(1)} uds).</span>`;
       
    analysisInsights.innerHTML = `
      <ul class="space-y-3">
        <li class="p-3 bg-slate-950 rounded border border-slate-800">
          <strong>Rendimiento de Ventas:</strong> ${salesStatus}<br>
          <span class="text-xs text-slate-400 mt-1 block">Precio prom real: ${formatMoney(realPrice)} (Proyectado: ${formatMoney(fin.monthly_price)})</span>
        </li>
        <li class="p-3 bg-slate-950 rounded border border-slate-800">
          <strong>Control de Mermas/Robos:</strong> ${shrinkStatus}
        </li>
        <li class="p-3 bg-slate-950 rounded border border-slate-800">
          <strong>Eficiencia de Costos:</strong> ${expStatus}
        </li>
      </ul>
    `;
  }
  
  // Handle form submission
  recordForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const projectId = projectSelect.value;
    
    if(!projectId) {
      alert("Por favor selecciona un proyecto primero.");
      return;
    }
    
    if (!trackerRecords[projectId]) {
      trackerRecords[projectId] = [];
    }
    
    trackerRecords[projectId].push({
      date: document.getElementById("recordDate").value,
      units: parseFloat(document.getElementById("recordUnits").value),
      revenue: parseFloat(document.getElementById("recordRevenue").value),
      shrinkage: parseFloat(document.getElementById("recordShrinkage").value),
      expenses: parseFloat(document.getElementById("recordExpenses").value),
    });
    
    localStorage.setItem("econometrics_tracker_records", JSON.stringify(trackerRecords));
    
    // Clear form except date
    document.getElementById("recordUnits").value = "";
    document.getElementById("recordRevenue").value = "";
    document.getElementById("recordShrinkage").value = "0";
    document.getElementById("recordExpenses").value = "0";
    
    renderRecords(projectId);
  });
  
  clearDataBtn.addEventListener("click", () => {
    const projectId = projectSelect.value;
    if(!projectId) return;
    
    if(confirm("¿Estás seguro de borrar todo el historial de este proyecto?")) {
      trackerRecords[projectId] = [];
      localStorage.setItem("econometrics_tracker_records", JSON.stringify(trackerRecords));
      renderRecords(projectId);
    }
  });
  
  // Delete single record
  window.deleteRecord = function(projectId, idx) {
    if(confirm("¿Eliminar registro?")) {
      trackerRecords[projectId].splice(idx, 1);
      localStorage.setItem("econometrics_tracker_records", JSON.stringify(trackerRecords));
      renderRecords(projectId);
    }
  };

  const importKeyInput = document.getElementById("importKeyInput");
  const importKeyBtn = document.getElementById("importKeyBtn");
  
  if (importKeyBtn) {
    importKeyBtn.addEventListener("click", () => {
      try {
        const val = importKeyInput.value.trim();
        if(!val) return;
        const decoded = JSON.parse(atob(val));
        
        if(!decoded || typeof decoded !== 'object' || !decoded.name || !decoded.investment) {
          throw new Error("Clave inválida o corrupta.");
        }
        
        const newProj = {
          id: 'imported_' + Date.now(),
          name: decoded.name || 'Proyecto Importado',
          savedAt: new Date().toISOString(),
          business: {
            name: decoded.name,
            business_type: decoded.type
          },
          financials: {
            initial_investment: parseFloat(decoded.investment) || 0,
            monthly_fixed_costs: parseFloat(decoded.monthlyFixedCosts) || 0,
            monthly_price: parseFloat(decoded.price) || 0,
            monthly_units: parseFloat(decoded.units) || 0,
            unit_variable_cost: parseFloat(decoded.varCost) || 0,
            shrinkage_risk_loss_pct: parseFloat(decoded.shrinkageLossPct) || 2.0
          }
        };
        
        savedProjects.push(newProj);
        localStorage.setItem("econometrics_saved_projects", JSON.stringify(savedProjects));
        
        const opt = document.createElement("option");
        opt.value = newProj.id;
        opt.textContent = `${newProj.name} - ${new Date(newProj.savedAt).toLocaleDateString()} (Importado)`;
        projectSelect.appendChild(opt);
        projectSelect.value = newProj.id;
        projectSelect.dispatchEvent(new Event('change'));
        
        alert("Proyecto importado con éxito.");
        importKeyInput.value = "";
      } catch(e) {
        alert("Clave inválida. Asegúrate de copiarla completa desde EconoMetrics.");
      }
    });
  }

});
