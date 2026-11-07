import os
import re
import json
import time
import httpx
from datetime import datetime
from typing import Optional, List, Dict, Any
from .models import (
    EquipmentRequest, BudgetsResponse, BudgetOption,
    ProcessRequest, FlowchartResponse, ActivityItem, ConsumableItem
)

# Modelos con cuota gratuita activa en Google AI Studio (ordenados por velocidad y disponibilidad de cuota)
ACTIVE_FREE_TIER_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]

MODEL_ALIASES = {
    "gemini-3.5-flash": "gemini-3.5-flash-lite",
}

# Caché en memoria de modelos disponibles por API key para evitar múltiples peticiones 404
_MODELS_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 600


async def resolve_available_models(client: httpx.AsyncClient, api_key: str, requested_model: str) -> List[str]:
    clean_req = MODEL_ALIASES.get((requested_model or "").strip(), (requested_model or "").strip()) or "gemini-3.8-flash"
    preferred_order = [clean_req] + [m for m in ACTIVE_FREE_TIER_MODELS if m != clean_req]

    cache_key = api_key[:12]
    now = time.time()
    cached = _MODELS_CACHE.get(cache_key)
    api_models: List[str] = []

    if cached and (now - cached["ts"] < _CACHE_TTL_SECONDS):
        api_models = cached["models"]
    else:
        try:
            resp = await client.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                timeout=6.0
            )
            if resp.status_code == 200:
                for m in resp.json().get("models", []):
                    methods = m.get("supportedGenerationMethods", [])
                    name = m.get("name", "").replace("models/", "")
                    lname = name.lower()
                    if (
                        "generateContent" in methods
                        and "gemini" in lname
                        and "tts" not in lname
                        and "image" not in lname
                        and "live" not in lname
                        and "embedding" not in lname
                        and "robotics" not in lname
                        and "computer-use" not in lname
                        and "2.0" not in lname
                        and "1.5" not in lname
                        and "-pro" not in lname
                    ):
                        api_models.append(name)
                if api_models:
                    _MODELS_CACHE[cache_key] = {"ts": now, "models": api_models}
        except Exception:
            pass

    if not api_models:
        return preferred_order

    resolved: List[str] = []
    for pref in preferred_order:
        # Coincidencia exacta
        if pref in api_models and pref not in resolved:
            resolved.append(pref)
            continue
        # Coincidencia con sufijo -preview o variante menor (ej. gemini-3.8-flash-preview, gemini-3-flash-preview)
        for avail in api_models:
            if avail.startswith(pref) and avail not in resolved:
                resolved.append(avail)

    # Añadir cualquier otro modelo flash válido disponible en la cuenta que no esté en la lista
    for avail in api_models:
        if avail not in resolved:
            resolved.append(avail)

    return resolved or preferred_order


def _extract_text_from_candidates(data: dict) -> str:
    candidates = data.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        return ""
    # Preferir la última parte que no sea de pensamiento interno ("thought": True)
    for part in reversed(parts):
        if not part.get("thought") and part.get("text"):
            return part["text"]
    return parts[-1].get("text", "")


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", s)
    if match:
        try:
            return float(match.group(0).replace(",", ""))
        except Exception:
            return default
    return default


def _parse_json(raw_text: str) -> Any:
    clean = (raw_text or "").strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    clean = clean.strip()

    try:
        return json.loads(clean)
    except Exception:
        # Extraer el primer bloque JSON {...} o [...] si hay texto adicional
        start_obj = clean.find("{")
        end_obj = clean.rfind("}")
        if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
            return json.loads(clean[start_obj : end_obj + 1])
        raise


async def _call_gemini(prompt: str, system_instruction: str, api_key: str, model_name: str) -> str:
    last_err = "Fallo la comunicación con Gemini API"
    async with httpx.AsyncClient(timeout=22.0) as client:
        candidate_models = await resolve_available_models(client, api_key, model_name)

        base_payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.95,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            },
        }

        for model in candidate_models[:5]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            # Intentar con thinkingBudget=0 en modelos 2.5/3 para respuesta ultra-rápida (2-4 seg)
            payload = json.loads(json.dumps(base_payload))
            if "2.5-flash" in model or "3-flash" in model or "3." in model:
                payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}

            try:
                response = await client.post(url, headers={"Content-Type": "application/json"}, json=payload)
                # Si el modelo no admite thinkingConfig (HTTP 400), reintentar de inmediato sin thinkingConfig
                if response.status_code == 400 and "thinkingConfig" in response.text:
                    response = await client.post(url, headers={"Content-Type": "application/json"}, json=base_payload)

                if response.status_code == 200:
                    raw_text = _extract_text_from_candidates(response.json())
                    if raw_text:
                        return raw_text
                elif response.status_code in (404, 429, 503):
                    last_err = f"Modelo {model} no disponible o en límite de cuota ({response.status_code})"
                    continue
                else:
                    try:
                        err_msg = response.json().get("error", {}).get("message", response.text)
                    except Exception:
                        err_msg = response.text
                    if "API_KEY_INVALID" in response.text or "API key not valid" in err_msg:
                        raise Exception(f"API Key inválida: {err_msg}")
                    last_err = f"{model} ({response.status_code}): {err_msg}"
                    continue
            except Exception as exc:
                if "API Key inválida" in str(exc):
                    raise
                last_err = str(exc)
                continue

    raise Exception(last_err)


async def generate_equipment_budgets(req: EquipmentRequest) -> BudgetsResponse:
    api_key = (req.custom_api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key or api_key in ("tu_api_key_aqui", "tu_api_key_de_google_aistudio_aqui"):
        raise ValueError("API Key de Gemini requerida. Configúrala en el botón 'API Key Gemini'.")

    system_inst = (
        "Eres un Ingeniero de Proyectos y Experto en Adquisiciones en México. "
        "Genera exactamente 3 presupuestos de inversión inicial (Económico, Estándar y Premium) en MXN "
        "contemplando los ítems solicitados. Sé directo y conciso. "
        "Devuelve estrictamente un JSON con esta estructura exacta: "
        '{"budgets":[{"budget_type":"Económico","total_cost":150000,"details":["Equipo A - $50,000 MXN","Equipo B - $100,000 MXN"]},'
        '{"budget_type":"Estándar","total_cost":220000,"details":["..."]},'
        '{"budget_type":"Premium","total_cost":340000,"details":["..."]}],'
        '"summary":"Recomendación ejecutiva breve."}'
    )

    items_list = "\n".join([f"- [{item.category}] {item.name}: {item.description}" for item in req.items])
    prompt = f"Cotiza 3 presupuestos (Económico, Estándar, Premium) en MXN para:\n{items_list}"

    raw = await _call_gemini(prompt, system_inst, api_key, req.gemini_model)
    parsed = _parse_json(raw)

    raw_budgets = parsed.get("budgets", []) if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
    budgets = []
    for b in raw_budgets:
        if not isinstance(b, dict):
            continue
        raw_details = b.get("details", [])
        clean_details: List[str] = []
        if isinstance(raw_details, list):
            for d in raw_details:
                if isinstance(d, str):
                    clean_details.append(d)
                elif isinstance(d, dict):
                    name = d.get("name") or d.get("item") or d.get("equipo") or "Partida"
                    cost = d.get("cost") or d.get("price") or d.get("precio") or ""
                    clean_details.append(f"{name} - ${cost} MXN" if cost else str(name))
        total_cost = _safe_float(b.get("total_cost"), 0.0)
        if total_cost <= 0 and clean_details:
            total_cost = sum(_safe_float(line, 0.0) for line in clean_details)
        budgets.append(BudgetOption(
            budget_type=str(b.get("budget_type", "Opción")),
            total_cost=total_cost,
            details=clean_details
        ))

    summary_text = parsed.get("summary", "Presupuestos generados con IA.") if isinstance(parsed, dict) else "Presupuestos generados con IA."
    return BudgetsResponse(
        budgets=budgets,
        summary=str(summary_text),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )


async def generate_production_flowchart(req: ProcessRequest) -> FlowchartResponse:
    api_key = (req.custom_api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key or api_key in ("tu_api_key_aqui", "tu_api_key_de_google_aistudio_aqui"):
        raise ValueError("API Key de Gemini requerida. Configúrala en el botón 'API Key Gemini'.")

    system_inst = (
        "Eres un Ingeniero Industrial experto en Diagramas de Flujo y Eficiencia Energética. "
        "Analiza el proceso y genera de forma concisa: "
        "1. mermaid_code: Código Mermaid válido usando 'flowchart LR'. Usa A([Inicio]), B[(Almacén)], C[Operación], D{Verificación} y Z([Fin]). No uses caracteres especiales raros dentro de los nodos. "
        "2. activities: Lista de pasos con step_number (int), activity (str), time_estimate (str) y movements (str). "
        "3. consumables_table: Lista de consumos mensuales (energía eléctrica en Kw/h, agua, gas, insumos) con item_name (str), quantity_monthly (str) y monthly_cost_estimate (float en MXN). "
        "4. total_monthly_consumables_cost: Suma total mensual en MXN (float). "
        "Devuelve estrictamente un objeto JSON válido con esas 4 llaves."
    )

    prompt = f"Diseña el diagrama de flujo Mermaid LR, tabla de actividades y tabla de consumo energético (Kw/h y suministros) en MXN para:\n{req.process_description}"

    raw = await _call_gemini(prompt, system_inst, api_key, req.gemini_model)
    parsed = _parse_json(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Respuesta JSON de IA con formato inesperado.")

    activities: List[ActivityItem] = []
    for idx, act in enumerate(parsed.get("activities", []), start=1):
        if isinstance(act, dict):
            activities.append(ActivityItem(
                step_number=int(_safe_float(act.get("step_number"), idx)),
                activity=str(act.get("activity") or act.get("name") or f"Paso {idx}"),
                time_estimate=str(act.get("time_estimate") or act.get("time") or "10 min"),
                movements=str(act.get("movements") or act.get("movement") or "Operación en estación")
            ))

    consumables_table: List[ConsumableItem] = []
    for en in parsed.get("consumables_table", []):
        if isinstance(en, dict):
            cost_val = _safe_float(en.get("monthly_cost_estimate") or en.get("cost"), 0.0)
            consumables_table.append(ConsumableItem(
                item_name=str(en.get("item_name") or en.get("name") or "Suministro"),
                quantity_monthly=str(en.get("quantity_monthly") or en.get("quantity") or "1 lote"),
                monthly_cost_estimate=cost_val
            ))

    total_cost = _safe_float(parsed.get("total_monthly_consumables_cost"), 0.0)
    if total_cost <= 0 and consumables_table:
        total_cost = sum(c.monthly_cost_estimate for c in consumables_table)

    return FlowchartResponse(
        mermaid_code=str(parsed.get("mermaid_code") or ""),
        activities=activities,
        consumables_table=consumables_table,
        total_monthly_consumables_cost=total_cost,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
