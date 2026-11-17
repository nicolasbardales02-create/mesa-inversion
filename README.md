# Mesa de Inversión

Sistema personal de análisis de acciones: unas 3,700 empresas con datos de la SEC (EDGAR) y precios de mercado, valorización por flujo de caja descontado con costo de capital por sector, banderas forenses, tasas base históricas, radar de eventos (compras de directivos, activistas, fusiones), veredicto cuantitativo, candidatas *ick* (baratas y rechazadas), termómetro del mercado e investigaciones a fondo con criterios vigilados.

**Abrir la app:** la página de este repositorio en GitHub Pages. En el celular, ábrela en el navegador y elige "Agregar a inicio" para usarla como app.

> Uso personal y educativo. No es una recomendación de inversión. Las cifras salen de fuentes públicas y pueden tener errores.

## Cómo se actualiza

Tareas automáticas en Claude:

| Tarea | Cuándo (hora de Nueva York) | Qué hace |
|---|---|---|
| Vigía S&P 500 | días hábiles, 5:10 p.m. | Avisa por ntfy si el índice cruza un nuevo escalón de caída (5%, 10%, 15%…) |
| Noticias | días hábiles, 7:41 a.m. | Presentaciones a la SEC y noticias de las empresas vigiladas |
| Actualización semanal | sábados, 1:58 p.m. | Precios, estados financieros, tabla de empresas, veredicto, tesis y registro |
| Revisión cualitativa | domingos, 10:23 a.m. | Lee resultados y noticias de ~8 candidatas: ¿hay algo que los números no muestran? |

## Estructura

- `index.html`, `manifest.json`: la página (versión para GitHub Pages, generada por `motor/sitio.py`).
- `web/index.html`: la misma página tal como se publica en Claude.
- `datos/`: datos que lee la página (JSON).
- `investigacion/`: investigaciones a fondo, con pre-mortem y criterios de entrada y salida.
- `motor/`: código Python que descarga, calcula y arma los datos (`python3 motor/semanal.py` corre todo).

Fuera de Claude la página no guarda portafolios ni tiene el chat del analista: esas dos funciones usan la cuenta de Claude.
