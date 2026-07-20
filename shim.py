"""REST-шим между 1С и rlm-tools-bsl (голый мост D3).
1С шлёт простой JSON {module, line} → шим говорит с rlm по MCP → отдаёт 1С готовый JSON.
Вся MCP/SSE-сложность заперта здесь, BSL остаётся тонким.
Запуск: uv run python shim.py  (порт 9001, rlm на 9000)."""
import json
import os
import re
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

# Все параметры — из окружения, чтобы одна и та же shim.py работала как Windows-служба,
# в Docker и на сервере. Дефолты сохраняют поведение пилота (файловая база, loopback).
# В поставке AUDIT_SRC ОБЯЗАТЕЛЕН (дампа исходников по умолчанию нет) — см. DEPLOY.md.
RLM_URL = os.environ.get("AUDIT_RLM_URL", "http://127.0.0.1:9000/mcp")
SRC = os.environ.get("AUDIT_SRC", "")                        # дамп исходников, который индексирует rlm (ОБЯЗАТЕЛЕН)
HOST = os.environ.get("AUDIT_HOST", "127.0.0.1")              # 0.0.0.0 для серверной базы (rphost на другом хосте)
PORT = int(os.environ.get("AUDIT_PORT", "9001"))

if not SRC:
    raise SystemExit("AUDIT_SRC не задан: укажите путь к XML-дампу конфигурации (см. DEPLOY.md)")

# Тело диагностики, исполняется внутри rlm-песочницы. mod/target подставляются заголовком.
DIAG_BODY = r'''
import json
outline = get_module_outline(mod)
mod_path = outline.get("path")
tot = outline.get("totals", {})
methods = []
def walk(regs):
    for r in regs:
        for m in r.get("methods", []):
            methods.append(m)
        walk(r.get("children", []))
walk(outline.get("outline", []))
methods += outline.get("orphan_methods", [])
hit = None
for m in methods:
    ln = m.get("line") or 0
    en = m.get("end_line") or 10**9
    if ln <= target <= en:
        hit = m
        break
result = {"module": mod, "module_path": mod_path, "module_loc": tot.get("loc"), "method": None}
if hit:
    name = hit.get("name")
    body = read_procedure(mod_path, name)
    callers = find_callers(name)
    result["method"] = {
        "name": name,
        "type": hit.get("type"),
        "is_export": hit.get("is_export"),
        "line_range": [hit.get("line"), hit.get("end_line")],
        "loc": (hit.get("end_line") or 0) - (hit.get("line") or 0) + 1,
        "body": body if isinstance(body, str) else json.dumps(body, ensure_ascii=False),
        "callers": callers if isinstance(callers, list) else [],
        "callers_count": len(callers) if isinstance(callers, list) else 0,
    }
print(json.dumps(result, ensure_ascii=False))
'''


def _txt(res):
    return "\n".join(getattr(c, "text", "") for c in res.content if getattr(c, "text", ""))


def _sid(s):
    m = re.search(r'"session[_a-z]*"\s*:\s*"([^"]+)"', s)
    return m.group(1) if m else None


async def audit(request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "невалидный JSON"}, status_code=400)
    mod = data.get("module")
    line = data.get("line")
    if not mod or not line:
        return JSONResponse({"ok": False, "error": "поля module и line обязательны"}, status_code=400)
    code = "mod = %s\ntarget = %d\n" % (json.dumps(mod, ensure_ascii=False), int(line)) + DIAG_BODY
    try:
        async with streamablehttp_client(RLM_URL) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                r1 = await s.call_tool("rlm_start", {"path": SRC, "query": "audit %s:%s" % (mod, line)})
                sid = _sid(_txt(r1))
                r2 = await s.call_tool("rlm_execute", {"session_id": sid, "code": code})
                out = _txt(r2)
                try:
                    await s.call_tool("rlm_end", {"session_id": sid})
                except Exception:
                    pass
    except Exception as e:
        return JSONResponse({"ok": False, "error": "rlm недоступен: %s" % e}, status_code=502)
    try:
        env = json.loads(out)
        if env.get("error"):
            return JSONResponse({"ok": False, "error": env["error"]}, status_code=500)
        payload = json.loads(env.get("stdout", "").strip().splitlines()[-1])
        return JSONResponse({"ok": True, **payload})
    except Exception as e:
        return JSONResponse({"ok": False, "error": "разбор ответа rlm: %s" % e, "raw": out[:1500]}, status_code=500)


async def health(request):
    return JSONResponse({"ok": True, "service": "iikona-audit-shim",
                         "rlm": RLM_URL, "src": SRC, "host": HOST, "port": PORT})


app = Starlette(routes=[
    Route("/audit", audit, methods=["POST"]),
    Route("/health", health, methods=["GET"]),
])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
