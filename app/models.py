from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class BusinessProfile(BaseModel):
    name: str = Field(default="Mi Proyecto", description="Nombre del proyecto o empresa")
    business_type: str = Field(default="Comercio / Servicios", description="Giro o tipo de negocio (e.g., Cafetería, E-commerce, Software SaaS, Gimnasio)")
    description: str = Field(default="Propuesta de valor y venta de productos o servicios.", description="Descripción detallada de la propuesta de valor y productos/servicios")
    target_market: str = Field(default="Clientes y consumidores del sector.", description="Público objetivo y segmento de clientes")
    location: str = Field(default="Ubicación comercial.", description="Ubicación geográfica, ciudad, tipo de zona (comercial, residencial, virtual)")
    location_details: Optional[str] = Field("", description="Detalles adicionales: flujo peatonal, accesibilidad, nivel socioeconómico")
    competition_level: str = Field(default="Media", description="Nivel de competencia (Baja, Media, Alta, Saturada)")
    competition_details: Optional[str] = Field("", description="Principales competidores identificados y diferenciadores clave")
    competitive_advantage: Optional[str] = Field("", description="Ventaja competitiva o Moat propuesto")

class FinancialInputs(BaseModel):
    initial_investment: float = Field(default=0.0, ge=0, description="Inversión inicial total en Pesos Mexicanos (MXN)")
    discount_rate_pct: float = Field(default=14.0, ge=0.0, le=10000.0, description="Tasa de descuento anual / WACC en % (ej. 14)")
    bank_risk_free_rate_pct: float = Field(default=10.0, ge=0.0, le=1000.0, description="Rendimiento anual pasivo que daría un banco o CETES sin riesgo (%)")
    shrinkage_risk_loss_pct: float = Field(default=2.0, ge=0.0, le=100.0, description="Pérdida estimada por mermas, robos hormiga, caducidad o riesgos operativos (%)")
    projection_years: int = Field(default=5, ge=1, le=20, description="Años de proyección")
    monthly_price: float = Field(default=0.0, ge=0, description="Precio de venta promedio unitario / Ticket promedio mensual en MXN")
    monthly_units: float = Field(default=0.0, ge=0, description="Volumen estimado mensual de ventas en unidades / clientes atendidos")
    unit_variable_cost: float = Field(default=0.0, ge=0, description="Costo variable unitario en MXN (materia prima, comisiones, empaque)")
    monthly_fixed_costs: float = Field(default=0.0, ge=0, description="Costos fijos mensuales totales en MXN (Renta, nóminas, servicios, seguros, marketing)")
    monthly_maintenance_cost: float = Field(default=0.0, ge=0.0, description="Mantenimiento recurrente y reserva mensual para reemplazo de equipo en MXN")
    annual_sales_growth_pct: float = Field(default=8.0, ge=-100.0, le=10000.0, description="Crecimiento anual esperado en volumen de ventas (%)")
    annual_inflation_pct: float = Field(default=4.0, ge=0.0, le=10000.0, description="Tasa anual estimada de inflación / incremento en costos (%)")
    tax_rate_pct: float = Field(default=30.0, ge=0.0, le=100.0, description="Tasa impositiva sobre utilidades (%)")
    depreciation_years: int = Field(default=5, ge=1, le=50, description="Años de depreciación de la inversión en activos")

class AnalysisRequest(BaseModel):
    business: BusinessProfile
    financials: FinancialInputs
    gemini_model: Optional[str] = Field(default="gemini-3.5-flash", description="Modelo de Gemini a utilizar")
    custom_api_key: Optional[str] = Field(default=None, description="API Key opcional provista en la petición")

class YearCashFlow(BaseModel):
    year: int
    units_sold: float
    price_unit: float
    revenue: float
    shrinkage_loss: float = 0.0
    net_revenue: float = 0.0
    variable_costs: float
    gross_margin: float
    gross_margin_pct: float
    fixed_costs: float
    ebitda: float
    depreciation: float
    ebit: float
    taxes: float
    net_income: float
    net_margin_pct: float
    free_cash_flow: float
    terminal_value: float = 0.0
    discounted_cash_flow: float
    cumulative_cash_flow: float

class BreakEvenMetrics(BaseModel):
    unit_contribution_margin: float
    contribution_margin_ratio_pct: float
    monthly_breakeven_units: float
    monthly_breakeven_revenue: float
    annual_breakeven_revenue: float
    margin_of_safety_pct: float
    current_monthly_revenue: float
    current_monthly_profit: float

class OpportunityCostComparison(BaseModel):
    bank_risk_free_rate_pct: float
    bank_passive_annual_income: float
    bank_passive_monthly_income: float
    business_net_annual_income: float
    business_net_monthly_income: float
    annual_difference: float
    monthly_difference: float
    risk_premium_pct: float
    verdict: str
    verdict_color: str

class ScenarioSummary(BaseModel):
    name: str
    description: str
    npv: float
    irr_pct: Optional[float]
    payback_years: Optional[float]
    total_5yr_net_profit: float
    roi_annual_avg_pct: float

class FinancialReport(BaseModel):
    npv: float
    irr_pct: Optional[float]
    payback_years: Optional[float]
    discounted_payback_years: Optional[float]
    benefit_cost_ratio: float
    roi_annual_avg_pct: float
    initial_investment: float
    discount_rate_pct: float
    recommended_equipment_reserve: float = 0.0
    shrinkage_annual_loss: float = 0.0
    shrinkage_monthly_loss: float = 0.0
    bank_comparison: Optional[OpportunityCostComparison] = None
    break_even: BreakEvenMetrics
    yearly_cash_flows: List[YearCashFlow]
    scenarios: Dict[str, ScenarioSummary]
    viability_status: str
    viability_color: str
    summary_bullets: List[str]

class RiskMatrixItem(BaseModel):
    category: str
    risk: str
    severity: str
    mitigation: str

class StrategicAdvice(BaseModel):
    viability_score: int
    verdict: str
    executive_summary: str
    location_analysis: str
    competition_analysis: str
    cost_structure_analysis: str
    risks_matrix: List[RiskMatrixItem]
    action_plan_steps: List[str]
    growth_tactics: List[str]

class FullAnalysisResponse(BaseModel):
    financial_report: FinancialReport
    strategic_advice: Optional[StrategicAdvice] = None
    ai_raw_text: Optional[str] = None
    generated_at: str

class EquipmentItem(BaseModel):
    category: str = Field(default="Maquinaria", description="Categoría: Maquinaria, Servicios, o Empleados")
    name: str = Field(..., description="Nombre genérico del equipo/maquinaria")
    description: str = Field(..., description="Descripción técnica o uso previsto")

class EquipmentRequest(BaseModel):
    items: List[EquipmentItem]
    custom_api_key: Optional[str] = None
    gemini_model: Optional[str] = "gemini-3.5-flash"

class BudgetOption(BaseModel):
    budget_type: str = Field(..., description="Ej: Económico, Estándar, Premium")
    total_cost: float = Field(..., description="Costo total estimado en MXN")
    details: List[str] = Field(..., description="Detalle del equipo sugerido (marca, modelo, precio unitario MXN)")

class BudgetsResponse(BaseModel):
    budgets: List[BudgetOption]
    summary: str = Field(..., description="Conclusión o recomendación sobre las opciones")
    generated_at: str

class ProcessRequest(BaseModel):
    process_description: str = Field(..., description="Descripción del proceso de producción o servicio")
    custom_api_key: Optional[str] = None
    gemini_model: Optional[str] = "gemini-3.5-flash"

class ActivityItem(BaseModel):
    step_number: int = 1
    activity: str = "Actividad"
    time_estimate: str = "N/A"
    movements: str = "N/A"

class ConsumableItem(BaseModel):
    item_name: str = "Consumible"
    quantity_monthly: str = "0"
    monthly_cost_estimate: float = 0.0

class FlowchartResponse(BaseModel):
    mermaid_code: str = Field(..., description="Código Mermaid.js para el diagrama de flujo")
    activities: List[ActivityItem]
    consumables_table: List[ConsumableItem]
    total_monthly_consumables_cost: float
    generated_at: str
