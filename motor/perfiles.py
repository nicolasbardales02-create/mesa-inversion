"""Perfiles de inversionista: mezcla de activos de cada perfil y su comportamiento.

Para cada perfil se calcula, con datos reales, cómo se habría comportado su mezcla
(S&P 500, bonos del Tesoro, oro, materias primas, letras del Tesoro) desde 2007, que incluye
la crisis de 2008, el 2020 y el 2022. Y una rentabilidad prospectiva con supuestos explícitos:
acciones 8% anual (supuesto), bonos y efectivo a las tasas actuales (FRED), oro 4%, materias primas 3%.
"""
import json, os, sys, math, statistics, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos

PERFILES = {  # pesos estratégicos: acciones, bonos, oro, materias primas, efectivo
    "conservador": {"nombre": "Conservador", "acciones": 0.25, "bonos": 0.50, "oro": 0.10, "materias": 0.00, "efectivo": 0.15, "satelite": 0.20},
    "moderado": {"nombre": "Moderado", "acciones": 0.45, "bonos": 0.35, "oro": 0.10, "materias": 0.00, "efectivo": 0.10, "satelite": 0.30},
    "equilibrado": {"nombre": "Equilibrado", "acciones": 0.60, "bonos": 0.25, "oro": 0.08, "materias": 0.02, "efectivo": 0.05, "satelite": 0.40},
    "crecimiento": {"nombre": "Crecimiento", "acciones": 0.75, "bonos": 0.12, "oro": 0.06, "materias": 0.02, "efectivo": 0.05, "satelite": 0.50},
    "agresivo": {"nombre": "Agresivo", "acciones": 0.90, "bonos": 0.00, "oro": 0.05, "materias": 0.00, "efectivo": 0.05, "satelite": 0.60}}
PROXY = {"acciones": "SPY", "bonos": "IEF", "oro": "GLD", "materias": "DBC", "efectivo": "BIL"}
INSTRUMENTOS = {  # fondos cotizados que se usan en el portafolio
    "VOO": "S&P 500 (Vanguard)", "IJH": "Empresas medianas de EE.UU. (S&P 400)", "IEF": "Bonos del Tesoro a 7-10 años",
    "TLT": "Bonos del Tesoro a 20+ años", "GLD": "Oro", "DBC": "Canasta de materias primas", "BIL": "Letras del Tesoro (1-3 meses)",
    "SPY": "S&P 500 (SPDR)", "SHY": "Bonos del Tesoro a 1-3 años", "IAU": "Oro (iShares)", "SGOV": "Letras del Tesoro (0-3 meses)",
    "VXUS": "Acciones fuera de EE.UU.", "USO": "Petróleo", "SLV": "Plata", "CPER": "Cobre", "DBA": "Materias primas agrícolas"}
# Equivalentes domiciliados en Irlanda (UCITS), para inversionistas que no residen en EE.UU.: no están sujetos al
# impuesto a la herencia de EE.UU. y las acciones de EE.UU. que tienen pagan 15% de retención de dividendos (tratado
# EE.UU.-Irlanda) en vez de 30%. Cotizan en la Bolsa de Londres en dólares (sufijo .L en Yahoo). Costos anuales
# verificados en las páginas de iShares y State Street (nov. 2026).
UCITS = {"CSPX": ("CSPX.L", "S&P 500 (iShares, Irlanda)"), "SPY4": ("SPY4.L", "Empresas medianas de EE.UU. (SPDR, Irlanda)"),
         "CBU0": ("CBU0.L", "Bonos del Tesoro a 7-10 años (iShares, Irlanda)"), "DTLA": ("DTLA.L", "Bonos del Tesoro a 20+ años (iShares, Irlanda)"),
         "IGLN": ("IGLN.L", "Oro físico (iShares, Irlanda)"), "ICOM": ("ICOM.L", "Canasta de materias primas (iShares, Irlanda)"),
         "IB01": ("IB01.L", "Letras del Tesoro de 0-1 año (iShares, Irlanda)")}
SUPUESTO = {"acciones": 0.08, "oro": 0.04, "materias": 0.03}


def _fred(serie):
    t = datos.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={serie}", ttl_horas=20)
    for linea in reversed(t.strip().splitlines()[1:]):
        try:
            return float(linea.split(",")[1]) / 100
        except ValueError:
            continue


def construir():
    series = {k: datos.precios(s, "max", "1d", ttl_horas=24) for k, s in PROXY.items()}
    comun = sorted(set.intersection(*[set(p["fechas"]) for p in series.values()]))
    semanal = comun[::5]
    niveles = {k: dict(zip(p["fechas"], p["cierre_aj"])) for k, p in series.items()}
    rf10, tb3 = _fred("DGS10"), _fred("DTB3")
    out = {}
    for clave, P in PERFILES.items():
        valor, pico, peor, curva, anual = 1.0, 1.0, 0.0, [], {}
        for i in range(1, len(semanal)):
            a, b = semanal[i - 1], semanal[i]
            r = sum(P[k] * (niveles[k][b] / niveles[k][a] - 1) for k in PROXY)   # rebalanceo semanal
            valor *= 1 + r; pico = max(pico, valor); peor = min(peor, valor / pico - 1)
            anual[b[:4]] = valor
            if i % 4 == 0 or i == len(semanal) - 1:
                curva.append({"f": b, "v": round(valor, 4)})
        anios = (dt.date.fromisoformat(semanal[-1]) - dt.date.fromisoformat(semanal[0])).days / 365.25
        rets = []
        prev = 1.0
        for y in sorted(anual):
            rets.append((y, anual[y] / prev - 1)); prev = anual[y]
        sem = [sum(P[k] * (niveles[k][semanal[i]] / niveles[k][semanal[i - 1]] - 1) for k in PROXY) for i in range(1, len(semanal))]
        prosp = P["acciones"] * SUPUESTO["acciones"] + P["bonos"] * rf10 + P["efectivo"] * tb3 + P["oro"] * SUPUESTO["oro"] + P["materias"] * SUPUESTO["materias"]
        out[clave] = {**P, "retorno_hist": valor ** (1 / anios) - 1, "volatilidad": statistics.pstdev(sem) * math.sqrt(52),
                      "peor_caida": peor, "peor_anio": min(rets, key=lambda x: x[1]), "anios_negativos": sum(1 for _, r in rets if r < 0),
                      "anios": len(rets), "retorno_prosp": prosp, "curva": curva}
    return {"generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "desde": semanal[0], "hasta": semanal[-1],
            "proxys": PROXY, "instrumentos": INSTRUMENTOS, "tasa_10a": rf10, "tasa_3m": tb3, "supuestos": SUPUESTO, "perfiles": out}


ESCENARIOS = {"crisis2008": ("Crisis financiera 2008-2009", "2007-10-09", "2009-03-09"),
              "covid2020": ("Pandemia, febrero-marzo 2020", "2020-02-19", "2020-03-23"),
              "tasas2022": ("Inflación y alza de tasas 2022", "2022-01-03", "2022-10-12")}
PROXY_ESTRES = ["SPY", "IJH", "IEF", "TLT", "GLD", "DBC", "BIL"]


def escenarios():
    """Retorno de cada fondo de referencia, con dividendos, entre el máximo y el piso del S&P 500 en tres crisis."""
    import bisect
    series = {}
    for t in PROXY_ESTRES:
        p = datos.precios(t, "max", "1d", ttl_horas=24)
        series[t] = (p["fechas"], p["cierre_aj"])
    out = {}
    for k, (nombre, a, b) in ESCENARIOS.items():
        r = {}
        for t, (f, c) in series.items():
            i, j = bisect.bisect_left(f, a), bisect.bisect_right(f, b) - 1
            if i < len(f) and j >= 0 and f[i] <= b and c[i] and c[j]:
                r[t] = round(c[j] / c[i] - 1, 4)
        out[k] = {"nombre": nombre, "desde": a, "hasta": b, "retornos": r}
    return out


def precios_extra(tickers):
    """Último cierre de fondos y de cualquier ticker que no esté en la tabla de empresas."""
    pr = datos.ultimos_precios([t.replace(".", "-") for t in tickers if t not in UCITS])
    pl = datos.ultimos_precios([UCITS[t][0] for t in tickers if t in UCITS])          # Londres, en dólares
    pr.update({t: pl[UCITS[t][0]] for t in tickers if t in UCITS and UCITS[t][0] in pl})
    return {"generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "precios": {k: round(v, 4) for k, v in pr.items()}}


if __name__ == "__main__":
    P = construir()
    P["escenarios"] = escenarios()
    json.dump(P, open(os.path.join(datos.RAIZ, "datos", "perfiles.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    print("desde", P["desde"], "tasas", P["tasa_10a"], P["tasa_3m"])
    for k, x in P["perfiles"].items():
        print(f"  {x['nombre']:12} hist {x['retorno_hist']*100:5.1f}%  vol {x['volatilidad']*100:5.1f}%  peor caída {x['peor_caida']*100:6.1f}%  peor año {x['peor_anio'][0]} {x['peor_anio'][1]*100:6.1f}%  prosp {x['retorno_prosp']*100:4.1f}%")
    extra = sorted(set(INSTRUMENTOS) | set(UCITS) | set(sys.argv[1:]))
    E = precios_extra(extra)
    json.dump(E, open(os.path.join(datos.RAIZ, "datos", "precios.json"), "w"), separators=(",", ":"))
    print("precios extra:", len(E["precios"]))
