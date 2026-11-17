"""El Universo: una fila estandarizada por empresa.

- Las ~3.000 mayores que reportan a la SEC con estados US GAAP (API 'frames').
- Más las extranjeras que cotizan en NYSE/Nasdaq (módulo extranjeras.py).
Método de valorización según el negocio:
  · DCF de caja libre, descontado al costo de capital (WACC) de su sector.
  · Bancos y aseguradoras: valor libro × (ROE − g)/(Ke − g).
  · Inmobiliarias (REIT): FFO como renta creciente.
Mismas compuertas de calidad para todas; cada fila dice si pasa y, si no, por qué.
"""
import json, os, sys, statistics, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos, fundamentales as F, valoracion as V, sectores
from screener import _flujo, _saldo, _acciones_recientes, ALIAS_CIK, ANIO

SIC_CACHE = os.path.join(datos.RAIZ, "datos", "sic.json")
DA = ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet", "Depreciation"]


def _sic(ciks, log):
    cache = json.load(open(SIC_CACHE)) if os.path.exists(SIC_CACHE) else {}
    faltan = [c for c in ciks if str(c) not in cache]
    for i, c in enumerate(faltan):
        try:
            d = json.loads(datos.get(f"https://data.sec.gov/submissions/CIK{int(c):010d}.json", ttl_horas=0, guardar=False))
            cache[str(c)] = [d.get("sic"), d.get("sicDescription"), (d.get("exchanges") or [None])[0]]
        except Exception:
            cache[str(c)] = [None, None, None]
        if i % 200 == 199:
            json.dump(cache, open(SIC_CACHE, "w")); log(f"  sectores: {i + 1}/{len(faltan)}")
    json.dump(cache, open(SIC_CACHE, "w"))
    return cache


def _saldo_en(etiqueta, periodo):
    return {f["cik"]: f["val"] for f in datos.marco(etiqueta, periodo)}


# Empresas que presentan 10-K (como si fueran de EE.UU.) pero cotizan en ADR: acciones ordinarias por ADR
ADR_DOMESTICO = {"ONC": 13}   # BeOne Medicines (antes BeiGene)


def construir(tope=3000, verbose=True, extranjeras=True):
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    lista, vistos = [], set()
    for t in datos.tickers_sec():
        if t["cik"] in vistos:
            continue
        vistos.add(t["cik"]); lista.append(t)
    lista = lista[:tope]
    A = {}
    for nombre, et in [("ing", F.INGRESOS), ("uo", F.UTIL_OPER), ("un", F.UTIL_NETA[:1]), ("fo", F.FLUJO_OPER),
                       ("cx", F.CAPEX), ("sbc", F.SBC), ("ai", F.ANTES_IMP), ("int", F.INTERES), ("imp", F.IMPUESTO), ("da", DA)]:
        A[nombre] = _flujo(et, ANIO)
    for a in (ANIO - 1, ANIO - 2):
        for nombre, et in [("ing", F.INGRESOS), ("fo", F.FLUJO_OPER), ("cx", F.CAPEX), ("sbc", F.SBC), ("un", F.UTIL_NETA[:1])]:
            A[f"{nombre}{a}"] = _flujo(et, a)
    A["ing_3"] = _flujo(F.INGRESOS, ANIO - 3); A["ing_5"] = _flujo(F.INGRESOS, ANIO - 5)
    A["un_3"] = _flujo(F.UTIL_NETA[:1], ANIO - 3)
    A["uo_3"] = _flujo(F.UTIL_OPER, ANIO - 3); A["ai_3"] = _flujo(F.ANTES_IMP, ANIO - 3); A["int_3"] = _flujo(F.INTERES, ANIO - 3)
    A["acc"] = _acciones_recientes(); A["bpa"] = _flujo(F.BPA, ANIO, "USD-per-shares")
    S = {e: _saldo(e) for e in [
        "CashAndCashEquivalentsAtCarryingValue", "ShortTermInvestments", "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent", "DebtSecuritiesCurrent", "OtherShortTermInvestments",
        "CashCashEquivalentsAndShortTermInvestments", "MarketableSecuritiesNoncurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent", "AvailableForSaleSecuritiesDebtSecurities",
        "DebtCurrent", "LongTermDebtCurrent", "ShortTermBorrowings", "CommercialPaper", "LongTermDebtNoncurrent",
        "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligationsCurrent",
        "DebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        "DebtLongtermAndShorttermCombinedAmount", "StockholdersEquity"]}
    PAT = {a: _saldo_en("StockholdersEquity", f"CY{a}Q4I") for a in (ANIO, ANIO - 1, ANIO - 2)}
    # Respaldo: etiquetas alternativas (REITs, aseguradoras, empresas con interés minoritario)
    def _completar(m, otro):
        for k, v in otro.items():
            m.setdefault(k, v)
    UN_ALT = ["NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"]
    for clave, anio in (("un", ANIO), (f"un{ANIO - 1}", ANIO - 1), (f"un{ANIO - 2}", ANIO - 2), ("un_3", ANIO - 3)):
        for e in UN_ALT:
            _completar(A[clave], _flujo([e], anio))
    PAT_ALT = "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    _completar(S["StockholdersEquity"], _saldo(PAT_ALT))
    for a in (ANIO, ANIO - 1, ANIO - 2):
        _completar(PAT[a], _saldo_en(PAT_ALT, f"CY{a}Q4I"))
    for periodo in ("CY2025", "CY2026Q1", "CY2026Q2", "CY2026Q3"):
        _completar(A["acc"], {f["cik"]: f["val"] for f in datos.marco("WeightedAverageNumberOfSharesOutstandingBasic", periodo, "shares")})
    log("marcos contables listos")
    sic = _sic([t["cik"] for t in lista], log)
    log("sectores listos")

    filas = []
    for t in lista:
        c = ALIAS_CIK.get(t["cik"], t["cik"])
        g = lambda k: A[k].get(c)
        s = lambda e: S[e].get(c, 0.0)
        sc = sic.get(str(t["cik"])) or [None, None, None]
        f = {"cik": c, "t": t["ticker"], "n": t["nombre"], "s": sectores.sector(sc[0]), "ind": sc[1], "sic": sc[0], "b": sc[2],
             "e": 0, "m": None, "met": "DCF"}
        filas.append(f)
        ing, fo, un = g("ing"), g("fo"), g("un")
        f["ing"], f["un"] = ing, un
        acc = g("acc")
        if not acc and un and g("bpa") and un / g("bpa") > 0:
            acc = un / g("bpa")
        f["acc"] = acc
        # Control de escala: algunas empresas reportan la utilidad con un error de unidades (×1.000 o ×1.000.000).
        # Si la utilidad no cuadra con utilidad por acción × acciones, se usa esa estimación verificable.
        # Se decide cuál de las dos está mal: una utilidad mayor que las ventas es imposible (error en la utilidad);
        # si la utilidad es verosímil, el error está en el número de acciones.
        bpa = g("bpa")
        if un and bpa and acc:
            est = bpa * acc
            # solo errores de escala (100 veces o más): diferencias menores suelen ser divisiones de acciones,
            # que las acciones del último trimestre ya reflejan
            if est and not (1 / 100 < un / est < 100):
                # se guardan las dos alternativas; se elige con el precio (más abajo), solo si la original es imposible
                f["un_alt"] = est
                if un / bpa > 0:
                    f["acc_alt"] = un / bpa
        efectivo = s("CashAndCashEquivalentsAtCarryingValue")
        inv_cp = max(s("ShortTermInvestments"), s("MarketableSecuritiesCurrent"),
                     s("AvailableForSaleSecuritiesDebtSecuritiesCurrent"), s("DebtSecuritiesCurrent"), s("OtherShortTermInvestments"))
        caja = max(efectivo + inv_cp, s("CashCashEquivalentsAndShortTermInvestments"))
        inv_lp = max(s("MarketableSecuritiesNoncurrent"), s("AvailableForSaleSecuritiesDebtSecuritiesNoncurrent"),
                     s("AvailableForSaleSecuritiesDebtSecurities") - (caja - efectivo), 0.0)
        caja += inv_lp
        corto = max(s("DebtCurrent"), s("LongTermDebtCurrent") + s("ShortTermBorrowings") + s("CommercialPaper"),
                    s("LongTermDebtAndCapitalLeaseObligationsCurrent"))
        deuda = max(s("DebtLongtermAndShorttermCombinedAmount"),
                    max(s("LongTermDebtNoncurrent"), s("LongTermDebtAndCapitalLeaseObligations")) + corto,
                    s("LongTermDebt") + s("ShortTermBorrowings") + s("CommercialPaper"),
                    s("DebtAndCapitalLeaseObligations"), s("LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"))
        pat = S["StockholdersEquity"].get(c)
        i3, i5 = A["ing_3"].get(c), A["ing_5"].get(c)
        f["c3"] = (ing / i3) ** (1 / 3) - 1 if ing and i3 and i3 > 0 and ing > 0 else None
        f["c5"] = (ing / i5) ** (1 / 5) - 1 if ing and i5 and i5 > 0 and ing > 0 else None

        # ---- financieras e inmobiliarias: su propio método
        if f["s"] in ("Financiero", "Inmobiliario"):
            if un is None or not pat or not acc:
                f["m"] = "Sin utilidad, patrimonio o acciones en formato estándar"; continue
            roes = [A[k].get(c) / PAT[a][c] for k, a in (("un", ANIO), (f"un{ANIO - 1}", ANIO - 1), (f"un{ANIO - 2}", ANIO - 2))
                    if A[k].get(c) is not None and PAT[a].get(c)]
            f.update(e=1, pat=pat, dn=deuda - caja, roe=statistics.median(roes) if roes else un / pat,
                     un3=A["un_3"].get(c), bvps=pat / acc)
            if f["s"] == "Inmobiliario":
                f["met"] = "FFO"; f["ffo"] = un + (g("da") or 0); f["ffo_ps"] = f["ffo"] / acc
                f["dnffo"] = f["dn"] / f["ffo"] if f["ffo"] > 0 else None
            else:
                f["met"] = "P/VL-ROE"
            continue

        if ing is None or fo is None:
            f["m"] = "No reporta ventas o flujo de caja en formato estándar"; continue
        uo = g("uo")
        if uo is None and g("ai") is not None:
            uo = g("ai") + (g("int") or 0)
        uo3 = A["uo_3"].get(c)
        if uo3 is None and A["ai_3"].get(c) is not None:
            uo3 = A["ai_3"][c] + (A["int_3"].get(c) or 0)
        margenes = []
        for a in ("", str(ANIO - 1), str(ANIO - 2)):
            i_, f_ = A[f"ing{a}"].get(c), A[f"fo{a}"].get(c)
            if i_ and f_ is not None:
                margenes.append((f_ - (A[f"cx{a}"].get(c) or 0) - (A[f"sbc{a}"].get(c) or 0)) / i_)
        tasa = V.limitar((g("imp") or 0) / g("ai"), 0, 0.35) if g("ai") and g("ai") > 0 else 0.21
        capital = (pat or 0) + deuda - caja
        f.update(uo=uo, fcf=fo - (g("cx") or 0) - (g("sbc") or 0), dn=deuda - caja,
                 mo=uo / ing if uo is not None and ing else None,
                 mo3=uo3 / i3 if uo3 is not None and i3 else None,
                 roic=uo * (1 - tasa) / capital if uo and capital > 0 else None,
                 dne=(deuda - caja) / uo if uo and uo > 0 else None,
                 mn=statistics.median(margenes) if margenes else None, e=1)
        if ing < 300e6: f["m"] = "Ventas menores a $300 millones"
        elif not acc: f["m"] = "Sin número de acciones en formato estándar"
        elif uo is None or uo <= 0 or f["fcf"] <= 0: f["m"] = "No gana dinero o no genera caja libre"
        elif f["c3"] is None or f["c3"] < -0.01: f["m"] = "Ventas en caída a tres años, o sin historia suficiente"
        elif f["dne"] is not None and f["dne"] > 3: f["m"] = "Deuda neta mayor a 3 veces la utilidad operativa"
        elif f["mo3"] and f["mo3"] > 0 and f["mo"] < 0.7 * f["mo3"]: f["m"] = "Margen operativo en deterioro"
        elif f["roic"] is None or f["roic"] < 0.10: f["m"] = "Retorno sobre capital menor a 10%"
        elif f["mn"] is None or f["mn"] <= 0: f["m"] = "Flujo de caja normalizado negativo"
        else: f["e"] = 2
    con = [f for f in filas if f["e"] >= 1 and f.get("acc")]
    log(f"con datos: {len(con)}")
    precios = datos.ultimos_precios([f["t"].replace(".", "-") for f in con])
    log(f"precios: {len(precios)}")

    for f in con:
        p = precios.get(f["t"].replace(".", "-"))
        if not p:
            if f["e"] == 2: f["e"], f["m"] = 1, "Sin precio disponible"
            continue
        if f["t"] in ADR_DOMESTICO:          # reporta como empresa de EE.UU. pero cotiza en ADR
            f["acc"] = f["acc"] / ADR_DOMESTICO[f["t"]]
        cap = p * f["acc"]
        # verosímil: P/U entre 1 y 1.000 y valor en bolsa entre 0.05 y 200 veces las ventas
        verosimil = lambda c, u: (not u or u <= 0 or 1 <= c / u <= 1000) and (not f.get("ing") or f["ing"] <= 0 or 0.05 <= c / f["ing"] <= 200)
        if not verosimil(cap, f.get("un")):
            if f.get("acc_alt") and verosimil(p * f["acc_alt"], f["un"]):
                f["acc"] = f["acc_alt"]; cap = p * f["acc"]; f["corregido"] = "acciones"
            elif f.get("un_alt") and verosimil(cap, f["un_alt"]):
                f["un"] = f["un_alt"]; f["corregido"] = "utilidad"
        f.update(p=p, cap=cap, per=cap / f["un"] if f.get("un") and f["un"] > 0 else None)
        if f["met"] == "P/VL-ROE":
            esc = V.escenarios_financiera(f["bvps"], f["roe"], cap, "Financiero")
            f.update(ke=V.tasa_descuento(cap, "Financiero", "ke"), pb=cap / f["pat"] if f["pat"] > 0 else None)
            if not f["m"]:
                if f["un"] <= 0: f["m"] = "No gana dinero"
                elif f["roe"] < 0.08: f["m"] = "Rentabilidad sobre patrimonio menor a 8%"
                elif f.get("un3") and f["un3"] > 0 and f["un"] < 0.7 * f["un3"]: f["m"] = "Utilidad en caída fuerte frente a hace 3 años"
                else: f["e"] = 2
        elif f["met"] == "FFO":
            esc = V.escenarios_reit(f["ffo_ps"], cap, "Inmobiliario") if f["ffo_ps"] > 0 else None
            f.update(ke=V.tasa_descuento(cap, "Inmobiliario", "ke"), pb=cap / f["pat"] if f["pat"] > 0 else None)
            if not f["m"]:
                if f["ffo"] <= 0: f["m"] = "FFO negativo"
                elif f.get("dnffo") is not None and f["dnffo"] > 10: f["m"] = "Deuda neta mayor a 10 veces el FFO"
                else: f["e"] = 2
        else:
            ve = cap + f["dn"]
            f.update(vee=ve / f["uo"] if f["uo"] and f["uo"] > 0 and ve > 0 else None, rf=f["fcf"] / cap)
            esc = None
            if f.get("mn") and f["mn"] > 0:
                hs = [x for x in (f["c3"], f["c5"]) if x is not None]
                esc = V.escenarios(min(hs) if hs else None, f["mn"], f["ing"], f["dn"], f["acc"], cap, sector=f["s"])
                f["wacc"] = esc["base"]["r"]
        if esc and esc["base"].get("valor_accion") and esc["base"]["valor_accion"] > 0:
            f.update(vp=esc["pesimista"]["valor_accion"], vb=esc["base"]["valor_accion"], vo=esc["optimista"]["valor_accion"])
            f["pot"] = f["vb"] / p - 1
            if f["e"] == 2 and (f["pot"] > 3 or (f.get("rf") or 0) > 0.30):
                f["e"], f["m"] = 1, "Cifras incoherentes (posible división de acciones o dato faltante)"
        elif f["e"] == 2 and f["met"] == "DCF":
            f["e"], f["m"] = 1, "DCF no aplicable"
        if f["e"] == 2 and cap < 2e9:
            f["e"], f["m"] = 1, "Capitalización menor a $2 mil millones"
        if f["e"] == 2 and f["b"] not in ("NYSE", "Nasdaq"):
            f["e"], f["m"] = 1, "No cotiza en NYSE ni Nasdaq"

    if extranjeras:
        import extranjeras as X
        try:
            # Las que presentan 20-F/40-F son extranjeras aunque reporten con normas de EE.UU. (Alibaba, PDD, BeOne):
            # sus acciones ordinarias no son sus ADR, así que pasan por el módulo que verifica la relación del ADR.
            emisores_ext = set(X.filers(log))
            nuevas = X.construir({f["cik"] for f in filas if f["e"] >= 1 and f["cik"] not in emisores_ext}, log)
            ciks_x = {f["cik"] for f in nuevas}
            filas = [f for f in filas if f["cik"] not in ciks_x] + nuevas   # la fila extranjera reemplaza a la vacía
        except Exception as e:
            log(f"extranjeras: error {e}")
    ruta = os.path.join(datos.RAIZ, "datos", "filtro.json")
    if os.path.exists(ruta):
        pts = {c["ticker"]: c["puntaje"] for c in json.load(open(ruta))["candidatas"]}
        for f in filas:
            if f["t"] in pts:
                f["pts"] = pts[f["t"]]
    red = {"ing": 0, "un": 0, "uo": 0, "fcf": 0, "acc": 0, "dn": 0, "cap": 0, "p": 2, "vp": 1, "vb": 1, "vo": 1, "c3": 4, "c5": 4,
           "mo": 4, "roic": 3, "dne": 2, "mn": 4, "vee": 1, "rf": 4, "per": 1, "pot": 3, "pts": 3, "roe": 4, "bvps": 2,
           "ffo_ps": 3, "pb": 2, "wacc": 4, "ke": 4, "adr": 4, "prima_pais": 3}
    cols = ["t", "n", "s", "ind", "b", "e", "m", "ing", "un", "uo", "fcf", "acc", "dn", "c3", "c5", "mo", "roic", "dne",
            "mn", "p", "cap", "vee", "rf", "per", "vp", "vb", "vo", "pot", "pts", "met", "roe", "bvps", "ffo_ps", "pb",
            "wacc", "ke", "ext", "pais", "mon", "adr", "adr_via", "prima_pais", "sic", "corregido"]
    def fmt(k, v):
        if v is None or isinstance(v, str) or k in ("e", "ext"):
            return v
        return int(round(v)) if red.get(k, 3) == 0 else round(v, red[k])
    filas_out = [[fmt(k, f.get(k)) for k in cols] for f in filas]
    W = V.tabla_wacc()
    return {"generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "anio_fiscal": ANIO,
            "cols": cols, "filas": filas_out,
            "wacc": {s: x["wacc"] for s, x in W.get("sectores", {}).items()},
            "ke": {s: x["ke"] for s, x in W.get("sectores", {}).items()}, "prima_tamano": W.get("prima_tamano"),
            "conteo": {"total": len(filas), "con_datos": sum(1 for f in filas if f["e"] >= 1),
                       "con_precio": sum(1 for f in filas if f.get("p")), "pasan": sum(1 for f in filas if f["e"] == 2),
                       "extranjeras": sum(1 for f in filas if f.get("ext")),
                       "financieras": sum(1 for f in filas if f["met"] != "DCF" and f["e"] >= 1)}}


if __name__ == "__main__":
    U = construir()
    with open(os.path.join(datos.RAIZ, "datos", "universo.json"), "w") as f:
        json.dump(U, f, separators=(",", ":"), ensure_ascii=False)
    print(U["conteo"], os.path.getsize(os.path.join(datos.RAIZ, "datos", "universo.json")))
    print("UNIVERSO TERMINADO")
