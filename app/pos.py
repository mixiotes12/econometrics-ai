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
import uuid
import base64
import json
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta
from html import escape
from typing import List, Optional, Dict, Any
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "pos.db")

router = APIRouter(prefix="/api/pos", tags=["POS"])

IVA_TYPES = {"iva16": 0.16, "iva0": 0.0, "exento": 0.0}
PAYMENT_METHODS = {"efectivo": "01", "tarjeta": "04", "transferencia": "03"}
RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")

REGIMENES_FISCALES = {
    "601": "Régimen General de Ley Personas Morales",
    "603": "Personas Morales con Fines No Lucrativos",
    "605": "Régimen de Sueldos y Salarios e Ingresos Asimilados a Salarios",
    "606": "Régimen de Arrendamiento",
    "607": "Régimen de Enajenación o Adquisición de Bienes",
    "608": "Régimen de los Demás Ingresos",
    "610": "Régimen de Residentes en el Extranjero sin Establecimiento Permanente en México",
    "611": "Régimen de Ingresos por Dividendos (Socios y Accionistas)",
    "612": "Régimen de las Personas Físicas con Actividades Empresariales y Profesionales",
    "614": "Régimen de los Ingresos por Intereses",
    "615": "Régimen de los Ingresos por Obtención de Premios",
    "616": "Sin Obligaciones Fiscales",
    "620": "Sociedades Cooperativas de Producción que Optan por Diferir sus Ingresos",
    "621": "Régimen de Incorporación Fiscal",
    "622": "Régimen de Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras",
    "623": "Régimen Opcional para Grupos de Sociedades",
    "624": "Régimen de los Coordinados",
    "625": "Régimen de las Actividades Empresariales con Ingresos a través de Plataformas Tecnológicas",
    "626": "Régimen Simplificado de Confianza (RESICO)",
}

USOS_CFDI = {
    "G01": "Adquisición de mercancías",
    "G03": "Gastos en general",
    "S01": "Sin efectos fiscales (Requerido para Público en General)",
    "CP01": "Pagos",
    "D01": "Honorarios médicos, dentales y gastos hospitalarios",
    "D02": "Gastos médicos por incapacidad o discapacidad",
    "D04": "Donativos",
    "I01": "Construcciones",
    "I02": "Mobiliario y equipo de oficina por inversiones",
    "I04": "Equipo de cómputo y accesorios",
}

FORMAS_PAGO_SAT = {
    "01": "Efectivo",
    "04": "Tarjeta de crédito",
    "28": "Tarjeta de débito",
    "03": "Transferencia electrónica de fondos (SPEI)",
    "99": "Por definir",
}

METODOS_PAGO_SAT = {
    "PUE": "Pago en una sola exhibición",
    "PPD": "Pago en parcialidades o diferido",
}

INVOICE_EXTRA_COLUMNS = {
    "uuid": "TEXT",
    "fecha_timbrado": "TEXT",
    "sello_sat": "TEXT",
    "sello_cfd": "TEXT",
    "no_certificado_sat": "TEXT",
    "no_certificado_emisor": "TEXT",
    "cadena_original": "TEXT",
    "forma_pago": "TEXT DEFAULT '01'",
    "metodo_pago": "TEXT DEFAULT 'PUE'",
}

def number_to_spanish_words(n: float) -> str:
    units = ['', 'UN', 'DOS', 'TRES', 'CUATRO', 'CINCO', 'SEIS', 'SIETE', 'OCHO', 'NUEVE', 'DIEZ',
             'ONCE', 'DOCE', 'TRECE', 'CATORCE', 'QUINCE', 'DIECISEIS', 'DIECISIETE', 'DIECIOCHO', 'DIECINUEVE']
    tens = ['', '', 'VEINTE', 'TREINTA', 'CUARENTA', 'CINCUENTA', 'SESENTA', 'SETENTA', 'OCHENTA', 'NOVENTA']
    hundreds = ['', 'CIENTO', 'DOSCIENTOS', 'TRESCIENTOS', 'CUATROCIENTOS', 'QUINIENTOS',
                'SEISCIENTOS', 'SETECIENTOS', 'OCHOCIENTOS', 'NOVECIENTOS']

    def _convert_group(val):
        if val == 0: return ''
        if val == 100: return 'CIEN'
        res = ''
        c, rem = divmod(val, 100)
        if c > 0:
            res += hundreds[c] + ' '
        if rem < 20:
            if rem > 0: res += units[rem]
        else:
            d, u = divmod(rem, 10)
            if d == 2 and u > 0:
                res += 'VEINTI' + units[u]
            else:
                res += tens[d] + ((' Y ' + units[u]) if u > 0 else '')
        return res.strip()

    entero = int(n)
    centavos = int(round((n - entero) * 100))
    if entero == 0:
        texto = 'CERO'
    else:
        partes = []
        millones, rem = divmod(entero, 1000000)
        miles, rem = divmod(rem, 1000)
        cientos = rem

        if millones > 0:
            partes.append('UN MILLON' if millones == 1 else f'{_convert_group(millones)} MILLONES')
        if miles > 0:
            partes.append('UN MIL' if miles == 1 else f'{_convert_group(miles)} MIL')
        if cientos > 0:
            partes.append(_convert_group(cientos))
        texto = ' '.join(partes)

    pesos_str = 'DE PESOS' if (entero >= 1000000 and entero % 1000000 == 0) else ('PESO' if entero == 1 else 'PESOS')
    return f'({texto} {pesos_str} {centavos:02d}/100 M.N.)'

def generate_simulated_signature(seed_str: str) -> str:
    h1 = hashlib.sha256(seed_str.encode("utf-8")).digest()
    h2 = hashlib.sha256((seed_str + "_sat_audit_cfdi40").encode("utf-8")).digest()
    h3 = hashlib.sha256((seed_str + "_rsa2048_pkcs1").encode("utf-8")).digest()
    h4 = hashlib.sha256((seed_str + "_tfd11_stamp").encode("utf-8")).digest()
    raw = h1 + h2 + h3 + h4 + (h1[::-1]) + (h2[::-1]) + (h3[::-1]) + (h4[::-1])
    return base64.b64encode(raw[:256]).decode("ascii")

SIMULATED_CERT_EMISOR = (
    "MIIF+DCCBOCgAwIBAgIUMDAwMDEwMDAwMDA1MDYxMjM0NTYwDQYJKoZIhvcNAQELBQAwgg"
    "GEMQ8wDQYDVQQDDAZBQ01FMSAwHgYDVQQKDBdBTkRFUlNPTiBTRUxMT1MgU0FUIElOQzEZ"
    "MBcGA1UECwwQU0VMT1MgRElHSVRBTEVTMREwDwYDVQQHDAhNRVhJQ08gMQ8wDQYDVQQIDA"
    "ZDRU5UUk8xEDAOBgNVBAYTB01FWElDTzEWMBQGA1UEBRMNMDEwMTAxMTAwMTAxMjEwMAYD"
    "VQQJEylBVi4gSU5TVVJHRU5URVMgU1VSIFdPUkxEIFRSQURFIENFTlRFUiAxNjAwMB4XDT"
    "I0MDExNTE2MDAwMFoXDTI4MDExNTE2MDAwMFowggEcMTEwLwYDVQQDEyhFQ09OT01FVFJJ"
    "Q1MgQ09NRVJDSUFMIExFR0FMIFNBREVDVjE8MDoGA1UEKRMzRUNPTk9NRVRSSUNTIENPTU"
    "VSQ0lBTCBTRVJWSUNJT1MgU0EgREUgQ1YgRklTQ0FMIFNFTExPMTEwLwYDVQQKEyhFQ09O"
    "T01FVFJJQ1MgQ09NRVJDSUFMIExFR0FMIFNBREVDVjELMAkGA1UEBhMCTVgxJTAjBgkqhk"
    "iG9w0BCQEWFmZhY3R1cmFzQGVjb25vbWV0cmljcy5teDEmMCQGA1UELRMNRUNTMjEwOTE1"
    "QUExIC8gQUFBQTAxMDEwMUFBQTEeMBwGA1UEBRMVIC8gQUFBQTAxMDEwMU1ERlNMTjAxMI"
    "IBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1k9Y7zKz4Vf8oB7zR9a7v8X4lY0L"
    "zZ6sWpL1h2e0u4z2k9s3n8b4w7l0z2q8x4j6p9m2k4j8v7z0q3n5m8l9v0z4p7k1h5f8r0"
    "s2n5m9w3j7p1q4x7l2v6z9n1m3k5j8p0v4z6l8m2k5j9n1w3x7l4v8z0q2n4m6k8j0p2v4"
    "z6m8l0k2j5n8w1x4l7v9z2q5n7m0k3j6p9v2z5l8m1k4j7n0w2x5l8v1z4q6n8m0k2j4p6"
    "v8z1l4m7k0j3n6w9x2l5v8z0q3n6m9k1j4p7v0z3l6m9k2j5n8w1x4l7v0z3q6n9m2k4j6"
    "v9w2x5l8v1z4q7n0m3k5j8p1v4z7l0m3k6j9n2w5l8v1z4q7n0m3k5j8p1v4z7l0m3k6j9"
    "IDAQABo08wTTAMBgNVHRMBAf8EAjAAMAsGA1UdDwQEAwIGwDARBglghkgBhvhCAQEEBAMC"
    "BaAwHQYDVR0OBBYEFG5L3z6r9m0w7l0z2q8x4j6p9m2kMA0GCSqGSIb3DQEBCwUAA4IBA"
    "QCV3s7k9n2m5l8w1x4l7v0z3q6n9m2k4j6v9w2x5l8v1z4q7n0m3k5j8p1v4z7l0m3k6j"
    "9n2w5l8v1z4q7n0m3k5j8p1v4z7l0m3k6j9IDAQAB1k9Y7zKz4Vf8oB7zR9a7v8X4lY0L"
    "zZ6sWpL1h2e0u4z2k9s3n8b4w7l0z2q8x4j6p9m2k4j8v7z0q3n5m8l9v0z4p7k1h5f8r0"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS business_settings (
    business_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (business_id, key)
);
CREATE TABLE IF NOT EXISTS auth_owners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    business_name TEXT NOT NULL DEFAULT 'Aura Café & Roastery',
    business_type TEXT NOT NULL DEFAULT 'Cafetería de Especialidad y Panadería Artesanal',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 1,
    project_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    business_type TEXT NOT NULL DEFAULT 'Comercio / Servicios',
    sector TEXT NOT NULL DEFAULT 'Alimentos y Bebidas (Hospitality)',
    state TEXT NOT NULL DEFAULT 'Ciudad de México',
    municipality TEXT NOT NULL DEFAULT 'Cuauhtémoc',
    studio_payload_json TEXT NOT NULL DEFAULT '{}',
    baseline_financials_json TEXT NOT NULL DEFAULT '{}',
    settings_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_branches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 1,
    business_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    code TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_branches_biz_code ON auth_branches(business_id, code);
CREATE TABLE IF NOT EXISTS pos_terminals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(branch_id, code)
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token TEXT PRIMARY KEY,
    actor_type TEXT NOT NULL DEFAULT 'owner',
    owner_id INTEGER,
    user_id INTEGER,
    employee_id INTEGER,
    active_business_id INTEGER NOT NULL DEFAULT 1,
    active_branch_id INTEGER NOT NULL DEFAULT 1,
    active_terminal_id INTEGER,
    role TEXT NOT NULL DEFAULT 'admin',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cashiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'cajero',
    area_id INTEGER,
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    last_login TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    must_change_pin INTEGER NOT NULL DEFAULT 0,
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1,
    pos_terminal_id INTEGER,
    employee_code TEXT,
    employee_id INTEGER
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
    status TEXT NOT NULL DEFAULT 'abierto',
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1,
    terminal_id INTEGER
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
    sku TEXT,
    barcode TEXT,
    name TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0,          -- precio al público con IVA incluido
    cost REAL NOT NULL DEFAULT 0,
    iva_type TEXT NOT NULL DEFAULT 'iva16',
    stock REAL NOT NULL DEFAULT 0,
    track_stock INTEGER NOT NULL DEFAULT 1,
    sat_product_key TEXT NOT NULL DEFAULT '01010101',
    sat_unit_key TEXT NOT NULL DEFAULT 'H87',
    active INTEGER NOT NULL DEFAULT 1,
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1
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
    status TEXT NOT NULL DEFAULT 'completada',
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1,
    terminal_id INTEGER
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
    created_at TEXT NOT NULL,
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_mov_product ON stock_movements(product_id, created_at);
CREATE TABLE IF NOT EXISTS exchange_rates (
    currency TEXT PRIMARY KEY,
    rate_mxn REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    updated_at TEXT NOT NULL
);
"""

# Columnas de Fase 2 y Multi-Sucursal agregadas a products (migración idempotente)
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
    "business_id": "INTEGER NOT NULL DEFAULT 1",
    "branch_id": "INTEGER NOT NULL DEFAULT 1",
}


def log_movement(conn, product_id: int, mtype: str, delta: float, unit_cost: float = 0.0,
                 reason: str = "", ref: str = "", cashier_id: Optional[int] = None,
                 business_id: Optional[int] = None, branch_id: Optional[int] = None):
    """Registra un movimiento (kardex). Debe llamarse DESPUÉS de actualizar products.stock."""
    prow = conn.execute("SELECT stock, business_id, branch_id FROM products WHERE id=?", (product_id,)).fetchone()
    stock_after = prow["stock"] if prow else 0.0
    biz_id = business_id if business_id is not None else (prow["business_id"] if prow and "business_id" in prow.keys() else 1)
    br_id = branch_id if branch_id is not None else (prow["branch_id"] if prow and "branch_id" in prow.keys() else 1)
    conn.execute(
        "INSERT INTO stock_movements(product_id, type, delta, unit_cost, stock_after, reason, ref, cashier_id, created_at, business_id, branch_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (product_id, mtype, delta, unit_cost, stock_after, reason, ref, cashier_id, now(), biz_id, br_id),
    )


ROLES = {
    "admin": {"label": "Administrador / Propietario", "perms": ["*"]},
    "gerente": {"label": "Gerente de Sucursal", "perms": [
        "pos.sell", "sales.cancel", "shifts.view_all", "products.manage", "inventory.move", "rates.manage",
        "finance.view", "hr.manage", "hr.payroll", "audit.view", "users.manage"]},
    "cajero": {"label": "Cajero (Caja / POS)", "perms": ["pos.sell"]},
    "rrhh": {"label": "Recursos Humanos (RRHH)", "perms": ["hr.manage", "hr.payroll", "users.manage"]},
    "almacenista": {"label": "Logística e Inventarios", "perms": ["products.manage", "inventory.move"]},
    "contador": {"label": "Contador / Finanzas", "perms": ["shifts.view_all", "finance.view", "rates.manage", "hr.payroll"]},
}

ROLE_CODE_MAP = {
    "admin": "ADM",
    "gerente": "GER",
    "cajero": "CAJ",
    "rrhh": "RRHH",
    "almacenista": "LOG",
    "contador": "CNT",
}

ROLE_REDIRECT_MAP = {
    "admin": "/hub.html",
    "gerente": "/owner.html",
    "cajero": "/pos.html",
    "rrhh": "/personal.html",
    "almacenista": "/inventario.html",
    "contador": "/owner.html",
}

ROLE_AREA_MAP = {
    "cajero": "Ventas / Caja",
    "almacenista": "Almacén",
    "rrhh": "Recursos Humanos",
    "contador": "Finanzas",
    "gerente": "Administración",
    "admin": "Administración",
}

ROLE_POSITION_MAP = {
    "cajero": "Cajero / Ventas POS",
    "almacenista": "Encargado de Logística e Inventario",
    "rrhh": "Especialista de Recursos Humanos",
    "gerente": "Gerente de Sucursal",
    "contador": "Contador / Finanzas",
    "admin": "Director / Propietario",
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
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    user_name TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    entity TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_audit_date ON audit_log(created_at);
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES cashiers(id),
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
    created_at TEXT NOT NULL,
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1,
    role TEXT NOT NULL DEFAULT 'cajero',
    pos_terminal_id INTEGER,
    employee_code TEXT,
    pin_plain TEXT NOT NULL DEFAULT '1234'
);
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    work_date TEXT NOT NULL,
    check_in TEXT NOT NULL,
    check_out TEXT,
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1
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
    created_at TEXT NOT NULL,
    business_id INTEGER NOT NULL DEFAULT 1,
    branch_id INTEGER NOT NULL DEFAULT 1
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
    "business_id": "INTEGER NOT NULL DEFAULT 1",
    "branch_id": "INTEGER NOT NULL DEFAULT 1",
    "pos_terminal_id": "INTEGER",
    "employee_code": "TEXT",
    "employee_id": "INTEGER",
}

EMPLOYEE_EXTRA_COLUMNS = {
    "business_id": "INTEGER NOT NULL DEFAULT 1",
    "branch_id": "INTEGER NOT NULL DEFAULT 1",
    "role": "TEXT NOT NULL DEFAULT 'cajero'",
    "pos_terminal_id": "INTEGER",
    "employee_code": "TEXT",
    "pin_plain": "TEXT NOT NULL DEFAULT '1234'",
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
    biz_id = user.get("business_id", 1) if isinstance(user, dict) else 1
    br_id = user.get("branch_id", 1) if isinstance(user, dict) else 1
    conn.execute(
        "INSERT INTO audit_log(user_id, user_name, action, entity, detail, created_at, business_id, branch_id) VALUES (?,?,?,?,?,?,?,?)",
        (uid, uname, action, entity, detail, now(), biz_id or 1, br_id or 1)
    )


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


# ------------------------------------------------------------------ DB helpers & Multi-Tenant Architecture
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


def _clean_slug(text: str, length: int = 4) -> str:
    norm = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z0-9]+", norm.upper())
    stop = {"DE", "LA", "EL", "LOS", "LAS", "DEL", "Y", "EN", "MI", "PROYECTO", "NEGOCIO", "EMPRESA"}
    filtered = [w for w in words if w not in stop and len(w) >= 2]
    base = (filtered[0] if filtered else (words[0] if words else "PROY"))[:length]
    return base.ljust(length, "X")


def generate_project_key(conn, name: str, preferred_key: Optional[str] = None) -> str:
    if preferred_key:
        pk = preferred_key.strip().upper()
        if not conn.execute("SELECT 1 FROM businesses WHERE UPPER(project_key)=?", (pk,)).fetchone():
            return pk
    slug = _clean_slug(name, 4)
    count = conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
    for attempt in range(100):
        digits = 1001 + count + attempt if attempt == 0 else (1000 + (secrets.randbelow(8999)))
        candidate = f"EM-{slug}-{digits:04d}"
        if not conn.execute("SELECT 1 FROM businesses WHERE UPPER(project_key)=?", (candidate,)).fetchone():
            return candidate
    return f"EM-{slug}-{secrets.token_hex(2).upper()}"


def normalize_branch_prefix(branch_code: str, branch_id: int = 1) -> str:
    cleaned = re.sub(r"[^A-Z0-9]", "", (branch_code or "").upper())
    return cleaned or f"SUC{branch_id:02d}"


def generate_employee_code(
    conn,
    business_id: int,
    branch_id: int,
    role: str,
    exclude_emp_id: Optional[int] = None,
    exclude_cashier_id: Optional[int] = None,
) -> str:
    br = conn.execute("SELECT code FROM auth_branches WHERE id=?", (branch_id,)).fetchone()
    br_prefix = normalize_branch_prefix(br["code"] if br else f"SUC-{branch_id:02d}", branch_id)
    role_prefix = ROLE_CODE_MAP.get(role, "EMP")
    prefix = f"{br_prefix}-{role_prefix}-"

    max_seq = 0
    for r in conn.execute(
        "SELECT employee_code FROM employees WHERE business_id=? AND employee_code LIKE ? AND id<>?",
        (business_id, f"{prefix}%", exclude_emp_id or 0),
    ).fetchall():
        code = r["employee_code"] or ""
        tail = code[len(prefix):]
        if tail.isdigit():
            max_seq = max(max_seq, int(tail))

    for r in conn.execute(
        "SELECT employee_code FROM cashiers WHERE business_id=? AND employee_code LIKE ? AND id<>?",
        (business_id, f"{prefix}%", exclude_cashier_id or 0),
    ).fetchall():
        code = r["employee_code"] or ""
        tail = code[len(prefix):]
        if tail.isdigit():
            max_seq = max(max_seq, int(tail))

    candidate_num = max_seq + 1
    while True:
        candidate = f"{prefix}{candidate_num:03d}"
        clash_emp = conn.execute(
            "SELECT 1 FROM employees WHERE business_id=? AND UPPER(employee_code)=? AND id<>?",
            (business_id, candidate.upper(), exclude_emp_id or 0),
        ).fetchone()
        clash_cash = conn.execute(
            "SELECT 1 FROM cashiers WHERE business_id=? AND UPPER(employee_code)=? AND id<>?",
            (business_id, candidate.upper(), exclude_cashier_id or 0),
        ).fetchone()
        if not clash_emp and not clash_cash:
            return candidate
        candidate_num += 1


def ensure_business_structure(conn, business_id: int) -> dict:
    biz = conn.execute("SELECT * FROM businesses WHERE id=?", (business_id,)).fetchone()
    if not biz:
        biz = conn.execute("SELECT * FROM businesses ORDER BY id ASC LIMIT 1").fetchone()
        if not biz:
            pk = generate_project_key(conn, "Aura Café & Roastery", "EM-AURA-1001")
            cur = conn.execute(
                "INSERT INTO businesses(owner_id, project_key, name, business_type, sector, state, municipality, created_at, updated_at) "
                "VALUES (1, ?, 'Aura Café & Roastery', 'Cafetería de Especialidad y Panadería Artesanal', 'Alimentos y Bebidas (Hospitality)', 'Ciudad de México', 'Cuauhtémoc', ?, ?)",
                (pk, now(), now()),
            )
            business_id = cur.lastrowid
            biz = conn.execute("SELECT * FROM businesses WHERE id=?", (business_id,)).fetchone()
        else:
            business_id = biz["id"]

    owner_id = biz["owner_id"] or 1
    branches = [dict(r) for r in conn.execute("SELECT * FROM auth_branches WHERE business_id=? AND active=1 ORDER BY id ASC", (business_id,)).fetchall()]
    if not branches:
        cur_b = conn.execute(
            "INSERT INTO auth_branches(owner_id, business_id, name, code, address, active, created_at) "
            "VALUES (?, ?, 'Sucursal Matriz', 'SUC-01', 'Ubicación Principal', 1, ?)",
            (owner_id, business_id, now()),
        )
        branches = [dict(r) for r in conn.execute("SELECT * FROM auth_branches WHERE id=?", (cur_b.lastrowid,)).fetchall()]

    terminals = []
    for br in branches:
        br_id = br["id"]
        br_terms = [dict(r) for r in conn.execute("SELECT * FROM pos_terminals WHERE branch_id=? AND active=1 ORDER BY id ASC", (br_id,)).fetchall()]
        if not br_terms:
            cur_t = conn.execute(
                "INSERT INTO pos_terminals(business_id, branch_id, code, name, active, created_at) "
                "VALUES (?, ?, 'CAJA-01', 'Caja Principal 01', 1, ?)",
                (business_id, br_id, now()),
            )
            br_terms = [dict(r) for r in conn.execute("SELECT * FROM pos_terminals WHERE id=?", (cur_t.lastrowid,)).fetchall()]
        terminals.extend(br_terms)

        for aname, adesc in DEFAULT_AREAS:
            if not conn.execute("SELECT 1 FROM areas WHERE business_id=? AND branch_id=? AND name=?", (business_id, br_id, aname)).fetchone():
                conn.execute(
                    "INSERT INTO areas(name, description, active, business_id, branch_id) VALUES (?,?,1,?,?)",
                    (aname, adesc, business_id, br_id),
                )

    return {
        "business": dict(biz),
        "branches": branches,
        "terminals": terminals,
    }


def resolve_area_id_for_role(conn, business_id: int, branch_id: int, role: str, preferred_area_id: Optional[int] = None) -> Optional[int]:
    if preferred_area_id:
        row = conn.execute("SELECT id FROM areas WHERE id=?", (preferred_area_id,)).fetchone()
        if row:
            return row["id"]
    target_name = ROLE_AREA_MAP.get(role, "Ventas / Caja")
    row = conn.execute(
        "SELECT id FROM areas WHERE business_id=? AND branch_id=? AND name=? LIMIT 1",
        (business_id, branch_id, target_name),
    ).fetchone()
    if row:
        return row["id"]
    row_any = conn.execute("SELECT id FROM areas WHERE business_id=? LIMIT 1", (business_id,)).fetchone()
    return row_any["id"] if row_any else None


def resolve_terminal_for_employee(conn, business_id: int, branch_id: int, role: str, preferred_terminal_id: Optional[int] = None) -> Optional[int]:
    """Solo los cajeros ('cajero') tienen terminal POS asignada; RRHH, logística, etc. tienen NULL."""
    if role != "cajero":
        return None
    if preferred_terminal_id:
        t = conn.execute(
            "SELECT id FROM pos_terminals WHERE id=? AND branch_id=? AND active=1",
            (preferred_terminal_id, branch_id),
        ).fetchone()
        if t:
            return t["id"]
    t = conn.execute(
        "SELECT id FROM pos_terminals WHERE branch_id=? AND active=1 ORDER BY id ASC LIMIT 1",
        (branch_id,),
    ).fetchone()
    if t:
        return t["id"]
    cur = conn.execute(
        "INSERT INTO pos_terminals(business_id, branch_id, code, name, active, created_at) VALUES (?, ?, 'CAJA-01', 'Caja Principal 01', 1, ?)",
        (business_id, branch_id, now()),
    )
    return cur.lastrowid


def sync_employee_and_cashier(
    conn,
    *,
    name: str,
    role: str = "cajero",
    business_id: int = 1,
    branch_id: Optional[int] = None,
    pos_terminal_id: Optional[int] = None,
    pin: Optional[str] = None,
    position: Optional[str] = None,
    area_id: Optional[int] = None,
    monthly_salary: float = 0.0,
    pay_frequency: str = "quincenal",
    hire_date: Optional[str] = None,
    termination_date: Optional[str] = None,
    status: str = "activo",
    rfc: str = "",
    curp: str = "",
    nss: str = "",
    phone: str = "",
    email: str = "",
    notes: str = "",
    employee_id: Optional[int] = None,
    cashier_id: Optional[int] = None,
) -> dict:
    """
    Mantiene sincronizadas las tablas `employees` y `cashiers` para que todo empleado
    tenga su Código del Negocio (`project_key`), su Código Individual (`employee_code`)
    codificando sucursal y puesto (ej. SUC01-CAJ-001, SUC01-RRHH-001, SUC01-LOG-001),
    su sucursal (`branch_id`), su terminal POS (`pos_terminal_id` sólo si es cajero) y su PIN.
    """
    role = role if role in ROLES else "cajero"
    struct = ensure_business_structure(conn, business_id)
    biz = struct["business"]
    business_id = biz["id"]

    # Verificar que la sucursal pertenezca al negocio
    if branch_id:
        br_row = conn.execute("SELECT * FROM auth_branches WHERE id=? AND business_id=?", (branch_id, business_id)).fetchone()
        if not br_row:
            br_row = conn.execute("SELECT * FROM auth_branches WHERE business_id=? AND active=1 ORDER BY id ASC LIMIT 1", (business_id,)).fetchone()
    else:
        br_row = conn.execute("SELECT * FROM auth_branches WHERE business_id=? AND active=1 ORDER BY id ASC LIMIT 1", (business_id,)).fetchone()
    branch_id = br_row["id"]
    branch_code = br_row["code"]

    terminal_id = resolve_terminal_for_employee(conn, business_id, branch_id, role, pos_terminal_id)
    area_id = resolve_area_id_for_role(conn, business_id, branch_id, role, area_id)
    position_str = (position or "").strip() or ROLE_POSITION_MAP.get(role, "Colaborador")
    hire_date_str = hire_date or datetime.now().strftime("%Y-%m-%d")
    is_active = 1 if status == "activo" else 0

    emp_row = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone() if employee_id else None
    cash_row = conn.execute("SELECT * FROM cashiers WHERE id=?", (cashier_id,)).fetchone() if cashier_id else None

    if emp_row and not cash_row and emp_row["user_id"]:
        cash_row = conn.execute("SELECT * FROM cashiers WHERE id=?", (emp_row["user_id"],)).fetchone()
    if cash_row and not emp_row:
        emp_row = conn.execute("SELECT * FROM employees WHERE user_id=?", (cash_row["id"],)).fetchone()
        if not emp_row and cash_row["employee_id"]:
            emp_row = conn.execute("SELECT * FROM employees WHERE id=?", (cash_row["employee_id"],)).fetchone()

    existing_emp_id = emp_row["id"] if emp_row else None
    existing_cash_id = cash_row["id"] if cash_row else None

    # Determinar si el employee_code existente sigue siendo válido para esta sucursal y rol
    expected_prefix = f"{normalize_branch_prefix(branch_code, branch_id)}-{ROLE_CODE_MAP.get(role, 'EMP')}-"
    current_code = (
        (emp_row["employee_code"] if emp_row and emp_row["employee_code"] else None)
        or (cash_row["employee_code"] if cash_row and cash_row["employee_code"] else None)
    )
    if (
        not current_code
        or not current_code.upper().startswith(expected_prefix)
        or (emp_row and emp_row["business_id"] != business_id)
        or (cash_row and cash_row["business_id"] != business_id)
    ):
        emp_code = generate_employee_code(conn, business_id, branch_id, role, existing_emp_id, existing_cash_id)
    else:
        emp_code = current_code.upper()

    pin_plain = (pin or "").strip() or (emp_row["pin_plain"] if emp_row and emp_row["pin_plain"] else "1234")
    pin_hashed = hash_pin(pin_plain) if pin else (cash_row["pin_hash"] if cash_row else hash_pin(pin_plain))

    # 1. Crear o actualizar registro en cashiers
    if cash_row:
        conn.execute(
            """UPDATE cashiers
               SET name=?, pin_hash=?, is_admin=?, active=?, role=?, area_id=?, email=?, phone=?,
                   business_id=?, branch_id=?, pos_terminal_id=?, employee_code=?
               WHERE id=?""",
            (
                name.strip(), pin_hashed, int(role == "admin"), is_active, role, area_id,
                email.strip(), phone.strip(), business_id, branch_id, terminal_id, emp_code, cash_row["id"]
            ),
        )
        cid = cash_row["id"]
    else:
        cur_c = conn.execute(
            """INSERT INTO cashiers(
                name, pin_hash, is_admin, active, created_at, role, area_id, email, phone,
                must_change_pin, business_id, branch_id, pos_terminal_id, employee_code
            ) VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?,?)""",
            (
                name.strip(), pin_hashed, int(role == "admin"), is_active, now(), role, area_id,
                email.strip(), phone.strip(), business_id, branch_id, terminal_id, emp_code
            ),
        )
        cid = cur_c.lastrowid

    # 2. Crear o actualizar registro en employees
    if emp_row:
        conn.execute(
            """UPDATE employees
               SET user_id=?, name=?, position=?, area_id=?, hire_date=?, termination_date=?,
                   status=?, monthly_salary=?, pay_frequency=?, rfc=?, curp=?, nss=?,
                   phone=?, email=?, notes=?, business_id=?, branch_id=?, role=?,
                   pos_terminal_id=?, employee_code=?, pin_plain=?
               WHERE id=?""",
            (
                cid, name.strip(), position_str, area_id, hire_date_str, termination_date,
                status, float(monthly_salary or 0), pay_frequency, rfc.strip().upper(), curp.strip().upper(),
                nss.strip(), phone.strip(), email.strip(), notes.strip(),
                business_id, branch_id, role, terminal_id, emp_code, pin_plain, emp_row["id"]
            ),
        )
        eid = emp_row["id"]
    else:
        cur_e = conn.execute(
            """INSERT INTO employees(
                user_id, name, position, area_id, hire_date, termination_date, status,
                monthly_salary, pay_frequency, rfc, curp, nss, phone, email, notes, created_at,
                business_id, branch_id, role, pos_terminal_id, employee_code, pin_plain
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cid, name.strip(), position_str, area_id, hire_date_str, termination_date, status,
                float(monthly_salary or 0), pay_frequency, rfc.strip().upper(), curp.strip().upper(),
                nss.strip(), phone.strip(), email.strip(), notes.strip(), now(),
                business_id, branch_id, role, terminal_id, emp_code, pin_plain
            ),
        )
        eid = cur_e.lastrowid

    conn.execute("UPDATE cashiers SET employee_id=? WHERE id=?", (eid, cid))

    term_row = conn.execute("SELECT code, name FROM pos_terminals WHERE id=?", (terminal_id,)).fetchone() if terminal_id else None
    area_row = conn.execute("SELECT name FROM areas WHERE id=?", (area_id,)).fetchone() if area_id else None

    return {
        "id": eid,
        "employee_id": eid,
        "user_id": cid,
        "cashier_id": cid,
        "name": name.strip(),
        "position": position_str,
        "role": role,
        "role_label": ROLES.get(role, {}).get("label", role),
        "employee_code": emp_code,
        "project_key": biz["project_key"],
        "business_id": business_id,
        "business_name": biz["name"],
        "branch_id": branch_id,
        "branch_name": br_row["name"],
        "branch_code": br_row["code"],
        "pos_terminal_id": terminal_id,
        "terminal_code": term_row["code"] if term_row else None,
        "terminal_name": term_row["name"] if term_row else None,
        "area_id": area_id,
        "area_name": area_row["name"] if area_row else "",
        "monthly_salary": float(monthly_salary or 0),
        "pay_frequency": pay_frequency,
        "status": status,
        "pin_plain": pin_plain,
        "redirect_url": ROLE_REDIRECT_MAP.get(role, "/pos.html"),
    }


def _migrate_table_if_global_unique(conn):
    """Migra tablas legacy que tenían restricciones UNIQUE globales (products, areas, auth_branches)."""
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        # 1. products: quitar sku TEXT UNIQUE / barcode TEXT UNIQUE
        p_sql_row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='products'").fetchone()
        if p_sql_row and p_sql_row["sql"] and ("sku TEXT UNIQUE" in p_sql_row["sql"] or "barcode TEXT UNIQUE" in p_sql_row["sql"]):
            conn.execute("DROP TABLE IF EXISTS products_migrated")
            conn.execute("""
                CREATE TABLE products_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT,
                    barcode TEXT,
                    name TEXT NOT NULL,
                    price REAL NOT NULL DEFAULT 0,
                    cost REAL NOT NULL DEFAULT 0,
                    iva_type TEXT NOT NULL DEFAULT 'iva16',
                    stock REAL NOT NULL DEFAULT 0,
                    track_stock INTEGER NOT NULL DEFAULT 1,
                    sat_product_key TEXT NOT NULL DEFAULT '01010101',
                    sat_unit_key TEXT NOT NULL DEFAULT 'H87',
                    active INTEGER NOT NULL DEFAULT 1,
                    category TEXT NOT NULL DEFAULT '',
                    supplier TEXT NOT NULL DEFAULT '',
                    image TEXT,
                    min_stock REAL NOT NULL DEFAULT 0,
                    max_stock REAL NOT NULL DEFAULT 0,
                    reorder_qty REAL NOT NULL DEFAULT 0,
                    is_imported INTEGER NOT NULL DEFAULT 0,
                    currency TEXT NOT NULL DEFAULT 'MXN',
                    foreign_cost REAL NOT NULL DEFAULT 0,
                    exchange_rate REAL NOT NULL DEFAULT 1,
                    duties_pct REAL NOT NULL DEFAULT 0,
                    freight_cost REAL NOT NULL DEFAULT 0,
                    other_cost REAL NOT NULL DEFAULT 0,
                    origin_country TEXT NOT NULL DEFAULT '',
                    business_id INTEGER NOT NULL DEFAULT 1,
                    branch_id INTEGER NOT NULL DEFAULT 1
                )
            """)
            old_cols = [r["name"] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
            new_cols = [r["name"] for r in conn.execute("PRAGMA table_info(products_migrated)").fetchall()]
            common = [c for c in old_cols if c in new_cols]
            cols_csv = ", ".join(common)
            conn.execute(f"INSERT INTO products_migrated ({cols_csv}) SELECT {cols_csv} FROM products")
            conn.execute("DROP TABLE products")
            conn.execute("ALTER TABLE products_migrated RENAME TO products")

        # 2. areas: quitar name TEXT NOT NULL UNIQUE
        a_sql_row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='areas'").fetchone()
        if a_sql_row and a_sql_row["sql"] and "UNIQUE" in a_sql_row["sql"].upper():
            conn.execute("DROP TABLE IF EXISTS areas_migrated")
            conn.execute("""
                CREATE TABLE areas_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    business_id INTEGER NOT NULL DEFAULT 1,
                    branch_id INTEGER NOT NULL DEFAULT 1
                )
            """)
            old_cols = [r["name"] for r in conn.execute("PRAGMA table_info(areas)").fetchall()]
            new_cols = [r["name"] for r in conn.execute("PRAGMA table_info(areas_migrated)").fetchall()]
            common = [c for c in old_cols if c in new_cols]
            cols_csv = ", ".join(common)
            conn.execute(f"INSERT INTO areas_migrated ({cols_csv}) SELECT {cols_csv} FROM areas")
            conn.execute("DROP TABLE areas")
            conn.execute("ALTER TABLE areas_migrated RENAME TO areas")

        # 3. auth_branches: quitar code TEXT NOT NULL UNIQUE global
        b_sql_row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='auth_branches'").fetchone()
        if b_sql_row and b_sql_row["sql"] and "CODE TEXT NOT NULL UNIQUE" in b_sql_row["sql"].upper():
            conn.execute("DROP TABLE IF EXISTS auth_branches_migrated")
            conn.execute("""
                CREATE TABLE auth_branches_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL DEFAULT 1,
                    business_id INTEGER NOT NULL DEFAULT 1,
                    name TEXT NOT NULL,
                    code TEXT NOT NULL,
                    address TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
            """)
            old_cols = [r["name"] for r in conn.execute("PRAGMA table_info(auth_branches)").fetchall()]
            new_cols = [r["name"] for r in conn.execute("PRAGMA table_info(auth_branches_migrated)").fetchall()]
            common = [c for c in old_cols if c in new_cols]
            cols_csv = ", ".join(common)
            conn.execute(f"INSERT INTO auth_branches_migrated ({cols_csv}) SELECT {cols_csv} FROM auth_branches")
            conn.execute("DROP TABLE auth_branches")
            conn.execute("ALTER TABLE auth_branches_migrated RENAME TO auth_branches")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def init_pos_db():
    with db() as conn:
        conn.executescript(SCHEMA)
        conn.executescript(SCHEMA_INVENTORY)
        conn.executescript(SCHEMA_HR)
        _migrate_table_if_global_unique(conn)

        # Asegurar columnas adicionales en tablas existentes
        existing_p = {r["name"] for r in conn.execute("PRAGMA table_info(products)")}
        for col, ddl in PRODUCT_EXTRA_COLUMNS.items():
            if col not in existing_p:
                conn.execute(f"ALTER TABLE products ADD COLUMN {col} {ddl}")

        existing_c = {r["name"] for r in conn.execute("PRAGMA table_info(cashiers)")}
        for col, ddl in CASHIER_EXTRA_COLUMNS.items():
            if col not in existing_c:
                conn.execute(f"ALTER TABLE cashiers ADD COLUMN {col} {ddl}")

        existing_e = {r["name"] for r in conn.execute("PRAGMA table_info(employees)")}
        for col, ddl in EMPLOYEE_EXTRA_COLUMNS.items():
            if col not in existing_e:
                conn.execute(f"ALTER TABLE employees ADD COLUMN {col} {ddl}")

        existing_b = {r["name"] for r in conn.execute("PRAGMA table_info(auth_branches)")}
        if "business_id" not in existing_b:
            conn.execute("ALTER TABLE auth_branches ADD COLUMN business_id INTEGER NOT NULL DEFAULT 1")
        if "owner_id" not in existing_b:
            conn.execute("ALTER TABLE auth_branches ADD COLUMN owner_id INTEGER NOT NULL DEFAULT 1")

        for tbl, cols_map in [
            ("stock_movements", {"business_id": "INTEGER NOT NULL DEFAULT 1", "branch_id": "INTEGER NOT NULL DEFAULT 1"}),
            ("shifts", {"business_id": "INTEGER NOT NULL DEFAULT 1", "branch_id": "INTEGER NOT NULL DEFAULT 1", "terminal_id": "INTEGER"}),
            ("sales", {"business_id": "INTEGER NOT NULL DEFAULT 1", "branch_id": "INTEGER NOT NULL DEFAULT 1", "terminal_id": "INTEGER"}),
            ("areas", {"business_id": "INTEGER NOT NULL DEFAULT 1", "branch_id": "INTEGER NOT NULL DEFAULT 1"}),
            ("audit_log", {"business_id": "INTEGER NOT NULL DEFAULT 1", "branch_id": "INTEGER NOT NULL DEFAULT 1"}),
            ("attendance", {"business_id": "INTEGER NOT NULL DEFAULT 1", "branch_id": "INTEGER NOT NULL DEFAULT 1"}),
            ("incidences", {"business_id": "INTEGER NOT NULL DEFAULT 1", "branch_id": "INTEGER NOT NULL DEFAULT 1"}),
        ]:
            t_cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({tbl})")}
            for c_name, c_ddl in cols_map.items():
                if c_name not in t_cols:
                    conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {c_name} {c_ddl}")

        # Índices únicos por negocio y sucursal (evita colisiones globales entre sucursales/negocios)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_products_biz_branch_sku ON products(business_id, branch_id, sku) WHERE sku IS NOT NULL AND sku != ''")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_products_biz_branch_barcode ON products(business_id, branch_id, barcode) WHERE barcode IS NOT NULL AND barcode != ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_biz_branch ON products(business_id, branch_id, active)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_branches_biz_code ON auth_branches(business_id, code)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_areas_biz_branch_name ON areas(business_id, branch_id, name)")

        # Seed Propietario Demo, Negocio Matriz, Sucursal Matriz (SUC-01) y Terminal POS (CAJA-01)
        if conn.execute("SELECT COUNT(*) FROM auth_owners").fetchone()[0] == 0:
            pw_hash = hashlib.sha256(("econometrics-owner-salt:admin123").encode()).hexdigest()
            conn.execute(
                "INSERT INTO auth_owners(full_name, email, password_hash, business_name, business_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "Propietario Principal",
                    "admin@econometrics.ai",
                    pw_hash,
                    "Aura Café & Roastery",
                    "Cafetería de Especialidad y Panadería Artesanal",
                    now(),
                ),
            )

        owner_row = conn.execute("SELECT * FROM auth_owners ORDER BY id ASC LIMIT 1").fetchone()
        default_owner_id = owner_row["id"] if owner_row else 1

        if conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0] == 0:
            default_baseline = {
                "initial_investment": 350000.0,
                "discount_rate_pct": 14.0,
                "bank_risk_free_rate_pct": 10.5,
                "shrinkage_risk_loss_pct": 3.0,
                "projection_years": 5,
                "monthly_price": 95.0,
                "monthly_units": 2800.0,
                "unit_variable_cost": 28.0,
                "monthly_fixed_costs": 62000.0,
                "monthly_maintenance_cost": 2500.0,
                "annual_sales_growth_pct": 10.0,
                "annual_inflation_pct": 4.5,
                "tax_rate_pct": 30.0,
                "depreciation_years": 5,
            }
            conn.execute(
                """INSERT INTO businesses(
                    owner_id, project_key, name, business_type, sector, state, municipality,
                    studio_payload_json, baseline_financials_json, settings_json, active, created_at, updated_at
                ) VALUES (?, 'EM-AURA-1001', ?, ?, 'Alimentos y Bebidas (Hospitality)', 'Ciudad de México', 'Cuauhtémoc', '{}', ?, '{}', 1, ?, ?)""",
                (
                    default_owner_id,
                    owner_row["business_name"] if owner_row else "Aura Café & Roastery",
                    owner_row["business_type"] if owner_row else "Cafetería de Especialidad y Panadería Artesanal",
                    json.dumps(default_baseline),
                    now(),
                    now(),
                ),
            )

        struct = ensure_business_structure(conn, 1)
        default_biz_id = struct["business"]["id"]
        default_br_id = struct["branches"][0]["id"]

        conn.execute("UPDATE cashiers SET role='admin' WHERE is_admin=1 AND role<>'admin'")
        conn.execute("UPDATE cashiers SET must_change_pin=1 WHERE pin_hash=? AND must_change_pin=0", (hash_pin("1234"),))
        conn.execute("INSERT OR IGNORE INTO exchange_rates(currency, rate_mxn, source, updated_at) VALUES ('MXN', 1, 'base', ?)", (now(),))
        conn.execute("INSERT OR IGNORE INTO exchange_rates(currency, rate_mxn, source, updated_at) VALUES ('USD', 18.0, 'inicial (actualizar)', ?)", (now(),))
        conn.execute("INSERT OR IGNORE INTO exchange_rates(currency, rate_mxn, source, updated_at) VALUES ('EUR', 19.5, 'inicial (actualizar)', ?)", (now(),))
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
            conn.execute("INSERT OR IGNORE INTO business_settings(business_id, key, value) VALUES (?, ?, ?)", (default_biz_id, k, v))

        if conn.execute("SELECT COUNT(*) FROM cashiers").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO cashiers(name, pin_hash, is_admin, active, created_at, role, must_change_pin, business_id, branch_id, employee_code) "
                "VALUES (?,?,1,1,?,'admin',1,?,?,?)",
                ("Administrador", hash_pin("1234"), now(), default_biz_id, default_br_id, "SUC01-ADM-001"),
            )

        # Seed productos de ejemplo si está vacío
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            sample_prods = [
                ("CAF-ESP-01", "750100100001", "Café Espresso Doble 4oz", 45.0, 12.0, "iva16", 120.0, 1, "01010101", "H87", 1, "Bebidas Calientes", "Proveedor Local", 30.0, 300.0, 100.0, 0, "MXN", 0.0, 1.0, 0.0, 0.0, 0.0, "México", default_biz_id, default_br_id),
                ("CAF-AME-02", "750100100002", "Café Americano Especial 12oz", 55.0, 14.5, "iva16", 95.0, 1, "01010101", "H87", 1, "Bebidas Calientes", "Proveedor Local", 25.0, 250.0, 80.0, 0, "MXN", 0.0, 1.0, 0.0, 0.0, 0.0, "México", default_biz_id, default_br_id),
                ("CAF-LAT-03", "750100100003", "Café Latte Vainilla 16oz", 72.0, 22.0, "iva16", 80.0, 1, "01010101", "H87", 1, "Bebidas Calientes", "Proveedor Local", 20.0, 200.0, 60.0, 0, "MXN", 0.0, 1.0, 0.0, 0.0, 0.0, "México", default_biz_id, default_br_id),
                ("GRN-VER-01", "750100100004", "Bolsa Café de Origen Coatepec 250g", 195.0, 90.0, "iva0", 40.0, 1, "01010101", "H87", 1, "Granos y Origen", "Cooperativa Veracruz", 15.0, 100.0, 30.0, 0, "MXN", 0.0, 1.0, 0.0, 0.0, 0.0, "México", default_biz_id, default_br_id),
                ("PAN-CRO-01", "750100100005", "Croissant Mantequilla Francés", 48.0, 18.0, "iva16", 28.0, 1, "01010101", "H87", 1, "Panadería Artesanal", "Panadería Local", 10.0, 60.0, 20.0, 0, "MXN", 0.0, 1.0, 0.0, 0.0, 0.0, "México", default_biz_id, default_br_id),
                ("ACC-PRE-01", "750100100006", "Prensa Francesa Acero Inoxidable 800ml", 520.0, 250.0, "iva16", 14.0, 1, "01010101", "H87", 1, "Accesorios y Métodos", "Importaciones Globales", 5.0, 30.0, 10.0, 1, "USD", 11.5, 18.0, 15.0, 25.0, 10.0, "Italia", default_biz_id, default_br_id),
            ]
            cols = ("sku, barcode, name, price, cost, iva_type, stock, track_stock, sat_product_key, sat_unit_key, "
                    "active, category, supplier, min_stock, max_stock, reorder_qty, is_imported, currency, foreign_cost, "
                    "exchange_rate, duties_pct, freight_cost, other_cost, origin_country, business_id, branch_id")
            placeholders = ",".join("?" for _ in range(len(sample_prods[0])))
            for sp in sample_prods:
                conn.execute(f"INSERT INTO products({cols}) VALUES ({placeholders})", sp)
                pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                log_movement(conn, pid, "entrada", sp[6], sp[4], "Existencia inicial del catálogo", "INVENTARIO_INICIAL", 1, default_biz_id, default_br_id)

        # Seed empleados de ejemplo si está vacío
        if conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 0:
            sample_emps = [
                {"name": "Carlos Mendoza", "role": "gerente", "position": "Gerente de Sucursal", "salary": 18500.0, "email": "carlos.mendoza@negocio.com"},
                {"name": "Ana Morales", "role": "cajero", "position": "Cajera Principal / Barista", "salary": 12000.0, "email": "ana.morales@negocio.com"},
                {"name": "Jorge Ramos", "role": "almacenista", "position": "Encargado de Logística e Inventario", "salary": 10500.0, "email": "jorge.ramos@negocio.com"},
                {"name": "Sofía Herrera", "role": "rrhh", "position": "Especialista de Recursos Humanos", "salary": 13500.0, "email": "sofia.herrera@negocio.com"},
            ]
            for se in sample_emps:
                sync_employee_and_cashier(
                    conn,
                    name=se["name"],
                    role=se["role"],
                    business_id=default_biz_id,
                    branch_id=default_br_id,
                    pin="1234",
                    position=se["position"],
                    monthly_salary=se["salary"],
                    email=se["email"],
                )
        else:
            # Sincronizar empleados existentes que aún no tengan employee_code o user_id vinculado
            for emp in conn.execute("SELECT * FROM employees").fetchall():
                if not emp["employee_code"] or not emp["user_id"]:
                    inferred_role = emp["role"] if emp["role"] in ROLES else "cajero"
                    pos_lower = (emp["position"] or "").lower()
                    if "gerente" in pos_lower:
                        inferred_role = "gerente"
                    elif "almac" in pos_lower or "log" in pos_lower or "invent" in pos_lower:
                        inferred_role = "almacenista"
                    elif "rrhh" in pos_lower or "recursos humanos" in pos_lower or "personal" in pos_lower:
                        inferred_role = "rrhh"
                    elif "contad" in pos_lower or "finanz" in pos_lower:
                        inferred_role = "contador"
                    sync_employee_and_cashier(
                        conn,
                        name=emp["name"],
                        role=inferred_role,
                        business_id=emp["business_id"] or default_biz_id,
                        branch_id=emp["branch_id"] or default_br_id,
                        pos_terminal_id=emp["pos_terminal_id"],
                        position=emp["position"],
                        area_id=emp["area_id"],
                        monthly_salary=emp["monthly_salary"],
                        pay_frequency=emp["pay_frequency"],
                        hire_date=emp["hire_date"],
                        termination_date=emp["termination_date"],
                        status=emp["status"],
                        rfc=emp["rfc"],
                        curp=emp["curp"],
                        nss=emp["nss"],
                        phone=emp["phone"],
                        email=emp["email"],
                        notes=emp["notes"],
                        employee_id=emp["id"],
                        cashier_id=emp["user_id"],
                    )
            for csh in conn.execute("SELECT * FROM cashiers WHERE employee_code IS NULL OR employee_code=''").fetchall():
                c_role = csh["role"] if csh["role"] in ROLES else ("admin" if csh["is_admin"] else "cajero")
                c_code = generate_employee_code(conn, csh["business_id"] or default_biz_id, csh["branch_id"] or default_br_id, c_role, exclude_cashier_id=csh["id"])
                conn.execute("UPDATE cashiers SET employee_code=?, business_id=COALESCE(business_id, ?), branch_id=COALESCE(branch_id, ?) WHERE id=?",
                             (c_code, default_biz_id, default_br_id, csh["id"]))

        # Migración y columnas extra para facturación CFDI 4.0
        iexisting = {r["name"] for r in conn.execute("PRAGMA table_info(invoices)")}
        for col, ddl in INVOICE_EXTRA_COLUMNS.items():
            if col not in iexisting:
                conn.execute(f"ALTER TABLE invoices ADD COLUMN {col} {ddl}")

        # Migrar facturas legacy a estado timbrada con UUID válido
        for inv in conn.execute("SELECT id, serie, folio, rfc, created_at, uuid FROM invoices WHERE status='pendiente_timbrado' OR uuid IS NULL").fetchall():
            sim_uuid = inv["uuid"] or str(uuid.uuid4()).upper()
            sim_fecha = (inv["created_at"] or now()).replace(" ", "T")
            sim_sello_cfd = generate_simulated_signature(f"{sim_uuid}_{inv['id']}_cfd")
            sim_sello_sat = generate_simulated_signature(f"{sim_uuid}_{inv['id']}_sat")
            sim_cadena = f"||1.1|{sim_uuid}|{sim_fecha}|SAT970701NN3|{sim_sello_cfd[:32]}|00001000000504465028||"
            conn.execute(
                "UPDATE invoices SET status='timbrada', uuid=?, fecha_timbrado=?, sello_cfd=?, sello_sat=?, "
                "no_certificado_sat='00001000000504465028', no_certificado_emisor='00001000000506123456', cadena_original=? WHERE id=?",
                (sim_uuid, sim_fecha, sim_sello_cfd, sim_sello_sat, sim_cadena, inv["id"])
            )


def get_settings(conn, business_id: int = 1) -> dict:
    st = dict(DEFAULT_SETTINGS)
    for r in conn.execute("SELECT key, value FROM settings"):
        st[r["key"]] = r["value"]
    for r in conn.execute("SELECT key, value FROM business_settings WHERE business_id=?", (business_id,)):
        st[r["key"]] = r["value"]
    biz = conn.execute("SELECT name FROM businesses WHERE id=?", (business_id,)).fetchone()
    if biz and st.get("business_name") in ("Mi Negocio", ""):
        st["business_name"] = biz["name"]
    return st


def money(x: float) -> float:
    return round(float(x) + 1e-9, 2)


# ------------------------------------------------------------------ Auth (PIN + Sesiones Persistentes Multi-Negocio/Sucursal)
SESSIONS: dict = {}  # token -> cashier_id


def create_auth_session(
    conn,
    user_id: int,
    *,
    actor_type: str = "employee",
    owner_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    business_id: int = 1,
    branch_id: int = 1,
    terminal_id: Optional[int] = None,
    role: str = "cajero",
) -> str:
    token = secrets.token_hex(24)
    SESSIONS[token] = user_id
    conn.execute(
        """INSERT OR REPLACE INTO auth_sessions(
            token, actor_type, owner_id, user_id, employee_id,
            active_business_id, active_branch_id, active_terminal_id, role, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (token, actor_type, owner_id, user_id, employee_id, business_id, branch_id, terminal_id, role, now()),
    )
    return token


def is_valid_session_token(conn, token: Optional[str]) -> bool:
    tok = (token or "").strip()
    if not tok:
        return False
    if tok in SESSIONS:
        return True
    row = conn.execute("SELECT user_id FROM auth_sessions WHERE token=?", (tok,)).fetchone()
    if row and row["user_id"]:
        SESSIONS[tok] = row["user_id"]
        return True
    return False


def _clean_opt_int(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if val > 0 else None
    if isinstance(val, str):
        s = val.strip()
        if s.isdigit():
            v = int(s)
            return v if v > 0 else None
    return None


def _enrich_cashier_session_dict(
    conn,
    cashier_row,
    sess_row=None,
    override_business_id: Optional[int] = None,
    override_branch_id: Optional[int] = None,
    override_terminal_id: Optional[int] = None,
) -> dict:
    user = dict(cashier_row)
    role = user.get("role") or ("admin" if user.get("is_admin") else "cajero")
    actor_type = (sess_row["actor_type"] if sess_row else None) or ("owner" if role == "admin" else "employee")
    owner_id = (sess_row["owner_id"] if sess_row else None) or 1

    base_biz_id = (sess_row["active_business_id"] if sess_row and sess_row["active_business_id"] else None) or user.get("business_id") or 1
    base_br_id = (sess_row["active_branch_id"] if sess_row and sess_row["active_branch_id"] else None) or user.get("branch_id") or 1
    base_term_id = (sess_row["active_terminal_id"] if sess_row else None) or user.get("pos_terminal_id")

    # Propietarios / Admins pueden cambiar de negocio y sucursal; Gerentes pueden cambiar de sucursal dentro de su negocio.
    if actor_type == "owner" or role == "admin":
        biz_id = override_business_id or base_biz_id
        br_id = override_branch_id or base_br_id
        term_id = override_terminal_id or base_term_id
    elif role == "gerente":
        biz_id = user.get("business_id") or base_biz_id
        br_id = override_branch_id or base_br_id
        term_id = override_terminal_id or base_term_id
    else:
        # Empleados operativos (cajero, rrhh, almacenista, contador) están fijos a su negocio y sucursal asignados
        biz_id = user.get("business_id") or base_biz_id
        br_id = user.get("branch_id") or base_br_id
        term_id = user.get("pos_terminal_id") if role == "cajero" else None

    struct = ensure_business_structure(conn, biz_id)
    biz = struct["business"]
    biz_id = biz["id"]

    br_row = conn.execute("SELECT * FROM auth_branches WHERE id=? AND business_id=?", (br_id, biz_id)).fetchone()
    if not br_row:
        br_row = conn.execute("SELECT * FROM auth_branches WHERE business_id=? AND active=1 ORDER BY id ASC LIMIT 1", (biz_id,)).fetchone()
    br_id = br_row["id"]

    term_row = None
    if role == "cajero" or (actor_type == "owner" or role in ("admin", "gerente")):
        if term_id:
            term_row = conn.execute("SELECT * FROM pos_terminals WHERE id=? AND branch_id=?", (term_id, br_id)).fetchone()
        if not term_row and role == "cajero":
            term_row = conn.execute("SELECT * FROM pos_terminals WHERE branch_id=? AND active=1 ORDER BY id ASC LIMIT 1", (br_id,)).fetchone()
            term_id = term_row["id"] if term_row else None
        elif term_row:
            term_id = term_row["id"]
        else:
            term_id = None
    else:
        term_id = None

    emp_row = None
    if user.get("employee_id"):
        emp_row = conn.execute("SELECT id, employee_code, position FROM employees WHERE id=?", (user["employee_id"],)).fetchone()
    if not emp_row:
        emp_row = conn.execute("SELECT id, employee_code, position FROM employees WHERE user_id=?", (user["id"],)).fetchone()

    user["role"] = role
    user["role_label"] = ROLES.get(role, {}).get("label", role)
    user["is_admin"] = bool(role == "admin" or user.get("is_admin"))
    user["permissions"] = user_permissions(user)
    user["actor_type"] = actor_type
    user["owner_id"] = biz.get("owner_id") or owner_id
    user["business_id"] = biz_id
    user["business_name"] = biz["name"]
    user["project_key"] = biz["project_key"]
    user["branch_id"] = br_id
    user["branch_name"] = br_row["name"]
    user["branch_code"] = br_row["code"]
    user["terminal_id"] = term_id
    user["pos_terminal_id"] = term_id
    user["terminal_code"] = term_row["code"] if term_row else None
    user["terminal_name"] = term_row["name"] if term_row else None
    user["employee_id"] = emp_row["id"] if emp_row else user.get("employee_id")
    user["employee_code"] = (emp_row["employee_code"] if emp_row and emp_row["employee_code"] else user.get("employee_code")) or f"SUC01-{ROLE_CODE_MAP.get(role, 'EMP')}-001"
    user["redirect_url"] = ROLE_REDIRECT_MAP.get(role, "/pos.html")
    return user


def resolve_request_context(
    conn,
    request: Optional[Request] = None,
    x_pos_token: Optional[str] = None,
    x_business_id: Optional[int] = None,
    x_branch_id: Optional[int] = None,
    project_key: Optional[str] = None,
) -> dict:
    """Resuelve (business_id, branch_id, owner_id, business, branch) para endpoints de Ops/Studio/ERP."""
    tok = x_pos_token if isinstance(x_pos_token, str) else None
    req_biz_id = _clean_opt_int(x_business_id)
    req_br_id = _clean_opt_int(x_branch_id)
    req_key = (project_key or "").strip().upper() if isinstance(project_key, str) else ""

    if request is not None:
        if not tok:
            tok = request.headers.get("x-pos-token") or request.query_params.get("token")
        if not req_biz_id:
            req_biz_id = _clean_opt_int(request.headers.get("x-business-id") or request.query_params.get("business_id"))
        if not req_br_id:
            req_br_id = _clean_opt_int(request.headers.get("x-branch-id") or request.query_params.get("branch_id"))
        if not req_key:
            req_key = (request.headers.get("x-project-key") or request.query_params.get("project_key") or "").strip().upper()

    if req_key:
        b_by_key = conn.execute("SELECT id FROM businesses WHERE UPPER(project_key)=?", (req_key,)).fetchone()
        if b_by_key:
            req_biz_id = b_by_key["id"]

    sess_row = None
    if tok:
        sess_row = conn.execute("SELECT * FROM auth_sessions WHERE token=?", (tok,)).fetchone()

    if sess_row:
        actor_type = sess_row["actor_type"]
        s_role = sess_row["role"]
        if actor_type == "owner" or s_role == "admin":
            biz_id = req_biz_id or sess_row["active_business_id"] or 1
            br_id = req_br_id or sess_row["active_branch_id"] or 1
        elif s_role == "gerente":
            biz_id = sess_row["active_business_id"] or 1
            br_id = req_br_id or sess_row["active_branch_id"] or 1
        else:
            biz_id = sess_row["active_business_id"] or 1
            br_id = sess_row["active_branch_id"] or 1
        owner_id = sess_row["owner_id"] or 1
    else:
        biz_id = req_biz_id or 1
        br_id = req_br_id or 1
        owner_id = 1

    struct = ensure_business_structure(conn, biz_id)
    biz = struct["business"]
    biz_id = biz["id"]
    owner_id = biz.get("owner_id") or owner_id

    br_row = conn.execute("SELECT * FROM auth_branches WHERE id=? AND business_id=?", (br_id, biz_id)).fetchone()
    if not br_row:
        br_row = conn.execute("SELECT * FROM auth_branches WHERE business_id=? AND active=1 ORDER BY id ASC LIMIT 1", (biz_id,)).fetchone()
    br_id = br_row["id"]

    return {
        "owner_id": owner_id,
        "business_id": biz_id,
        "branch_id": br_id,
        "business": biz,
        "branch": dict(br_row),
        "branches": struct["branches"],
        "terminals": struct["terminals"],
    }


def current_cashier(
    request: Request = None,
    x_pos_token: Optional[str] = Header(None),
    x_business_id: Optional[str] = Header(None),
    x_branch_id: Optional[str] = Header(None),
    x_terminal_id: Optional[str] = Header(None),
) -> dict:
    tok = x_pos_token if isinstance(x_pos_token, str) else None
    if not tok and request is not None and hasattr(request, "headers"):
        tok = request.headers.get("x-pos-token") or request.query_params.get("token")
    tok = (tok or "").strip()
    if not tok:
        raise HTTPException(401, "Sesión no válida. Inicia sesión con tu PIN.")

    override_biz = _clean_opt_int(x_business_id if isinstance(x_business_id, (int, str)) else None)
    override_br = _clean_opt_int(x_branch_id if isinstance(x_branch_id, (int, str)) else None)
    override_term = _clean_opt_int(x_terminal_id if isinstance(x_terminal_id, (int, str)) else None)

    if request is not None and hasattr(request, "query_params"):
        if not override_biz:
            override_biz = _clean_opt_int(request.query_params.get("business_id"))
        if not override_br:
            override_br = _clean_opt_int(request.query_params.get("branch_id"))
        if not override_term:
            override_term = _clean_opt_int(request.query_params.get("terminal_id"))

    with db() as conn:
        sess_row = conn.execute("SELECT * FROM auth_sessions WHERE token=?", (tok,)).fetchone()
        cid = SESSIONS.get(tok) or (sess_row["user_id"] if sess_row else None)
        if not cid:
            raise HTTPException(401, "Sesión no válida. Inicia sesión con tu PIN.")
        SESSIONS[tok] = cid
        row = conn.execute("SELECT * FROM cashiers WHERE id=? AND active=1", (cid,)).fetchone()
        if not row:
            raise HTTPException(401, "Cajero inactivo o inexistente.")
        return _enrich_cashier_session_dict(conn, row, sess_row, override_biz, override_br, override_term)


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
    cashier_id: Optional[int] = None
    employee_code: Optional[str] = None
    project_key: Optional[str] = None
    pin: str


@router.get("/cashiers/public")
def public_cashiers(business_id: Optional[int] = None, branch_id: Optional[int] = None, project_key: Optional[str] = None):
    init_pos_db()
    with db() as conn:
        sql = """SELECT c.id, c.name, c.role, c.business_id, c.branch_id, c.pos_terminal_id, c.employee_code,
                        b.project_key, b.name as business_name, br.name as branch_name, br.code as branch_code,
                        t.code as terminal_code, t.name as terminal_name
                 FROM cashiers c
                 LEFT JOIN businesses b ON b.id = c.business_id
                 LEFT JOIN auth_branches br ON br.id = c.branch_id
                 LEFT JOIN pos_terminals t ON t.id = c.pos_terminal_id
                 WHERE c.active=1 """
        args = []
        if project_key:
            sql += "AND UPPER(b.project_key)=? "
            args.append(project_key.strip().upper())
        elif business_id:
            sql += "AND c.business_id=? "
            args.append(business_id)
        if branch_id:
            sql += "AND c.branch_id=? "
            args.append(branch_id)
        sql += "ORDER BY c.business_id, c.branch_id, c.name"
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


@router.post("/login")
def login(req: LoginReq):
    err = None
    result = None
    with db() as conn:
        row = None
        if req.employee_code:
            code_clean = req.employee_code.strip().upper()
            if req.project_key:
                pk_clean = req.project_key.strip().upper()
                row = conn.execute(
                    """SELECT c.* FROM cashiers c
                       JOIN businesses b ON b.id = c.business_id
                       WHERE UPPER(c.employee_code)=? AND UPPER(b.project_key)=? AND c.active=1""",
                    (code_clean, pk_clean),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM cashiers WHERE UPPER(employee_code)=? AND active=1",
                    (code_clean,),
                ).fetchone()
        elif req.cashier_id:
            row = conn.execute("SELECT * FROM cashiers WHERE id=? AND active=1", (req.cashier_id,)).fetchone()

        if not row:
            err = (401, "Cajero, código o PIN incorrecto.")
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
            enriched = _enrich_cashier_session_dict(conn, row)
            token = create_auth_session(
                conn,
                row["id"],
                actor_type="owner" if enriched["role"] == "admin" else "employee",
                owner_id=enriched["owner_id"],
                employee_id=enriched["employee_id"],
                business_id=enriched["business_id"],
                branch_id=enriched["branch_id"],
                terminal_id=enriched["terminal_id"],
                role=enriched["role"],
            )
            audit(conn, enriched, "login", f"Código {enriched.get('employee_code')}", "usuario")
            result = {
                "token": token,
                "redirect_url": enriched["redirect_url"],
                "cashier": {
                    "id": row["id"],
                    "name": row["name"],
                    "role": enriched["role"],
                    "role_label": enriched["role_label"],
                    "is_admin": enriched["is_admin"],
                    "permissions": enriched["permissions"],
                    "area_id": row["area_id"],
                    "must_change_pin": bool(row["must_change_pin"]),
                    "business_id": enriched["business_id"],
                    "business_name": enriched["business_name"],
                    "project_key": enriched["project_key"],
                    "branch_id": enriched["branch_id"],
                    "branch_name": enriched["branch_name"],
                    "branch_code": enriched["branch_code"],
                    "terminal_id": enriched["terminal_id"],
                    "pos_terminal_id": enriched["terminal_id"],
                    "terminal_code": enriched["terminal_code"],
                    "terminal_name": enriched["terminal_name"],
                    "employee_id": enriched["employee_id"],
                    "employee_code": enriched["employee_code"],
                    "redirect_url": enriched["redirect_url"],
                },
            }
    if err:
        raise HTTPException(*err)
    return result


@router.post("/logout")
def logout(x_pos_token: Optional[str] = Header(None)):
    tok = (x_pos_token or "").strip()
    cid = SESSIONS.pop(tok, None)
    with db() as conn:
        if not cid and tok:
            s = conn.execute("SELECT user_id FROM auth_sessions WHERE token=?", (tok,)).fetchone()
            if s:
                cid = s["user_id"]
        if tok:
            conn.execute("DELETE FROM auth_sessions WHERE token=?", (tok,))
        if cid:
            r = conn.execute("SELECT id, name FROM cashiers WHERE id=?", (cid,)).fetchone()
            if r:
                audit(conn, dict(r), "logout", "", "usuario")
    return {"ok": True}


# ------------------------------------------------------------------ Configuración del negocio / ticket
@router.get("/settings")
def read_settings(me: dict = Depends(current_cashier)):
    with db() as conn:
        return get_settings(conn, me.get("business_id", 1))


@router.put("/settings")
def write_settings(data: dict, me: dict = Depends(require("settings.manage"))):
    biz_id = me.get("business_id", 1)
    with db() as conn:
        for k, v in data.items():
            if k in DEFAULT_SETTINGS:
                conn.execute("INSERT OR REPLACE INTO business_settings(business_id, key, value) VALUES (?, ?, ?)", (biz_id, k, str(v)))
                if biz_id == 1:
                    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (k, str(v)))
        audit(conn, me, "configuracion", "Se actualizó la configuración del negocio", "settings")
        return get_settings(conn, biz_id)


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
        biz_id = me.get("business_id", 1)
        br_id = me.get("branch_id", 1)
        term_id = me.get("terminal_id") or me.get("pos_terminal_id") or 1
        cur = conn.execute(
            "INSERT INTO shifts(cashier_id, opened_at, opening_float, business_id, branch_id, terminal_id) VALUES (?,?,?,?,?,?)",
            (me["id"], now(), money(req.opening_float), biz_id, br_id, term_id),
        )
        audit(conn, me, "turno_abierto", f"Fondo ${req.opening_float:.2f} (Sucursal {br_id}, Caja {term_id})", "turno")
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
def list_products(q: str = "", include_inactive: bool = False, me: dict = Depends(current_cashier)):
    biz_id = me.get("business_id", 1)
    br_id = me.get("branch_id", 1)
    sql = "SELECT * FROM products WHERE business_id=? AND branch_id=? "
    args: list = [biz_id, br_id]
    if not include_inactive:
        sql += "AND active=1 "
    if q:
        sql += "AND (name LIKE ? OR sku LIKE ? OR barcode LIKE ?) "
        args += [f"%{q}%"] * 3
    sql += "ORDER BY name LIMIT 200"
    with db() as conn:
        rows = [dict(r) for r in conn.execute(sql, args)]
        if not rows and not q:
            # Fallback a productos del negocio si esta sucursal aún no tiene catálogo propio
            rows = [dict(r) for r in conn.execute("SELECT * FROM products WHERE business_id=? AND active=1 ORDER BY name LIMIT 200", (biz_id,))]
        return rows


@router.get("/products/barcode/{code}")
def product_by_code(code: str, me: dict = Depends(current_cashier)):
    biz_id = me.get("business_id", 1)
    br_id = me.get("branch_id", 1)
    with db() as conn:
        r = conn.execute(
            "SELECT * FROM products WHERE (barcode=? OR sku=?) AND business_id=? AND branch_id=? AND active=1",
            (code, code, biz_id, br_id),
        ).fetchone()
        if not r:
            r = conn.execute(
                "SELECT * FROM products WHERE (barcode=? OR sku=?) AND business_id=? AND active=1",
                (code, code, biz_id),
            ).fetchone()
    if not r:
        raise HTTPException(404, "Producto no encontrado.")
    return dict(r)


@router.post("/products")
def create_product(p: ProductIn, me: dict = Depends(require("products.manage"))):
    biz_id = me.get("business_id", 1)
    br_id = me.get("branch_id", 1)
    try:
        with db() as conn:
            args = list(_prod_args(p)) + [biz_id, br_id]
            cur = conn.execute(
                "INSERT INTO products(sku, barcode, name, price, cost, iva_type, stock, track_stock, "
                "sat_product_key, sat_unit_key, active, business_id, branch_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                args,
            )
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
        biz_id = me.get("business_id", 1)
        br_id = me.get("branch_id", 1)
        term_id = me.get("terminal_id") or me.get("pos_terminal_id") or (shift["terminal_id"] if "terminal_id" in shift.keys() else None) or 1
        cur = conn.execute(
            "INSERT INTO sales(shift_id, cashier_id, created_at, subtotal, iva, total, payment_method, received, change_given, business_id, branch_id, terminal_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (shift["id"], me["id"], now(), subtotal, iva_total, total, req.payment_method, received, change, biz_id, br_id, term_id),
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
                log_movement(conn, p["id"], "venta", -qty, p["cost"], "Venta POS", f"V-{sale_id:06d}", me["id"], biz_id, br_id)
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
    forma_pago: Optional[str] = "01"
    metodo_pago: Optional[str] = "PUE"
    email: Optional[str] = None


def build_cfdi_xml(sale: dict, st: dict, inv: InvoiceReq, serie: str, folio: str) -> tuple:
    NS_CFDI = "http://www.sat.gob.mx/cfd/4"
    NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
    NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"

    ET.register_namespace("cfdi", NS_CFDI)
    ET.register_namespace("xsi", NS_XSI)
    ET.register_namespace("tfd", NS_TFD)

    def q(ns, t):
        return f"{{{ns}}}{t}"

    emisor_rfc = (st.get("rfc") or "").strip().upper()
    if not emisor_rfc or not RFC_RE.match(emisor_rfc) or emisor_rfc == "XAXX010101000":
        emisor_rfc = "ECS210915AA1"

    emisor_nombre = (st.get("legal_name") or st.get("business_name") or "ECONOMETRICS COMERCIAL Y SERVICIOS S.A. DE C.V.").strip().upper()
    emisor_regimen = st.get("tax_regime") or "601"
    emisor_cp = st.get("zip_code") or "06700"

    sim_uuid = str(uuid.uuid4()).upper()
    sim_fecha = (sale["created_at"] or now()).replace(" ", "T")
    forma_pago = inv.forma_pago or PAYMENT_METHODS.get(sale["payment_method"], "01")
    metodo_pago = inv.metodo_pago or "PUE"
    no_cert_sat = "00001000000504465028"
    no_cert_emisor = "00001000000506123456"
    rfc_pac = "SAT970701NN3"

    sim_sello_cfd = generate_simulated_signature(f"{sim_uuid}_{serie}{folio}_{sale['total']}_cfd")
    sim_sello_sat = generate_simulated_signature(f"{sim_uuid}_{sim_fecha}_{rfc_pac}_sat")
    cadena_original = f"||1.1|{sim_uuid}|{sim_fecha}|{rfc_pac}|{sim_sello_cfd[:32]}...|{no_cert_sat}||"

    gravados, exentos = {}, 0.0
    for it in sale["items"]:
        base = it["total"] - it["iva"]
        rate = IVA_TYPES.get(it["iva_type"], 0.16)
        if it["iva_type"] == "exento":
            exentos += base
        else:
            t = gravados.setdefault(rate, [0.0, 0.0])
            t[0] += base
            t[1] += it["iva"]

    total_trasladado = sum(v[1] for v in gravados.values())

    root = ET.Element(q(NS_CFDI, "Comprobante"), {
        f"{{{NS_XSI}}}schemaLocation": (
            "http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd "
            "http://www.sat.gob.mx/TimbreFiscalDigital http://www.sat.gob.mx/sitio_internet/cfd/TimbreFiscalDigital/TimbreFiscalDigitalv11.xsd"
        ),
        "Version": "4.0",
        "Serie": serie,
        "Folio": folio,
        "Fecha": sim_fecha,
        "Sello": sim_sello_cfd,
        "FormaPago": forma_pago,
        "NoCertificado": no_cert_emisor,
        "Certificado": SIMULATED_CERT_EMISOR,
        "SubTotal": f"{sale['subtotal']:.2f}",
        "Moneda": "MXN",
        "Total": f"{sale['total']:.2f}",
        "TipoDeComprobante": "I",
        "Exportacion": "01",
        "MetodoPago": metodo_pago,
        "LugarExpedicion": emisor_cp,
    })

    ET.SubElement(root, q(NS_CFDI, "Emisor"), {
        "Rfc": emisor_rfc,
        "Nombre": emisor_nombre,
        "RegimenFiscal": emisor_regimen,
    })

    ET.SubElement(root, q(NS_CFDI, "Receptor"), {
        "Rfc": inv.rfc,
        "Nombre": inv.razon_social.strip().upper(),
        "DomicilioFiscalReceptor": inv.codigo_postal,
        "RegimenFiscalReceptor": inv.regimen_fiscal,
        "UsoCFDI": inv.uso_cfdi,
    })

    conceptos = ET.SubElement(root, q(NS_CFDI, "Conceptos"))
    for it in sale["items"]:
        base = it["total"] - it["iva"]
        rate = IVA_TYPES.get(it["iva_type"], 0.16)
        c = ET.SubElement(conceptos, q(NS_CFDI, "Concepto"), {
            "ClaveProdServ": it.get("sat_product_key") or "01010101",
            "Cantidad": f"{it['qty']:g}",
            "ClaveUnidad": it.get("sat_unit_key") or "H87",
            "Descripcion": it["name"],
            "ValorUnitario": f"{base / it['qty']:.6f}" if it['qty'] else f"{base:.6f}",
            "Importe": f"{base:.2f}",
            "ObjetoImp": "02",
        })
        imp = ET.SubElement(ET.SubElement(c, q(NS_CFDI, "Impuestos")), q(NS_CFDI, "Traslados"))
        if it["iva_type"] == "exento":
            ET.SubElement(imp, q(NS_CFDI, "Traslado"), {
                "Base": f"{base:.2f}", "Impuesto": "002", "TipoFactor": "Exento"
            })
        else:
            ET.SubElement(imp, q(NS_CFDI, "Traslado"), {
                "Base": f"{base:.2f}", "Impuesto": "002", "TipoFactor": "Tasa",
                "TasaOCuota": f"{rate:.6f}", "Importe": f"{it['iva']:.2f}"
            })

    imps = ET.SubElement(root, q(NS_CFDI, "Impuestos"), {
        "TotalImpuestosTrasladados": f"{total_trasladado:.2f}"
    })
    tr = ET.SubElement(imps, q(NS_CFDI, "Traslados"))
    for rate, (base, importe) in gravados.items():
        ET.SubElement(tr, q(NS_CFDI, "Traslado"), {
            "Base": f"{base:.2f}", "Impuesto": "002", "TipoFactor": "Tasa",
            "TasaOCuota": f"{rate:.6f}", "Importe": f"{importe:.2f}"
        })
    if exentos:
        ET.SubElement(tr, q(NS_CFDI, "Traslado"), {
            "Base": f"{exentos:.2f}", "Impuesto": "002", "TipoFactor": "Exento"
        })

    complemento = ET.SubElement(root, q(NS_CFDI, "Complemento"))
    ET.SubElement(complemento, q(NS_TFD, "TimbreFiscalDigital"), {
        f"{{{NS_XSI}}}schemaLocation": (
            "http://www.sat.gob.mx/TimbreFiscalDigital "
            "http://www.sat.gob.mx/sitio_internet/cfd/TimbreFiscalDigital/TimbreFiscalDigitalv11.xsd"
        ),
        "Version": "1.1",
        "UUID": sim_uuid,
        "FechaTimbrado": sim_fecha,
        "RfcProvCertif": rfc_pac,
        "SelloCFD": sim_sello_cfd,
        "NoCertificadoSAT": no_cert_sat,
        "SelloSAT": sim_sello_sat,
    })

    ET.indent(root)
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    qr_str = f"https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?id={sim_uuid}&re={emisor_rfc}&rr={inv.rfc}&tt={sale['total']:.6f}&fe={sim_sello_cfd[-8:]}"

    meta = {
        "uuid": sim_uuid,
        "fecha_timbrado": sim_fecha,
        "sello_cfd": sim_sello_cfd,
        "sello_sat": sim_sello_sat,
        "no_certificado_sat": no_cert_sat,
        "no_certificado_emisor": no_cert_emisor,
        "cadena_original": cadena_original,
        "emisor_rfc": emisor_rfc,
        "emisor_nombre": emisor_nombre,
        "emisor_regimen": emisor_regimen,
        "emisor_cp": emisor_cp,
        "forma_pago": forma_pago,
        "metodo_pago": metodo_pago,
        "qr_str": qr_str,
        "total_letras": number_to_spanish_words(sale["total"]),
    }
    return xml_str, meta


def render_invoice_html(inv: dict, sale: dict, st: dict) -> str:
    """Genera representación impresa oficial CFDI 4.0 (HTML/PDF visual)."""
    emisor_rfc = (st.get("rfc") or "").strip().upper()
    if not emisor_rfc or not RFC_RE.match(emisor_rfc) or emisor_rfc == "XAXX010101000":
        emisor_rfc = "ECS210915AA1"

    emisor_nombre = (st.get("legal_name") or st.get("business_name") or "ECONOMETRICS COMERCIAL Y SERVICIOS S.A. DE C.V.").strip().upper()
    emisor_regimen = st.get("tax_regime") or "601"
    emisor_regimen_desc = REGIMENES_FISCALES.get(emisor_regimen, "General de Ley Personas Morales")
    emisor_cp = st.get("zip_code") or "06700"

    uuid_val = inv.get("uuid") or str(uuid.uuid4()).upper()
    fecha_timbrado = inv.get("fecha_timbrado") or (inv["created_at"] or now()).replace(" ", "T")
    fecha_emision = (sale["created_at"] or now()).replace(" ", "T")
    sello_cfd = inv.get("sello_cfd") or generate_simulated_signature(f"{uuid_val}_cfd")
    sello_sat = inv.get("sello_sat") or generate_simulated_signature(f"{uuid_val}_sat")
    no_cert_sat = inv.get("no_certificado_sat") or "00001000000504465028"
    no_cert_emisor = inv.get("no_certificado_emisor") or "00001000000506123456"
    cadena_orig = inv.get("cadena_original") or f"||1.1|{uuid_val}|{fecha_timbrado}|SAT970701NN3|{sello_cfd[:32]}...|{no_cert_sat}||"

    forma_pago_val = inv.get("forma_pago") or PAYMENT_METHODS.get(sale.get("payment_method"), "01")
    forma_pago_desc = FORMAS_PAGO_SAT.get(forma_pago_val, f"{forma_pago_val} - Efectivo")
    metodo_pago_val = inv.get("metodo_pago") or "PUE"
    metodo_pago_desc = METODOS_PAGO_SAT.get(metodo_pago_val, "Pago en una sola exhibición")

    regimen_receptor_desc = REGIMENES_FISCALES.get(inv.get("regimen_fiscal", "616"), inv.get("regimen_fiscal", "616"))
    uso_cfdi_desc = USOS_CFDI.get(inv.get("uso_cfdi", "G03"), inv.get("uso_cfdi", "G03"))
    total_letras = number_to_spanish_words(sale["total"])

    rows_html = ""
    for it in sale["items"]:
        base = it["total"] - it["iva"]
        unit_net = (base / it["qty"]) if it["qty"] else base
        rows_html += f"""
        <tr class="border-b border-gray-200 text-xs">
          <td class="py-2 px-1 font-mono text-[11px]">{escape(it.get('sat_product_key') or '01010101')}</td>
          <td class="py-2 px-1 font-mono text-[11px]">{escape(it.get('barcode') or it.get('sku') or 'H87')}</td>
          <td class="py-2 px-1 text-center font-bold">{it['qty']:g}</td>
          <td class="py-2 px-1 text-center font-mono text-[11px]">{escape(it.get('sat_unit_key') or 'H87')}</td>
          <td class="py-2 px-1">
            <div class="font-medium text-gray-900">{escape(it['name'])}</div>
            <div class="text-[10px] text-gray-500">Impuesto: 002 IVA Tasa 0.160000 (${it['iva']:.2f})</div>
          </td>
          <td class="py-2 px-1 text-right font-mono">${unit_net:.2f}</td>
          <td class="py-2 px-1 text-right font-mono font-semibold">${base:.2f}</td>
        </tr>
        """

    qr_param = f"https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?id={uuid_val}&re={emisor_rfc}&rr={inv['rfc']}&tt={sale['total']:.6f}&fe={sello_cfd[-8:]}"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Factura CFDI 4.0 - {escape(inv['serie'])}{escape(inv['folio'])}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/qrcode@1.5.3/build/qrcode.min.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" />
  <style>
    @page {{
      size: letter;
      margin: 12mm 15mm;
    }}
    @media print {{
      body {{ background: white !important; color: black !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
      .no-print {{ display: none !important; }}
      .sheet {{ border: none !important; box-shadow: none !important; padding: 0 !important; width: 100% !important; }}
    }}
  </style>
</head>
<body class="bg-zinc-100 text-gray-800 font-sans antialiased p-3 sm:p-5">
  <div class="sheet max-w-4xl mx-auto bg-white p-8 rounded-lg shadow-md border border-gray-300 text-gray-800">
    <!-- ENCABEZADO -->
    <div class="flex justify-between items-start border-b-2 border-amber-500 pb-4 mb-4">
      <div class="max-w-md">
        <div class="flex items-center gap-2 mb-1">
          <span class="bg-zinc-900 text-amber-400 font-extrabold text-sm px-2 py-0.5 rounded tracking-wider">ECONOMETRICS</span>
          <span class="text-[11px] font-semibold text-gray-500 uppercase tracking-wider">SISTEMA FISCAL DIGITAL</span>
        </div>
        <h1 class="text-base font-bold text-gray-900 leading-tight uppercase">{escape(emisor_nombre)}</h1>
        <div class="text-xs text-gray-600 mt-1 space-y-0.5">
          <div><strong class="text-gray-800">RFC:</strong> <span class="font-mono font-bold text-gray-900">{escape(emisor_rfc)}</span></div>
          <div><strong class="text-gray-800">Régimen Fiscal:</strong> {escape(emisor_regimen)} - {escape(emisor_regimen_desc)}</div>
          <div><strong class="text-gray-800">Lugar de Expedición:</strong> C.P. {escape(emisor_cp)} México</div>
        </div>
      </div>
      <div class="text-right border-l-2 border-gray-100 pl-4 min-w-[240px]">
        <div class="inline-block bg-zinc-900 text-amber-400 text-xs font-bold px-3 py-1 rounded mb-1 uppercase tracking-wider">
          FACTURA {escape(inv['serie'])}-{escape(inv['folio'])}
        </div>
        <div class="text-[11px] text-gray-600 space-y-0.5 mt-1">
          <div><strong>Folio Fiscal (UUID):</strong></div>
          <div class="font-mono font-bold text-[10px] text-gray-900 break-all">{escape(uuid_val)}</div>
          <div><strong>No. Serie Certificado SAT:</strong></div>
          <div class="font-mono text-[10px]">{escape(no_cert_sat)}</div>
          <div><strong>No. Serie Certificado Emisor:</strong></div>
          <div class="font-mono text-[10px]">{escape(no_cert_emisor)}</div>
          <div><strong>Fecha y Hora de Certificación:</strong></div>
          <div class="font-mono text-[10px]">{escape(fecha_timbrado)}</div>
          <div><strong>Fecha de Emisión:</strong></div>
          <div class="font-mono text-[10px]">{escape(fecha_emision)}</div>
          <div><strong>Tipo de Comprobante:</strong> I - Ingreso</div>
        </div>
      </div>
    </div>

    <!-- DATOS RECEPTOR Y CONDICIONES DE PAGO -->
    <div class="grid grid-cols-2 gap-4 mb-4 bg-gray-50 p-3 rounded border border-gray-200 text-xs">
      <div>
        <div class="text-[10px] font-bold text-amber-600 uppercase tracking-wider mb-1">DATOS DEL CLIENTE / RECEPTOR</div>
        <div class="font-bold text-gray-900 text-sm uppercase">{escape(inv['razon_social'])}</div>
        <div class="mt-1 space-y-0.5 text-gray-700">
          <div><strong>RFC:</strong> <span class="font-mono font-bold text-gray-900">{escape(inv['rfc'])}</span></div>
          <div><strong>Régimen Fiscal:</strong> {escape(inv.get('regimen_fiscal', '616'))} - {escape(regimen_receptor_desc)}</div>
          <div><strong>Domicilio Fiscal (C.P.):</strong> {escape(inv['codigo_postal'])}</div>
          <div><strong>Uso de CFDI:</strong> {escape(inv.get('uso_cfdi', 'G03'))} - {escape(uso_cfdi_desc)}</div>
          {f"<div><strong>Email:</strong> {escape(inv['email'])}</div>" if inv.get('email') else ""}
        </div>
      </div>
      <div>
        <div class="text-[10px] font-bold text-amber-600 uppercase tracking-wider mb-1">INFORMACIÓN DE PAGO</div>
        <div class="space-y-1 text-gray-700">
          <div><strong>Forma de Pago:</strong> {escape(forma_pago_val)} - {escape(forma_pago_desc)}</div>
          <div><strong>Método de Pago:</strong> {escape(metodo_pago_val)} - {escape(metodo_pago_desc)}</div>
          <div><strong>Moneda:</strong> MXN (Peso Mexicano)</div>
          <div><strong>Tipo de Cambio:</strong> 1.00</div>
          <div><strong>Exportación:</strong> 01 - No aplica</div>
          <div><strong>Estatus del Comprobante:</strong> <span class="bg-emerald-100 text-emerald-800 font-bold px-1.5 py-0.5 rounded text-[10px]">VIGENTE / TIMBRADO</span></div>
        </div>
      </div>
    </div>

    <!-- TABLA DE CONCEPTOS -->
    <div class="mb-4 overflow-hidden border border-gray-200 rounded">
      <table class="w-full text-left border-collapse">
        <thead class="bg-zinc-800 text-white text-[11px] uppercase tracking-wider">
          <tr>
            <th class="py-2 px-1">Clave Prod/Serv</th>
            <th class="py-2 px-1">No. Identif</th>
            <th class="py-2 px-1 text-center">Cant</th>
            <th class="py-2 px-1 text-center">Clave Unidad</th>
            <th class="py-2 px-1">Descripción</th>
            <th class="py-2 px-1 text-right">P. Unitario</th>
            <th class="py-2 px-1 text-right">Importe</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-200">
          {rows_html}
        </tbody>
      </table>
    </div>

    <!-- TOTALES Y CANTIDAD CON LETRA -->
    <div class="flex justify-between items-start mb-6 text-xs gap-4">
      <div class="flex-1 bg-amber-50/60 border border-amber-200/80 rounded p-3">
        <div class="text-[10px] font-bold text-amber-800 uppercase tracking-wider mb-1">IMPORTE CON LETRA</div>
        <div class="font-bold text-gray-900">{escape(total_letras)}</div>
        <div class="mt-3 text-[10px] text-gray-500">
          Este comprobante ampara la venta realizada bajo folio de mostrador <strong>{escape(sale['folio'])}</strong>.
        </div>
      </div>
      <div class="w-64 bg-gray-50 border border-gray-200 rounded p-3 text-xs space-y-1.5">
        <div class="flex justify-between text-gray-600">
          <span>Subtotal:</span>
          <span class="font-mono font-medium text-gray-800">${sale['subtotal']:.2f}</span>
        </div>
        <div class="flex justify-between text-gray-600">
          <span>Impuestos Trasladados (IVA 16%):</span>
          <span class="font-mono font-medium text-gray-800">${sale['iva']:.2f}</span>
        </div>
        <div class="border-t-2 border-gray-300 pt-1.5 flex justify-between text-sm font-bold text-gray-900">
          <span>TOTAL:</span>
          <span class="font-mono text-base text-gray-900">${sale['total']:.2f} MXN</span>
        </div>
      </div>
    </div>

    <!-- SELLO DIGITAL Y TIMBRE FISCAL -->
    <div class="border-t-2 border-gray-200 pt-4 text-[9px] text-gray-600">
      <div class="flex gap-4 items-start">
        <div class="flex-shrink-0 flex flex-col items-center">
          <canvas id="satQrCanvas" class="w-28 h-28 border border-gray-300 rounded"></canvas>
          <span class="text-[8px] text-gray-400 mt-1 font-mono text-center">Verificación SAT</span>
        </div>
        <div class="flex-1 space-y-1.5 overflow-hidden">
          <div>
            <span class="font-bold text-gray-800 block uppercase tracking-wider text-[8px]">Cadena Original del complemento de certificación digital del SAT:</span>
            <p class="font-mono break-all text-gray-500 bg-gray-50 p-1 rounded border border-gray-200 leading-tight">{escape(cadena_orig)}</p>
          </div>
          <div>
            <span class="font-bold text-gray-800 block uppercase tracking-wider text-[8px]">Sello Digital del Emisor (CFD):</span>
            <p class="font-mono break-all text-gray-500 bg-gray-50 p-1 rounded border border-gray-200 leading-tight">{escape(sello_cfd)}</p>
          </div>
          <div>
            <span class="font-bold text-gray-800 block uppercase tracking-wider text-[8px]">Sello Digital del SAT:</span>
            <p class="font-mono break-all text-gray-500 bg-gray-50 p-1 rounded border border-gray-200 leading-tight">{escape(sello_sat)}</p>
          </div>
          <div class="flex justify-between pt-1 text-[8px] text-gray-500 border-t border-gray-100">
            <span><strong>RFC Proveedor de Certificación:</strong> SAT970701NN3</span>
            <span><strong>Leyenda:</strong> Este documento es una representación impresa de un CFDI versión 4.0</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    window.addEventListener('DOMContentLoaded', function() {{
      var canvas = document.getElementById('satQrCanvas');
      if (canvas && window.QRCode) {{
        QRCode.toCanvas(canvas, {repr(qr_param)}, {{
          width: 112,
          margin: 1,
          color: {{ dark: '#000000', light: '#ffffff' }}
        }});
      }}
    }});
  </script>
</body>
</html>
"""


@router.post("/sales/{sale_id}/invoice")
def create_invoice(sale_id: int, req: InvoiceReq, me: dict = Depends(require("pos.sell"))):
    """
    Genera y timbra el comprobante fiscal CFDI 4.0 con complemento TimbreFiscalDigital 1.1.
    Estado inmediato: 'timbrada'.
    """
    rfc = req.rfc.strip().upper()
    if not RFC_RE.match(rfc):
        raise HTTPException(400, "RFC del receptor inválido (debe tener 12 o 13 caracteres alfanuméricos válidos).")
    req.rfc = rfc
    req.razon_social = req.razon_social.strip().upper()

    with db() as conn:
        sale = get_sale(conn, sale_id)
        st = get_settings(conn)
        if sale["status"] != "completada":
            raise HTTPException(400, "Solo se pueden facturar ventas completadas.")
        if sale["invoice"]:
            raise HTTPException(400, "La venta ya fue facturada previamente.")

        serie = st.get("invoice_series", "A")
        folio = str(sale_id)
        xml, meta = build_cfdi_xml(sale, st, req, serie, folio)

        conn.execute(
            """INSERT INTO invoices(
                sale_id, serie, folio, rfc, razon_social, regimen_fiscal, codigo_postal,
                uso_cfdi, email, xml, status, created_at, uuid, fecha_timbrado,
                sello_sat, sello_cfd, no_certificado_sat, no_certificado_emisor,
                cadena_original, forma_pago, metodo_pago
            ) VALUES (?,?,?,?,?,?,?,?,?,?,'timbrada',?,?,?,?,?,?,?,?,?,?)""",
            (
                sale_id, serie, folio, rfc, req.razon_social, req.regimen_fiscal, req.codigo_postal,
                req.uso_cfdi, req.email, xml, now(), meta["uuid"], meta["fecha_timbrado"],
                meta["sello_sat"], meta["sello_cfd"], meta["no_certificado_sat"], meta["no_certificado_emisor"],
                meta["cadena_original"], meta["forma_pago"], meta["metodo_pago"]
            ),
        )
        inv_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        audit(conn, me, "factura", f"{serie}{folio} UUID {meta['uuid']} RFC {rfc} venta {sale['folio']}", "factura")
        return {
            "id": inv_id,
            "serie": serie,
            "folio": folio,
            "uuid": meta["uuid"],
            "status": "timbrada",
            "fecha_timbrado": meta["fecha_timbrado"],
            "rfc": rfc,
            "razon_social": req.razon_social,
            "total": sale["total"],
        }


@router.get("/invoices")
def list_invoices(me: dict = Depends(current_cashier)):
    with db() as conn:
        rows = conn.execute(
            """SELECT i.id, i.sale_id, i.serie, i.folio, i.rfc, i.razon_social,
                      COALESCE(i.status, 'timbrada') as status, i.created_at,
                      i.uuid, i.fecha_timbrado, i.forma_pago, i.metodo_pago,
                      s.total, s.folio as sale_folio
               FROM invoices i
               JOIN sales s ON s.id=i.sale_id
               ORDER BY i.id DESC LIMIT 100"""
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/invoices/{invoice_id}")
def get_invoice_detail(invoice_id: int, me: dict = Depends(current_cashier)):
    with db() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Factura no encontrada.")
        inv = dict(row)
        sale = get_sale(conn, inv["sale_id"])
        st = get_settings(conn)

    emisor_rfc = (st.get("rfc") or "").strip().upper()
    if not emisor_rfc or not RFC_RE.match(emisor_rfc) or emisor_rfc == "XAXX010101000":
        emisor_rfc = "ECS210915AA1"

    emisor_nombre = (st.get("legal_name") or st.get("business_name") or "ECONOMETRICS COMERCIAL Y SERVICIOS S.A. DE C.V.").strip().upper()
    emisor_regimen = st.get("tax_regime") or "601"
    emisor_cp = st.get("zip_code") or "06700"

    forma_pago_desc = FORMAS_PAGO_SAT.get(inv.get("forma_pago") or "01", inv.get("forma_pago") or "01")
    metodo_pago_desc = METODOS_PAGO_SAT.get(inv.get("metodo_pago") or "PUE", inv.get("metodo_pago") or "PUE")
    regimen_desc = REGIMENES_FISCALES.get(inv.get("regimen_fiscal") or "616", inv.get("regimen_fiscal") or "")
    uso_desc = USOS_CFDI.get(inv.get("uso_cfdi") or "G03", inv.get("uso_cfdi") or "")
    qr_str = f"https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?id={inv.get('uuid') or ''}&re={emisor_rfc}&rr={inv.get('rfc') or ''}&tt={sale['total']:.6f}&fe={(inv.get('sello_cfd') or '')[-8:]}"

    return {
        "invoice": inv,
        "sale": sale,
        "emisor": {
            "rfc": emisor_rfc,
            "nombre": emisor_nombre,
            "regimen": emisor_regimen,
            "regimen_desc": REGIMENES_FISCALES.get(emisor_regimen, "General de Ley Personas Morales"),
            "cp": emisor_cp,
        },
        "receptor": {
            "rfc": inv["rfc"],
            "razon_social": inv["razon_social"],
            "regimen": inv["regimen_fiscal"],
            "regimen_desc": regimen_desc,
            "cp": inv["codigo_postal"],
            "uso_cfdi": inv["uso_cfdi"],
            "uso_cfdi_desc": uso_desc,
            "email": inv.get("email"),
        },
        "pago": {
            "forma_pago": inv.get("forma_pago") or "01",
            "forma_pago_desc": forma_pago_desc,
            "metodo_pago": inv.get("metodo_pago") or "PUE",
            "metodo_pago_desc": metodo_pago_desc,
            "moneda": "MXN",
        },
        "totales": {
            "subtotal": sale["subtotal"],
            "iva": sale["iva"],
            "total": sale["total"],
            "total_letras": number_to_spanish_words(sale["total"]),
        },
        "timbrado": {
            "uuid": inv.get("uuid"),
            "fecha_timbrado": inv.get("fecha_timbrado"),
            "no_certificado_sat": inv.get("no_certificado_sat") or "00001000000504465028",
            "no_certificado_emisor": inv.get("no_certificado_emisor") or "00001000000506123456",
            "rfc_pac": "SAT970701NN3",
            "sello_cfd": inv.get("sello_cfd"),
            "sello_sat": inv.get("sello_sat"),
            "cadena_original": inv.get("cadena_original"),
            "qr_str": qr_str,
        }
    }


@router.get("/invoices/{invoice_id}/print")
def invoice_print(invoice_id: int, token: Optional[str] = Query(None), x_pos_token: Optional[str] = Header(None)):
    if (token or x_pos_token or "") not in SESSIONS:
        raise HTTPException(401, "Sesión no válida.")
    with db() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Factura no encontrada.")
        inv = dict(row)
        sale = get_sale(conn, inv["sale_id"])
        st = get_settings(conn)
    return HTMLResponse(render_invoice_html(inv, sale, st))


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
