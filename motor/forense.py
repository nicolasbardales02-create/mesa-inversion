"""Contabilidad forense: banderas rojas por empresa, calculadas con los estados financieros de la SEC.

- Piotroski F (0-9): fortaleza financiera. 8-9 sólida, 0-3 débil.
- Altman Z: riesgo de quiebra a 2 años. > 2.99 zona segura, 1.81-2.99 gris, < 1.81 peligro.
  (No aplica a bancos, aseguradoras ni REITs.)
- Beneish M (8 variables): probabilidad de manipulación contable. > -1.78 = señal de alerta.
  (Detecta patrones de empresas que luego fueron sancionadas; tiene falsos positivos,
  sobre todo en empresas que crecen muy rápido o hacen compras grandes.)
- Devengos (Sloan): (utilidad − flujo de caja operativo) / activos. Utilidades que no se convierten
  en caja suelen revertirse.
- Dilución: aumento del número de acciones; pago en acciones como % de las ventas.

Solo empresas que reportan en US-GAAP (las extranjeras con IFRS no están en el API frames).
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(__file__))
import datos, fundamentales as F
from screener import _flujo, ALIAS_CIK, ANIO


def _primero(etiquetas, periodo, unidad="USD"):
    m = {}
    for e in etiquetas:
        for f in datos.marco(e, periodo, unidad):
            m.setdefault(f["cik"], f["val"])
    return m


def _cargar(log=print):
    D = {}
    for a in (ANIO, ANIO - 1):
        P = f"CY{a}"
        D[a] = {
            "ing": _flujo(F.INGRESOS, a),
            "cogs": _primero(["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"], P),
            "gp": _primero(["GrossProfit"], P),
            "ni": _primero(["NetIncomeLoss", "ProfitLoss"], P),
            "cfo": _primero(F.FLUJO_OPER, P),
            "dep": _primero(["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                             "DepreciationAmortizationAndAccretionNet", "Depreciation"], P),
            "sga": _primero(["SellingGeneralAndAdministrativeExpense"], P),
            "ebit": _primero(["OperatingIncomeLoss"], P),
            "sh": _primero(F.ACC_DIL, P, "shares"),
            "sbc": _primero(F.SBC, P),
        }
    for a in (ANIO, ANIO - 1, ANIO - 2):
        P = f"CY{a}Q4I"
        D.setdefault(a, {}).update({
            "ta": _primero(["Assets"], P),
            "tl": _primero(["Liabilities"], P),
            "eqt": _primero(["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"], P),
            "ca": _primero(["AssetsCurrent"], P),
            "cl": _primero(["LiabilitiesCurrent"], P),
            "re": _primero(["RetainedEarningsAccumulatedDeficit"], P),
            "ar": _primero(["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"], P),
            "ppe": _primero(["PropertyPlantAndEquipmentNet"], P),
            "ltd": _primero(["LongTermDebtNoncurrent", "LongTermDebt"], P),
        })
    log("forense: estados descargados")
    return D


def _div(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def evaluar(cik, D, cap=None, sector=None):
    t, t1, t2 = ANIO, ANIO - 1, ANIO - 2
    g = lambda a, k: D[a][k].get(cik)
    r = {}
    ta, ta1, ta2 = g(t, "ta"), g(t1, "ta"), g(t2, "ta")
    ing, ing1 = g(t, "ing"), g(t1, "ing")
    ni, ni1, cfo = g(t, "ni"), g(t1, "ni"), g(t, "cfo")
    # utilidad con error de unidades (más de 2 veces las ventas): se descarta en vez de usarla
    if ni is not None and ing and abs(ni) > 2 * abs(ing): ni = None
    if ni1 is not None and ing1 and abs(ni1) > 2 * abs(ing1): ni1 = None
    tl = g(t, "tl") if g(t, "tl") is not None else (ta - g(t, "eqt") if ta is not None and g(t, "eqt") is not None else None)
    tl1 = g(t1, "tl") if g(t1, "tl") is not None else (ta1 - g(t1, "eqt") if ta1 is not None and g(t1, "eqt") is not None else None)
    finan = sector in ("Financiero", "Inmobiliario")

    # dilución (aplica a todas)
    sh, sh1 = g(t, "sh"), g(t1, "sh")
    r["dil"] = _div(sh, sh1) - 1 if sh and sh1 else None
    r["sbcv"] = _div(g(t, "sbc"), ing) if ing and ing > 0 else None
    # devengos
    if ni is not None and cfo is not None and ta and ta1:
        r["acr"] = (ni - cfo) / ((ta + ta1) / 2)
    if finan:
        return r

    # --- Piotroski F
    pts, disp = 0, 0
    def senal(cond):
        nonlocal pts, disp
        if cond is None:
            return
        disp += 1; pts += 1 if cond else 0
    roa = _div(ni, ta1); roa1 = _div(ni1, ta2)
    senal(roa > 0 if roa is not None else None)
    senal(cfo > 0 if cfo is not None else None)
    senal(roa > roa1 if roa is not None and roa1 is not None else None)
    senal(_div(cfo, ta1) > roa if cfo is not None and roa is not None and ta1 else None)
    lev, lev1 = _div(g(t, "ltd") or 0.0, ta), _div(g(t1, "ltd") or 0.0, ta1)
    senal(lev <= lev1 if lev is not None and lev1 is not None else None)
    cr, cr1 = _div(g(t, "ca"), g(t, "cl")), _div(g(t1, "ca"), g(t1, "cl"))
    senal(cr > cr1 if cr is not None and cr1 is not None else None)
    senal(sh <= sh1 * 1.005 if sh and sh1 else None)
    gm = _div(g(t, "gp"), ing) if g(t, "gp") is not None else (_div(ing - g(t, "cogs"), ing) if ing and g(t, "cogs") is not None else None)
    gm1 = _div(g(t1, "gp"), ing1) if g(t1, "gp") is not None else (_div(ing1 - g(t1, "cogs"), ing1) if ing1 and g(t1, "cogs") is not None else None)
    senal(gm > gm1 if gm is not None and gm1 is not None else None)
    at, at1 = _div(ing, ta1), _div(ing1, ta2)
    senal(at > at1 if at is not None and at1 is not None else None)
    if disp >= 7:
        r["fs"], r["fn"] = round(pts * 9 / disp), disp

    # --- Altman Z (con capitalización bursátil)
    ca, cl, re_, ebit = g(t, "ca"), g(t, "cl"), g(t, "re"), g(t, "ebit")
    if ta and ta > 0 and tl and tl > 0 and cap and ing is not None and ebit is not None and ca is not None and cl is not None and re_ is not None:
        r["az"] = 1.2 * (ca - cl) / ta + 1.4 * re_ / ta + 3.3 * ebit / ta + 0.6 * cap / tl + 1.0 * ing / ta

    # --- Beneish M (8 variables; las que faltan se toman neutrales = 1)
    ar, ar1 = g(t, "ar"), g(t1, "ar")
    if ing and ing1 and ing > 0 and ing1 > 0 and ar is not None and ar1 and ta and ta1 and ni is not None and cfo is not None:
        dsri = (ar / ing) / (ar1 / ing1)
        gmi = (gm1 / gm) if gm and gm1 and gm > 0 else 1.0
        ppe, ppe1 = g(t, "ppe"), g(t1, "ppe")
        aqi = 1.0
        if ca is not None and g(t1, "ca") is not None and ppe is not None and ppe1 is not None:
            q, q1 = 1 - (ca + ppe) / ta, 1 - (g(t1, "ca") + ppe1) / ta1
            aqi = q / q1 if q1 > 0 and q > 0 else 1.0
        sgi = ing / ing1
        dep, dep1 = g(t, "dep"), g(t1, "dep")
        depi = ((dep1 / (dep1 + ppe1)) / (dep / (dep + ppe))) if dep and dep1 and ppe and ppe1 else 1.0
        sga, sga1 = g(t, "sga"), g(t1, "sga")
        sgai = ((sga / ing) / (sga1 / ing1)) if sga and sga1 else 1.0
        lvgi = ((tl / ta) / (tl1 / ta1)) if tl and tl1 else 1.0
        tata = (ni - cfo) / ta
        r["bm"] = (-4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi
                   - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
    return r


def banderas(r):
    b = []
    if r.get("bm") is not None and r["bm"] > -1.78: b.append("M")
    if r.get("az") is not None and r["az"] < 1.81: b.append("Z")
    if r.get("fs") is not None and r["fs"] <= 3: b.append("F")
    if r.get("acr") is not None and r["acr"] > 0.10: b.append("AC")
    if r.get("dil") is not None and r["dil"] > 0.05: b.append("DI")
    if r.get("sbcv") is not None and r["sbcv"] > 0.10: b.append("SBC")
    return b


COLS = {"fs": 0, "fn": 0, "az": 2, "bm": 2, "acr": 3, "dil": 3, "sbcv": 3, "rojas": None}


def anotar_archivo(log=print):
    ruta = os.path.join(datos.RAIZ, "datos", "universo.json")
    U = json.load(open(ruta)); cols = U["cols"]
    filas = [dict(zip(cols, x)) for x in U["filas"]]
    cik_de = {}
    for t in datos.tickers_sec():
        cik_de.setdefault(t["ticker"], ALIAS_CIK.get(t["cik"], t["cik"]))
    D = _cargar(log)
    n = 0
    for f in filas:
        for k in COLS:
            f[k] = None
        c = cik_de.get(f["t"])
        if not c or f.get("ext"):
            continue
        r = evaluar(c, D, f.get("cap"), f.get("s"))
        if not r:
            continue
        f.update(r); f["rojas"] = "".join(x + " " for x in banderas(r)).strip() or ""
        n += 1
    for k in COLS:
        if k not in cols:
            cols.append(k)
    U["filas"] = [[(round(f[c], COLS[c]) if c in COLS and COLS[c] is not None and isinstance(f.get(c), float) else
                    (int(f[c]) if c in COLS and COLS[c] == 0 and f.get(c) is not None else f.get(c))) for c in cols] for f in filas]
    json.dump(U, open(ruta, "w"), separators=(",", ":"), ensure_ascii=False)
    log(f"forense: {n} empresas evaluadas")


if __name__ == "__main__":
    anotar_archivo()
