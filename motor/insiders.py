"""Directivos, directores y sus operaciones con acciones propias (Formularios 4 de la SEC)."""
import datetime as dt, re
import xml.etree.ElementTree as ET
import datos


def _txt(nodo, ruta):
    x = nodo.find(ruta)
    return x.text.strip() if x is not None and x.text else None


def _num(nodo, ruta):
    t = _txt(nodo, ruta)
    try:
        return float(t) if t else None
    except ValueError:
        return None


def resumen(cik, meses=12, tope=80):
    sub = datos.presentaciones(cik)
    if not sub:
        return None
    rec = sub["filings"]["recent"]
    desde = (dt.date.today() - dt.timedelta(days=int(30.44 * meses))).isoformat()
    enlaces = {}
    for forma, acc, doc, fecha in zip(rec["form"], rec["accessionNumber"], rec["primaryDocument"], rec["filingDate"]):
        if forma in ("10-K", "DEF 14A", "10-Q") and forma not in enlaces:
            enlaces[forma] = {"fecha": fecha, "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"}
    f4 = [(acc, doc, fecha) for forma, acc, doc, fecha in
          zip(rec["form"], rec["accessionNumber"], rec["primaryDocument"], rec["filingDate"])
          if forma == "4" and fecha >= desde]
    total_f4 = len(f4)
    personas, operaciones = {}, []
    for acc, doc, fecha in f4[:tope]:
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{re.sub(r'^xsl[^/]+/', '', doc)}"
        try:
            x = datos.get(url, ttl_horas=24 * 30)
            raiz = ET.fromstring(x.encode()) if x else None
        except Exception:
            raiz = None
        if raiz is None:
            continue
        for due in raiz.findall("reportingOwner"):
            nombre = _txt(due, "reportingOwnerId/rptOwnerName")
            rel = due.find("reportingOwnerRelationship")
            es = lambda k: rel is not None and (_txt(rel, k) or "").lower() in ("1", "true")
            cargo = _txt(rel, "officerTitle") if rel is not None else None
            p = personas.setdefault(nombre, {"nombre": nombre, "director": False, "ejecutivo": False,
                                             "cargo": None, "dueno_10pct": False})
            p["director"] |= es("isDirector"); p["ejecutivo"] |= es("isOfficer")
            p["dueno_10pct"] |= es("isTenPercentOwner")
            p["cargo"] = p["cargo"] or cargo
        nombre = _txt(raiz, "reportingOwner/reportingOwnerId/rptOwnerName")
        for tr in raiz.findall("nonDerivativeTable/nonDerivativeTransaction"):
            cod = _txt(tr, "transactionCoding/transactionCode")
            if cod not in ("P", "S"):
                continue  # solo compras y ventas en el mercado; se ignoran premios, ejercicios e impuestos
            n = _num(tr, "transactionAmounts/transactionShares/value") or 0
            precio = _num(tr, "transactionAmounts/transactionPricePerShare/value") or 0
            operaciones.append({"fecha": _txt(tr, "transactionDate/value") or fecha, "persona": nombre,
                                "tipo": "compra" if cod == "P" else "venta", "acciones": n, "precio": precio,
                                "monto": n * precio})
    compras = [o for o in operaciones if o["tipo"] == "compra"]
    ventas = [o for o in operaciones if o["tipo"] == "venta"]

    def agrupar(ops):
        m = {}
        for o in ops:
            g = m.setdefault(o["persona"], {"persona": o["persona"], "monto": 0.0, "acciones": 0.0, "ultima": o["fecha"]})
            g["monto"] += o["monto"]; g["acciones"] += o["acciones"]; g["ultima"] = max(g["ultima"], o["fecha"])
        return sorted(m.values(), key=lambda g: -g["monto"])[:8]

    gente = sorted(personas.values(), key=lambda p: (not p["ejecutivo"], p["nombre"] or ""))
    return {"meses": meses, "formularios": total_f4, "leidos": min(total_f4, tope),
            "compras_monto": sum(o["monto"] for o in compras), "compras_n": len(compras),
            "compradores": len({o["persona"] for o in compras}),
            "ventas_monto": sum(o["monto"] for o in ventas), "ventas_n": len(ventas),
            "vendedores": len({o["persona"] for o in ventas}),
            "top_compras": agrupar(compras), "top_ventas": agrupar(ventas),
            "personas": gente, "enlaces": enlaces,
            "perfil": {"sic": sub.get("sic"), "sic_desc": sub.get("sicDescription"), "bolsa": (sub.get("exchanges") or [None])[0],
                       "cierre_fiscal": sub.get("fiscalYearEnd"), "estado": sub.get("stateOfIncorporation"),
                       "web": sub.get("website") or None, "nombre": sub.get("name")}}
