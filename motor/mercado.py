"""Termómetro del mercado: lo que necesitas saber para leer una caída del S&P 500.

1. Prima de riesgo implícita (método de Damodaran, versión de caja devuelta):
   ¿qué retorno anual espera el mercado, dado el precio de hoy y la caja que las empresas devuelven?
   - Caja devuelta = dividendos + recompras del último ejercicio de las 500 empresas más grandes de EE.UU. de la tabla
     (aproximación del S&P 500), sobre su capitalización total.
   - Crece 5 años al ritmo `g` y después al de la tasa libre de riesgo (bono a 10 años).
   - Se busca la tasa r que iguala ese flujo con la capitalización: prima implícita = r − tasa libre.
   - g: el punto medio entre el crecimiento anual de la caja devuelta y el de la utilidad agregada en los últimos
     10 años, acotado entre 3% y 10%. Es el supuesto que más mueve el resultado: se muestra el rango completo.
   - Damodaran usa el crecimiento que esperan los analistas; aquí se usa la historia, que es verificable.
2. Señales de ciclo (FRED, Reserva Federal de St. Louis):
   - Curva de tasas: 10 años menos 3 meses (T10Y3M). Invertida (< 0) precedió a las recesiones de EE.UU. desde 1970.
   - Diferencial de los bonos de alto riesgo (BAMLH0A0HYM2): sube cuando el mercado teme quiebras.
   - Regla de Sahm (SAHMREALTIME): ≥ 0.5 puntos indicó, en tiempo real, el inicio de cada recesión desde 1970.
Uso: python3 motor/mercado.py
"""
import json, os, sys, statistics, datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
import datos, fundamentales as F
from screener import _flujo, ALIAS_CIK, ANIO

RUTA = os.path.join(datos.RAIZ, "datos", "mercado.json")


def fred(serie, anios=40):
    t = datos.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={serie}", ttl_horas=20)
    out = []
    desde = (dt.date.today() - dt.timedelta(days=365 * anios)).isoformat()
    for linea in t.strip().splitlines()[1:]:
        f, v = linea.split(",")[:2]
        try:
            if f >= desde:
                out.append((f, float(v)))
        except ValueError:
            continue
    return out


def _resumen(serie, semanal=True):
    """Último valor, hace un año, percentil histórico y serie semanal de 10 años para graficar."""
    f, v = serie[-1]
    hace = [x for x in serie if x[0] <= (dt.date.fromisoformat(f) - dt.timedelta(days=365)).isoformat()]
    vals = sorted(x[1] for x in serie)
    pctl = sum(1 for x in vals if x <= v) / len(vals)
    corte = (dt.date.fromisoformat(f) - dt.timedelta(days=3653)).isoformat()
    s10 = [x for x in serie if x[0] >= corte]
    if semanal and len(s10) > 600:
        s10 = s10[::5]
    return {"valor": v, "fecha": f, "hace_1a": hace[-1][1] if hace else None, "percentil": round(pctl, 3),
            "desde": serie[0][0], "serie": [[a, round(b, 3)] for a, b in s10]}


def valor_presente(cash, g, rf, r, n=5):
    flujos = [cash * (1 + g) ** t for t in range(1, n + 1)]
    v = sum(c / (1 + r) ** t for t, c in enumerate(flujos, 1))
    return v + flujos[-1] * (1 + rf) / (r - rf) / (1 + r) ** n


def prima_implicita(cash, cap, g, rf, n=5):
    """Tasa r que iguala: cap = Σ cash(1+g)^t/(1+r)^t (t=1..n) + valor terminal con crecimiento rf."""
    vp = lambda r: valor_presente(cash, g, rf, r, n)
    lo, hi = rf + 1e-4, 0.5
    for _ in range(100):
        m = (lo + hi) / 2
        if vp(m) > cap:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2 - rf


def construir(log=print):
    U = json.load(open(os.path.join(datos.RAIZ, "datos", "universo.json")))
    filas = [dict(zip(U["cols"], r)) for r in U["filas"]]
    cik = {}
    for t in datos.tickers_sec():
        cik.setdefault(t["ticker"], ALIAS_CIK.get(t["cik"], t["cik"]))
    top = sorted([f for f in filas if not f.get("ext") and f.get("cap") and f["t"] in cik], key=lambda f: -f["cap"])[:500]
    capm = {cik[f["t"]]: f["cap"] for f in top}

    def suma(etq, anio, tope=None):
        m = _flujo(etq, anio); tot = 0.0
        for c, v in m.items():
            if c in capm and v and (tope is None or abs(v) <= tope * capm[c]):   # descarta errores de unidades
                tot += v
        return tot
    cap = sum(capm.values())
    caja = {a: suma(F.DIVID, a, .3) + suma(F.RECOMPRA, a, .3) for a in (ANIO, ANIO - 10)}
    util = {a: suma(F.UTIL_NETA[:1], a, .5) for a in (ANIO, ANIO - 10)}
    g_caja = (caja[ANIO] / caja[ANIO - 10]) ** .1 - 1
    g_util = (util[ANIO] / util[ANIO - 10]) ** .1 - 1
    g = max(.03, min(.10, (g_caja + g_util) / 2))
    rf_serie = fred("DGS10")
    rf = rf_serie[-1][1] / 100
    erp = prima_implicita(caja[ANIO], cap, g, rf)
    sens = {f"{x:.0%}": round(prima_implicita(caja[ANIO], cap, x, rf), 4) for x in (.05, .07, .10)}
    rango = sorted([prima_implicita(caja[ANIO], cap, max(.03, min(.10, x)), rf) for x in (g_caja, g_util)])
    log(f"caja devuelta {caja[ANIO] / 1e9:.0f} mil M sobre {cap / 1e12:.1f} billones = {caja[ANIO] / cap:.2%}; g={g:.2%} (caja {g_caja:.2%}, utilidad {g_util:.2%}); rf={rf:.2%}; prima implícita {erp:.2%}")
    M = {"generado": dt.datetime.now().isoformat(timespec="minutes"),
         "prima": {"valor": round(erp, 4), "tasa_libre": rf, "fecha_tasa": rf_serie[-1][0], "rendimiento_caja": round(caja[ANIO] / cap, 4),
                   "pe": round(cap / util[ANIO], 1) if util[ANIO] > 0 else None, "g": round(g, 4), "g_caja": round(g_caja, 4),
                   "g_utilidad": round(g_util, 4), "empresas": len(top), "anio": ANIO, "sensibilidad": sens, "rango": [round(x, 4) for x in rango],
                   "retorno_esperado": round(erp + rf, 4),
                   "prima_sistema": 0.045, "nivel_a_prima_sistema": round(valor_presente(caja[ANIO], g, rf, rf + 0.045) / cap - 1, 4), "referencia": {"fuente": "Damodaran, 1 oct 2026", "valor": 0.042,
                   "url": "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/home.htm"}}}
    S = {}
    for clave, serie in (("curva", "T10Y3M"), ("credito", "BAMLH0A0HYM2"), ("sahm", "SAHMREALTIME"), ("tasa10", "DGS10")):
        try:
            S[clave] = _resumen(fred(serie))
        except Exception as e:
            log(f"{serie}: {e}")
    M.update(S)
    json.dump(M, open(RUTA, "w"), ensure_ascii=False, separators=(",", ":"))
    log("MERCADO TERMINADO")
    return M


if __name__ == "__main__":
    construir()
