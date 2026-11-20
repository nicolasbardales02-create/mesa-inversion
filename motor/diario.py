"""Actualización diaria de precios (días hábiles, después del cierre de Nueva York).

La actualización semanal recalcula todo desde la SEC. Esta, en unos minutos, solo mueve lo que depende del precio:
  - tabla de empresas (datos/universo.json): precio, capitalización, P/U, P/VL, VE/utilidad operativa,
    rendimiento de caja, potencial frente al valor base, caída desde el máximo y retorno a 1 año (aprox.);
  - fichas (datos/fichas/*.json): precio, serie, máximos, múltiplos, crecimiento implícito, tasa base,
    margen de seguridad y zona del DCF;
  - índice (datos/indice.json), tesis vigilada (datos/tesis.json) y precios de fondos (datos/precios.json).
NO cambia el veredicto cuantitativo ni la lista ick: esos se recalculan el sábado con datos completos,
para que no salten por el ruido de un solo día.

Cada valor se mueve por el cociente cierre_nuevo / cierre_anterior del mismo símbolo, así que sirve igual
para acciones locales y ADR (no importa en qué unidad esté guardado el precio).

Uso: python3 motor/diario.py
"""
import datetime as dt, glob, json, os, sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos
import valoracion as V

NY = ZoneInfo("America/New_York")
RAIZ = datos.RAIZ
D = os.path.join(RAIZ, "datos")


def _fecha_ny(ts):
    return dt.datetime.fromtimestamp(ts, NY).date().isoformat()


def series(simbolos, lote=20, log=print, max_fallos=12, minutos=90):
    """{símbolo: [(fecha, cierre), ...]} del último mes, solo ruedas cerradas.
    Si Yahoo limita (HTTP 429), espera un minuto y sigue con el mismo lote; se rinde tras varios rechazos
    seguidos o al pasar el tiempo máximo, y devuelve lo que alcanzó."""
    import requests, time
    fin = time.time() + minutos * 60
    hoy = dt.datetime.now(NY)
    cerrado = hoy.hour > 16 or (hoy.hour == 16 and hoy.minute >= 20)
    salida, fallos, i = {}, 0, 0
    while i < len(simbolos):
        if time.time() > fin:
            log(f"  tiempo máximo alcanzado: me detengo con {len(salida)} símbolos")
            break
        grupo = simbolos[i:i + lote]
        url = ("https://query1.finance.yahoo.com/v8/finance/spark?symbols="
               + requests.utils.quote(",".join(grupo)) + "&range=1mo&interval=1d")
        try:
            t = datos.get(url, ttl_horas=1, reintentos=2)
            d = json.loads(t) if t else {}
            fallos = 0
        except RuntimeError as e:
            fallos += 1
            log(f"  lote {i // lote + 1} rechazado ({str(e)[-8:]}); espero un minuto")
            if fallos >= max_fallos:
                log(f"  Yahoo rechazó {fallos} veces seguidas: me detengo con {len(salida)} símbolos")
                break
            time.sleep(60)
            continue                          # reintenta el mismo lote
        for s, v in d.items():
            pares = [(_fecha_ny(t), c) for t, c in zip(v.get("timestamp") or [], v.get("close") or []) if c]
            if pares and not cerrado and pares[-1][0] == hoy.date().isoformat():
                pares = pares[:-1]          # la rueda de hoy sigue abierta
            if pares:
                salida[s] = pares
        if (i // lote) % 25 == 0:
            log(f"  precios: {min(i + lote, len(simbolos))}/{len(simbolos)}")
        i += lote
    return salida


def _en(pares, fecha):
    """Cierre de la última rueda en o antes de `fecha`."""
    previos = [c for f, c in pares if f <= fecha]
    return previos[-1] if previos else None


def _mul(x, k):
    return x * k if isinstance(x, (int, float)) else x


def universo(S, log=print):
    ruta = os.path.join(D, "universo.json")
    U = json.load(open(ruta))
    cols = U["cols"]
    base_tabla = dt.datetime.fromisoformat(U["generado"]).astimezone(NY).date().isoformat()
    fechas = U.get("precio_fecha") or {}       # fecha del precio de cada empresa movida por esta tarea
    nueva, n = base_tabla, 0
    for fila in U["filas"]:
        f = dict(zip(cols, fila))
        pares = S.get(f["t"].replace(".", "-"))
        base = fechas.get(f["t"], base_tabla)
        if not f.get("p") or not pares or pares[-1][0] <= base:
            continue
        c0, c1 = _en(pares, base), pares[-1][1]
        if not c0:
            continue
        k = c1 / c0
        if not 0.5 < k < 2:          # salto extremo: probable error de datos o split; se deja al semanal
            continue
        f["p"], f["cap"] = round(f["p"] * k, 2), f["cap"] * k if f.get("cap") else f.get("cap")
        for c in ("per", "pb"):
            f[c] = _mul(f.get(c), k)
        if f.get("rf") is not None:
            f["rf"] = f["rf"] / k
        if f.get("vee") is not None and f.get("uo") and f.get("cap"):
            ve = f["cap"] + (f.get("dn") or 0)
            f["vee"] = ve / f["uo"] if f["uo"] > 0 and ve > 0 else None
        if f.get("pot") is not None:
            f["pot"] = (1 + f["pot"]) / k - 1
        if f.get("dd52") is not None:
            f["dd52"] = min(0.0, (1 + f["dd52"]) * k - 1)
        if f.get("r1a") is not None:
            f["r1a"] = (1 + f["r1a"]) * k - 1      # aproximado; el semanal lo recalcula exacto
        for c, dec in (("per", 1), ("pb", 2), ("rf", 4), ("vee", 1), ("pot", 3), ("dd52", 3), ("r1a", 3)):
            if isinstance(f.get(c), float):
                f[c] = round(f[c], dec)
        if f.get("cap"):
            f["cap"] = round(f["cap"])
        fila[:] = [f.get(c) for c in cols]
        fechas[f["t"]] = pares[-1][0]
        nueva, n = max(nueva, pares[-1][0]), n + 1
    U["precio_fecha"], U["precios_al"] = fechas, nueva
    json.dump(U, open(ruta, "w"), ensure_ascii=False, separators=(",", ":"))
    log(f"universo: {n} precios movidos (tabla del {base_tabla}; último cierre {nueva})")
    return nueva


def _zona(precio, vp, vb, vo):
    # mismos umbrales que motor/analista.py
    margen = vb / precio - 1
    if precio < vp:
        z = "Bajo el escenario pesimista"
    elif margen >= 0.25:
        z = "Descuento amplio sobre el valor base"
    elif margen >= 0.0:
        z = "Algo por debajo del valor base"
    elif precio <= vo:
        z = "Entre el valor base y el optimista"
    else:
        z = "Por encima del escenario optimista"
    return z, margen


def fichas(S, log=print):
    n = 0
    for ruta in glob.glob(os.path.join(D, "fichas", "*.json")):
        d = json.load(open(ruta))
        px, pares = d.get("precio") or {}, S.get(d["ticker"].replace(".", "-"))
        if not px.get("ultimo") or not pares or pares[-1][0] <= (px.get("fecha") or ""):
            continue
        fecha, c1 = pares[-1]
        k = c1 / px["ultimo"]
        if not 0.5 < k < 2:
            continue
        px.update(ultimo=c1, fecha=fecha, en_curso=False, hora=f"{fecha} 16:00")
        px["max_52s"] = max(px.get("max_52s") or c1, c1)
        px["min_52s"] = min(px.get("min_52s") or c1, c1)
        px["desde_max_52s"] = c1 / px["max_52s"] - 1
        for r in ("ret_1a", "ret_3a", "ret_5a", "ret_10a"):
            if px.get(r) is not None:
                px[r] = (1 + px[r]) * k - 1
        serie = px.get("serie") or []
        if serie and serie[-1]["f"] < fecha:
            # la serie guarda un punto cada ~3 semanas más el último cierre: se reemplaza ese último
            if len(serie) >= 2 and (dt.date.fromisoformat(serie[-1]["f"]) - dt.date.fromisoformat(serie[-2]["f"])).days < 18:
                serie.pop()
            serie.append({"f": fecha, "c": round(c1, 2)})
        cap0 = d.get("cap_bursatil")
        if cap0:
            ve0 = d.get("valor_empresa") or cap0
            d["cap_bursatil"] = cap0 * k
            d["valor_empresa"] = ve0 + cap0 * (k - 1)
            kv = d["valor_empresa"] / ve0 if ve0 else 1
            m = d.get("multiplos") or {}
            for c in ("per", "p_fcf", "p_valor_libro"):
                m[c] = _mul(m.get(c), k)
            for c in ("rend_fcf", "rend_fcf_sbc"):
                if m.get(c) is not None:
                    m[c] = m[c] / k
            for c in ("ve_ebit", "ve_ventas"):
                m[c] = _mul(m.get(c), kv)
            pers = [x["per"] for x in d.get("per_historia") or [] if x.get("per")]
            if m.get("per") and len(pers) >= 4:
                m["per_percentil"] = sum(1 for x in pers if x <= m["per"]) / len(pers)
        dcf = d.get("dcf")
        if dcf and dcf.get("escenarios"):
            b = dcf["escenarios"]["base"]
            try:
                impl = V.crecimiento_implicito(c1, b["fcf0"], b["g_t"], b["r"], dcf["deuda_neta"], dcf["acciones"])
                dcf["crecimiento_implicito"] = impl
                tb = dcf.get("tasa_base")
                if tb and impl is not None and b["fcf0"] > 0:
                    import tasas_base as TB
                    g10 = (V.flujos(b["fcf0"], impl, b["g_t"])[-1] / b["fcf0"]) ** (1 / 10) - 1
                    tb.update(implicito_10=g10, prob=TB.prob_lograr(g10, dcf["ingresos_ttm"], json.load(open(TB.RUTA))))
            except Exception:
                pass
        v = d.get("veredicto")
        if v and v.get("valor_base"):
            v["zona"], v["margen_seguridad"] = _zona(c1, v["valor_pes"], v["valor_base"], v["valor_opt"])
        d["precio_actualizado"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        json.dump(d, open(ruta, "w"), ensure_ascii=False, separators=(",", ":"))
        n += 1
    log(f"fichas: {n} actualizadas")


def indice(log=print):
    """Pone al día precio, zona y minigráfico del índice con las fichas ya movidas (sin descargar nada)."""
    ruta = os.path.join(D, "indice.json")
    if not os.path.exists(ruta):
        return
    I = json.load(open(ruta))
    for x in I["fichas"]:
        r = os.path.join(D, "fichas", x["ticker"] + ".json")
        if not os.path.exists(r):
            continue
        d = json.load(open(r))
        px, v = d.get("precio") or {}, d.get("veredicto") or {}
        if px.get("ultimo") and px["ultimo"] != x.get("precio"):
            x["spark"] = (x.get("spark") or [])[-52:] + [round(px["ultimo"], 2)]
        x.update(precio=px.get("ultimo"), zona=v.get("zona"), margen=v.get("margen_seguridad"),
                 desde_max=px.get("desde_max_52s"))
    json.dump(I, open(ruta, "w"), separators=(",", ":"))


def fondos(log=print):
    ruta = os.path.join(D, "precios.json")
    if not os.path.exists(ruta):
        return
    P = json.load(open(ruta))
    import perfiles                     # sabe qué fondos irlandeses se buscan en Londres (CSPX → CSPX.L)
    nuevos = perfiles.precios_extra(list(P["precios"]))["precios"]
    P["precios"].update({k: v for k, v in nuevos.items() if k in P["precios"]})
    P["generado"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    json.dump(P, open(ruta, "w"), separators=(",", ":"))
    log(f"fondos: {len(nuevos)} de {len(P['precios'])}")


def main(log=print):
    U = json.load(open(os.path.join(D, "universo.json")))
    primero = sorted(os.path.basename(x)[:-5].replace(".", "-") for x in glob.glob(os.path.join(D, "fichas", "*.json")))
    # el resto, empezando por las empresas con el precio más viejo: si Yahoo corta, mañana siguen las que faltaron
    base = dt.datetime.fromisoformat(U["generado"]).astimezone(NY).date().isoformat()
    fechas = U.get("precio_fecha") or {}
    con_p = [r[0] for r in U["filas"] if r[U["cols"].index("p")]]
    resto = [t.replace(".", "-") for t in sorted(con_p, key=lambda t: (fechas.get(t, base), t))
             if t.replace(".", "-") not in set(primero)]
    S = series(primero + resto, log=log)      # las fichas van primero: si Yahoo corta, al menos ellas quedan al día
    log(f"series: {len(S)} de {len(primero) + len(resto)} símbolos")
    universo(S, log)
    fichas(S, log)
    if len(S) >= 0.5 * (len(primero) + len(resto)):
        fondos(log)                           # solo si Yahoo está respondiendo: si no, se queda con los del sábado
    else:
        log("fondos: se omiten (Yahoo está limitando)")
    indice(log)
    log("índice listo")
    import subprocess
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tesis.py")], check=False)
    log("DIARIO TERMINADO")


if __name__ == "__main__":
    main(lambda *a: print(*a, flush=True))
