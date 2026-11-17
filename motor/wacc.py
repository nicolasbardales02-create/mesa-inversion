"""Costo de capital por sector (WACC), calculado con datos de mercado.

  Ke  = tasa libre de riesgo + beta del sector × prima de riesgo del mercado
  Kd  = tasa libre de riesgo + diferencial de crédito
  WACC = E/(D+E)·Ke + D/(D+E)·Kd·(1 − impuesto)

- Tasa libre de riesgo: bono del Tesoro a 10 años (FRED, serie DGS10), último dato.
- Beta del sector: beta semanal a 5 años del ETF sectorial SPDR contra el S&P 500 (SPY), ajustada
  hacia 1 (0.67·beta + 0.33) como hacen los proveedores de datos, porque las betas tienden a revertir.
- Peso de la deuda: mediana de deuda neta / (deuda neta + capitalización) de las empresas del sector.
- Prima de riesgo del mercado y diferencial de crédito: supuestos explícitos (editables abajo).
A las empresas medianas y pequeñas se les suma una prima por tamaño al usarlo.
"""
import json, os, sys, math, statistics, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos

PRIMA_MERCADO = 0.045     # prima de riesgo de las acciones de EE.UU. (supuesto)
DIFERENCIAL = 0.015       # diferencial de crédito de la deuda corporativa (supuesto)
IMPUESTO = 0.21
PRIMA_TAMANO = {"mediana": 0.01, "pequena": 0.02}
ETF = {"Tecnología": "XLK", "Salud": "XLV", "Financiero": "XLF", "Energía": "XLE", "Servicios públicos": "XLU",
       "Consumo básico": "XLP", "Consumo discrecional": "XLY", "Industrial": "XLI", "Materiales": "XLB",
       "Inmobiliario": "XLRE", "Comunicación": "XLC", "Otros": "SPY"}


def tasa_libre():
    t = datos.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10", ttl_horas=20)
    filas = [l.split(",") for l in t.strip().splitlines()[1:]]
    for f, v in reversed(filas):
        try:
            return float(v) / 100, f
        except ValueError:
            continue
    raise RuntimeError("sin dato de DGS10")


def _semanales(sim, fechas=None):
    """Retornos semanales (log) en un calendario común: el de SPY cada 5 ruedas."""
    p = datos.precios(sim, "10y", "1d", ttl_horas=24)
    serie = dict(zip(p["fechas"], p["cierre_aj"]))
    if fechas is None:
        f = p["fechas"]; fechas = [f[i] for i in range(len(f) - 1, -1, -5)][::-1][-261:]
    fs = [d for d in fechas if d in serie]
    return {fs[i]: math.log(serie[fs[i]] / serie[fs[i - 1]]) for i in range(1, len(fs))}, fechas


def beta(sim, mercado, fechas):
    r, _ = _semanales(sim, fechas)
    com = [d for d in r if d in mercado]
    x = [mercado[d] for d in com]; y = [r[d] for d in com]
    mx, my = sum(x) / len(x), sum(y) / len(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y)); var = sum((a - mx) ** 2 for a in x)
    return cov / var, len(com)


def construir():
    rf, f_rf = tasa_libre()
    mercado, fechas = _semanales("SPY")
    pesos = {}
    ruta_u = os.path.join(datos.RAIZ, "datos", "universo.json")
    if os.path.exists(ruta_u):
        U = json.load(open(ruta_u)); C = {c: i for i, c in enumerate(U["cols"])}
        por = {}
        for r in U["filas"]:
            cap, dn = r[C["cap"]], r[C["dn"]]
            if cap and dn is not None and cap > 0:
                d = max(dn, 0.0); por.setdefault(r[C["s"]], []).append(d / (d + cap))
        pesos = {s: statistics.median(v) for s, v in por.items() if len(v) >= 10}
    sect = {}
    for s, etf in ETF.items():
        b_hist, n = (1.0, 0) if etf == "SPY" else beta(etf, mercado, fechas)
        b = 0.67 * b_hist + 0.33          # beta ajustada (Blume): las betas tienden a volver a 1
        ke = rf + b * PRIMA_MERCADO
        wd = 0.0 if s in ("Financiero",) else min(pesos.get(s, 0.15), 0.6)
        kd = rf + DIFERENCIAL
        w = (1 - wd) * ke + wd * kd * (1 - IMPUESTO)
        sect[s] = {"etf": etf, "beta_hist": round(b_hist, 3), "beta": round(b, 3), "semanas": n, "ke": round(ke, 4), "peso_deuda": round(wd, 3),
                   "kd": round(kd, 4), "wacc": round(max(w, rf + 0.02), 4)}
    return {"generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "tasa_libre": round(rf, 4), "fecha_tasa": f_rf, "prima_mercado": PRIMA_MERCADO, "diferencial": DIFERENCIAL,
            "impuesto": IMPUESTO, "prima_tamano": PRIMA_TAMANO, "sectores": sect,
            "metodo": "Ke = tasa libre + beta ajustada × prima de mercado; WACC pondera Ke y el costo de la deuda después de impuestos con el peso mediano de la deuda del sector."}


if __name__ == "__main__":
    W = construir()
    json.dump(W, open(os.path.join(datos.RAIZ, "datos", "wacc.json"), "w"), ensure_ascii=False, indent=1)
    print("tasa libre", W["tasa_libre"], W["fecha_tasa"])
    for s, x in sorted(W["sectores"].items(), key=lambda kv: kv[1]["wacc"]):
        print(f"  {s:22} beta {x['beta']:.2f}  Ke {x['ke']*100:.2f}%  deuda {x['peso_deuda']*100:4.1f}%  WACC {x['wacc']*100:.2f}%")
