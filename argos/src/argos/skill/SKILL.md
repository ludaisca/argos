---
name: argos
description: >
  LECTURA (solo lectura) de Instagram y Facebook usando la sesión propia del
  operador. Usar cuando el usuario pida investigar, buscar o leer perfiles,
  posts, reels, hashtags, comentarios o cuentas/páginas en Instagram o Facebook.
  NO usar para publicar, comentar, reaccionar, seguir ni ninguna acción de
  escritura.
---

# Argos — lectura de Instagram y Facebook

CLI que navega IG/FB como un humano (lee el DOM, no las APIs internas) con la
sesión ya iniciada y devuelve JSON estable. Solo lectura de contenido visible.

## Reglas de seguridad (obligatorias)

1. **Solo lectura.** Nunca publicar, comentar, reaccionar, seguir ni mandar mensajes.
2. **Chequeá la cuota antes de correr:** `argos quota --json`. Si `remaining` < 10,
   avisá al usuario y no sigas. Cuota: 400 acciones/día por red.
3. **No paralelices** comandos sobre la misma red; de a uno.
4. **Usá `--headless`** para corridas automáticas (sin ventana).
5. **Ante exit 3 (login/checkpoint) o 4 (rate-limit): PARÁ.** No reintentes ni
   hagas loops; informá al usuario del motivo.
6. **No fuerces límites con bucles:** el tool ya frena solo; un error de límite es
   una señal de esperar, no de insistir.
7. El tool solo lee lo que la sesión puede ver; si un perfil es privado, lo dice.

## Salud y cuota

```bash
argos doctor --json     # estado de las sesiones por plataforma
argos quota --json      # acciones usadas/restantes hoy
```

## Comandos — Instagram

```bash
argos ig profile <usuario> [--limit N] [--json] [--out DIR]
argos ig posts <usuario> [--limit N] [--since ISO] [--details/--no-details] [--json]
argos ig hashtag <tag> [--limit N] [--details] [--json]
argos ig reels <usuario> [--limit N] [--details] [--json]
argos ig search <texto> [--type posts|users] [--limit N] [--variants] [--json]
argos ig comments <url-o-shortcode> [--limit N] [--json]
```

## Comandos — Facebook

```bash
argos fb page <slug-o-url> [--limit N] [--json] [--out DIR]
argos fb search <texto> --type pages|groups|people [--limit N] [--variants] [--json]
argos fb groups-feed [--limit N] [--json]
```

## Informes e investigación multi-objetivo

```bash
argos research <plan.yaml> [--out DIR] [--json]   # corre varios objetivos y arma el informe
argos research --example                          # plan de ejemplo (YAML)
argos report <dir> [--json]                       # (re)genera report.md / CSV / argos.db
```

El plan lista objetivos (`ig_profile`, `ig_posts`, `ig_hashtag`, `ig_reels`, `ig_search`,
`ig_comments`, `fb_page`, `fb_search`, `fb_groups_feed`). La corrida genera `report.md`,
CSVs, `argos.db` (SQLite consultable) y `run.json` en la carpeta del job.

## Agente autónomo

```bash
argos agent plan  [--brief X.yaml] [--json]     # plan del LLM, sin recolectar
argos agent run   [--brief X.yaml] [--json]     # una corrida completa
argos agent daemon [--interval-hours 12]        # loop (contenedor Docker)
```

El brief es YAML (`objective`, `questions`, `targets?`, `max_targets`). El LLM se
configura por entorno: `ARGOS_LLM_API_KEY` / `ARGOS_LLM_BASE_URL` / `ARGOS_LLM_MODEL`.
Las cookies se pueden dar por `ARGOS_COOKIES_DIR` (carpeta con `*-cookies.json`) o
`ARGOS_COOKIES_IG` / `ARGOS_COOKIES_FB`.

## Contrato de salida

- **stdout** = solo el JSON cuando usás `--json` (parseá stdout).
- **stderr** = progreso/info humana; ignoralo para parsear.
- **exit codes**: `0` ok · `1` error interno · `2` uso inválido · `3` requiere
  humano (login/checkpoint) · `4` rate-limited · `5` sin resultados/extracción.

## Sesión

- `argos login instagram|facebook` abre el navegador; el usuario inicia sesión una
  vez y queda guardada en `~/.argos/profiles/<red>/`.
- Si `argos doctor` dice `needs-login`, pedile al usuario que corra
  `argos login <red>` (es manual; vos no podés iniciar sesión).
- **Servidor sin navegador (VPS):** migrá la sesión con cookies:
  `argos cookies <red> --out X.json` en la máquina con sesión, y en el VPS
  `cat X.json | argos configure <ig-cookies|fb-cookies> --stdin`.

## Notas

- `--out DIR` agrega JSONL deduplicado (`posts.jsonl`, `profiles.jsonl`,
  `search.jsonl`, `comments.jsonl`).
- `--variants` (búsqueda de personas) prueba variantes del nombre y junta
  resultados deduplicados por URL.
- Fechas: Instagram exactas; Facebook aproximadas (derivadas de "hace X").
- Cada navegación/scroll/consulta consume 1 acción de la cuota diaria.
