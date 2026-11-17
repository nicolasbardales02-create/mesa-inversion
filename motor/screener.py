"""El Filtro: recorre todas las empresas que reportan a la SEC y ordena las candidatas.

Usa la API 'frames' de EDGAR (un concepto contable para todas las empresas a la vez).
Compuertas de calidad primero (para evitar trampas de valor), luego ranking por precio.
"""
import json, os, sys, statistics, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos, fundamentales as F, valoracion as V, sectores

ANIO = 2025          # último ejercicio completo de todas las empresas
SALDO = "CY2026Q2I"  # balance más reciente publicado por todas


def _flujo(etiquetas, anio, unidad="USD", modo="max"):
    m = {}
    for e in etiquetas:
        for f in datos.marco(e, f"CY{anio}", unidad):
            v = f["val"]
            if f["cik"] not in m or abs(v) > abs(m[f["cik"]]):
                m[f["cik"]] = v
    return m


# Reorganizaciones: el ticker pasó a un registro nuevo y la historia contable quedó en el anterior
ALIAS_CIK = {2115436: 34088}  # ExxonMobil Holdings -> Exxon Mobil Corp


def _acciones_recientes():
    """Acciones diluidas del trimestre más reciente (ya reflejan divisiones de acciones de 2026);
    si no hay dato trimestral, se usa el anual."""
    m = {}
    for periodo in ("CY2025", "CY2026Q1", "CY2026Q2", "CY2026Q3"):
        for f in datos.marco(F.ACC_DIL[0], periodo, "shares"):
            m[f["cik"]] = f["val"]
    return m


def _saldo(etiqueta):
    return {f["cik"]: f["val"] for f in datos.marco(etiqueta, SALDO)}


_ruta_sic = os.path.join(datos.RAIZ, "datos", "sic.json")
SIC = json.load(open(_ruta_sic)) if os.path.exists(_ruta_sic) else {}


def construir(tope_universo=3000, minimo_cap=2e9, verbose=True):
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    lista, vistos = [], set()
    for t in datos.tickers_sec():
        if t["cik"] in vistos:
            continue
        vistos.add(t["cik"]); lista.append(t)
    lista = lista[:tope_universo]
    log(f"universo inicial: {len(lista)} empresas")

    A = {}
    for nombre, et in [("ing", F.INGRESOS), ("uo", F.UTIL_OPER), ("un", F.UTIL_NETA[:1]), ("fo", F.FLUJO_OPER),
                       ("cx", F.CAPEX), ("sbc", F.SBC), ("ai", F.ANTES_IMP), ("int", F.INTERES), ("imp", F.IMPUESTO)]:
        A[nombre] = _flujo(et, ANIO)
    for a in (ANIO - 1, ANIO - 2):
        for nombre, et in [("ing", F.INGRESOS), ("fo", F.FLUJO_OPER), ("cx", F.CAPEX), ("sbc", F.SBC)]:
            A[f"{nombre}{a}"] = _flujo(et, a)
    A["ing_3"] = _flujo(F.INGRESOS, ANIO - 3); A["ing_5"] = _flujo(F.INGRESOS, ANIO - 5)
    A["uo_3"] = _flujo(F.UTIL_OPER, ANIO - 3); A["ai_3"] = _flujo(F.ANTES_IMP, ANIO - 3); A["int_3"] = _flujo(F.INTERES, ANIO - 3)
    A["acc"] = _acciones_recientes(); A["bpa"] = _flujo(F.BPA, ANIO, "USD-per-shares")
    S = {e: _saldo(e) for e in [
        "CashAndCashEquivalentsAtCarryingValue", "ShortTermInvestments", "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent", "DebtSecuritiesCurrent", "OtherShortTermInvestments",
        "CashCashEquivalentsAndShortTermInvestments", "MarketableSecuritiesNoncurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent", "AvailableForSaleSecuritiesDebtSecurities",
        "DebtCurrent", "LongTermDebtCurrent", "ShortTermBorrowings", "CommercialPaper", "LongTermDebtNoncurrent",
        "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligationsCurrent",
        "DebtLongtermAndShorttermCombinedAmount", "StockholdersEquity"]}
    log("marcos contables descargados")

    filas, descartes = [], {}
    def fuera(motivo):
        descartes[motivo] = descartes.get(motivo, 0) + 1
    for t in lista:
        c = ALIAS_CIK.get(t["cik"], t["cik"])
        g = lambda k: A[k].get(c)
        s = lambda e: S[e].get(c, 0.0)
        ing, fo = g("ing"), g("fo")
        if ing is None or fo is None:
            fuera("sin datos US-GAAP completos"); continue
        if ing < 300e6:
            fuera("ventas menores a $300 M"); continue
        uo = g("uo")
        if uo is None and g("ai") is not None:
            uo = g("ai") + (g("int") or 0)
        uo3 = A["uo_3"].get(c)
        if uo3 is None and A["ai_3"].get(c) is not None:
            uo3 = A["ai_3"][c] + (A["int_3"].get(c) or 0)
        fcf_sbc = fo - (g("cx") or 0) - (g("sbc") or 0)
        acc = g("acc")
        if not acc and g("un") and g("bpa"):
            acc = g("un") / g("bpa") if g("un") / g("bpa") > 0 else None
        if not acc:
            fuera("sin número de acciones"); continue
        efectivo = s("CashAndCashEquivalentsAtCarryingValue")
        inv_cp = max(s("ShortTermInvestments"), s("MarketableSecuritiesCurrent"),
                     s("AvailableForSaleSecuritiesDebtSecuritiesCurrent"), s("DebtSecuritiesCurrent"), s("OtherShortTermInvestments"))
        caja = max(efectivo + inv_cp, s("CashCashEquivalentsAndShortTermInvestments"))
        inv_lp = max(s("MarketableSecuritiesNoncurrent"), s("AvailableForSaleSecuritiesDebtSecuritiesNoncurrent"),
                     s("AvailableForSaleSecuritiesDebtSecurities") - (caja - efectivo), 0.0)
        corto = max(s("DebtCurrent"), s("LongTermDebtCurrent") + s("ShortTermBorrowings") + s("CommercialPaper"),
                    s("LongTermDebtAndCapitalLeaseObligationsCurrent"))
        deuda = max(s("DebtLongtermAndShorttermCombinedAmount"),
                    max(s("LongTermDebtNoncurrent"), s("LongTermDebtAndCapitalLeaseObligations")) + corto,
                    s("LongTermDebt") + s("ShortTermBorrowings") + s("CommercialPaper"))
        margenes = []
        for a in ("", str(ANIO - 1), str(ANIO - 2)):
            i_, f_ = A[f"ing{a}"].get(c), A[f"fo{a}"].get(c)
            if i_ and f_ is not None:
                margenes.append((f_ - (A[f"cx{a}"].get(c) or 0) - (A[f"sbc{a}"].get(c) or 0)) / i_)
        filas.append({"cik": c, "ticker": t["ticker"], "nombre": t["nombre"], "ing": ing, "uo": uo, "un": g("un"),
                      "fcf_sbc": fcf_sbc, "acc": acc, "caja": caja + inv_lp, "deuda": deuda,
                      "patrimonio": S["StockholdersEquity"].get(c), "ing_3": A["ing_3"].get(c), "ing_5": A["ing_5"].get(c),
                      "uo_3": uo3, "margen_norm": statistics.median(margenes) if margenes else None,
                      "tasa": V.limitar((g("imp") or 0) / g("ai"), 0, 0.35) if g("ai") and g("ai") > 0 else 0.21})
    log(f"con datos suficientes: {len(filas)}")

    # ---- compuertas de calidad que no dependen del precio (así se piden menos precios)
    sanas = []
    for f in filas:
        dn = f["deuda"] - f["caja"]
        f["deuda_neta"] = dn
        f["crec3"] = (f["ing"] / f["ing_3"]) ** (1 / 3) - 1 if f["ing_3"] and f["ing_3"] > 0 else None
        f["crec5"] = (f["ing"] / f["ing_5"]) ** (1 / 5) - 1 if f["ing_5"] and f["ing_5"] > 0 else None
        f["margen_oper"] = f["uo"] / f["ing"] if f["uo"] is not None else None
        f["margen_oper_3"] = f["uo_3"] / f["ing_3"] if f["uo_3"] is not None and f["ing_3"] else None
        capital = (f["patrimonio"] or 0) + f["deuda"] - f["caja"]
        f["roic"] = f["uo"] * (1 - f["tasa"]) / capital if f["uo"] and capital > 0 else None
        f["dn_ebit"] = dn / f["uo"] if f["uo"] and f["uo"] > 0 else None
        if f["uo"] is None or f["uo"] <= 0 or f["fcf_sbc"] <= 0:
            fuera("no gana dinero o no genera caja"); continue
        if f["crec3"] is None or f["crec3"] < -0.01:
            fuera("ventas en caída a 3 años (o sin historia)"); continue
        if f["dn_ebit"] is not None and f["dn_ebit"] > 3:
            fuera("deuda neta mayor a 3x la utilidad operativa"); continue
        if f["margen_oper_3"] and f["margen_oper_3"] > 0 and f["margen_oper"] < 0.7 * f["margen_oper_3"]:
            fuera("margen operativo en deterioro"); continue
        if f["roic"] is None or f["roic"] < 0.10:
            fuera("retorno sobre capital menor a 10%"); continue
        if f["margen_norm"] is None or f["margen_norm"] <= 0:
            fuera("flujo de caja normalizado negativo"); continue
        sanas.append(f)
    log(f"pasan las compuertas de calidad: {len(sanas)}")

    precios = datos.ultimos_precios([f["ticker"].replace(".", "-") for f in sanas])
    log(f"precios obtenidos: {len(precios)}")
    candidatas, todas = [], []
    for f in sanas:
        p = precios.get(f["ticker"].replace(".", "-"))
        if not p:
            fuera("sin precio"); continue
        cap = p * f["acc"]
        f["precio"], f["cap"] = p, cap
        if cap < minimo_cap:
            fuera("capitalización menor a $2 mil M"); continue
        dn = f["deuda_neta"]
        ve = cap + dn
        f["ve"] = ve
        f["rend_fcf_sbc"] = f["fcf_sbc"] / cap
        f["ve_ebit"] = ve / f["uo"] if ve > 0 else None
        todas.append(f)
        hist = min(x for x in (f["crec3"], f["crec5"]) if x is not None)
        sc = SIC.get(str(f["cik"])) or [None]
        esc = V.escenarios(hist, f["margen_norm"], f["ing"], dn, f["acc"], cap, sector=sectores.sector(sc[0]))
        vb = esc["base"].get("valor_accion")
        if not vb or vb <= 0:
            fuera("DCF no aplicable"); continue
        f["valor_base"], f["valor_pes"], f["valor_opt"] = vb, esc["pesimista"].get("valor_accion"), esc["optimista"].get("valor_accion")
        f["potencial"] = vb / p - 1
        if f["potencial"] > 3 or f["rend_fcf_sbc"] > 0.30:
            fuera("cifras incoherentes (posible split o dato faltante)"); continue
        candidatas.append(f)
    log(f"candidatas con precio y tamaño: {len(candidatas)}")

    def percentil(valores, x, invertido=False):
        r = sum(1 for v in valores if v <= x) / len(valores)
        return 1 - r if invertido else r
    pots = [f["potencial"] for f in candidatas]; rends = [f["rend_fcf_sbc"] for f in candidatas]
    ves = [f["ve_ebit"] for f in candidatas if f["ve_ebit"]]; roics = [min(f["roic"], 1.0) for f in candidatas]
    for f in candidatas:
        f["puntaje"] = (0.35 * percentil(pots, f["potencial"]) + 0.25 * percentil(rends, f["rend_fcf_sbc"])
                        + 0.15 * (percentil(ves, f["ve_ebit"], True) if f["ve_ebit"] else 0.5)
                        + 0.25 * percentil(roics, min(f["roic"], 1.0)))
    candidatas.sort(key=lambda f: -f["puntaje"])

    # sector (una consulta por empresa: solo para las 150 mejores)
    finales = []
    for f in candidatas[:150]:
        sub = datos.presentaciones(f["cik"]) or {}
        f["sector"] = sectores.sector(sub.get("sic")); f["industria"] = sub.get("sicDescription")
        f["bolsa"] = (sub.get("exchanges") or [None])[0]
        if f["sector"] in ("Financiero", "Inmobiliario"):
            fuera("financiera o inmobiliaria (el DCF de caja libre no aplica)"); continue
        if f["bolsa"] not in ("NYSE", "Nasdaq"):
            fuera("no cotiza en NYSE/Nasdaq"); continue
        f["tamano"] = V.nivel_riesgo(f["cap"])
        finales.append(f)
    log(f"finalistas: {len(finales)}")
    claves = ["ticker", "nombre", "sector", "industria", "tamano", "precio", "cap", "ve", "valor_pes", "valor_base",
              "valor_opt", "potencial", "rend_fcf_sbc", "ve_ebit", "roic", "crec3", "crec5", "margen_oper", "dn_ebit", "puntaje", "cik"]
    return {"generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "anio_fiscal": ANIO, "universo": len(lista), "con_datos": len(filas), "sanas": len(sanas), "sobre_minimo": len(todas),
            "pasan": len(candidatas), "descartes": dict(sorted(descartes.items(), key=lambda kv: -kv[1])),
            "pesos": {"potencial DCF base": 0.35, "rendimiento de caja libre": 0.25, "retorno sobre capital": 0.25, "VE/EBIT": 0.15},
            "candidatas": [{k: f.get(k) for k in claves} for f in finales[:80]]}


if __name__ == "__main__":
    r = construir()
    with open(os.path.join(datos.RAIZ, "datos", "filtro.json"), "w") as f:
        json.dump(r, f, separators=(",", ":"))
    print(json.dumps(r["descartes"], ensure_ascii=False, indent=1))
    for c in r["candidatas"][:45]:
        print(f"{c['ticker']:6} {c['nombre'][:26]:26} {c['sector'][:14]:14} cap {c['cap']/1e9:7.1f} pot {c['potencial']*100:6.0f}% fcf {c['rend_fcf_sbc']*100:5.1f}% ve/ebit {c['ve_ebit'] or 0:5.1f} roic {c['roic']*100:5.0f}% crec3 {c['crec3']*100:5.1f}% pts {c['puntaje']:.2f}")
