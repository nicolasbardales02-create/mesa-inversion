"""Tesis vigilada: revisa cada semana los criterios de salida y de entrada de cada empresa investigada.

Los criterios viven en investigacion/<T>.json ("criterios": tipo, métrica, operador, umbral, texto) y se
miden contra la ficha recién actualizada (datos/fichas/<T>.json). Tipos:
  - entrada: el precio llegó a la zona de compra con margen de seguridad.
  - salida: se rompió un supuesto de la tesis → revisar la conclusión (y la posición, si la tienes).
  - revisar: el precio ya descuenta el escenario bueno → el alza restante es poca.
  - manual: algo que las cifras no miden y hay que mirar a mano (se muestra, no se evalúa).
Uso: python3 motor/tesis.py
"""
import glob, json, os, sys, datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
import datos

RUTA = os.path.join(datos.RAIZ, "datos", "tesis.json")


def metricas(f):
    t, m, p = f["ttm"], f["multiplos"], f["precio"]
    ing = t.get("ingresos")
    hist = [h for h in f.get("historia", []) if h.get("ingresos")]
    ult = hist[-1]["ingresos"] if hist else None
    return {"precio": p.get("ultimo"),
            "margen_oper": t["util_oper"] / ing if ing and t.get("util_oper") is not None else None,
            "margen_fcf": t["fcf_sbc"] / ing if ing and t.get("fcf_sbc") is not None else None,
            "deuda_ebit": m.get("deuda_neta_ebit"),
            "rend_caja": m.get("rend_fcf_sbc"),
            # ventas de los últimos 12 meses frente al último año fiscal completo (negativo = las ventas caen)
            "ventas_vs_anual": (ing / ult - 1) if ing and ult else None}


def construir(log=print):
    out = {"generado": dt.datetime.now().isoformat(timespec="minutes"), "empresas": {}}
    for ruta in sorted(glob.glob(os.path.join(datos.RAIZ, "investigacion", "*.json"))):
        t = os.path.basename(ruta)[:-5]
        inv = json.load(open(ruta))
        fr = os.path.join(datos.RAIZ, "datos", "fichas", t + ".json")
        if not inv.get("criterios") or not os.path.exists(fr):
            continue
        M = metricas(json.load(open(fr)))
        crit = []
        for c in inv["criterios"]:
            x = dict(c)
            if c.get("metrica"):
                v = M.get(c["metrica"])
                x["actual"] = v
                x["cumple"] = None if v is None else (v <= c["valor"] if c["op"] == "<=" else v < c["valor"] if c["op"] == "<"
                                                      else v >= c["valor"] if c["op"] == ">=" else v > c["valor"])
            crit.append(x)
        activos = [c for c in crit if c.get("cumple")]
        out["empresas"][t] = {"premortem": inv.get("premortem"), "tono": inv.get("tono"), "fecha_conclusion": inv.get("fecha"),
                              "criterios": crit, "salida": sum(1 for c in activos if c["tipo"] == "salida"),
                              "entrada": any(c["tipo"] == "entrada" for c in activos),
                              "revisar": any(c["tipo"] == "revisar" for c in activos)}
        log(f"{t}: " + ", ".join(f"{c['tipo']}:{c['metrica']}={c.get('actual')}→{c.get('cumple')}" for c in crit if c.get("metrica")))
    json.dump(out, open(RUTA, "w"), ensure_ascii=False, separators=(",", ":"))
    log("TESIS TERMINADO")
    return out


if __name__ == "__main__":
    construir()
