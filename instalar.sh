#!/usr/bin/env bash
# Argos — instalador de un solo comando (Linux/macOS; pensado para VPS).
# Idempotente y no interactivo: lo puede correr un agente sin supervisión.
# Uso:  bash instalar.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/argos"
VENV_DIR="${ARGOS_VENV:-$HOME/.argos/venv}"
PY=""

echo "== Argos: instalando =="

# 1) Encontrar un Python >= 3.11
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PY="$candidate"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "ERROR: se necesita Python 3.11 o superior." >&2
  echo "  Ubuntu/Debian: sudo apt-get install -y python3.12 python3.12-venv" >&2
  exit 2
fi
echo "Python: $($PY --version)"

# 2) Virtualenv
if [ ! -x "$VENV_DIR/bin/python" ]; then
  "$PY" -m venv "$VENV_DIR"
fi
V="$VENV_DIR/bin/python"

# 3) Instalar el paquete (fuente local; dependencias desde PyPI)
"$V" -m pip install --quiet --upgrade pip
"$V" -m pip install --quiet "$PROJECT_DIR"

# 4) Navegador de Playwright
if [ "$(id -u)" = "0" ]; then
  "$V" -m playwright install --with-deps chromium
else
  "$V" -m playwright install chromium || true
  echo "AVISO: sin root no se instalaron las dependencias del sistema."
  echo "  Si Chromium no arranca, pedí al usuario:"
  echo "  sudo '$V' -m playwright install --with-deps chromium"
fi

# 5) Cookies incluidas en el zip (opcional; para VPS sin navegador)
COOKIE_DIR="$SCRIPT_DIR/cookies"
IMPORTED=""
if [ -d "$COOKIE_DIR" ]; then
  for name in instagram facebook; do
    file="$COOKIE_DIR/${name}-cookies.json"
    [ -f "$file" ] || continue
    if [ "$name" = "instagram" ]; then key="ig-cookies"; else key="fb-cookies"; fi
    if "$VENV_DIR/bin/argos" configure "$key" --stdin < "$file"; then
      IMPORTED="$IMPORTED $name"
    fi
  done
  if [ -n "$IMPORTED" ]; then
    echo "Cookies importadas:$IMPORTED"
  fi
fi

# 6) Verificación (sin red: versión y cuota)
echo "== Verificando =="
"$VENV_DIR/bin/argos" --version
"$VENV_DIR/bin/argos" quota || true

echo ""
echo "== Instalación completa =="
echo "Binario: $VENV_DIR/bin/argos"
echo "Para usarlo sin ruta completa:"
echo "  export PATH=\"$VENV_DIR/bin:\$PATH\""
echo ""
if [ -n "$IMPORTED" ]; then
  echo "Sesión lista (cookies importadas)."
  echo "Verificá con: argos doctor"
else
  echo "Pendiente (requiere humano): iniciar sesión una vez por red."
  echo "  argos login instagram"
  echo "  argos login facebook"
  echo "En un VPS sin navegador (headless), ver AGENTS.md."
fi
