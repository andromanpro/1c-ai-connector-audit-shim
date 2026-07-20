# Развёртывание аудитора кода D3 (шим + rlm)

Аудитор кода ИИконы состоит из двух движущихся частей вне 1С:

```
1С (КИИ_АудиторКода) ──POST /audit {module,line}──▶ ШИМ :9001 ──MCP──▶ rlm :9000 (индекс XML-дампа)
                     ◀──── {method, body, callers} ─────────────────
```

- **rlm-tools-bsl** — семантический движок (MIT, github.com/Dach-Coin/rlm-tools-bsl). Stateless,
  держит только SQLite-индекс дампа. **Ставится РОДНЫМ установщиком upstream** — не переизобретаем.
- **шим** (`shim.py`) — тонкий REST-мост: прячет MCP/SSE, отдаёт 1С готовый JSON. **Наш**, ставится
  рядом с rlm одним из трёх способов ниже.

Обе части — только «механика наружу». Диагноз ставит LLM через `КИИ_КоннекторИИ` (внутри 1С),
результат падает в `КИИ_МониторингОшибокЖурнал`. На движке и шиме ничего ценного не оседает.

---

## 0. Топология и bind/auth — прочитать ПЕРВЫМ

Где размещать шим+rlm и как их закрывать — зависит от того, откуда ходит код 1С (`rphost` на
серверной базе, клиент — на файловой). Клиент `КИИ_АудиторКода` берёт адрес:порт из констант
(`КИИ_АдресХостаШимаАудитора` / `КИИ_ПортШимаАудитора`), поэтому 1С-сторона от топологии не зависит —
меняется только `AUDIT_HOST` шима и firewall.

| Топология | Где шим+rlm | `AUDIT_HOST` | Firewall / auth |
|---|---|---|---|
| Файловая база | тот же ПК, что и клиент 1С | `127.0.0.1` | не нужно (loopback) |
| Серверная, 1 сервер | тот же хост, что и кластер (`rphost`) | `127.0.0.1` | не нужно (loopback) |
| Серверная, шим на отдельном хосте | отдельная машина | `0.0.0.0` / конкретный IP | **firewall :9001 только с IP кластера** |
| Многосерверный кластер | известный хост, доступный всем рабочим серверам | `0.0.0.0` / LAN IP | **firewall: только IP рабочих серверов** |

> ⚠️ **Шим неаутентифицирован.** Это голый REST, отдающий исходный код по `{модуль, строка}`.
> На `127.0.0.1` — безопасно. На `0.0.0.0` в общей сети это **читалка кода** для всего сегмента.
> Для не-loopback топологий **обязательно** ограничь доступ firewall'ом до IP хостов кластера 1С.
> (Токен-аутентификация шима — в плане; пока сеть закрывается только firewall'ом + доверенным bind.)

**Дефолт-рекомендация:** держи шим+rlm **co-located** с 1С (тот же хост) и слушай `127.0.0.1`.
Это проще, быстрее (нет сети между 1С и шимом) и не требует firewall/auth. Отдельный хост —
только если так требует инфраструктура кластера.

---

## Общий шаг: XML-дамп конфигурации + индекс rlm

rlm анализирует **XML-выгрузку** конфигурации (не живую базу). Один раз подготовь дамп и индекс,
дальше обновляй по мере изменения кода («свежесть»).

1. **Выгрузить конфигурацию в XML** (Конфигуратор/`ibcmd`/`DESIGNER`):
   - основную конфигурацию: `DumpConfigToFiles <dump>`;
   - расширения: тем же дампом с `-AllExtensions` (в отдельные подпапки).
   - Кириллица в путях → `.bat` в cp1251 (см. skill `cyrillic-paths`).
2. **Построить индекс** (ускоряет резолв строка→метод и граф вызовов):
   ```bash
   rlm-bsl-index index build <путь-к-дампу>
   ```
   Индекс ложится в `~/.cache/rlm-tools-bsl/` (переживает переустановку движка).
3. **Обновление свежести** после изменения кода — пере-дамп + `rlm-bsl-index index update <путь>`
   (инкрементально; в Docker — `docker compose exec rlm rlm-bsl-index index update /repos/iikona`).

> Путь дампа, который шлёт шим (`AUDIT_SRC`), должен **точно совпадать** со строкой, по которой
> построен индекс — rlm ключует индекс по пути.

---

## Вариант A — Windows-служба (файловая или одиночный Windows-сервер)

Самый надёжный headless-автозапуск на Windows. rlm — родной службой upstream, шим — через WinSW.

### A1. rlm как служба (родной установщик)

PowerShell **от администратора**:
```powershell
irm https://raw.githubusercontent.com/Dach-Coin/rlm-tools-bsl/master/simple-install-from-pip.ps1 -OutFile simple-install-from-pip.ps1
PowerShell -ExecutionPolicy Bypass -File .\simple-install-from-pip.ps1
```
Скрипт поставит пакет из PyPI, зарегистрирует и запустит службу, проверит `/health` на :9000.
Диагностика при сбое (ошибка 1053 и т.п.) — `diagnose-service-win.ps1` (см. upstream INSTALL.md).

### A2. шим как служба (WinSW)

1. Разверни дамп рядом с шимом как `xml-dump/` (или поправь `AUDIT_SRC` в конфиге, шаг 3).
2. PowerShell **от администратора** из каталога шима:
   ```powershell
   PowerShell -ExecutionPolicy Bypass -File .\deploy\windows\install-shim-service.ps1
   ```
   Скрипт: `uv sync` (создаст `.venv`) → скачает WinSW как `iikona-audit-shim.exe` →
   поставит конфиг → зарегистрирует и запустит службу → проверит `/health` на :9001.
3. Проверь блок `<env>` в `iikona-audit-shim.xml` (`AUDIT_SRC`, `AUDIT_HOST`) — правь под установку,
   затем перезапусти: `iikona-audit-shim.exe restart`.

Управление: `iikona-audit-shim.exe start|stop|restart|status|uninstall`. Логи — `*.out.log`/`*.err.log`
рядом с exe.

---

## Вариант B — Docker (оптимально на Linux-хосте)

На Windows Docker Desktop **не рекомендуется**: I/O 1С-исходников через WSL2/Virtiofs медленнее в
5-10x (индексация конфигурации из ~6 мин превращается в 50+). Это документированное ограничение
Docker Desktop, не rlm. На Windows бери вариант A.

1. Клонируй движок и подготовь `.env`:
   ```bash
   git clone https://github.com/Dach-Coin/rlm-tools-bsl   # рядом, путь пойдёт в RLM_REPO
   cd deploy/docker && cp .env.example .env
   # заполни RLM_REPO (путь к клону) и AUDIT_DUMP (путь к XML-дампу конфигурации)
   ```
2. Подъём:
   ```bash
   docker compose up -d --build
   ```
   Поднимутся два сервиса: `rlm` (:9000) и `shim` (:9001, стартует после healthy rlm).
   Дамп монтируется в rlm read-only как `/repos/iikona`; шим шлёт именно этот путь (`AUDIT_SRC=/repos/iikona`).
3. Построй индекс внутри контейнера (один раз / после изменений кода):
   ```bash
   docker compose exec rlm rlm-bsl-index index build /repos/iikona
   ```
4. Проверка: `curl http://localhost:9001/health` и тестовый `/audit` (см. ниже).

Тома `rlm-config` и `rlm-index-cache` переживают `docker compose down && up`. Обновление движка —
`docker compose restart rlm` (образ авто-подтягивает свежий пакет из PyPI; фиксация версии — `RLM_VERSION`).

---

## Вариант C — Linux без Docker (systemd)

1. rlm службой (родной установщик):
   ```bash
   curl -LO https://raw.githubusercontent.com/Dach-Coin/rlm-tools-bsl/master/simple-install-from-pip.sh
   chmod +x simple-install-from-pip.sh && ./simple-install-from-pip.sh
   loginctl enable-linger $USER   # автозапуск без входа
   ```
2. шим службой:
   ```bash
   sudo cp -r <каталог-шима> /opt/iikona-audit-shim
   cd /opt/iikona-audit-shim && uv sync              # создаст .venv
   sudo useradd -r -s /usr/sbin/nologin iikona
   sudo cp deploy/linux/iikona-audit-shim.service /etc/systemd/system/
   # поправь Environment=AUDIT_SRC и User= в unit'е под установку
   sudo systemctl daemon-reload
   sudo systemctl enable --now iikona-audit-shim
   ```

---

## Настройка 1С (после любого варианта)

Константы в базе ИИконы (можно через форму настройки анализатора):

| Константа | Тип | Значение |
|---|---|---|
| `КИИ_АдресХостаШимаАудитора` | Строка | пусто = авто (файловая→127.0.0.1; серверная→хост кластера). Явный IP — для отдельного хоста шима |
| `КИИ_ПортШимаАудитора` | Число | `9001` (или свой) |
| `МодельДляАнализа` | — | модель для диагноза, **`ИспользоватьПрокси=Истина`** (иначе resolve-host/403 при системном прокси) |

Регламент `КИИ_АудиторКодаАвтоанализ` (раз в час): проверь `Использование=Истина` и что база
стартует с `/AllowExecuteScheduledJobs`. Автоанализ ходит в шим → при недоступном шиме fail-closed
(0 диагнозов, не падает).

---

## Проверка работоспособности

```bash
# шим жив
curl http://127.0.0.1:9001/health
# → {"ok":true,"service":"iikona-audit-shim","rlm":"...","src":"...","host":"...","port":9001}

# сквозной аудит (подставь реальный модуль:строку своей конфигурации)
curl -s -X POST http://127.0.0.1:9001/audit -H "Content-Type: application/json" \
  --data-binary '{"module":"КИИ_HTTPКлиент","line":342}'
# → {"ok":true,"module":"...","method":{"name":"...","line_range":[...],"body":"...","callers":[...]}}
```

Из 1С — `КИИ_АудиторКода.ШимДоступен()` (true/false) и `ПроанализироватьМестоОшибки(Модуль, Строка)`.

> ⚠️ Windows-curl часто ходит через системный прокси (VPN/xkeen и т. п.) и врёт по localhost — проверяй
> с `--noproxy '*'` или из самого 1С (`КИИ_АудиторКода.ШимДоступен`).
