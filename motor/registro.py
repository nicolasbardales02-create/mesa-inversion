"""Registro de veredictos: ¿acierta el sistema?

Cada conclusión investigada y cada lista automática se congela con su fecha. Después se mide cuánto rindió
cada acción frente al S&P 500 (SPY) en el MISMO periodo, con precios ajustados por dividendos y divisiones.

- Veredictos: una entrada por cada versión de investigacion/<T>.json (ticker + fecha). Precio de partida =
  cierre ajustado del día de la conclusión.
- Listas automáticas (una foto por semana, como máximo):
    · "filtro": las 20 de mayor puntaje entre las que pasan el filtro de calidad.
    · "alcanzables": pasan el filtro, la tasa base dice que lo que asume el precio es alcanzable (≥50%)
      y no tienen banderas rojas (hasta 30, por puntaje).
    · "directivos": empresas con compras de directivos en grupo (radar), hasta 30.
    · "candidatas": las 30 de mayor puntaje del veredicto cuantitativo.
    · "ick": las 30 de mayor puntaje ick (baratas y rechazadas).
    · "revisadas": las que la revisión cualitativa confirmó (y cuyo rechazo no parece de fondo).
  Cada foto se mide como una canasta con el mismo peso en cada acción.

El archivo es acumulativo: NUNCA se borra una entrada. Uso: python3 motor/registro.py
"""
import bisect, glob, json, os, sys, datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
import datos

RUTA = os.path.join(datos.RAIZ, "datos", "registro.json")
INICIO = "2026-11-13"


def _serie(t, cache):
    """Fechas y cierres ajustados diarios de 2 años."""
    if t not in cache:
        try:
            p = datos.precios(t.replace(".", "-"), "2y", "1d", ttl_horas=20)
            cache[t] = (p["fechas"], p["cierre_aj"]) if p and p.get("cierre_aj") else None
        except Exception:
            cache[t] = None
    return cache[t]


def _desde(serie, fecha):
    """Retorno desde el cierre del día `fecha` (o el hábil anterior) hasta el último cierre."""
    if not serie:
        return None, None
    f, c = serie
    i = bisect.bisect_right(f, fecha) - 1
    if i < 0 or not c[i] or not c[-1]:
        return None, None
    return c[-1] / c[i] - 1, f[-1]


def construir(log=print):
    R = json.load(open(RUTA)) if os.path.exists(RUTA) else {"inicio": INICIO, "veredictos": [], "canastas": []}
    hoy = dt.date.today().isoformat()

    # ---- 1. nuevas versiones de conclusiones
    ya = {(v["ticker"], v["fecha"]) for v in R["veredictos"]}
    for ruta in sorted(glob.glob(os.path.join(datos.RAIZ, "investigacion", "*.json"))):
        d = json.load(open(ruta)); t = os.path.basename(ruta)[:-5]
        if (t, d["fecha"]) in ya or not d.get("tono"):
            continue
        R["veredictos"].append({"ticker": t, "fecha": d["fecha"], "tono": d["tono"], "etiqueta": d.get("etiqueta"),
                                "postura": (d.get("conclusion") or {}).get("postura")})
        log(f"veredicto registrado: {t} {d['fecha']} {d['tono']}")

    # ---- 2. fotos semanales de las listas automáticas
    U = json.load(open(os.path.join(datos.RAIZ, "datos", "universo.json")))
    F = [dict(zip(U["cols"], r)) for r in U["filas"]]
    pasan = sorted([f for f in F if f.get("e") == 2 and f.get("p")], key=lambda f: -(f.get("pts") or 0))
    listas = {"filtro": [f["t"] for f in pasan[:20]],
              "alcanzables": [f["t"] for f in pasan if f.get("pbr") is not None and f["pbr"] >= .5 and f.get("rojas") == ""][:30]}
    # embudo: veredicto cuantitativo, ick, y las que además confirmó la revisión cualitativa
    if any(f.get("vq") for f in F):
        listas["candidatas"] = [f["t"] for f in sorted(F, key=lambda f: -(f.get("vqp") or -99)) if f.get("vq") == "candidata" and f.get("p")][:30]
        listas["ick"] = [f["t"] for f in sorted(F, key=lambda f: -(f["ick"] if f.get("ick") is not None else -99)) if f.get("ick") is not None and f.get("p")][:30]
    rv = os.path.join(datos.RAIZ, "datos", "revisiones.json")
    if os.path.exists(rv):
        items = json.load(open(rv)).get("items", {})
        listas["revisadas"] = [t for t, x in items.items() if x.get("senal") == "confirma" and x.get("rechazo") != "permanente"][:30]
    rr = os.path.join(datos.RAIZ, "datos", "radar.json")
    if os.path.exists(rr):
        listas["directivos"] = [x["ticker"] for x in json.load(open(rr)).get("compras_directivos", []) if x.get("ticker") and x.get("precio")][:30]
    for nombre, tks in listas.items():
        previas = [c["fecha"] for c in R["canastas"] if c["lista"] == nombre]
        if previas and (dt.date.fromisoformat(hoy) - dt.date.fromisoformat(max(previas))).days < 6:
            continue
        if tks:
            R["canastas"].append({"lista": nombre, "fecha": hoy, "tickers": tks})
            log(f"foto de la lista {nombre}: {len(tks)} empresas")

    # ---- 3. medición contra el S&P 500
    cache = {}
    spy = _serie("SPY", cache)
    for v in R["veredictos"]:
        r, hasta = _desde(_serie(v["ticker"], cache), v["fecha"])
        s, _ = _desde(spy, v["fecha"])
        v.update(ret=r, ret_sp=s, exceso=(r - s) if r is not None and s is not None else None, hasta=hasta,
                 dias=(dt.date.fromisoformat(hasta) - dt.date.fromisoformat(v["fecha"])).days if hasta else None)
    for c in R["canastas"]:
        rets = [x for x in (_desde(_serie(t, cache), c["fecha"])[0] for t in c["tickers"]) if x is not None]
        s, hasta = _desde(spy, c["fecha"])
        c.update(ret=sum(rets) / len(rets) if rets else None, medidas=len(rets), ret_sp=s, hasta=hasta,
                 exceso=(sum(rets) / len(rets) - s) if rets and s is not None else None,
                 gana=sum(1 for x in rets if s is not None and x > s),
                 dias=(dt.date.fromisoformat(hasta) - dt.date.fromisoformat(c["fecha"])).days if hasta else None)
    R["medido"] = dt.datetime.now().isoformat(timespec="minutes")
    json.dump(R, open(RUTA, "w"), ensure_ascii=False, indent=0, separators=(",", ":"))
    log(f"registro: {len(R['veredictos'])} veredictos, {len(R['canastas'])} fotos de listas")
    return R


if __name__ == "__main__":
    construir()
