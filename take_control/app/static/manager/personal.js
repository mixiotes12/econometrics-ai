/* Personal y Seguridad - Fase 3 */
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => "$" + Number(n || 0).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const val = (id) => $(id).value;
  const fnum = (id) => parseFloat($(id).value) || 0;
  const today = () => new Date().toISOString().slice(0, 10);

  let token = sessionStorage.getItem("pos_token") || "";
  let me = JSON.parse(sessionStorage.getItem("pos_me") || "null");
  let areas = [], users = [], employees = [], rolesData = null;

  const can = (perm) => !!me && (me.is_admin || (me.permissions || []).includes(perm));
  const canAny = (spec) => spec.split("|").some(can);

  async function api(path, opts = {}) {
    const res = await fetch("/api/hr" + path, {
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
  const msg = (id, text, ok = true) => { $(id).innerHTML = `<span class="${ok ? "text-emerald-400" : "text-red-400"}">${esc(text)}</span>`; setTimeout(() => ($(id).innerHTML = ""), 5000); };
  const areaOptions = (withEmpty = true) => (withEmpty ? '<option value="">— Sin área —</option>' : "") + areas.filter((a) => a.active).map((a) => `<option value="${a.id}">${esc(a.name)}</option>`).join("");

  // ---------- Tabs
  function switchTab(name) {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("hidden", p.id !== "tab-" + name));
    const loaders = { usuarios: loadUsers, roles: loadRoles, areas: loadAreas, personal: loadEmployees, asistencia: loadAttendance, nomina: loadPayroll, bitacora: loadAudit };
    loaders[name]().catch((e) => alert(e.message));
  }

  // ---------- Reloj checador (usuario vinculado a empleado)
  async function refreshClock() {
    const b = $("clockBtn");
    try {
      const st = await api("/attendance/status");
      if (!st.linked) return b.classList.add("hidden");
      b.classList.remove("hidden");
      b.innerHTML = st.clocked_in ? '<i class="fa-solid fa-right-from-bracket mr-1"></i>Registrar salida' : '<i class="fa-solid fa-right-to-bracket mr-1"></i>Registrar entrada';
      b.className = "btn " + (st.clocked_in ? "btn-red" : "btn-pri");
    } catch { b.classList.add("hidden"); }
  }

  // ---------- Usuarios
  async function loadUsers() {
    [areas, users] = await Promise.all([api("/areas"), api("/users")]);
    $("uArea").innerHTML = areaOptions();
    $("usersBody").innerHTML = users.map((u) => `<tr class="${u.active ? "" : "opacity-50"}"><td><b>${esc(u.name)}</b><div class="text-[10px] text-zinc-500">${esc(u.email || "")} ${esc(u.phone || "")}</div></td>
      <td><span class="pill bg-violet-900 text-violet-200">${esc(u.role_label)}</span></td><td>${esc(u.area_name || "—")}</td><td>${esc(u.last_login || "Nunca")}</td>
      <td>${u.locked ? '<span class="pill bg-red-900 text-red-300">Bloqueado</span>' : u.active ? "Activo" : "Inactivo"}${u.must_change_pin ? ' <span class="pill bg-amber-900 text-amber-300">PIN por cambiar</span>' : ""}</td>
      <td class="whitespace-nowrap"><button class="btn btn-sec !py-0.5" data-edituser="${u.id}">Editar</button>
      ${u.locked ? `<button class="btn btn-pri !py-0.5" data-unlock="${u.id}">Desbloquear</button>` : ""}</td></tr>`).join("");
  }
  function resetUserForm() {
    $("userForm").reset(); $("uId").value = ""; $("uActive").checked = true; $("uRole").value = "cajero"; $("uArea").value = "";
  }

  // ---------- Roles
  async function loadRoles() {
    rolesData = await api("/roles");
    const r = rolesData.roles;
    $("rolesTable").innerHTML = `<thead><tr><th>Permiso</th>${r.map((x) => `<th class="text-center">${esc(x.label)}</th>`).join("")}</tr></thead><tbody>` +
      Object.entries(rolesData.permissions).map(([p, d]) => `<tr><td>${esc(d)}<div class="text-[10px] text-zinc-500">${p}</div></td>${
        r.map((x) => `<td class="text-center">${x.permissions.includes(p) ? '<i class="fa-solid fa-check text-emerald-400"></i>' : '<span class="text-zinc-700">—</span>'}</td>`).join("")}</tr>`).join("") + "</tbody>";
  }
  async function ensureRoles() {
    if (!rolesData) rolesData = await api("/roles");
    $("uRole").innerHTML = rolesData.roles.map((r) => `<option value="${r.key}">${esc(r.label)}</option>`).join("");
  }

  // ---------- Áreas
  async function loadAreas() {
    areas = await api("/areas");
    $("areasBody").innerHTML = areas.map((a) => `<tr class="${a.active ? "" : "opacity-50"}"><td><b>${esc(a.name)}</b></td><td>${esc(a.description)}</td><td>${a.users}</td><td>${a.employees}</td><td>${a.active ? "Activa" : "Inactiva"}</td>
      <td><button class="btn btn-sec !py-0.5" data-editarea="${a.id}">Editar</button></td></tr>`).join("");
  }

  // ---------- Personal
  async function loadEmployees() {
    const canEdit = can("hr.manage");
    document.querySelectorAll(".hr-edit").forEach((el) => el.classList.toggle("hidden", !canEdit));
    [areas, employees] = await Promise.all([api("/areas"), api("/employees?include_inactive=" + $("eInactive").checked)]);
    $("eArea").innerHTML = areaOptions();
    if (can("users.manage")) users = await api("/users");
    $("eUser").innerHTML = '<option value="">— Sin usuario —</option>' + users.filter((u) => u.active).map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("");
    $("iEmp").innerHTML = employees.filter((e) => e.status === "activo").map((e) => `<option value="${e.id}">${esc(e.name)}</option>`).join("");
    $("empBody").innerHTML = employees.map((e) => `<tr class="${e.status === "activo" ? "" : "opacity-50"}"><td><b>${esc(e.name)}</b></td><td>${esc(e.position)}</td><td>${esc(e.area_name || "—")}</td>
      <td>${esc(e.user_name || "—")}</td><td>${fmt(e.monthly_salary)}</td><td>${esc(e.hire_date || "—")}</td><td>${esc(e.status)}</td>
      <td>${canEdit ? `<button class="btn btn-sec !py-0.5" data-editemp="${e.id}">Editar</button>` : ""}</td></tr>`).join("");
    const inc = await api("/incidences");
    $("incBody").innerHTML = inc.map((i) => `<tr><td>${esc(i.date)}</td><td>${esc(i.employee_name)}</td><td>${esc(i.type.replace("_", " "))}</td>
      <td>${["bono", "deduccion", "hora_extra"].includes(i.type) ? fmt(i.amount) : i.amount + " d"}</td><td>${esc(i.note)}</td>
      <td>${canEdit ? `<button class="text-red-400" data-delinc="${i.id}"><i class="fa-solid fa-trash"></i></button>` : ""}</td></tr>`).join("");
  }
  function resetEmpForm() { $("empForm").reset(); $("eId").value = ""; $("eStatus").value = "activo"; $("ePayFreq").value = "quincenal"; }
  function fillEmpForm(e) {
    $("eId").value = e.id; $("eName").value = e.name; $("ePosition").value = e.position; $("eArea").value = e.area_id ?? "";
    $("eUser").value = e.user_id ?? ""; $("eSalary").value = e.monthly_salary; $("ePayFreq").value = e.pay_frequency;
    $("eHire").value = e.hire_date || ""; $("eStatus").value = e.status; $("eTerm").value = e.termination_date || "";
    $("eRfc").value = e.rfc; $("eCurp").value = e.curp; $("eNss").value = e.nss; $("ePhone").value = e.phone; $("eEmail").value = e.email; $("eNotes").value = e.notes;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // ---------- Asistencia
  async function loadAttendance() {
    if (!$("tFrom").value) { const d = new Date(); d.setDate(d.getDate() - 14); $("tFrom").value = d.toISOString().slice(0, 10); $("tTo").value = today(); }
    const manager = can("hr.manage");
    $("tEmpBox").classList.toggle("hidden", !manager);
    if (manager && !$("tEmp").options.length) {
      const emps = await api("/employees");
      $("tEmp").innerHTML = '<option value="">Todos</option>' + emps.map((e) => `<option value="${e.id}">${esc(e.name)}</option>`).join("");
    }
    const q = new URLSearchParams({ date_from: val("tFrom"), date_to: val("tTo") });
    if (manager && val("tEmp")) q.set("employee_id", val("tEmp"));
    const rows = await api("/attendance?" + q);
    const st = await api("/attendance/status");
    $("tLinkMsg").textContent = !manager && !st.linked ? "Tu usuario no está vinculado a un empleado (pide a RRHH vincularlo)." : "";
    $("attBody").innerHTML = rows.map((r) => `<tr><td>${esc(r.work_date)}</td><td>${esc(r.employee_name)}</td><td>${esc(r.check_in.slice(11, 16))}</td>
      <td>${r.check_out ? esc(r.check_out.slice(11, 16)) : '<span class="text-amber-400">en turno</span>'}</td><td>${r.hours ?? "—"}</td><td></td></tr>`).join("");
    $("attTotal").textContent = `Horas registradas: ${rows.reduce((a, r) => a + (r.hours || 0), 0).toFixed(2)} h en ${rows.length} registro(s).`;
  }

  // ---------- Nómina
  async function loadPayroll() {
    if (!$("pMonth").value) $("pMonth").value = today().slice(0, 7);
    document.querySelectorAll(".hr-edit").forEach((el) => el.classList.toggle("hidden", !can("hr.manage")));
    const [y, m] = val("pMonth").split("-");
    const [p, labor] = await Promise.all([api(`/payroll?year=${y}&month=${+m}&period=${val("pPeriod")}`), api("/labor-cost")]);
    $("cBurden").value = p.settings.payroll_burden_pct; $("cAgui").value = p.settings.aguinaldo_days; $("cVac").value = p.settings.vacation_days; $("cPrima").value = p.settings.prima_vac_pct;
    const t = p.totals;
    const card = (l, v, c = "") => `<div class="card"><div class="text-[11px] text-zinc-400">${l}</div><div class="text-xl font-bold ${c}">${v}</div></div>`;
    $("payCards").innerHTML = card("Pago bruto del periodo", fmt(t.gross_pay)) + card("Carga patronal", fmt(t.employer_burden)) + card("Provisiones (aguinaldo + prima)", fmt(t.provisions)) + card("Costo total empresa", fmt(t.employer_cost), "text-violet-300");
    $("payBody").innerHTML = p.rows.map((r) => `<tr><td><b>${esc(r.name)}</b><div class="text-[10px] text-zinc-500">${esc(r.position)}</div></td><td>${esc(r.area)}</td><td>${fmt(r.base_period)}</td>
      <td>${r.faltas_dias ? `${r.faltas_dias} d (−${fmt(r.descuento_faltas)})` : "—"}</td><td>${fmt(r.bonos + r.horas_extra)}</td><td>${fmt(r.deducciones)}</td>
      <td>${fmt(r.gross_pay)}</td><td>${fmt(r.employer_burden)}</td><td>${fmt(r.provisions)}</td><td><b>${fmt(r.employer_cost)}</b></td></tr>`).join("") ||
      '<tr><td colspan="10" class="text-center text-zinc-500">Sin empleados en el periodo.</td></tr>';
    $("payNote").textContent = `${p.start} a ${p.end}. ${p.disclaimer}`;
    $("areaCostBody").innerHTML = p.by_area.map((a) => `<tr><td>${esc(a.area)}</td><td>${a.headcount}</td><td>${fmt(a.gross_pay)}</td><td>${fmt(a.employer_cost)}</td></tr>`).join("");
    $("laborBox").innerHTML = `<div>Plantilla activa: <b>${labor.headcount}</b> · Sueldos: <b>${fmt(labor.monthly_base_salaries)}</b> · Carga patronal: <b>${fmt(labor.monthly_employer_burden)}</b> · Provisiones: <b>${fmt(labor.monthly_provisions)}</b></div>
      <div class="mt-1">Costo laboral mensual: <b class="text-violet-300 text-lg">${fmt(labor.monthly_total_cost)}</b> · Anual: <b>${fmt(labor.annual_total_cost)}</b></div>`;
  }

  // ---------- Bitácora
  async function loadAudit() {
    const q = new URLSearchParams({ days: val("bDays") || 7 });
    if (val("bAction")) q.set("action", val("bAction"));
    if (val("bQ")) q.set("q", val("bQ"));
    const r = await api("/audit?" + q);
    const cur = val("bAction");
    $("bAction").innerHTML = '<option value="">Todas</option>' + r.actions.map((a) => `<option ${a === cur ? "selected" : ""}>${esc(a)}</option>`).join("");
    $("auditBody").innerHTML = r.items.map((a) => `<tr><td class="whitespace-nowrap">${esc(a.created_at)}</td><td>${esc(a.user_name)}</td><td><span class="pill bg-zinc-700">${esc(a.action)}</span></td><td>${esc(a.detail)}</td></tr>`).join("");
  }

  // ---------- Eventos
  function bind() {
    $("tabs").addEventListener("click", (e) => { const b = e.target.closest(".tab-btn"); if (b) switchTab(b.dataset.tab); });
    $("clockBtn").onclick = async () => {
      try { const r = await api("/attendance/clock", { method: "POST", body: {} }); alert(`Registro de ${r.action} para ${r.employee}: ${r.time.slice(11, 16)}`); await refreshClock(); if (!$("tab-asistencia").classList.contains("hidden")) loadAttendance(); }
      catch (e) { alert(e.message); }
    };

    $("userForm").onsubmit = async (e) => {
      e.preventDefault();
      const body = { name: val("uName"), role: val("uRole"), area_id: val("uArea") ? +val("uArea") : null, email: val("uEmail"), phone: val("uPhone"), pin: val("uPin") || null, active: $("uActive").checked };
      try {
        const id = val("uId");
        await api(id ? "/users/" + id : "/users", { method: id ? "PUT" : "POST", body });
        resetUserForm(); msg("uMsg", "Usuario guardado."); await loadUsers();
      } catch (er) { msg("uMsg", er.message, false); }
    };
    $("uReset").onclick = resetUserForm;
    $("usersBody").addEventListener("click", async (e) => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.edituser) {
        const u = users.find((x) => x.id === +b.dataset.edituser);
        $("uId").value = u.id; $("uName").value = u.name; $("uRole").value = u.role; $("uArea").value = u.area_id ?? ""; $("uEmail").value = u.email; $("uPhone").value = u.phone;
        $("uPin").value = ""; $("uActive").checked = !!u.active; window.scrollTo({ top: 0, behavior: "smooth" });
      } else if (b.dataset.unlock) { try { await api(`/users/${b.dataset.unlock}/unlock`, { method: "POST" }); await loadUsers(); } catch (er) { alert(er.message); } }
    });

    $("areaForm").onsubmit = async (e) => {
      e.preventDefault();
      const body = { name: val("aName"), description: val("aDesc"), active: $("aActive").checked };
      try { const id = val("aId"); await api(id ? "/areas/" + id : "/areas", { method: id ? "PUT" : "POST", body }); $("areaForm").reset(); $("aId").value = ""; $("aActive").checked = true; await loadAreas(); }
      catch (er) { alert(er.message); }
    };
    $("aReset").onclick = () => { $("areaForm").reset(); $("aId").value = ""; $("aActive").checked = true; };
    $("areasBody").addEventListener("click", (e) => {
      const b = e.target.closest("[data-editarea]"); if (!b) return;
      const a = areas.find((x) => x.id === +b.dataset.editarea);
      $("aId").value = a.id; $("aName").value = a.name; $("aDesc").value = a.description; $("aActive").checked = !!a.active;
    });

    $("empForm").onsubmit = async (e) => {
      e.preventDefault();
      const body = { name: val("eName"), position: val("ePosition"), area_id: val("eArea") ? +val("eArea") : null, user_id: val("eUser") ? +val("eUser") : null,
        monthly_salary: fnum("eSalary"), pay_frequency: val("ePayFreq"), hire_date: val("eHire") || null, status: val("eStatus"), termination_date: val("eTerm") || null,
        rfc: val("eRfc"), curp: val("eCurp"), nss: val("eNss"), phone: val("ePhone"), email: val("eEmail"), notes: val("eNotes") };
      try { const id = val("eId"); await api(id ? "/employees/" + id : "/employees", { method: id ? "PUT" : "POST", body }); resetEmpForm(); msg("eMsg", "Empleado guardado."); await loadEmployees(); refreshClock(); }
      catch (er) { msg("eMsg", er.message, false); }
    };
    $("eReset").onclick = resetEmpForm;
    $("eInactive").onchange = () => loadEmployees().catch((e) => alert(e.message));
    $("empBody").addEventListener("click", (e) => { const b = e.target.closest("[data-editemp]"); if (b) fillEmpForm(employees.find((x) => x.id === +b.dataset.editemp)); });
    $("incForm").onsubmit = async (e) => {
      e.preventDefault();
      try { await api("/incidences", { method: "POST", body: { employee_id: +val("iEmp"), date: val("iDate"), type: val("iType"), amount: fnum("iAmount"), note: val("iNote") } });
        $("iAmount").value = ""; $("iNote").value = ""; msg("iMsg", "Incidencia registrada."); await loadEmployees(); }
      catch (er) { msg("iMsg", er.message, false); }
    };
    $("incBody").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-delinc]"); if (!b || !confirm("¿Eliminar incidencia?")) return;
      try { await api("/incidences/" + b.dataset.delinc, { method: "DELETE" }); await loadEmployees(); } catch (er) { alert(er.message); }
    });

    $("tRefresh").onclick = () => loadAttendance().catch((e) => alert(e.message));
    $("pRefresh").onclick = () => loadPayroll().catch((e) => alert(e.message));
    $("cSave").onclick = async () => {
      try { await api("/payroll/settings", { method: "PUT", body: { payroll_burden_pct: fnum("cBurden"), aguinaldo_days: fnum("cAgui"), vacation_days: fnum("cVac"), prima_vac_pct: fnum("cPrima") } }); await loadPayroll(); }
      catch (er) { alert(er.message); }
    };
    $("bRefresh").onclick = () => loadAudit().catch((e) => alert(e.message));
  }

  document.addEventListener("DOMContentLoaded", async () => {
    if (!token || !me) return showNoSession();
    try { me = await api("/me"); sessionStorage.setItem("pos_me", JSON.stringify(me)); } catch { return; }
    $("whoami").textContent = `${me.name} · ${me.role_label}`;
    document.querySelectorAll("[data-perm]").forEach((b) => b.classList.toggle("hidden", !canAny(b.dataset.perm)));
    bind();
    await ensureRoles().catch(() => {});
    if (can("users.manage")) { try { areas = await api("/areas"); $("uArea").innerHTML = areaOptions(); } catch {} }
    refreshClock();
    const first = [...document.querySelectorAll(".tab-btn")].find((b) => !b.classList.contains("hidden"));
    if (first) switchTab(first.dataset.tab);
  });
})();
