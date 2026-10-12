# AGENTS.md — instalar Argos (instrucciones para el agente)

Tu tarea: instalar Argos, una CLI de **solo lectura** para Instagram y Facebook,
en esta máquina. Acá está todo lo que necesitás.

> ⚠️ Este zip incluye cookies de sesión reales en `cookies/`. Tratá ese contenido
> como credenciales: no lo muestres en logs, no lo subas a repos, no lo compartas.

## Qué hacer

1. Si el zip no está descomprimido, extraélo.
2. Ejecutá el instalador (idempotente; podés re-correro si algo falla):
   - Linux/macOS: `bash instalar.sh`
   - Windows: `powershell -ExecutionPolicy Bypass -File instalar.ps1`
3. Esperá a que termine. Éxito = imprime `== Instalación completa ==` y la versión.
   Si hay carpeta `cookies/`, el instalador las importa solo y la sesión queda lista
   (verificá con `argos doctor`).

## Límites (no cruzar)

- **No modifiqués nada fuera de la carpeta extraída y `~/.argos/`.**
- **No corras `sudo` sin que el usuario lo apruebe.** Si el script avisa que faltan
  dependencias del sistema (`sudo <venv>/python -m playwright install --with-deps chromium`),
  pedí permiso antes.
- **No automatices el login ni pidas credenciales.** El login abre un navegador y lo
  hace un humano. Vos no podés ni debés iniciar sesión.
- No instalés paquetes de Python fuera del venv que crea el script.

## Resultado esperado

- Binario: `~/.argos/venv/bin/argos` (Linux/macOS) o `~\.argos\venv\Scripts\argos.exe` (Windows).
- `argos doctor --json`: cada red debería quedar en `needs-login` (falta sesión) o `ok`.
- `argos quota`: cuota 400 acciones/día por red.

## Iniciar sesión (requiere humano)

- **Máquina con navegador:** el usuario corre `argos login instagram` y
  `argos login facebook`; se abre una ventana y la sesión queda guardada.
- **VPS sin navegador (headless):** `argos login` no puede abrir ventana. Migrá la sesión
  con cookies (el usuario las exporta en su máquina con `argos cookies <red> --out X.json`
  y vos las importás acá con `cat X.json | argos configure <ig-cookies|fb-cookies> --stdin`).
  **No intentes inventar una sesión ni pedir credenciales.**

## Después de instalar

Reportá: la versión instalada, el resultado de `argos doctor`, y qué falta
(login / dependencias del sistema). Listo.
