"""
Módulo Personal & Seguridad (Fase 3)
- Usuarios con roles (niveles de control), áreas organizacionales y bitácora de actividad
- Control de personal: empleados, asistencia (reloj checador), incidencias
- Nómina estimada y costo laboral mensual (enlazable a los costos fijos del análisis financiero)

Nota: la nómina es una ESTIMACIÓN para costeo (no calcula ISR/IMSS del trabajador ni timbra recibos).
"""
import calendar
import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .pos import (PERMISSIONS, ROLES, SESSIONS, audit, current_cashier, db, get_settings, has_perm, hash_pin,
                  money, now, require, require_any, user_permissions)

router = APIRouter(prefix="/api/hr", tags=["Personal y Seguridad"])

DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
PAYROLL_KEYS = ("payroll_burden_pct", "aguinaldo_days", "vacation_days", "prima_vac_pct")
INCIDENCE_TYPES = {"falta", "bono", "deduccion", "hora_extra", "vacaciones", "incapacidad"}


# ------------------------------------------------------------------ yo / roles
@router.get("/me")
def me_info(me: dict = Depends(current_cashier)):
    return {"id": me["id"], "name": me["name"], "role": me["role"], "role_label": ROLES[me["role"]]["label"],
            "is_admin": me["role"] == "admin", "permissions": user_permissions(me), "area_id": me["area_id"]}


class PinChange(BaseModel):
    current_pin: str
    new_pin: str = Field(pattern=r"^\d{4,8}$")


@router.post("/me/pin")
def change_own_pin(body: PinChange, me: dict = Depends(current_cashier)):
    if me["pin_hash"] != hash_pin(body.current_pin):
        raise HTTPException(400, "El PIN actual es incorrecto.")
    if body.new_pin == body.current_pin:
        raise HTTPException(400, "El nuevo PIN debe ser distinto al actual.")
    if body.new_pin in ("1234", "0000", "1111"):
        raise HTTPException(400, "Elige un PIN menos obvio.")
    with db() as conn:
        conn.execute("UPDATE cashiers SET pin_hash=?, must_change_pin=0 WHERE id=?", (hash_pin(body.new_pin), me["id"]))
        audit(conn, me, "pin_cambiado", "", "usuario")
    return {"ok": True}


@router.get("/roles")
def roles(_: dict = Depends(current_cashier)):
    return {
        "roles": [{"key": k, "label": v["label"], "permissions": list(PERMISSIONS) if "*" in v["perms"] else v["perms"]}
                  for k, v in ROLES.items()],
        "permissions": PERMISSIONS,
    }


# ------------------------------------------------------------------ áreas
class AreaIn(BaseModel):
    name: str = Field(min_length=2)
    description: str = ""
    active: bool = True


@router.get("/areas")
def list_areas(_: dict = Depends(current_cashier)):
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT a.*, (SELECT COUNT(*) FROM cashiers c WHERE c.area_id=a.id AND c.active=1) users, "
            "(SELECT COUNT(*) FROM employees e WHERE e.area_id=a.id AND e.status='activo') employees "
            "FROM areas a ORDER BY a.name")]


@router.post("/areas")
def create_area(a: AreaIn, me: dict = Depends(require("users.manage"))):
    with db() as conn:
        if conn.execute("SELECT 1 FROM areas WHERE name=?", (a.name.strip(),)).fetchone():
            raise HTTPException(400, "Ya existe un área con ese nombre.")
        cur = conn.execute("INSERT INTO areas(name, description, active) VALUES (?,?,?)", (a.name.strip(), a.description, int(a.active)))
        audit(conn, me, "area_creada", a.name, "area")
        return {"id": cur.lastrowid}


@router.put("/areas/{aid}")
def update_area(aid: int, a: AreaIn, me: dict = Depends(require("users.manage"))):
    with db() as conn:
        dup = conn.execute("SELECT 1 FROM areas WHERE name=? AND id<>?", (a.name.strip(), aid)).fetchone()
        if dup:
            raise HTTPException(400, "Ya existe un área con ese nombre.")
        conn.execute("UPDATE areas SET name=?, description=?, active=? WHERE id=?", (a.name.strip(), a.description, int(a.active), aid))
        audit(conn, me, "area_editada", a.name, "area")
    return {"ok": True}


# ------------------------------------------------------------------ usuarios
class UserIn(BaseModel):
    name: str = Field(min_length=2)
    role: str = "cajero"
    area_id: Optional[int] = None
    email: str = ""
    phone: str = ""
    pin: Optional[str] = Field(default=None, pattern=r"^\d{4,8}$")
    active: bool = True


def _user_row(r) -> dict:
    d = {k: r[k] for k in ("id", "name", "role", "area_id", "email", "phone", "active", "created_at", "last_login", "locked_until", "must_change_pin")}
    d["role_label"] = ROLES.get(r["role"], {}).get("label", r["role"])
    d["area_name"] = r["area_name"]
    d["locked"] = bool(r["locked_until"] and r["locked_until"] > now())
    return d


def _check_user(conn, u: UserIn):
    if u.role not in ROLES:
        raise HTTPException(400, "Rol inválido.")
    if u.area_id is not None and not conn.execute("SELECT 1 FROM areas WHERE id=?", (u.area_id,)).fetchone():
        raise HTTPException(400, "Área inexistente.")


@router.get("/users")
def list_users(_: dict = Depends(require("users.manage"))):
    with db() as conn:
        rows = conn.execute("SELECT c.*, a.name area_name FROM cashiers c LEFT JOIN areas a ON a.id=c.area_id ORDER BY c.id").fetchall()
    return [_user_row(r) for r in rows]


@router.post("/users")
def create_user(u: UserIn, me: dict = Depends(require("users.manage"))):
    if not u.pin:
        raise HTTPException(400, "El PIN (4 a 8 dígitos) es obligatorio.")
    with db() as conn:
        _check_user(conn, u)
        cur = conn.execute(
            "INSERT INTO cashiers(name, pin_hash, is_admin, active, created_at, role, area_id, email, phone, must_change_pin) "
            "VALUES (?,?,?,?,?,?,?,?,?,1)",
            (u.name.strip(), hash_pin(u.pin), int(u.role == "admin"), int(u.active), now(), u.role, u.area_id, u.email, u.phone))
        audit(conn, me, "usuario_creado", f"{u.name} ({u.role})", "usuario")
        return {"id": cur.lastrowid}


@router.put("/users/{uid}")
def update_user(uid: int, u: UserIn, me: dict = Depends(require("users.manage"))):
    with db() as conn:
        old = conn.execute("SELECT * FROM cashiers WHERE id=?", (uid,)).fetchone()
        if not old:
            raise HTTPException(404, "Usuario no encontrado.")
        _check_user(conn, u)
        if uid == me["id"] and (not u.active or u.role != "admin"):
            raise HTTPException(400, "No puedes desactivarte ni quitarte el rol de administrador a ti mismo.")
        if old["role"] == "admin" and (u.role != "admin" or not u.active):
            others = conn.execute("SELECT COUNT(*) FROM cashiers WHERE role='admin' AND active=1 AND id<>?", (uid,)).fetchone()[0]
            if others == 0:
                raise HTTPException(400, "Debe quedar al menos un administrador activo.")
        conn.execute("UPDATE cashiers SET name=?, role=?, is_admin=?, area_id=?, email=?, phone=?, active=? WHERE id=?",
                     (u.name.strip(), u.role, int(u.role == "admin"), u.area_id, u.email, u.phone, int(u.active), uid))
        changes = []
        if old["role"] != u.role:
            changes.append(f"rol {old['role']}→{u.role}")
        if bool(old["active"]) != u.active:
            changes.append("activado" if u.active else "desactivado")
        if u.pin:
            conn.execute("UPDATE cashiers SET pin_hash=?, must_change_pin=1, failed_attempts=0, locked_until=NULL WHERE id=?", (hash_pin(u.pin), uid))
            changes.append("PIN restablecido")
        audit(conn, me, "usuario_editado", f"{u.name}: {', '.join(changes) or 'datos'}", "usuario")
    if not u.active or u.role != old["role"]:
        for t in [t for t, cid in SESSIONS.items() if cid == uid]:
            SESSIONS.pop(t, None)   # fuerza nuevo login para aplicar permisos
    return {"ok": True}


@router.post("/users/{uid}/unlock")
def unlock_user(uid: int, me: dict = Depends(require("users.manage"))):
    with db() as conn:
        conn.execute("UPDATE cashiers SET failed_attempts=0, locked_until=NULL WHERE id=?", (uid,))
        audit(conn, me, "usuario_desbloqueado", f"id {uid}", "usuario")
    return {"ok": True}


# ------------------------------------------------------------------ bitácora
@router.get("/audit")
def audit_log(days: int = Query(7, ge=1, le=365), user_id: Optional[int] = None, action: str = "",
              q: str = "", limit: int = Query(300, le=1000), _: dict = Depends(require("audit.view"))):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    sql, args = "SELECT * FROM audit_log WHERE created_at>=? ", [since]
    if user_id:
        sql += "AND user_id=? "; args.append(user_id)
    if action:
        sql += "AND action=? "; args.append(action)
    if q:
        sql += "AND (detail LIKE ? OR user_name LIKE ?) "; args += [f"%{q}%"] * 2
    sql += "ORDER BY id DESC LIMIT ?"; args.append(limit)
    with db() as conn:
        rows = [dict(r) for r in conn.execute(sql, args)]
        actions = [r[0] for r in conn.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")]
    return {"items": rows, "actions": actions}


# ------------------------------------------------------------------ empleados
class EmployeeIn(BaseModel):
    name: str = Field(min_length=2)
    user_id: Optional[int] = None
    position: str = ""
    area_id: Optional[int] = None
    hire_date: Optional[str] = Field(default=None, pattern=DATE_RE)
    termination_date: Optional[str] = Field(default=None, pattern=DATE_RE)
    status: str = Field(default="activo", pattern="^(activo|baja)$")
    monthly_salary: float = Field(default=0, ge=0)
    pay_frequency: str = Field(default="quincenal", pattern="^(semanal|quincenal|mensual)$")
    rfc: str = ""
    curp: str = ""
    nss: str = ""
    phone: str = ""
    email: str = ""
    notes: str = ""


EMP_COLS = ["user_id", "name", "position", "area_id", "hire_date", "termination_date", "status", "monthly_salary",
            "pay_frequency", "rfc", "curp", "nss", "phone", "email", "notes"]


def _emp_clean(conn, e: EmployeeIn, emp_id: Optional[int] = None) -> dict:
    d = e.model_dump()
    d["name"] = e.name.strip()
    d["rfc"], d["curp"] = e.rfc.strip().upper(), e.curp.strip().upper()
    if e.area_id is not None and not conn.execute("SELECT 1 FROM areas WHERE id=?", (e.area_id,)).fetchone():
        raise HTTPException(400, "Área inexistente.")
    if e.user_id is not None:
        if not conn.execute("SELECT 1 FROM cashiers WHERE id=?", (e.user_id,)).fetchone():
            raise HTTPException(400, "Usuario inexistente.")
        dup = conn.execute("SELECT id FROM employees WHERE user_id=? AND id<>?", (e.user_id, emp_id or 0)).fetchone()
        if dup:
            raise HTTPException(400, "Ese usuario ya está vinculado a otro empleado.")
    if e.status == "baja" and not e.termination_date:
        d["termination_date"] = datetime.now().strftime("%Y-%m-%d")
    return d


def _emp_out(r) -> dict:
    d = dict(r)
    d["daily_salary"] = money(d["monthly_salary"] / 30.0)
    return d


@router.get("/employees")
def list_employees(include_inactive: bool = False, _: dict = Depends(require_any("hr.manage", "hr.payroll"))):
    sql = "SELECT e.*, a.name area_name, c.name user_name FROM employees e LEFT JOIN areas a ON a.id=e.area_id LEFT JOIN cashiers c ON c.id=e.user_id "
    if not include_inactive:
        sql += "WHERE e.status='activo' "
    sql += "ORDER BY e.name"
    with db() as conn:
        return [_emp_out(r) for r in conn.execute(sql)]


@router.post("/employees")
def create_employee(e: EmployeeIn, me: dict = Depends(require("hr.manage"))):
    with db() as conn:
        d = _emp_clean(conn, e)
        d["created_at"] = now()
        cols = EMP_COLS + ["created_at"]
        cur = conn.execute(f"INSERT INTO employees({','.join(cols)}) VALUES ({','.join(':' + c for c in cols)})", d)
        audit(conn, me, "empleado_creado", d["name"], "empleado")
        return {"id": cur.lastrowid}


@router.put("/employees/{eid}")
def update_employee(eid: int, e: EmployeeIn, me: dict = Depends(require("hr.manage"))):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM employees WHERE id=?", (eid,)).fetchone():
            raise HTTPException(404, "Empleado no encontrado.")
        d = _emp_clean(conn, e, eid)
        d["id"] = eid
        conn.execute(f"UPDATE employees SET {','.join(c + '=:' + c for c in EMP_COLS)} WHERE id=:id", d)
        audit(conn, me, "empleado_editado", d["name"], "empleado")
    return {"ok": True}


# ------------------------------------------------------------------ asistencia
def _own_employee(conn, me: dict):
    return conn.execute("SELECT * FROM employees WHERE user_id=? AND status='activo'", (me["id"],)).fetchone()


class ClockIn(BaseModel):
    employee_id: Optional[int] = None


@router.post("/attendance/clock")
def clock(body: ClockIn, me: dict = Depends(current_cashier)):
    """Reloj checador: alterna entrada/salida del día. Sin employee_id usa el empleado vinculado al usuario."""
    with db() as conn:
        if body.employee_id:
            emp = conn.execute("SELECT * FROM employees WHERE id=? AND status='activo'", (body.employee_id,)).fetchone()
            if not emp:
                raise HTTPException(404, "Empleado activo no encontrado.")
            if emp["user_id"] != me["id"] and not has_perm(me, "hr.manage"):
                raise HTTPException(403, "Solo puedes registrar tu propia asistencia.")
        else:
            emp = _own_employee(conn, me)
            if not emp:
                raise HTTPException(400, "Tu usuario no está vinculado a un empleado. Pide a RRHH que lo vincule.")
        today = datetime.now().strftime("%Y-%m-%d")
        open_rec = conn.execute("SELECT id FROM attendance WHERE employee_id=? AND work_date=? AND check_out IS NULL ORDER BY id DESC LIMIT 1",
                                (emp["id"], today)).fetchone()
        if open_rec:
            conn.execute("UPDATE attendance SET check_out=? WHERE id=?", (now(), open_rec["id"]))
            action = "salida"
        else:
            conn.execute("INSERT INTO attendance(employee_id, work_date, check_in) VALUES (?,?,?)", (emp["id"], today, now()))
            action = "entrada"
        audit(conn, me, "asistencia_" + action, emp["name"], "asistencia")
        return {"action": action, "employee": emp["name"], "time": now()}


@router.get("/attendance/status")
def attendance_status(me: dict = Depends(current_cashier)):
    with db() as conn:
        emp = _own_employee(conn, me)
        if not emp:
            return {"linked": False}
        today = datetime.now().strftime("%Y-%m-%d")
        rec = conn.execute("SELECT * FROM attendance WHERE employee_id=? AND work_date=? ORDER BY id DESC LIMIT 1", (emp["id"], today)).fetchone()
        return {"linked": True, "employee_id": emp["id"], "employee": emp["name"],
                "clocked_in": bool(rec and not rec["check_out"]), "last": dict(rec) if rec else None}


def _hours(ci: str, co: Optional[str]) -> Optional[float]:
    if not co:
        return None
    return round((datetime.strptime(co, "%Y-%m-%d %H:%M:%S") - datetime.strptime(ci, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600, 2)


@router.get("/attendance")
def list_attendance(date_from: Optional[str] = Query(None, pattern=DATE_RE), date_to: Optional[str] = Query(None, pattern=DATE_RE),
                    employee_id: Optional[int] = None, me: dict = Depends(current_cashier)):
    today = datetime.now().strftime("%Y-%m-%d")
    date_from = date_from or (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    date_to = date_to or today
    sql = ("SELECT t.*, e.name employee_name FROM attendance t JOIN employees e ON e.id=t.employee_id "
           "WHERE t.work_date BETWEEN ? AND ? ")
    args: list = [date_from, date_to]
    with db() as conn:
        if has_perm(me, "hr.manage"):
            if employee_id:
                sql += "AND t.employee_id=? "; args.append(employee_id)
        else:
            emp = _own_employee(conn, me)
            if not emp:
                return []
            sql += "AND t.employee_id=? "; args.append(emp["id"])
        sql += "ORDER BY t.work_date DESC, t.id DESC LIMIT 1000"
        rows = [dict(r) for r in conn.execute(sql, args)]
    for r in rows:
        r["hours"] = _hours(r["check_in"], r["check_out"])
    return rows


# ------------------------------------------------------------------ incidencias
class IncidenceIn(BaseModel):
    employee_id: int
    date: str = Field(pattern=DATE_RE)
    type: str
    amount: float = Field(default=0, ge=0)   # falta/vacaciones/incapacidad: días; bono/deducción/hora extra: pesos
    note: str = ""


@router.get("/incidences")
def list_incidences(employee_id: Optional[int] = None, date_from: Optional[str] = Query(None, pattern=DATE_RE),
                    date_to: Optional[str] = Query(None, pattern=DATE_RE), _: dict = Depends(require_any("hr.manage", "hr.payroll"))):
    sql = "SELECT i.*, e.name employee_name FROM incidences i JOIN employees e ON e.id=i.employee_id WHERE 1=1 "
    args: list = []
    if employee_id:
        sql += "AND i.employee_id=? "; args.append(employee_id)
    if date_from:
        sql += "AND i.date>=? "; args.append(date_from)
    if date_to:
        sql += "AND i.date<=? "; args.append(date_to)
    sql += "ORDER BY i.date DESC, i.id DESC LIMIT 500"
    with db() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


@router.post("/incidences")
def create_incidence(i: IncidenceIn, me: dict = Depends(require("hr.manage"))):
    if i.type not in INCIDENCE_TYPES:
        raise HTTPException(400, "Tipo de incidencia inválido.")
    amount = i.amount if i.amount > 0 else (1.0 if i.type in ("falta", "vacaciones", "incapacidad") else 0.0)
    if i.type in ("bono", "deduccion", "hora_extra") and amount <= 0:
        raise HTTPException(400, "Indica el monto en pesos.")
    with db() as conn:
        emp = conn.execute("SELECT name FROM employees WHERE id=?", (i.employee_id,)).fetchone()
        if not emp:
            raise HTTPException(404, "Empleado no encontrado.")
        cur = conn.execute("INSERT INTO incidences(employee_id, date, type, amount, note, created_by, created_at) VALUES (?,?,?,?,?,?,?)",
                           (i.employee_id, i.date, i.type, amount, i.note, me["id"], now()))
        audit(conn, me, "incidencia_creada", f"{emp['name']}: {i.type} {amount:g} ({i.date})", "incidencia")
        return {"id": cur.lastrowid}


@router.delete("/incidences/{iid}")
def delete_incidence(iid: int, me: dict = Depends(require("hr.manage"))):
    with db() as conn:
        conn.execute("DELETE FROM incidences WHERE id=?", (iid,))
        audit(conn, me, "incidencia_eliminada", f"id {iid}", "incidencia")
    return {"ok": True}


# ------------------------------------------------------------------ nómina estimada y costo laboral
def _payroll_cfg(conn) -> dict:
    st = get_settings(conn)
    return {k: float(st.get(k, 0) or 0) for k in PAYROLL_KEYS}


@router.get("/payroll/settings")
def payroll_settings(_: dict = Depends(require_any("hr.manage", "hr.payroll", "finance.view"))):
    with db() as conn:
        return _payroll_cfg(conn)


@router.put("/payroll/settings")
def set_payroll_settings(data: dict, me: dict = Depends(require("hr.manage"))):
    clean = {}
    for k in PAYROLL_KEYS:
        if k in data:
            try:
                v = float(data[k])
            except (TypeError, ValueError):
                raise HTTPException(400, f"Valor inválido para {k}.")
            if v < 0 or v > 365:
                raise HTTPException(400, f"{k} fuera de rango.")
            clean[k] = v
    with db() as conn:
        for k, v in clean.items():
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?,?)", (k, str(v)))
        audit(conn, me, "nomina_parametros", ", ".join(f"{k}={v:g}" for k, v in clean.items()), "nomina")
        return _payroll_cfg(conn)


def _costs(base: float, gross: float, cfg: dict, fraction: float) -> dict:
    """Carga patronal sobre lo pagado + provisiones de aguinaldo y prima vacacional (base = sueldo mensual)."""
    daily = base / 30.0
    burden = gross * cfg["payroll_burden_pct"] / 100.0
    aguinaldo = daily * cfg["aguinaldo_days"] / 12.0 * fraction
    prima = daily * cfg["vacation_days"] * (cfg["prima_vac_pct"] / 100.0) / 12.0 * fraction
    return {"burden": money(burden), "provisions": money(aguinaldo + prima), "aguinaldo": money(aguinaldo), "prima_vacacional": money(prima)}


@router.get("/payroll")
def payroll(year: int = Query(default=datetime.now().year, ge=2000, le=2100), month: int = Query(default=datetime.now().month, ge=1, le=12),
            period: str = Query("mensual", pattern="^(mensual|q1|q2)$"), _: dict = Depends(require_any("hr.manage", "hr.payroll"))):
    last = calendar.monthrange(year, month)[1]
    d1, d2 = {"mensual": (1, last), "q1": (1, 15), "q2": (16, last)}[period]
    start, end = f"{year}-{month:02d}-{d1:02d}", f"{year}-{month:02d}-{d2:02d}"
    fraction = 1.0 if period == "mensual" else 0.5
    with db() as conn:
        cfg = _payroll_cfg(conn)
        emps = conn.execute(
            "SELECT e.*, a.name area_name FROM employees e LEFT JOIN areas a ON a.id=e.area_id WHERE e.status='activo' "
            "OR (e.termination_date IS NOT NULL AND e.termination_date>=?) ORDER BY e.name", (start,)).fetchall()
        inc = conn.execute("SELECT * FROM incidences WHERE date BETWEEN ? AND ?", (start, end)).fetchall()
    by_emp: dict = {}
    for i in inc:
        by_emp.setdefault(i["employee_id"], []).append(i)
    rows, by_area = [], {}
    for e in emps:
        if (e["hire_date"] and e["hire_date"] > end) or (e["termination_date"] and e["termination_date"] < start):
            continue
        base_period = e["monthly_salary"] * fraction
        daily = e["monthly_salary"] / 30.0
        faltas = sum(i["amount"] for i in by_emp.get(e["id"], []) if i["type"] == "falta")
        bonos = sum(i["amount"] for i in by_emp.get(e["id"], []) if i["type"] == "bono")
        extras = sum(i["amount"] for i in by_emp.get(e["id"], []) if i["type"] == "hora_extra")
        deds = sum(i["amount"] for i in by_emp.get(e["id"], []) if i["type"] == "deduccion")
        gross = max(base_period + bonos + extras - deds - faltas * daily, 0.0)
        c = _costs(e["monthly_salary"], gross, cfg, fraction)
        total = money(gross + c["burden"] + c["provisions"])
        row = {"employee_id": e["id"], "name": e["name"], "position": e["position"], "area": e["area_name"] or "Sin área",
               "monthly_salary": e["monthly_salary"], "base_period": money(base_period), "faltas_dias": faltas, "descuento_faltas": money(faltas * daily),
               "bonos": money(bonos), "horas_extra": money(extras), "deducciones": money(deds), "gross_pay": money(gross),
               "employer_burden": c["burden"], "provisions": c["provisions"], "employer_cost": total}
        rows.append(row)
        a = by_area.setdefault(row["area"], {"area": row["area"], "headcount": 0, "gross_pay": 0.0, "employer_cost": 0.0})
        a["headcount"] += 1; a["gross_pay"] += gross; a["employer_cost"] += total
    totals = {k: money(sum(r[k] for r in rows)) for k in ("base_period", "descuento_faltas", "bonos", "horas_extra", "deducciones",
                                                           "gross_pay", "employer_burden", "provisions", "employer_cost")}
    return {"period": period, "start": start, "end": end, "settings": cfg, "rows": rows, "totals": totals,
            "by_area": [{**a, "gross_pay": money(a["gross_pay"]), "employer_cost": money(a["employer_cost"])} for a in by_area.values()],
            "disclaimer": "Estimación para costeo: no incluye ISR/IMSS del trabajador ni sustituye el recibo de nómina timbrado."}


@router.get("/labor-cost")
def labor_cost(_: dict = Depends(require_any("hr.manage", "hr.payroll", "finance.view"))):
    """Costo laboral mensual estándar de la plantilla activa: se importa como costo fijo en el análisis financiero."""
    with db() as conn:
        cfg = _payroll_cfg(conn)
        emps = conn.execute("SELECT e.*, a.name area_name FROM employees e LEFT JOIN areas a ON a.id=e.area_id WHERE e.status='activo'").fetchall()
    base = burden = prov = 0.0
    by_area: dict = {}
    for e in emps:
        c = _costs(e["monthly_salary"], e["monthly_salary"], cfg, 1.0)
        t = e["monthly_salary"] + c["burden"] + c["provisions"]
        base += e["monthly_salary"]; burden += c["burden"]; prov += c["provisions"]
        a = by_area.setdefault(e["area_name"] or "Sin área", {"headcount": 0, "monthly_cost": 0.0})
        a["headcount"] += 1; a["monthly_cost"] += t
    return {"headcount": len(emps), "monthly_base_salaries": money(base), "monthly_employer_burden": money(burden),
            "monthly_provisions": money(prov), "monthly_total_cost": money(base + burden + prov),
            "annual_total_cost": money((base + burden + prov) * 12), "settings": cfg,
            "by_area": [{"area": k, "headcount": v["headcount"], "monthly_cost": money(v["monthly_cost"])} for k, v in by_area.items()]}
