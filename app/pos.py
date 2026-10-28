"""
Módulo POS & Ventas (Fase 1)
- Cajeros (login por PIN) y turnos de caja (apertura, movimientos, Corte X / Corte Z)
- Búsqueda por código de barras / SKU / nombre
- Ventas con desglose de IVA (16%, 0%, exento), descuento de inventario
- Ticket imprimible (58mm / 80mm)
- Facturación CFDI 4.0 (XML pre-timbrado; el timbrado requiere un PAC externo)

Persistencia: SQLite (librería estándar) en app/data/pos.db
"""
import os
import re
import secrets
import sqlite3
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta
from html import escape
from typing import List, Optional
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "pos.db")

router = APIRouter(prefix="/api/pos", tags=["POS"])

IVA_TYPES = {"iva16": 0.16, "iva0": 0.0, "exento": 0.0}
PAYMENT_METHODS = {"efectivo": "01", "tarjeta": "04", "transferencia": "03"}
RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS cashiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cashier_id INTEGER NOT NULL REFERENCES cashiers(id),
    opened_at TEXT NOT NULL,
    opening_float REAL NOT NULL DEFAULT 0,
    closed_at TEXT,
    counted_cash REAL,
    expected_cash REAL,
    difference REAL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'abierto'
);
CREATE TABLE IF NOT EXISTS cash_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_id INTEGER NOT NULL REFERENCES shifts(id),
    type TEXT NOT NULL CHECK (type IN ('entrada','salida')),
    amount REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE,
    barcode TEXT UNIQUE,
    name TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0,          -- precio al público con IVA incluido
    cost REAL NOT NULL DEFAULT 0,
    iva_type TEXT NOT NULL DEFAULT 'iva16',
    stock REAL NOT NULL DEFAULT 0,
    track_stock INTEGER NOT NULL DEFAULT 1,
    sat_product_key TEXT NOT NULL DEFAULT '01010101',
    sat_unit_key TEXT NOT NULL DEFAULT 'H87',
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio TEXT UNIQUE,
    shift_id INTEGER NOT NULL REFERENCES shifts(id),
    cashier_id INTEGER NOT NULL REFERENCES cashiers(id),
    created_at TEXT NOT NULL,
    subtotal REAL NOT NULL,
    iva REAL NOT NULL,
    total REAL NOT NULL,
    payment_method TEXT NOT NULL,
    received REAL NOT NULL,
    change_given REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completada'
);
CREATE TABLE IF NOT EXISTS sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    name TEXT NOT NULL,
    barcode TEXT,
    qty REAL NOT NULL,
    unit_price REAL NOT NULL,               -- con IVA
    unit_net REAL NOT NULL,                 -- sin IVA
    iva_type TEXT NOT NULL,
    iva REAL NOT NULL,
    total REAL NOT NULL,
    sat_product_key TEXT NOT NULL,
    sat_unit_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL UNIQUE REFERENCES sales(id),
    serie TEXT NOT NULL,
    folio TEXT NOT NULL,
    rfc TEXT NOT NULL,
    razon_social TEXT NOT NULL,
    regimen_fiscal TEXT NOT NULL,
    codigo_postal TEXT NOT NULL,
    uso_cfdi TEXT NOT NULL,
    email TEXT,
    xml TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendiente_timbrado',
    created_at TEXT NOT NULL
);
"""

SCHEMA_INVENTORY = """
CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    type TEXT NOT NULL,                     -- entrada | ajuste | merma | venta | devolucion
    delta REAL NOT NULL,                    -- cambio con signo en existencias
    unit_cost REAL NOT NULL DEFAULT 0,
    stock_after REAL NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    ref TEXT NOT NULL DEFAULT '',
    cashier_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mov_product ON stock_movements(product_id, created_at);
CREATE TABLE IF NOT EXISTS exchange_rates (
    currency TEXT PRIMARY KEY,
    rate_mxn REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    updated_at TEXT NOT NULL
);
"""

# Columnas de Fase 2 agregadas a products (migración idempotente)
PRODUCT_EXTRA_COLUMNS = {
    "category": "TEXT NOT NULL DEFAULT ''",
    "supplier": "TEXT NOT NULL DEFAULT ''",
    "image": "TEXT",
    "min_stock": "REAL NOT NULL DEFAULT 0",       # punto de reorden
    "max_stock": "REAL NOT NULL DEFAULT 0",
    "reorder_qty": "REAL NOT NULL DEFAULT 0",
    "is_imported": "INTEGER NOT NULL DEFAULT 0",
    "currency": "TEXT NOT NULL DEFAULT 'MXN'",
    "foreign_cost": "REAL NOT NULL DEFAULT 0",
    "exchange_rate": "REAL NOT NULL DEFAULT 1",
    "duties_pct": "REAL NOT NULL DEFAULT 0",
    "freight_cost": "REAL NOT NULL DEFAULT 0",
    "other_cost": "REAL NOT NULL DEFAULT 0",
    "origin_country": "TEXT NOT NULL DEFAULT ''",
}


def log_movement(conn, product_id: int, mtype: str, delta: float, unit_cost: float = 0.0,
                 reason: str = "", ref: str = "", cashier_id: Optional[int] = None):
    """Registra un movimiento (kardex). Debe llamarse DESPUÉS de actualizar products.stock."""
    stock_after = conn.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()["stock"]
    conn.execute(
        "INSERT INTO stock_movements(product_id, type, delta, unit_cost, stock_after, reason, ref, cashier_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (product_id, mtype, delta, unit_cost, stock_after, reason, ref, cashier_id, now()),
    )


ROLES = {
    "admin": {"label": "Administrador", "perms": ["*"]},
    "gerente": {"label": "Gerente de tienda", "perms": [
        "pos.sell", "sales.cancel", "shifts.view_all", "products.manage", "inventory.move", "rates.manage",
        "finance.view", "hr.manage", "audit.view"]},
    "cajero": {"label": "Cajero", "perms": ["pos.sell"]},
    "almacenista": {"label": "Almacenista", "perms": ["products.manage", "inventory.move"]},
    "contador": {"label": "Contador / Finanzas", "perms": ["shifts.view_all", "finance.view", "rates.manage", "hr.payroll"]},
}
PERMISSIONS = {
    "pos.sell": "Vender, abrir/cerrar turno, facturar",
    "sales.cancel": "Cancelar ventas",
    "shifts.view_all": "Ver turnos y ventas de todos los cajeros",
    "products.manage": "Alta y edición de productos/catálogo",
    "inventory.move": "Entradas, mermas y ajustes de inventario",
    "rates.manage": "Administrar tipos de cambio",
    "finance.view": "Ver costos y reportes financieros",
    "hr.manage": "Administrar personal, asistencia e incidencias",
    "hr.payroll": "Ver nómina y costo laboral",
    "audit.view": "Consultar la bitácora de actividad",
    "settings.manage": "Configuración del negocio",
    "users.manage": "Usuarios, roles y áreas",
}

SCHEMA_HR = """
CREATE TABLE IF NOT EXISTS areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    user_name TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    entity TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_date ON audit_log(created_at);
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE REFERENCES cashiers(id),
    name TEXT NOT NULL,
    position TEXT NOT NULL DEFAULT '',
    area_id INTEGER REFERENCES areas(id),
    hire_date TEXT,
    termination_date TEXT,
    status TEXT NOT NULL DEFAULT 'activo',
    monthly_salary REAL NOT NULL DEFAULT 0,
    pay_frequency TEXT NOT NULL DEFAULT 'quincenal',
    rfc TEXT NOT NULL DEFAULT '',
    curp TEXT NOT NULL DEFAULT '',
    nss TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    work_date TEXT NOT NULL,
    check_in TEXT NOT NULL,
    check_out TEXT
);
CREATE INDEX IF NOT EXISTS idx_att_emp ON attendance(employee_id, work_date);
CREATE TABLE IF NOT EXISTS incidences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    date TEXT NOT NULL,
    type TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    created_by INTEGER,
    created_at TEXT NOT NULL
);
"""

CASHIER_EXTRA_COLUMNS = {
    "role": "TEXT NOT NULL DEFAULT 'cajero'",
    "area_id": "INTEGER",
    "email": "TEXT NOT NULL DEFAULT ''",
    "phone": "TEXT NOT NULL DEFAULT ''",
    "last_login": "TEXT",
    "failed_attempts": "INTEGER NOT NULL DEFAULT 0",
    "locked_until": "TEXT",
    "must_change_pin": "INTEGER NOT NULL DEFAULT 0",
}
DEFAULT_AREAS = [
    ("Ventas / Caja", "Punto de venta, cajeros y atención al cliente"),
    ("Almacén", "Recepción, inventarios y mermas"),
    ("Finanzas", "Contabilidad, facturación y reportes financieros"),
    ("Recursos Humanos", "Personal, asistencia y nómina"),
    ("Administración", "Dirección y gestión general"),
]
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 5


def has_perm(user: dict, perm: str) -> bool:
    perms = ROLES.get(user.get("role", ""), {}).get("perms", [])
    return "*" in perms or perm in perms


def user_permissions(user: dict) -> list:
    perms = ROLES.get(user.get("role", ""), {}).get("perms", [])
    return list(PERMISSIONS) if "*" in perms else list(perms)


def audit(conn, user, action: str, detail: str = "", entity: str = ""):
    """Bitácora de actividad. `user` puede ser dict de usuario, None (sistema) o un nombre."""
    uid, uname = (user["id"], user["name"]) if isinstance(user, dict) else (None, str(user or "sistema"))
    conn.execute("INSERT INTO audit_log(user_id, user_name, action, entity, detail, created_at) VALUES (?,?,?,?,?,?)",
                 (uid, uname, action, entity, detail, now()))


DEFAULT_SETTINGS = {
    "payroll_burden_pct": "30",
    "aguinaldo_days": "15",
    "vacation_days": "12",
    "prima_vac_pct": "25",
    "business_name": "Mi Negocio",
    "legal_name": "",
    "rfc": "XAXX010101000",
    "tax_regime": "601",
    "address": "",
    "zip_code": "00000",
    "phone": "",
    "ticket_width": "80",
    "ticket_footer": "¡Gracias por su compra!",
    "invoice_series": "A",
}


# ------------------------------------------------------------------ DB helpers
@contextmanager
def db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_pin(pin: str) -> str:
    return hashlib.sha256(("pos-salt:" + pin).encode()).hexdigest()


def init_pos_db():
    with db() as conn:
        conn.executescript(SCHEMA)
        conn.executescript(SCHEMA_INVENTORY)
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(products)")}
        for col, ddl in PRODUCT_EXTRA_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE products ADD COLUMN {col} {ddl}")
        conn.executescript(SCHEMA_HR)
        cexisting = {r["name"] for r in conn.execute("PRAGMA table_info(cashiers)")}
        for col, ddl in CASHIER_EXTRA_COLUMNS.items():
            if col not in cexisting:
                conn.execute(f"ALTER TABLE cashiers ADD COLUMN {col} {ddl}")
        for aname, adesc in DEFAULT_AREAS:
            conn.execute("INSERT OR IGNORE INTO areas(name, description) VALUES (?,?)", (aname, adesc))
        conn.execute("UPDATE cashiers SET role='admin' WHERE is_admin=1 AND role<>'admin'")
        conn.execute("UPDATE cashiers SET must_change_pin=1 WHERE pin_hash=? AND must_change_pin=0", (hash_pin("1234"),))
        conn.execute("INSERT OR IGNORE INTO exchange_rates(currency, rate_mxn, source, updated_at) VALUES ('MXN', 1, 'base', ?)", (now(),))
        conn.execute("INSERT OR IGNORE INTO exchange_rates(currency, rate_mxn, source, updated_at) VALUES ('USD', 18.0, 'inicial (actualizar)', ?)", (now(),))
        conn.execute("INSERT OR IGNORE INTO exchange_rates(currency, rate_mxn, source, updated_at) VALUES ('EUR', 19.5, 'inicial (actualizar)', ?)", (now(),))
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        if conn.execute("SELECT COUNT(*) FROM cashiers").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO cashiers(name, pin_hash, is_admin, active, created_at, role, must_change_pin) VALUES (?,?,1,1,?,'admin',1)",
                ("Administrador", hash_pin("1234"), now()),
            )


def get_settings(conn) -> dict:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}


def money(x: float) -> float:
    return round(float(x) + 1e-9, 2)


# ------------------------------------------------------------------ Auth (PIN + token en memoria)
SESSIONS: dict = {}  # token -> cashier_id


def current_cashier(x_pos_token: Optional[str] = Header(None)) -> dict:
    cid = SESSIONS.get(x_pos_token or "")
    if not cid:
        raise HTTPException(401, "Sesión no válida. Inicia sesión con tu PIN.")
    with db() as conn:
        row = conn.execute("SELECT * FROM cashiers WHERE id=? AND active=1", (cid,)).fetchone()
    if not row:
        raise HTTPException(401, "Cajero inactivo o inexistente.")
    return dict(row)


def require(perm: str):
    """Dependencia FastAPI: exige un permiso del rol del usuario."""
    def dep(c: dict = Depends(current_cashier)) -> dict:
        if not has_perm(c, perm):
            raise HTTPException(403, f"Tu rol no tiene permiso para esta acción ({perm}).")
        return c
    return dep


def require_any(*perms: str):
    def dep(c: dict = Depends(current_cashier)) -> dict:
        if not any(has_perm(c, p) for p in perms):
            raise HTTPException(403, "Tu rol no tiene permiso para esta acción.")
        return c
    return dep


def admin_only(c: dict = Depends(current_cashier)) -> dict:
    if c.get("role") != "admin":
        raise HTTPException(403, "Se requiere nivel Administrador.")
    return c


class LoginReq(BaseModel):
    cashier_id: int
    pin: str


@router.get("/cashiers/public")
def public_cashiers():
    init_pos_db()
    with db() as conn:
        rows = conn.execute("SELECT id, name FROM cashiers WHERE active=1 ORDER BY name").fetchall()
    return [dict(r) for r in rows]


@router.post("/login")
def login(req: LoginReq):
    err = None
    result = None
    with db() as conn:
        row = conn.execute("SELECT * FROM cashiers WHERE id=? AND active=1", (req.cashier_id,)).fetchone()
        if not row:
            err = (401, "Cajero o PIN incorrecto.")
        elif row["locked_until"] and row["locked_until"] > now():
            err = (423, f"Usuario bloqueado por intentos fallidos hasta las {row['locked_until'][11:16]}.")
            audit(conn, row["name"], "login_bloqueado", "Intento durante bloqueo", "usuario")
        elif row["pin_hash"] != hash_pin(req.pin):
            attempts = row["failed_attempts"] + 1
            if attempts >= MAX_FAILED_LOGINS:
                until = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("UPDATE cashiers SET failed_attempts=0, locked_until=? WHERE id=?", (until, row["id"]))
                audit(conn, row["name"], "usuario_bloqueado", f"{MAX_FAILED_LOGINS} intentos fallidos", "usuario")
                err = (423, f"Demasiados intentos. Usuario bloqueado {LOCK_MINUTES} minutos.")
            else:
                conn.execute("UPDATE cashiers SET failed_attempts=? WHERE id=?", (attempts, row["id"]))
                audit(conn, row["name"], "login_fallido", f"Intento {attempts}", "usuario")
                err = (401, "Cajero o PIN incorrecto.")
        else:
            conn.execute("UPDATE cashiers SET failed_attempts=0, locked_until=NULL, last_login=? WHERE id=?", (now(), row["id"]))
            token = secrets.token_hex(24)
            SESSIONS[token] = row["id"]
            user = dict(row)
            audit(conn, user, "login", "", "usuario")
            result = {"token": token, "cashier": {
                "id": row["id"], "name": row["name"], "role": row["role"], "role_label": ROLES[row["role"]]["label"],
                "is_admin": row["role"] == "admin", "permissions": user_permissions(user),
                "area_id": row["area_id"], "must_change_pin": bool(row["must_change_pin"])}}
    if err:
        raise HTTPException(*err)
    return result


@router.post("/logout")
def logout(x_pos_token: Optional[str] = Header(None)):
    cid = SESSIONS.pop(x_pos_token or "", None)
    if cid:
        with db() as conn:
            r = conn.execute("SELECT id, name FROM cashiers WHERE id=?", (cid,)).fetchone()
            if r:
                audit(conn, dict(r), "logout", "", "usuario")
    return {"ok": True}


# ------------------------------------------------------------------ Configuración del negocio / ticket
@router.get("/settings")
def read_settings(_: dict = Depends(current_cashier)):
    with db() as conn:
        return get_settings(conn)


@router.put("/settings")
def write_settings(data: dict, me: dict = Depends(require("settings.manage"))):
    with db() as conn:
        for k, v in data.items():
            if k in DEFAULT_SETTINGS:
                conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (k, str(v)))
        audit(conn, me, "configuracion", "Se actualizó la configuración del negocio", "settings")
        return get_settings(conn)


# ------------------------------------------------------------------ Turnos de caja
class OpenShiftReq(BaseModel):
    opening_float: float = Field(ge=0)


class MovementReq(BaseModel):
    type: str = Field(pattern="^(entrada|salida)$")
    amount: float = Field(gt=0)
    reason: str = Field(min_length=3)


class CloseShiftReq(BaseModel):
    counted_cash: float = Field(ge=0)
    notes: Optional[str] = ""


def open_shift_of(conn, cashier_id: int):
    return conn.execute(
        "SELECT * FROM shifts WHERE cashier_id=? AND status='abierto' ORDER BY id DESC LIMIT 1", (cashier_id,)
    ).fetchone()


def shift_report(conn, shift_id: int) -> dict:
    s = conn.execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
    if not s:
        raise HTTPException(404, "Turno no encontrado.")
    by_method = {m: 0.0 for m in PAYMENT_METHODS}
    count = 0
    subtotal = iva = total = 0.0
    for r in conn.execute(
        "SELECT payment_method, COUNT(*) n, SUM(subtotal) st, SUM(iva) iv, SUM(total) t "
        "FROM sales WHERE shift_id=? AND status='completada' GROUP BY payment_method", (shift_id,)
    ):
        by_method[r["payment_method"]] = money(r["t"])
        count += r["n"]
        subtotal += r["st"]; iva += r["iv"]; total += r["t"]
    cancelled = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM sales WHERE shift_id=? AND status='cancelada'", (shift_id,)
    ).fetchone()
    mv = {"entrada": 0.0, "salida": 0.0}
    for r in conn.execute("SELECT type, SUM(amount) a FROM cash_movements WHERE shift_id=? GROUP BY type", (shift_id,)):
        mv[r["type"]] = money(r["a"])
    expected = money(s["opening_float"] + by_method["efectivo"] + mv["entrada"] - mv["salida"])
    cashier = conn.execute("SELECT name FROM cashiers WHERE id=?", (s["cashier_id"],)).fetchone()
    return {
        "shift": dict(s),
        "cashier_name": cashier["name"] if cashier else "",
        "sales_count": count,
        "subtotal": money(subtotal), "iva": money(iva), "total": money(total),
        "by_method": by_method,
        "cancelled_count": cancelled["n"], "cancelled_total": money(cancelled["t"]),
        "cash_in": mv["entrada"], "cash_out": mv["salida"],
        "expected_cash": expected,
    }


@router.get("/shifts/current")
def current_shift(me: dict = Depends(current_cashier)):
    with db() as conn:
        s = open_shift_of(conn, me["id"])
        return {"shift": dict(s) if s else None, "report": shift_report(conn, s["id"]) if s else None}


@router.post("/shifts/open")
def open_shift(req: OpenShiftReq, me: dict = Depends(require("pos.sell"))):
    with db() as conn:
        if open_shift_of(conn, me["id"]):
            raise HTTPException(400, "Ya tienes un turno abierto.")
        cur = conn.execute(
            "INSERT INTO shifts(cashier_id, opened_at, opening_float) VALUES (?,?,?)",
            (me["id"], now(), money(req.opening_float)),
        )
        audit(conn, me, "turno_abierto", f"Fondo ${req.opening_float:.2f}", "turno")
        return {"id": cur.lastrowid}


@router.post("/shifts/movement")
def cash_movement(req: MovementReq, me: dict = Depends(require("pos.sell"))):
    with db() as conn:
        s = open_shift_of(conn, me["id"])
        if not s:
            raise HTTPException(400, "Abre un turno primero.")
        conn.execute(
            "INSERT INTO cash_movements(shift_id, type, amount, reason, created_at) VALUES (?,?,?,?,?)",
            (s["id"], req.type, money(req.amount), req.reason.strip(), now()),
        )
        return shift_report(conn, s["id"])


@router.get("/shifts/report/x")
def corte_x(me: dict = Depends(require("pos.sell"))):
    """Corte X: reporte parcial sin cerrar el turno."""
    with db() as conn:
        s = open_shift_of(conn, me["id"])
        if not s:
            raise HTTPException(400, "No hay turno abierto.")
        return shift_report(conn, s["id"])


@router.post("/shifts/close")
def corte_z(req: CloseShiftReq, me: dict = Depends(require("pos.sell"))):
    """Corte Z: cierra el turno, calcula la diferencia de arqueo."""
    with db() as conn:
        s = open_shift_of(conn, me["id"])
        if not s:
            raise HTTPException(400, "No hay turno abierto.")
        rep = shift_report(conn, s["id"])
        expected = rep["expected_cash"]
        diff = money(req.counted_cash - expected)
        conn.execute(
            "UPDATE shifts SET status='cerrado', closed_at=?, counted_cash=?, expected_cash=?, difference=?, notes=? WHERE id=?",
            (now(), money(req.counted_cash), expected, diff, req.notes or "", s["id"]),
        )
        audit(conn, me, "turno_cerrado", f"Esperado ${expected:.2f}, contado ${req.counted_cash:.2f}, diferencia ${diff:.2f}", "turno")
        return shift_report(conn, s["id"])


@router.get("/shifts")
def list_shifts(me: dict = Depends(current_cashier), limit: int = 50):
    with db() as conn:
        q = "SELECT s.*, c.name cashier_name FROM shifts s JOIN cashiers c ON c.id=s.cashier_id "
        args: list = []
        if not has_perm(me, "shifts.view_all"):
            q += "WHERE s.cashier_id=? "
            args.append(me["id"])
        q += "ORDER BY s.id DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in conn.execute(q, args)]


# ------------------------------------------------------------------ Productos (mínimo para POS; Fase 2 lo amplía)
class ProductIn(BaseModel):
    sku: Optional[str] = None
    barcode: Optional[str] = None
    name: str = Field(min_length=1)
    price: float = Field(ge=0)
    cost: float = Field(default=0, ge=0)
    iva_type: str = "iva16"
    stock: float = 0
    track_stock: bool = True
    sat_product_key: str = "01010101"
    sat_unit_key: str = "H87"
    active: bool = True


def _prod_args(p: ProductIn):
    if p.iva_type not in IVA_TYPES:
        raise HTTPException(400, "Tipo de IVA inválido (iva16, iva0, exento).")
    return (
        (p.sku or "").strip() or None, (p.barcode or "").strip() or None, p.name.strip(), money(p.price),
        money(p.cost), p.iva_type, p.stock, int(p.track_stock), p.sat_product_key, p.sat_unit_key, int(p.active),
    )


@router.get("/products")
def list_products(q: str = "", include_inactive: bool = False, _: dict = Depends(current_cashier)):
    sql = "SELECT * FROM products WHERE 1=1 "
    args: list = []
    if not include_inactive:
        sql += "AND active=1 "
    if q:
        sql += "AND (name LIKE ? OR sku LIKE ? OR barcode LIKE ?) "
        args += [f"%{q}%"] * 3
    sql += "ORDER BY name LIMIT 200"
    with db() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


@router.get("/products/barcode/{code}")
def product_by_code(code: str, _: dict = Depends(current_cashier)):
    with db() as conn:
        r = conn.execute("SELECT * FROM products WHERE (barcode=? OR sku=?) AND active=1", (code, code)).fetchone()
    if not r:
        raise HTTPException(404, "Producto no encontrado.")
    return dict(r)


@router.post("/products")
def create_product(p: ProductIn, _: dict = Depends(require("products.manage"))):
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO products(sku, barcode, name, price, cost, iva_type, stock, track_stock, "
                "sat_product_key, sat_unit_key, active) VALUES (?,?,?,?,?,?,?,?,?,?,?)", _prod_args(p))
            return {"id": cur.lastrowid}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "SKU o código de barras duplicado.")


@router.put("/products/{pid}")
def update_product(pid: int, p: ProductIn, _: dict = Depends(require("products.manage"))):
    try:
        with db() as conn:
            conn.execute(
                "UPDATE products SET sku=?, barcode=?, name=?, price=?, cost=?, iva_type=?, stock=?, track_stock=?, "
                "sat_product_key=?, sat_unit_key=?, active=? WHERE id=?", _prod_args(p) + (pid,))
        return {"ok": True}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "SKU o código de barras duplicado.")


# ------------------------------------------------------------------ Ventas
class SaleLine(BaseModel):
    product_id: int
    qty: float = Field(gt=0)


class SaleReq(BaseModel):
    items: List[SaleLine] = Field(min_length=1)
    payment_method: str
    received: float = Field(ge=0)


def split_iva(gross: float, iva_type: str):
    """Precio con IVA incluido -> (neto, iva)."""
    rate = IVA_TYPES[iva_type]
    net = gross / (1 + rate)
    return net, gross - net


@router.post("/sales")
def create_sale(req: SaleReq, me: dict = Depends(require("pos.sell"))):
    if req.payment_method not in PAYMENT_METHODS:
        raise HTTPException(400, "Forma de pago inválida.")
    with db() as conn:
        shift = open_shift_of(conn, me["id"])
        if not shift:
            raise HTTPException(400, "Debes abrir turno de caja antes de vender.")
        lines, subtotal, iva_total, total = [], 0.0, 0.0, 0.0
        for ln in req.items:
            p = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (ln.product_id,)).fetchone()
            if not p:
                raise HTTPException(404, f"Producto {ln.product_id} no existe o está inactivo.")
            if p["track_stock"] and p["stock"] < ln.qty:
                raise HTTPException(400, f"Stock insuficiente de '{p['name']}' (disponible: {p['stock']}).")
            gross = money(p["price"] * ln.qty)
            net, iva = split_iva(gross, p["iva_type"])
            lines.append((p, ln.qty, gross, money(net), money(iva)))
            subtotal += money(net); iva_total += money(iva); total += gross
        subtotal, iva_total, total = money(subtotal), money(iva_total), money(total)
        if req.payment_method == "efectivo":
            if req.received + 1e-9 < total:
                raise HTTPException(400, "El efectivo recibido es menor al total.")
            received, change = money(req.received), money(req.received - total)
        else:
            received, change = total, 0.0
        cur = conn.execute(
            "INSERT INTO sales(shift_id, cashier_id, created_at, subtotal, iva, total, payment_method, received, change_given) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (shift["id"], me["id"], now(), subtotal, iva_total, total, req.payment_method, received, change),
        )
        sale_id = cur.lastrowid
        conn.execute("UPDATE sales SET folio=? WHERE id=?", (f"V-{sale_id:06d}", sale_id))
        for p, qty, gross, net, iva in lines:
            conn.execute(
                "INSERT INTO sale_items(sale_id, product_id, name, barcode, qty, unit_price, unit_net, iva_type, iva, total, "
                "sat_product_key, sat_unit_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (sale_id, p["id"], p["name"], p["barcode"], qty, p["price"], money(p["price"] / (1 + IVA_TYPES[p["iva_type"]])),
                 p["iva_type"], iva, gross, p["sat_product_key"], p["sat_unit_key"]),
            )
            if p["track_stock"]:
                conn.execute("UPDATE products SET stock = stock - ? WHERE id=?", (qty, p["id"]))
                log_movement(conn, p["id"], "venta", -qty, p["cost"], "Venta POS", f"V-{sale_id:06d}", me["id"])
        audit(conn, me, "venta", f"V-{sale_id:06d} total ${total:.2f} ({req.payment_method})", "venta")
        return get_sale(conn, sale_id)


def get_sale(conn, sale_id: int) -> dict:
    s = conn.execute(
        "SELECT s.*, c.name cashier_name FROM sales s JOIN cashiers c ON c.id=s.cashier_id WHERE s.id=?", (sale_id,)
    ).fetchone()
    if not s:
        raise HTTPException(404, "Venta no encontrada.")
    sale = dict(s)
    sale["items"] = [dict(r) for r in conn.execute("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,))]
    inv = conn.execute("SELECT id, serie, folio, status FROM invoices WHERE sale_id=?", (sale_id,)).fetchone()
    sale["invoice"] = dict(inv) if inv else None
    return sale


@router.get("/sales")
def list_sales(me: dict = Depends(current_cashier), limit: int = 50, date: Optional[str] = None):
    sql = ("SELECT s.id, s.folio, s.created_at, s.total, s.payment_method, s.status, c.name cashier_name, "
           "(SELECT COUNT(*) FROM invoices i WHERE i.sale_id=s.id) invoiced "
           "FROM sales s JOIN cashiers c ON c.id=s.cashier_id WHERE 1=1 ")
    args: list = []
    if not has_perm(me, "shifts.view_all"):
        sql += "AND s.cashier_id=? "
        args.append(me["id"])
    if date:
        sql += "AND substr(s.created_at,1,10)=? "
        args.append(date)
    sql += "ORDER BY s.id DESC LIMIT ?"
    args.append(limit)
    with db() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


@router.get("/sales/{sale_id}")
def read_sale(sale_id: int, _: dict = Depends(current_cashier)):
    with db() as conn:
        return get_sale(conn, sale_id)


@router.post("/sales/{sale_id}/cancel")
def cancel_sale(sale_id: int, _: dict = Depends(require("sales.cancel"))):
    """Cancela una venta (solo admin), regresa el stock. No permite cancelar si ya fue facturada."""
    with db() as conn:
        sale = get_sale(conn, sale_id)
        if sale["status"] == "cancelada":
            raise HTTPException(400, "La venta ya está cancelada.")
        if sale["invoice"]:
            raise HTTPException(400, "La venta ya está facturada; cancela primero la factura.")
        for it in sale["items"]:
            cur = conn.execute("UPDATE products SET stock = stock + ? WHERE id=? AND track_stock=1", (it["qty"], it["product_id"]))
            if cur.rowcount:
                log_movement(conn, it["product_id"], "devolucion", it["qty"], 0, "Cancelación de venta", sale["folio"], _["id"])
        conn.execute("UPDATE sales SET status='cancelada' WHERE id=?", (sale_id,))
        audit(conn, _, "venta_cancelada", f"{sale['folio']} total ${sale['total']:.2f}", "venta")
        return get_sale(conn, sale_id)


# ------------------------------------------------------------------ Ticket imprimible
def render_ticket(sale: dict, st: dict, auto_print: bool) -> str:
    width = 58 if st.get("ticket_width") == "58" else 80
    e = escape
    rows = ""
    for it in sale["items"]:
        rows += (f"<tr><td colspan='3'>{e(it['name'])}</td></tr>"
                 f"<tr><td>{it['qty']:g} x ${it['unit_price']:.2f}</td><td></td><td class='r'>${it['total']:.2f}</td></tr>")
    iva_breakdown: dict = {}
    for it in sale["items"]:
        iva_breakdown.setdefault(it["iva_type"], [0.0, 0.0])
        iva_breakdown[it["iva_type"]][0] += it["total"] - it["iva"]
        iva_breakdown[it["iva_type"]][1] += it["iva"]
    labels = {"iva16": "IVA 16%", "iva0": "IVA 0%", "exento": "Exento"}
    iva_rows = "".join(
        f"<tr><td>Base {labels[k]}</td><td class='r' colspan='2'>${v[0]:.2f}</td></tr>"
        f"<tr><td>{labels[k]}</td><td class='r' colspan='2'>${v[1]:.2f}</td></tr>"
        for k, v in iva_breakdown.items())
    cancelled = "<div class='c b'>*** VENTA CANCELADA ***</div>" if sale["status"] == "cancelada" else ""
    pm = sale["payment_method"].capitalize()
    cash_rows = (f"<tr><td>Recibido</td><td class='r' colspan='2'>${sale['received']:.2f}</td></tr>"
                 f"<tr><td>Cambio</td><td class='r' colspan='2'>${sale['change_given']:.2f}</td></tr>"
                 if sale["payment_method"] == "efectivo" else "")
    script = "<script>window.onload=()=>{window.print();}</script>" if auto_print else ""
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>Ticket {e(sale['folio'])}</title>
<style>
 @page {{ size: {width}mm auto; margin: 2mm; }}
 body {{ font-family: 'Courier New', monospace; font-size: 12px; width: {width - 6}mm; margin: 0 auto; color:#000; }}
 table {{ width: 100%; border-collapse: collapse; }} td {{ padding: 1px 0; vertical-align: top; }}
 .r {{ text-align: right; }} .c {{ text-align: center; }} .b {{ font-weight: bold; }}
 hr {{ border: 0; border-top: 1px dashed #000; margin: 4px 0; }}
</style></head><body>
<div class="c b" style="font-size:14px">{e(st.get('business_name',''))}</div>
<div class="c">{e(st.get('legal_name',''))}<br>RFC: {e(st.get('rfc',''))}<br>{e(st.get('address',''))}<br>CP {e(st.get('zip_code',''))} {e(st.get('phone',''))}</div>
<hr>{cancelled}
<div>Folio: <b>{e(sale['folio'])}</b><br>Fecha: {e(sale['created_at'])}<br>Cajero: {e(sale['cashier_name'])}</div>
<hr><table>{rows}</table><hr>
<table>
<tr><td>Subtotal</td><td class='r' colspan='2'>${sale['subtotal']:.2f}</td></tr>
{iva_rows}
<tr class="b" style="font-size:14px"><td>TOTAL</td><td class='r' colspan='2'>${sale['total']:.2f}</td></tr>
<tr><td>Pago ({e(pm)})</td><td class='r' colspan='2'>${sale['received']:.2f}</td></tr>
{cash_rows}
</table><hr>
<div class="c">{e(st.get('ticket_footer',''))}<br>Para facturar conserve este ticket.<br>Folio de facturación: {e(sale['folio'])}</div>
<div class="c" style="margin-top:6px">||||| {e(sale['folio'])} |||||</div>
{script}</body></html>"""


@router.get("/sales/{sale_id}/ticket", response_class=HTMLResponse)
def ticket(sale_id: int, print: bool = Query(False), token: Optional[str] = Query(None),
           x_pos_token: Optional[str] = Header(None)):
    if (token or x_pos_token or "") not in SESSIONS:
        raise HTTPException(401, "Sesión no válida.")
    with db() as conn:
        return HTMLResponse(render_ticket(get_sale(conn, sale_id), get_settings(conn), print))


# ------------------------------------------------------------------ Facturación CFDI 4.0
class InvoiceReq(BaseModel):
    rfc: str
    razon_social: str = Field(min_length=2)
    regimen_fiscal: str = Field(pattern=r"^\d{3}$")
    codigo_postal: str = Field(pattern=r"^\d{5}$")
    uso_cfdi: str = Field(default="G03", min_length=3, max_length=4)
    email: Optional[str] = None


def build_cfdi_xml(sale: dict, st: dict, inv: InvoiceReq, serie: str, folio: str) -> str:
    NS = "http://www.sat.gob.mx/cfd/4"
    ET.register_namespace("cfdi", NS)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    q = lambda t: f"{{{NS}}}{t}"
    gravados, exentos = {}, 0.0  # tasa -> [base, importe]
    for it in sale["items"]:
        base = it["total"] - it["iva"]
        if it["iva_type"] == "exento":
            exentos += base
        else:
            t = gravados.setdefault(IVA_TYPES[it["iva_type"]], [0.0, 0.0])
            t[0] += base; t[1] += it["iva"]
    total_trasladado = sum(v[1] for v in gravados.values())
    root = ET.Element(q("Comprobante"), {
        "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":
            "http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd",
        "Version": "4.0", "Serie": serie, "Folio": folio,
        "Fecha": sale["created_at"].replace(" ", "T"),
        "FormaPago": PAYMENT_METHODS[sale["payment_method"]], "MetodoPago": "PUE",
        "SubTotal": f"{sale['subtotal']:.2f}", "Moneda": "MXN", "Total": f"{sale['total']:.2f}",
        "TipoDeComprobante": "I", "Exportacion": "01", "LugarExpedicion": st.get("zip_code", "00000"),
    })
    ET.SubElement(root, q("Emisor"), {
        "Rfc": st.get("rfc", ""), "Nombre": st.get("legal_name") or st.get("business_name", ""),
        "RegimenFiscal": st.get("tax_regime", "601")})
    ET.SubElement(root, q("Receptor"), {
        "Rfc": inv.rfc, "Nombre": inv.razon_social.upper(), "DomicilioFiscalReceptor": inv.codigo_postal,
        "RegimenFiscalReceptor": inv.regimen_fiscal, "UsoCFDI": inv.uso_cfdi})
    conceptos = ET.SubElement(root, q("Conceptos"))
    for it in sale["items"]:
        base = it["total"] - it["iva"]
        c = ET.SubElement(conceptos, q("Concepto"), {
            "ClaveProdServ": it["sat_product_key"], "Cantidad": f"{it['qty']:g}", "ClaveUnidad": it["sat_unit_key"],
            "Descripcion": it["name"], "ValorUnitario": f"{base / it['qty']:.6f}", "Importe": f"{base:.2f}",
            "ObjetoImp": "02"})
        imp = ET.SubElement(ET.SubElement(c, q("Impuestos")), q("Traslados"))
        if it["iva_type"] == "exento":
            ET.SubElement(imp, q("Traslado"), {"Base": f"{base:.2f}", "Impuesto": "002", "TipoFactor": "Exento"})
        else:
            ET.SubElement(imp, q("Traslado"), {
                "Base": f"{base:.2f}", "Impuesto": "002", "TipoFactor": "Tasa",
                "TasaOCuota": f"{IVA_TYPES[it['iva_type']]:.6f}", "Importe": f"{it['iva']:.2f}"})
    imps = ET.SubElement(root, q("Impuestos"), {"TotalImpuestosTrasladados": f"{total_trasladado:.2f}"})
    tr = ET.SubElement(imps, q("Traslados"))
    for rate, (base, importe) in gravados.items():
        ET.SubElement(tr, q("Traslado"), {
            "Base": f"{base:.2f}", "Impuesto": "002", "TipoFactor": "Tasa",
            "TasaOCuota": f"{rate:.6f}", "Importe": f"{importe:.2f}"})
    if exentos:
        ET.SubElement(tr, q("Traslado"), {"Base": f"{exentos:.2f}", "Impuesto": "002", "TipoFactor": "Exento"})
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


@router.post("/sales/{sale_id}/invoice")
def create_invoice(sale_id: int, req: InvoiceReq, me: dict = Depends(require("pos.sell"))):
    """
    Genera el CFDI 4.0 en XML (sin Sello/Certificado/Timbre). Queda 'pendiente_timbrado':
    el timbrado fiscal real requiere conectar un PAC y el CSD del emisor.
    """
    rfc = req.rfc.strip().upper()
    if not RFC_RE.match(rfc):
        raise HTTPException(400, "RFC del receptor inválido.")
    req.rfc = rfc
    with db() as conn:
        sale = get_sale(conn, sale_id)
        st = get_settings(conn)
        if sale["status"] != "completada":
            raise HTTPException(400, "Solo se pueden facturar ventas completadas.")
        if sale["invoice"]:
            raise HTTPException(400, "La venta ya fue facturada.")
        if not RFC_RE.match(st.get("rfc", "")) or st.get("rfc") == "XAXX010101000":
            raise HTTPException(400, "Configura el RFC del emisor en Configuración antes de facturar.")
        serie = st.get("invoice_series", "A")
        folio = str(sale_id)
        xml = build_cfdi_xml(sale, st, req, serie, folio)
        conn.execute(
            "INSERT INTO invoices(sale_id, serie, folio, rfc, razon_social, regimen_fiscal, codigo_postal, uso_cfdi, email, xml, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sale_id, serie, folio, rfc, req.razon_social.upper(), req.regimen_fiscal, req.codigo_postal,
             req.uso_cfdi, req.email, xml, now()),
        )
        audit(conn, me, "factura", f"{serie}{folio} RFC {rfc} venta {sale['folio']}", "factura")
        return {"serie": serie, "folio": folio, "status": "pendiente_timbrado"}


@router.get("/invoices")
def list_invoices(me: dict = Depends(current_cashier)):
    with db() as conn:
        rows = conn.execute(
            "SELECT i.id, i.sale_id, i.serie, i.folio, i.rfc, i.razon_social, i.status, i.created_at, s.total, s.folio sale_folio "
            "FROM invoices i JOIN sales s ON s.id=i.sale_id ORDER BY i.id DESC LIMIT 100").fetchall()
    return [dict(r) for r in rows]


@router.get("/invoices/{invoice_id}/xml")
def invoice_xml(invoice_id: int, token: Optional[str] = Query(None), x_pos_token: Optional[str] = Header(None)):
    if (token or x_pos_token or "") not in SESSIONS:
        raise HTTPException(401, "Sesión no válida.")
    with db() as conn:
        r = conn.execute("SELECT serie, folio, xml FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Factura no encontrada.")
    return Response(r["xml"], media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="CFDI_{r["serie"]}{r["folio"]}.xml"'})
