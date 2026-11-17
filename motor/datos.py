"""Acceso a datos. Todo número del sistema sale de aquí o se calcula a partir de aquí.

Fuentes:
  - Precios: Yahoo Finance (endpoint público de gráficos, sin login).
  - Fundamentales, insiders y directivos: SEC EDGAR (fuente oficial).
"""
import json, os, time, hashlib, threading, datetime as dt
import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(RAIZ, "cache")
UA = {"User-Agent": "personal-research-tool admin@example.com", "Accept-Encoding": "gzip, deflate"}
_ultimo = {"sec": 0.0, "yahoo": 0.0}


_candado = threading.Lock()


def _espera(clave, intervalo):
    """Espaciado mínimo entre pedidos al mismo servidor; seguro con varios hilos (la SEC permite 10 por segundo)."""
    with _candado:
        ahora = time.time()
        turno = max(ahora, _ultimo[clave] + intervalo)
        _ultimo[clave] = turno
    if turno > ahora:
        time.sleep(turno - ahora)


def get(url, ttl_horas=20, binario=False, reintentos=4, guardar=True):
    """GET con caché en disco. ttl_horas=0 fuerza descarga."""
    os.makedirs(CACHE, exist_ok=True)
    ruta = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest())
    if ttl_horas and os.path.exists(ruta) and time.time() - os.path.getmtime(ruta) < ttl_horas * 3600:
        with open(ruta, "rb") as f:
            cuerpo = f.read()
        return cuerpo if binario else cuerpo.decode("utf-8", "replace")
    clave = "sec" if "sec.gov" in url else "yahoo"
    ultimo_error = None
    for intento in range(reintentos):
        _espera(clave, 0.13 if clave == "sec" else 2.0)
        destino = url
        if clave == "yahoo" and intento % 2 == 1:  # alterna entre los dos servidores de Yahoo
            destino = url.replace("query1.finance", "query2.finance")
        try:
            r = requests.get(destino, headers=UA, timeout=60)
            if r.status_code == 404:
                return None
            if r.status_code in (429, 500, 502, 503, 504, 403):
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            if guardar:
                with open(ruta, "wb") as f:
                    f.write(r.content)
            return r.content if binario else r.content.decode("utf-8", "replace")
        except Exception as e:  # red inestable: reintenta con espera creciente
            ultimo_error = e
            limite = "429" in str(e)
            time.sleep((20 * (intento + 1)) if limite else 2 ** intento)
    raise RuntimeError(f"No se pudo descargar {url}: {ultimo_error}")


def get_json(url, ttl_horas=20):
    t = get(url, ttl_horas)
    return None if t is None else json.loads(t)


# ---------------------------------------------------------------- precios
def precios(simbolo, rango="max", intervalo="1d", ttl_horas=6):
    """Serie de precios. Devuelve dict con fechas, cierre (ajustado por splits),
    cierre_aj (ajustado por splits y dividendos) y splits [(fecha, factor)]."""
    s = requests.utils.quote(simbolo)
    if rango == "max":
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?period1=-1500000000&period2=9999999999&interval={intervalo}&events=div%2Csplit"
    else:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range={rango}&interval={intervalo}&events=div%2Csplit"
    d = get_json(url, ttl_horas)
    if not d or not d.get("chart", {}).get("result"):
        return None
    r = d["chart"]["result"][0]
    ts = r.get("timestamp") or []
    cierre = r["indicators"]["quote"][0].get("close") or []
    aj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose") or cierre
    gmt = r["meta"].get("gmtoffset", -18000)
    fechas, c, a = [], [], []
    for t, x, y in zip(ts, cierre, aj):
        if x is None:
            continue
        f = (dt.datetime.fromtimestamp(t + gmt, dt.timezone.utc)).date().isoformat()
        if fechas and fechas[-1] == f:  # barra duplicada del día en curso
            c[-1], a[-1] = x, (y if y is not None else x)
            continue
        fechas.append(f); c.append(x); a.append(y if y is not None else x)
    splits = []
    for ev in (r.get("events", {}).get("splits") or {}).values():
        f = dt.datetime.fromtimestamp(ev["date"] + gmt, dt.timezone.utc).date().isoformat()
        if ev.get("denominator"):
            splits.append((f, ev["numerator"] / ev["denominator"]))
    # ¿la última barra es de una rueda que todavía no cierra?
    meta = r["meta"]
    t_mercado = meta.get("regularMarketTime")
    fin_rueda = ((meta.get("currentTradingPeriod") or {}).get("regular") or {}).get("end")
    en_curso, hora = False, None
    if t_mercado:
        local = dt.datetime.fromtimestamp(t_mercado + gmt, dt.timezone.utc)
        hora = local.strftime("%Y-%m-%d %H:%M")
        # en curso si el dato se tomó antes del cierre de esa rueda (vale también para datos en caché)
        en_curso = bool(fechas and fechas[-1] == local.date().isoformat() and fin_rueda and t_mercado < fin_rueda - 60)
    return {"simbolo": simbolo, "fechas": fechas, "cierre": c, "cierre_aj": a, "en_curso": en_curso, "hora": hora,
            "splits": sorted(splits), "moneda": r["meta"].get("currency"),
            "nombre": r["meta"].get("longName") or r["meta"].get("shortName") or simbolo}


def ultimos_precios(simbolos, lote=20):
    """Último cierre de muchos símbolos en pocas llamadas."""
    salida = {}
    for i in range(0, len(simbolos), lote):
        grupo = simbolos[i:i + lote]
        url = ("https://query1.finance.yahoo.com/v8/finance/spark?symbols="
               + requests.utils.quote(",".join(grupo)) + "&range=5d&interval=1d")
        try:
            d = get_json(url, ttl_horas=6) or {}
        except RuntimeError:
            d = {}
        for s, v in d.items():
            cs = [x for x in (v.get("close") or []) if x is not None]
            if cs:
                salida[s] = cs[-1]
    return salida


# ---------------------------------------------------------------- SEC EDGAR
def tickers_sec():
    """Lista oficial ticker -> CIK. Viene ordenada aproximadamente por tamaño."""
    d = get_json("https://www.sec.gov/files/company_tickers.json", ttl_horas=24 * 7)
    return [{"cik": v["cik_str"], "ticker": v["ticker"], "nombre": v["title"]}
            for _, v in sorted(d.items(), key=lambda kv: int(kv[0]))]


def cik_de(ticker):
    t = ticker.upper().replace(".", "-")
    for fila in tickers_sec():
        if fila["ticker"].upper() == t:
            return fila["cik"]
    return None


def hechos(cik):
    return get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", ttl_horas=24)


def presentaciones(cik):
    return get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", ttl_horas=24)


def marco(concepto, periodo, unidad="USD", taxonomia="us-gaap"):
    """Un concepto contable para TODAS las empresas en un periodo (API frames)."""
    d = get_json(f"https://data.sec.gov/api/xbrl/frames/{taxonomia}/{concepto}/{unidad}/{periodo}.json",
                 ttl_horas=24 * 3)
    return (d or {}).get("data", [])
