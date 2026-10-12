# Argos

CLI y librería en Python para **navegar e investigar Facebook e Instagram con Playwright**.

A diferencia de otras herramientas del ecosistema, Argos no instala CLIs de terceros: trae su
propio motor de navegador (sesión persistente), ejecuta el login una sola vez de forma humana y
después expone comandos reproducibles y parseables para humanos y agentes.

> Estado: **Fases 0–4** (núcleo de navegador + Instagram completo + Facebook: páginas, búsqueda y grupos).
> Pendiente: store/reportes (5) y hardening (6) — ver [`PLAN.md`](PLAN.md).

## Cómo funciona

- **Sesión persistente por plataforma** en `~/.argos/profiles/<plataforma>/` (o `$ARGOS_HOME`).
  El login lo hacés vos en una ventana de Chrome; Argos nunca pide ni guarda contraseñas.
- **Probes reales**: `argos doctor` abre el navegador y verifica la sesión contra las APIs
  internas de cada plataforma (no alcanza con "hay cookies").
- **Parada segura**: ante login-walls, checkpoints o rate-limits, Argos guarda evidencia
  (screenshot + HTML) en `~/.argos/debug/`, corta con un exit code específico y no reintenta
  a lo bruto.
## Integración con agentes y n8n

```bash
argos skill --install    # copia el SKILL.md a ~/.config/opencode/skills/, ~/.claude/skills/ y ~/.agents/skills/
argos skill --path       # ruta del SKILL.md empaquetado (para referencia manual)
argos quota --json       # acciones usadas/restantes hoy (sin navegador, para gatear antes de correr)
argos mcp                # servidor MCP (stdio) con las lecturas como tools tipadas
```

- **Agentes (OpenCode, Claude Code, Cursor…):** con `argos skill --install` el agente descubre
  el skill y sabe qué comandos usar, el contrato JSON, los exit codes y las reglas de
  seguridad (solo lectura, chequeo de cuota, frenar ante límites). O le pasás el contenido
  de `argos skill --path` directamente.
- **n8n:** dos vías. (1) Nodo *Execute Command* → `argos … --json` + parsear stdout.
  (2) Nodo *MCP Client* apuntando a `argos mcp` (requiere `pip install 'argos[mcp]'`), y
  llamás `fb_search`, `ig_profile`, `doctor`, `quota`, etc. como herramientas tipadas.
- Contrato estable: `--json` va a stdout, el progreso a stderr, exit codes 0–5.

## Personalizada: enriquecimiento de leads (sector médico)

En la UI (menú **Investigación → Personalizada**) o por CLI:

```bash
argos leads template --out leads.csv
argos leads enrich leads.csv --sector medico --out ./leads-out
```

Entra tu lista del CRM (**Nombre, Correo, Teléfono, Empresa/clínica/hospital** — cualquiera
de los cuatro, en CSV/TSV o pegado) y sale una fila por lead con las columnas del CRM y la
validación de **ramo médico**:

- **Fuentes sin login**: SearxNG propio (web, teléfonos, Facebook), Google Maps (ficha,
  categoría, dirección, teléfono) y Nominatim reverse (Entidad/Ciudad). LinkedIn, después.
- **Fuentes activables**: en la UI cada una tiene su switch (se guarda en
  `leads_sources` de `config.yaml`); el pipeline respeta lo activo. Overrides por corrida:
  `--no-searxng --no-facebook --no-gmaps --no-nominatim`.
- **Tandas**: `--batch-size 20 --pause-seconds 180` (la UI lo trae puesto por defecto)
  para lotes grandes sin saturar la búsqueda.
- **Validación de sector** con señales (categorías médicas, "Dr./Dra.", especialidades,
  IMSS/ISSSTE, dominios…) y **confianza + evidencia** por dato. Lo dudoso **no se auto-llena**.
- **Tipo de cliente** se mapea al enum del CRM (incluye `No es del ramo`).
- **Salida**: `leads.csv` (Nombre, Apellido, Correo, Teléfono, Entidad, Ciudad, Tipo de
  cliente, Especialidad, Categoría, Facebook, Google Maps, Observaciones, Ramo médico,
  Confianza, Evidencias) + `leads.json` + `report.md`. Escritura **incremental**: un lote
  largo se puede cortar sin perder lo hecho.

## Más plataformas: YouTube, LinkedIn y X

```bash
argos fetch yt_search "inteligencia artificial" --limit 10 --json
argos fetch yt_channel "@nasa" --limit 12 --out ./yt
argos fetch yt_video "https://youtu.be/VIDEOID" --limit 20    # video + comentarios
argos fetch li_profile "ana-lopez-123" --out ./li             # requiere sesión
argos fetch li_search "marketing" --kind people
argos fetch x_profile "@nasa" --limit 20                      # requiere sesión
argos fetch x_search "deepseek" --kind latest
```

- **YouTube**: público, sin login. Búsqueda (videos/canales), canal (perfil + videos) y
  video + comentarios. Parsea `ytInitialData` (el JSON embebido de la página), por lo
  que aguanta cambios de layout mejor que selectores CSS.
- **LinkedIn** y **X**: requieren tu sesión — `argos login linkedin` / `argos login x`
  (login humano en la ventana), o importar cookies (`argos cookies linkedin --out li.json`).
  Perfil/empresa + publicaciones, y búsquedas (personas/empresas/contenido en LinkedIn;
  destacados/recientes en X).
- Todo entra al mismo pipeline: objetivos en planes (`yt_search`, `li_profile`, `x_search`…),
  planner del LLM, cola de trabajos, informes con CSV/SQLite y la UI.

## Lugares sin costo (OpenStreetMap / Google Maps)

```bash
argos places search "cafeterías" --cerca "Puebla, MX" --radio 3 --limite 20
argos places search "restaurantes" --cerca "CDMX" --proveedor gmaps --limite 10
argos places search "farmacias" --cerca "Puebla, MX" --out ./lugares   # + reporte md/CSV/SQLite
```

- **OpenStreetMap** (default, `--proveedor osm`): sin API key ni pagos. Nominatim
  ubica la zona (eligiendo la ciudad, no el estado) y Overpass lista los POIs por
  categoría dentro del radio — con **Photon como respaldo automático** si Overpass
  está saturado. ~50 categorías en español/inglés (restaurantes, cafeterías,
  farmacias, gimnasios, talleres…) o búsqueda por nombre.
- **Google Maps** (`--proveedor gmaps`): scraping con Playwright (misma maquinaria
  que FB/IG). Agrega rating de Google; puede fallar si Google cambia su DOM.
- **En la UI**: pestaña **Lugares** — formulario, tabla con links/rating/distancia,
  botón "ver en el mapa" y "Guardar como corrida".
- **Como objetivo de investigación**: tipo `places_search` con `value` = búsqueda y
  `kind` = zona; funciona con el planner del LLM, la cola de trabajos y los informes.

## Interfaz web (local)

```bash
argos ui            # abre http://127.0.0.1:8756 en el navegador
argos ui --port 9000 --no-open
```

La interfaz está construida con **React 19 + Vite + Tailwind v4 + [coss-ui](https://coss.com/ui)**
(la librería de componentes de Cal.com — 56 componentes: sidebar, command palette ⌘K,
tablas, diálogos, toasts, meters, empty states…). Secciones:

- **Estado** — cuota diaria con gauges, actividad reciente, sesiones y daemon.
- **Investigación** — brief, plataformas (IG/FB/Lugares), targets y preview del plan.
- **Lugares** — OSM/Google Maps con tabla ordenable y "guardar como corrida".
- **Ejecutar** — corridas puntuales, cola de trabajos, daemon y consola en vivo.
- **Resultados** — informes renderizados + descargas (md/CSV/JSONL/SQLite).
- **Ajustes** — LLM con botón de prueba, cadencia, doctor de sesiones y tema claro/oscuro.

La UI usa exactamente los mismos módulos que el CLI: el brief se guarda en
`<ARGOS_HOME>/brief.yaml`, los trabajos en `<ARGOS_HOME>/jobs/` y las corridas en
`<ARGOS_HOME>/runs/` — todo coherente con el modo daemon y el contenedor.
Con `ARGOS_UI_TOKEN=...` la interfaz queda protegida (header o `?token=`).

**Desarrollo de la UI** (el build se commitea; el contenedor no necesita Node):

```bash
cd ui
npm install
npm run dev      # dev server con proxy a la API local
npm run build    # compila a src/argos/web/static/ (servido por FastAPI)
```

## Agente autónomo (Docker)

Argos puede correr **como agente**: le das una API de LLM, un objetivo y las credenciales,
y cada N horas planifica, recolecta y escribe un informe solo.

```bash
# En tu máquina / VPS con Docker:
cp .env.example .env            # completá ARGOS_LLM_API_KEY (+ base_url/model)
cp brief.example.yaml brief.yaml  # editá `objective` y `questions`
docker compose up -d --build    # levanta el agente en loop
docker compose logs -f          # mirá los ciclos
```

Flujo interno: **brief → LLM planifica targets → Argos recolecta (FB/IG) → LLM analiza → informe**.

Comandos (también sin Docker):

```bash
argos agent plan [--brief X.yaml]     # ver el plan que armaría el LLM (sin recolectar)
argos agent run  [--brief X.yaml]     # una corrida completa
argos agent daemon [--interval-hours 12]  # loop para el contenedor
```

Configuración (variables de entorno, pensadas para el contenedor):

| Variable | Qué es |
|---|---|
| `ARGOS_LLM_API_KEY` | clave del proveedor (requerida) |
| `ARGOS_LLM_BASE_URL` | endpoint compatible OpenAI (default `https://api.openai.com/v1`) |
| `ARGOS_LLM_MODEL` | modelo (default `gpt-4o-mini`) |
| `ARGOS_BRIEF_FILE` / `ARGOS_BRIEF` | objetivo (archivo YAML o texto) |
| `ARGOS_COOKIES_DIR` / `ARGOS_COOKIES_IG` / `ARGOS_COOKIES_FB` | sesiones FB/IG |
| `ARGOS_INTERVAL_HOURS` | cadencia del daemon (default 12) |
| `ARGOS_WEBHOOK_URL` | aviso opcional al terminar (n8n, Slack…) |

Las corridas quedan en `<ARGOS_HOME>/runs/<job>-<fecha>/` con `analysis.md` (informe del LLM),
`data/` (datos crudos + CSV + SQLite) y `run.json`. Guía completa: [`DOCKER.md`](../DOCKER.md).

## Investigación multi-objetivo (report + research)

```bash
argos research examples/research.yaml --out ./research   # corre varios objetivos y arma el informe
argos research --example                                 # imprime un plan de ejemplo
argos report ./research/<job>                            # regenera report.md/CSV/argos.db desde los JSONL
```

Un **plan YAML** lista objetivos (tipos: `ig_profile`, `ig_posts`, `ig_hashtag`, `ig_reels`, `ig_search`,
`ig_comments`, `fb_page`, `fb_search`, `fb_groups_feed`). La corrida agrupa por red (una sola
sesión, más humano y más barato), respeta los límites y al final genera:

- `report.md` — informe legible (resumen, perfiles, posts, comentarios, búsquedas)
- `posts.csv` / `profiles.csv` / `comments.csv` / `search.csv` — para Excel/Sheets
- `argos.db` — SQLite consultable (tablas `posts`, `profiles`, `comments`, `search`)
- `run.json` — qué corrió, acciones por objetivo y cuota restante
- los `*.jsonl` crudos (deduplicados)

## Requisitos

- Python 3.11+
- Google Chrome (recomendado) o el Chromium de Playwright (`python -m playwright install chromium`)

## Instalación

```bash
git clone <tu-fork>/argos && cd argos
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
python -m playwright install chromium   # solo si no tenés Chrome
```

## Uso

```bash
# 1) Iniciar sesión (una vez por plataforma; se abre una ventana, la sesión queda guardada)
argos login instagram
argos login facebook

# 2) Ver el estado de la sesión y del entorno
argos doctor
argos doctor --json
```

`argos doctor` reporta por plataforma:

| estado | significado |
|---|---|
| `ok` | sesión verificada contra la plataforma |
| `needs-login` | falta (o expiró) la sesión → `argos login <plataforma>` |
| `checkpoint` | la plataforma pide verificación humana → resolvela en la ventana |
| `rate-limited` | límite temporal de la plataforma → esperar |
| `off` | navegador/dependencias no instaladas |
| `error` | fallo inesperado (detalle en el mensaje) |

Exit codes: `0` ok · `1` error · `2` uso inválido · `3` requiere humano (login/checkpoint) ·
`4` rate-limited · `5` extracción.

## Investigar en Instagram

```bash
# Perfil: bio, métricas y los posts visibles en la grilla (1 navegación)
argos ig profile nasa --limit 12
argos ig profile nasa --json --out ./research

# Posts: visita cada post para traer likes, comentarios y fecha
argos ig posts nasa --limit 12
argos ig posts nasa --limit 30 --since 2026-09-01 --json --out ./research
argos ig posts nasa --limit 12 --no-details     # solo lo visible en la grilla (1 navegación)

# Hashtags: grilla del tag; con --details, métricas por post
argos ig hashtag astrophotography --limit 12
argos ig hashtag astrophotography --limit 12 --details

# Reels de un perfil (la grilla ya trae vistas; --details agrega likes/comentarios/fecha)
argos ig reels nasa --limit 12

# Búsqueda: posts por keyword (default) o usuarios (typeahead, tipeo humano)
argos ig search "milky way" --limit 12
argos ig search nasa --type users --limit 10
argos ig search "Uriel Arriaga Garcia" --type users --variants --limit 20   # variantes de username

# Comentarios de un post (autor, texto y antigüedad; la fecha es aproximada)
argos ig comments https://www.instagram.com/nasa/p/DdHyaYAifb6/ --limit 20
```

Salidas: `--json` imprime el contrato a stdout; `--out DIR` agrega a `posts.jsonl`
(dedupe por `platform` + `id`), `profiles.jsonl`, `search.jsonl` y `comments.jsonl`.
Cada corrida informa por stderr cuántas acciones de red consumió y cuánta cuota
diaria queda.

## Investigar en Facebook

```bash
# Página: info del header + posts visibles (1 navegación; scrollea acotado si pedís más)
argos fb page NASA --limit 12
argos fb page nasaearth --limit 12 --json --out ./research

# Búsqueda: páginas, grupos o personas
argos fb search nasa --type pages --limit 10
argos fb search "Uriel Arriaga Garcia" --type people --variants --limit 20   # prueba variantes del nombre
argos fb search "machine learning" --type groups --limit 10

# Posts del feed de tus grupos (si sos miembro de alguno)
argos fb groups-feed --limit 12
```

Notas de fidelidad (Facebook no expone todo como Instagram):

- La **URL del post** es la de la página (FB no publica permalinks en este layout); el
  identificador es un hash estable de autor+texto para poder deduplicar.
- La **fecha** es aproximada, derivada de la antigüedad relativa ("hace 3 horas").
- Los contadores (reacciones/comentarios/compartidos) se leen de la tarjeta del post.
- Si un post trae un evento/oferta adjunta, su texto puede colarse al final del caption.

### Movimiento cuidadoso (anti-bloqueo)

La prioridad del proyecto es no ser bloqueado, así que eso es diseño, no configuración:

| Control | Valor por defecto |
|---|---|
| Ritmo | token bucket 12/min (IG) y 8/min (FB) + pausas de 3–9 s entre acciones y 1,5–4 s entre micro-pasos |
| Cuota diaria | 400 acciones por plataforma, persistida en `~/.argos/state/limits.json` |
| Topes por corrida | máx. 36 posts, 6 scrolls de grilla (IG) / 4 (FB) y 4 scrolls de comentarios |
| Parada segura | ante login-wall, checkpoint o 429: se detiene, guarda evidencia en `~/.argos/debug/` y sale con exit 3/4 |
| Lectura | **DOM-first**: se navega y se lee la UI como un humano; la API interna de IG se evita porque en la práctica responde 429/HTML |
| Búsqueda | el typeahead de IG se abre y se escribe con pausas; FB usa las rutas de búsqueda del sitio |
| Re-intentos | nunca automáticos: si hay señal de límite, esperás vos (o subís la cuota con criterio) |

Cada post/reel visitado cuenta como una acción: `--limit 12 --details` = 13 navegaciones,
~1–2 min con el ritmo humano. Para investigaciones grandes, primero `--no-details`
(barato) y después detalle solo de lo elegido.

## Configuración

`~/.argos/config.yaml` (opcional; se crea a mano, permisos 0600):

```yaml
headless: false            # los comandos de contenido usan ventana visible por defecto
locale: es-ES              # opcional; por defecto se respeta el del sistema
timezone_id: America/Argentina/Buenos_Aires   # opcional
proxy: "http://user:pass@host:port"           # opcional (solo si la IP está bloqueada)
limits:
  instagram: { per_minute: 12, daily_actions: 400 }
  facebook:  { per_minute: 8,  daily_actions: 400 }
```

`ARGOS_HOME` permite mover todo el estado (`profiles/`, `state/`, `debug/`, `config.yaml`)
a otra ruta — útil para tests o perfiles separados.

## Estructura

```
src/argos/
  cli.py                 # comandos (typer)
  config.py              # ~/.argos/config.yaml + paths
  private_fs.py          # escrituras 0600 y rechazo de symlinks
  doctor.py              # chequeo de entorno y sesiones
  browser/               # sesión, lanzamiento, ritmo, límites, checkpoints
  platforms/             # instagram, facebook (probes y, en fases 2-4, extracción)
```

## Notas operativas

- Usá cuentas dedicadas para automatización: las plataformas pueden restringir cuentas que
  hacen llamadas no humanas. Argos mitiga con límites conservadores, pero el riesgo existe.
- Argos no evade captchas ni checkpoints y no automatiza logins.
