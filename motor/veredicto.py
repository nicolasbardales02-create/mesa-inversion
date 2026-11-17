"""Veredicto cuantitativo para todas las empresas e "ick investing" (valor profundo en acciones que el mercado rechaza).

Todo es código con reglas a la vista; no se usa IA. Se agregan columnas a datos/universo.json.

1. Veredicto cuantitativo (vq = candidata | neutral | cara | evitar), puntaje vqp y razones vqr:
   + calidad (pasa el filtro), descuento del DCF o del método que corresponda, tasa base (lo que asume el precio es
     probable), descuento frente a sus pares de industria, rendimiento de caja alto, compras de directivos;
   − banderas forenses, lo que asume el precio es improbable, cara frente a sus pares.
   Candidata: pasa el filtro, puntaje ≥ 5 y sin banderas de manipulación (M) ni de quiebra (Z).
   Evitar: pierde dinero o tiene banderas de manipulación (M) o de quiebra (Z). Cara: puntaje ≤ −2 por precio.

2. Ick investing (Michael Burry; Tobias Carlisle, "The Acquirer's Multiple"): empresas que dan "asco" al
   inversionista promedio pero que son baratas y generan caja. Tres condiciones, todas medibles:
   a) Barata: valor empresa / utilidad operativa ≤ 8, o rendimiento de caja libre ≥ 10%
      (bancos: precio ≤ 0.8 veces el valor libro y ≤ 8 veces utilidades; inmobiliarias: ≤ 8 veces el FFO).
   b) Rechazada: al menos un motivo de "asco": cayó ≥ 35% desde su máximo de 52 semanas, perdió ≥ 30% en un año,
      industria que el mercado evita (tabaco, carbón, petróleo, minería, papel, diarios, tiendas por departamento...),
      ventas en caída, aviso grave en un 8-K, o cotiza muy por debajo de sus pares.
   c) No es una trampa obvia: gana dinero y genera caja; sin bandera de manipulación contable (M); sin riesgo de
      quiebra (Altman Z < 1.81) con deuda; sin re-expresión de estados financieros (8-K 4.02).
   El puntaje suma barato + motivos de rechazo + catalizadores (compras de directivos, activista, recompras, caja
   neta) − riesgos. La pregunta que el código no responde —¿el rechazo es temporal o permanente?— la responde la
   revisión cualitativa.
Uso: python3 motor/veredicto.py
"""
import json, os, statistics, sys, datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
import datos, requests

RUTA_U = os.path.join(datos.RAIZ, "datos", "universo.json")

# Industrias que el inversionista promedio evita (código SIC de la SEC, por prefijo)
ICK_SIC = {"2111": "tabaco", "21": "tabaco", "1221": "carbón", "1222": "carbón", "122": "carbón", "10": "minería metálica",
           "13": "petróleo y gas", "29": "refinación de petróleo", "26": "papel y empaques", "27": "diarios e imprentas",
           "331": "acero", "332": "fundiciones", "3711": "autos", "3714": "autopartes", "4213": "transporte por camión",
           "4512": "aerolíneas", "44": "transporte marítimo", "5311": "tiendas por departamento", "5651": "ropa al por menor",
           "4813": "telefonía fija", "4841": "televisión por cable", "7990": "apuestas y casinos", "7011": "hoteles y casinos",
           "348": "armas", "208": "bebidas alcohólicas", "4953": "residuos", "6798": None, "8200": "educación con fines de lucro",
           "1311": "petróleo y gas", "1381": "perforación petrolera", "3089": None}


def industria_ick(sic):
    s = str(sic or "")
    for n in (4, 3, 2):
        if s[:n] in ICK_SIC and ICK_SIC[s[:n]]:
            return ICK_SIC[s[:n]]
    return None


def precios_1a(simbolos, log=print):
    """Cierres semanales de 1 año de muchos símbolos (Yahoo spark, de a 20)."""
    out = {}
    for i in range(0, len(simbolos), 20):
        g = simbolos[i:i + 20]
        url = ("https://query1.finance.yahoo.com/v8/finance/spark?symbols=" + requests.utils.quote(",".join(g))
               + "&range=1y&interval=1wk")
        try:
            d = datos.get_json(url, ttl_horas=20) or {}
        except Exception:
            d = {}
        for s, v in d.items():
            c = [x for x in (v.get("close") or []) if x]
            if len(c) >= 20:
                out[s] = c
        if i % 400 == 0:
            log(f"  precios de 1 año: {i}/{len(simbolos)}")
    return out


def _medianas_pares(F):
    """P/U mediano por código de industria (4 dígitos si hay ≥ 3 pares; si no, 3 dígitos con ≥ 4)."""
    por = {}
    for f in F:
        if f.get("per") and 0 < f["per"] < 200 and f.get("sic"):
            s = str(f["sic"])
            por.setdefault(s[:4], []).append(f["per"]); por.setdefault("3:" + s[:3], []).append(f["per"])
    def med(f):
        s = str(f.get("sic") or "")
        a = [x for x in por.get(s[:4], [])]
        if len(a) >= 4:          # incluye a la propia empresa: 3 pares + ella
            return statistics.median(a)
        b = por.get("3:" + s[:3], [])
        return statistics.median(b) if len(b) >= 5 else None
    return med


def construir(log=print):
    U = json.load(open(RUTA_U)); cols = U["cols"]
    F = [dict(zip(cols, r)) for r in U["filas"]]
    R = json.load(open(os.path.join(datos.RAIZ, "datos", "radar.json"))) if os.path.exists(os.path.join(datos.RAIZ, "datos", "radar.json")) else {}
    compras = {x["ticker"]: x for x in R.get("compras_directivos", []) if x.get("ticker")}
    activ = {x["ticker"] for x in R.get("activistas", []) if x.get("ticker") and x.get("activista")}
    alert = {}
    for x in R.get("alertas_8k", []):
        if x.get("ticker"):
            alert.setdefault(x["ticker"], []).append(x["item"])
    fusion = {x["ticker"] for x in R.get("fusiones", []) if x.get("ticker")}
    reestr = {x["ticker"] for x in R.get("reestructuraciones", []) if x.get("ticker")}
    escind = {x["ticker"] for x in R.get("spinoffs", []) if x.get("ticker")}

    # precios de 1 año para medir el rechazo
    con_p = [f for f in F if f.get("p")]
    P = precios_1a([f["t"].replace(".", "-") for f in con_p], log)
    log(f"precios de 1 año: {len(P)} de {len(con_p)}")
    for f in F:
        c = P.get(f["t"].replace(".", "-"))
        f["dd52"] = f["r1a"] = None
        if c:
            saltos = [c[i] / c[i - 1] for i in range(1, len(c)) if c[i - 1]]
            if all(0.55 < s < 1.8 for s in saltos):          # sin divisiones de acciones sin ajustar
                f["dd52"] = c[-1] / max(c) - 1
                f["r1a"] = c[-1] / c[0] - 1
    med = _medianas_pares(F)

    n_c = n_ick = 0
    for f in F:
        rojas = (f.get("rojas") or "").split()
        f["vq"] = f["vqp"] = f["vqr"] = f["ick"] = f["ickm"] = f["ickc"] = f["ickr"] = None
        if not f.get("p") or f.get("e", 0) < 1:
            continue
        fin, reit = f.get("met") == "P/VL-ROE", f.get("met") == "FFO"
        pts, raz = 0, []
        def suma(n, txt):
            nonlocal pts
            pts += n; raz.append(("+" if n > 0 else "−") + " " + txt)
        if f["e"] == 2: suma(2, "pasa el filtro de calidad")
        pot = f.get("pot")
        if pot is not None:
            if pot >= .30: suma(2, f"el valor estimado está {pot:.0%} sobre el precio")
            elif pot >= .10: suma(1, f"el valor estimado está {pot:.0%} sobre el precio")
            elif pot <= -.30: suma(-2, (f"el precio está {-pot / (1 + pot):.0%} sobre el valor estimado" if pot > -.95 else "el valor estimado es casi nulo frente al precio"))
            elif pot <= -.10: suma(-1, f"el precio está algo sobre el valor estimado")
        pbr = f.get("pbr")
        if pbr is not None:
            if pbr >= .5: suma(2, f"lo que asume el precio lo logró el {pbr:.0%} de las empresas de su tamaño")
            elif pbr >= .2: suma(1, f"lo que asume el precio es exigente pero frecuente ({pbr:.0%})")
            elif pbr < .05: suma(-2, f"lo que asume el precio casi nadie lo logró ({pbr:.1%})")
            else: suma(-1, f"lo que asume el precio es poco frecuente ({pbr:.0%})")
        m = med(f) if f.get("per") else None
        if m and f.get("per"):
            rel = f["per"] / m - 1
            f["per_rel"] = rel
            if rel <= -.25: suma(1, f"cotiza {-rel:.0%} más barata que sus pares por utilidad")
            elif rel >= .50: suma(-1, f"cotiza {rel:.0%} más cara que sus pares por utilidad")
        if f.get("rf") is not None and f["rf"] >= .06 and not fin: suma(1, f"rinde {f['rf']:.1%} de caja libre al año")
        if f["t"] in compras: suma(1, f"{compras[f['t']]['compradores']} directivos compraron acciones con su dinero")
        # Beneish da falsas alarmas en empresas que crecen muy rápido: ahí pesa menos y no basta para "evitar"
        crece = f.get("c3") is not None and f["c3"] > .25
        if crece and "M" in rojas:
            rojas = [b for b in rojas if b != "M"]; suma(-1, "alerta de Beneish, probablemente por su crecimiento muy rápido")
        for b, n, txt in (("M", -3, "posible manipulación contable (Beneish)"), ("Z", -3, "riesgo de quiebra (Altman)"),
                          ("F", -1, "fortaleza financiera débil (Piotroski)"), ("AC", -1, "utilidad que no llega a caja"),
                          ("DI", -1, "dilución alta")):
            if b in rojas: suma(n, txt)
        perdidas = (f.get("un") is not None and f["un"] <= 0) or (f.get("m") or "").startswith("No gana")
        if "M" in rojas or "Z" in rojas or perdidas:
            vq = "evitar"
        elif pts <= -2:
            vq = "cara"
        elif f["e"] == 2 and pts >= 5:
            vq = "candidata"
        else:
            vq = "neutral"
        f.update(vq=vq, vqp=pts, vqr="|".join(raz[:6]))
        n_c += vq == "candidata"

        # ---- ick investing
        if not f.get("cap") or f["cap"] < 3e8 or perdidas or f["t"] in fusion:
            continue
        if not fin and not reit and not ((f.get("uo") or 0) > 0 and (f.get("fcf") or 0) > 0):
            continue
        barata, bp = [], 0
        if fin:
            if f.get("pb") and f["pb"] <= .8 and f.get("per") and f["per"] <= 8:
                barata.append(f"precio de {f['pb']:.2f} veces su valor libro y {f['per']:.1f} veces utilidades"); bp = 2
        elif reit:
            pf = f["p"] / f["ffo_ps"] if f.get("ffo_ps") else None
            if pf and 0 < pf <= 8:
                barata.append(f"{pf:.1f} veces su FFO"); bp = 2
        else:
            if f.get("vee") and 0 < f["vee"] <= 8:
                barata.append(f"valor empresa de {f['vee']:.1f} veces su utilidad operativa"); bp += 3 if f["vee"] <= 5 else 2
            if f.get("rf") and f["rf"] >= .10:
                barata.append(f"rinde {f['rf']:.0%} de caja libre al año"); bp += 2 if f["rf"] >= .15 else 1
        if not barata:
            continue
        mot = []
        if f.get("dd52") is not None and f["dd52"] <= -.35: mot.append(f"cayó {-f['dd52']:.0%} desde su máximo de 52 semanas")
        if f.get("r1a") is not None and f["r1a"] <= -.30: mot.append(f"perdió {-f['r1a']:.0%} en un año")
        ind = industria_ick(f.get("sic"))
        if ind: mot.append(f"industria que el mercado evita ({ind})")
        if f.get("c3") is not None and f["c3"] <= -.03: mot.append(f"ventas en caída ({f['c3']:.0%} anual en 3 años)")
        its = alert.get(f["t"], [])
        if any(i in ("4.01", "3.01") for i in its): mot.append("aviso grave en un 8-K (" + ", ".join(sorted(set(its))) + ")")
        if f.get("per_rel") is not None and f["per_rel"] <= -.40: mot.append(f"cotiza {-f['per_rel']:.0%} bajo sus pares")
        if f["t"] in reestr: mot.append("en reestructuración (cierra o vende operaciones, 8-K 2.05)")
        if f["t"] in escind: mot.append("escisión reciente: muchos fondos la venden sin mirarla")
        if not mot:                 # ser pequeña no basta: hace falta un motivo de rechazo
            continue
        if f["cap"] < 2e9: mot.append("pequeña y poco seguida por el mercado")
        # trampas obvias: fuera
        if "M" in rojas or "4.02" in its or ("Z" in rojas and (f.get("dn") or 0) > 0):
            continue
        cat, rie = [], []
        if f["t"] in compras: cat.append(f"{compras[f['t']]['compradores']} directivos compraron con su dinero")
        if f["t"] in activ: cat.append("un inversionista activista entró (13D)")
        if f.get("dil") is not None and f["dil"] <= -.03: cat.append(f"recompra acciones ({-f['dil']:.0%} menos en un año)")
        if f.get("dn") is not None and f["dn"] < 0 and not fin: cat.append("tiene más caja que deuda")
        if f.get("dne") is not None and f["dne"] > 3: rie.append(f"deuda neta de {f['dne']:.1f} veces la utilidad operativa")
        if "F" in rojas: rie.append("fortaleza financiera débil (Piotroski)")
        if "DI" in rojas: rie.append("emite acciones (dilución)")
        if "AC" in rojas: rie.append("utilidad que no llega a caja")
        if f.get("c3") is not None and f["c3"] <= -.10: rie.append("ventas cayendo rápido: puede ser un negocio en extinción")
        if f.get("az") is not None and f["az"] < 1.81: rie.append("Altman Z en zona de peligro (tiene caja neta)")
        f.update(ick=bp + min(len(mot), 3) + len(cat) - len(rie), ickm="|".join(barata + mot), ickc="|".join(cat), ickr="|".join(rie))
        n_ick += 1

    nuevas = ["vq", "vqp", "vqr", "dd52", "r1a", "ick", "ickm", "ickc", "ickr"]
    for c in nuevas:
        if c not in cols:
            cols.append(c)
    red = {"dd52": 3, "r1a": 3}
    U["filas"] = [[(round(f[c], red[c]) if c in red and isinstance(f.get(c), float) else f.get(c)) for c in cols] for f in F]
    U["conteo"]["candidatas"] = n_c; U["conteo"]["ick"] = n_ick
    json.dump(U, open(RUTA_U, "w"), separators=(",", ":"), ensure_ascii=False)
    log(f"veredicto: {n_c} candidatas, {sum(1 for f in F if f.get('vq') == 'evitar')} evitar; ick: {n_ick}")
    log("VEREDICTO TERMINADO")


if __name__ == "__main__":
    construir(log=lambda *a: print(*a, flush=True))
