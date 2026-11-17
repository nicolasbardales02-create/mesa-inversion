"""Radar de eventos especiales: situaciones que la investigación académica asocia con retornos anormales,
detectadas en los índices oficiales de presentaciones de la SEC (todo verificable con su enlace).

1. Compras de directivos en grupo (Formulario 4, código P = compra en el mercado con su dinero).
   Varias personas de adentro comprando a la vez es una de las señales más estudiadas.
2. Activistas y tenedores de más de 5% con intención de influir (SCHEDULE 13D inicial).
3. Escisiones / spin-offs (Formulario 10-12B: registro de una empresa nueva que se separará de su matriz).
4. Fusiones y ofertas de compra (DEFM14A/PREM14A: votación de una fusión; SC TO-T: oferta pública de compra;
   SC 14D9: respuesta de la empresa objetivo).
5. Alertas contables y de cotización en 8-K: 4.01 cambio de auditor, 4.02 estados financieros no confiables
   (re-expresión), 3.01 aviso de exclusión de la bolsa, 1.03 quiebra.

Uso: python3 motor/radar.py [días_formulario4=30]
"""
import gzip, json, os, re, sys, datetime as dt
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(__file__))
import datos

ACTIVISTAS = ["ELLIOTT", "STARBOARD", "TRIAN", "VALUEACT", "ICAHN", "JANA PARTNERS", "THIRD POINT", "PERSHING SQUARE",
              "ENGINE CAPITAL", "ENGINE NO", "ANCORA", "LAND & BUILDINGS", "MANTLE RIDGE", "SACHEM HEAD", "CORVEX",
              "LEGION PARTNERS", "POLITAN", "IRENIC", "CARRONADE", "BLACKWELLS", "SARISSA", "INCLUSIVE CAPITAL",
              "BARINGTON", "MACELLUM", "HOTCHKIS", "CAS INVESTMENT", "PALLIser", "PALLISER", "D. E. SHAW", "D.E. SHAW"]
ITEMS_8K = {"4.01": ("Cambio de auditor", 2), "4.02": ("Estados financieros previos ya no son confiables (re-expresión)", 3),
            "3.01": ("Aviso sobre su cotización: exclusión, incumplimiento de requisitos o traslado a otra bolsa", 2), "1.03": ("Quiebra o administración judicial", 3)}
RUTA = os.path.join(datos.RAIZ, "datos", "radar.json")


def es_activista(quien):
    q = quien.upper()
    return any(re.search(r"\b" + re.escape(a.upper()) + r"\b", q) for a in ACTIVISTAS)


def _trimestres(n=3):
    hoy = dt.date.today(); y, q = hoy.year, (hoy.month - 1) // 3 + 1; out = []
    for _ in range(n):
        out.append((y, q)); q -= 1
        if q == 0:
            y, q = y - 1, 4
    return out


def indice(n=3, log=print):
    """Filas (forma, empresa, cik, fecha, archivo) de los últimos n trimestres."""
    filas = []
    for k, (y, q) in enumerate(_trimestres(n)):
        try:
            b = datos.get(f"https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.gz",
                          ttl_horas=12 if k == 0 else 24 * 30, binario=True)
        except Exception as e:
            log(f"índice {y} T{q}: {e}"); continue
        for linea in gzip.decompress(b).decode("latin-1").splitlines():
            if not linea.rstrip().endswith(".txt") or len(linea) < 100:
                continue
            forma = linea[:17].strip()                     # columnas de ancho fijo
            partes = linea[17:].rsplit(None, 3)
            if len(partes) == 4 and partes[1].isdigit():
                filas.append((forma, partes[0].strip(), int(partes[1]), partes[2], partes[3]))
    return filas


def _acc(archivo):
    m = re.search(r"data/(\d+)/(\d{10}-\d{2}-\d{6})", archivo)
    return (int(m.group(1)), m.group(2)) if m else (None, None)


def _url_carpeta(cik, acc):
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/"


def _cabecera(cik, acc):
    try:
        return datos.get(f"{_url_carpeta(cik, acc)}{acc}.hdr.sgml", ttl_horas=24 * 60) or ""
    except Exception:
        return ""


def _partes(hdr):
    """Empresa objetivo y quien presenta, desde la cabecera SGML."""
    def bloque(tag):
        out = []
        for b in re.findall(rf"<{tag}>(.*?)</{tag}>", hdr, re.S):
            n = re.search(r"<CONFORMED-NAME>(.+)", b); c = re.search(r"<CIK>(\d+)", b)
            if n and c:
                out.append((n.group(1).strip(), int(c.group(1))))
        return out
    return bloque("SUBJECT-COMPANY"), bloque("FILED-BY")


def _precargar(urls, ttl, log=print, hilos=16):
    """Descarga en paralelo (con el límite de ritmo de datos.get) para que luego se lea del caché."""
    from concurrent.futures import ThreadPoolExecutor
    urls = list(dict.fromkeys(urls))
    def uno(u):
        try:
            datos.get(u, ttl_horas=ttl)
        except Exception:
            pass
    with ThreadPoolExecutor(hilos) as ex:
        for k, _ in enumerate(ex.map(uno, urls)):
            if k % 1000 == 0:
                log(f"  descargados {k}/{len(urls)}")


def _hoy_menos(d):
    return (dt.date.today() - dt.timedelta(days=d)).isoformat()


def construir(dias_f4=30, log=print):
    U = json.load(open(os.path.join(datos.RAIZ, "datos", "universo.json")))
    cols = U["cols"]; filas_u = [dict(zip(cols, r)) for r in U["filas"]]
    por_t = {f["t"]: f for f in filas_u}
    tick = {}
    for t in datos.tickers_sec():
        tick.setdefault(t["cik"], t["ticker"])
    uni_cik = {c: t for c, t in tick.items() if t in por_t}
    seguidas = {c for c, t in uni_cik.items() if por_t[t].get("p")}       # con precio
    info = lambda cik: (lambda t: {"ticker": t, "empresa": por_t[t]["n"] if t in por_t else None,
                                   "precio": por_t.get(t, {}).get("p"), "cap": por_t.get(t, {}).get("cap"),
                                   "sector": por_t.get(t, {}).get("s"), "pot": por_t.get(t, {}).get("pot"),
                                   "rojas": por_t.get(t, {}).get("rojas")})(tick.get(cik))
    idx = indice(3, log)
    log(f"índice: {len(idx)} presentaciones en 3 trimestres")
    R = {"generado": dt.datetime.now().isoformat(timespec="minutes"), "dias_f4": dias_f4}

    # ---------- 1. compras de directivos
    f4 = {}
    for forma, emp, cik, fecha, arch in idx:
        if forma == "4" and cik in seguidas and fecha >= _hoy_menos(dias_f4):
            f4.setdefault(arch, (cik, fecha))
    log(f"formularios 4 a revisar: {len(f4)}")
    _precargar(["https://www.sec.gov/Archives/" + a for a in f4], 24 * 60, log)
    compras = {}
    for k, (arch, (cik, fecha)) in enumerate(f4.items()):
        if k % 500 == 0:
            log(f"  f4 {k}/{len(f4)}")
        try:
            txt = datos.get("https://www.sec.gov/Archives/" + arch, ttl_horas=24 * 60) or ""
        except Exception:
            continue
        m = re.search(r"<ownershipDocument>.*?</ownershipDocument>", txt, re.S)
        if not m:
            continue
        try:
            raiz = ET.fromstring(m.group(0))
        except ET.ParseError:
            continue
        emisor = raiz.findtext("issuer/issuerCik")
        if not emisor or int(emisor) != cik:
            continue
        nombre = (raiz.findtext("reportingOwner/reportingOwnerId/rptOwnerName") or "").strip()
        rel = raiz.find("reportingOwner/reportingOwnerRelationship")
        es = lambda t: rel is not None and (rel.findtext(t) or "").strip().lower() in ("1", "true")
        cargo = (rel.findtext("officerTitle") or "").strip() if rel is not None else ""
        rol = cargo or ("Director" if es("isDirector") else ("Dueño de más de 10%" if es("isTenPercentOwner") else "Otro"))
        for tr in raiz.findall("nonDerivativeTable/nonDerivativeTransaction"):
            if (tr.findtext("transactionCoding/transactionCode") or "").strip() != "P":
                continue
            try:
                n = float(tr.findtext("transactionAmounts/transactionShares/value") or 0)
                p = float(tr.findtext("transactionAmounts/transactionPricePerShare/value") or 0)
            except ValueError:
                continue
            if n <= 0 or p <= 0:
                continue
            c = compras.setdefault(cik, {"personas": {}, "monto": 0.0, "ultima": fecha, "enlace": None})
            pe = c["personas"].setdefault(nombre, {"nombre": nombre.title(), "rol": rol, "monto": 0.0, "acciones": 0.0,
                                                   "diez": es("isTenPercentOwner") and not es("isDirector") and not cargo})
            pe["monto"] += n * p; pe["acciones"] += n
            c["monto"] += n * p
            if fecha >= c["ultima"] or not c["enlace"]:
                c["ultima"] = max(c["ultima"], fecha)
                c["enlace"] = _url_carpeta(*_acc(arch))
    lista = []
    for cik, c in compras.items():
        # solo directivos y directores, y compras de al menos $15 mil por persona
        # (las compras pequeñas y parejas suelen ser planes de compra para empleados, no una decisión)
        gente = [p for p in c["personas"].values() if not p["diez"] and p["monto"] >= 15_000]
        monto = sum(p["monto"] for p in gente)
        if not gente or not (len(gente) >= 2 or monto >= 500_000):
            continue
        for p in gente:
            p["precio_prom"] = p["monto"] / p["acciones"] if p["acciones"] else None
        lista.append({**info(cik), "compradores": len(gente), "monto": monto, "ultima": c["ultima"], "enlace": c["enlace"],
                      "personas": sorted(({k: v for k, v in p.items() if k != "diez"} for p in gente), key=lambda p: -p["monto"])[:6],
                      "ceo_cfo": any(re.search(r"chief executive|ceo|chief financial|cfo|president", p["rol"], re.I) for p in gente)})
    lista.sort(key=lambda x: (-x["compradores"], -x["monto"]))
    R["compras_directivos"] = lista
    log(f"compras en grupo: {len(lista)}")

    cab = [a for forma, emp, cik, fecha, a in idx if (forma in ("SCHEDULE 13D", "SC 13D") and fecha >= _hoy_menos(90))
           or (forma in ("SC TO-T", "SC 14D9", "SC TO-C") and fecha >= _hoy_menos(150))]
    _precargar([f"{_url_carpeta(*_acc(a))}{_acc(a)[1]}.hdr.sgml" for a in cab], 24 * 60, log)
    # ---------- 2. activistas (13D inicial)
    vistos, act = set(), []
    for forma, emp, cik, fecha, arch in idx:
        if forma in ("SCHEDULE 13D", "SC 13D") and fecha >= _hoy_menos(90) and _acc(arch)[1] not in vistos:
            c, acc = _acc(arch)
            vistos.add(acc)
            sujeto, por = _partes(_cabecera(c, acc))
            if not sujeto:
                continue
            s_nombre, s_cik = sujeto[0]
            if s_cik not in uni_cik and s_cik not in tick:
                continue
            quien = ", ".join(n.title() for n, _ in por[:3]) or "—"
            act.append({**info(s_cik), "empresa": info(s_cik)["empresa"] or s_nombre.title(), "fecha": fecha,
                        "quien": quien, "activista": es_activista(quien),
                        "enlace": _url_carpeta(c, acc)})
    act.sort(key=lambda x: (not x["activista"], x["ticker"] not in por_t, x["fecha"]), reverse=False)
    act = sorted(act, key=lambda x: x["fecha"], reverse=True)
    act = [a for a in act if a["activista"]] + [a for a in act if not a["activista"] and a["ticker"] in por_t]
    R["activistas"] = act[:120]
    log(f"13D: {len(act)}")

    # ---------- 3. spin-offs
    so = {}
    for forma, emp, cik, fecha, arch in idx:
        if forma in ("10-12B", "10-12B/A") and fecha >= _hoy_menos(270):
            s = so.setdefault(cik, {"empresa": emp.title(), "primera": fecha, "ultima": fecha, "enmiendas": 0, "enlace": None})
            s["primera"] = min(s["primera"], fecha)
            if fecha >= s["ultima"]:
                s["ultima"] = fecha; s["enlace"] = _url_carpeta(*_acc(arch))
            s["enmiendas"] += forma.endswith("/A")
    R["spinoffs"] = sorted(({**v, "ticker": tick.get(k)} for k, v in so.items()), key=lambda x: x["ultima"], reverse=True)
    log(f"spin-offs: {len(so)}")

    # ---------- 4. fusiones y ofertas de compra
    fus, vistos = {}, set()
    TIPOS = {"DEFM14A": "Votación de fusión (definitiva)", "PREM14A": "Votación de fusión (preliminar)",
             "SC TO-T": "Oferta pública de compra", "SC 14D9": "Respuesta a oferta de compra", "SC TO-C": "Anuncio de oferta"}
    for forma, emp, cik, fecha, arch in idx:
        if forma in TIPOS and fecha >= _hoy_menos(150) and _acc(arch)[1] not in vistos:
            c, acc = _acc(arch)
            vistos.add(acc)
            if forma in ("DEFM14A", "PREM14A"):
                obj, comprador = (emp, cik), None
            else:
                sujeto, por = _partes(_cabecera(c, acc))
                if not sujeto:
                    continue
                obj = sujeto[0]
                comprador = ", ".join(n.title() for n, k in por if k != obj[1]) or None
            o_nombre, o_cik = obj
            if o_cik not in tick:
                continue
            f = fus.setdefault(o_cik, {**info(o_cik), "empresa": info(o_cik)["empresa"] or o_nombre.title(),
                                       "eventos": [], "comprador": None})
            f["comprador"] = f["comprador"] or comprador
            f["eventos"].append({"fecha": fecha, "tipo": TIPOS[forma], "enlace": _url_carpeta(c, acc)})
    for f in fus.values():
        f["eventos"].sort(key=lambda e: e["fecha"], reverse=True); f["ultima"] = f["eventos"][0]["fecha"]
    R["fusiones"] = sorted(fus.values(), key=lambda x: (x["ticker"] in por_t, x["ultima"]), reverse=True)
    log(f"fusiones/ofertas: {len(fus)}")

    # ---------- 5. alertas en 8-K
    al, vistos, reestr = [], set(), []
    ochos = [(cik, fecha, arch) for forma, emp, cik, fecha, arch in idx
             if forma == "8-K" and cik in seguidas and fecha >= _hoy_menos(90)]
    log(f"8-K a revisar: {len(ochos)}")
    _precargar([f"{_url_carpeta(*_acc(a))}{_acc(a)[1]}.hdr.sgml" for _, _, a in ochos], 24 * 60, log)
    for k, (cik, fecha, arch) in enumerate(ochos):
        if arch in vistos:
            continue
        vistos.add(arch)
        if k % 1000 == 0:
            log(f"  8-K {k}/{len(ochos)}")
        c, acc = _acc(arch)
        items = re.findall(r"<ITEMS>\s*([\d.]+)", _cabecera(c, acc))
        if "2.05" in items:   # costos de salida o cierre de operaciones: reestructuración
            reestr.append({**info(cik), "fecha": fecha, "enlace": _url_carpeta(c, acc)})
        for it in items:
            if it in ITEMS_8K:
                al.append({**info(cik), "fecha": fecha, "item": it, "que": ITEMS_8K[it][0], "gravedad": ITEMS_8K[it][1],
                           "enlace": _url_carpeta(c, acc)})
    R["alertas_8k"] = sorted(al, key=lambda x: (x["fecha"], x["gravedad"]), reverse=True)
    R["reestructuraciones"] = sorted(reestr, key=lambda x: x["fecha"], reverse=True)
    log(f"reestructuraciones (8-K 2.05): {len(reestr)}")
    log(f"alertas 8-K: {len(al)}")
    json.dump(R, open(RUTA, "w"), ensure_ascii=False, separators=(",", ":"))
    log("RADAR TERMINADO")
    return R


if __name__ == "__main__":
    construir(int(sys.argv[1]) if len(sys.argv) > 1 else 30, log=lambda *a: print(*a, flush=True))
