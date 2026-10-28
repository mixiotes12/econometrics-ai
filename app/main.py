import os
from datetime import datetime
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from .models import (
    AnalysisRequest,
    FinancialInputs,
    FinancialReport,
    FullAnalysisResponse
)
from .financial_engine import analyze_financials
from .gemini_service import generate_gemini_analysis

load_dotenv()

app = FastAPI(
    title="EconoMetrics AI - Evaluador de Rentabilidad y Viabilidad de Negocios",
    description="Motor de fórmulas financieras validadas (VAN, TIR, Payback, Punto de Equilibrio) potenciado con Gemini",
    version="1.0.0"
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    print(">>> VALIDATION ERROR ON REQUEST:", errors)
    formatted = []
    for e in errors:
        loc = " -> ".join(str(x) for x in e.get("loc", []))
        msg = e.get("msg", "Dato inválido")
        formatted.append(f"{loc}: {msg}")
    detail_str = " | ".join(formatted)
    return JSONResponse(status_code=422, content={"detail": detail_str, "errors": errors})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".html") or path.endswith(".js"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

TEMPLATES = [
    {
        "id": "cafe_especialidad",
        "name": "Cafetería de Especialidad & Brunch",
        "icon": "coffee",
        "business": {
            "name": "Aura Café & Roastery",
            "business_type": "Cafetería de Especialidad y Panadería Artesanal",
            "description": "Venta de café de origen, bebidas de autor, métodos de extracción y repostería artesanal con área de coworking ligera y terraza.",
            "target_market": "Profesionistas jóvenes de 22 a 45 años, nómadas digitales, estudiantes universitarios y amantes del buen café.",
            "location": "Avenida comercial de alto flujo en colonia de nivel socioeconómico medio-alto (C+/B/A).",
            "location_details": "Cerca de corporativos y zona residencial, paso peatonal de ~4,000 personas al día, visibilidad frontal con ventanal.",
            "competition_level": "Alta",
            "competition_details": "3 cafeterías comerciales (Starbucks, Oxxo café) a 300m y 1 cafetería local independiente.",
            "competitive_advantage": "Tueste propio en vivo, granos con trazabilidad directa con productores, atmósfera estética 'instagrammable' y café de calidad 86+ SCA."
        },
        "financials": {
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
            "depreciation_years": 5
        }
    },
    {
        "id": "ecommerce_d2c",
        "name": "E-Commerce D2C (Cosmética / Skincare)",
        "icon": "shopping-bag",
        "business": {
            "name": "Botanica Organics D2C",
            "business_type": "Comercio Electrónico Direct-to-Consumer (D2C)",
            "description": "Marca propia de productos de cuidado facial y corporal veganos, libres de crueldad animal, empaques biodegradables.",
            "target_market": "Mujeres y hombres de 18 a 38 años preocupados por el cuidado de la piel y la sustentabilidad.",
            "location": "Canal 100% digital (Shopify + Amazon + MercadoLibre) con almacén centralizado 3PL.",
            "location_details": "Cobertura nacional, envíos express a las principales urbes del país en 24-48 horas.",
            "competition_level": "Saturada",
            "competition_details": "Gran cantidad de marcas emergentes en Instagram y TikTok, marcas tradicionales de farmacia y retail.",
            "competitive_advantage": "Formulaciones con activos botánicos clínicos probados, modelo de suscripción mensual con 15% de descuento y fuerte comunidad con UGC."
        },
        "financials": {
            "initial_investment": 200000.0,
            "discount_rate_pct": 16.0,
            "bank_risk_free_rate_pct": 10.5,
            "shrinkage_risk_loss_pct": 2.5,
            "projection_years": 5,
            "monthly_price": 480.0,
            "monthly_units": 850.0,
            "unit_variable_cost": 130.0,
            "monthly_fixed_costs": 110000.0,
            "monthly_maintenance_cost": 1500.0,
            "annual_sales_growth_pct": 25.0,
            "annual_inflation_pct": 4.0,
            "tax_rate_pct": 30.0,
            "depreciation_years": 3
        }
    },
    {
        "id": "saas_b2b",
        "name": "Software SaaS B2B (Gestión para Clínicas)",
        "icon": "laptop",
        "business": {
            "name": "MedFlow Cloud",
            "business_type": "Software as a Service (SaaS) B2B",
            "description": "Plataforma en la nube de gestión integral para consultorios médicos y clínicas dentales (agenda, expediente electrónico, facturación y recordatorios por WhatsApp).",
            "target_market": "Médicos especialistas independientes y clínicas privadas de 2 a 10 consultorios.",
            "location": "Venta remota nacional e internacional (Hispanoamérica).",
            "location_details": "Operación cloud en AWS, fuerza de ventas remota mediante Inside Sales y demos online.",
            "competition_level": "Media",
            "competition_details": "Software legado de escritorio complejo y 2 competidores en la nube más costosos y con soporte deficiente.",
            "competitive_advantage": "Onboarding en menos de 10 minutos, interfaz ultra intuitiva, integración nativa con WhatsApp Business API y soporte humano 24/7."
        },
        "financials": {
            "initial_investment": 280000.0,
            "discount_rate_pct": 18.0,
            "bank_risk_free_rate_pct": 10.5,
            "shrinkage_risk_loss_pct": 1.0,
            "projection_years": 5,
            "monthly_price": 890.0,
            "monthly_units": 180.0,
            "unit_variable_cost": 65.0,
            "monthly_fixed_costs": 68000.0,
            "monthly_maintenance_cost": 2000.0,
            "annual_sales_growth_pct": 35.0,
            "annual_inflation_pct": 4.0,
            "tax_rate_pct": 30.0,
            "depreciation_years": 3
        }
    },
    {
        "id": "gimnasio_boutique",
        "name": "Gimnasio Boutique / Pilates & Funcional",
        "icon": "activity",
        "business": {
            "name": "CoreLab Boutique Studio",
            "business_type": "Estudio Fitness / Pilates Reformer & HIIT",
            "description": "Clases grupales semi-personalizadas de alta intensidad y Pilates Reformer en sesiones de 50 minutos con coaches certificados.",
            "target_market": "Hombres y mujeres de 25 a 55 años que buscan entrenamiento efectivo, dinámico y en grupos reducidos (máximo 12 personas).",
            "location": "Plaza comercial abierta en zona residencial de alta plusvalía con estacionamiento propio.",
            "location_details": "Local de 180 m² con facilidades de acceso, rodeado de supermercados gourmet y restaurantes saludables.",
            "competition_level": "Media",
            "competition_details": "Gimnasios comerciales de cadena masiva a 2 km y un estudio de yoga a 800m.",
            "competitive_advantage": "Membresías flexibles por créditos, equipamiento Reformer de última generación y ambiente exclusivo sin aglomeraciones."
        },
        "financials": {
            "initial_investment": 650000.0,
            "discount_rate_pct": 13.0,
            "bank_risk_free_rate_pct": 10.5,
            "shrinkage_risk_loss_pct": 2.0,
            "projection_years": 5,
            "monthly_price": 1650.0,
            "monthly_units": 160.0,
            "unit_variable_cost": 150.0,
            "monthly_fixed_costs": 115000.0,
            "monthly_maintenance_cost": 5500.0,
            "annual_sales_growth_pct": 8.0,
            "annual_inflation_pct": 4.0,
            "tax_rate_pct": 30.0,
            "depreciation_years": 5
        }
    }
]

from .templates_engineering import ENGINEERING_TEMPLATES
for _tmpl in TEMPLATES:
    if _tmpl["id"] in ENGINEERING_TEMPLATES:
        _tmpl["engineering"] = ENGINEERING_TEMPLATES[_tmpl["id"]]

@app.get("/api/templates")
def get_templates():
    return TEMPLATES

@app.get("/api/config")
def get_config():
    return {
        "has_server_api_key": bool(os.getenv("GEMINI_API_KEY")),
        "default_model": "gemini-3.5-flash"
    }

@app.post("/api/calc-financials", response_model=FinancialReport)
def calculate_financial_report(inputs: FinancialInputs):
    """
    Calcula instantáneamente las fórmulas financieras (VAN, TIR, Payback, Punto de Equilibrio, Sensibilidad)
    sin consumir la API de Gemini.
    """
    try:
        report = analyze_financials(inputs)
        return report
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error en el cálculo financiero: {str(e)}")

@app.post("/api/full-analysis", response_model=FullAnalysisResponse)
async def perform_full_analysis(
    req: AnalysisRequest,
    x_gemini_api_key: str = Header(None)
):
    """
    Ejecuta el análisis financiero cuantitativo y genera el dictamen estratégico con Gemini 3.7 / 2.5 Flash.
    """
    try:
        # 1. Run rigorous mathematical financial calculation
        financial_report = analyze_financials(req.financials)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al calcular las métricas financieras: {str(e)}")

    api_key_to_use = req.custom_api_key or x_gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key_to_use:
        raise HTTPException(
            status_code=400,
            detail="Falta la API Key de Gemini. Por favor proporciónala en la casilla superior de la aplicación."
        )

    # 2. Call Gemini
    try:
        model_name = req.gemini_model or "gemini-3.5-flash"
        advice, raw_text = await generate_gemini_analysis(
            business=req.business,
            financials=req.financials,
            report=financial_report,
            model_name=model_name,
            custom_api_key=api_key_to_use
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar el análisis estratégico con Gemini: {str(e)}")

    return FullAnalysisResponse(
        financial_report=financial_report,
        strategic_advice=advice,
        ai_raw_text=raw_text,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

from .models import EquipmentRequest, BudgetsResponse, ProcessRequest, FlowchartResponse
from .engineering_service import generate_equipment_budgets, generate_production_flowchart

@app.post("/api/generate-budgets", response_model=BudgetsResponse)
async def api_generate_budgets(req: EquipmentRequest, x_gemini_api_key: str = Header(None)):
    try:
        api_key_to_use = req.custom_api_key or x_gemini_api_key or os.getenv("GEMINI_API_KEY")
        req.custom_api_key = api_key_to_use
        response = await generate_equipment_budgets(req)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar presupuestos: {str(e)}")

@app.post("/api/generate-flowchart", response_model=FlowchartResponse)
async def api_generate_flowchart(req: ProcessRequest, x_gemini_api_key: str = Header(None)):
    try:
        api_key_to_use = req.custom_api_key or x_gemini_api_key or os.getenv("GEMINI_API_KEY")
        req.custom_api_key = api_key_to_use
        response = await generate_production_flowchart(req)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar diagrama de flujo: {str(e)}")

# Static files for the frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
