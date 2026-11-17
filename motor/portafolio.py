"""El Constructor: arma una canasta de 10 activos poco correlacionados entre sí.

7 acciones (las mejor puntuadas, de sectores distintos) + 3 diversificadores que no son
acciones (materias primas, oro, bonos del Tesoro). Todas las correlaciones se calculan con
retornos semanales de los últimos 5 años; también se mide qué pasa en las semanas malas.
"""
import json, os, sys, math, statistics, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos

DIVERSIFICADORES = {
    "GLD": ("Oro", "Materia prima"), "SLV": ("Plata", "Materia prima"),
    "DBC": ("Canasta de materias primas", "Materia prima"), "USO": ("Petróleo", "Materia prima"),
    "CPER": ("Cobre", "Materia prima"), "DBA": ("Materias primas agrícolas", "Materia prima"),
    "TLT": ("Bonos del Tesoro a 20+ años", "Bonos"),
}
FACTORES = {"SPY": "Mercado (S&P 500)", "TLT": "Tasas de interés (bonos largos)", "USO": "Petróleo",
            "GLD": "Oro", "UUP": "Dólar"}
SEMANAS = 260


def _retornos(simbolo):
    p = datos.precios(simbolo, "10y", "1d", ttl_horas=12)
    if not p:
        return None
    return dict(zip(p["fechas"], p["cierre_aj"]))


def _corr(a, b):
    n = len(a)
    if n < 8:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a); vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def construir(candidatas, n_acciones=7, n_divers=3, penal=0.6):
    """candidatas: lista de dicts con ticker, nombre, sector, puntaje, potencial, tamano."""
    simbolos = [c["ticker"] for c in candidatas] + list(DIVERSIFICADORES) + list(FACTORES)
    series = {}
    for s in dict.fromkeys(simbolos):
        r = _retornos(s.replace(".", "-"))
        if r:
            series[s] = r
    # calendario común: un punto cada 5 ruedas del S&P
    base = sorted(series["SPY"])
    fechas = base[::-1][::5][::-1][-(SEMANAS + 1):]
    validos = [s for s in series if all(f in series[s] for f in fechas[-(SEMANAS // 2):])]
    ret = {}
    for s in validos:
        fs = [f for f in fechas if f in series[s]]
        ret[s] = {fs[i]: math.log(series[s][fs[i]] / series[s][fs[i - 1]]) for i in range(1, len(fs))}

    def corr(a, b, solo=None):
        comunes = [f for f in ret[a] if f in ret[b] and (solo is None or f in solo)]
        return _corr([ret[a][f] for f in comunes], [ret[b][f] for f in comunes])

    estres = {f for f, x in ret["SPY"].items() if x <= -0.02}
    vol = {s: statistics.pstdev(ret[s].values()) * math.sqrt(52) for s in ret}

    # ---- acciones: mejor puntaje, penalizando parecerse a las ya elegidas; un sector no se repite
    pool = [c for c in candidatas if c["ticker"] in ret]
    elegidas, sectores = [], {}
    while len(elegidas) < n_acciones and pool:
        def valor(c):
            if not elegidas:
                return c["puntaje"]
            prom = sum(corr(c["ticker"], e["ticker"]) or 0 for e in elegidas) / len(elegidas)
            return c["puntaje"] - penal * prom
        libres = [c for c in pool if sectores.get(c["sector"], 0) < 1] or [c for c in pool if sectores.get(c["sector"], 0) < 2]
        if not libres:
            break
        mejor = max(libres, key=valor)
        elegidas.append(mejor); pool.remove(mejor)
        sectores[mejor["sector"]] = sectores.get(mejor["sector"], 0) + 1

    # ---- diversificadores: los menos correlacionados con lo ya elegido
    divers, dpool = [], [d for d in DIVERSIFICADORES if d in ret]
    while len(divers) < n_divers and dpool:
        actuales = [e["ticker"] for e in elegidas] + divers
        mejor = min(dpool, key=lambda d: sum(corr(d, a) or 0 for a in actuales) / len(actuales))
        divers.append(mejor); dpool.remove(mejor)

    activos = [{"ticker": e["ticker"], "nombre": e["nombre"], "tipo": "Acción", "sector": e["sector"],
                "tamano": e.get("tamano"), "potencial": e.get("potencial"), "puntaje": e.get("puntaje")} for e in elegidas]
    activos += [{"ticker": d, "nombre": DIVERSIFICADORES[d][0], "tipo": DIVERSIFICADORES[d][1],
                 "sector": DIVERSIFICADORES[d][1], "tamano": "Fondo cotizado (ETF)", "potencial": None, "puntaje": None} for d in divers]
    tk = [a["ticker"] for a in activos]

    # ---- pesos: inverso de la volatilidad; tope 15% por posición y 30% en no-acciones
    bruto = {t: 1 / vol[t] for t in tk}
    total = sum(bruto.values())
    w = {t: bruto[t] / total for t in tk}
    for _ in range(50):
        exceso = {t: w[t] - 0.15 for t in tk if w[t] > 0.15 + 1e-9}
        if not exceso:
            break
        libres = [t for t in tk if w[t] < 0.15 - 1e-9]
        sobra = sum(exceso.values())
        for t in exceso:
            w[t] = 0.15
        suma_l = sum(w[t] for t in libres)
        for t in libres:
            w[t] += sobra * w[t] / suma_l
    no_acc = [a["ticker"] for a in activos if a["tipo"] != "Acción"]
    peso_no = sum(w[t] for t in no_acc)
    if peso_no > 0.30:
        k = 0.30 / peso_no
        acc = [t for t in tk if t not in no_acc]
        suma_acc = sum(w[t] for t in acc)
        for t in no_acc:
            w[t] *= k
        for t in acc:
            w[t] *= (1 - 0.30) / suma_acc

    M = [[(1.0 if a == b else corr(a, b)) for b in tk] for a in tk]
    ME = [[(1.0 if a == b else corr(a, b, estres)) for b in tk] for a in tk]

    def promedio(m, idx):
        xs = [m[i][j] for i in idx for j in idx if i < j and m[i][j] is not None]
        return sum(xs) / len(xs) if xs else None
    todos = list(range(len(tk))); solo_acc = [i for i, a in enumerate(activos) if a["tipo"] == "Acción"]

    def cartera(pesos):
        fs = sorted(set.intersection(*[set(ret[t]) for t in pesos]))
        return fs, [sum(pesos[t] * (math.exp(ret[t][f]) - 1) for t in pesos) for f in fs]

    def metricas(fs, rs):
        v = statistics.pstdev(rs) * math.sqrt(52)
        nivel, pico, peor, curva = 1.0, 1.0, 0.0, []
        for f, r in zip(fs, rs):
            nivel *= 1 + r; pico = max(pico, nivel); peor = min(peor, nivel / pico - 1)
            curva.append({"f": f, "v": round(nivel, 4)})
        anual = nivel ** (52 / len(rs)) - 1
        spy = [math.exp(ret["SPY"][f]) - 1 for f in fs]
        c = _corr(rs, spy)
        beta = c * statistics.pstdev(rs) / statistics.pstdev(spy)
        malas = [r for r, s in zip(rs, spy) if s <= -0.02]
        return {"volatilidad": v, "peor_caida": peor, "retorno_anual": anual, "corr_sp500": c, "beta": beta,
                "semanas_malas": (sum(malas) / len(malas)) if malas else None}, curva

    fs, rs = cartera(w)
    m_cart, curva_cart = metricas(fs, rs)
    w_acc = {t: 1 / len(solo_acc) for t in [tk[i] for i in solo_acc]}
    m_acc, curva_acc = metricas(*cartera(w_acc))
    m_spy, curva_spy = metricas(*cartera({"SPY": 1.0}))
    paso = max(1, len(curva_cart) // 130)
    recorta = lambda c: c[::paso] + ([c[-1]] if (len(c) - 1) % paso else [])

    factores = []
    for a in activos:
        factores.append({"ticker": a["ticker"], **{f: (1.0 if f == a["ticker"] else corr(a["ticker"], f)) for f in FACTORES if f in ret}})
    comunes = {}
    for f in FACTORES:
        if f not in ret:
            continue
        xs = [x[f] for x in factores if x.get(f) is not None and x["ticker"] != f]
        comunes[f] = {"nombre": FACTORES[f], "promedio": sum(xs) / len(xs), "expuestos": sum(1 for x in xs if abs(x) >= 0.4)}

    for a in activos:
        t = a["ticker"]
        a.update(peso=w[t], volatilidad=vol[t], corr_sp500=corr(t, "SPY"), corr_sp500_estres=corr(t, "SPY", estres),
                 corr_prom=sum(M[tk.index(t)][j] for j in todos if j != tk.index(t)) / (len(tk) - 1))
    return {"generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "desde": fechas[1], "hasta": fechas[-1], "semanas": len(fechas) - 1, "semanas_estres": len(estres),
            "activos": activos, "tickers": tk, "matriz": M, "matriz_estres": ME,
            "corr_prom": promedio(M, todos), "corr_prom_acciones": promedio(M, solo_acc),
            "corr_prom_estres": promedio(ME, todos), "corr_prom_acciones_estres": promedio(ME, solo_acc),
            "cartera": m_cart, "solo_acciones": m_acc, "sp500": m_spy,
            "curvas": {"cartera": recorta(curva_cart), "solo_acciones": recorta(curva_acc), "sp500": recorta(curva_spy)},
            "factores": factores, "factores_comunes": comunes, "nombres_factores": FACTORES,
            "descartados_divers": [{"ticker": d, "nombre": DIVERSIFICADORES[d][0]} for d in DIVERSIFICADORES if d in ret and d not in divers]}
