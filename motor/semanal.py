"""Actualización semanal completa. Uso: python3 motor/semanal.py
Orden: costo de capital → ranking → tabla de empresas (con extranjeras) → tasas base → banderas forenses → termómetro del mercado → fichas → índice →
perfiles y precios de fondos → presentaciones a la SEC de las vigiladas → radar de eventos → veredicto cuantitativo e ick → registro de veredictos.
Cada paso deja su registro en datos/semanal.log; si uno falla, sigue con los demás."""
import json, os, subprocess, sys, time, datetime as dt
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = lambda x: os.path.join(RAIZ, "motor", x)
LOG = os.path.join(RAIZ, "datos", "semanal.log")


def paso(nombre, args, salida=None):
    t0 = time.time()
    with open(LOG, "a") as lg:
        lg.write(f"\n=== {nombre} · {dt.datetime.now().isoformat(timespec='seconds')}\n"); lg.flush()
        r = subprocess.run([sys.executable, "-u"] + args, cwd=RAIZ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        out = r.stdout
        if salida:
            open(os.path.join(RAIZ, "datos", salida), "w").write(out)
        lg.write(out[-4000:]); lg.write(f"\n--- {nombre}: {'OK' if r.returncode == 0 else 'ERROR ' + str(r.returncode)} en {time.time() - t0:.0f} s\n")
    print(f"{nombre}: {'OK' if r.returncode == 0 else 'ERROR'} ({time.time() - t0:.0f} s)", flush=True)
    return r.returncode == 0


if __name__ == "__main__":
    open(LOG, "w").write(f"Actualización semanal {dt.date.today()}\n")
    paso("Costo de capital", [M("wacc.py")])
    paso("Ranking del filtro", [M("screener.py")], "filtro.log")
    paso("Tabla de empresas", [M("universo.py")], "universo.log")
    paso("Tasas base", [M("tasas_base.py")])
    paso("Banderas forenses", [M("forense.py")])
    paso("Termómetro del mercado", [M("mercado.py")])
    idx = json.load(open(os.path.join(RAIZ, "datos", "indice.json")))
    orden = [f["ticker"] for f in idx["fichas"] if f.get("investigada")]
    tickers = [f["ticker"] for f in idx["fichas"]]
    paso("Fichas", [M("analista.py")] + tickers, "fichas.log")
    paso("Índice", [M("publicar.py")] + orden)
    paso("Tesis vigilada", [M("tesis.py")])
    paso("Perfiles y precios", [M("perfiles.py")] + sys.argv[1:])
    paso("Presentaciones a la SEC", [M("noticias.py"), "21"])
    paso("Radar de eventos", [M("radar.py")], "radar.log")
    paso("Veredicto cuantitativo e ick", [M("veredicto.py")], "veredicto.log")
    paso("Registro de veredictos", [M("registro.py")])
    print("SEMANAL TERMINADO")
