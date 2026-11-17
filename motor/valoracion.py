"""Valorización: DCF en tres escenarios y DCF inverso. Aritmética pura, sin opiniones.

Modelo de 10 años: crecimiento g1 los años 1-5, luego baja en línea recta hasta el
crecimiento perpetuo g_t en el año 10. Valor terminal de Gordon. Todo en dólares nominales.
"""


def flujos(fcf0, g1, g_t, anios=10):
    salida, f = [], fcf0
    for a in range(1, anios + 1):
        g = g1 if a <= 5 else g1 + (g_t - g1) * (a - 5) / (anios - 5)
        f *= 1 + g
        salida.append(f)
    return salida


def dcf(fcf0, g1, g_t, r, deuda_neta, acciones, anios=10):
    """Valor por acción. fcf0 = flujo de caja libre normalizado de partida."""
    if r <= g_t or not acciones:
        return None
    fl = flujos(fcf0, g1, g_t, anios)
    vp = sum(f / (1 + r) ** (i + 1) for i, f in enumerate(fl))
    terminal = fl[-1] * (1 + g_t) / (r - g_t)
    vp_terminal = terminal / (1 + r) ** anios
    empresa = vp + vp_terminal
    capital = empresa - deuda_neta
    return {"valor_accion": capital / acciones, "valor_empresa": empresa, "valor_capital": capital,
            "peso_terminal": (vp_terminal / empresa) if empresa else None}


def crecimiento_implicito(precio, fcf0, g_t, r, deuda_neta, acciones):
    """DCF inverso: ¿qué crecimiento anual (años 1-5) justifica el precio de hoy?"""
    if fcf0 is None or fcf0 <= 0 or not acciones:
        return None
    lo, hi = -0.30, 0.80
    f = lambda g: dcf(fcf0, g, g_t, r, deuda_neta, acciones)["valor_accion"] - precio
    if f(lo) > 0:
        return lo
    if f(hi) < 0:
        return hi
    for _ in range(80):
        m = (lo + hi) / 2
        if f(m) > 0:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


_WACC = None


def tabla_wacc():
    global _WACC
    if _WACC is None:
        import json, os
        ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos", "wacc.json")
        _WACC = json.load(open(ruta)) if os.path.exists(ruta) else {}
    return _WACC


def prima_tamano(cap_bursatil):
    W = tabla_wacc().get("prima_tamano", {"mediana": 0.01, "pequena": 0.02})
    if cap_bursatil is None or cap_bursatil >= 10e9:
        return 0.0
    return W["mediana"] if cap_bursatil >= 2e9 else W["pequena"]


def tasa_descuento(cap_bursatil, sector=None, costo="wacc", extra=0.0):
    """Retorno exigido: costo de capital del sector (WACC, o Ke para métodos de patrimonio)
    + prima por tamaño + prima país si corresponde. Sin tabla, usa 8.5% como referencia."""
    sec = tabla_wacc().get("sectores", {}).get(sector or "Otros") or tabla_wacc().get("sectores", {}).get("Otros")
    base = sec[costo] if sec else 0.085
    return base + prima_tamano(cap_bursatil) + extra


def nivel_riesgo(cap_bursatil):
    if cap_bursatil is None:
        return "Sin dato"
    if cap_bursatil >= 200e9:
        return "Mega (más de $200 mil M)"
    if cap_bursatil >= 10e9:
        return "Grande ($10-200 mil M)"
    if cap_bursatil >= 2e9:
        return "Mediana ($2-10 mil M) · riesgo mayor"
    return "Pequeña (menos de $2 mil M) · riesgo alto"


def limitar(x, lo, hi):
    return max(lo, min(hi, x))


def escenarios(crec_hist, margen_norm, ingresos_ttm, deuda_neta, acciones, cap_bursatil, g_t=0.025, sector=None, extra=0.0):
    """Supuestos por defecto de los tres escenarios. Son puntos de partida editables,
    derivados mecánicamente de la historia de la empresa; no son pronósticos.
    El retorno exigido base es el WACC del sector (+ prima por tamaño y país)."""
    r = tasa_descuento(cap_bursatil, sector, "wacc", extra)
    h = crec_hist if crec_hist is not None else 0.04
    defs = {
        "pesimista": {"g1": limitar(0.35 * h, 0.0, 0.07), "margen": margen_norm * 0.85, "r": r + 0.01},
        "base": {"g1": limitar(0.75 * h, 0.02, 0.14), "margen": margen_norm, "r": r},
        "optimista": {"g1": limitar(1.10 * h, 0.04, 0.20), "margen": margen_norm * 1.10, "r": r - 0.005},
    }
    salida = {}
    for nombre, s in defs.items():
        fcf0 = ingresos_ttm * s["margen"]
        res = dcf(fcf0, s["g1"], g_t, s["r"], deuda_neta, acciones)
        salida[nombre] = {**s, "g_t": g_t, "fcf0": fcf0, **(res or {})}
    return salida


def escenarios_financiera(valor_libro_accion, roe_norm, cap_bursatil, sector="Financiero", extra=0.0):
    """Bancos y aseguradoras: precio justo / valor libro = (ROE − g) / (Ke − g).
    Una financiera que gana sobre su patrimonio más de lo que exige el accionista vale más que su valor en libros."""
    ke = tasa_descuento(cap_bursatil, sector, "ke", extra)
    roe = limitar(roe_norm, 0.0, 0.35)
    defs = {"pesimista": {"roe": roe * 0.85, "g": 0.015, "r": ke + 0.01},
            "base": {"roe": roe, "g": 0.025, "r": ke},
            "optimista": {"roe": roe * 1.10, "g": 0.03, "r": ke - 0.005}}
    for d in defs.values():
        pb = (d["roe"] - d["g"]) / (d["r"] - d["g"]) if d["roe"] > d["g"] else d["roe"] / d["r"]
        d["pb_justo"] = pb
        d["valor_accion"] = valor_libro_accion * pb
    return defs


def escenarios_reit(ffo_accion, cap_bursatil, sector="Inmobiliario", extra=0.0):
    """Inmobiliarias (REIT): la caja repartible se aproxima con el FFO (utilidad + depreciación)
    menos 15% de inversión de mantención; se valora como una renta que crece (Gordon)."""
    ke = tasa_descuento(cap_bursatil, sector, "ke", extra)
    affo = ffo_accion * 0.85
    defs = {"pesimista": {"g": 0.01, "r": ke + 0.01}, "base": {"g": 0.02, "r": ke}, "optimista": {"g": 0.03, "r": ke - 0.005}}
    for d in defs.values():
        d["affo"] = affo
        d["valor_accion"] = affo * (1 + d["g"]) / (d["r"] - d["g"]) if d["r"] > d["g"] else None
    return defs
