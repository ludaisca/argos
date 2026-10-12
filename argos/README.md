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
