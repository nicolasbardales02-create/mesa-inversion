"""Versión de la página para abrirla fuera de Claude (GitHub Pages) y guardarla como app en el celular.

La página del artefacto (web/index.html) no trae doctype porque claude.ai la envuelve al publicar. Este script
escribe un documento completo (doctype, charset, viewport, manifiesto e íconos para "Agregar a inicio").
Los datos se leen con rutas relativas (datos/..., investigacion/...), así que la raíz del repositorio sirve tal cual.
Fuera de claude.ai no hay base de datos ni IA: la página ya lo detecta (no guarda portafolios, no hay chat) y
muestra todo lo demás normalmente.

Uso:
  python3 motor/sitio.py                 escribe index.html y manifest.json en la raíz de este proyecto
  python3 motor/sitio.py espejo <repo>   copia página, datos, investigaciones y motor a la carpeta <repo>
                                         (un clon del repositorio de GitHub Pages); nunca borra nada allí
"""
import glob, json, os, shutil, sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CABECERA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0B1020">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Mesa">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="robots" content="noindex, nofollow">
<link rel="manifest" href="manifest.json">
<link rel="icon" type="image/png" sizes="192x192" href="web/app/icono-192.png">
<link rel="apple-touch-icon" href="web/app/icono-180.png">
"""

MANIFIESTO = {
    "name": "Mesa de Inversión",
    "short_name": "Mesa",
    "start_url": "./index.html",
    "scope": "./",
    "display": "standalone",
    "background_color": "#F4F6FA",
    "theme_color": "#0B1020",
    "lang": "es",
    "icons": [
        {"src": "web/app/icono-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "web/app/icono-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "web/app/icono-mask-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}


def fuente_pagina(origen=RAIZ):
    """Texto de la página tal como se publica en el artefacto (sin el envoltorio de claude.ai)."""
    for ruta in (os.path.join(origen, "web", "index.html"), os.path.join(origen, "index.html")):
        if os.path.exists(ruta):
            t = open(ruta, encoding="utf-8").read()
            if t.lstrip().lower().startswith("<!doctype"):
                if "apple-mobile-web-app-title" in t:      # ya es la versión para GitHub Pages
                    continue
                t = t[t.find("<body>") + 6:].rsplit("</body>", 1)[0].strip()   # copia leída del artefacto
            return t
    raise FileNotFoundError("no encontré la página (web/index.html o index.html)")


def construir(destino=RAIZ, origen=RAIZ):
    fuente = fuente_pagina(origen)
    corte = fuente.find("</style>")     # el artefacto empieza con <title> y <style> sueltos: van al <head>
    corte = corte + len("</style>") if corte >= 0 else 0
    html = CABECERA + fuente[:corte] + "\n</head>\n<body>\n" + fuente[corte:] + "\n</body>\n</html>\n"
    open(os.path.join(destino, "index.html"), "w", encoding="utf-8").write(html)
    json.dump(MANIFIESTO, open(os.path.join(destino, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(destino, ".nojekyll"), "w").close()   # GitHub Pages: servir los archivos tal cual
    os.makedirs(os.path.join(destino, "web"), exist_ok=True)
    open(os.path.join(destino, "web", "index.html"), "w", encoding="utf-8").write(fuente)   # fuente del artefacto
    print(f"sitio listo en {destino}: index.html ({len(html) // 1024} KB) y manifest.json")


def espejo(repo, origen=RAIZ):
    """Copia lo publicable a un clon del repositorio. Solo agrega o reemplaza: nunca borra."""
    n = 0
    patrones = ["README.md", "datos/*.json", "datos/fichas/*.json", "investigacion/*.json", "motor/*.py", "web/app/*.png"]
    for pat in patrones:
        for f in glob.glob(os.path.join(origen, pat)):
            rel = os.path.relpath(f, origen)
            if os.path.basename(rel).startswith(("universo.antes_", "nuevas")):
                continue
            os.makedirs(os.path.dirname(os.path.join(repo, rel)), exist_ok=True)
            shutil.copy2(f, os.path.join(repo, rel)); n += 1
    construir(destino=repo, origen=origen)
    print(f"espejo: {n} archivos copiados a {repo}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "espejo":
        espejo(os.path.abspath(a[1]))
    else:
        construir()
