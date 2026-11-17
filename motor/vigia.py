"""El Vigía: caída del S&P 500 desde su máximo histórico (cierres diarios).

Regla (determinista, sin estado guardado: todo se deriva de la serie de precios):
  caída_t = cierre_t / máximo_histórico_hasta_t - 1
  Escalones: -5, -10, -15, -20, -25, -30, -40, -50 %.
  Un escalón suena UNA vez por episodio, el día que el cierre lo cruza por primera vez.
  El episodio se rearma cuando el índice vuelve a estar a menos de 2 % de su máximo.
"""
import json, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos

ESCALONES = [5, 10, 15, 20, 25, 30, 40, 50]
REARME = 2.0  # % bajo el máximo por encima del cual se rearma la alarma


def escalon(caida_pct):
    """Escalón más profundo alcanzado por una caída (número positivo, en %)."""
    e = 0
    for x in ESCALONES:
        if -caida_pct >= x - 1e-9:
            e = x
    return e


def analizar(fechas, cierres):
    maximo, f_max = cierres[0], fechas[0]
    alcanzado = 0
    alertas, caidas, episodios = [], [], []
    ep = None
    for f, c in zip(fechas, cierres):
        if c >= maximo:
            if ep:  # recuperación total: cierra el episodio
                ep["fin"] = f
                ep["dias_recuperacion"] = (dt.date.fromisoformat(f) - dt.date.fromisoformat(ep["fecha_piso"])).days
                episodios.append(ep); ep = None
            maximo, f_max = c, f
        dd = (c / maximo - 1) * 100
        caidas.append(dd)
        if dd > -REARME:
            alcanzado = 0
        e = escalon(dd)
        if e > alcanzado:
            alcanzado = e
            alertas.append({"fecha": f, "escalon": e, "caida": round(dd, 2), "cierre": round(c, 2),
                            "maximo": round(maximo, 2), "fecha_maximo": f_max})
        if dd <= -5:
            if ep is None:
                ep = {"inicio": f_max, "maximo": round(maximo, 2), "piso": c, "fecha_piso": f,
                      "caida_max": dd, "cruce": f, "fin": None, "dias_recuperacion": None}
            if dd < ep["caida_max"]:
                ep.update(piso=c, fecha_piso=f, caida_max=dd)
    if ep:
        episodios.append(ep)
    for e in episodios:
        e["piso"] = round(e["piso"], 2); e["caida_max"] = round(e["caida_max"], 2)
        e["dias_caida"] = (dt.date.fromisoformat(e["fecha_piso"]) - dt.date.fromisoformat(e["inicio"])).days
    return caidas, alertas, episodios, maximo, f_max, alcanzado


def construir(ttl_horas=0, previo=None):
    """previo: el vigia.json de la corrida anterior. Sirve para avisar exactamente una vez:
    son nuevas las alertas con fecha posterior al último cierre ya procesado."""
    p = datos.precios("^GSPC", "max", "1d", ttl_horas=ttl_horas)
    fechas, cierres = p["fechas"], p["cierre"]
    intradia = None
    if p.get("en_curso"):  # la rueda de hoy no ha cerrado: se muestra, pero no cuenta para la alarma
        f_hoy, c_vivo = fechas[-1], cierres[-1]
        fechas, cierres = fechas[:-1], cierres[:-1]
        tope = max(max(cierres), c_vivo)
        intradia = {"fecha": f_hoy, "hora": p.get("hora"), "precio": round(c_vivo, 2),
                    "caida": round((c_vivo / tope - 1) * 100, 2), "var": round((c_vivo / cierres[-1] - 1) * 100, 2)}
    caidas, alertas, episodios, maximo, f_max, alcanzado = analizar(fechas, cierres)
    hoy, c_hoy, dd_hoy = fechas[-1], cierres[-1], caidas[-1]
    if previo and previo.get("fecha"):
        nuevas = [a for a in alertas if a["fecha"] > previo["fecha"]]
    else:
        hoy_ny = dt.datetime.now(dt.timezone(dt.timedelta(hours=-5))).date().isoformat()
        nuevas = [a for a in alertas if a["fecha"] == hoy == hoy_ny]
    alerta_hoy = alertas[-1] if alertas and alertas[-1]["fecha"] == hoy else None

    def var(n):
        return round((cierres[-1] / cierres[-1 - n] - 1) * 100, 2) if len(cierres) > n else None

    # frecuencia histórica de cada escalón (desde 1950 y últimos 20 años)
    def frecuencia(desde):
        al = [a for a in alertas if a["fecha"] >= desde]
        anios = (dt.date.fromisoformat(hoy) - dt.date.fromisoformat(max(desde, fechas[0]))).days / 365.25
        return {str(e): {"veces": sum(1 for a in al if a["escalon"] == e),
                         "cada_anios": (round(anios / n, 1) if (n := sum(1 for a in al if a["escalon"] == e)) else None)}
                for e in ESCALONES}

    hace20 = (dt.date.fromisoformat(hoy) - dt.timedelta(days=int(365.25 * 20))).isoformat()
    caidas_diarias = sum(1 for i in range(1, len(cierres))
                         if fechas[i] >= "1950-01-01" and cierres[i] / cierres[i - 1] - 1 <= -0.05)
    # serie para el gráfico: semanal desde 1990 + diaria último año
    serie = [{"f": f, "c": round(c, 2), "d": round(d, 2)}
             for i, (f, c, d) in enumerate(zip(fechas, cierres, caidas))
             if f >= "1990-01-01" and (i % 5 == 0 or i >= len(fechas) - 260)]
    falta = {str(e): round(maximo * (1 - e / 100), 2) for e in ESCALONES[:4]}
    return {
        "actualizado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "fuente": "Yahoo Finance, índice ^GSPC, cierres diarios",
        "fecha": hoy, "cierre": round(c_hoy, 2), "maximo": round(maximo, 2), "fecha_maximo": f_max,
        "caida": round(dd_hoy, 2), "escalon_actual": escalon(dd_hoy), "escalon_ya_avisado": alcanzado,
        "var_1d": var(1), "var_5d": var(5), "var_21d": var(21),
        "niveles": falta, "alerta_hoy": alerta_hoy, "alertas_nuevas": nuevas, "intradia": intradia,
        "alertas_recientes": alertas[-12:][::-1],
        "frecuencia_desde_1950": frecuencia("1950-01-01"), "frecuencia_20_anios": frecuencia(hace20),
        "caidas_diarias_5pct_desde_1950": caidas_diarias,
        "episodios": [e for e in episodios if e["inicio"] >= "1950-01-01"][::-1],
        "serie": serie, "escalones": ESCALONES, "rearme": REARME,
    }


def mensaje(v):
    if not v["alertas_nuevas"]:
        return None
    a = max(v["alertas_nuevas"], key=lambda x: (x["fecha"], x["escalon"]))
    return (f"ALERTA S&P 500: cayó {abs(a['caida']):.1f}% desde su máximo "
            f"(escalón -{a['escalon']}%). Cierre {a['cierre']:,.2f} el {a['fecha']}; "
            f"máximo {a['maximo']:,.2f} del {a['fecha_maximo']}.")


if __name__ == "__main__":
    salida = os.path.join(datos.RAIZ, "datos", "vigia.json")
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    previo = json.load(open(salida)) if os.path.exists(salida) else None
    v = construir(previo=previo)
    with open(salida, "w") as f:
        json.dump(v, f, separators=(",", ":"))
    print(f"S&P 500 {v['fecha']}: cierre {v['cierre']:,.2f} | máximo {v['maximo']:,.2f} ({v['fecha_maximo']}) | caída {v['caida']:.2f}%")
    if v["intradia"]:
        i = v["intradia"]
        print(f"Rueda en curso {i['hora']} NY: {i['precio']:,.2f} ({i['caida']:.2f}% desde el máximo); no cuenta para la alarma")
    print(mensaje(v) or "SIN ALERTA NUEVA")
