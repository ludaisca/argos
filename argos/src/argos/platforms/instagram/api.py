"""Acceso a la API interna de Instagram desde el contexto del navegador.

Nota (2026-09-30, verificado en vivo): la API interna de IG en este entorno
responde de forma errática (200 con HTML, 429 al ritmo). Por eso los flujos de
lectura son DOM-first y ``api_get`` queda solo para usos oportunistas.
"""

from __future__ import annotations

from typing import Any, cast

from playwright.sync_api import Page

IG_APP_ID = "936619743392459"

#: La ejecución devuelve siempre una forma estable, nunca lanza en JS.
_FETCH_JS = """
async ([path, appId]) => {
  try {
    const response = await fetch(path, {
      credentials: 'include',
      headers: { 'x-ig-app-id': appId },
    });
    const text = await response.text();
    let data = null;
    try { data = JSON.parse(text); } catch (error) { data = null; }
    return { status: response.status, data: data, error: null };
  } catch (error) {
    return { status: 0, data: null, error: String(error) };
  }
}
"""


def api_get(page: Page, path: str) -> dict[str, Any]:
    """GET a la API interna desde el contexto autenticado del navegador."""
    result = cast(dict[str, Any], page.evaluate(_FETCH_JS, [path, IG_APP_ID]))
    if not isinstance(result, dict):
        return {"status": 0, "data": None, "error": "respuesta inválida del navegador"}
    return result
