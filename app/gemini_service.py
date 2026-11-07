import os
import json
import httpx
from typing import Optional, Dict, Any, Tuple
from .models import BusinessProfile, FinancialInputs, FinancialReport, StrategicAdvice

GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM_INSTRUCTION = """
Eres un Director Financiero (CFO) y Consultor Estratégico de Negocios de clase mundial especializado en el mercado mexicano y latinoamericano.
Tu especialidad es la evaluación económica rigurosa, finanzas corporativas, economía de unidades (Unit Economics), análisis de micro-localización y estrategia competitiva (Marco de Michael Porter y Value Proposition Design).

TODOS los valores monetarios están expresados en PESOS MEXICANOS (MXN). Considera el contexto macroeconómico, fiscal (SAT / ISR en México) y comercial de México (rentas en plazas o zonas comerciales mexicanas, sueldos, costos operativos e inflación local).

Tu misión es analizar la viabilidad económica y estratégica del negocio proporcionado, interpretando los indicadores financieros calculados con fórmulas validadas (VAN, TIR, Payback, Punto de Equilibrio, Margen de Contribución y Sensibilidad) y cruzándolos con los datos del giro de negocio, ubicación, perfil de competencia y estructura de costos en Pesos Mexicanos.

DEBES responder ÚNICAMENTE con un objeto JSON válido que siga estrictamente la estructura solicitada, sin bloques de código ni texto adicional fuera del JSON.
"""

def build_analysis_prompt(
    business: BusinessProfile,
    financials: FinancialInputs,
    report: FinancialReport
) -> str:
    flows_summary = "\n".join([
        f"- Año {f.year}: Ingresos=${f.revenue:,.2f} MXN | Costos Var=${f.variable_costs:,.2f} MXN | Costos Fijos=${f.fixed_costs:,.2f} MXN | EBITDA=${f.ebitda:,.2f} MXN | Utilidad Neta=${f.net_income:,.2f} MXN | Flujo Libre=${f.free_cash_flow:,.2f} MXN"
        for f in report.yearly_cash_flows
    ])

    return f"""
Analiza detalladamente la viabilidad de este proyecto de negocio (Moneda: Pesos Mexicanos - MXN):

### 1. DATOS DEL NEGOCIO
- **Nombre:** {business.name}
- **Giro/Sector:** {business.business_type}
- **Propuesta de Valor:** {business.description}
- **Mercado Objetivo:** {business.target_market}
- **Ubicación & Entorno:** {business.location}
- **Detalles de la Ubicación (Tráfico/Zona):** {business.location_details or 'No especificado'}
- **Nivel de Competencia:** {business.competition_level}
- **Competidores & Contexto:** {business.competition_details or 'No especificado'}
- **Ventaja Competitiva / Moat:** {business.competitive_advantage or 'No especificado'}

### 2. PARÁMETROS ECONÓMICOS DE ENTRADA (VALORES EN MXN)
- Inversión Inicial ($I_0$): ${financials.initial_investment:,.2f} MXN
- Tasa de Descuento (WACC / Tasa de Corte Exigida): {financials.discount_rate_pct}%
- Tasa Libre de Riesgo / Renta Pasiva Banco o CETES: {financials.bank_risk_free_rate_pct}%
- Pérdida Estimada por Mermas, Robos y Riesgos Operativos: {financials.shrinkage_risk_loss_pct}% (-${report.shrinkage_monthly_loss:,.2f} MXN/mes deducidos)
- Reserva y Mantenimiento Mensual de Equipo: ${financials.monthly_maintenance_cost:,.2f} MXN
- Precio Promedio / Ticket: ${financials.monthly_price:,.2f} MXN
- Demanda Mensual Estimada: {financials.monthly_units:,.0f} unidades/clientes
- Costo Variable Unitario: ${financials.unit_variable_cost:,.2f} MXN
- Costos Fijos Mensuales: ${financials.monthly_fixed_costs:,.2f} MXN
- Crecimiento Anual de Ventas: {financials.annual_sales_growth_pct}%
- Inflación Anual de Costos: {financials.annual_inflation_pct}%
- Tasa de ISR / Impuestos: {financials.tax_rate_pct}%

### 3. RESULTADOS CUANTITATIVOS CALCULADOS (FÓRMULAS VALIDADAS)
- **VAN (Valor Actual Neto):** ${report.npv:,.2f} MXN
- **TIR (Tasa Interna de Retorno):** {f"{report.irr_pct}%" if report.irr_pct is not None else "No calculable"}
- **Payback Simple:** {f"{report.payback_years:.2f} años" if report.payback_years else "No recupera en el horizonte"}
- **Payback Descontado:** {f"{report.discounted_payback_years:.2f} años" if report.discounted_payback_years else "No recupera"}
- **Relación Beneficio/Costo (B/C):** {report.benefit_cost_ratio:.2f}
- **ROI Anual Promedio:** {report.roi_annual_avg_pct:.2f}%
- **Punto de Equilibrio Mensual:** {report.break_even.monthly_breakeven_units:,.0f} unidades (${report.break_even.monthly_breakeven_revenue:,.2f} MXN)
- **Margen de Contribución Unitario:** ${report.break_even.unit_contribution_margin:,.2f} MXN ({report.break_even.contribution_margin_ratio_pct:.1f}%)
- **Margen de Seguridad:** {report.break_even.margin_of_safety_pct:.1f}%

### 4. COMPARATIVA DE COSTO DE OPORTUNIDAD (BANCO / CETES vs TU NEGOCIO)
- **Ganancia Pasiva Banco/CETES (Riesgo Cero):** ${report.bank_comparison.bank_passive_annual_income:,.2f} MXN/año (${report.bank_comparison.bank_passive_monthly_income:,.2f} MXN/mes)
- **Utilidad Neta Real del Negocio:** ${report.bank_comparison.business_net_annual_income:,.2f} MXN/año (${report.bank_comparison.business_net_monthly_income:,.2f} MXN/mes)
- **Premio por Riesgo (Spread sobre Banco):** {report.bank_comparison.risk_premium_pct:+.1f}% (${report.bank_comparison.annual_difference:+,.2f} MXN/año de diferencia)
- **Diagnóstico de Oportunidad:** {report.bank_comparison.verdict}

### 5. RESUMEN DE FLUJOS DE CAJA PROYECTADOS (5 AÑOS EN MXN):
{flows_summary}

### 6. ESCENARIOS DE SENSIBILIDAD (MXN):
- **Pesimista (-20% ventas, +15% cv, +10% cf):** VAN=${report.scenarios['pessimistic'].npv:,.2f} MXN | TIR={report.scenarios['pessimistic'].irr_pct}%
- **Base:** VAN=${report.scenarios['base'].npv:,.2f} MXN | TIR={report.scenarios['base'].irr_pct}%
- **Optimista (+20% ventas, -10% cv, -5% cf):** VAN=${report.scenarios['optimistic'].npv:,.2f} MXN | TIR={report.scenarios['optimistic'].irr_pct}%

---
INSTRUCCIÓN DE SALIDA:
Genera un dictamen financiero y estratégico completo y profundo en formato JSON con la siguiente estructura exacta:

{{
  "viability_score": <Número entero entre 0 y 100 evaluando la viabilidad general>,
  "verdict": "<Frase contundente de dictamen: ej. 'Altamente Viable y Escalable', 'Viable sujeto a Optimización de Costos Fijos', 'Riesgo Crítico / No Recomendado'>",
  "executive_summary": "<Resumen ejecutivo de 2-3 párrafos con diagnóstico financiero profundo, evaluando VAN, TIR, flujo y sustentabilidad>",
  "location_analysis": "<Análisis estratégico específico para la ubicación y sector. Cómo impacta el punto geográfico, flujo, accesibilidad y costo de renta en la atracción de clientes>",
  "competition_analysis": "<Análisis de competencia para el nivel ({business.competition_level}). Cómo posicionarse, crear barreras de entrada, proteger márgenes y evitar la guerra de precios>",
  "cost_structure_analysis": "<Evaluación detallada del Punto de Equilibrio y Margen de Contribución. Diagnóstico sobre si los costos fijos o variables son adecuados para la industria y cómo optimizarlos>",
  "risks_matrix": [
    {{
      "category": "Financiero | Mercado | Operativo | Ubicación/Regulatorio",
      "risk": "<Descripción precisa del riesgo>",
      "severity": "Alta | Media | Baja",
      "mitigation": "<Estrategia concreta de mitigación>"
    }}
  ],
  "action_plan_steps": [
    "<Paso 1: Validación y pre-lanzamiento>",
    "<Paso 2: Optimización de capital y negociación de costos>",
    "<Paso 3: Estrategia de adquisición inicial de clientes>",
    "<Paso 4: Métricas clave a vigilar en los primeros 90 días>",
    "<Paso 5: Estrategia de escalabilidad>"
  ],
  "growth_tactics": [
    "<Táctica 1 para incrementar ticket promedio o recurrencia>",
    "<Táctica 2 para optimizar costos y maximizar margen de contribución>",
    "<Táctica 3 de marketing local / digital adaptada a la zona>"
  ]
}}
"""

from .engineering_service import resolve_available_models, _extract_text_from_candidates, _parse_json

async def generate_gemini_analysis(
    business: BusinessProfile,
    financials: FinancialInputs,
    report: FinancialReport,
    model_name: str = "gemini-3.8-flash",
    custom_api_key: Optional[str] = None
) -> Tuple[Optional[StrategicAdvice], str]:
    api_key = (custom_api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key or api_key in ("tu_api_key_aqui", "tu_api_key_de_google_aistudio_aqui"):
        raise ValueError("No se proporcionó una API Key válida de Gemini. Ingrésala en el botón 'API Key Gemini' de la barra superior.")

    prompt = build_analysis_prompt(business, financials, report)

    base_payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.95,
            "maxOutputTokens": 2500,
            "responseMimeType": "application/json"
        }
    }

    last_error = None
    raw_text = ""

    async with httpx.AsyncClient(timeout=28.0) as client:
        candidate_models = await resolve_available_models(client, api_key, model_name)
        for model in candidate_models[:5]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = json.loads(json.dumps(base_payload))
            if "2.5-flash" in model or "3-flash" in model or "3." in model:
                payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
            try:
                response = await client.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload
                )
                if response.status_code == 400 and "thinkingConfig" in response.text:
                    response = await client.post(
                        url,
                        headers={"Content-Type": "application/json"},
                        json=base_payload
                    )
                if response.status_code == 200:
                    raw_text = _extract_text_from_candidates(response.json())
                    if raw_text:
                        break
                elif response.status_code in (404, 429, 503):
                    last_error = f"Cuota o saturación temporal en {model} ({response.status_code}). Probando siguiente modelo..."
                    continue
                else:
                    err_msg = response.text
                    try:
                        err_json = response.json()
                        err_msg = err_json.get("error", {}).get("message", response.text)
                    except Exception:
                        pass
                    if "API_KEY_INVALID" in response.text or "API key not valid" in err_msg:
                        raise ValueError(f"Tu API Key de Gemini no es válida: {err_msg}")
                    last_error = f"Error de Gemini API en {model} ({response.status_code}): {err_msg}"
                    continue
            except ValueError:
                raise
            except httpx.RequestError as exc:
                last_error = f"Error de conexión con Gemini API: {str(exc)}"
                continue

    if not raw_text:
        raise ValueError(last_error or "No se pudo conectar con Gemini API. Verifica que tu API Key sea válida y tenga cuota disponible.")

    try:
        parsed = _parse_json(raw_text)
        advice = StrategicAdvice(
            viability_score=int(parsed.get("viability_score", 75)),
            verdict=parsed.get("verdict", "Análisis completado"),
            executive_summary=parsed.get("executive_summary", ""),
            location_analysis=parsed.get("location_analysis", ""),
            competition_analysis=parsed.get("competition_analysis", ""),
            cost_structure_analysis=parsed.get("cost_structure_analysis", ""),
            risks_matrix=parsed.get("risks_matrix", []),
            action_plan_steps=parsed.get("action_plan_steps", []),
            growth_tactics=parsed.get("growth_tactics", [])
        )
        return advice, raw_text
    except Exception as e:
        # Fallback if parsing fails
        advice = StrategicAdvice(
            viability_score=70,
            verdict="Análisis Cuantitativo y Estratégico Generado",
            executive_summary=raw_text[:500],
            location_analysis="Consulte el reporte completo generado.",
            competition_analysis="Consulte el reporte completo generado.",
            cost_structure_analysis="Consulte el reporte completo generado.",
            risks_matrix=[],
            action_plan_steps=["Revisar supuestos financieros", "Monitorear punto de equilibrio"],
            growth_tactics=["Estrategia de posicionamiento diferenciado"]
        )
        return advice, raw_text
