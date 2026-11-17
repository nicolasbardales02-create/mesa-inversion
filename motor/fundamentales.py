"""Normaliza los estados financieros de SEC EDGAR (XBRL) a series anuales y TTM.

Las empresas usan etiquetas distintas para lo mismo; aquí se listan las equivalencias.
Cada cifra es la reportada por la empresa a la SEC: no hay estimaciones.
"""
import datetime as dt

INGRESOS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet"]
UTIL_OPER = ["OperatingIncomeLoss"]
UTIL_NETA = ["NetIncomeLoss", "ProfitLoss"]
FLUJO_OPER = ["NetCashProvidedByUsedInOperatingActivities",
              "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
         "PaymentsToAcquireOtherPropertyPlantAndEquipment"]
SBC = ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"]
DEPREC = ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
          "DepreciationAndAmortization"]
BPA = ["EarningsPerShareDiluted"]
ACC_DIL = ["WeightedAverageNumberOfDilutedSharesOutstanding"]
DIVID = ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"]
RECOMPRA = ["PaymentsForRepurchaseOfCommonStock"]
IMPUESTO = ["IncomeTaxExpenseBenefit"]
INTERES = ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"]
ANTES_IMP = ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
             "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"]


def _d(s):
    return dt.date.fromisoformat(s)


def _unidades(h, etiqueta, unidad):
    nodo = h.get("facts", {}).get("us-gaap", {}).get(etiqueta) or h.get("facts", {}).get("dei", {}).get(etiqueta)
    if not nodo:
        return []
    u = nodo.get("units", {})
    if unidad in u:
        return u[unidad]
    return []


def anuales(h, etiquetas, unidad="USD", original=False):
    """{fecha_fin: valor} de periodos de ~1 año. original=True toma el dato tal
    como se reportó por primera vez (para valoraciones 'en su momento')."""
    por_etiqueta = []
    for e in etiquetas:
        m = {}
        for f in _unidades(h, e, unidad):
            if "start" not in f:
                continue
            dur = (_d(f["end"]) - _d(f["start"])).days
            if not 345 <= dur <= 380:
                continue
            previo = m.get(f["end"])
            if previo is None or (f["filed"] < previo["filed"] if original else f["filed"] >= previo["filed"]):
                m[f["end"]] = f
        por_etiqueta.append(m)
    salida = {}
    for m in por_etiqueta:
        for fin, f in m.items():
            if fin not in salida or abs(f["val"]) > abs(salida[fin]["val"]):
                salida[fin] = f
    return salida


def instantes(h, etiquetas, unidad="USD"):
    """{fecha: valor} de saldos de balance; suma entre etiquetas NO, toma la primera disponible por fecha."""
    salida = {}
    for e in etiquetas:
        for f in _unidades(h, e, unidad):
            if "start" in f:
                continue
            previo = salida.get(f["end"])
            if previo is None or f["filed"] >= previo["filed"]:
                if previo is None or previo.get("_e") == e or f["filed"] > previo["filed"]:
                    g = dict(f); g["_e"] = e
                    salida[f["end"]] = g
    return salida


def _cerca(m, fecha, tolerancia=10):
    """Valor del diccionario {fecha: hecho} más cercano a `fecha` dentro de la tolerancia (días)."""
    mejor, dist = None, tolerancia + 1
    obj = _d(fecha) if isinstance(fecha, str) else fecha
    for k, f in m.items():
        x = abs((_d(k) - obj).days)
        if x < dist:
            mejor, dist = f, x
    return mejor


def ttm(h, etiquetas, unidad="USD"):
    """Últimos doce meses = último año fiscal + acumulado del año en curso − acumulado del año previo.
    Devuelve (valor, fecha_fin) o (None, None)."""
    mejor = (None, None)
    for e in etiquetas:
        hechos = [f for f in _unidades(h, e, unidad) if "start" in f]
        if not hechos:
            continue
        fin = max(f["end"] for f in hechos)
        del_fin = [f for f in hechos if f["end"] == fin]
        largo = max(del_fin, key=lambda f: ((_d(f["end"]) - _d(f["start"])).days, f["filed"]))
        dur = (_d(largo["end"]) - _d(largo["start"])).days
        if dur >= 345:
            val = largo["val"]
        else:
            ini = _d(largo["start"])
            previo_ytd = None
            for f in hechos:
                d2 = (_d(f["end"]) - _d(f["start"])).days
                if abs(d2 - dur) <= 10 and abs((_d(f["end"]) - (_d(fin) - dt.timedelta(days=365))).days) <= 10:
                    if previo_ytd is None or f["filed"] > previo_ytd["filed"]:
                        previo_ytd = f
            anual = None
            for f in hechos:
                d2 = (_d(f["end"]) - _d(f["start"])).days
                if 345 <= d2 <= 380 and abs((_d(f["end"]) - (ini - dt.timedelta(days=1))).days) <= 10:
                    if anual is None or f["filed"] > anual["filed"]:
                        anual = f
            if previo_ytd is None or anual is None:
                continue
            val = anual["val"] + largo["val"] - previo_ytd["val"]
        if mejor[1] is None or fin > mejor[1] or (fin == mejor[1] and abs(val) > abs(mejor[0])):
            mejor = (val, fin)
    return mejor


def _ultimo_saldo(h, etiqueta, fecha, unidad="USD"):
    f = instantes(h, [etiqueta], unidad).get(fecha)
    return f["val"] if f else 0.0


def balance(h):
    """Caja, deuda y patrimonio del último balance publicado."""
    pat = instantes(h, ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"])
    act = instantes(h, ["Assets"])
    fechas = sorted(set(pat) | set(act))
    if not fechas:
        return None
    fecha = fechas[-1]
    s = lambda e: _ultimo_saldo(h, e, fecha)
    efectivo = s("CashAndCashEquivalentsAtCarryingValue")
    inv_cp = max(s("ShortTermInvestments"), s("MarketableSecuritiesCurrent"),
                 s("AvailableForSaleSecuritiesDebtSecuritiesCurrent"), s("DebtSecuritiesCurrent"),
                 s("OtherShortTermInvestments"))
    caja = max(efectivo + inv_cp, s("CashCashEquivalentsAndShortTermInvestments"))
    inv_cp = caja - efectivo
    inv_lp = max(s("MarketableSecuritiesNoncurrent"), s("AvailableForSaleSecuritiesDebtSecuritiesNoncurrent"),
                 s("AvailableForSaleSecuritiesDebtSecurities") - inv_cp, 0.0)
    corto = max(s("DebtCurrent"), s("LongTermDebtCurrent") + s("ShortTermBorrowings") + s("CommercialPaper"),
                s("LongTermDebtAndCapitalLeaseObligationsCurrent"))
    largo_nc = max(s("LongTermDebtNoncurrent"), s("LongTermDebtAndCapitalLeaseObligations"))
    deuda = max(s("DebtLongtermAndShorttermCombinedAmount"),
                largo_nc + corto,
                s("LongTermDebt") + s("ShortTermBorrowings") + s("CommercialPaper"),
                s("LongTermDebt"), s("DebtAndCapitalLeaseObligations"),
                s("LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"))
    return {"fecha": fecha, "caja": caja, "inversiones_lp": inv_lp, "deuda": deuda,
            "deuda_neta": deuda - caja - inv_lp,
            "patrimonio": (pat.get(fecha) or {}).get("val"), "activos": (act.get(fecha) or {}).get("val")}


def acciones_diluidas(h, splits=()):
    """Acciones diluidas más recientes (promedio ponderado del último periodo reportado),
    ajustadas por splits posteriores a la presentación. Devuelve (acciones, fecha, método)."""
    hechos = [f for f in _unidades(h, ACC_DIL[0], "shares") if "start" in f]
    cand = None
    if hechos:
        fin = max(f["end"] for f in hechos)
        del_fin = [f for f in hechos if f["end"] == fin]
        f = min(del_fin, key=lambda f: ((_d(f["end"]) - _d(f["start"])).days, f["filed"]))
        cand = (f["val"], f["end"], f["filed"], "promedio diluido del último periodo")
    # alternativa: utilidad neta / BPA diluido (sirve para empresas con varias clases de acción)
    un = [f for f in _unidades(h, "NetIncomeLoss", "USD") if "start" in f]
    bp = {(f["start"], f["end"]): f for f in _unidades(h, "EarningsPerShareDiluted", "USD/shares") if "start" in f}
    alt = None
    for f in sorted(un, key=lambda f: (f["end"], f["filed"]), reverse=True):
        b = bp.get((f["start"], f["end"]))
        if b and b["val"] and f["val"] and f["val"] / b["val"] > 0:
            alt = (f["val"] / b["val"], f["end"], max(f["filed"], b["filed"]), "utilidad neta / BPA diluido")
            break
    elegido = cand
    if alt and (cand is None or alt[1] > cand[1]):
        elegido = alt
    if elegido is None:
        return None, None, None
    n, fin, presentado, metodo = elegido
    for fecha, factor in splits:
        if fecha > presentado:
            n *= factor
    return n, fin, metodo


def historia(h, anios=11):
    """Tabla anual de los últimos ejercicios fiscales."""
    ing, uo, un = anuales(h, INGRESOS), anuales(h, UTIL_OPER), anuales(h, UTIL_NETA[:1])
    fo, cx, sb, dp = anuales(h, FLUJO_OPER), anuales(h, CAPEX), anuales(h, SBC), anuales(h, DEPREC)
    bpa = anuales(h, BPA, "USD/shares"); acc = anuales(h, ACC_DIL, "shares")
    dv, rc = anuales(h, DIVID), anuales(h, RECOMPRA)
    imp, ai, inte = anuales(h, IMPUESTO), anuales(h, ANTES_IMP), anuales(h, INTERES)
    pat = instantes(h, ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"])
    fines = sorted(set(ing) | set(un))
    # descarta periodos anuales solapados (cambios de ejercicio): conserva los separados >= 300 días
    limpios = []
    for f in fines:
        if not limpios or (_d(f) - _d(limpios[-1])).days >= 300:
            limpios.append(f)
        else:
            limpios[-1] = f
    filas = []
    v = lambda m, f: (m[f]["val"] if f in m else None)
    for f in limpios[-anios:]:
        fila = {"fin": f, "ingresos": v(ing, f), "util_oper": v(uo, f), "util_neta": v(un, f),
                "flujo_oper": v(fo, f), "capex": v(cx, f), "sbc": v(sb, f), "deprec": v(dp, f),
                "bpa": v(bpa, f), "acciones": v(acc, f), "dividendos": v(dv, f), "recompras": v(rc, f),
                "impuesto": v(imp, f), "antes_imp": v(ai, f)}
        p = _cerca(pat, f, 5)
        fila["patrimonio"] = p["val"] if p else None
        fila["ebit_estimado"] = False
        if fila["util_oper"] is None and fila["antes_imp"] is not None:
            # sin utilidad operativa reportada: utilidad antes de impuestos + intereses
            fila["util_oper"] = fila["antes_imp"] + (v(inte, f) or 0)
            fila["ebit_estimado"] = True
        if fila["flujo_oper"] is not None:
            fila["fcf"] = fila["flujo_oper"] - (fila["capex"] or 0)
            fila["fcf_sbc"] = fila["fcf"] - (fila["sbc"] or 0)
        else:
            fila["fcf"] = fila["fcf_sbc"] = None
        filas.append(fila)
    return filas


def resumen_ttm(h):
    """Cifras de los últimos doce meses."""
    r = {}
    for nombre, et in [("ingresos", INGRESOS), ("util_oper", UTIL_OPER), ("util_neta", UTIL_NETA[:1]),
                       ("flujo_oper", FLUJO_OPER), ("capex", CAPEX), ("sbc", SBC), ("deprec", DEPREC)]:
        val, fin = ttm(h, et)
        r[nombre] = val
        if nombre == "ingresos":
            r["fin"] = fin
    val, _ = ttm(h, BPA, "USD/shares")
    r["bpa"] = val
    r["ebit_estimado"] = False
    if r.get("util_oper") is None:
        ai, _ = ttm(h, ANTES_IMP); it, _ = ttm(h, INTERES)
        if ai is not None:
            r["util_oper"] = ai + (it or 0); r["ebit_estimado"] = True
    if r.get("flujo_oper") is not None:
        r["fcf"] = r["flujo_oper"] - (r.get("capex") or 0)
        r["fcf_sbc"] = r["fcf"] - (r.get("sbc") or 0)
    else:
        r["fcf"] = r["fcf_sbc"] = None
    return r


def originales(h):
    """Datos anuales tal como se publicaron por primera vez, con su fecha de presentación."""
    bpa = anuales(h, BPA, "USD/shares", original=True)
    acc = anuales(h, ACC_DIL, "shares", original=True)
    fo = anuales(h, FLUJO_OPER, original=True); cx = anuales(h, CAPEX, original=True)
    salida = []
    for fin, f in sorted(bpa.items()):
        fila = {"fin": fin, "presentado": f["filed"], "bpa": f["val"]}
        if fin in fo and fin in acc and acc[fin]["val"]:
            fila["fcf_accion"] = (fo[fin]["val"] - (cx[fin]["val"] if fin in cx else 0)) / acc[fin]["val"]
        salida.append(fila)
    return salida
