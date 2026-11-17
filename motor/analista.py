"""El Analista: arma la ficha completa de una acción.

Capa determinista (este archivo): cifras oficiales, múltiplos, DCF, insiders.
Capa cualitativa (investigacion/<TICKER>.json): gerencia, consenso de analistas, noticias y
conclusión, redactadas a partir de fuentes citadas. Los números nunca salen de esa capa.
"""
import json, os, sys, bisect, statistics, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos, fundamentales as F, valoracion as V, insiders, sectores


def _div(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def _anio_fiscal(fin):
    y, m, d = int(fin[:4]), int(fin[5:7]), int(fin[8:10])
    return str(y - 1) if m == 1 and d <= 10 else str(y)


def _cagr(a, b, anios):
    if a is None or b is None or a <= 0 or b <= 0 or anios <= 0:
        return None
    return (b / a) ** (1 / anios) - 1


def _precio_en(px, fecha):
    i = bisect.bisect_left(px["fechas"], fecha)
    if i >= len(px["fechas"]):
        return None
    return px["cierre"][i]


def _sin_ajuste(px, fecha, precio):
    """Deshace los splits posteriores a `fecha` para comparar con cifras por acción de esa época."""
    for f, factor in px["splits"]:
        if f > fecha:
            precio *= factor
    return precio


def ficha(ticker, con_insiders=True):
    ticker = ticker.upper()
    cik = datos.cik_de(ticker)
    if cik is None:
        raise ValueError(f"{ticker}: no figura en la lista de la SEC")
    h = datos.hechos(cik)
    pxd_full = datos.precios(ticker.replace(".", "-"), "10y", "1d", ttl_horas=12)
    if not h or not pxd_full:
        raise ValueError(f"{ticker}: faltan datos")
    # una sola descarga diaria; la serie semanal se deriva de ella
    idx = list(range(len(pxd_full["fechas"]) - 1, -1, -5))[::-1]
    px = {**pxd_full, "fechas": [pxd_full["fechas"][i] for i in idx],
          "cierre": [pxd_full["cierre"][i] for i in idx], "cierre_aj": [pxd_full["cierre_aj"][i] for i in idx]}
    pxd = {"fechas": pxd_full["fechas"][-252:], "cierre": pxd_full["cierre"][-252:]}
    precio = pxd["cierre"][-1]
    hist = F.historia(h)
    t = F.resumen_ttm(h)
    bal = F.balance(h)
    acciones, f_acc, metodo_acc = F.acciones_diluidas(h, px["splits"])
    cap = precio * acciones if acciones else None
    deuda_neta = bal["deuda_neta"] if bal else 0.0
    ve = cap + deuda_neta if cap is not None else None

    # si el TTM no se pudo armar, usa el último año fiscal
    ult = hist[-1] if hist else {}
    for k in ("ingresos", "util_oper", "util_neta", "fcf", "fcf_sbc", "sbc", "bpa", "flujo_oper", "capex"):
        if t.get(k) is None:
            t[k] = ult.get(k)
    t["fin"] = t.get("fin") or ult.get("fin")

    # ---- historia con márgenes
    tabla = []
    for r in hist:
        ing = r["ingresos"]
        tasa = _div(r["impuesto"], r["antes_imp"])
        tasa = V.limitar(tasa, 0.0, 0.35) if tasa is not None else 0.21
        tabla.append({"anio": _anio_fiscal(r["fin"]), "fin": r["fin"], "ingresos": ing, "util_oper": r["util_oper"],
                      "util_neta": r["util_neta"], "fcf": r["fcf"], "fcf_sbc": r["fcf_sbc"], "sbc": r["sbc"],
                      "bpa": r["bpa"], "acciones": r["acciones"], "dividendos": r["dividendos"],
                      "recompras": r["recompras"], "patrimonio": r["patrimonio"],
                      "margen_oper": _div(r["util_oper"], ing), "margen_neto": _div(r["util_neta"], ing),
                      "margen_fcf": _div(r["fcf"], ing), "margen_fcf_sbc": _div(r["fcf_sbc"], ing),
                      "roe": _div(r["util_neta"], r["patrimonio"]) if (r["patrimonio"] or 0) > 0 else None,
                      "tasa_imp": tasa})
    n = len(tabla)
    crec3 = _cagr(tabla[-4]["ingresos"], tabla[-1]["ingresos"], 3) if n >= 4 else None
    crec5 = _cagr(tabla[-6]["ingresos"], tabla[-1]["ingresos"], 5) if n >= 6 else None
    crec10 = _cagr(tabla[-11]["ingresos"], tabla[-1]["ingresos"], 10) if n >= 11 else None
    candidatos = [x for x in (crec3, crec5) if x is not None]
    crec_hist = min(candidatos) if candidatos else None

    # ---- múltiplos de hoy
    # PER = capitalización / utilidad neta: no se ve afectado por divisiones de acciones
    mult = {"per": _div(cap, t["util_neta"]) if (t["util_neta"] or 0) > 0 else None,
            "ve_ebit": _div(ve, t["util_oper"]) if (t["util_oper"] or 0) > 0 else None,
            "ve_ventas": _div(ve, t["ingresos"]),
            "p_fcf": _div(cap, t["fcf"]) if (t["fcf"] or 0) > 0 else None,
            "rend_fcf": _div(t["fcf"], cap), "rend_fcf_sbc": _div(t["fcf_sbc"], cap),
            "deuda_neta_ebit": _div(deuda_neta, t["util_oper"]) if (t["util_oper"] or 0) > 0 else None,
            "p_valor_libro": _div(cap, bal["patrimonio"]) if bal and (bal["patrimonio"] or 0) > 0 else None}
    tasa_imp = tabla[-1]["tasa_imp"] if tabla else 0.21
    capital_inv = (bal["patrimonio"] or 0) + bal["deuda"] - bal["caja"] - bal["inversiones_lp"] if bal else None
    mult["roic"] = _div((t["util_oper"] or 0) * (1 - tasa_imp), capital_inv) if capital_inv and capital_inv > 0 else None

    # ---- PER histórico "en su momento": precio el día de la presentación / BPA como se reportó
    per_hist = []
    for o in F.originales(h)[-11:]:
        p0 = _precio_en(pxd_full, o["presentado"])
        if p0 is None or not o["bpa"] or o["bpa"] <= 0:
            continue
        p0 = _sin_ajuste(px, o["presentado"], p0)
        per = p0 / o["bpa"]
        if 0 < per < 300:
            per_hist.append({"anio": _anio_fiscal(o["fin"]), "per": per,
                             "p_fcf": (p0 / o["fcf_accion"]) if o.get("fcf_accion") and o["fcf_accion"] > 0 else None})
    pers = [x["per"] for x in per_hist]
    mult["per_mediana_10a"] = statistics.median(pers) if len(pers) >= 4 else None
    mult["per_percentil"] = (sum(1 for x in pers if x <= mult["per"]) / len(pers)) if mult["per"] and len(pers) >= 4 else None

    # ---- insiders y perfil (el sector define el costo de capital)
    ins = insiders.resumen(cik) if con_insiders else None
    perfil = (ins or {}).get("perfil") or {}
    sic = perfil.get("sic")
    sector = sectores.sector(sic)
    financiero = sector in ("Financiero", "Inmobiliario")

    # ---- DCF
    margenes = [r["margen_fcf_sbc"] for r in tabla[-3:] if r["margen_fcf_sbc"] is not None]
    m_ttm = _div(t["fcf_sbc"], t["ingresos"])
    if m_ttm is not None:
        margenes.append(m_ttm)
    margen_norm = statistics.median(margenes) if margenes else None
    margenes_sin = [r["margen_fcf"] for r in tabla[-3:] if r["margen_fcf"] is not None]
    if _div(t["fcf"], t["ingresos"]) is not None:
        margenes_sin.append(_div(t["fcf"], t["ingresos"]))
    margen_norm_sin_sbc = statistics.median(margenes_sin) if margenes_sin else None
    dcf = None
    if margen_norm is not None and t["ingresos"] and acciones:
        esc = V.escenarios(crec_hist, margen_norm, t["ingresos"], deuda_neta, acciones, cap, sector=sector)
        b = esc["base"]
        impl = V.crecimiento_implicito(precio, b["fcf0"], b["g_t"], b["r"], deuda_neta, acciones)
        dcf = {"escenarios": esc, "crecimiento_implicito": impl, "crec_hist": crec_hist,
               "margen_norm": margen_norm, "margen_norm_sin_sbc": margen_norm_sin_sbc,
               "ingresos_ttm": t["ingresos"], "deuda_neta": deuda_neta, "acciones": acciones,
               "aplicable": margen_norm > 0}
        # Tasa base: ¿cuántas empresas de su tamaño lograron el crecimiento que el precio asume?
        try:
            import tasas_base as TB
            if impl is not None and b["fcf0"] > 0:
                g10 = (V.flujos(b["fcf0"], impl, b["g_t"])[-1] / b["fcf0"]) ** (1 / 10) - 1
                tb = json.load(open(TB.RUTA))
                i = TB.tramo(t["ingresos"])
                dcf["tasa_base"] = {"implicito_10": g10, "prob": TB.prob_lograr(g10, t["ingresos"], tb),
                                    "tramo": tb["tramos"][i] if i is not None else None,
                                    "n": tb["horizontes"]["10"][i]["n"] if i is not None else None,
                                    "mediana": tb["horizontes"]["10"][i]["mediana"] if i is not None else None}
        except Exception:
            pass

    # ---- precio
    c, f = px["cierre"], px["fechas"]
    ca = px["cierre_aj"]
    def ret(sem):
        return (ca[-1] / ca[-1 - sem] - 1) if len(ca) > sem else None
    max52, min52 = max(pxd["cierre"]), min(pxd["cierre"])
    paso = max(1, len(c) // 130)
    serie = [{"f": f[i], "c": round(c[i], 2)} for i in range(0, len(c), paso)]
    if serie[-1]["f"] != pxd["fechas"][-1]:
        serie.append({"f": pxd["fechas"][-1], "c": round(precio, 2)})
    rend = [(ca[i] / ca[i - 1] - 1) for i in range(max(1, len(ca) - 156), len(ca))]
    vol = statistics.pstdev(rend) * (52 ** 0.5) if len(rend) > 20 else None
    pico = ca[0]; peor = 0.0
    for x in ca:
        pico = max(pico, x); peor = min(peor, x / pico - 1)
    precio_d = {"ultimo": precio, "fecha": pxd["fechas"][-1], "en_curso": pxd_full.get("en_curso", False), "hora": pxd_full.get("hora"), "max_52s": max52, "min_52s": min52,
                "desde_max_52s": precio / max52 - 1, "ret_1a": ret(52), "ret_3a": ret(156), "ret_5a": ret(260),
                "ret_10a": (ca[-1] / ca[0] - 1) if len(ca) > 500 else None, "volatilidad": vol,
                "peor_caida_10a": peor, "serie": serie}


    # ---- señales
    senales = []
    def s(tipo, texto):
        senales.append({"tipo": tipo, "texto": texto})
    dn = mult["deuda_neta_ebit"]
    if deuda_neta < 0:
        s("positivo", f"Caja neta: tiene ${-deuda_neta / 1e9:,.1f} mil M más de caja que de deuda.")
    elif dn is not None and dn > 3:
        s("riesgo", f"Apalancamiento alto: la deuda neta equivale a {dn:.1f} años de utilidad operativa.")
    if n >= 4 and tabla[-1]["ingresos"] and tabla[-4]["ingresos"] and tabla[-1]["ingresos"] < tabla[-4]["ingresos"]:
        s("riesgo", f"Las ventas del último año fiscal son menores que las de hace tres años ({(tabla[-1]['ingresos'] / tabla[-4]['ingresos'] - 1) * 100:+.0f}%).")
    mo = [r["margen_oper"] for r in tabla[-6:-1] if r["margen_oper"] is not None]
    mo_ttm = _div(t["util_oper"], t["ingresos"])
    if mo and mo_ttm is not None:
        prom = sum(mo) / len(mo)
        if prom > 0.03 and mo_ttm < prom * 0.7:
            s("riesgo", f"Margen operativo en deterioro: {mo_ttm * 100:.1f}% hoy contra {prom * 100:.1f}% promedio de los cinco años previos.")
        elif prom > 0 and mo_ttm > prom * 1.25:
            s("nota", f"Margen operativo muy por encima de su promedio ({mo_ttm * 100:.1f}% vs {prom * 100:.1f}%): puede estar en un pico de ciclo.")
    if n >= 6 and tabla[-1]["acciones"] and tabla[-6]["acciones"]:
        # corrige por splits comparando con la variación del BPA implícito
        a0, a1 = tabla[-6]["acciones"], tabla[-1]["acciones"]
        for fs, factor in px["splits"]:
            if tabla[-6]["fin"] < fs:
                a0 *= factor if a1 / a0 > 1.5 or factor < 1 else 1
        cambio = a1 / a0 - 1
        if -0.6 < cambio < -0.08:
            s("positivo", f"Recompra de acciones: el número de acciones bajó {abs(cambio) * 100:.0f}% en cinco años.")
        elif 0.10 < cambio < 1.0:
            s("riesgo", f"Dilución: el número de acciones subió {cambio * 100:.0f}% en cinco años.")
    sbc_ing = _div(t["sbc"], t["ingresos"])
    if sbc_ing is not None and sbc_ing > 0.08:
        s("riesgo", f"Paga mucho en acciones a sus empleados: {sbc_ing * 100:.0f}% de las ventas. El flujo de caja 'normal' lo esconde; aquí ya se resta.")
    neg = sum(1 for r in tabla[-5:] if r["fcf"] is not None and r["fcf"] < 0)
    if neg >= 2:
        s("riesgo", f"Flujo de caja libre negativo en {neg} de los últimos 5 años.")
    if (t["util_neta"] or 0) < 0:
        s("riesgo", "Pierde dinero en los últimos doce meses.")
    if financiero:
        s("nota", "Empresa financiera o inmobiliaria: el DCF por flujo de caja libre no es el método adecuado; mirar utilidad, valor en libros y dividendos.")
    if ins:
        if ins["compras_monto"] > 250_000 and ins["compradores"] >= 2:
            s("positivo", f"{ins['compradores']} insiders compraron acciones con su propio dinero en los últimos 12 meses (${ins['compras_monto'] / 1e6:,.1f} M).")
        elif ins["compras_monto"] > 100_000:
            s("positivo", f"Compra de insiders en el mercado en los últimos 12 meses (${ins['compras_monto'] / 1e6:,.2f} M).")
    if dcf and dcf["aplicable"] and (dcf["escenarios"]["base"].get("peso_terminal") or 0) > 0.75:
        s("nota", f"El {dcf['escenarios']['base']['peso_terminal'] * 100:.0f}% del valor del DCF viene de después del año 10: el resultado es muy sensible a los supuestos.")

    # ---- veredicto numérico (solo aritmética; la conclusión cualitativa va aparte)
    veredicto = None
    if dcf and dcf["aplicable"] and not financiero:
        e = dcf["escenarios"]
        vp, vb, vo = (e[k].get("valor_accion") for k in ("pesimista", "base", "optimista"))
        if vb and vb > 0:
            margen = vb / precio - 1
            if precio < vp:
                zona = "Bajo el escenario pesimista"
            elif margen >= 0.25:
                zona = "Descuento amplio sobre el valor base"
            elif margen >= 0.0:
                zona = "Algo por debajo del valor base"
            elif precio <= vo:
                zona = "Entre el valor base y el optimista"
            else:
                zona = "Por encima del escenario optimista"
            veredicto = {"zona": zona, "margen_seguridad": margen, "valor_pes": vp, "valor_base": vb, "valor_opt": vo}

    inv_ruta = os.path.join(datos.RAIZ, "investigacion", f"{ticker}.json")
    investigacion = json.load(open(inv_ruta)) if os.path.exists(inv_ruta) else None

    return {"ticker": ticker, "nombre": perfil.get("nombre") or h.get("entityName"), "cik": cik,
            "sector": sector, "industria": perfil.get("sic_desc"), "bolsa": perfil.get("bolsa"),
            "cierre_fiscal": perfil.get("cierre_fiscal"), "web": perfil.get("web"),
            "cap_bursatil": cap, "valor_empresa": ve, "tamano": V.nivel_riesgo(cap), "financiero": financiero,
            "acciones": acciones, "acciones_metodo": metodo_acc, "acciones_fecha": f_acc,
            "precio": precio_d, "ttm": t, "balance": bal, "historia": tabla,
            "crecimiento": {"ventas_3a": crec3, "ventas_5a": crec5, "ventas_10a": crec10},
            "multiplos": mult, "per_historia": per_hist, "dcf": dcf, "veredicto": veredicto,
            "senales": senales, "insiders": ins, "investigacion": investigacion,
            "generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "fuentes": {"fundamentales": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(cik):010d}&type=10-K",
                        "precios": "Yahoo Finance"}}


if __name__ == "__main__":
    for tk in sys.argv[1:]:
        d = ficha(tk)
        os.makedirs(os.path.join(datos.RAIZ, "datos", "fichas"), exist_ok=True)
        with open(os.path.join(datos.RAIZ, "datos", "fichas", f"{tk.upper()}.json"), "w") as f:
            json.dump(d, f, separators=(",", ":"))
        m, v = d["multiplos"], d["veredicto"]
        pct = lambda x: "s/d" if x is None else f"{x * 100:.1f}%"
        num = lambda x: "s/d" if x is None else f"{x:.1f}"
        print(f"{tk.upper():6} {d['nombre'][:28]:28} {d['sector']:20} ${d['precio']['ultimo']:>8.2f} cap ${d['cap_bursatil'] / 1e9:>7.1f}MM "
              f"PER {num(m['per'])} (med {num(m['per_mediana_10a'])}) VE/EBIT {num(m['ve_ebit'])} FCF-SBC {pct(m['rend_fcf_sbc'])} ROIC {pct(m['roic'])}")
        if d["dcf"]:
            e = d["dcf"]["escenarios"]
            print("        DCF pes/base/opt:", *(f"${e[k].get('valor_accion', 0) or 0:,.0f} (g {e[k]['g1'] * 100:.1f}%, m {e[k]['margen'] * 100:.1f}%, r {e[k]['r'] * 100:.1f}%)" for k in e),
                  "| implícito", pct(d["dcf"]["crecimiento_implicito"]), "| hist", pct(d["dcf"]["crec_hist"]))
        if v: print("        →", v["zona"], pct(v["margen_seguridad"]))
        for x in d["senales"]: print("        ·", x["tipo"], x["texto"])
        i = d["insiders"]
        if i: print(f"        insiders: {i['formularios']} F4, compras ${i['compras_monto']/1e6:.2f}M ({i['compradores']}), ventas ${i['ventas_monto']/1e6:.1f}M ({i['vendedores']}), {len(i['personas'])} personas")
