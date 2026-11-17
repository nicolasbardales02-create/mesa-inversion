"""Tasas base (base rates, método Mauboussin).

Pregunta: el precio de hoy asume que la empresa crecerá X% al año por 10 años.
¿Cuántas empresas de su mismo tamaño lo lograron en la historia?

- Fuente: ventas anuales de TODAS las empresas que reportan a la SEC (API frames, XBRL), 2011-2025.
- Ventanas: 10 años (inicio 2011..2015) y 5 años (inicio 2011..2020), agrupadas.
- Se clasifica por tamaño de ventas al inicio, porque crecer rápido es más difícil siendo grande.
- Sesgo de supervivencia: solo cuentan las empresas que siguen reportando al final de la ventana
  (las quebradas o compradas no están). Eso hace que las tasas base sean OPTIMISTAS:
  si aun así la probabilidad sale baja, la conclusión es robusta.
- Se usa el crecimiento de ventas como aproximación del crecimiento del flujo de caja
  (el DCF mantiene el margen constante).
"""
import bisect, json, os, sys, datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
import datos, fundamentales as F, valoracion as V
from screener import _flujo

TRAMOS = [("< $500 M", 0, 5e8), ("$0.5 – 2 mil M", 5e8, 2e9), ("$2 – 10 mil M", 2e9, 1e10),
          ("$10 – 50 mil M", 1e10, 5e10), ("> $50 mil M", 5e10, float("inf"))]
MINIMO = 5e7          # ventas mínimas al inicio (evita empresas sin negocio aún)
RUTA = os.path.join(datos.RAIZ, "datos", "tasas_base.json")


def tramo(ventas):
    for i, (_, lo, hi) in enumerate(TRAMOS):
        if lo <= ventas < hi:
            return i
    return None


def construir(log=print):
    ventas = {a: _flujo(F.INGRESOS, a) for a in range(2011, 2026)}
    log("ventas anuales 2011-2025 descargadas")
    salida = {"generado": dt.date.today().isoformat(), "tramos": [t[0] for t in TRAMOS], "horizontes": {}}
    for h, inicios in ((10, range(2011, 2016)), (5, range(2011, 2021))):
        muestras = [[] for _ in TRAMOS]
        sin_final = [0] * len(TRAMOS)
        for a0 in inicios:
            v0, v1 = ventas[a0], ventas[a0 + h]
            for cik, x0 in v0.items():
                if x0 is None or x0 < MINIMO:
                    continue
                i = tramo(x0)
                x1 = v1.get(cik)
                if x1 is None:
                    sin_final[i] += 1; continue
                if x1 <= 0:
                    continue
                muestras[i].append((x1 / x0) ** (1 / h) - 1)
        tabla = []
        for i, m in enumerate(muestras):
            m.sort()
            pct = [round(m[min(len(m) - 1, int(len(m) * p / 100))], 4) for p in range(1, 100)] if m else []
            tabla.append({"n": len(m), "sin_final": sin_final[i], "pct": pct,
                          "mediana": pct[49] if pct else None})
        salida["horizontes"][str(h)] = tabla
        log(f"horizonte {h} años: " + ", ".join(f"{TRAMOS[i][0]} n={t['n']} mediana={t['mediana']}" for i, t in enumerate(tabla)))
    json.dump(salida, open(RUTA, "w"), ensure_ascii=False, separators=(",", ":"))
    return salida


def prob_lograr(cagr, ventas, tb, h=10):
    """Fracción de empresas del mismo tamaño que crecieron al menos `cagr` anual durante h años."""
    i = tramo(ventas) if ventas else None
    if i is None or cagr is None:
        return None
    pct = tb["horizontes"][str(h)][i]["pct"]
    if not pct:
        return None
    k = bisect.bisect_left(pct, cagr)          # percentiles 1..99 por debajo del valor
    return round(max(0.005, min(0.995, 1 - (k + 0.5) / 100)), 3)


def implicito(f):
    """Crecimiento años 1-5 que justifica el precio (DCF inverso) y su equivalente anual a 10 años."""
    if f.get("met") != "DCF" or not f.get("p") or not f.get("ing") or not f.get("mn") or f["mn"] <= 0 \
            or not f.get("acc") or not f.get("wacc"):
        return None, None
    fcf0 = f["ing"] * f["mn"]
    g = V.crecimiento_implicito(f["p"], fcf0, 0.025, f["wacc"], f.get("dn") or 0.0, f["acc"])
    if g is None:
        return None, None
    g10 = (V.flujos(fcf0, g, 0.025)[-1] / fcf0) ** (1 / 10) - 1
    return g, g10


def anotar(filas, tb=None):
    tb = tb or (json.load(open(RUTA)) if os.path.exists(RUTA) else None)
    if not tb:
        return
    for f in filas:
        g, g10 = implicito(f)
        f["gi"], f["gi10"] = g, g10
        f["pbr"] = prob_lograr(g10, f.get("ing"), tb) if g10 is not None else None


def anotar_archivo(log=print):
    """Agrega las columnas al universo.json ya construido (sin reconstruirlo)."""
    ruta = os.path.join(datos.RAIZ, "datos", "universo.json")
    U = json.load(open(ruta))
    cols = U["cols"]
    filas = [dict(zip(cols, r)) for r in U["filas"]]
    anotar(filas)
    for c in ("gi", "gi10", "pbr"):
        if c not in cols:
            cols.append(c)
    red = {"gi": 4, "gi10": 4, "pbr": 3}
    U["filas"] = [[(round(f.get(c), red[c]) if c in red and isinstance(f.get(c), float) else f.get(c)) for c in cols] for f in filas]
    json.dump(U, open(ruta, "w"), separators=(",", ":"), ensure_ascii=False)
    log(f"universo anotado: {sum(1 for f in filas if f.get('pbr') is not None)} empresas con probabilidad base")


if __name__ == "__main__":
    construir()
    anotar_archivo()
