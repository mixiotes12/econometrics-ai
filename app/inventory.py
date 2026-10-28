"""
Módulo Inventarios & Catálogo (Fase 2)
- Catálogo completo: foto, categoría, proveedor, costos, precios, márgenes (margen y markup)
- Puntos de reorden / stock mínimo y alertas
- Productos importados: moneda extranjera, tipo de cambio, arancel, flete -> costo puesto en MXN
- Tipos de cambio (manual o actualización en línea)
- Kardex: entradas, mermas, ajustes (+ ventas/devoluciones desde el POS)
- Análisis: valuación, clasificación ABC, rotación, días de cobertura, mermas
"""
import base64
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .pos import IVA_TYPES, audit, current_cashier, db, log_movement, money, now, require

router = APIRouter(prefix="/api/inv", tags=["Inventarios"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads", "products")
UPLOAD_URL = "/uploads/products/"
MAX_IMAGE_BYTES = 2 * 1024 * 1024
DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|webp);base64,(.+)$", re.S)
CURRENCIES = {"MXN", "USD", "EUR"}


# ------------------------------------------------------------------ cálculos
def get_rate(conn, currency: str) -> float:
    r = conn.execute("SELECT rate_mxn FROM exchange_rates WHERE currency=?", (currency,)).fetchone()
    if not r:
        raise HTTPException(400, f"No hay tipo de cambio registrado para {currency}.")
    return float(r["rate_mxn"])


def landed_cost(foreign_cost: float, rate: float, duties_pct: float, freight: float, other: float) -> float:
    """Costo puesto en MXN = valor aduana (divisa x TC) + arancel% + flete + otros gastos por unidad."""
    customs_value = foreign_cost * rate
    return money(customs_value * (1 + duties_pct / 100.0) + freight + other)


def enrich(row) -> dict:
    p = dict(row)
    rate = IVA_TYPES.get(p["iva_type"], 0.0)
    net = p["price"] / (1 + rate)
    profit = net - p["cost"]
    p["net_price"] = money(net)
    p["profit_unit"] = money(profit)
    p["margin_pct"] = round(profit / net * 100, 2) if net > 0 else 0.0
    p["markup_pct"] = round(profit / p["cost"] * 100, 2) if p["cost"] > 0 else 0.0
    p["stock_value_cost"] = money(max(p["stock"], 0) * p["cost"])
    p["stock_value_sale"] = money(max(p["stock"], 0) * net)
    if not p["track_stock"]:
        status = "sin_control"
    elif p["stock"] <= 0:
        status = "agotado"
    elif p["min_stock"] > 0 and p["stock"] <= p["min_stock"]:
        status = "reorden"
    else:
        status = "ok"
    p["stock_status"] = status
    p["reorder_suggest"] = suggest_qty(p) if status in ("agotado", "reorden") else 0
    return p


def suggest_qty(p: dict) -> float:
    if p["reorder_qty"] > 0:
        return p["reorder_qty"]
    target = p["max_stock"] if p["max_stock"] > 0 else p["min_stock"] * 2
    return max(round(target - p["stock"], 2), 0)


# ------------------------------------------------------------------ catálogo
class ProductFull(BaseModel):
    sku: Optional[str] = None
    barcode: Optional[str] = None
    name: str = Field(min_length=1)
    category: str = ""
    supplier: str = ""
    price: float = Field(ge=0)                  # precio público con IVA incluido
    cost: float = Field(default=0, ge=0)        # ignorado si es importado (se calcula)
    iva_type: str = "iva16"
    stock: float = 0
    track_stock: bool = True
    min_stock: float = Field(default=0, ge=0)
    max_stock: float = Field(default=0, ge=0)
    reorder_qty: float = Field(default=0, ge=0)
    is_imported: bool = False
    currency: str = "MXN"
    foreign_cost: float = Field(default=0, ge=0)
    exchange_rate: Optional[float] = Field(default=None, gt=0)   # None = tipo de cambio vigente
    duties_pct: float = Field(default=0, ge=0, le=500)
    freight_cost: float = Field(default=0, ge=0)
    other_cost: float = Field(default=0, ge=0)
    origin_country: str = ""
    sat_product_key: str = "01010101"
    sat_unit_key: str = "H87"
    active: bool = True


COLS = ["sku", "barcode", "name", "category", "supplier", "price", "cost", "iva_type", "stock", "track_stock",
        "min_stock", "max_stock", "reorder_qty", "is_imported", "currency", "foreign_cost", "exchange_rate",
        "duties_pct", "freight_cost", "other_cost", "origin_country", "sat_product_key", "sat_unit_key", "active"]


def prepare(conn, p: ProductFull) -> dict:
    if p.iva_type not in IVA_TYPES:
        raise HTTPException(400, "Tipo de IVA inválido (iva16, iva0, exento).")
    if p.currency not in CURRENCIES:
        raise HTTPException(400, "Moneda no soportada (MXN, USD, EUR).")
    d = p.model_dump()
    d["sku"] = (p.sku or "").strip() or None
    d["barcode"] = (p.barcode or "").strip() or None
    d["name"] = p.name.strip()
    if p.is_imported:
        rate = p.exchange_rate or get_rate(conn, p.currency)
        d["exchange_rate"] = rate
        d["cost"] = landed_cost(p.foreign_cost, rate, p.duties_pct, p.freight_cost, p.other_cost)
    else:
        d["currency"], d["foreign_cost"], d["exchange_rate"] = "MXN", 0.0, 1.0
        d["duties_pct"] = d["freight_cost"] = d["other_cost"] = 0.0
    for k in ("track_stock", "is_imported", "active"):
        d[k] = int(d[k])
    return d


@router.get("/products")
def list_products(q: str = "", category: str = "", status: str = "", imported: Optional[bool] = None,
                  include_inactive: bool = False, _: dict = Depends(current_cashier)):
    sql, args = "SELECT * FROM products WHERE 1=1 ", []
    if not include_inactive:
        sql += "AND active=1 "
    if q:
        sql += "AND (name LIKE ? OR sku LIKE ? OR barcode LIKE ? OR supplier LIKE ?) "
        args += [f"%{q}%"] * 4
    if category:
        sql += "AND category=? "
        args.append(category)
    if imported is not None:
        sql += "AND is_imported=? "
        args.append(int(imported))
    sql += "ORDER BY name LIMIT 1000"
    with db() as conn:
        rows = [enrich(r) for r in conn.execute(sql, args)]
    if status:
        rows = [r for r in rows if r["stock_status"] == status]
    return rows


@router.get("/products/{pid}")
def get_product(pid: int, _: dict = Depends(current_cashier)):
    with db() as conn:
        r = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not r:
        raise HTTPException(404, "Producto no encontrado.")
    return enrich(r)


@router.get("/categories")
def categories(_: dict = Depends(current_cashier)):
    with db() as conn:
        return [r[0] for r in conn.execute("SELECT DISTINCT category FROM products WHERE category<>'' ORDER BY category")]


@router.post("/products")
def create_product(p: ProductFull, me: dict = Depends(require("products.manage"))):
    try:
        with db() as conn:
            d = prepare(conn, p)
            stock0 = d["stock"]
            conn.execute(f"INSERT INTO products({','.join(COLS)}) VALUES ({','.join(':' + c for c in COLS)})", d)
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            audit(conn, me, "producto_creado", d["name"], "producto")
            if d["track_stock"] and stock0:
                log_movement(conn, pid, "entrada", stock0, d["cost"], "Existencia inicial", "", me["id"])
            return enrich(conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())
    except sqlite3.IntegrityError:
        raise HTTPException(400, "SKU o código de barras duplicado.")


@router.put("/products/{pid}")
def update_product(pid: int, p: ProductFull, me: dict = Depends(require("products.manage"))):
    try:
        with db() as conn:
            old = conn.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()
            if not old:
                raise HTTPException(404, "Producto no encontrado.")
            d = prepare(conn, p)
            d["stock"] = old["stock"]          # la existencia solo cambia con movimientos (kardex)
            d["id"] = pid
            sets = ",".join(f"{c}=:{c}" for c in COLS)
            conn.execute(f"UPDATE products SET {sets} WHERE id=:id", d)
            audit(conn, me, "producto_editado", d["name"], "producto")
            return enrich(conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())
    except sqlite3.IntegrityError:
        raise HTTPException(400, "SKU o código de barras duplicado.")


# ------------------------------------------------------------------ fotos
class ImageIn(BaseModel):
    data_url: str


def _remove_file(url: Optional[str]):
    if url and url.startswith(UPLOAD_URL):
        path = os.path.join(UPLOAD_DIR, os.path.basename(url))
        if os.path.exists(path):
            os.remove(path)


@router.post("/products/{pid}/image")
def upload_image(pid: int, body: ImageIn, _: dict = Depends(require("products.manage"))):
    m = DATA_URL_RE.match(body.data_url.strip())
    if not m:
        raise HTTPException(400, "Formato de imagen inválido (PNG, JPEG o WEBP).")
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except Exception:
        raise HTTPException(400, "Imagen corrupta.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "La imagen excede 2 MB.")
    ext = "jpg" if m.group(1) == "jpeg" else m.group(1)
    with db() as conn:
        r = conn.execute("SELECT image FROM products WHERE id=?", (pid,)).fetchone()
        if not r:
            raise HTTPException(404, "Producto no encontrado.")
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        fname = f"{pid}_{secrets.token_hex(4)}.{ext}"
        with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
            f.write(raw)
        _remove_file(r["image"])
        conn.execute("UPDATE products SET image=? WHERE id=?", (UPLOAD_URL + fname, pid))
    return {"image": UPLOAD_URL + fname}


@router.delete("/products/{pid}/image")
def delete_image(pid: int, _: dict = Depends(require("products.manage"))):
    with db() as conn:
        r = conn.execute("SELECT image FROM products WHERE id=?", (pid,)).fetchone()
        if not r:
            raise HTTPException(404, "Producto no encontrado.")
        _remove_file(r["image"])
        conn.execute("UPDATE products SET image=NULL WHERE id=?", (pid,))
    return {"ok": True}


# ------------------------------------------------------------------ alertas de reorden
@router.get("/alerts")
def reorder_alerts(_: dict = Depends(current_cashier)):
    with db() as conn:
        rows = [enrich(r) for r in conn.execute("SELECT * FROM products WHERE active=1 AND track_stock=1 ORDER BY name")]
    alerts = [r for r in rows if r["stock_status"] in ("agotado", "reorden")]
    for a in alerts:
        a["reorder_cost"] = money(a["reorder_suggest"] * a["cost"])
    return {
        "count": len(alerts),
        "out_of_stock": sum(1 for a in alerts if a["stock_status"] == "agotado"),
        "estimated_cost": money(sum(a["reorder_cost"] for a in alerts)),
        "items": alerts,
    }


# ------------------------------------------------------------------ kardex / movimientos
class MovementIn(BaseModel):
    type: str = Field(pattern="^(entrada|merma|ajuste)$")
    qty: float = Field(ge=0)                 # entrada/merma: cantidad; ajuste: existencia contada real
    unit_cost: Optional[float] = Field(default=None, ge=0)
    reason: str = ""


@router.post("/products/{pid}/movement")
def add_movement(pid: int, m: MovementIn, me: dict = Depends(require("inventory.move"))):
    with db() as conn:
        p = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if not p:
            raise HTTPException(404, "Producto no encontrado.")
        if not p["track_stock"]:
            raise HTTPException(400, "Este producto no controla inventario.")
        if m.type != "ajuste" and m.qty <= 0:
            raise HTTPException(400, "La cantidad debe ser mayor a cero.")
        if m.type in ("merma", "ajuste") and len(m.reason.strip()) < 3:
            raise HTTPException(400, "Indica el motivo (caducidad, robo, daño, conteo físico...).")
        unit_cost = p["cost"]
        if m.type == "entrada":
            delta = m.qty
            if m.unit_cost is not None and not p["is_imported"]:
                # costo promedio ponderado
                base = max(p["stock"], 0)
                new_cost = (base * p["cost"] + m.qty * m.unit_cost) / (base + m.qty)
                conn.execute("UPDATE products SET cost=? WHERE id=?", (money(new_cost), pid))
                unit_cost = m.unit_cost
        elif m.type == "merma":
            if m.qty > p["stock"]:
                raise HTTPException(400, f"La merma excede la existencia ({p['stock']}).")
            delta = -m.qty
        else:
            delta = m.qty - p["stock"]
        conn.execute("UPDATE products SET stock = stock + ? WHERE id=?", (delta, pid))
        log_movement(conn, pid, m.type, delta, unit_cost, m.reason.strip(), "", me["id"])
        audit(conn, me, "inventario_" + m.type, f"{p['name']}: {delta:+g} (motivo: {m.reason.strip() or '-'})", "inventario")
        return enrich(conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())


@router.get("/movements")
def movements(product_id: Optional[int] = None, type: str = "", days: int = 90, limit: int = 300,
              _: dict = Depends(current_cashier)):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    sql = ("SELECT m.*, p.name product_name, p.sku, c.name cashier_name FROM stock_movements m "
           "JOIN products p ON p.id=m.product_id LEFT JOIN cashiers c ON c.id=m.cashier_id WHERE m.created_at>=? ")
    args: list = [since]
    if product_id:
        sql += "AND m.product_id=? "
        args.append(product_id)
    if type:
        sql += "AND m.type=? "
        args.append(type)
    sql += "ORDER BY m.id DESC LIMIT ?"
    args.append(limit)
    with db() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


# ------------------------------------------------------------------ divisas
class RateIn(BaseModel):
    rate_mxn: float = Field(gt=0)


@router.get("/rates")
def list_rates(_: dict = Depends(current_cashier)):
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM exchange_rates ORDER BY currency")]


@router.put("/rates/{currency}")
def set_rate(currency: str, body: RateIn, _: dict = Depends(require("rates.manage"))):
    currency = currency.upper()
    if currency not in CURRENCIES or currency == "MXN":
        raise HTTPException(400, "Solo se puede editar USD o EUR.")
    with db() as conn:
        conn.execute("REPLACE INTO exchange_rates(currency, rate_mxn, source, updated_at) VALUES (?,?,?,?)",
                     (currency, body.rate_mxn, "manual", now()))
    return list_rates(_)


@router.post("/rates/refresh")
def refresh_rates(_: dict = Depends(require("rates.manage"))):
    """Actualiza USD y EUR contra MXN desde open.er-api.com (requiere Internet)."""
    try:
        r = httpx.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        r.raise_for_status()
        rates = r.json()["rates"]
        usd_mxn = float(rates["MXN"])
        eur_mxn = usd_mxn / float(rates["EUR"])
    except Exception as e:
        raise HTTPException(502, f"No se pudo consultar el tipo de cambio en línea: {e}")
    with db() as conn:
        for cur, val in (("USD", usd_mxn), ("EUR", eur_mxn)):
            conn.execute("REPLACE INTO exchange_rates(currency, rate_mxn, source, updated_at) VALUES (?,?,?,?)",
                         (cur, round(val, 4), "open.er-api.com", now()))
        return [dict(x) for x in conn.execute("SELECT * FROM exchange_rates ORDER BY currency")]


@router.post("/rates/apply")
def apply_rates(_: dict = Depends(require("rates.manage"))):
    """Recalcula el costo de todos los productos importados con el tipo de cambio vigente."""
    updated = []
    with db() as conn:
        for p in conn.execute("SELECT * FROM products WHERE is_imported=1 AND currency<>'MXN'").fetchall():
            rate = get_rate(conn, p["currency"])
            new_cost = landed_cost(p["foreign_cost"], rate, p["duties_pct"], p["freight_cost"], p["other_cost"])
            if abs(new_cost - p["cost"]) > 0.004 or abs(rate - p["exchange_rate"]) > 1e-9:
                conn.execute("UPDATE products SET cost=?, exchange_rate=? WHERE id=?", (new_cost, rate, p["id"]))
                updated.append({"id": p["id"], "name": p["name"], "old_cost": p["cost"], "new_cost": new_cost})
    return {"updated": len(updated), "items": updated}


# ------------------------------------------------------------------ análisis de inventarios
@router.get("/analysis")
def analysis(days: int = Query(90, ge=7, le=730), _: dict = Depends(current_cashier)):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with db() as conn:
        products = [enrich(r) for r in conn.execute("SELECT * FROM products WHERE active=1")]
        sold = {r["product_id"]: r for r in conn.execute(
            "SELECT si.product_id, SUM(si.qty) units, SUM(si.total - si.iva) revenue "
            "FROM sale_items si JOIN sales s ON s.id=si.sale_id "
            "WHERE s.status='completada' AND s.created_at>=? GROUP BY si.product_id", (since,))}
        mermas = conn.execute(
            "SELECT COALESCE(SUM(-m.delta),0) units, COALESCE(SUM(-m.delta * m.unit_cost),0) value "
            "FROM stock_movements m WHERE m.type='merma' AND m.created_at>=?", (since,)).fetchone()
        merma_by_reason = [dict(r) for r in conn.execute(
            "SELECT reason, SUM(-delta) units, SUM(-delta*unit_cost) value FROM stock_movements "
            "WHERE type='merma' AND created_at>=? GROUP BY reason ORDER BY value DESC LIMIT 10", (since,))]

    rows, total_rev, total_cogs = [], 0.0, 0.0
    for p in products:
        s = sold.get(p["id"])
        units = float(s["units"]) if s else 0.0
        rev = money(s["revenue"]) if s else 0.0
        cogs = money(units * p["cost"])
        total_rev += rev
        total_cogs += cogs
        daily = units / days
        cover = round(p["stock"] / daily, 1) if daily > 0 and p["track_stock"] else None
        rows.append({
            "id": p["id"], "name": p["name"], "sku": p["sku"], "category": p["category"], "image": p["image"],
            "stock": p["stock"], "cost": p["cost"], "margin_pct": p["margin_pct"],
            "units_sold": units, "revenue": rev, "cogs": cogs, "profit": money(rev - cogs),
            "days_cover": cover, "stock_value_cost": p["stock_value_cost"], "stock_status": p["stock_status"],
        })
    # Clasificación ABC por ingresos (Pareto 80/15/5)
    rows.sort(key=lambda r: r["revenue"], reverse=True)
    cum = 0.0
    for r in rows:
        if r["revenue"] <= 0:
            r["abc"], r["cum_pct"] = "C", 100.0
            continue
        cum += r["revenue"]
        pct = cum / total_rev * 100 if total_rev else 100
        r["cum_pct"] = round(pct, 1)
        r["abc"] = "A" if pct - (r["revenue"] / total_rev * 100) < 80 else ("B" if pct - (r["revenue"] / total_rev * 100) < 95 else "C")
    inv_cost = sum(p["stock_value_cost"] for p in products)
    inv_sale = sum(p["stock_value_sale"] for p in products)
    slow = [r for r in rows if r["stock"] > 0 and r["stock_status"] != "sin_control"
            and (r["units_sold"] == 0 or (r["days_cover"] or 0) > 90)]
    by_cat: dict = {}
    for p in products:
        c = p["category"] or "Sin categoría"
        by_cat[c] = by_cat.get(c, 0.0) + p["stock_value_cost"]
    return {
        "period_days": days,
        "summary": {
            "products": len(products),
            "units_in_stock": round(sum(max(p["stock"], 0) for p in products if p["track_stock"]), 2),
            "inventory_value_cost": money(inv_cost),
            "inventory_value_sale": money(inv_sale),
            "potential_profit": money(inv_sale - inv_cost),
            "revenue_period": money(total_rev),
            "cogs_period": money(total_cogs),
            "turnover": round(total_cogs / inv_cost, 2) if inv_cost > 0 else None,    # veces en el periodo
            "turnover_annualized": round(total_cogs / inv_cost * 365 / days, 2) if inv_cost > 0 else None,
            "avg_days_inventory": round(inv_cost / (total_cogs / days), 1) if total_cogs > 0 else None,
            "low_stock_count": sum(1 for p in products if p["stock_status"] in ("agotado", "reorden")),
            "merma_units": round(mermas["units"], 2),
            "merma_value": money(mermas["value"]),
            "merma_pct_of_cogs": round(mermas["value"] / total_cogs * 100, 2) if total_cogs > 0 else 0.0,
        },
        "abc_counts": {k: sum(1 for r in rows if r["abc"] == k) for k in "ABC"},
        "products": rows,
        "slow_movers": slow[:25],
        "value_by_category": [{"category": k, "value": money(v)} for k, v in sorted(by_cat.items(), key=lambda x: -x[1])],
        "merma_by_reason": merma_by_reason,
    }
