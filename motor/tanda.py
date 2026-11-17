"""Tanda completa: fichas de las mejores candidatas del filtro y armado del portafolio."""
import json, os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos, analista, portafolio, publicar

def main(n=16, por_sector=3, fijas=("NVDA",)):
    F = json.load(open(os.path.join(datos.RAIZ, "datos", "filtro.json")))
    pool, cuenta = [], {}
    for c in F["candidatas"]:
        if cuenta.get(c["sector"], 0) >= por_sector:
            continue
        cuenta[c["sector"]] = cuenta.get(c["sector"], 0) + 1
        pool.append(c)
        if len(pool) >= n:
            break
    listas = []
    for c in pool:
        t = c["ticker"]
        try:
            d = analista.ficha(t)
            with open(os.path.join(datos.RAIZ, "datos", "fichas", f"{t}.json"), "w") as f:
                json.dump(d, f, separators=(",", ":"))
            v = d.get("veredicto") or {}
            riesgos = sum(1 for s in d["senales"] if s["tipo"] == "riesgo")
            print(f"ficha {t}: {v.get('zona')} margen {v.get('margen_seguridad')} riesgos {riesgos} sector {d['sector']}", flush=True)
            if v.get("margen_seguridad") is not None and v["margen_seguridad"] >= 0.10 and riesgos <= 1:
                listas.append({"ticker": t, "nombre": d["nombre"], "sector": d["sector"], "puntaje": c["puntaje"],
                               "potencial": v["margen_seguridad"], "tamano": d["tamano"]})
        except Exception as e:
            print(f"ficha {t}: ERROR {e}", flush=True)
    print("aptas para portafolio:", [x["ticker"] for x in listas], flush=True)
    try:
        P = portafolio.construir(listas)
        with open(os.path.join(datos.RAIZ, "datos", "portafolio.json"), "w") as f:
            json.dump(P, f, separators=(",", ":"))
        for a in P["activos"]:
            print(f"  {a['ticker']:5} {a['tipo']:14} {a['sector'][:20]:20} peso {a['peso']*100:5.1f}% vol {a['volatilidad']*100:4.0f}% corrSPY {a['corr_sp500']:.2f} estrés {a['corr_sp500_estres'] if a['corr_sp500_estres'] is None else round(a['corr_sp500_estres'],2)}")
        print("corr prom", round(P["corr_prom"], 3), "acciones", round(P["corr_prom_acciones"], 3), "estrés", round(P["corr_prom_estres"], 3), round(P["corr_prom_acciones_estres"], 3))
        for k in ("cartera", "solo_acciones", "sp500"):
            print(k, {x: round(y, 3) for x, y in P[k].items() if y is not None})
        print({k: (round(v["promedio"], 2), v["expuestos"]) for k, v in P["factores_comunes"].items()})
    except Exception:
        traceback.print_exc()
    publicar.indice(list(fijas) + [x["ticker"] for x in listas])
    print("TANDA TERMINADA", flush=True)

if __name__ == "__main__":
    main()
