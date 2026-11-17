"""Vigilancia de noticias, parte verificable: presentaciones a la SEC de las empresas vigiladas.

Lista los formularios recientes (8-K, 6-K, 10-Q, 10-K, 20-F, SC 13D, 4 con compras) de cada ticker
y los guarda en datos/noticias.json junto con las noticias de prensa que agrega la tarea diaria.
Uso: python3 motor/noticias.py [días] [TICKER ...]
"""
import json, os, sys, datetime as dt, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos

ITEMS = {"1.01": "firmó un acuerdo importante", "1.02": "terminó un acuerdo importante", "2.01": "completó una compra o venta de activos",
         "2.02": "publicó resultados", "2.03": "asumió una obligación financiera", "2.05": "anunció costos de reestructuración",
         "2.06": "registró un deterioro de activos", "3.01": "recibió un aviso de la bolsa sobre su cotización",
         "4.01": "cambió de auditor", "4.02": "advirtió que estados financieros anteriores no son confiables",
         "5.02": "cambió directores o ejecutivos", "5.07": "publicó votaciones de su junta de accionistas",
         "7.01": "publicó información para el mercado", "8.01": "informó otro hecho relevante", "5.03": "modificó sus estatutos"}
IMPORTANTES = {"1.01", "1.02", "2.01", "2.03", "2.05", "2.06", "3.01", "4.01", "4.02"}
FORMAS = {"10-Q": "presentó su informe trimestral (10-Q)", "10-K": "presentó su informe anual (10-K)", "20-F": "presentó su informe anual (20-F)",
          "SC 13D": "un inversionista declaró una participación activa de más de 5% (13D)", "SC 13D/A": "actualizó una participación activa de más de 5% (13D)"}


def vigiladas(extra=()):
    t = set(extra)
    ruta = os.path.join(datos.RAIZ, "datos", "indice.json")
    if os.path.exists(ruta):
        t |= {f["ticker"] for f in json.load(open(ruta))["fichas"] if f.get("investigada")}
    ruta = os.path.join(datos.RAIZ, "datos", "portafolio.json")
    if os.path.exists(ruta):
        t |= {a["ticker"] for a in json.load(open(ruta))["activos"] if a.get("tipo") == "Acción"}
    return sorted(t)


def sec(tickers, dias=21):
    desde = (dt.date.today() - dt.timedelta(days=dias)).isoformat()
    items = []
    for tk in tickers:
        cik = datos.cik_de(tk)
        if not cik:
            continue
        sub = datos.get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", ttl_horas=6)
        r = sub["filings"]["recent"]
        for f, a, doc, d, it in zip(r["form"], r["accessionNumber"], r["primaryDocument"], r["filingDate"], r["items"]):
            if d < desde:
                break
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{a.replace('-', '')}/{doc}"
            if f in ("8-K", "8-K/A", "6-K"):
                cods = [x.strip() for x in (it or "").split(",") if x.strip() and x.strip() != "9.01"]
                if f == "6-K":
                    texto = "presentó un informe al mercado (6-K)"
                else:
                    texto = "; ".join(ITEMS.get(c, f"informó el ítem {c}") for c in cods) or "informó un hecho relevante"
                imp = 3 if any(c in IMPORTANTES for c in cods) else 2 if ("2.02" in cods or "5.02" in cods) else 1
                items.append({"fecha": d, "ticker": tk, "tipo": "sec", "titulo": f"{tk} {texto}", "resumen": f"Formulario {f}" + (f", ítems {', '.join(cods)}" if cods else "") + ".",
                              "impacto": "neutral", "importancia": imp, "verificado": True, "fuente": {"nombre": f"SEC: formulario {f}", "url": url}})
            elif f in FORMAS:
                items.append({"fecha": d, "ticker": tk, "tipo": "sec", "titulo": f"{tk} {FORMAS[f]}", "resumen": f"Formulario {f}.",
                              "impacto": "neutral", "importancia": 2 if f.startswith("SC") else 1, "verificado": True, "fuente": {"nombre": f"SEC: formulario {f}", "url": url}})
    return items


def fusionar(nuevos, dias_guardar=45):
    ruta = os.path.join(datos.RAIZ, "datos", "noticias.json")
    previo = json.load(open(ruta)) if os.path.exists(ruta) else {"items": []}
    clave = lambda x: (x["ticker"], x["fuente"]["url"])
    todos = {clave(x): x for x in previo["items"]}
    for x in nuevos:
        todos[clave(x)] = x
    limite = (dt.date.today() - dt.timedelta(days=dias_guardar)).isoformat()
    items = sorted((x for x in todos.values() if x["fecha"] >= limite), key=lambda x: (x["fecha"], x.get("importancia", 1)), reverse=True)
    return {"generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "vigiladas": previo.get("vigiladas", []), "items": items}


if __name__ == "__main__":
    dias = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 21
    tk = vigiladas([a for a in sys.argv[1:] if not a.isdigit()])
    N = fusionar(sec(tk, dias)); N["vigiladas"] = tk
    json.dump(N, open(os.path.join(datos.RAIZ, "datos", "noticias.json"), "w"), ensure_ascii=False, indent=1)
    print(len(tk), "vigiladas;", len(N["items"]), "noticias")
    for x in N["items"][:12]:
        print(" ", x["fecha"], x["titulo"][:90])
