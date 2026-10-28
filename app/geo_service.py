"""
Módulo de Geolocalización, Sectores, Giros Comerciales y Sugerencias de Adquisición (Fase 4)
- Catálogos de entidades federativas mexicanas, regiones económicas, sectores y giros comerciales.
- Motor de sugerencias estratégicas para adquisición de productos en función de la geolocalización:
  * Evaluación de abastecimiento local vs. importación
  * Logística regional, fletes y proximidad a clusters (Frontera norte, Centro CEDA, Bajío, Puertos)
  * Calendario de compras por temporada y estacionalidad
  * Productos clave de alta rotación sugeridos según la zona
"""
import os
import json
import httpx
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Header, HTTPException
from .models import (
    BusinessProfile,
    AcquisitionSuggestionRequest,
    AcquisitionSuggestionResponse,
    KeyProductSuggestion,
    SeasonalCalendarItem
)

router = APIRouter(prefix="/api/geo", tags=["Geolocalización & Adquisiciones"])

MEXICO_STATES = [
    {"name": "Aguascalientes", "region": "Bajío", "logistics_hub": "Corredor Bajío Automotriz/Electrónica"},
    {"name": "Baja California", "region": "Frontera Norte", "logistics_hub": "Frontera Tijuana/Mexicali y Puerto Ensenada (Acceso directo a importación USA/Asia)"},
    {"name": "Baja California Sur", "region": "Noroeste", "logistics_hub": "Zona marítima/turística (Requiere consolidación marítima/aérea)"},
    {"name": "Campeche", "region": "Sureste", "logistics_hub": "Suministro peninsular y sector energético"},
    {"name": "Chiapas", "region": "Sureste", "logistics_hub": "Frontera Sur y agroindustria (café, cacao, frutos)"},
    {"name": "Chihuahua", "region": "Frontera Norte", "logistics_hub": "Puente Juárez/El Paso (Maquila e importación terrestre intensiva)"},
    {"name": "Ciudad de México", "region": "Centro", "logistics_hub": "CEDA Iztapalapa (Mayor centro de abastos de AL) y hubs centrales"},
    {"name": "Coahuila", "region": "Frontera Norte", "logistics_hub": "Corredor Piedras Negras/Acuña y Saltillo automotriz"},
    {"name": "Colima", "region": "Occidente", "logistics_hub": "Puerto de Manzanillo (Principal puerto de entrada de contenedores de Asia)"},
    {"name": "Durango", "region": "Norte", "logistics_hub": "Conexión Pacífico-Norte (Madera y minería)"},
    {"name": "Estado de México", "region": "Centro", "logistics_hub": "Parques logísticos Cuautitlán/Tultitlán/Tlalnepantla (Mayor hub e-commerce 3PL de México)"},
    {"name": "Guanajuato", "region": "Bajío", "logistics_hub": "Puerto Interior Guanajuato (GTO Dry Port, calzado y manufactura)"},
    {"name": "Guerrero", "region": "Sur", "logistics_hub": "Corredor turístico Acapulco/Costa Grande"},
    {"name": "Hidalgo", "region": "Centro", "logistics_hub": "Arco Norte y cercanía al AIFA (Distribución centro-norte)"},
    {"name": "Jalisco", "region": "Occidente", "logistics_hub": "Mercado de Abastos GDL, Silicon Valley mexicano y conexión Manzanillo"},
    {"name": "Michoacán", "region": "Occidente", "logistics_hub": "Puerto Lázaro Cárdenas y agroindustria de exportación"},
    {"name": "Morelos", "region": "Centro", "logistics_hub": "Acceso sur a CDMX y agroquímicos/servicios"},
    {"name": "Nayarit", "region": "Occidente", "logistics_hub": "Corredor Riviera Nayarit y agropecuario"},
    {"name": "Nuevo León", "region": "Frontera Norte", "logistics_hub": "Hub industrial de Monterrey y Puente Colombia hacia Texas"},
    {"name": "Oaxaca", "region": "Sur", "logistics_hub": "Corredor Interoceánico y artesanías/alimentos endémicos"},
    {"name": "Puebla", "region": "Centro-Oriente", "logistics_hub": "Cluster automotriz y textil, paso obligado al Puerto de Veracruz"},
    {"name": "Querétaro", "region": "Bajío", "logistics_hub": "Aeropuerto Intercontinental de Querétaro y cluster aeroespacial"},
    {"name": "Quintana Roo", "region": "Península / Turística", "logistics_hub": "Cancún/Riviera Maya (Mercado de alto poder adquisitivo y hotelería)"},
    {"name": "San Luis Potosí", "region": "Bajío-Norte", "logistics_hub": "Encrucijada logística nacional (Eje carretero 57)"},
    {"name": "Sinaloa", "region": "Noroeste", "logistics_hub": "Puerto de Mazatlán y mayor productor agrícola de hortalizas"},
    {"name": "Sonora", "region": "Frontera Norte", "logistics_hub": "Frontera Nogales y Puerto Guaymas"},
    {"name": "Tabasco", "region": "Sureste", "logistics_hub": "Puerta del Sureste y zona logística petrolera Dos Bocas"},
    {"name": "Tamaulipas", "region": "Frontera Norte", "logistics_hub": "Puente Nuevo Laredo (El puerto terrestre #1 de América Latina) y Puerto Altamira"},
    {"name": "Tlaxcala", "region": "Centro", "logistics_hub": "Conexión Arco Norte y manufactura textil/autopartes"},
    {"name": "Veracruz", "region": "Golfo", "logistics_hub": "Puerto de Veracruz (Principal entrada marítima del Atlántico/Europa)"},
    {"name": "Yucatán", "region": "Península", "logistics_hub": "Puerto Progreso y polo de innovación/seguridad de Mérida"},
    {"name": "Zacatecas", "region": "Norte", "logistics_hub": "Eje minero y agropecuario del centro-norte"}
]

SECTORS_CATALOG = [
    {
        "sector": "Comercio al por menor (Retail)",
        "branches": [
            "Abarrotes y Minisúper",
            "Boutique de Ropa y Calzado",
            "Farmacia y Salud",
            "Ferretería y Tlapalería",
            "Papelería y Regalos",
            "Electrónica y Telefonía",
            "Cosméticos y Cuidado Personal",
            "Óptica y Accesorios",
            "Mascotas y Veterinaria"
        ]
    },
    {
        "sector": "Alimentos y Bebidas (Hospitality)",
        "branches": [
            "Cafetería de Especialidad & Brunch",
            "Restaurante Casual / Familiar",
            "Pizzería & Comida Rápida",
            "Taquería Tradicional",
            "Panadería y Repostería Artesanal",
            "Dark Kitchen / Comida para Llevar",
            "Bar & Cervecería Artesanal",
            "Nevería y Paletería"
        ]
    },
    {
        "sector": "Servicios Profesionales y Personales",
        "branches": [
            "Gimnasio Boutique / Fitness & Pilates",
            "Barbería y Salón de Belleza / Spa",
            "Consultorio Médico o Dental",
            "Lavandería y Tintorería",
            "Taller Mecánico / Car Wash",
            "Coworking y Oficinas Flexibles",
            "Guardería y Centro Educativo"
        ]
    },
    {
        "sector": "Comercio Electrónico y Tecnología (Digital)",
        "branches": [
            "E-Commerce D2C (Marca Propia)",
            "Software SaaS B2B",
            "Marketplace / Plataforma Digital",
            "Agencia de Marketing Digital y Creativa"
        ]
    },
    {
        "sector": "Manufactura e Industria Ligera",
        "branches": [
            "Taller de Confección Textil",
            "Carpintería y Muebles de Diseño",
            "Elaboración de Alimentos Envasados / Conservas",
            "Imprenta y Empaque Comercial"
        ]
    }
]

ZONE_TYPES = [
    "Corredor comercial de alto flujo peatonal",
    "Plaza o Centro Comercial (Mall)",
    "Centro Histórico o Zona Turística",
    "Zona Residencial de nivel socioeconómico medio-alto (A/B/C+)",
    "Zona Residencial de nivel medio/popular (C/D+)",
    "Parque Industrial o Corredor Logístico",
    "Zona Corporativa / Complejos de Oficinas",
    "Zona Universitaria / Escolar",
    "100% Digital / Envíos a Domicilio"
]

@router.get("/catalogs")
def get_geo_catalogs():
    return {
        "states": MEXICO_STATES,
        "sectors": SECTORS_CATALOG,
        "zone_types": ZONE_TYPES
    }

def generate_heuristic_acquisition_plan(b: BusinessProfile) -> AcquisitionSuggestionResponse:
    state_info = next((s for s in MEXICO_STATES if s["name"].lower() == (b.state or "").lower()), None)
    region = state_info["region"] if state_info else "Centro"
    hub_desc = state_info["logistics_hub"] if state_info else "Red logística nacional"
    
    sector = b.sector or "Comercio al por menor (Retail)"
    branch = b.commercial_branch or b.business_type or "Comercio general"
    zone = b.zone_type or "Corredor comercial de alto flujo peatonal"
    state = b.state or "Ciudad de México"

    # Evaluaciones por región
    if region == "Frontera Norte":
        strategy = (f"En {state} ({region}) cuentas con una ventaja logística sobresaliente para "
                    f"importación directa de maquinaria, refacciones y mercancía de EE.UU. a través de aduanas fronterizas. "
                    f"Se recomienda negociar contratos en USD con cobertura cambiaria o compra en almacenes fiscales fronterizos.")
        local_vs_import = ("65% Importación directa o distribuidores de frontera / 35% Proveedores nacionales. "
                           "Aprovecha los tiempos de tránsito terrestres ultracortos (24 a 48 hrs desde Texas o California).")
        logistics = (f"Fletes locales accesibles por carretera interestatal; cercanía directa a {hub_desc}. "
                     f"Costos de flete terrestre menores comparados con el sur del país.")
    elif region in ("Centro", "Bajío"):
        strategy = (f"En {state} ({region}) te encuentras en el corazón de la red de distribución de México. "
                    f"Tienes acceso preferencial a {hub_desc}. Conviene priorizar compras a fabricantes directos del Bajío "
                    f"o distribuidores mayoristas de la zona metropolitana, evitando intermediarios.")
        local_vs_import = ("75% Proveedores nacionales y clusters locales / 25% Importación consolidada. "
                           "La disponibilidad inmediata y menor costo de flete hace que el producto nacional sea más rentable en rotación rápida.")
        logistics = (f"Acceso inmejorable a autopistas y centros de distribución 3PL en {state}. "
                     f"Entregas en el mismo día o 24 hrs reducen drásticamente la necesidad de inmovilizar capital en inventarios gigantes.")
    elif region in ("Occidente", "Golfo"):
        strategy = (f"En {state} ({region}) tienes conectividad marítima estratégica a través de {hub_desc}. "
                    f"Ideal para negocios que comercializan insumos o productos importados de ultramar (China, Vietnam, Europa).")
        local_vs_import = ("50% Proveedores locales agrícolas/industriales / 50% Importación marítima directa en contenedor compartido (LCL/FCL).")
        logistics = "Ventaja portuaria para desaduanamiento marítimo rápido con menores fletes de arrastre hacia tu bodega."
    else:  # Sureste, Península, Sur
        strategy = (f"En {state} ({region}), el costo de flete terrestre desde el centro del país representa del 4% al 8% del valor del producto. "
                    f"Estrategia clave: negociar compras por volumen consolidado (tarima completa) para diluir el flete unitario y "
                    f"desarrollar proveedores regionales de insumos frescos y consumibles.")
        local_vs_import = ("60% Mayoristas con presencia regional / 30% Productores locales / 10% Importación directa en puerto local si aplica.")
        logistics = f"Planea compras con 10 a 15 días de anticipación debido a tiempos de flete carretero hacia el sureste ({hub_desc})."

    # Calendario estacional
    calendar = [
        SeasonalCalendarItem(
            season_period="Enero - Febrero (Inicio de Año)",
            action="Liquidación de excedentes y negociación anual",
            recommended_focus="Pactar convenios de volumen con proveedores principales y asegurar precios antes de ajustes por inflación.",
            discount_opportunity="Descuentos del 5% al 12% por pronto pago o compra por volumen para el Q1."
        ),
        SeasonalCalendarItem(
            season_period="Mayo - Junio (Media Temporada / Hot Sale)",
            action="Abastecimiento de stock de alta demanda",
            recommended_focus="Preparar inventario para campañas de mitad de año y temporadas vacacionales según el giro.",
            discount_opportunity="Aprovechar promociones de distribuidores en meses de media rotación."
        ),
        SeasonalCalendarItem(
            season_period="Septiembre - Octubre (Preparación Temporada Alta)",
            action="Compra anticipada para Fin de Año",
            recommended_focus="Adquisición de productos estrella y consumibles para Buen Fin, Navidad y fin de año.",
            discount_opportunity="Evitar sobrecostos de última hora y desabasto comprando con 6 a 8 semanas de anticipación."
        ),
        SeasonalCalendarItem(
            season_period="Noviembre - Diciembre (Pico Comercial)",
            action="Venta máxima y control estricto de mermas",
            recommended_focus="Reabastecimiento express solo de productos clase A (alta rotación) mediante transferencias rápidas.",
            discount_opportunity="Enfocar liquidez en mantener stock 100% disponible de los artículos con más del 40% de margen."
        )
    ]

    # Productos clave sugeridos según sector y giro
    key_products = []
    if "alimento" in sector.lower() or "café" in branch.lower() or "restaurante" in branch.lower():
        key_products = [
            KeyProductSuggestion(
                name="Insumos Base & Materia Prima Fresca",
                category="Consumibles Diarios",
                target_margin_pct=65.0,
                turnover_speed="Alta (Rotación semanal)",
                local_advantage="Comprar a productores de mercados regionales para garantizar máxima frescura y aroma.",
                suggested_source="Proveedor Local / Central de Abastos"
            ),
            KeyProductSuggestion(
                name="Bebidas Especiales & Productos de Autor",
                category="Alta Rentabilidad",
                target_margin_pct=75.0,
                turnover_speed="Alta",
                local_advantage="Diferenciador del menú con insumos de origen controlado que justifican un ticket promedio elevado.",
                suggested_source="Distribuidor Especializado Regional"
            ),
            KeyProductSuggestion(
                name="Empaques Biodegradables & Desechables Eco",
                category="Operación",
                target_margin_pct=40.0,
                turnover_speed="Media",
                local_advantage="Cumplimiento con normativas ambientales locales y percepción de valor de marca.",
                suggested_source="Distribuidor Mayorista / Fabricante Nacional"
            )
        ]
    elif "retail" in sector.lower() or "comercio" in sector.lower() or "tienda" in branch.lower():
        key_products = [
            KeyProductSuggestion(
                name="Artículos Gancho / Alta Rotación (Clase A)",
                category="Tráfico y Volumen",
                target_margin_pct=35.0,
                turnover_speed="Rápida (Rotación quincenal)",
                local_advantage="Generan el 70% del flujo de efectivo y visitas recurrentes de clientes.",
                suggested_source="Mayorista Regional / Fabricante Directo"
            ),
            KeyProductSuggestion(
                name="Productos Complementarios & Impulso (Caja)",
                category="Impulso en Mostrador",
                target_margin_pct=55.0,
                turnover_speed="Alta",
                local_advantage="Aumentan el ticket promedio en caja en un 15% a 25% con nulo esfuerzo adicional.",
                suggested_source="Distribuidor Local de Accesorios"
            ),
            KeyProductSuggestion(
                name="Línea Premium o Exclusiva Importada",
                category="Margen Alto",
                target_margin_pct=60.0,
                turnover_speed="Media",
                local_advantage="Posicionamiento aspiracional y margen bruto superior para amortizar costos fijos.",
                suggested_source="Importación Directa / Representante de Marca"
            )
        ]
    else:
        key_products = [
            KeyProductSuggestion(
                name="Servicio Principal / Membresía Recurrente",
                category="Ingreso Recurrente",
                target_margin_pct=70.0,
                turnover_speed="Alta",
                local_advantage="Cubre la base de costos fijos mensuales desde los primeros 10 días del mes.",
                suggested_source="Operación Propia"
            ),
            KeyProductSuggestion(
                name="Add-ons & Productos Retail Especializados",
                category="Cross-Selling",
                target_margin_pct=50.0,
                turnover_speed="Media",
                local_advantage="Venta cruzada a clientes cautivos con confianza en la marca.",
                suggested_source="Distribuidor Mayorista"
            ),
            KeyProductSuggestion(
                name="Consumibles Operativos & Mantenimiento",
                category="Operación Continua",
                target_margin_pct=30.0,
                turnover_speed="Media",
                local_advantage="Adquisición programada con crédito comercial a 30 días para proteger liquidez.",
                suggested_source="Proveedor de Servicios Industriales"
            )
        ]

    pricing = (f"Para la zona '{zone}' en {state}: Se recomienda fijar precios considerando un margen bruto "
               f"mínimo del 45% al 60% para absorber los costos de renta comercial locales y cargas laborales. "
               f"Establece una política de 3 niveles de precio (Económico, Estándar, Premium) para capturar el excedente del consumidor.")

    return AcquisitionSuggestionResponse(
        state=state,
        zone_type=zone,
        sector=sector,
        commercial_branch=branch,
        regional_supply_strategy=strategy,
        local_vs_import_verdict=local_vs_import,
        logistics_and_freight_insights=logistics,
        recommended_key_products=key_products,
        seasonal_buying_calendar=calendar,
        local_competitive_pricing=pricing,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

@router.post("/acquisition-suggestions", response_model=AcquisitionSuggestionResponse)
async def get_acquisition_suggestions(
    req: AcquisitionSuggestionRequest,
    x_gemini_api_key: Optional[str] = Header(None)
):
    """
    Genera recomendaciones de compras y adquisición de insumos optimizadas por geolocalización,
    sector económico y tipo de zona comercial en México.
    """
    b = req.business
    api_key = req.custom_api_key or x_gemini_api_key or os.getenv("GEMINI_API_KEY")
    
    # Heurística inicial robusta
    base_plan = generate_heuristic_acquisition_plan(b)
    
    # Si hay API Key de Gemini, enriquecer con análisis de IA
    if api_key:
        try:
            model = req.gemini_model or "gemini-3.5-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            prompt = f"""
            Eres un experto en Cadena de Suministro (Supply Chain), Logística y Adquisiciones comerciales en México.
            Analiza el siguiente negocio y genera recomendaciones estratégicas de compra de productos e insumos:
            - Nombre: {b.name}
            - Sector Económico: {b.sector or 'Comercio'}
            - Giro Comercial: {b.commercial_branch or b.business_type}
            - Estado de México: {b.state or 'Ciudad de México'}
            - Municipio / Ciudad: {b.municipality or 'No especificado'}
            - Tipo de Zona: {b.zone_type or 'Corredor comercial'}
            - Descripción: {b.description}
            - Inversión Inicial estimada: ${b.target_market}

            Responde estrictamente en formato JSON con las siguientes claves:
            {{
              "regional_supply_strategy": "Explicación de estrategia de compra según la geografía",
              "local_vs_import_verdict": "Veredicto sobre si conviene comprar en México o importar y qué porcentaje",
              "logistics_and_freight_insights": "Consejos sobre fletes, carreteras y centros logísticos cercanos",
              "local_competitive_pricing": "Consejo sobre política de precios para ese tipo de zona",
              "recommended_key_products": [
                {{"name": "...", "category": "...", "target_margin_pct": 50.0, "turnover_speed": "Alta", "local_advantage": "...", "suggested_source": "..."}}
              ],
              "seasonal_buying_calendar": [
                {{"season_period": "Ene-Mar", "action": "...", "recommended_focus": "...", "discount_opportunity": "..."}}
              ]
            }}
            """
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.post(url, json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}
                })
                if resp.status_code == 200:
                    data = resp.json()
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(raw_text)
                    
                    products = [KeyProductSuggestion(**p) for p in parsed.get("recommended_key_products", [])] or base_plan.recommended_key_products
                    calendar = [SeasonalCalendarItem(**c) for c in parsed.get("seasonal_buying_calendar", [])] or base_plan.seasonal_buying_calendar
                    
                    return AcquisitionSuggestionResponse(
                        state=b.state or "Ciudad de México",
                        zone_type=b.zone_type or "Corredor comercial",
                        sector=b.sector or "Comercio",
                        commercial_branch=b.commercial_branch or b.business_type or "Comercio",
                        regional_supply_strategy=parsed.get("regional_supply_strategy", base_plan.regional_supply_strategy),
                        local_vs_import_verdict=parsed.get("local_vs_import_verdict", base_plan.local_vs_import_verdict),
                        logistics_and_freight_insights=parsed.get("logistics_and_freight_insights", base_plan.logistics_and_freight_insights),
                        recommended_key_products=products,
                        seasonal_buying_calendar=calendar,
                        local_competitive_pricing=parsed.get("local_competitive_pricing", base_plan.local_competitive_pricing),
                        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )
        except Exception:
            # Si hay cualquier fallo de red o API de Gemini, fallback a la heurística especializada
            pass

    return base_plan
