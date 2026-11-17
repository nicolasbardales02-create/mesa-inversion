"""Empresas extranjeras que cotizan en EE.UU. (presentan informe anual 20-F o 40-F a la SEC).

- Lista: índices oficiales de presentaciones de la SEC (form.gz) de los últimos trimestres,
  cruzados con los tickers de NYSE y Nasdaq.
- Cifras: estados financieros en XBRL (IFRS o US GAAP) en su moneda, convertidos a dólares
  al tipo de cambio actual. El crecimiento se mide en moneda local, sin efecto cambiario.
- Relación del ADR (cuántas acciones de la empresa representa cada título que cotiza en EE.UU.):
  1) en las canadienses (40-F) es 1, porque cotiza la misma acción;
  2) si se conoce su bolsa de origen, se calcula comparando ambos precios;
  3) si no, se busca la frase en la portada del informe anual.
  Sin relación verificada no hay valorización por acción.
"""
import time
import gzip, json, os, re, sys, html, statistics, datetime as dt
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos, valoracion as V, sectores

# bolsa de origen en Yahoo de los ADR más grandes (solo para verificar la relación por precio)
ORIGEN = {"TSM": "2330.TW", "NVO": "NOVO-B.CO", "TM": "7203.T", "SONY": "6758.T", "HMC": "7267.T", "MUFG": "8306.T",
          "SMFG": "8316.T", "MFG": "8411.T", "SHEL": "SHEL.L", "AZN": "AZN.L", "HSBC": "HSBA.L", "UL": "ULVR.L",
          "BP": "BP.L", "GSK": "GSK.L", "DEO": "DGE.L", "BTI": "BATS.L", "RIO": "RIO.L", "RELX": "REL.L", "NGG": "NG.L",
          "VOD": "VOD.L", "LYG": "LLOY.L", "BCS": "BARC.L", "BHP": "BHP.AX", "NVS": "NOVN.SW", "SAP": "SAP.DE",
          "TTE": "TTE.PA", "SNY": "SAN.PA", "BUD": "ABI.BR", "ING": "INGA.AS", "SAN": "SAN.MC", "BBVA": "BBVA.MC",
          "ASML": "ASML.AS", "E": "ENI.MI", "EQNR": "EQNR.OL", "STLA": "STLAM.MI", "INFY": "INFY.NS",
          "HDB": "HDFCBANK.NS", "IBN": "ICICIBANK.NS", "WIT": "WIPRO.NS", "BABA": "9988.HK", "JD": "9618.HK",
          "BIDU": "9888.HK", "NTES": "9999.HK", "TCOM": "9961.HK", "BILI": "9626.HK", "LI": "2015.HK", "NIO": "9866.HK",
          "XPEV": "9868.HK", "ZTO": "2057.HK", "YUMC": "9987.HK", "ABEV": "ABEV3.SA", "PBR": "PETR3.SA",
          "VALE": "VALE3.SA", "ITUB": "ITUB4.SA", "BBD": "BBDC4.SA", "SQM": "SQM-B.SN", "FMX": "FEMSAUBD.MX",
          "AMX": "AMXB.MX", "KB": "105560.KS", "SHG": "055550.KS", "PKX": "005490.KS", "UMC": "2303.TW",
          "ASX": "3711.TW", "CHT": "2412.TW", "ERIC": "ERIC-B.ST", "NOK": "NOKIA.HE", "PHG": "PHIA.AS",
          "SE": None, "ARM": None, "SPOT": None, "NU": None, "PDD": None, "CPNG": None, "MELI": None}
SUBUNIDAD = {"GBp": 100, "GBX": 100, "ILA": 100, "ZAc": 100}
# ADR que cotizan con prima persistente sobre la acción local: la verificación por precio no sirve
RATIO_FIJO = {"TSM": (5, "1 ADR = 5 acciones (el ADR cotiza con prima sobre Taiwán)"),
              "BAP": (1.0, "acción común listada en NYSE y en la Bolsa de Lima")}
# País donde opera, cuando la sede legal es otra (prima de riesgo país)
PAIS_OPERA = {"BAP": "Peru", "IFS": "Peru"}
EMERGENTES = {  # prima país (supuesto, en la línea de las estimaciones de riesgo país de Damodaran)
    "TAIWAN": 0.01, "KOREA": 0.01, "CHILE": 0.01, "CHINA": 0.02, "HONG KONG": 0.015, "INDIA": 0.02, "MEXICO": 0.02,
    "INDONESIA": 0.02, "PERU": 0.02, "COLOMBIA": 0.025, "PHILIPPINES": 0.02, "BRAZIL": 0.03, "SOUTH AFRICA": 0.03,
    "TURKEY": 0.04, "TURKIYE": 0.04, "ARGENTINA": 0.06, "GREECE": 0.02}
NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
       "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "twenty-five": 25, "thirty": 30, "forty": 40, "fifty": 50,
       "one-half": 0.5, "one half": 0.5, "one-third": 1 / 3, "one-fourth": 0.25, "one-quarter": 0.25, "one-fifth": 0.2,
       "one-tenth": 0.1}
REDONDOS = [0.05, 0.1, 0.2, 0.25, 1 / 3, 0.5, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 100]

ETIQ = {
    "ifrs-full": {"ing": ["Revenue", "RevenueFromContractsWithCustomers"],
                  "un": ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"],
                  "uo": ["ProfitLossFromOperatingActivities"],
                  "fo": ["CashFlowsFromUsedInOperatingActivities"],
                  "cx": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "PurchaseOfPropertyPlantAndEquipment"],
                  "cxi": ["PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"],
                  "sbc": ["ExpenseFromSharebasedPaymentTransactionsWithEmployees", "AdjustmentsForSharebasedPayments"],
                  "da": ["DepreciationAndAmortisationExpense", "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss"],
                  "imp": ["IncomeTaxExpenseContinuingOperations"], "ai": ["ProfitLossBeforeTax"],
                  "eps": ["DilutedEarningsLossPerShare", "BasicEarningsLossPerShare"],
                  "pat": ["EquityAttributableToOwnersOfParent", "Equity"], "caja": ["CashAndCashEquivalents"],
                  "deuda": ["Borrowings"], "deuda_lp": ["NoncurrentPortionOfNoncurrentBorrowings", "LongtermBorrowings"],
                  "deuda_cp": ["CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings", "ShorttermBorrowings", "CurrentPortionOfLongtermBorrowings"]},
    "us-gaap": {"ing": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax"],
                "un": ["NetIncomeLoss", "ProfitLoss"], "uo": ["OperatingIncomeLoss"],
                "fo": ["NetCashProvidedByUsedInOperatingActivities"], "cx": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
                "cxi": ["PaymentsToAcquireIntangibleAssets"], "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
                "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"],
                "imp": ["IncomeTaxExpenseBenefit"], "ai": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"],
                "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
                "pat": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
                "caja": ["CashAndCashEquivalentsAtCarryingValue"], "deuda": ["LongTermDebt", "DebtLongtermAndShorttermCombinedAmount"],
                "deuda_lp": ["LongTermDebtNoncurrent"], "deuda_cp": ["LongTermDebtCurrent", "ShortTermBorrowings"]}}
FORMAS = ("20-F", "40-F", "20-F/A", "40-F/A", "10-K", "6-K")


def _d(s):
    return dt.date.fromisoformat(s)


def filers(log):
    hoy = dt.date.today(); trimestres = []
    y, q = hoy.year, (hoy.month - 1) // 3 + 1
    for _ in range(5):
        trimestres.append((y, q)); q -= 1
        if q == 0:
            y, q = y - 1, 4
    ciks = {}
    for y, q in trimestres:
        try:
            b = datos.get(f"https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.gz", ttl_horas=24 * 6, binario=True)
        except Exception as e:
            log(f"  índice {y} T{q}: {e}"); continue
        if not b:
            continue
        for linea in gzip.decompress(b).decode("latin-1").splitlines():
            if linea[:5] in ("20-F ", "40-F ") or linea[:7] in ("20-F/A ", "40-F/A "):
                m = re.search(r"\s(\d{3,10})\s+(\d{4}-\d{2}-\d{2})\s", linea)
                if m:
                    ciks[int(m.group(1))] = linea[:4]
    return ciks


def listados():
    d = datos.get_json("https://www.sec.gov/files/company_tickers_exchange.json", ttl_horas=24 * 7)
    i = {k: n for n, k in enumerate(d["fields"])}
    out = {}
    for r in d["data"]:
        if r[i["exchange"]] not in ("NYSE", "Nasdaq"):
            continue
        c, t = int(r[i["cik"]]), r[i["ticker"]]
        if c not in out or len(t) < len(out[c][0]):
            out[c] = (t, r[i["name"]], r[i["exchange"]])
    return out


def _hechos(h, tax, etiquetas, instante=False):
    """{moneda: {fecha_fin: valor}} de periodos anuales (o saldos), por la primera etiqueta con datos."""
    nodo = h.get("facts", {}).get(tax, {})
    res = {}
    for e in etiquetas:
        if e not in nodo:
            continue
        for u, fs in nodo[e]["units"].items():
            m = res.setdefault(u, {})
            for f in fs:
                if instante != ("start" not in f):
                    continue
                if not instante and not 345 <= (_d(f["end"]) - _d(f["start"])).days <= 380:
                    continue
                if f["end"] in m and m[f["end"]][1] >= f["filed"]:
                    continue
                m[f["end"]] = (f["val"], f["filed"])
    return {u: {k: v[0] for k, v in m.items()} for u, m in res.items() if m}


def _moneda(h, tax):
    cuenta = {}
    for e in ETIQ[tax]["un"] + ETIQ[tax]["ing"]:
        for u, fs in h.get("facts", {}).get(tax, {}).get(e, {}).get("units", {}).items():
            cuenta[u] = cuenta.get(u, 0) + len(fs)
    if not cuenta:
        return None
    return max(cuenta, key=lambda u: (cuenta[u], u != "USD"))


def _fx(moneda, cache):
    if moneda in cache:
        return cache[moneda]
    if moneda == "USD":
        cache[moneda] = 1.0; return 1.0
    for intento in range(2):          # Yahoo puede limitar: un segundo intento tras una pausa
        try:
            p = datos.precios(f"USD{moneda}=X", "5d", "1d", ttl_horas=24)
            if p and p["cierre"]:
                cache[moneda] = 1 / p["cierre"][-1]
                return cache[moneda]
        except Exception:
            pass
        time.sleep(60)
    return None                       # no se guarda el fallo: se reintenta con la siguiente empresa


def _cabeza(url, n=700000):
    r = requests.get(url, headers=datos.UA, timeout=60, stream=True); buf = b""
    for ch in r.iter_content(65536):
        buf += ch
        if len(buf) >= n:
            break
    r.close()
    t = html.unescape(re.sub(r"<[^>]+>", " ", buf.decode("utf-8", "replace")))
    return re.sub(r"\s+", " ", t)


def _num(txt):
    txt = txt.lower().strip()
    if txt in NUM:
        return NUM[txt]
    try:
        return float(txt.replace(",", ""))
    except ValueError:
        return None


def ratio_portada(sub, cik):
    r = sub["filings"]["recent"]
    for f, a, doc in zip(r["form"], r["accessionNumber"], r["primaryDocument"]):
        if f in ("20-F", "20-F/A"):
            try:
                t = _cabeza(f"https://www.sec.gov/Archives/edgar/data/{cik}/{a.replace('-', '')}/{doc}")
            except Exception:
                return None
            pats = [(r"(?i)(?:American Depositary Shares?|ADSs?)\W{0,3}(?:\([^)]{0,40}\)\W{0,3})?,?\s*(?:each|every)\s+(?:of which\s+)?represent\w*\s+([\w\-.,]+(?:[ -]\w+)?)\s+(?:of\s+(?:our|the)\s+)?(?:class [a-z]\s+)?(?:ordinary|common|equity)", 1),
                    (r"(?i)(?:each|one|every)\s+(?:American Depositary Share|ADS)\w*\s*(?:\([^)]{0,40}\)\s*)?represent\w*\s+([\w\-.,]+(?:[ -]\w+)?)\s+(?:of\s+(?:our|the)\s+)?(?:class [a-z]\s+)?(?:ordinary|common|equity)", 1),
                    (r"(?i)([\w\-]+)\s+(?:American Depositary Shares|ADSs)\s+represent\w*\s+one\s+(?:class [a-z]\s+)?(?:ordinary|common)", -1)]
            for p, sgn in pats:
                m = re.search(p, t)
                if m:
                    n = _num(m.group(1))
                    if n:
                        return n if sgn > 0 else 1 / n
            return None
    return None


def _redondo(x, tol=0.06):
    for r in REDONDOS:
        if abs(x / r - 1) <= tol:
            return r
    return None


def construir(ya_incluidos, log=print, minimo_cap=0):
    ciks = filers(log); lst = listados()
    cand = {c: ciks[c] for c in ciks if c in lst and c not in ya_incluidos}
    log(f"extranjeras: {len(ciks)} presentaron 20-F/40-F; {len(cand)} cotizan en NYSE/Nasdaq y faltan en la tabla")
    fxc, filas = {}, []
    precios_adr = datos.ultimos_precios([lst[c][0].replace(".", "-") for c in cand])
    for k, (c, forma) in enumerate(cand.items()):
        if k % 50 == 0:
            log(f"  extranjeras {k}/{len(cand)}")
        t, nombre_l, bolsa = lst[c]
        try:
            h = datos.get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json", ttl_horas=24 * 6)
            sub = datos.get_json(f"https://data.sec.gov/submissions/CIK{c:010d}.json", ttl_horas=24 * 6)
        except Exception:
            continue
        if not h or not sub:
            continue
        tax = "ifrs-full" if h.get("facts", {}).get("ifrs-full") else "us-gaap"
        cur = _moneda(h, tax)
        E = ETIQ[tax]
        dirs = sub.get("addresses") or {}
        pais = next((x for x in [(dirs.get(k) or {}).get(c2) for k in ("business", "mailing") for c2 in ("country", "stateOrCountryDescription")]
                     + [sub.get("stateOfIncorporationDescription")] if x), "")
        pais = PAIS_OPERA.get(t) or pais.split(",")[-1].strip()      # "Ontario, Canada" -> "Canada"
        sector = sectores.sector(sub.get("sic"))
        fila = {"cik": c, "t": t, "n": sub.get("name") or nombre_l, "s": sector, "ind": sub.get("sicDescription"), "sic": sub.get("sic"), "b": bolsa,
                "e": 0, "m": None, "ext": 1, "pais": pais.title(), "mon": cur, "met": "DCF"}
        filas.append(fila)
        if not cur:
            fila["m"] = "Sin estados financieros en XBRL"; continue
        fx = _fx(cur, fxc)
        if not fx:
            fila["m"] = f"Sin tipo de cambio para {cur}"; continue
        serie = lambda clave, inst=False: _hechos(h, tax, E[clave], inst).get(cur, {})
        ing, un, uo, fo, cx, cxi, sbc, da = (serie(x) for x in ("ing", "un", "uo", "fo", "cx", "cxi", "sbc", "da"))
        ai, imp = serie("ai"), serie("imp")
        eps = _hechos(h, tax, E["eps"]).get(cur + "/shares", {})
        pat, caja = serie("pat", True), serie("caja", True)
        deu, dlp, dcp = serie("deuda", True), serie("deuda_lp", True), serie("deuda_cp", True)
        fines = sorted(set(un) | set(ing))
        if not fines or not un:
            fila["m"] = "Sin resultados anuales en formato estándar"; continue
        f0 = fines[-1]
        if (dt.date.today() - _d(f0)).days > 800:
            fila["m"] = "Sin informe anual reciente"; continue
        anio = lambda m, k: m.get(k)
        prev = lambda n: next((x for x in reversed(fines) if (_d(f0) - _d(x)).days >= 365 * n - 40), None)
        f3, f5 = prev(3), prev(5)
        I0, N0 = anio(ing, f0), anio(un, f0)
        acc_ord = (N0 / anio(eps, f0)) if anio(eps, f0) else None
        acc_portada = False
        if acc_ord is None:   # sin utilidad por acción: promedio ponderado de acciones o acciones en circulación
            for tg, tx in (("NumberOfSharesOutstanding", tax), ("WeightedAverageShares", tax), ("AdjustedWeightedAverageShares", tax), ("WeightedAverageNumberOfDilutedSharesOutstanding", tax), ("EntityCommonStockSharesOutstanding", "dei")):
                nodo = h.get("facts", {}).get(tx, {}).get(tg)
                if nodo and nodo["units"].get("shares"):
                    ult_acc = max(nodo["units"]["shares"], key=lambda x: x["end"])
                    if (_d(f0) - _d(ult_acc["end"])).days > 200:
                        continue          # dato viejo (p. ej. antes de una emisión o bonificación): se busca otro
                    acc_ord = ult_acc["val"]
                    acc_portada = tx == "dei"; break
        if acc_ord is not None and acc_ord <= 0:
            acc_ord = None
        ult = max(pat) if pat else None
        caja0 = caja.get(max(caja)) if caja else 0.0
        deuda0 = (deu.get(max(deu)) if deu else 0.0) or ((dlp.get(max(dlp)) if dlp else 0.0) + (dcp.get(max(dcp)) if dcp else 0.0))
        usd = lambda x: x * fx if x is not None else None
        uo0 = anio(uo, f0)
        if uo0 is None and anio(ai, f0) is not None:
            uo0 = anio(ai, f0)
        fcf = (anio(fo, f0) - (anio(cx, f0) or 0) - (anio(cxi, f0) or 0) - (anio(sbc, f0) or 0)) if anio(fo, f0) is not None else None
        margenes = []
        for k2 in fines[-3:]:
            if anio(fo, k2) is not None and anio(ing, k2):
                margenes.append((anio(fo, k2) - (anio(cx, k2) or 0) - (anio(cxi, k2) or 0) - (anio(sbc, k2) or 0)) / anio(ing, k2))
        tasa = V.limitar((anio(imp, f0) or 0) / anio(ai, f0), 0, 0.35) if anio(ai, f0) and anio(ai, f0) > 0 else 0.21
        pat0 = pat.get(ult) if ult else None
        roes = [anio(un, k2) / pat[k2] for k2 in fines[-3:] if k2 in pat and pat[k2] and anio(un, k2) is not None]
        dn = deuda0 - caja0
        fila.update(ing=usd(I0), un=usd(N0), uo=usd(uo0), fcf=usd(fcf), dn=usd(dn),
                    c3=(I0 / anio(ing, f3)) ** (1 / 3) - 1 if f3 and I0 and anio(ing, f3) and anio(ing, f3) > 0 and I0 > 0 else None,
                    c5=(I0 / anio(ing, f5)) ** (1 / 5) - 1 if f5 and I0 and anio(ing, f5) and anio(ing, f5) > 0 and I0 > 0 else None,
                    mo=uo0 / I0 if uo0 is not None and I0 else None,
                    mn=statistics.median(margenes) if margenes else None,
                    roe=statistics.median(roes) if roes else None,
                    roic=(uo0 * (1 - tasa)) / (pat0 + deuda0 - caja0) if uo0 and pat0 and (pat0 + deuda0 - caja0) > 0 else None,
                    dne=dn / uo0 if uo0 and uo0 > 0 else None, fy=f0)
        # relación del ADR
        p_adr = precios_adr.get(t.replace(".", "-"))
        ratio, via = None, None
        if t in RATIO_FIJO:
            ratio, via = RATIO_FIJO[t]
        elif forma == "40-F":
            ratio, via = 1.0, "acción común interlistada (Canadá)"
        elif ORIGEN.get(t):
            try:
                ph = datos.precios(ORIGEN[t], "5d", "1d", ttl_horas=24)
                base = {"GBp": "GBP", "GBX": "GBP", "ILA": "ILS", "ZAc": "ZAR"}.get(ph["moneda"], ph["moneda"]) if ph else None
                fxh = _fx(base, fxc) if base else None
                if ph and fxh and p_adr:
                    pr = ph["cierre"][-1] / SUBUNIDAD.get(ph["moneda"], 1) * fxh
                    ratio = _redondo(p_adr / pr)
                    via = f"precio frente a {ORIGEN[t]}" if ratio else None
            except Exception:
                pass
        elif t in ORIGEN and ORIGEN[t] is None:
            ratio, via = 1.0, "cotiza su propia acción en EE.UU."
        if ratio is None and forma.startswith("20-F"):
            try:
                ratio = ratio_portada(sub, c)
            except Exception:
                ratio = None
            via = "portada del informe anual" if ratio else None
        if ratio and p_adr and acc_ord and N0:
            eps_adr_usd = N0 / acc_ord * fx * ratio
            pe = p_adr / eps_adr_usd if eps_adr_usd > 0 else None
            if pe is not None and not 2 <= pe <= 300:
                ratio, via = None, None            # relación inverosímil: se descarta
        fila.update(adr=ratio, adr_via=via)
        if acc_portada:      # la portada suele contar una sola clase (p. ej. omite preferentes): no es confiable
            fila["e"] = 1
            fila["m"] = "Número de acciones incompleto (solo portada; puede omitir clases de acciones)"
            continue
        if not (ratio and p_adr and acc_ord):
            fila["e"] = 1
            fila["m"] = "Relación del ADR no verificada: sin valorización por acción" if not ratio else "Sin precio o número de acciones"
            continue
        acc = acc_ord / ratio
        cap = p_adr * acc
        fila.update(p=p_adr, acc=acc, cap=cap, per=cap / fila["un"] if fila["un"] and fila["un"] > 0 else None,
                    rf=fila["fcf"] / cap if fila["fcf"] is not None else None,
                    vee=(cap + fila["dn"]) / fila["uo"] if fila["uo"] and fila["uo"] > 0 and cap + fila["dn"] > 0 else None)
        extra = max((v for k3, v in EMERGENTES.items() if k3 in pais.upper()), default=0.0)
        fila["prima_pais"] = extra
        valorar(fila, sector, cap, acc, extra, bvps=(pat0 * fx / acc) if pat0 else None, ffo=(N0 + (anio(da, f0) or 0)) * fx if N0 is not None else None)
        fila["e"], fila["m"] = calidad(fila, cap, minimo_cap)
    log(f"extranjeras: {len(filas)} filas, {sum(1 for f in filas if f.get('p'))} con valorización por acción")
    return filas


def valorar(f, sector, cap, acc, extra, bvps=None, ffo=None):
    if sector == "Financiero":
        f["met"] = "P/VL-ROE"
        if bvps and f.get("roe") is not None:
            esc = V.escenarios_financiera(bvps, f["roe"], cap, sector, extra)
            f.update(bvps=bvps, ke=V.tasa_descuento(cap, sector, "ke", extra))
    elif sector == "Inmobiliario":
        f["met"] = "FFO"
        esc = V.escenarios_reit(ffo / acc, cap, sector, extra) if ffo and ffo > 0 else None
        if esc:
            f.update(ffo_ps=ffo / acc, ke=V.tasa_descuento(cap, sector, "ke", extra))
    else:
        esc = None
        if f.get("mn") and f["mn"] > 0 and f.get("ing"):
            hs = [x for x in (f.get("c3"), f.get("c5")) if x is not None]
            esc = V.escenarios(min(hs) if hs else None, f["mn"], f["ing"], f["dn"], acc, cap, sector=sector, extra=extra)
            f["wacc"] = esc["base"]["r"]
    if sector in ("Financiero", "Inmobiliario") and not (f.get("bvps") or f.get("ffo_ps")):
        esc = None
    if sector == "Financiero" and f.get("bvps"):
        esc = V.escenarios_financiera(f["bvps"], f["roe"], cap, sector, extra)
    if esc and esc["base"].get("valor_accion") and esc["base"]["valor_accion"] > 0 and f.get("p"):
        f.update(vp=esc["pesimista"]["valor_accion"], vb=esc["base"]["valor_accion"], vo=esc["optimista"]["valor_accion"])
        f["pot"] = f["vb"] / f["p"] - 1


def calidad(f, cap, minimo_cap):
    s = f["s"]
    if cap < max(minimo_cap, 2e9):
        return 1, "Capitalización menor a $2 mil millones"
    if f.get("b") not in ("NYSE", "Nasdaq"):
        return 1, "No cotiza en NYSE ni Nasdaq"
    if s == "Financiero":
        if not f.get("un") or f["un"] <= 0:
            return 1, "No gana dinero"
        if f.get("roe") is None or f["roe"] < 0.08:
            return 1, "Rentabilidad sobre patrimonio menor a 8%"
    elif s == "Inmobiliario":
        if not f.get("ffo_ps") or f["ffo_ps"] <= 0:
            return 1, "FFO negativo o sin datos"
    else:
        if f.get("uo") is None or f["uo"] <= 0 or f.get("fcf") is None or f["fcf"] <= 0:
            return 1, "No gana dinero o no genera caja libre"
        if f.get("c3") is None or f["c3"] < -0.01:
            return 1, "Ventas en caída a tres años, o sin historia suficiente"
        if f.get("dne") is not None and f["dne"] > 3:
            return 1, "Deuda neta mayor a 3 veces la utilidad operativa"
        if f.get("roic") is None or f["roic"] < 0.10:
            return 1, "Retorno sobre capital menor a 10%"
    if f.get("pot") is not None and (f["pot"] > 3 or (f.get("rf") or 0) > 0.30):
        return 1, "Cifras incoherentes (revisar moneda o relación del ADR)"
    return 2, None
