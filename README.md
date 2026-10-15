# Аудит-шим ИИконы

REST-мост между [ИИконой](https://github.com/andromanpro/1c-ai-connector)
(аудитор кода) и анализатором
[rlm-tools-bsl](https://github.com/Dach-Coin/rlm-tools-bsl): 1С шлёт простой JSON
`{module, line}` — шим разговаривает с rlm по MCP и возвращает готовый ответ
(метод, тело, граф вызовов). Вся сложность MCP/SSE заперта здесь, BSL-сторона
остаётся тонкой.

```
1С (КИИ_АудиторКода) ──{модуль, строка}──▶ шим (REST :9001) ──▶ rlm-tools-bsl (MCP :9000)
```

## Установка

Три варианта — Windows-служба, Docker, systemd. Пошагово — в [DEPLOY.md](DEPLOY.md);
готовые файлы — в [deploy/](deploy/). Коротко для Windows:

```powershell
# 1) rlm-tools-bsl — родным установщиком (PowerShell от администратора)
irm https://raw.githubusercontent.com/Dach-Coin/rlm-tools-bsl/master/simple-install-from-pip.ps1 -OutFile simple-install-from-pip.ps1
PowerShell -ExecutionPolicy Bypass -File .\simple-install-from-pip.ps1

# 2) шим — службой
PowerShell -ExecutionPolicy Bypass -File .\deploy\windows\install-shim-service.ps1
```

Конфигурация — переменными окружения:

| Переменная | Дефолт | Что это |
|---|---|---|
| `AUDIT_SRC` | — (**обязательна**) | путь к XML-дампу конфигурации, который индексирует rlm |
| `AUDIT_RLM_URL` | `http://127.0.0.1:9000/mcp` | адрес rlm-tools-bsl |
| `AUDIT_HOST` | `127.0.0.1` | где слушать (`0.0.0.0` — для серверной базы на другом хосте) |
| `AUDIT_PORT` | `9001` | порт шима |

## API

```bash
curl http://127.0.0.1:9001/health
curl -X POST http://127.0.0.1:9001/audit -H "Content-Type: application/json" \
  --data-binary '{"module":"<ИмяМодуля>","line":<номер>}'
```

Ответ: имя метода, диапазон строк, тело, список вызывающих мест.

## Безопасность

Шим неаутентифицирован и отдаёт исходный код по координате. На `127.0.0.1`
безопасно; при публикации по сети закройте порт firewall'ом, пустив только
адреса серверов 1С. Настройка со стороны 1С (константы, право чтения кода) —
в [руководстве аудитора кода](https://github.com/andromanpro/1c-ai-connector-guide).

## О проекте

[ИИкона](https://github.com/andromanpro/1c-ai-connector) — расширение для работы с ИИ в 1С.

<a href="https://infostart.ru/1c/articles/2585691/">
  <img src="https://infostart.ru/bitrix/templates/sandbox_empty/assets/tpl/abo/img/logo.svg" alt="Инфостарт" width="140">
</a>

[ИИкона на Инфостарте — описание и файл](https://infostart.ru/1c/articles/2585691/).

## Лицензия

[MIT](LICENSE) © 2026 Роман Андриянов ([androman.pro](https://androman.pro))
