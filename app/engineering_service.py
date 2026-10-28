import os
import json
import httpx
from datetime import datetime
from typing import Optional, Tuple
from .models import (
    EquipmentRequest, BudgetsResponse, BudgetOption,
    ProcessRequest, FlowchartResponse, ActivityItem, ConsumableItem
)

async def _call_gemini(prompt: str, system_instruction: str, api_key: str, model_name: str) -> str:
    clean_model = model_name.strip()
    if not clean_model:
        clean_model = "gemini-3.5-flash"
        
    ordered = [clean_model, "gemini-3.5-flash", "gemini-3.5-flash-lite"]
    candidate_models = []
    for m in ordered:
        if m not in candidate_models:
            candidate_models.append(m)
            
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "generationConfig": {"temperature": 0.2, "topP": 0.95, "responseMimeType": "application/json"}
    }
    
    async with httpx.AsyncClient(timeout=90.0) as client:
        for model in candidate_models:
            success = False
            for api_version in ["v1beta", "v1"]:
                url = f"https://generativelanguage.googleapis.com/{api_version}/models/{model}:generateContent?key={api_key}"
                try:
                    response = await client.post(url, headers={"Content-Type": "application/json"}, json=payload)
                    if response.status_code == 200:
                        data = response.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                            return raw_text
                except Exception:
                    pass
    raise Exception("Fallo la comunicación con Gemini API")

def _parse_json(raw_text: str) -> dict:
    clean_json_str = raw_text.strip()
    if clean_json_str.startswith("```json"):
        clean_json_str = clean_json_str[7:]
    if clean_json_str.startswith("```"):
        clean_json_str = clean_json_str[3:]
    if clean_json_str.endswith("```"):
        clean_json_str = clean_json_str[:-3]
    return json.loads(clean_json_str.strip())

async def generate_equipment_budgets(req: EquipmentRequest) -> BudgetsResponse:
    api_key = req.custom_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("API Key requerida")
        
    system_inst = """
    Eres un Ingeniero de Proyectos y Experto en Adquisiciones especializado en el mercado de México.
    Tu tarea es generar 3 presupuestos de inversión inicial (Económico, Estándar y Premium) que contemplen Maquinaria, Servicios (trámites, licencias, adecuaciones) y Empleados (reclutamiento o nómina inicial).
    Debes verificar y estimar los precios reales de mercado en México en MXN (Pesos Mexicanos).
    Devuelve un JSON con:
    {
      "budgets": [
        {
          "budget_type": "Económico",
          "total_cost": 150000.0,
          "details": ["1x Máquina A - Marca X - $50,000 MXN", "1x Equipo B - Marca Y - $100,000 MXN"]
        },
        ... (Estándar y Premium)
      ],
      "summary": "Resumen comparativo de las 3 opciones y recomendación."
    }
    """
    
    items_list = "\n".join([f"- [{item.category}] {item.name}: {item.description}" for item in req.items])
    prompt = f"Genera 3 presupuestos detallados en MXN para la siguiente inversión inicial requerida en México:\n\n{items_list}"
    
    raw = await _call_gemini(prompt, system_inst, api_key, req.gemini_model)
    parsed = _parse_json(raw)
    
    budgets = []
    for b in parsed.get("budgets", []):
        budgets.append(BudgetOption(
            budget_type=b.get("budget_type", "Opción"),
            total_cost=float(b.get("total_cost", 0.0)),
            details=b.get("details", [])
        ))
        
    return BudgetsResponse(
        budgets=budgets,
        summary=parsed.get("summary", ""),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

async def generate_production_flowchart(req: ProcessRequest) -> FlowchartResponse:
    api_key = req.custom_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("API Key requerida")
        
    system_inst = """
    Eres un Ingeniero Industrial experto en Mejora Continua, Diagramas de Flujo y Eficiencia Energética.
    Tu tarea es analizar una descripción de proceso de producción y generar:
    1. Un código en Mermaid.js válido para un diagrama de flujo de forma horizontal (usando flowchart LR). Usa figuras variadas de Mermaid.js para mejorar la estética y legibilidad: usa ([Inicio/Fin]) para los límites del proceso, {Decisión} para ramas o verificaciones, [(Almacén/Inventario)] para almacenamiento, y rectángulos redondeados o normales para las actividades.
    2. Una lista de actividades describiendo paso a paso con tiempos estimados y movimientos clave.
    3. Una estimación de consumo mensual de energía (Kw/h) y de cualquier otro consumible (agua, gas, materias primas indirectas) involucrado en el proceso.
    
    Devuelve estrictamente un JSON con esta estructura:
    {
      "mermaid_code": "flowchart LR\\n A([Inicio]) --> B{Decisión}\\n B -->|Sí| C[Actividad 1]\\n ...",
      "activities": [
        {"step_number": 1, "activity": "Descripción", "time_estimate": "5 min", "movements": "Traslado a zona X"}
      ],
      "consumables_table": [
        {"item_name": "Energía Horno", "quantity_monthly": "450 Kw/h", "monthly_cost_estimate": 1125.0},
        {"item_name": "Agua", "quantity_monthly": "10 m3", "monthly_cost_estimate": 800.0}
      ],
      "total_monthly_consumables_cost": 1925.0
    }
    No incluyas comillas invertidas (```json) rodeando la respuesta, solo el objeto JSON crudo.
    """
    
    prompt = f"Analiza el siguiente proceso de producción y genera el diagrama de flujo y tabla energética:\n\n{req.process_description}"
    
    raw = await _call_gemini(prompt, system_inst, api_key, req.gemini_model)
    parsed = _parse_json(raw)
    
    activities = [ActivityItem(**act) for act in parsed.get("activities", [])]
    consumables_table = [ConsumableItem(**en) for en in parsed.get("consumables_table", [])]
    
    return FlowchartResponse(
        mermaid_code=parsed.get("mermaid_code", ""),
        activities=activities,
        consumables_table=consumables_table,
        total_monthly_consumables_cost=float(parsed.get("total_monthly_consumables_cost", 0.0)),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
