document.addEventListener("DOMContentLoaded", () => {
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

  addEqBtn.addEventListener("click", () => {
    const div = document.createElement("div");
    div.className = "flex gap-2 equipment-item mt-2";
    div.innerHTML = `
      <input type="text" placeholder="Ej: Equipo" class="eq-name w-1/3 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none">
      <input type="text" placeholder="Especificaciones" class="eq-desc flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none">
      <button type="button" class="text-rose-400 hover:text-rose-300 px-2" onclick="this.parentElement.remove()"><i class="fa-solid fa-xmark"></i></button>
    `;
    equipmentList.appendChild(div);
  });

  genBudgetsBtn.addEventListener("click", async () => {
    const items = [];
    document.querySelectorAll(".equipment-item").forEach(item => {
      const name = item.querySelector(".eq-name").value.trim();
      const desc = item.querySelector(".eq-desc").value.trim();
      if(name) items.push({name, description: desc});
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
    budgetsGrid.innerHTML = "";
    
    data.budgets.forEach(b => {
      let icon = "fa-star";
      let color = "text-indigo-400";
      if(b.budget_type.toLowerCase().includes("econ")) { icon = "fa-piggy-bank"; color = "text-emerald-400"; }
      if(b.budget_type.toLowerCase().includes("prem") || b.budget_type.toLowerCase().includes("alt")) { icon = "fa-gem"; color = "text-amber-400"; }

      const detailsHtml = b.details.map(d => `<li class="text-[10px] text-slate-300 mb-1 border-b border-slate-800 pb-1">${d}</li>`).join('');

      const card = document.createElement("div");
      card.className = "bg-slate-900 rounded-xl border border-slate-800 p-4 relative cursor-pointer hover:border-emerald-500 transition group";
      card.innerHTML = `
        <div class="text-xs font-bold text-slate-300 uppercase mb-2 flex items-center gap-1.5 ${color}">
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
    
    budgetsSummary.textContent = data.summary;
    budgetsOutput.classList.remove("hidden");
  }

  useInvestmentBtn.addEventListener("click", () => {
    // Save the selected cost to a global config so it can be read in index.html
    localStorage.setItem("econometrics_transfer_investment", selectedBudgetCost.toString());
    alert(`Inversión de $${selectedBudgetCost.toLocaleString('es-MX')} transferida. Vuelve a EconoMetrics para aplicarla.`);
  });


  // --- 2. DIAGRAMA DE FLUJO Y ENERGÍA ---
  const genFlowchartBtn = document.getElementById("genFlowchartBtn");
  const processDesc = document.getElementById("processDesc");
  const flowLoader = document.getElementById("flowLoader");
  const flowOutput = document.getElementById("flowOutput");
  const mermaidContainer = document.getElementById("mermaidContainer");
  const activitiesTable = document.getElementById("activitiesTable");
  const energyTable = document.getElementById("consumablesTable");
  const totalEnergyCost = document.getElementById("totalConsumablesCost");

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

  async function renderFlowchart(data) {
    // Mermaid
    let code = data.mermaid_code;
    if(code.startsWith("```mermaid")) code = code.substring(10);
    if(code.startsWith("```")) code = code.substring(3);
    if(code.endsWith("```")) code = code.substring(0, code.length-3);
    
    mermaidContainer.innerHTML = `<div class="mermaid">${code.trim()}</div>`;
    try {
       await window.mermaid.run({ nodes: document.querySelectorAll('.mermaid') });
    } catch(e) {
       console.error("Mermaid error:", e);
       mermaidContainer.innerHTML = `<pre class="text-[10px] text-rose-400">Error renderizando diagrama. Código:<br>${code}</pre>`;
    }

    // Activities
    activitiesTable.innerHTML = "";
    data.activities.forEach(a => {
      activitiesTable.innerHTML += `
        <tr>
          <td class="p-2 text-center text-slate-400 font-bold">${a.step_number}</td>
          <td class="p-2">
            <div class="font-medium text-slate-200">${a.activity}</div>
            <div class="text-[10px] text-slate-500">${a.movements}</div>
          </td>
          <td class="p-2 font-mono text-cyan-400">${a.time_estimate}</td>
        </tr>
      `;
    });

    // Energy
    energyTable.innerHTML = "";
    data.energy_table.forEach(e => {
      energyTable.innerHTML += `
        <tr>
          <td class="p-2 font-medium text-slate-200">${e.equipment}</td>
          <td class="p-2 text-right font-mono">${e.kw_h.toFixed(1)}</td>
          <td class="p-2 text-right font-mono text-amber-300">$${e.monthly_cost_estimate.toLocaleString('es-MX')}</td>
        </tr>
      `;
    });
    totalEnergyCost.textContent = `$${data.total_monthly_energy_cost.toLocaleString('es-MX')}`;

    flowOutput.classList.remove("hidden");
  }
});
