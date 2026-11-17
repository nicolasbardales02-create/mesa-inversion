"""Revisión cualitativa barata: arma expedientes cortos para que una IA responda una sola pregunta por empresa:
¿hay algo que los números todavía no muestran? (y, para las candidatas ick: ¿el rechazo es temporal o de fondo?)

El código hace el trabajo pesado y gratuito: elige las empresas y extrae de la SEC solo lo que importa:
  - el comienzo del análisis de la gerencia (MD&A) del último 10-Q o 10-K (20-F: "Operating and Financial Review"),
  - el comunicado de resultados del último 8-K con punto 2.02 (anexo 99.1),
  - el resumen de cifras del sistema (veredicto, motivos ick, riesgos).
Cada expediente queda en expedientes/<TICKER>.md (unos 10 mil caracteres) para que la lectura cueste poco.

Uso: python3 motor/cualitativa.py [n_candidatas=4] [n_ick=4] [TICKER extra ...]
También: python3 motor/cualitativa.py fusionar nuevas.json   → agrega revisiones a datos/revisiones.json
"""
import html, json, os, re, sys, datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
import datos

RUTA = os.path.join(datos.RAIZ, "datos", "revisiones.json")
DIR = os.path.join(datos.RAIZ, "expedientes")


def _texto(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def _url(cik, acc, doc):
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"


def mdna(cik, n=6500):
    sub = datos.presentaciones(cik)
    if not sub:
        return None, None
    r = sub["filings"]["recent"]
    for forma, acc, doc, fecha in zip(r["form"], r["accessionNumber"], r["primaryDocument"], r["filingDate"]):
        if forma in ("10-Q", "10-K", "20-F", "40-F"):
            try:
                t = _texto(datos.get(_url(cik, acc, doc), ttl_horas=24 * 30) or "")
            except Exception:
                return None, None
            pat = r"(?i)management.s discussion and analysis|operating and financial review"
            pos = [m.start() for m in re.finditer(pat, t)]
            # la primera aparición suele ser el índice: se toma la que tenga más texto a continuación
            inicio = next((p for p in pos[1:] if len(t) - p > 3000), pos[0] if pos else None)
            if inicio is None:
                return None, None
            # saltar el texto de rigor y empezar en el resumen ejecutivo o en los resultados
            ventana = t[inicio + 200:inicio + 9000]
            for pat in (r"(?i)\bexecutive summary\b", r"(?i)\bbusiness overview\b", r"\bOVERVIEW\b|\bOverview\b", r"\bRESULTS OF OPERATIONS\b|\n\s*Results of Operations"):
                m = re.search(pat, ventana)
                if m:
                    inicio += 200 + m.start(); break
            return f"{forma} del {fecha} · {_url(cik, acc, doc)}", t[inicio:inicio + n]
    return None, None


def resultados(cik, n=3500):
    sub = datos.presentaciones(cik)
    if not sub:
        return None, None
    r = sub["filings"]["recent"]
    for forma, acc, items, fecha in zip(r["form"], r["accessionNumber"], r.get("items", [""] * len(r["form"])), r["filingDate"]):
        if forma == "8-K" and "2.02" in (items or ""):
            try:
                idx = datos.get_json(_url(cik, acc, "index.json"), ttl_horas=24 * 30)
                htm = [x["name"] for x in idx["directory"]["item"] if x["name"].lower().endswith((".htm", ".html")) and "index" not in x["name"].lower()]
                arch = [n for n in htm if re.search(r"(?i)ex(hibit)?[\W_]*99", n)] or [n for n in htm if re.search(r"(?i)press|release|earnings|result", n)]
                if not arch:
                    return None, None
                t = _texto(datos.get(_url(cik, acc, arch[0]), ttl_horas=24 * 30) or "")
                return f"comunicado de resultados del {fecha} · {_url(cik, acc, arch[0])}", t[:n]
            except Exception:
                return None, None
    return None, None


def elegir(n_c, n_i, extra):
    U = json.load(open(os.path.join(datos.RAIZ, "datos", "universo.json")))
    F = [dict(zip(U["cols"], r)) for r in U["filas"]]
    import glob
    investigadas = {os.path.basename(x)[:-5] for x in glob.glob(os.path.join(datos.RAIZ, "investigacion", "*.json"))}
    prev = json.load(open(RUTA)).get("items", {}) if os.path.exists(RUTA) else {}
    hoy = dt.date.today()
    reciente = lambda t: t in prev and (hoy - dt.date.fromisoformat(prev[t]["fecha"])).days < 28   # no repetir antes de 4 semanas
    cand = [f for f in sorted(F, key=lambda f: -(f.get("vqp") or -99)) if f.get("vq") == "candidata" and f["t"] not in investigadas and not reciente(f["t"])][:n_c]
    ick = [f for f in sorted(F, key=lambda f: -(f["ick"] if f.get("ick") is not None else -99)) if f.get("ick") is not None
           and f["t"] not in investigadas and not reciente(f["t"]) and f not in cand][:n_i]
    por_t = {f["t"]: f for f in F}
    ext = [por_t[t] for t in extra if t in por_t]
    return [(f, "candidata") for f in cand] + [(f, "ick") for f in ick] + [(f, "pedida") for f in ext]


def construir(n_c=4, n_i=4, extra=(), log=print):
    os.makedirs(DIR, exist_ok=True)
    cik_de = {}
    for t in datos.tickers_sec():
        cik_de.setdefault(t["ticker"], t["cik"])
    elegidas = elegir(n_c, n_i, extra)
    lista = []
    for f, motivo in elegidas:
        c = cik_de.get(f["t"])
        if not c:
            continue
        fm, tm = mdna(c)
        fr, tr = resultados(c)
        partes = [f"# {f['t']} · {f['n']}", f"Sector: {f.get('s')} · Industria: {f.get('ind')} · País: {f.get('pais') or 'EE.UU.'} · Capitalización: {f.get('cap')}",
                  f"Por qué se revisa: {'candidata del veredicto cuantitativo' if motivo == 'candidata' else 'candidata ick (barata y rechazada)' if motivo == 'ick' else 'pedida por el usuario'}",
                  "## Cifras del sistema",
                  f"Veredicto cuantitativo: {f.get('vq')} (puntaje {f.get('vqp')}). Razones: " + "; ".join((f.get("vqr") or "").split("|")),
                  f"P/U {f.get('per')}, VE/utilidad operativa {f.get('vee')}, caja libre/precio {f.get('rf')}, margen operativo {f.get('mo')}, crecimiento de ventas 3 años {f.get('c3')}, deuda neta {f.get('dn')}, caída desde máximo 52 semanas {f.get('dd52')}, retorno 1 año {f.get('r1a')}, banderas forenses: {f.get('rojas') or 'ninguna'}"]
        if f.get("ick") is not None:
            partes += [f"Motivos ick: " + "; ".join((f.get("ickm") or "").split("|")), "Catalizadores: " + ("; ".join((f.get("ickc") or "").split("|")) or "ninguno"),
                       "Riesgos de trampa: " + ("; ".join((f.get("ickr") or "").split("|")) or "ninguno")]
        partes += [f"## Análisis de la gerencia ({fm or 'no disponible'})", tm or "(no se pudo extraer)",
                   f"## Resultados ({fr or 'no disponible'})", tr or "(no se pudo extraer)"]
        ruta = os.path.join(DIR, f["t"] + ".md")
        open(ruta, "w").write("\n\n".join(partes))
        lista.append({"ticker": f["t"], "motivo": motivo, "expediente": os.path.relpath(ruta, datos.RAIZ), "caracteres": sum(len(p) for p in partes)})
        log(f"{f['t']} ({motivo}): {lista[-1]['caracteres']} caracteres; MD&A: {fm}; resultados: {fr}")
    json.dump(lista, open(os.path.join(DIR, "lista.json"), "w"), ensure_ascii=False, indent=1)
    log("EXPEDIENTES LISTOS: " + " ".join(x["ticker"] for x in lista))
    return lista


def fusionar(ruta_nuevas):
    """Agrega o reemplaza revisiones (una por empresa, la más reciente) y conserva el historial anterior."""
    R = json.load(open(RUTA)) if os.path.exists(RUTA) else {"items": {}, "historial": []}
    for x in json.load(open(ruta_nuevas)):
        t = x["ticker"]
        if t in R["items"]:
            R["historial"].append(R["items"][t])
        R["items"][t] = x
    R["generado"] = dt.datetime.now().isoformat(timespec="minutes")
    json.dump(R, open(RUTA, "w"), ensure_ascii=False, indent=1)
    print(f"revisiones: {len(R['items'])} empresas")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "fusionar":
        fusionar(a[1])
    else:
        nums = [int(x) for x in a[:2] if x.isdigit()]
        construir(*(nums + [4, 4][len(nums):]), extra=[x.upper() for x in a[len(nums):]], log=lambda *z: print(*z, flush=True))
