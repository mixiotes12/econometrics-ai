from typing import List, Dict, Tuple, Optional
from .models import (
    FinancialInputs,
    YearCashFlow,
    BreakEvenMetrics,
    ScenarioSummary,
    FinancialReport,
    OpportunityCostComparison
)

def calculate_irr(cash_flows: List[float], max_iter: int = 1000, tol: float = 1e-6) -> Optional[float]:
    """
    Calcula la Tasa Interna de Retorno (TIR / IRR) usando el método de Newton-Raphson
    con fallback a Bisección. cash_flows[0] debe ser la inversión negativa (-I0).
    """
    if not cash_flows or len(cash_flows) < 2:
        return None

    # Check if there is at least one sign change
    has_pos = any(cf > 0 for cf in cash_flows)
    has_neg = any(cf < 0 for cf in cash_flows)
    if not (has_pos and has_neg):
        return None

    def npv_fn(rate: float) -> float:
        if rate <= -1.0:
            return float('inf')
        val = 0.0
        for t, cf in enumerate(cash_flows):
            val += cf / ((1.0 + rate) ** t)
        return val

    def npv_derivative(rate: float) -> float:
        if rate <= -1.0:
            return float('inf')
        dval = 0.0
        for t, cf in enumerate(cash_flows):
            if t > 0:
                dval -= t * cf / ((1.0 + rate) ** (t + 1))
        return dval

    # Newton-Raphson
    rate = 0.10  # Initial guess 10%
    for _ in range(max_iter):
        f = npv_fn(rate)
        if abs(f) < tol:
            return rate
        df = npv_derivative(rate)
        if abs(df) < 1e-12:
            break
        new_rate = rate - f / df
        if abs(new_rate - rate) < tol:
            return new_rate
        if new_rate < -0.99 or new_rate > 10.0:  # out of reasonable bounds
            break
        rate = new_rate

    # Fallback: Bisection Method between -90% and +500%
    low = -0.90
    high = 5.0
    f_low = npv_fn(low)
    f_high = npv_fn(high)

    if f_low * f_high > 0:
        # Check higher bound
        high = 20.0
        f_high = npv_fn(high)
        if f_low * f_high > 0:
            return None

    for _ in range(max_iter):
        mid = (low + high) / 2.0
        f_mid = npv_fn(mid)
        if abs(f_mid) < tol or (high - low) / 2.0 < tol:
            return mid
        if f_low * f_mid < 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid

    return None

def compute_yearly_flows(
    inputs: FinancialInputs,
    sales_multiplier: float = 1.0,
    var_cost_multiplier: float = 1.0,
    fixed_cost_multiplier: float = 1.0
) -> Tuple[List[YearCashFlow], List[float]]:
    """
    Genera la tabla proforma de flujos de caja y el array de flujos para NPV/IRR.
    """
    years = inputs.projection_years
    r = inputs.discount_rate_pct / 100.0
    tax_r = inputs.tax_rate_pct / 100.0
    sales_growth = inputs.annual_sales_growth_pct / 100.0
    inflation = inputs.annual_inflation_pct / 100.0

    depreciation_per_year = inputs.initial_investment / float(inputs.depreciation_years)

    base_monthly_units = inputs.monthly_units * sales_multiplier
    base_unit_var_cost = inputs.unit_variable_cost * var_cost_multiplier
    base_monthly_fixed = (inputs.monthly_fixed_costs + inputs.monthly_maintenance_cost) * fixed_cost_multiplier

    yearly_flows: List[YearCashFlow] = []
    cash_flows_for_irr: List[float] = [-inputs.initial_investment]

    cum_cash = -inputs.initial_investment

    for year in range(1, years + 1):
        growth_factor = (1.0 + sales_growth) ** (year - 1)
        inflation_factor = (1.0 + inflation) ** (year - 1)

        annual_units = base_monthly_units * 12.0 * growth_factor
        current_price = inputs.monthly_price * inflation_factor
        current_var_cost = base_unit_var_cost * inflation_factor

        revenue = annual_units * current_price
        shrinkage_loss = revenue * (inputs.shrinkage_risk_loss_pct / 100.0)
        net_revenue = max(0.0, revenue - shrinkage_loss)
        
        var_costs = annual_units * current_var_cost
        gross_margin = net_revenue - var_costs
        gross_margin_pct = (gross_margin / net_revenue * 100.0) if net_revenue > 0 else 0.0

        fixed_costs = (base_monthly_fixed * 12.0) * inflation_factor
        ebitda = gross_margin - fixed_costs

        depr = depreciation_per_year if year <= inputs.depreciation_years else 0.0
        ebit = ebitda - depr

        taxable_income = max(0.0, ebit)
        taxes = taxable_income * tax_r
        net_income = ebit - taxes
        net_margin_pct = (net_income / net_revenue * 100.0) if net_revenue > 0 else 0.0

        # Free Cash Flow = Net Income + Depreciation (capex already accounted at t=0)
        fcf = net_income + depr
        discounted_fcf = fcf / ((1.0 + r) ** year)
        cum_cash += fcf

        cash_flows_for_irr.append(fcf)

        yearly_flows.append(YearCashFlow(
            year=year,
            units_sold=round(annual_units, 2),
            price_unit=round(current_price, 2),
            revenue=round(revenue, 2),
            shrinkage_loss=round(shrinkage_loss, 2),
            net_revenue=round(net_revenue, 2),
            variable_costs=round(var_costs, 2),
            gross_margin=round(gross_margin, 2),
            gross_margin_pct=round(gross_margin_pct, 2),
            fixed_costs=round(fixed_costs, 2),
            ebitda=round(ebitda, 2),
            depreciation=round(depr, 2),
            ebit=round(ebit, 2),
            taxes=round(taxes, 2),
            net_income=round(net_income, 2),
            net_margin_pct=round(net_margin_pct, 2),
            free_cash_flow=round(fcf, 2),
            discounted_cash_flow=round(discounted_fcf, 2),
            cumulative_cash_flow=round(cum_cash, 2)
        ))

    # Add Terminal Value to the final year to correctly evaluate business continuity (Gordon Growth Model)
    if years > 0 and r > 0:
        last_flow = yearly_flows[-1]
        # Conservative perpetual growth rate (max 2% or slightly below inflation/WACC)
        g = min(0.02, r - 0.02)
        if g < 0:
            g = 0.0
        
        # Terminal Value based on last year's free cash flow
        if last_flow.free_cash_flow > 0:
            tv_nominal = last_flow.free_cash_flow * (1.0 + g) / (r - g)
            # Cap Terminal Value to 5x EBITDA to avoid absurd valuations in small businesses
            max_tv = 5.0 * last_flow.ebitda
            tv_nominal = min(tv_nominal, max_tv)
        else:
            tv_nominal = 0.0

        tv_discounted = tv_nominal / ((1.0 + r) ** years)

        # Append TV to the last year's flow
        last_flow.terminal_value = round(tv_nominal, 2)
        last_flow.free_cash_flow = round(last_flow.free_cash_flow + tv_nominal, 2)
        last_flow.discounted_cash_flow = round(last_flow.discounted_cash_flow + tv_discounted, 2)
        last_flow.cumulative_cash_flow = round(last_flow.cumulative_cash_flow + tv_nominal, 2)
        
        # Add TV to the IRR array (the last cash flow is added directly to it)
        cash_flows_for_irr[-1] += tv_nominal

    return yearly_flows, cash_flows_for_irr

def calculate_paybacks(
    initial_investment: float,
    yearly_flows: List[YearCashFlow]
) -> Tuple[Optional[float], Optional[float]]:
    """
    Calcula Payback Simple y Payback Descontado en años.
    """
    # Payback Simple
    cum = 0.0
    simple_payback = None
    for i, flow in enumerate(yearly_flows):
        prev_cum = cum
        op_fcf = flow.free_cash_flow - flow.terminal_value
        cum += op_fcf
        if cum >= initial_investment:
            needed = initial_investment - prev_cum
            frac = needed / op_fcf if op_fcf > 0 else 0
            simple_payback = i + frac
            break

    # Discounted Payback
    cum_disc = 0.0
    disc_payback = None
    for i, flow in enumerate(yearly_flows):
        prev_cum_disc = cum_disc
        # To get the discounted operating FCF, subtract the discounted terminal value
        # But wait, terminal_value is nominal. So we need to calculate its discounted version.
        # Actually, since TV is added to the last flow, we can just subtract it from discounted_cash_flow if we know the discount rate.
        # Instead, let's calculate the fraction of operating fcf to total fcf.
        if flow.free_cash_flow > 0:
            ratio = (flow.free_cash_flow - flow.terminal_value) / flow.free_cash_flow
        else:
            ratio = 1.0
        op_disc_fcf = flow.discounted_cash_flow * ratio
        
        cum_disc += op_disc_fcf
        if cum_disc >= initial_investment:
            needed = initial_investment - prev_cum_disc
            frac = needed / op_disc_fcf if op_disc_fcf > 0 else 0
            disc_payback = i + frac
            break

    return simple_payback, disc_payback

def calculate_breakeven(inputs: FinancialInputs) -> BreakEvenMetrics:
    """
    Calcula las fórmulas de Punto de Equilibrio y Margen de Seguridad
    descontando mermas y pérdidas por robos / riesgos operativos.
    """
    p = inputs.monthly_price
    shrinkage_factor = max(0.0, 1.0 - (inputs.shrinkage_risk_loss_pct / 100.0))
    effective_price = p * shrinkage_factor
    cv_u = inputs.unit_variable_cost
    
    # Calculate monthly depreciation to include in fixed costs (Accounting Break-Even)
    monthly_depr = (inputs.initial_investment / inputs.depreciation_years) / 12.0 if inputs.depreciation_years > 0 else 0.0
    cf_m = inputs.monthly_fixed_costs + inputs.monthly_maintenance_cost + monthly_depr
    
    q_actual = inputs.monthly_units

    unit_cm = effective_price - cv_u
    cm_ratio = (unit_cm / p) if p > 0 else 0.0
    cm_ratio_pct = cm_ratio * 100.0

    if unit_cm > 0:
        be_units = cf_m / unit_cm
        be_revenue = be_units * p
    else:
        be_units = float('inf')
        be_revenue = float('inf')

    annual_be_revenue = be_revenue * 12.0

    current_monthly_rev = q_actual * p
    current_monthly_net_rev = q_actual * effective_price
    current_monthly_cost = cf_m + (cv_u * q_actual)
    current_monthly_profit = current_monthly_net_rev - current_monthly_cost

    if q_actual > 0 and be_units != float('inf'):
        margin_of_safety = ((q_actual - be_units) / q_actual) * 100.0
    else:
        margin_of_safety = -100.0

    return BreakEvenMetrics(
        unit_contribution_margin=round(unit_cm, 2),
        contribution_margin_ratio_pct=round(cm_ratio_pct, 2),
        monthly_breakeven_units=round(be_units, 2) if be_units != float('inf') else 999999.0,
        monthly_breakeven_revenue=round(be_revenue, 2) if be_revenue != float('inf') else 999999.0,
        annual_breakeven_revenue=round(annual_be_revenue, 2) if annual_be_revenue != float('inf') else 999999.0,
        margin_of_safety_pct=round(margin_of_safety, 2),
        current_monthly_revenue=round(current_monthly_rev, 2),
        current_monthly_profit=round(current_monthly_profit, 2)
    )

def build_scenario_summary(
    name: str,
    desc: str,
    inputs: FinancialInputs,
    sales_mult: float,
    var_mult: float,
    fixed_mult: float
) -> ScenarioSummary:
    flows, cf_irr = compute_yearly_flows(inputs, sales_mult, var_mult, fixed_mult)
    npv = sum(f.discounted_cash_flow for f in flows) - inputs.initial_investment
    irr = calculate_irr(cf_irr)
    irr_pct = round(irr * 100.0, 2) if irr is not None else None
    payback, _ = calculate_paybacks(inputs.initial_investment, flows)

    total_net = sum(f.net_income for f in flows)
    avg_annual_net = total_net / len(flows) if flows else 0.0
    roi_annual = (avg_annual_net / inputs.initial_investment) * 100.0 if inputs.initial_investment > 0 else 0.0

    return ScenarioSummary(
        name=name,
        description=desc,
        npv=round(npv, 2),
        irr_pct=irr_pct,
        payback_years=round(payback, 2) if payback is not None else None,
        total_5yr_net_profit=round(total_net, 2),
        roi_annual_avg_pct=round(roi_annual, 2)
    )

def analyze_financials(inputs: FinancialInputs) -> FinancialReport:
    """
    Función principal que ejecuta todas las evaluaciones cuantitativas de rentabilidad.
    """
    yearly_flows, cf_irr = compute_yearly_flows(inputs)
    pv_cash_flows = sum(f.discounted_cash_flow for f in yearly_flows)
    npv = pv_cash_flows - inputs.initial_investment

    irr = calculate_irr(cf_irr)
    irr_pct = round(irr * 100.0, 2) if irr is not None else None

    simple_pb, disc_pb = calculate_paybacks(inputs.initial_investment, yearly_flows)
    be_metrics = calculate_breakeven(inputs)

    bc_ratio = (pv_cash_flows / inputs.initial_investment) if inputs.initial_investment > 0 else 0.0

    total_net_profit = sum(f.net_income for f in yearly_flows)
    avg_net_annual = total_net_profit / len(yearly_flows) if yearly_flows else 0.0
    roi_avg_pct = (avg_net_annual / inputs.initial_investment) * 100.0 if inputs.initial_investment > 0 else 0.0

    # Scenarios
    scenarios = {
        "pessimistic": build_scenario_summary(
            "Pesimista",
            "Ventas -20%, Costos Variables +15%, Costos Fijos +10%",
            inputs, 0.80, 1.15, 1.10
        ),
        "base": build_scenario_summary(
            "Base / Esperado",
            "Condiciones estándar ingresadas",
            inputs, 1.0, 1.0, 1.0
        ),
        "optimistic": build_scenario_summary(
            "Optimista",
            "Ventas +20%, Costos Variables -10%, Costos Fijos -5%",
            inputs, 1.20, 0.90, 0.95
        )
    }

    # Determine Viability Indicator
    bullets = []
    if npv > 0 and (irr_pct is None or irr_pct > inputs.discount_rate_pct):
        viability_status = "Proyecto Altamente Viable y Rentable"
        viability_color = "emerald"
        bullets.append(f"El Valor Actual Neto (VAN) es positivo (${npv:,.2f}), generando valor económico superior a la tasa de descuento.")
        if irr_pct is not None:
            bullets.append(f"La TIR ({irr_pct}%) supera significativamente la tasa de corte exigida ({inputs.discount_rate_pct}%).")
        else:
            bullets.append("La rentabilidad es tan alta que la TIR supera el límite calculable (o no hay flujos negativos).")
    elif npv > 0 and (irr_pct is not None and irr_pct >= inputs.discount_rate_pct * 0.9):
        viability_status = "Proyecto Viable con Margen Moderado"
        viability_color = "amber"
        bullets.append(f"El VAN es positivo (${npv:,.2f}), pero el margen sobre la tasa de oportunidad es estrecho.")
    elif npv <= 0 and (irr_pct is None or irr_pct > 0) and sum(f.free_cash_flow for f in yearly_flows) > inputs.initial_investment:
        viability_status = "Viabilidad Comprometida / Requiere Reestructuración"
        viability_color = "orange"
        bullets.append(f"El VAN es negativo (${npv:,.2f}), indicando que el retorno no compensa el costo de capital ({inputs.discount_rate_pct}%).")
    else:
        viability_status = "Proyecto No Viable Económicamente"
        viability_color = "red"
        bullets.append("Los flujos proyectados no cubren la inversión inicial ni los costos operativos de forma suficiente.")

    if be_metrics.margin_of_safety_pct > 30:
        bullets.append(f"Excelente Margen de Seguridad ({be_metrics.margin_of_safety_pct}%): las ventas pueden caer notablemente antes de entrar en pérdidas.")
    elif be_metrics.margin_of_safety_pct > 0:
        bullets.append(f"Margen de Seguridad ajustado ({be_metrics.margin_of_safety_pct}%): se requiere mantener un control estricto del volumen de venta.")
    else:
        bullets.append(f"Alerta: Las ventas estimadas están por debajo del Punto de Equilibrio mensual ({be_metrics.monthly_breakeven_units:,.0f} unidades).")

    if simple_pb is not None:
        bullets.append(f"El período de recuperación estimado (Payback) es de aproximadamente {simple_pb:.1f} años.")

    rec_equipment_reserve = (inputs.initial_investment / inputs.depreciation_years) / 12.0 if inputs.depreciation_years > 0 else 0.0

    if inputs.monthly_maintenance_cost > 0:
        bullets.append(f"Reserva para Equipo: Se presupuestaron ${inputs.monthly_maintenance_cost:,.2f}/mes para reparaciones y reemplazo (Fondo mínimo sugerido: ${rec_equipment_reserve:,.2f}/mes).")
    elif rec_equipment_reserve > 0:
        bullets.append(f"💡 Fondo Sugerido de Equipo: Para renovar tu equipo tras {inputs.depreciation_years} años, se sugiere apartar ${rec_equipment_reserve:,.2f}/mes en una cuenta de reserva.")

    # Bank Opportunity Cost & Shrinkage Calculations
    shrinkage_annual_loss = (inputs.monthly_units * 12.0 * inputs.monthly_price) * (inputs.shrinkage_risk_loss_pct / 100.0)
    shrinkage_monthly_loss = shrinkage_annual_loss / 12.0

    bank_rate = inputs.bank_risk_free_rate_pct
    bank_passive_annual = inputs.initial_investment * (bank_rate / 100.0)
    bank_passive_monthly = bank_passive_annual / 12.0
    business_net_annual = avg_net_annual
    business_net_monthly = avg_net_annual / 12.0
    annual_diff = business_net_annual - bank_passive_annual
    monthly_diff = business_net_monthly - bank_passive_monthly
    risk_premium = roi_avg_pct - bank_rate

    if inputs.initial_investment > 0 and business_net_annual < bank_passive_annual:
        bank_verdict = f"¡ALERTA! El banco/CETES ({bank_rate}%) te pagaría ${bank_passive_annual:,.2f}/año (${bank_passive_monthly:,.2f}/mes) sin riesgos ni trabajo. El negocio deja menos que una inversión pasiva."
        bank_verdict_color = "red"
        viability_status = "Inviable: El Banco / CETES genera más ganancias sin riesgo"
        viability_color = "red"
        bullets.insert(0, f"❌ Alerta Crítica de Costo de Oportunidad: Invirtiendo tus ${inputs.initial_investment:,.2f} en el banco/CETES al {bank_rate}% ganarías ${bank_passive_annual:,.2f}/año (${bank_passive_monthly:,.2f}/mes) sin esfuerzo ni riesgos. Tu negocio generaría ${business_net_annual:,.2f}/año. ¡No conviene emprender!")
    elif inputs.initial_investment > 0 and risk_premium < 5.0:
        bank_verdict = f"Premio por riesgo muy bajo (+{risk_premium:.1f}% sobre banco). Generas ${annual_diff:,.2f} extras al año, lo cual difícilmente compensa el riesgo operativo."
        bank_verdict_color = "amber"
        bullets.append(f"⚖️ Comparativa Bancaria: El negocio supera al banco por ${annual_diff:,.2f}/año (+${monthly_diff:,.2f}/mes), pero el premio por riesgo (+{risk_premium:.1f}%) es muy bajo para el trabajo requerido.")
    elif inputs.initial_investment > 0:
        bank_verdict = f"Premio por riesgo atractivo (+{risk_premium:.1f}% sobre banco). El negocio genera ${annual_diff:,.2f} adicionales al año frente a dejar el dinero en el banco."
        bank_verdict_color = "emerald"
        bullets.append(f"🏦 Premio sobre Inversión Bancaria: El negocio genera ${annual_diff:,.2f}/año extras (+${monthly_diff:,.2f}/mes) por encima de una inversión bancaria pasiva al {bank_rate}%.")
    else:
        bank_verdict = "Sin inversión inicial registrada para calcular comparativa bancaria."
        bank_verdict_color = "slate"

    if inputs.shrinkage_risk_loss_pct > 0:
        bullets.append(f"🛡️ Descuento por Mermas y Riesgos: Se dedujeron ${shrinkage_monthly_loss:,.2f}/mes (${shrinkage_annual_loss:,.2f}/año, {inputs.shrinkage_risk_loss_pct}%) de las ventas por merma, robos y riesgos operativos.")

    bank_comparison = OpportunityCostComparison(
        bank_risk_free_rate_pct=round(bank_rate, 2),
        bank_passive_annual_income=round(bank_passive_annual, 2),
        bank_passive_monthly_income=round(bank_passive_monthly, 2),
        business_net_annual_income=round(business_net_annual, 2),
        business_net_monthly_income=round(business_net_monthly, 2),
        annual_difference=round(annual_diff, 2),
        monthly_difference=round(monthly_diff, 2),
        risk_premium_pct=round(risk_premium, 2),
        verdict=bank_verdict,
        verdict_color=bank_verdict_color
    )

    return FinancialReport(
        npv=round(npv, 2),
        irr_pct=irr_pct,
        payback_years=round(simple_pb, 2) if simple_pb is not None else None,
        discounted_payback_years=round(disc_pb, 2) if disc_pb is not None else None,
        benefit_cost_ratio=round(bc_ratio, 2),
        roi_annual_avg_pct=round(roi_avg_pct, 2),
        initial_investment=round(inputs.initial_investment, 2),
        discount_rate_pct=inputs.discount_rate_pct,
        recommended_equipment_reserve=round(rec_equipment_reserve, 2),
        shrinkage_annual_loss=round(shrinkage_annual_loss, 2),
        shrinkage_monthly_loss=round(shrinkage_monthly_loss, 2),
        bank_comparison=bank_comparison,
        break_even=be_metrics,
        yearly_cash_flows=yearly_flows,
        scenarios=scenarios,
        viability_status=viability_status,
        viability_color=viability_color,
        summary_bullets=bullets
    )
