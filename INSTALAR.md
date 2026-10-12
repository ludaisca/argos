# Instalar Argos

CLI para **navegar e investigar Instagram y Facebook** (solo lectura) con Playwright, usando la
sesión propia del operador. Diseñado para no hacerte bloquear la cuenta: límites por minuto/día,
ritmo humano y parada ante checkpoints.

## Requisitos

- Python 3.11+
- Google Chrome (recomendado) o el Chromium de Playwright (`python -m playwright install chromium`)

## Instalación automática (recomendada — para un agente o un VPS)

El zip trae un instalador de un solo comando, más un instructivo para agentes:

- **Linux/macOS (VPS):** `bash instalar.sh`
- **Windows:** `powershell -ExecutionPolicy Bypass -File instalar.ps1`
- **Para agentes:** leé `AGENTS.md` (dice exactamente qué hacer y qué NO: no sudo sin
  permiso, no automatizar el login, no tocar nada fuera de la carpeta y `~/.argos/`).

El instalador crea el venv en `~/.argos/venv`, instala el paquete y el Chromium de
Playwright, y termina imprimiendo `== Instalación completa ==` + la versión. Es
idempotente: podés re-correro sin problema.

> ⚠️ **VPS sin navegador (headless):** `argos login` abre una ventana, así que en un
> servidor sin escritorio el login se resuelve importando cookies (ver abajo) o levantando
> un escritorio virtual (Xvfb + noVNC). La instalación en sí no lo necesita; solo el login.

### Importar cookies (para un VPS)

> ⚠️ **Este zip incluye cookies de sesión reales en `cookies/`** (equivalen a tu
> contraseña). No lo compartas ni lo subas a repos públicos.

El instalador (`instalar.sh` / `instalar.ps1`) **ya importa las cookies incluidas
automáticamente** si encuentra la carpeta `cookies/`. Así, en un VPS sin navegador
no hace falta login: instalás y la sesión queda lista.

Si querés migrar cookies de otra sesión (o refrescar las que vienen), de forma manual:

1. **En tu máquina con sesión:**
   ```powershell
   argos cookies instagram --out ig.json
   argos cookies facebook  --out fb.json
   ```
2. Copiá `ig.json` y `fb.json` al VPS.
3. **En el VPS:**
   ```powershell
   cat ig.json | argos configure ig-cookies --stdin
   cat fb.json | argos configure fb-cookies --stdin
   ```
4. `argos doctor` debería pasar a `ok` (las cookies se inyectan solo si el perfil no
   tiene sesión, así que no pisan nada).

Estas cookies equivalen a tu contraseña: guardalas en un lugar seguro.

---

## Pasos (instalación manual)

### 1. Descomprimir

Extraer `argos.zip`: deja una carpeta `argos/` (el código) y este `INSTALAR.md`.

### 2. Instalar

```powershell
cd argos
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows / PowerShell
# macOS/Linux: source .venv/bin/activate

pip install -e .                  # para usar Argos
# o con herramientas de desarrollo/tests:
#   pip install -e ".[dev]"
```

Para el servidor MCP (integración con n8n/agentes): `pip install -e ".[mcp]"`.

### 3. Navegador

```powershell
python -m playwright install chromium   # solo si no tenés Chrome instalado
```

### 4. Iniciar sesión (una vez por red)

```powershell
argos login instagram
argos login facebook
```

Se abre una ventana del navegador; iniciás sesión a mano y queda guardada en
`~/.argos/profiles/<red>/`. Argos no guarda contraseñas.

### 5. Verificar

```powershell
argos doctor          # estado de las sesiones
argos quota           # acciones usadas/restantes hoy
```

## Uso rápido

```powershell
# Instagram
argos ig profile nasa --limit 12
argos ig posts nasa --limit 12 --json
argos ig search nasa --type users --limit 10
argos ig hashtag astrophotography --limit 12
argos ig reels nasa --limit 12
argos ig comments https://www.instagram.com/nasa/p/XXXXXXXX/ --limit 20

# Facebook
argos fb page NASA --limit 12
argos fb search nasa --type pages --limit 10
argos fb search "Uriel Arriaga Garcia" --type people --variants --limit 20
argos fb groups-feed --limit 12
```

Convenciones: `--json` imprime JSON a stdout (para parsear); `--out DIR` guarda JSONL deduplicado;
`--headless` corre sin ventana. Exit codes: `0` ok · `1` error · `2` uso inválido ·
`3` requiere humano (login/checkpoint) · `4` rate-limited · `5` sin resultados.

## Integración con agentes y n8n

```powershell
argos skill --install   # copia el SKILL.md a los directorios de skills de los agentes
argos quota --json      # para gatear antes de correr un workflow
argos mcp               # servidor MCP (stdio) con las lecturas como tools tipadas
```

- **Agentes:** con `argos skill --install` descubren el skill automáticamente.
- **n8n:** nodo *Execute Command* (`argos … --json` + parsear stdout) o nodo *MCP Client*
  apuntando a `argos mcp`.

## Seguridad / cuentas

- Usá cuentas dedicadas para automatización: las plataformas pueden restringir cuentas con
  actividad no humana.
- Límites por defecto: 12 acciones/min (IG) y 8 (FB), 400 acciones/día por red, pausas de 3–9 s.
  Todo configurable en `~/.argos/config.yaml`.
- Ante login-wall, checkpoint o 429, Argos se detiene y guarda evidencia en `~/.argos/debug/`.

## Desinstalar

```powershell
pip uninstall argos
# y si querés borrar sesiones y cuota:
#   (borrar la carpeta ~/.argos/)
```

Más detalles: `README.md` y `PLAN.md` dentro de `argos/`.
