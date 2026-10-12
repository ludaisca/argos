# Desplegar Argos en Coolify — revisión por MCP (ambas instancias)

Revisado: **Vasahub** y **Igniscore**. Recomendación: **desplegar en Igniscore**.

## Igniscore ✅ (recomendado)

| Cosa | Estado |
|---|---|
| Coolify | **4.4.6** (más nueva que Vasahub), team Root Team, MCP habilitado |
| Servidores | 1 solo: `localhost` = el propio host del Coolify (`is_coolify_host`), Docker 29.5.3, Traefik 3.6.21, TZ America/Mexico_City |
| Proyecto | **"Marketing"** (env `production`) — 4 recursos en total: muchísima capacidad libre |
| App existente | **WAB** (`ludaisca/WAB`, pública, main) → build pack **dockercompose** (`/docker-compose.yml`), puerto 3000, **sin FQDN**, `running:healthy`, **4 storages persistentes** |
| Fuente Git | "Public GitHub" — el flujo público **ya probado** con WAB |
| Repo Argos | `ludaisca/argos` **no existe aún** (verificado 404) → hay que crearlo |
| Token MCP | **puede deployar** (verificado); sin tools de creación |
| Extra | demo `z168….igniscore.cloud` (exited), 2 services apagados. El wildcard dice `gniscore.cloud` (typo en settings, no afecta a un worker) |

Por qué acá: instancia personal y casi vacía, Coolify más nuevo, y el repo es del mismo
dueño que WAB (`ludaisca`). Vasahub es la granja WhatsApp (30 recursos en SERVER 1, un
N8N unhealthy): mejor no meter el scraper ahí.

## Vasahub (alternativa, no recomendada)

| Cosa | Estado |
|---|---|
| Coolify | 4.4.2 · 6 servidores (SERVER 1–5 + localhost), todos reachable |
| Proyecto | "Agentes Digitales" (SERVER 1): Chatwoot, Metabase, N8N ×2, Searxng + PG + Redis |
| Fuente Git | "Public GitHub" (`is_public`) |
| Token MCP | puede deployar (verificado) |

Si algún día se usa: Application en "Agentes Digitales", SERVER 1 (destino `coolify`,
`os04cscg00cwk4w0sowk4wcs`), sin FQDN, storage `/data`.

## Checklist de despliegue en Igniscore

### 1. Repo público `ludaisca/argos`
El contenido de `argos.zip` ya es un repo válido (Dockerfile en la raíz + `argos/`).
**Ojo: el zip trae `cookies/` con tus sesiones — eso NO va a un repo público.**
El `.gitignore` raíz ya las excluye; verificá igual con `git status`.

```bash
# crear el repo en github.com/new → ludaisca/argos (público)
# descomprimir el zip en una carpeta y:
cd argos
git init -b main
git add .
git status                 # cookies/ y .env NO deben aparecer
git commit -m "Argos: agente de investigación FB/IG"
git remote add origin git@github.com:ludaisca/argos.git
git push -u origin main
```

### 2. Crear la Application (UI, una sola vez)

**New Resource → Application → Public Repository**
- URL: `https://github.com/ludaisca/argos` · Branch: `main`
- Build Pack: **Docker Compose** con `Docker Compose Location: /docker-compose.coolify.yml`
  (mismo molde que WAB) — o **Dockerfile** si preferís lo mínimo
- **Server: `localhost`** · Destination: `coolify` · Project: `Marketing` (o creá
  un proyecto "Argos" desde la UI) · Environment: `production`
- **FQDN: vacío** y **Ports: vacío** (worker, no publica nada)
- **Healthcheck: desactivado** (no hay endpoint HTTP)
- El image base de Playwright pesa ~1.5 GB — mirá el disco del host en la UI la primera vez

### 3. Environment (runtime)

| Variable | Valor |
|---|---|
| `ARGOS_LLM_API_KEY` | tu clave |
| `ARGOS_LLM_BASE_URL` | p. ej. `https://api.deepseek.com/v1` |
| `ARGOS_LLM_MODEL` | p. ej. `deepseek-chat` |
| `ARGOS_BRIEF` | objetivo **en una línea** (o file storage, ver abajo) |
| `ARGOS_COOKIES_IG` | JSON de `argos cookies instagram --out ig.json`, en una línea |
| `ARGOS_COOKIES_FB` | JSON de `argos cookies facebook --out fb.json`, en una línea |
| `ARGOS_INTERVAL_HOURS` | `12` |
| `ARGOS_WEBHOOK_URL` | opcional (tu N8N) |

Alternativas sin pegar JSON gigante: **Storages → File** montando
`/cookies/instagram-cookies.json` (+ facebook) con env `ARGOS_COOKIES_DIR=/cookies`;
y para un brief largo: file storage `/app/brief.yaml` + env `ARGOS_BRIEF_FILE=/app/brief.yaml`.

### 4. Storage persistente
- **Persistent Storage:** volumen en **`/data`** (config, sesiones, corridas, informes).
  El `docker-compose.coolify.yml` ya lo declara (`argos-data`).

### 5. Deploy y seguimiento (por MCP)

```
deploy(uuid) → get_deployment / list_deployments → get_logs → control(restart/stop)
```

Logs esperados al arrancar:

```
agente en marcha — cada 12.0 h · salidas en /data/runs
brief recurrente: /data/brief.yaml (o ARGOS_BRIEF) · cola de trabajos: /data/jobs
ciclo 1
…
```

Resultados: `/data/runs/<job>-<fecha>/` → `analysis.md` + `data/` (crudos, CSV, SQLite).

### 6. Cambiar el objetivo o lanzar varias investigaciones (sin redeploy)

El daemon **re-lee el brief en cada ciclo** desde el volumen. En el **Terminal** del
recurso en Coolify:

```bash
# Objetivo recurrente (se usa en cada ciclo):
cat > /data/brief.yaml <<'EOF'
job: "Mi investigación"
objective: >
  Qué querés averiguar, en tus palabras.
questions:
  - Pregunta concreta 1
targets: []          # vacío = el LLM arma el plan
max_targets: 5
EOF

# O una investigación puntual (se corre una vez y se archiva en /data/jobs/done):
cat > /data/jobs/tema-x.yaml <<'EOF'
job: "Tema X"
objective: "Investigar X en IG y FB."
EOF
```

- La cola se revisa cada `ARGOS_JOBS_POLL_SECONDS` (300 s por defecto).
- El brief por env (`ARGOS_BRIEF`) queda como **fallback**: si existe
  `/data/brief.yaml`, ese manda.
- Alternativa on-demand: **Scheduled Tasks** de Coolify → comando
  `argos agent run --brief /data/jobs/tema.yaml` (botón *Execute now* o cron propio).

> Nota: la interfaz web (`argos ui`) hoy se usa **en local**. Para exponerla en este
> Coolify más adelante: el mismo repo, comando `ui --host 0.0.0.0`, FQDN propio y
> `ARGOS_UI_TOKEN` obligatorio.

## Capacidades del MCP (iguales en ambas instancias)

- **Puede:** inspeccionar todo (servidores, proyectos, apps, storages, env keys sin
  valores), deployar, cancelar deploy, restart/stop/start, logs, historial.
- **No puede:** crear ni editar recursos → la creación es por UI (o API directa con token
  write); después todo se opera por MCP.
