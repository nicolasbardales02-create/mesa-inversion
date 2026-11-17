"""Reúne los datos que la página lee: índice de fichas y, si se pide, refresca las fichas."""
import json, os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos


def indice(orden=None):
    fichas = []
    for ruta in glob.glob(os.path.join(datos.RAIZ, "datos", "fichas", "*.json")):
        d = json.load(open(ruta))
        v = d.get("veredicto") or {}
        try:  # 52 cierres semanales del último año para el minigráfico (de la caché de precios)
            px = datos.precios(d["ticker"].replace(".", "-"), "10y", "1d", ttl_horas=72)
            c = px["cierre"][-260:]
            spark = [round(x, 2) for x in c[::5]] + ([round(c[-1], 2)] if (len(c) - 1) % 5 else [])
        except Exception:
            spark = []
        fichas.append({"spark": spark, "ticker": d["ticker"], "nombre": d["nombre"], "sector": d["sector"],
                       "precio": d["precio"]["ultimo"], "zona": v.get("zona"), "margen": v.get("margen_seguridad"),
                       "investigada": bool(d.get("investigacion")), "generado": d["generado"],
                       "etiqueta": (d.get("investigacion") or {}).get("etiqueta"),
                       "tono": (d.get("investigacion") or {}).get("tono"),
                       "titular": (d.get("investigacion") or {}).get("titular"),
                       "postura": ((d.get("investigacion") or {}).get("conclusion") or {}).get("postura"),
                       "desde_max": d["precio"].get("desde_max_52s"), "tamano": d.get("tamano")})
    orden = orden or []
    fichas.sort(key=lambda f: (orden.index(f["ticker"]) if f["ticker"] in orden else 999, not f["investigada"], f["ticker"]))
    with open(os.path.join(datos.RAIZ, "datos", "indice.json"), "w") as f:
        json.dump({"fichas": fichas}, f, separators=(",", ":"))
    return fichas


if __name__ == "__main__":
    print([f["ticker"] for f in indice(sys.argv[1:])])
