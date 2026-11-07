"""
Módulo de Operaciones y Puente ERP para el Portal del Dueño (/api/ops)
Conecta EconoMetrics Studio (Plan Base, Presupuestos y Catálogo) con la operación real
(Maquinaria/Activos Fijos, Gastos Fijos, Nómina de RRHH, Catálogo e Inventario POS)
con soporte Multi-Negocio y Multi-Sucursal.
"""
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .financial_engine import analyze_financials
from .hr import _costs, _payroll_cfg
from .models import FinancialInputs
from .pos import (
    IVA_TYPES,
    db,
    ensure_business_structure,
    generate_project_key,
    init_pos_db,
    log_movement,
    money,
    now,
    sync_employee_and_cashier,
)

router = APIRouter(prefix="/api/ops", tags=["Operaciones y ERP del Dueño"])

OPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_baseline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL DEFAULT 1,
    project_name TEXT NOT NULL,
    business_type TEXT NOT NULL,
    financials_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ops_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Maquinaria',
    status TEXT NOT NULL DEFAULT 'activo',
    purchase_cost REAL NOT NULL DEFAULT 0,
    useful_life_years REAL NOT NULL DEFAULT 5,
    monthly_maintenance REAL NOT NULL DEFAULT 0,
    purchase_date TEXT NOT NULL,
    notes TEXT DEFAULT '',
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ops_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Renta / Local',
    monthly_amount REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT DEFAULT '',
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1
);
"""

DEFAULT_BASELINE_FINANCIALS = {
    "initial_investment": 350000.0,
    "discount_rate_pct": 14.0,
    "bank_risk_free_rate_pct": 10.5,
    "shrinkage_risk_loss_pct": 3.0,
    "projection_years": 5,
    "monthly_price": 95.0,
    "monthly_units": 2800.0,
    "unit_variable_cost": 28.0,
    "monthly_fixed_costs": 75000.0,
    "monthly_maintenance_cost": 3500.0,
    "annual_sales_growth_pct": 10.0,
    "annual_inflation_pct": 4.5,
    "tax_rate_pct": 30.0,
    "depreciation_years": 5,
}


def init_ops_db() -> None:
    init_pos_db()
    with db() as conn:
        conn.executescript(OPS_SCHEMA)
        # Migrar columnas en ops_baseline si no existen
        b_cols = {r["name"] for r in conn.execute("PRAGMA table_info(ops_baseline)")}
        if "business_id" not in b_cols:
            conn.execute("ALTER TABLE ops_baseline ADD COLUMN business_id INTEGER NOT NULL DEFAULT 1")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ops_baseline_biz ON ops_baseline(business_id)")

        a_cols = {r["name"] for r in conn.execute("PRAGMA table_info(ops_assets)")}
        if "business_id" not in a_cols:
            conn.execute("ALTER TABLE ops_assets ADD COLUMN business_id INTEGER NOT NULL DEFAULT 1")
        if "branch_id" not in a_cols:
            conn.execute("ALTER TABLE ops_assets ADD COLUMN branch_id INTEGER NOT NULL DEFAULT 1")

        e_cols = {r["name"] for r in conn.execute("PRAGMA table_info(ops_expenses)")}
        if "business_id" not in e_cols:
            conn.execute("ALTER TABLE ops_expenses ADD COLUMN business_id INTEGER NOT NULL DEFAULT 1")
        if "branch_id" not in e_cols:
            conn.execute("ALTER TABLE ops_expenses ADD COLUMN branch_id INTEGER NOT NULL DEFAULT 1")

        row = conn.execute("SELECT id FROM ops_baseline WHERE business_id = 1").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO ops_baseline (business_id, project_name, business_type, financials_json, updated_at) VALUES (1, ?, ?, ?, ?)",
                (
                    "Aura Café & Roastery",
                    "Cafetería de Especialidad y Panadería Artesanal",
                    json.dumps(DEFAULT_BASELINE_FINANCIALS),
                    now(),
                ),
            )
        assets_count = conn.execute("SELECT COUNT(*) FROM ops_assets WHERE business_id=1").fetchone()[0]
        if assets_count == 0:
            today = datetime.now().strftime("%Y-%m-%d")
            seed_assets = [
                ("Máquina de Espresso 2 Grupos Comercial", "Maquinaria", "activo", 115000.0, 5.0, 1200.0, today, "Equipo principal de barra", 1, 1),
                ("Molino Dosificador On-Demand (x2)", "Maquinaria", "activo", 32000.0, 5.0, 350.0, today, "Molienda de especialidad", 1, 1),
                ("Horno Convector y Vitrina Refrigerada", "Maquinaria", "activo", 68000.0, 5.0, 800.0, today, "Panadería y repostería", 1, 1),
                ("Mobiliario, Barra y Adecuación de Local", "Mobiliario", "activo", 95000.0, 7.0, 650.0, today, "Mesas, sillas e interiorismo", 1, 1),
                ("Sistema POS, Red y Equipo de Cómputo", "Cómputo / POS", "activo", 25000.0, 4.0, 500.0, today, "Terminal de cobro e impresora", 1, 1),
            ]
            conn.executemany(
                "INSERT INTO ops_assets (name, category, status, purchase_cost, useful_life_years, monthly_maintenance, purchase_date, notes, business_id, branch_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                seed_assets,
            )
        exp_count = conn.execute("SELECT COUNT(*) FROM ops_expenses WHERE business_id=1").fetchone()[0]
        if exp_count == 0:
            seed_expenses = [
                ("Renta de Local Comercial", "Renta / Local", 28000.0, 1, "Contrato vigente", 1, 1),
                ("Energía Eléctrica CFE y Agua", "Servicios (Luz/Agua/Internet)", 6500.0, 1, "Tarifa comercial", 1, 1),
                ("Internet Fibra Óptica y Licencias Software", "Servicios (Luz/Agua/Internet)", 1800.0, 1, "POS y WiFi clientes", 1, 1),
                ("Publicidad Digital y Redes Sociales", "Marketing", 4200.0, 1, "Campañas locales", 1, 1),
                ("Contabilidad, Seguros y Permisos", "Administrativos", 3500.0, 1, "Honorarios mensuales", 1, 1),
            ]
            conn.executemany(
                "INSERT INTO ops_expenses (concept, category, monthly_amount, active, notes, business_id, branch_id) VALUES (?,?,?,?,?,?,?)",
                seed_expenses,
            )


def _resolve_biz_id(conn, business_id: Optional[int] = None, project_key: Optional[str] = None) -> int:
    if project_key:
        pk = project_key.strip().upper()
        b_row = conn.execute("SELECT id FROM businesses WHERE UPPER(project_key)=?", (pk,)).fetchone()
        if b_row:
            return b_row["id"]
    if business_id and business_id > 0:
        b_row = conn.execute("SELECT id FROM businesses WHERE id=?", (business_id,)).fetchone()
        if b_row:
            return b_row["id"]
    first = conn.execute("SELECT id FROM businesses ORDER BY id ASC LIMIT 1").fetchone()
    return first["id"] if first else 1


def _get_baseline_record(conn, business_id: int = 1) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM ops_baseline WHERE business_id = ? ORDER BY id DESC LIMIT 1", (business_id,)).fetchone()
    if not row:
        biz = conn.execute("SELECT * FROM businesses WHERE id=?", (business_id,)).fetchone()
        pname = biz["name"] if biz else "Mi Negocio"
        btype = biz["business_type"] if biz else "Comercio / Servicios"
        fin = dict(DEFAULT_BASELINE_FINANCIALS)
        return {
            "business_id": business_id,
            "project_name": pname,
            "business_type": btype,
            "financials": fin,
            "updated_at": now(),
            **fin,
        }
    try:
        fin = json.loads(row["financials_json"])
    except Exception:
        fin = dict(DEFAULT_BASELINE_FINANCIALS)
    merged = {**DEFAULT_BASELINE_FINANCIALS, **fin}
    return {
        "business_id": business_id,
        "project_name": row["project_name"],
        "business_type": row["business_type"],
        "financials": merged,
        "updated_at": row["updated_at"],
        **merged,
    }


def _compute_live_snapshot(conn, business_id: int = 1, branch_id: Optional[int] = None, days: int = 30) -> Dict[str, Any]:
    business_id = _resolve_biz_id(conn, business_id)
    baseline = _get_baseline_record(conn, business_id=business_id)
    base_fin = baseline["financials"]

    # 1. Activos Fijos / Maquinaria
    sql_a = "SELECT * FROM ops_assets WHERE business_id = ? "
    args_a = [business_id]
    if branch_id:
        sql_a += "AND branch_id = ? "
        args_a.append(branch_id)
    sql_a += "ORDER BY id"
    asset_rows = conn.execute(sql_a, args_a).fetchall()

    assets = []
    total_assets_value = 0.0
    monthly_dep_real = 0.0
    monthly_maint_real = 0.0
    active_assets_count = 0

    for r in asset_rows:
        d = dict(r)
        life = max(float(d.get("useful_life_years") or 5.0), 1.0)
        dep = money(float(d.get("purchase_cost") or 0.0) / (life * 12.0))
        d["monthly_depreciation"] = dep
        assets.append(d)
        if d.get("status") != "baja":
            active_assets_count += 1
            total_assets_value += float(d.get("purchase_cost") or 0.0)
            monthly_dep_real += dep
            monthly_maint_real += float(d.get("monthly_maintenance") or 0.0)

    total_assets_value = money(total_assets_value)
    monthly_dep_real = money(monthly_dep_real)
    monthly_maint_real = money(monthly_maint_real)

    # 2. Catálogo e Inventario del POS
    sql_p = "SELECT * FROM products WHERE business_id = ? AND active = 1 "
    args_p = [business_id]
    if branch_id:
        sql_p += "AND branch_id = ? "
        args_p.append(branch_id)
    prod_rows = conn.execute(sql_p, args_p).fetchall()

    inventory_cost_value = 0.0
    net_prices = []
    unit_costs = []
    for p in prod_rows:
        rate = IVA_TYPES.get(p["iva_type"], 0.0)
        net_p = float(p["price"] or 0.0) / (1.0 + rate)
        cost_p = float(p["cost"] or 0.0)
        stock_p = max(float(p["stock"] or 0.0), 0.0)
        if p["track_stock"]:
            inventory_cost_value += stock_p * cost_p
        if net_p > 0:
            net_prices.append(net_p)
            unit_costs.append(cost_p)

    inventory_cost_value = money(inventory_cost_value)
    catalog_count = len(prod_rows)
    if net_prices:
        avg_net_price = money(sum(net_prices) / len(net_prices))
        avg_unit_cost = money(sum(unit_costs) / len(unit_costs))
    else:
        avg_net_price = money(base_fin.get("monthly_price", 95.0))
        avg_unit_cost = money(base_fin.get("unit_variable_cost", 28.0))

    gross_margin_pct = round(((avg_net_price - avg_unit_cost) / avg_net_price) * 100.0, 1) if avg_net_price > 0 else 0.0

    # 3. Nómina activa de RRHH
    cfg = _payroll_cfg(conn)
    sql_e = "SELECT * FROM employees WHERE business_id = ? AND status = 'activo' "
    args_e = [business_id]
    if branch_id:
        sql_e += "AND branch_id = ? "
        args_e.append(branch_id)
    emp_rows = conn.execute(sql_e, args_e).fetchall()

    monthly_payroll_total = 0.0
    for e in emp_rows:
        sal = float(e["monthly_salary"] or 0.0)
        c = _costs(sal, sal, cfg, 1.0)
        monthly_payroll_total += sal + c["burden"] + c["provisions"]
    monthly_payroll_total = money(monthly_payroll_total)
    labor_headcount = len(emp_rows)

    # 4. Gastos fijos no laborales
    sql_x = "SELECT * FROM ops_expenses WHERE business_id = ? "
    args_x = [business_id]
    if branch_id:
        sql_x += "AND branch_id = ? "
        args_x.append(branch_id)
    sql_x += "ORDER BY id"
    exp_rows = conn.execute(sql_x, args_x).fetchall()

    expenses = [dict(r) for r in exp_rows]
    monthly_non_payroll = money(sum(float(r["monthly_amount"] or 0.0) for r in exp_rows if r["active"]))
    monthly_fixed_total = money(monthly_payroll_total + monthly_non_payroll)

    # 5. Volumen de ventas reales en la ventana (extrapolado a 30 días)
    since = (datetime.now() - timedelta(days=max(days, 1))).strftime("%Y-%m-%d %H:%M:%S")
    sql_s = """
        SELECT COALESCE(SUM(si.qty), 0) AS total_qty
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        WHERE s.status = 'completada' AND s.business_id = ? AND s.created_at >= ?
    """
    args_s = [business_id, since]
    if branch_id:
        sql_s += " AND s.branch_id = ? "
        args_s.append(branch_id)
    sales_row = conn.execute(sql_s, args_s).fetchone()

    raw_qty = float(sales_row["total_qty"] if sales_row else 0.0)
    real_monthly_units = round((raw_qty / max(days, 1)) * 30.0, 1) if raw_qty > 0 else float(base_fin.get("monthly_units", 2800.0))

    total_capital_deployed = money(total_assets_value + inventory_cost_value)
    if total_capital_deployed <= 0:
        total_capital_deployed = money(base_fin.get("initial_investment", 350000.0))

    avg_life_years = int(round(total_assets_value / (monthly_dep_real * 12.0))) if monthly_dep_real > 0 else int(base_fin.get("depreciation_years", 5))
    avg_life_years = max(1, min(50, avg_life_years))

    live_inputs = {
        "initial_investment": total_capital_deployed,
        "discount_rate_pct": float(base_fin.get("discount_rate_pct", 14.0)),
        "bank_risk_free_rate_pct": float(base_fin.get("bank_risk_free_rate_pct", 10.5)),
        "shrinkage_risk_loss_pct": float(base_fin.get("shrinkage_risk_loss_pct", 3.0)),
        "projection_years": int(base_fin.get("projection_years", 5)),
        "monthly_price": avg_net_price if catalog_count > 0 else float(base_fin.get("monthly_price", 95.0)),
        "monthly_units": float(base_fin.get("monthly_units", 2800.0)),
        "unit_variable_cost": avg_unit_cost if catalog_count > 0 else float(base_fin.get("unit_variable_cost", 28.0)),
        "monthly_fixed_costs": monthly_fixed_total if monthly_fixed_total > 0 else float(base_fin.get("monthly_fixed_costs", 75000.0)),
        "monthly_maintenance_cost": monthly_maint_real,
        "annual_sales_growth_pct": float(base_fin.get("annual_sales_growth_pct", 10.0)),
        "annual_inflation_pct": float(base_fin.get("annual_inflation_pct", 4.5)),
        "tax_rate_pct": float(base_fin.get("tax_rate_pct", 30.0)),
        "depreciation_years": avg_life_years,
    }

    breakdown = {
        "business_id": business_id,
        "branch_id": branch_id,
        "assets_count": active_assets_count,
        "total_assets_value": total_assets_value,
        "inventory_cost_value": inventory_cost_value,
        "total_capital_deployed": total_capital_deployed,
        "monthly_depreciation_real": monthly_dep_real,
        "monthly_maintenance_real": monthly_maint_real,
        "catalog_avg_net_price": avg_net_price,
        "catalog_avg_unit_cost": avg_unit_cost,
        "catalog_gross_margin_pct": gross_margin_pct,
        "catalog_products_count": catalog_count,
        "labor_headcount": labor_headcount,
        "monthly_payroll_total": monthly_payroll_total,
        "monthly_non_payroll_expenses": monthly_non_payroll,
        "monthly_fixed_costs_total": monthly_fixed_total,
        "real_monthly_units_sold": real_monthly_units,
    }

    return {
        "business_id": business_id,
        "branch_id": branch_id,
        "baseline": baseline,
        "breakdown": breakdown,
        "live_inputs": live_inputs,
        "assets": assets,
        "expenses": expenses,
        "hr": {
            "headcount": labor_headcount,
            "monthly_total_payroll": monthly_payroll_total,
        },
        "unified": {
            "monthly_fixed_costs": monthly_fixed_total,
            "unit_variable_cost": live_inputs["unit_variable_cost"],
        },
        "active_capex_total": total_assets_value,
    }


class BaselineIn(BaseModel):
    project_key: Optional[str] = None
    project_name: str = "Mi Negocio"
    business_type: str = "Comercio / Servicios"
    business_id: Optional[int] = None
    branch_id: Optional[int] = None
    financials: Dict[str, Any]
    replace_assets: bool = False
    assets: Optional[List[Dict[str, Any]]] = None
    engineering: Optional[Dict[str, Any]] = None
    catalog: Optional[List[Dict[str, Any]]] = None


class RecalcIn(BaseModel):
    business_id: Optional[int] = None
    branch_id: Optional[int] = None
    days_window: int = Field(default=30, ge=1, le=365)
    use_real_sales_volume: bool = True
    custom_financials: Optional[Dict[str, Any]] = None


class AssetIn(BaseModel):
    business_id: Optional[int] = 1
    branch_id: Optional[int] = 1
    name: str = Field(min_length=1)
    category: str = "Maquinaria"
    status: str = "activo"
    purchase_cost: float = Field(default=0, ge=0)
    useful_life_years: float = Field(default=5, gt=0)
    monthly_maintenance: float = Field(default=0, ge=0)
    purchase_date: Optional[str] = None
    notes: str = ""


class ExpenseIn(BaseModel):
    business_id: Optional[int] = 1
    branch_id: Optional[int] = 1
    concept: str = Field(min_length=1)
    category: str = "Renta / Local"
    monthly_amount: float = Field(default=0, ge=0)
    active: bool = True
    notes: str = ""


@router.get("/baseline")
def get_ops_baseline(
    business_id: Optional[int] = Query(None),
    project_key: Optional[str] = Query(None),
):
    init_ops_db()
    with db() as conn:
        biz_id = _resolve_biz_id(conn, business_id, project_key)
        b = _get_baseline_record(conn, business_id=biz_id)
        biz_row = conn.execute("SELECT * FROM businesses WHERE id=?", (biz_id,)).fetchone()
        pkey = biz_row["project_key"] if biz_row else "EM-AURA-1001"

    fin_inputs = FinancialInputs(**b["financials"])
    rep = analyze_financials(fin_inputs)
    return {
        "exists": True,
        "business_id": biz_id,
        "project_key": pkey,
        "project_name": b["project_name"],
        "business_type": b["business_type"],
        "financials": b["financials"],
        "updated_at": b["updated_at"],
        "baseline": {
            "business_id": biz_id,
            "project_key": pkey,
            "project_name": b["project_name"],
            "business_type": b["business_type"],
            "financial_input": b["financials"],
            "payload": {
                "project_name": b["project_name"],
                "business_type": b["business_type"],
                "financial_input": b["financials"],
            },
            "report_summary": {
                "npv": rep.npv,
                "irr_pct": rep.irr_pct,
                "viability_status": rep.viability_status,
            },
            "updated_at": b["updated_at"],
        },
    }


@router.post("/baseline")
@router.post("/save_ops_baseline")
@router.post("/save-ops-baseline")
@router.post("/sync-from-studio")
def save_ops_baseline(req: BaselineIn):
    init_ops_db()
    clean_fin = {**DEFAULT_BASELINE_FINANCIALS}
    for k in clean_fin:
        if k in req.financials and req.financials[k] is not None:
            try:
                clean_fin[k] = float(req.financials[k])
            except (TypeError, ValueError):
                pass
    clean_fin["projection_years"] = max(1, min(20, int(round(clean_fin.get("projection_years", 5)))))
    clean_fin["depreciation_years"] = max(1, min(50, int(round(clean_fin.get("depreciation_years", 5)))))

    today = datetime.now().strftime("%Y-%m-%d")
    with db() as conn:
        # 1. Crear o actualizar registro en businesses
        biz_id = req.business_id
        pkey = (req.project_key or "").strip().upper()
        if pkey:
            biz_row = conn.execute("SELECT id FROM businesses WHERE UPPER(project_key)=?", (pkey,)).fetchone()
            if biz_row:
                biz_id = biz_row["id"]

        pname = req.project_name.strip() or "Mi Proyecto"
        btype = req.business_type.strip() or "Comercio / Servicios"

        if not pkey:
            pkey = generate_project_key(conn, pname)

        if biz_id:
            conn.execute(
                """UPDATE businesses SET
                    name=?, business_type=?, project_key=?, baseline_financials_json=?, updated_at=?
                    WHERE id=?""",
                (pname, btype, pkey, json.dumps(clean_fin), now(), biz_id),
            )
        else:
            cur_biz = conn.execute(
                """INSERT INTO businesses (
                    owner_id, project_key, name, business_type, sector, state, municipality,
                    studio_payload_json, baseline_financials_json, settings_json, active, created_at, updated_at
                ) VALUES (1, ?, ?, ?, 'Comercio / Servicios', 'Ciudad de México', 'Cuauhtémoc', '{}', ?, '{}', 1, ?, ?)""",
                (pkey, pname, btype, json.dumps(clean_fin), now(), now()),
            )
            biz_id = cur_biz.lastrowid

        # 2. Asegurar estructura de sucursal matriz y terminal para este negocio
        struct = ensure_business_structure(conn, biz_id)
        br_id = req.branch_id or struct["branches"][0]["id"]
        br_code = struct["branches"][0]["code"]

        # 3. Guardar en ops_baseline
        existing_base = conn.execute("SELECT id FROM ops_baseline WHERE business_id=?", (biz_id,)).fetchone()
        if existing_base:
            conn.execute(
                """UPDATE ops_baseline SET
                    project_name=?, business_type=?, financials_json=?, updated_at=?
                    WHERE business_id=?""",
                (pname, btype, json.dumps(clean_fin), now(), biz_id),
            )
        else:
            conn.execute(
                """INSERT INTO ops_baseline (business_id, project_name, business_type, financials_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (biz_id, pname, btype, json.dumps(clean_fin), now()),
            )

        # 4. Sincronizar Activos (Maquinaria) y Gastos Fijos (Servicios)
        if req.replace_assets and req.assets:
            conn.execute("DELETE FROM ops_assets WHERE business_id=?", (biz_id,))
            for a in req.assets:
                cat = str(a.get("category") or "Maquinaria")
                cost = float(a.get("purchase_cost") or 0.0)
                maint = float(a.get("monthly_maintenance") or 0.0)
                life = float(a.get("useful_life_years") or clean_fin["depreciation_years"])
                p_date = str(a.get("purchase_date") or today)
                notes = str(a.get("notes") or f"Importado de {pname}")

                if "servicio" in cat.lower() or "gasto" in cat.lower() or "renta" in cat.lower():
                    # Es un servicio / gasto recurrente
                    conn.execute(
                        "INSERT INTO ops_expenses (concept, category, monthly_amount, active, notes, business_id, branch_id) VALUES (?,?,?,1,?,?,?)",
                        (str(a.get("name") or "Servicio Planeado"), cat, cost, notes, biz_id, br_id),
                    )
                else:
                    # Es activo fijo / maquinaria
                    conn.execute(
                        """INSERT INTO ops_assets (name, category, status, purchase_cost, useful_life_years, monthly_maintenance, purchase_date, notes, business_id, branch_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (str(a.get("name") or "Equipo"), cat, str(a.get("status") or "activo"), cost, life, maint, p_date, notes, biz_id, br_id),
                    )
        elif req.replace_assets and not req.assets and clean_fin.get("initial_investment", 0) > 0:
            conn.execute("DELETE FROM ops_assets WHERE business_id=?", (biz_id,))
            conn.execute(
                """INSERT INTO ops_assets (name, category, status, purchase_cost, useful_life_years, monthly_maintenance, purchase_date, notes, business_id, branch_id)
                   VALUES (?, 'Maquinaria Presupuestada', 'activo', ?, ?, ?, ?, 'Presupuesto Studio', ?, ?)""",
                (f"Equipamiento de Apertura ({pname})", float(clean_fin["initial_investment"]), float(clean_fin["depreciation_years"]), float(clean_fin.get("monthly_maintenance_cost") or 0.0), today, biz_id, br_id),
            )

        # 5. Si viene Catálogo Multiproducto desde Studio, aprovisionarlo en la tabla `products` de esta sucursal
        if req.catalog:
            for item in req.catalog:
                sku = str(item.get("sku") or "").strip() or None
                name = str(item.get("name") or "Producto").strip()
                price = float(item.get("price") or 0.0)
                cost = float(item.get("cost") or 0.0)
                initial_stock = float(item.get("initial_stock") or item.get("stock") or 50.0)
                cat_name = str(item.get("category") or "General").strip()

                existing_prod = None
                if sku:
                    existing_prod = conn.execute("SELECT id FROM products WHERE business_id=? AND branch_id=? AND sku=?", (biz_id, br_id, sku)).fetchone()
                if not existing_prod:
                    existing_prod = conn.execute("SELECT id FROM products WHERE business_id=? AND branch_id=? AND name=?", (biz_id, br_id, name)).fetchone()

                if existing_prod:
                    conn.execute(
                        "UPDATE products SET price=?, cost=?, category=?, active=1 WHERE id=?",
                        (price, cost, cat_name, existing_prod["id"]),
                    )
                else:
                    conn.execute(
                        """INSERT INTO products (sku, name, price, cost, stock, track_stock, active, category, business_id, branch_id)
                           VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?, ?)""",
                        (sku, name, price, cost, initial_stock, cat_name, biz_id, br_id),
                    )
                    pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    log_movement(conn, pid, "entrada", initial_stock, cost, "Aprovisionamiento inicial de Studio", "STUDIO_SYNC", 1, biz_id, br_id)

        # 6. Si vienen Empleados Planeados desde Studio, aprovisionarlos con sus códigos y PIN 1234
        if req.engineering and "staff" in req.engineering and isinstance(req.engineering["staff"], list):
            for st in req.engineering["staff"]:
                role_cand = str(st.get("role") or "cajero").lower()
                role_key = "cajero"
                if "gerent" in role_cand or "admin" in role_cand:
                    role_key = "gerente"
                elif "almac" in role_cand or "logist" in role_cand or "inven" in role_cand:
                    role_key = "almacenista"
                elif "rrhh" in role_cand or "recurs" in role_cand or "personal" in role_cand:
                    role_key = "rrhh"
                elif "cont" in role_cand or "finan" in role_cand:
                    role_key = "contador"

                sync_employee_and_cashier(
                    conn,
                    name=str(st.get("name") or "Colaborador"),
                    role=role_key,
                    business_id=biz_id,
                    branch_id=br_id,
                    pin="1234",
                    position=str(st.get("position") or st.get("name") or "Colaborador"),
                    monthly_salary=float(st.get("salary") or st.get("monthly_salary") or 10000.0),
                )

    return {
        "ok": True,
        "success": True,
        "business_id": biz_id,
        "project_key": pkey,
        "project_name": pname,
        "branch_id": br_id,
        "branch_code": br_code,
        "message": f"Proyecto '{pname}' sincronizado exitosamente con el ERP bajo la clave {pkey}.",
    }


@router.get("/live-parameters")
def get_live_parameters(
    business_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    project_key: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
):
    init_ops_db()
    with db() as conn:
        biz_id = _resolve_biz_id(conn, business_id, project_key)
        return _compute_live_snapshot(conn, business_id=biz_id, branch_id=branch_id, days=days)


@router.post("/recalculate")
def recalculate_ops(req: RecalcIn):
    init_ops_db()
    with db() as conn:
        biz_id = _resolve_biz_id(conn, req.business_id)
        snap = _compute_live_snapshot(conn, business_id=biz_id, branch_id=req.branch_id, days=req.days_window)

    base_fin_dict = snap["baseline"]["financials"]
    cur_fin_dict = dict(snap["live_inputs"])

    if req.use_real_sales_volume:
        cur_fin_dict["monthly_units"] = float(snap["breakdown"]["real_monthly_units_sold"] or cur_fin_dict["monthly_units"])

    if req.custom_financials:
        for k, v in req.custom_financials.items():
            if k in cur_fin_dict and v is not None:
                try:
                    cur_fin_dict[k] = float(v)
                except (TypeError, ValueError):
                    pass
        cur_fin_dict["projection_years"] = max(1, min(20, int(round(cur_fin_dict.get("projection_years", 5)))))
        cur_fin_dict["depreciation_years"] = max(1, min(50, int(round(cur_fin_dict.get("depreciation_years", 5)))))

    base_inputs = FinancialInputs(**base_fin_dict)
    cur_inputs = FinancialInputs(**cur_fin_dict)

    base_rep = analyze_financials(base_inputs)
    cur_rep = analyze_financials(cur_inputs)

    def _comp(label: str, unit: str, b_val: float, c_val: float, inverse_good: bool = False) -> Dict[str, Any]:
        b_num = float(b_val or 0.0)
        c_num = float(c_val or 0.0)
        delta = round(c_num - b_num, 2)
        delta_pct = round(((c_num - b_num) / abs(b_num)) * 100.0, 2) if abs(b_num) > 0.001 else 0.0
        return {
            "label": label,
            "unit": unit,
            "baseline": round(b_num, 2),
            "current": round(c_num, 2),
            "delta": delta,
            "delta_pct": delta_pct,
            "inverse_good": inverse_good,
        }

    comparisons = [
        _comp("Inversión / Capital Desplegado", "MXN", base_inputs.initial_investment, cur_inputs.initial_investment, inverse_good=True),
        _comp("Precio Promedio Neto", "MXN", base_inputs.monthly_price, cur_inputs.monthly_price, inverse_good=False),
        _comp("Costo Variable Unitario", "MXN", base_inputs.unit_variable_cost, cur_inputs.unit_variable_cost, inverse_good=True),
        _comp("Gastos Fijos + Nómina Mensual", "MXN", base_inputs.monthly_fixed_costs, cur_inputs.monthly_fixed_costs, inverse_good=True),
        _comp("Mantenimiento Mensual de Planta", "MXN", base_inputs.monthly_maintenance_cost, cur_inputs.monthly_maintenance_cost, inverse_good=True),
        _comp("Punto de Equilibrio (Unidades)", "uds/mes", base_rep.break_even.monthly_breakeven_units, cur_rep.break_even.monthly_breakeven_units, inverse_good=True),
        _comp("Punto de Equilibrio (Facturación)", "MXN", base_rep.break_even.monthly_breakeven_revenue, cur_rep.break_even.monthly_breakeven_revenue, inverse_good=True),
        _comp("Valor Actual Neto (VAN / NPV)", "MXN", base_rep.npv, cur_rep.npv, inverse_good=False),
        _comp("Tasa Interna de Retorno (TIR)", "%", base_rep.irr_pct or 0.0, cur_rep.irr_pct or 0.0, inverse_good=False),
    ]

    alerts = []
    if cur_rep.npv < 0:
        alerts.append({
            "severity": "critica",
            "title": "Alerta de Rentabilidad: VAN Negativo con Parámetros Actuales",
            "detail": f"Con la estructura actual de costos fijos (${cur_inputs.monthly_fixed_costs:,.0f}/mes) e inversión (${cur_inputs.initial_investment:,.0f}), el VAN es de ${cur_rep.npv:,.0f} MXN. Usa el Simulador Rápido arriba para evaluar un incremento de precio o reducción de gastos.",
        })
    else:
        alerts.append({
            "severity": "ok",
            "title": "Operación Rentable y Creando Valor Económico",
            "detail": f"El negocio genera un VAN positivo de ${cur_rep.npv:,.0f} MXN y una TIR de {(cur_rep.irr_pct or 0):.1f}% anual, superando el costo de capital exigido ({cur_inputs.discount_rate_pct}%).",
        })

    if cur_inputs.monthly_fixed_costs > base_inputs.monthly_fixed_costs * 1.1:
        diff_fixed = cur_inputs.monthly_fixed_costs - base_inputs.monthly_fixed_costs
        alerts.append({
            "severity": "alta",
            "title": "Desvío en Gastos Fijos y Nómina vs. Plan Base",
            "detail": f"Los gastos fijos reales superan el Plan Base por ${diff_fixed:,.0f} MXN/mes, lo que elevó el punto de equilibrio a {cur_rep.break_even.monthly_breakeven_units:,.0f} unidades/mes.",
        })

    if cur_rep.break_even.margin_of_safety_pct < 15:
        alerts.append({
            "severity": "media",
            "title": "Margen de Seguridad Operativo Estrecho",
            "detail": f"Tu margen de seguridad sobre el punto de equilibrio es de {cur_rep.break_even.margin_of_safety_pct:.1f}%. Se recomienda impulsar productos de mayor margen o paquetes promocionales.",
        })

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "business_id": biz_id,
        "baseline_inputs": base_inputs.model_dump(),
        "current_inputs": cur_inputs.model_dump(),
        "baseline_report": base_rep.model_dump(),
        "current_report": cur_rep.model_dump(),
        "comparisons": comparisons,
        "alerts": alerts,
    }


@router.post("/assets")
def create_ops_asset(asset: AssetIn):
    init_ops_db()
    pdate = asset.purchase_date or datetime.now().strftime("%Y-%m-%d")
    with db() as conn:
        b_id = asset.business_id or 1
        br_id = asset.branch_id or 1
        cur = conn.execute(
            """
            INSERT INTO ops_assets (name, category, status, purchase_cost, useful_life_years, monthly_maintenance, purchase_date, notes, business_id, branch_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (asset.name.strip(), asset.category, asset.status, asset.purchase_cost, asset.useful_life_years, asset.monthly_maintenance, pdate, asset.notes, b_id, br_id),
        )
        return {"id": cur.lastrowid, "ok": True}


@router.put("/assets/{aid}")
def update_ops_asset(aid: int, asset: AssetIn):
    init_ops_db()
    pdate = asset.purchase_date or datetime.now().strftime("%Y-%m-%d")
    with db() as conn:
        row = conn.execute("SELECT id FROM ops_assets WHERE id = ?", (aid,)).fetchone()
        if not row:
            raise HTTPException(404, "Activo no encontrado.")
        conn.execute(
            """
            UPDATE ops_assets
            SET name=?, category=?, status=?, purchase_cost=?, useful_life_years=?, monthly_maintenance=?, purchase_date=?, notes=?
            WHERE id=?
            """,
            (asset.name.strip(), asset.category, asset.status, asset.purchase_cost, asset.useful_life_years, asset.monthly_maintenance, pdate, asset.notes, aid),
        )
    return {"ok": True}


@router.delete("/assets/{aid}")
def delete_ops_asset(aid: int):
    init_ops_db()
    with db() as conn:
        conn.execute("DELETE FROM ops_assets WHERE id = ?", (aid,))
    return {"ok": True}


@router.post("/expenses")
def create_ops_expense(exp: ExpenseIn):
    init_ops_db()
    with db() as conn:
        b_id = exp.business_id or 1
        br_id = exp.branch_id or 1
        cur = conn.execute(
            """
            INSERT INTO ops_expenses (concept, category, monthly_amount, active, notes, business_id, branch_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (exp.concept.strip(), exp.category, exp.monthly_amount, int(exp.active), exp.notes, b_id, br_id),
        )
        return {"id": cur.lastrowid, "ok": True}


@router.put("/expenses/{eid}")
def update_ops_expense(eid: int, exp: ExpenseIn):
    init_ops_db()
    with db() as conn:
        row = conn.execute("SELECT id FROM ops_expenses WHERE id = ?", (eid,)).fetchone()
        if not row:
            raise HTTPException(404, "Gasto fijo no encontrado.")
        conn.execute(
            """
            UPDATE ops_expenses
            SET concept=?, category=?, monthly_amount=?, active=?, notes=?
            WHERE id=?
            """,
            (exp.concept.strip(), exp.category, exp.monthly_amount, int(exp.active), exp.notes, eid),
        )
    return {"ok": True}


@router.delete("/expenses/{eid}")
def delete_ops_expense(eid: int):
    init_ops_db()
    with db() as conn:
        conn.execute("DELETE FROM ops_expenses WHERE id = ?", (eid,))
    return {"ok": True}
