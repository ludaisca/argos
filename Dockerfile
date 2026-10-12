# Argos en Docker — agente autónomo de investigación en Facebook e Instagram.
#
# Base oficial de Playwright: trae Chromium y las dependencias del sistema ya
# instaladas, así el build es rápido y confiable en cualquier VPS.
# Si querés otra versión de Playwright, cambiá el tag (debe coincidir con la
# versión que instala pip, ver `pip show playwright`).
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ARGOS_HOME=/data

WORKDIR /app

# Código + instalación del paquete y del Chromium
COPY argos /app/argos
RUN pip install /app/argos \
    && python -m playwright install chromium

# Estado persistente: config, sesiones, corridas e informes
VOLUME ["/data"]

ENTRYPOINT ["python", "-m", "argos.cli"]
# Por defecto: agente en loop.  Override: `docker run … agent run`
CMD ["agent", "daemon"]
