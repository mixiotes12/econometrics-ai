"""
Módulo de Operaciones y Puente ERP para el Portal del Dueño (/api/ops)
Conecta EconoMetrics Studio (Plan Base y Presupuestos de IA) con la operación real
(Maquinaria/Activos Fijos, Gastos Fijos, Nómina de RRHH, Catálogo e Inventario POS).
"""
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .financial_engine import analyze_financials
from .hr import _costs, _payroll_cfg
from .models import FinancialInputs
from .pos import IVA_TYPES, db, init_pos_db, money, now

router = APIRouter(prefix="/api/ops", tags=["Operaciones y ERP del Dueño"])

OPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_baseline (
    id INTEGER PRIMARY KEY CHECK (id = 1),
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
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ops_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Renta / Local',
    monthly_amount REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT DEFAULT ''
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
        row = conn.execute("SELECT id FROM ops_baseline WHERE id = 1").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO ops_baseline (id, project_name, business_type, financials_json, updated_at) VALUES (1, ?, ?, ?, ?)",
                (
                    "Aura Café & Roastery",
                    "Cafetería de Especialidad y Panadería Artesanal",
                    json.dumps(DEFAULT_BASELINE_FINANCIALS),
                    now(),
                ),
            )
        assets_count = conn.execute("SELECT COUNT(*) FROM ops_assets").fetchone()[0]
        if assets_count == 0:
            today = datetime.now().strftime("%Y-%m-%d")
            seed_assets = [
                ("Máquina de Espresso 2 Grupos Comercial", "Maquinaria", "activo", 115000.0, 5.0, 1200.0, today, "Equipo principal de barra"),
                ("Molino Dosificador On-Demand (x2)", "Maquinaria", "activo", 32000.0, 5.0, 350.0, today, "Molienda de especialidad"),
                ("Horno Convector y Vitrina Refrigerada", "Maquinaria", "activo", 68000.0, 5.0, 800.0, today, "Panadería y repostería"),
                ("Mobiliario, Barra y Adecuación de Local", "Mobiliario", "activo", 95000.0, 7.0, 650.0, today, "Mesas, sillas e interiorismo"),
                ("Sistema POS, Red y Equipo de Cómputo", "Cómputo / POS", "activo", 25000.0, 4.0, 500.0, today, "Terminal de cobro e impresora"),
            ]
            conn.executemany(
                "INSERT INTO ops_assets (name, category, status, purchase_cost, useful_life_years, monthly_maintenance, purchase_date, notes) VALUES (?,?,?,?,?,?,?,?)",
                seed_assets,
            )
        exp_count = conn.execute("SELECT COUNT(*) FROM ops_expenses").fetchone()[0]
        if exp_count == 0:
            seed_expenses = [
                ("Renta de Local Comercial", "Renta / Local", 28000.0, 1, "Contrato vigente"),
                ("Energía Eléctrica CFE y Agua", "Servicios (Luz/Agua/Internet)", 6500.0, 1, "Tarifa comercial"),
                ("Internet Fibra Óptica y Licencias Software", "Servicios (Luz/Agua/Internet)", 1800.0, 1, "POS y WiFi clientes"),
                ("Publicidad Digital y Redes Sociales", "Marketing", 4200.0, 1, "Campañas locales"),
                ("Contabilidad, Seguros y Permisos", "Administrativos", 3500.0, 1, "Honorarios mensuales"),
            ]
            conn.executemany(
                "INSERT INTO ops_expenses (concept, category, monthly_amount, active, notes) VALUES (?,?,?,?,?)",
                seed_expenses,
            )


def _get_baseline_record(conn) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM ops_baseline WHERE id = 1").fetchone()
    if not row:
        fin = dict(DEFAULT_BASELINE_FINANCIALS)
        return {
            "project_name": "Aura Café & Roastery",
            "business_type": "Cafetería de Especialidad",
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
        "project_name": row["project_name"],
        "business_type": row["business_type"],
        "financials": merged,
        "updated_at": row["updated_at"],
        **merged,
    }


def _compute_live_snapshot(conn, days: int = 30) -> Dict[str, Any]:
    baseline = _get_baseline_record(conn)
    base_fin = baseline["financials"]

    # 1. Activos Fijos / Maquinaria
    asset_rows = conn.execute("SELECT * FROM ops_assets ORDER BY id").fetchall()
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
    prod_rows = conn.execute("SELECT * FROM products WHERE active = 1").fetchall()
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
    emp_rows = conn.execute("SELECT * FROM employees WHERE status = 'activo'").fetchall()
    monthly_payroll_total = 0.0
    for e in emp_rows:
        sal = float(e["monthly_salary"] or 0.0)
        c = _costs(sal, sal, cfg, 1.0)
        monthly_payroll_total += sal + c["burden"] + c["provisions"]
    monthly_payroll_total = money(monthly_payroll_total)
    labor_headcount = len(emp_rows)

    # 4. Gastos fijos no laborales
    exp_rows = conn.execute("SELECT * FROM ops_expenses ORDER BY id").fetchall()
    expenses = [dict(r) for r in exp_rows]
    monthly_non_payroll = money(sum(float(r["monthly_amount"] or 0.0) for r in exp_rows if r["active"]))
    monthly_fixed_total = money(monthly_payroll_total + monthly_non_payroll)

    # 5. Volumen de ventas reales en la ventana (extrapolado a 30 días)
    since = (datetime.now() - timedelta(days=max(days, 1))).strftime("%Y-%m-%d %H:%M:%S")
    sales_row = conn.execute(
        """
        SELECT COALESCE(SUM(si.qty), 0) AS total_qty
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        WHERE s.status = 'completada' AND s.created_at >= ?
        """,
        (since,),
    ).fetchone()
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
        "baseline": baseline,
        "breakdown": breakdown,
        "live_inputs": live_inputs,
        "assets": assets,
        "expenses": expenses,
        # Campos adicionales para compatibilidad directa con hub.html
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
    project_name: str = "Mi Negocio"
    business_type: str = "Comercio / Servicios"
    financials: Dict[str, Any]
    replace_assets: bool = False
    assets: Optional[List[Dict[str, Any]]] = None


class RecalcIn(BaseModel):
    days_window: int = 30
    use_real_sales_volume: bool = False
    custom_financials: Optional[Dict[str, Any]] = None


class AssetIn(BaseModel):
    name: str = Field(min_length=1)
    category: str = "Maquinaria"
    status: str = "activo"
    purchase_cost: float = Field(default=0, ge=0)
    useful_life_years: float = Field(default=5, gt=0)
    monthly_maintenance: float = Field(default=0, ge=0)
    purchase_date: Optional[str] = None
    notes: str = ""


class ExpenseIn(BaseModel):
    concept: str = Field(min_length=1)
    category: str = "Renta / Local"
    monthly_amount: float = Field(default=0, ge=0)
    active: bool = True
    notes: str = ""


@router.get("/baseline")
def get_ops_baseline():
    init_ops_db()
    with db() as conn:
        b = _get_baseline_record(conn)
    fin_inputs = FinancialInputs(**b["financials"])
    rep = analyze_financials(fin_inputs)
    return {
        "exists": True,
        "project_name": b["project_name"],
        "business_type": b["business_type"],
        "financials": b["financials"],
        "updated_at": b["updated_at"],
        "baseline": {
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
        conn.execute(
            """
            INSERT INTO ops_baseline (id, project_name, business_type, financials_json, updated_at)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                project_name = excluded.project_name,
                business_type = excluded.business_type,
                financials_json = excluded.financials_json,
                updated_at = excluded.updated_at
            """,
            (req.project_name.strip() or "Mi Proyecto", req.business_type.strip() or "Comercio / Servicios", json.dumps(clean_fin), now()),
        )
        if req.replace_assets and req.assets:
            conn.execute("DELETE FROM ops_assets")
            for a in req.assets:
                conn.execute(
                    """
                    INSERT INTO ops_assets (name, category, status, purchase_cost, useful_life_years, monthly_maintenance, purchase_date, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(a.get("name") or "Equipo Presupuestado"),
                        str(a.get("category") or "Maquinaria Presupuestada"),
                        str(a.get("status") or "activo"),
                        float(a.get("purchase_cost") or 0.0),
                        float(a.get("useful_life_years") or clean_fin["depreciation_years"]),
                        float(a.get("monthly_maintenance") or 0.0),
                        str(a.get("purchase_date") or today),
                        str(a.get("notes") or f"Importado de {req.project_name}"),
                    ),
                )
        elif req.replace_assets and not req.assets and clean_fin.get("initial_investment", 0) > 0:
            # Si se aplicó un presupuesto global sin partidas individuales, reflejar la inversión en activos
            conn.execute("DELETE FROM ops_assets")
            conn.execute(
                """
                INSERT INTO ops_assets (name, category, status, purchase_cost, useful_life_years, monthly_maintenance, purchase_date, notes)
                VALUES (?, ?, 'activo', ?, ?, ?, ?, ?)
                """,
                (
                    f"Inversión en Equipamiento y Apertura ({req.project_name})",
                    "Maquinaria Presupuestada",
                    float(clean_fin["initial_investment"]),
                    float(clean_fin["depreciation_years"]),
                    float(clean_fin.get("monthly_maintenance_cost") or 0.0),
                    today,
                    "Presupuesto cargado desde EconoMetrics Studio",
                ),
            )
    return get_ops_baseline()


@router.get("/live-parameters")
def get_live_parameters(days: int = Query(30, ge=1, le=365)):
    init_ops_db()
    with db() as conn:
        return _compute_live_snapshot(conn, days=days)


@router.post("/recalculate")
def recalculate_ops(req: RecalcIn):
    init_ops_db()
    with db() as conn:
        snap = _compute_live_snapshot(conn, days=req.days_window)

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
        cur = conn.execute(
            """
            INSERT INTO ops_assets (name, category, status, purchase_cost, useful_life_years, monthly_maintenance, purchase_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (asset.name.strip(), asset.category, asset.status, asset.purchase_cost, asset.useful_life_years, asset.monthly_maintenance, pdate, asset.notes),
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
        cur = conn.execute(
            """
            INSERT INTO ops_expenses (concept, category, monthly_amount, active, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (exp.concept.strip(), exp.category, exp.monthly_amount, int(exp.active), exp.notes),
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
