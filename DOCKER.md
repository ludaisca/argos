# Argos en Docker — agente autónomo de investigación (Facebook + Instagram)

Un contenedor que **investiga solo**: le das una API de LLM, un objetivo y las
credenciales, y cada N horas planifica, recolecta y escribe un informe.

```
brief (objetivo)  →  LLM planifica targets  →  Argos recolecta (FB/IG)
                  →  LLM analiza  →  informe en el volumen /data
```

## Requisitos

- Un VPS con **Docker** y **Docker Compose** (2 GB de RAM alcanzan).
- Salida a internet (para las redes y para el LLM).
- La API de un proveedor LLM compatible con OpenAI.

## Arranque rápido

```bash
# 1) Descomprimí el zip y entrá a la carpeta
unzip argos.zip && cd argos-zip        # (la carpeta con Dockerfile, argos/, cookies/)

# 2) Configurá el LLM
cp .env.example .env
nano .env                              # completá ARGOS_LLM_API_KEY (y base_url/model si no es OpenAI)

# 3) Escribí tu objetivo
cp brief.example.yaml brief.yaml
nano brief.yaml                        # editá `objective` y `questions`

# 4) Credenciales: el zip ya trae cookies/ con tus sesiones de FB e IG.
#    (Si querés renovarlas: en tu máquina `argos cookies instagram --out ig.json`.)

# 5) Levantá el agente
docker compose up -d --build

# 6) Mirá lo que hace
docker compose logs -f
```

Los informes aparecen en el volumen `argos-data` → `/data/runs/<job>-<fecha>/`
con `analysis.md` (informe del LLM), `data/` (datos crudos, CSV, SQLite) y `run.json`.

## Las tres configuraciones

### 1. API del LLM (`.env`)

```env
ARGOS_LLM_API_KEY=sk-...
ARGOS_LLM_BASE_URL=https://api.deepseek.com/v1   # u OpenAI/Groq/OpenRouter/Ollama…
ARGOS_LLM_MODEL=deepseek-chat
```

Cualquier endpoint compatible con `/chat/completions` funciona. Si el proveedor no
soporta `response_format`, Argos reintenta sin él automáticamente.

### 2. Objetivo (`brief.yaml`)

```yaml
job: "Mi investigación"
objective: >
  Qué querés averiguar, en tus palabras.
questions:
  - Preguntas concretas que el informe debe responder.
targets: []        # vacío = el LLM arma el plan (podés fijarlo a mano)
max_targets: 5
```

Previsualizá el plan que armaría el LLM **sin recolectar nada**:
```bash
docker compose run --rm argos agent plan
```

### 3. Credenciales (`cookies/` o `.env`)

- **Recomendado:** el compose monta `./cookies` en `/cookies` y el agente importa
  `instagram-cookies.json` / `facebook-cookies.json` automáticamente.
- Alternativa: pegar el JSON en `ARGOS_COOKIES_IG` / `ARGOS_COOKIES_FB` del `.env`.
- Si una red no tiene cookies, el agente la reportará como `needs-login` y seguirá
  con la otra.

## Comandos útiles

```bash
docker compose logs -f                      # ver los ciclos en vivo
docker compose run --rm argos agent plan    # ver el plan del LLM (sin recolectar)
docker compose run --rm argos agent run     # una corrida única (en vez del loop)
docker compose run --rm argos quota         # cuota restante del día
docker compose run --rm argos doctor        # estado de las sesiones
docker compose exec argos ls /data/runs     # ver las corridas guardadas
docker compose down                          # parar
docker compose up -d --build                 # actualizar tras cambios
```

Para sacar los informes del VPS:

```bash
docker compose cp argos:/data/runs ./runs
# o montá ./data en el compose:  - ./data:/data
```

## Cadencia

`ARGOS_INTERVAL_HOURS` (default 12) controla cada cuánto corre un ciclo.
`restart: unless-stopped` hace que el contenedor se recupere solo.

## Límites y seguridad

- Argos aplica los mismos límites que el CLI (12/min y 400/día por red, pausas de
  3–9 s, topes por corrida) — el agente **no** los saltea.
- Usá **cuentas dedicadas**: la actividad automatizada puede restringir cuentas.
- El contenedor guarda las cookies en `/data` (volumen). Tratá ese volumen como
  credenciales: no lo subas a repos ni lo compartas.
- El agente es **solo lectura**: no publica, comenta ni sigue.

## ¿Coolify?

Si el VPS está gestionado con **Coolify**, hay una variante lista y una guía con el
checklist de la UI: [`COOLIFY.md`](COOLIFY.md) + `docker-compose.coolify.yml`
(sin binds locales: todo por variables de entorno y volumen `/data`).

## Si el tag de la imagen no existe

El `Dockerfile` usa `mcr.microsoft.com/playwright/python:v1.63.0-noble`, que debe
coincidir con la versión de Playwright del paquete. Verificala con
`pip show playwright` y ajustá el tag (por ejemplo `v1.63.0-jammy`).
