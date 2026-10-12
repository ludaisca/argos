# Argos — Plan de implementación

> CLI + librería en Python para **navegar e investigar Facebook e Instagram con Playwright**, diseñada para uso propio y para ser operada por agentes (OpenCode, Claude Code, etc.).
>
> Estado: Fases 0 y 1 implementadas (bootstrap + núcleo de navegador) · Versión: v0.1.0 · Fecha: 2026-09-30

---

## Estado de avance

| Fase | Estado | Notas |
|---|---|---|
| 0. Bootstrap | ✅ hecha | `pyproject` (hatchling, versión única en `__init__.py`), ruff/mypy strict, pytest, CI Ubuntu+Windows, layout `src/` |
| 1. Núcleo navegador | ✅ hecha y verificada | `browser/` (session, launch, pacing, limiter, checkpoints), `platforms/` (instagram, facebook con probes reales), `doctor`, `argos login` / `argos doctor`, escrituras privadas 0600 + anti-symlink, tests unitarios + e2e real |
| 2. Instagram lectura | ✅ hecha y verificada en vivo | `ig profile` + `ig posts` (DOM-first, límites y pacing wireados a cada acción), modelos pydantic, JSONL con dedupe, fixtures reales, tests con navegador |
| 3. Instagram resto | ✅ hecha y verificada en vivo | `ig hashtag`, `ig reels` (vistas en grilla), `ig search` (posts y usuarios vía typeahead con tipeo humano), `ig comments` (autor/texto/antigüedad, sufijo "· Edited" soportado) |
| 4. Facebook | ✅ hecha y verificada en vivo | `fb page` (header + posts con reacciones/comentarios/compartidos), `fb search` (pages/groups/people), `fb groups-feed`; tarjetas detectadas por antigüedad "hace X" (los comentarios usan otro formato), números en formato es/en (`28 mill.`), fixtures reales |
| 5. Store y research | ✅ hecha y verificada en vivo | `argos report` (Markdown + CSV + SQLite desde los JSONL) y `argos research` (plan YAML multi-objetivo → job con informe); verificado con una corrida real IG+FB |
| 6. Hardening + agentes | ✅ hecha | `SKILL.md` (instalable con `argos skill --install`), server MCP (`argos mcp`, 11 tools, verificado con handshake stdio), `argos quota`, doc del contrato en README |
| 7. Opcional | pendiente | `argos watch` (monitoreo con diff) |
| 8. Agente autónomo + Docker | ✅ hecha y verificada | `argos agent plan/run/daemon`: brief → plan (LLM) → recolección → análisis (LLM) → informe; LLM provider-agnostic (env); Dockerfile + compose + `.env.example` + `DOCKER.md`; validado end-to-end con un LLM local simulado |
| 9. Interfaz web local | ✅ hecha y verificada | `argos ui` (FastAPI + SPA): brief con selección de plataformas IG/FB, ajustes del LLM con prueba real, preview del plan, corridas en vivo con consola, cola de trabajos, daemon con start/stop, resultados con informes renderizados y descargas, doctor de sesiones; playtest local con Gemini 3.8 Flash y datos reales |
| 10. Lugares sin costo | ✅ hecha y verificada | `argos places search` + pestaña Lugares + target `places_search`: OSM (Nominatim+Overpass, respaldo Photon, ~50 categorías es/en, sin API key) y Google Maps por scraping (rating real); dataset `places` con CSV/SQLite/informe; probado en vivo con Puebla (cafés, farmacias, ratings) |
| 11. UI profesional (coss-ui) | ✅ hecha y verificada | React 19 + Vite + Tailwind v4 + coss-ui (56 componentes, la librería detrás de devl.dev): app shell con sidebar, command palette ⌘K, dashboard con gauges de cuota, tablas ordenables, diálogos, toasts, tema claro/oscuro; el build compila a estáticos servidos por FastAPI; smoke test headless: 6 secciones + paleta, 0 errores de consola |
| 12. Más plataformas: YouTube, LinkedIn, X | ✅ hecha (YouTube verificado en vivo; LI/X requieren login humano) | Targets `yt_search`/`yt_channel`/`yt_video` (JSON de ytInitialData, público sin login), `li_profile`/`li_search` y `x_profile`/`x_search` (DOM con la sesión del humano); probes de doctor, límites propios, cookies importables (li-cookies/x-cookies), CLI `argos fetch`, UI y planner automáticos; probado en vivo: búsqueda y canal de YouTube reales |

### Verificación de Fase 2 (2026-09-30)

Bonus: la fase 1 quedó verificada contra el mundo real (login humano con challenge de IG
y 2FA de FB, persistencia de sesión entre reinicios, doctor con probes reales).

Nota de arquitectura: la API interna de Instagram devolvió 429/HTML en pruebas en vivo, así
que la lectura quedó **DOM-first** (navegar y leer la UI) — más lento pero mucho menos
agresivo. Todos los requests pasan por el `RateLimiter` (12/min, 400/día) y el `Pacer`
(3–9 s), con topes por corrida (36 posts / 6 scrolls) y parada inmediata ante cualquier
señal de bloqueo.

### Verificación de Fase 3 (2026-09-30)

| Check | Resultado |
|---|---|
| `ruff` + `mypy` strict | ✅ limpios (22 archivos) |
| `pytest` | ✅ **112 passed**, 5 skipped (solo permisos POSIX/symlink del entorno Windows) |
| `ig hashtag astrophotography` (vivo) | ✅ 3 posts, exit 0 |
| `ig reels nasa` (vivo) | ✅ 2 reels con vistas (4.7M / 7.2M) |
| `ig search nasa --type users` (vivo) | ✅ `@nasa · NASA · 104M seguidores` + 3 más |
| `ig comments <post>` (vivo) | ✅ autores, textos y antigüedad; bug de "· Edited" detectado en vivo y corregido |
| Cuota | ✅ contador diario funcionando (`~/.argos/state/limits.json`) |

### Verificación de Fase 4 (2026-09-30)

| Check | Resultado |
|---|---|
| `ruff` + `mypy` strict | ✅ limpios (25 archivos) |
| `pytest` | ✅ **137 passed**, 5 skipped (solo permisos POSIX/symlink) |
| `fb page NASA` (vivo) | ✅ 2 posts con reacciones/comentarios y fecha aproximada; 2 acciones |
| `fb search nasa --type pages` (vivo) | ✅ 4 páginas con seguidores (28M / 279K / 11M / 133K) |
| `fb groups-feed` (vivo) | ✅ sin grupos activos → nota clara, exit 0 |
| Decisión de arquitectura | `mbasic` está retirado (redirige a www) y la API interna no se usa: todo es DOM del sitio con JS |

Notas de fidelidad de FB documentadas en el README: URL de post = URL de página, fecha
aproximada desde la antigüedad relativa, id = hash de autor+texto, CTAs adjuntas pueden
aparecer en el caption.




---

## 0. Resumen ejecutivo

- **Qué es:** herramienta autónoma ("motor propio"), no un instalador de CLIs ajenos como Agent-Reach. Todo el control del navegador y la extracción viven en este repo.
- **Alcance v1:** Facebook (perfil/página, posts, búsqueda, grupos) + Instagram (perfil, posts, reels, hashtags, búsqueda, comentarios).
- **Fuera de alcance v1:** operaciones de escritura (postear, comentar, reaccionar), mensajes directos, otras plataformas, intake de credenciales, bypass de captcha/checkpoints.
- **Stack:** Python 3.11+, Playwright (Chromium + `channel="chrome"` recomendado), typer + rich, pydantic v2, SQLite (stdlib) + JSONL, ruff + mypy strict, pytest + pytest-playwright, uv como gestor.
- **Idea central de robustez:** extracción **network-first** (leer las respuestas que la propia web app ya carga, no scrapers de DOM frágiles) con **fallback DOM**, cadenas de selectores con auto-chequeo, y parada segura ante login-walls/checkpoints.

---

## 1. Principios de diseño

### Lo que copiamos de Agent-Reach (las buenas ideas)

- `doctor` que hace **probes reales** (ejecuta algo y verifica), no `shutil.which()`.
- Multi-backend con backend activo reportado (`active_backend`).
- Escrituras atómicas `0600`/`0700` con rechazo de symlinks en todo path de credenciales/config.
- Scrubber de credenciales aplicado en logs y mensajes de error.
- Login 100% humano: la herramienta nunca pide, captura ni guarda contraseñas.
- "Requiere humano" como estado de primera clase: screenshot + evidencia + exit code propio.
- Documento `SKILL.md` para agentes.

### Lo que evitamos (lecciones de su revisión)

- Instalar herramientas de terceros desde ramas móviles o commits ajenos → **cero dependencias de CLIs externos**.
- Selectores únicos sin fallback → cadenas de selectores + extractor genérico + fixtures de regresión.
- `cli.py` monolítico de 2400 líneas → estructura por capas y subcomandos tipados.
- Marketing/nags dentro del output del CLI o de los skills.
- Docs que hardcodean el entorno del autor (ej. `conda run -n dl`).

### Regla operativa

La herramienta solo lee contenido **visible con la sesión propia del operador**. No evade captchas, no rota fingerprints por request, no automatiza logins. Cuando aparece un checkpoint, para y avisa.

---

## 2. Arquitectura

```
argos/
├── pyproject.toml
├── README.md
├── PLAN.md
├── src/argos/
│   ├── __init__.py
│   ├── cli.py                     # typer: subcomandos fb/ig/doctor/login/report/cache
│   ├── config.py                  # ~/.argos/config.yaml (0600), ARGOS_HOME
│   ├── models.py                  # pydantic: Profile, Post, Comment, SearchHit, ...
│   ├── store.py                   # JSONL append-only + SQLite (dedupe incremental)
│   ├── report.py                  # Markdown/CSV desde JSONL
│   ├── doctor.py                  # estado por plataforma: ok | needs-login | checkpoint | ...
│   ├── browser/
│   │   ├── session.py             # persistent context por plataforma, login humano
│   │   ├── launch.py              # args de launch, channel=chrome, opciones proxy
│   │   ├── pacing.py              # dwell humano: delays, scroll incremental
│   │   ├── limiter.py             # token bucket + cuota diaria + backoff
│   │   ├── intercept.py           # captura de responses (graphql / api/v1)
│   │   └── checkpoints.py         # detección login-wall / challenge / 429
│   └── platforms/
│       ├── base.py                # interfaz Platform: name, probe(), flows
│       ├── facebook/
│       │   ├── selectors.py
│       │   ├── walker.py          # extraction genérica de GraphQL JSON
│       │   ├── extract.py         # graphql → modelo, fallback DOM, fallback mbasic
│       │   └── flows.py           # profile, posts, search, groups
│       └── instagram/
│           ├── selectors.py
│           ├── endpoints.py       # registry de endpoints /api/v1/*
│           ├── extract.py         # payloads → modelo, fallback DOM
│           └── flows.py           # profile, posts, reels, hashtag, search, comments
└── tests/
    ├── fixtures/                  # payloads IG/FB anonimizados + HTML snapshots
    ├── unit/                      # parsers, walker, limiter, checkpoints, config
    ├── e2e/                       # Playwright + servidor local + page.route
    └── live/                      # opt-in (-m live), contra sesión real
```

### Flujo típico de un comando

```
CLI ──> Platform (fb|ig)
          │
          ▼
   BrowserSession (persistent context)
          │
          ├─ limiter/pacing        ← espera humana, jitter, cuotas
          ├─ interceptores         ← respuestas GraphQL / api/v1 de la propia web
          ├─ checkpoints           ← si hay login-wall/429 → evidencia + abort (exit 3/4)
          ▼
   extract (network-first → DOM fallback)
          ▼
   models (pydantic) → store (JSONL/SQLite) → report (MD/CSV) / stdout --json
```

---

## 3. Decisiones técnicas clave

| Tema | Decisión | Alternativa y por qué no |
|---|---|---|
| Control del navegador | `launch_persistent_context(user_data_dir=~/.argos/profiles/<plat>)` | `connect_over_cdp` al Chrome del usuario: invasivo y acopla a un Chrome abierto; queda como modo opcional `--attach-cdp` en fase 6 |
| Binario | Chromium de Playwright por defecto; `channel="chrome"` recomendado (menos huella) | Chromium bundled tiene fingerprint más "automatizado" |
| Extracción Instagram | **Network-first**: `page.evaluate(fetch(...))` dentro del contexto autenticado, header `x-ig-app-id`, csrf desde cookies | Scraping DOM puro: lento, frágil, no pagina bien |
| Extracción Facebook | Interceptar respuestas `/api/graphql/` mientras la web navega/scroll EA; walker genérico por claves conocidas | Usar GraphQL directo con `doc_id`: se invalidan a las semanas |
| Fallback Facebook | DOM (`div[role=article]`) y opcional `mbasic.facebook.com` (solo lectura) | mbasic está limitado/geo-bloqueado; nunca como backend principal |
| Modelos | pydantic v2 con `extra="ignore"` y fechas UTC | dicts sueltos: imposibles de testear con fixtures |
| Persistencia | JSONL append-only (fase 2–4) + SQLite stdlib (fase 5) con `UNIQUE(platform,id)` | Solo JSON: sin dedupe incremental ("solo lo nuevo") |
| CLI | typer + rich, `--json` en todos los comandos | argparse con subcomandos anidados termina en un archivo gigante |
| Rate limiting | Token bucket + dwell aleatorio + cuota diaria persistida + backoff exponencial | Sin límites → checkpoint/ban rápido |
| Config | `~/.argos/config.yaml` en 0600; `ARGOS_HOME` override; sin secretos salvo proxy opcional | Configs dispersas y en claro |

### Detalle: sesión persistente + login humano

```python
# browser/session.py (esquema)
from playwright.sync_api import sync_playwright

def open_session(platform: str, *, headless: bool):
    profile = Path(os.environ.get("ARGOS_HOME", Path.home() / ".argos")) / "profiles" / platform
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(profile),
        headless=headless,
        channel="chrome",                     # fallback a bundled si no está
        viewport={"width": 1440, "height": 900},
        locale="es-ES", timezone_id=os.environ.get("TZ"),
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return pw, ctx, page
```

- `argos login ig|fb` abre headed, imprime "iniciá sesión en la ventana, después presioná Enter", espera input humano y valida éxito por cookies de sesión + ausencia de formulario de login.
- Todo comando posterior reusa el perfil. `--headless` es opt-in (default: headed, que es más seguro contra detección).

---

## 4. Sesión, estados y doctor

Estados por plataforma (contrato de `--json`):

```json
{ "platform": "instagram", "status": "ok",
  "detail": "sesión válida (ds_user_id=...)", "active_backend": "internal-api",
  "hint": null }
```

- `ok` · `needs-login` · `checkpoint` · `rate-limited` · `off` · `error`
- Probe real de IG: `fetch('/api/v1/accounts/current_user/?edit=true')` desde la página → 200 con `user` = ok.
- Probe real de FB: abrir `https://www.facebook.com/me`, verificar cookie `c_user` y ausencia de formulario de login; detectar `checkpoint`.
- Ante `checkpoint`/login-wall: guardar screenshot + HTML + URL en `~/.argos/debug/<timestamp>/`, imprimir la ruta y salir con código 3.

---

## 5. Facebook — diseño de extracción

**Superficies soportadas**

| Flujo | URL base | Extracción |
|---|---|---|
| Perfil/página | `/username`, `/username/about` | GraphQL intercept + DOM |
| Posts de página/perfil | `/username/posts`, scroll | GraphQL intercept + DOM, paginación por scroll con tope |
| Búsqueda | `/search/top/?q=`, `/search/pages/?q=`, `/search/groups/?q=` | DOM-first (los resultados ya son HTML) + links |
| Grupos | `/groups/{id-slug}` (requiere ser miembro) | GraphQL intercept + DOM |

**Walker genérico de GraphQL** (el corazón de la robustez FB): dado cualquier response JSON de `/api/graphql/`, recorrer recursivamente buscando nodos con `post_id`/`story_id` y mapear por claves tolerantes a faltantes:

```
message.text | story.message.text        → texto
creation_time (epoch)                    → fecha UTC
actors[0].name | actors[0].url           → autor
wwwURL | permalink_url                   → url
feedback.reaction_count.count            → reacciones
feedback.comment_count.total_count       → comentarios
feedback.share_count.count               → shares
attachments[].*                          → media (urls)
```

Regla: **un campo ausente nunca rompe**; el post se emite con lo que haya y un `warnings[]` opcional.

**Fallback DOM**: `div[role=article]` → texto, `abbr`/`aria-label` para fecha, links `/posts/|/videos/|/photos/`, `aria-label` de reacciones ("1,2 mil personas reaccionaron"). Cadenas de selectores en `selectors.py` (primero el más semántico, después el histórico).

**Fallback mbasic** (opcional, fase 4): `https://mbasic.facebook.com/...` HTML liviano parseado con selectolax; útil para lecturas simples de páginas públicas, no para grupos/comentarios.

---

## 6. Instagram — diseño de extracción

**Endpoints conocidos hoy** (verificar y fijar durante la fase 2; la web app cambia):

| Dato | Endpoint |
|---|---|
| Perfil + primeros ~12 posts | `GET /api/v1/users/web_profile_info/?username=U` |
| Posts con paginación | `GET /api/v1/feed/user/{user_id}/?count=12&max_id=...` |
| Reels | `POST /api/v1/clips/user/` (form: `target_user_id`) |
| Hashtag info | `GET /api/v1/tags/web_info/?tag_name=T` |
| Hashtag feed | `GET /api/v1/tags/{t}/sections/` |
| Búsqueda top | `GET /api/v1/fbsearch/web/top_serp/?query=Q` |
| Comentarios | `GET /api/v1/media/{id}/comments/?can_support_threading=true` |

**Ejecución de requests**: siempre desde la página (`page.evaluate`) para que el navegador aporte cookies, csrf y headers; nunca desde Python.

```python
# platforms/instagram/endpoints.py (esquema)
IG_APP_ID = "936619743392459"

def api_get(page, path: str) -> dict:
    return page.evaluate(
        """async ([path, appId]) => {
             const r = await fetch(path, { headers: { 'x-ig-app-id': appId } });
             if (r.status === 429) throw new Error('RATE_LIMITED');
             if (!r.ok) throw new Error('HTTP_' + r.status);
             return await r.json();
           }""",
        [path, IG_APP_ID],
    )
```

- Paginación: `next_max_id`/`max_id` con corte por `--limit` y dedupe por `id` de media.
- Los errores `429`/`checkpoint_required` en el payload → mapear a estados del doctor, no reintentar en caliente.
- **Fallback DOM**: `article`, `a[href*="/p/"]`, `img[alt]` (caption), time (`datetime`).

---

## 7. Límites, pacing y anti-detección

Requisitos (no opcionales):

- **Dwell** entre acciones: 3–9 s aleatorio; scroll incremental con pausas 1.5–4 s.
- **Token bucket** por plataforma (defaults conservadores, configurables): IG 12 req/min · FB 8 navegaciones/min.
- **Cuota diaria** persistida: 400 acciones/plataforma por día.
- **Backoff** en 429/"Try Again Later": 30 s → 2 min → 10 min → stop con exit 4. Nunca retry inmediato.
- **Detección de checkpoint**: patrones de URL (`/checkpoint`, `/challenge`, `/accounts/login`) + marcadores DOM ("Confirm it's you", "suspended", "Try Again Later"). Al detectar: abortar y guardar evidencia.
- **Launch hardening**: `--disable-blink-features=AutomationControlled`, viewport y locale realistas, perfil persistente "cálido", opcional parche de `navigator.webdriver`.
- **Prohibido por diseño**: intake de credenciales, extracción de cookies del navegador personal, bypass de captcha, rotación agresiva de fingerprints.
- **Proxy** opcional por plataforma (si FB/IG bloquean la IP del host).

---

## 8. Datos y salidas

**Modelos** (pydantic): `Profile`, `Post`, `Comment`, `SearchHit`, `GroupInfo`, `JobRun`. Todos con `platform`, `url`, `fetched_at`, `raw_ref` (referencia al payload crudo guardado opcionalmente).

**Salidas**

- `--json` a stdout: contrato estable para agentes.
- `--out DIR/`: `results.jsonl` (append-only), `report.md`, `report.csv`.
- SQLite `~/.argos/cache.db`: `profiles`, `posts`, `comments`, `runs` con `UNIQUE(platform, id)` → dedupe e incremental con `--since`.

**Exit codes**: `0` ok · `1` error interno · `2` input inválido · `3` requiere humano (login/checkpoint) · `4` rate-limited · `5` fallo de extracción/parseo.

---

## 9. CLI (v1)

```
argos doctor [--json]
argos login <fb|ig> [--proxy URL]

argos fb profile <user-or-url> [--json]
argos fb posts   <user-or-url> --limit N [--since DATE] [--out DIR]
argos fb search  <query> --type pages|groups|people|posts --limit N
argos fb group   <id-or-url> posts --limit N

argos ig profile <username> [--json]
argos ig posts   <username> --limit N [--since DATE] [--out DIR]
argos ig reels   <username> --limit N
argos ig hashtag <tag> --limit N
argos ig search  <query> [--type users|tags|places]
argos ig comments <post-url> --limit N

argos report <jobdir> [--format md|csv]
argos cache stats|prune
argos debug capture <url>      # guarda HAR + HTML + responses para fixtures
```

Convenciones: `--json` nunca imprime texto decorativo; los humanos usan la vista rich por defecto. Nada de contenido sensible en argumentos de proceso.

---

## 10. Fases de implementación

| Fase | Entregable | DoD (definition of done) | Esfuerzo |
|---|---|---|---|
| **0. Bootstrap** | Repo, `pyproject` (uv, hatchling), ruff/mypy/pytest, CI Ubuntu+Windows, esqueleto | `uv run pytest` verde; `argos --version` funciona | 0.5 d |
| **1. Núcleo navegador** | `session.py`, `launch.py`, `pacing.py`, `limiter.py`, `checkpoints.py`, `doctor.py`, `argos login`, `argos doctor` | Login IG+FB persiste entre corridas; doctor distingue `ok/needs-login/checkpoint`; evidencia ante checkpoint; unit tests de limiter/checkpoints | 1–2 d |
| **2. Instagram lectura** | `ig profile`, `ig posts` (network-first + DOM fallback), fixtures | Contra sesión real: perfil + últimos N posts con id/url/caption/likes/comments/fecha; `--limit` y paginación correctos; e2e stubeado con `page.route` | 2 d |
| **3. Instagram resto** | `ig hashtag`, `ig reels`, `ig search`, `ig comments` | Resultados tipados, dedupe, fallback DOM ante endpoint caído, tests por fixture | 1–2 d |
| **4. Facebook** | intercept GraphQL + walker + DOM fallback → `fb profile`, `fb posts`; luego `fb search`, `fb group posts` (+ mbasic opcional) | Posts de una página y de un grupo propio con texto/fecha/autor/métricas; degrada a DOM con warning si GraphQL cambia; no cuelga | 2–3 d |
| **5. Store y research** | SQLite + JSONL + `--since`; `argos report`; `argos research --targets file.yaml --platforms fb,ig` | Corrida end-to-end multi-target → JSONL + report.md; re-corrida incremental solo trae nuevos | 1–2 d |
| **6. Hardening + agentes** | Self-test de extractores contra fixtures, `SKILL.md`, logs estructurados, opcional MCP y `--attach-cdp` | Suite completa verde en CI; `doctor --json` estable; skill sin hardcodeos | 1–2 d |
| **7. (Opcional) Monitoreo** | `argos watch` para cron con diff de posts nuevos (stdout/webhook) | Diff correcto entre corridas; silencioso si no hay novedades | 1 d |

**Total estimado v1: ~8–12 días de trabajo efectivo.**

---

## 11. Testing y CI

- **Unit**: parsers (fixtures JSON reales anonimizados), walker genérico FB, limiter, detector de checkpoints, config (permisos 0600, rechazo de symlinks), modelos.
- **E2E sin red real**: servidor local + `page.route` que sirve HTML/JSON grabados → valida pipeline completo navegación → intercept → extract → modelo.
- **Live (opt-in)**: `-m live`, contra sesión real, límites duros; nunca en CI; usado en checklist de release.
- **Fixtures**: `argos debug capture <url>` graba HAR + HTML + responses para renovar parsers cuando las plataformas cambien.
- **CI**: Ubuntu + Windows; `playwright install --with-deps chromium`; ruff + mypy strict; los tests live no corren en CI.

---

## 12. Riesgos y mitigaciones

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| Cambios de endpoints/selectores IG/FB | Alta | Medio | network-first + walker genérico + DOM fallback + fixtures + self-test; payloads crudos guardados para re-parsear sin re-navegar |
| Ban/checkpoint de la cuenta | Media | Alto | cuentas dedicadas, cuotas conservadoras, backoff, parada ante checkpoint, proxy residencial opcional |
| Login bloqueado/captcha | Media | Medio | login 100% humano, sin automatización de credenciales, sin bypass |
| GraphQL FB ofuscado (`doc_id`) | Alta | Bajo | no depender de doc_ids; interceptar lo que el propio cliente web pide |
| Headless detectado | Media | Medio | headed por defecto en login; `channel=chrome`; perfil cálido reusado; headless=new opt-in |
| Deriva de schema | Alta | Bajo | pydantic `extra="ignore"` + walker tolerante; un campo faltante nunca rompe |

---

## 13. Decisiones abiertas (con default propuesto)

1. **Nombre**: *Argos* (provisorio) — se puede renombrar antes de la fase 0.
2. **CLI**: typer (propuesto) vs argparse puro.
3. **mbasic como backend FB**: sí, opcional en fase 4.
4. **MCP server**: sí, opcional en fase 6 (`argos mcp`).
5. **SQLite**: recién en fase 5; JSONL cubre fases 2–4.

---

## 14. Nota operativa

- Uso previsto: investigación de contenido accesible con la sesión propia del operador. Cuentas dedicadas para automatización (el propio FB/IG lo recomienda de facto por el riesgo de restricciones).
- La herramienta no intenta evadir captchas ni checkpoints: cuando aparecen, para y avisa con evidencia.
