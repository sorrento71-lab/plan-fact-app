#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Прототип «План-Факт» — вариант А: отдельное окно без браузера.

Что делает этот файл (одним процессом):
  1. поднимает существующий FastAPI-бэкенд из backend/ на http://127.0.0.1:8000
     (uvicorn.Server в отдельном потоке; код backend/ НЕ меняется);
  2. отдаёт собранную React-статику из desktop-a/webapp по http://127.0.0.1:3000
     (http.server.ThreadingHTTPServer + SPA-fallback на index.html);
  3. открывает окно pywebview на http://127.0.0.1:3000/index.html — в отдельном
     дочернем процессе (pywebview тянет pythonnet/WebView2, которые при сбое могут
     уронить процесс, поэтому серверы изолированы). Если нативное окно не получилось —
     резервный вариант: отдельное окно-приложение Edge/Chrome (--app, без вкладок и
     адресной строки). Если не вышло ничего — понятное сообщение, а не белый экран;
  4. при закрытии окна останавливает оба сервера и завершает процесс.

Порты 8000/3000 выбраны не случайно: frontend/src/config.js обращается к API по
адресу http://<хост>:8000 (хост берётся из адресной строки), поэтому окно и
другие машины видят один и тот же API. backend/app.py разрешает CORS для
localhost и частных адресов локальной сети, поэтому список адресов править не
нужно — меняется только IP компьютера.

Сетевой режим (по умолчанию): серверы слушают все интерфейсы (0.0.0.0), окно
открывается на http://127.0.0.1:3000, а другие участники заходят браузером на
http://<адрес этого ПК>:3000. Только этот компьютер: --local-only.

Режимы запуска:
  python launcher.py                  — обычный запуск (окно, доступно в сети)
  python launcher.py --local-only     — только этот компьютер (без доступа из сети)
  python launcher.py --host 0.0.0.0   — явно указать адрес прослушивания
  python launcher.py --selftest       — поднять серверы, проверить HTTP, выйти (окно не открывать)
  python launcher.py --no-window      — то же, но серверы работают до Ctrl+C
  python launcher.py --window-test    — открыть окно, убедиться, что оно появилось, закрыть (автотест окна)
  python launcher.py --window browser — сразу окно-приложение Edge/Chrome (--app), без pywebview

Все пути вычисляются относительно расположения этого файла.
"""

from __future__ import annotations

import argparse
import ctypes
import http.server
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ----------------------------------------------------------------------------
# Константы
# ----------------------------------------------------------------------------
APP_TITLE = "План-Факт"
WINDOW_WIDTH = 1600
WINDOW_HEIGHT = 950
WINDOW_MIN_SIZE = (1100, 700)

DEFAULT_API_PORT = 8000   # жёстко задан в frontend/src/config.js
DEFAULT_WEB_PORT = 3000
# По умолчанию серверы слушают все интерфейсы: окно открывается на этой машине
# (127.0.0.1), а остальные участники заходят браузером на
# http://<адрес этой машины>:3000 — интерфейс сам обращается к API на :8000.
# Режим «только этот компьютер»: --local-only (или PLANFACT_HOST=127.0.0.1).
BIND_ALL_HOST = "0.0.0.0"
LOCAL_HOST = "127.0.0.1"
BIND_HOST = BIND_ALL_HOST   # адрес, на котором реально слушают серверы
WEB_HOST = LOCAL_HOST       # адрес для окна и проверок
API_HOST = LOCAL_HOST

BACKEND_START_TIMEOUT = 90.0     # сек: первый импорт pandas/openpyxl небыстрый
PROBE_TIMEOUT = 4.0
REUSE_PROBE_TIMEOUT = 3.0

HERE = Path(__file__).resolve().parent

EXIT_OK = 0
EXIT_ERROR = 2


# ----------------------------------------------------------------------------
# Логирование (в консоль + в файл; под pythonw.exe консоли нет, поэтому файл)
# ----------------------------------------------------------------------------
class Log:
    def __init__(self, path: Path | None):
        self.path = path
        self._lock = threading.Lock()
        self._file = None
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._file = open(path, "a", encoding="utf-8", errors="replace")
            except OSError:
                self._file = None

    def _emit(self, text: str, console: bool) -> None:
        line = text if text.endswith("\n") else text + "\n"
        with self._lock:
            if self._file is not None:
                try:
                    self._file.write(line)
                    self._file.flush()
                except OSError:
                    pass
            if console:
                try:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                except Exception:
                    pass

    def info(self, text: str, console: bool = True) -> None:
        self._emit(text, console)

    def debug(self, text: str) -> None:
        """Только в файл (запросы статики и прочий шум)."""
        self._emit(text, console=False)

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                try:
                    self._file.close()
                except OSError:
                    pass
                self._file = None


LOG: Log = Log(None)


# ----------------------------------------------------------------------------
# Пути: исходники (python) или one-dir сборка PyInstaller (frozen)
# ----------------------------------------------------------------------------
class Paths:
    def __init__(self, backend_dir: Path, webapp_dir: Path, data_root: Path, mode: str):
        self.backend_dir = backend_dir
        self.webapp_dir = webapp_dir
        self.data_root = data_root
        self.mode = mode

    @property
    def index_html(self) -> Path:
        return self.webapp_dir / "index.html"


def _project_root_near(exe_dir: Path, levels: int = 4) -> Path | None:
    """Папка проекта рядом со сборкой: в ней те же данные, что у веб-версии.

    Собранный exe обычно лежит в <проект>\\desktop-a\\dist\\План-Факт, поэтому
    поднимаемся на несколько уровней вверх и ищем backend\\plan_fact.db.
    """
    current = exe_dir
    for _ in range(levels):
        current = current.parent
        if (current / "backend" / "plan_fact.db").is_file():
            return current
    return None


def resolve_paths() -> Paths:
    """backend/ и webapp/ ищутся рядом с launcher.py, а в exe — в папке сборки."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass))
        candidates.append(exe_dir)
        base = candidates[0]
        for candidate in candidates:
            if (candidate / "backend").is_dir():
                base = candidate
                break
        # Интерфейс всегда берём из сборки, а данные — из папки проекта,
        # если exe запущен внутри неё: тогда веб-версия и настольное окно
        # работают с одной базой и одним графиком.
        project_root = _project_root_near(exe_dir)
        if project_root is not None:
            return Paths(project_root / "backend", base / "webapp", project_root, "exe")
        base = candidates[0]
        return Paths(base / "backend", base / "webapp", base, "exe")

    project_root = HERE.parent
    return Paths(project_root / "backend", HERE / "webapp", project_root, "python")


def log_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "launcher.log"
    return HERE / "launcher.log"


# ----------------------------------------------------------------------------
# Сеть: проверка портов и HTTP-пробы
# ----------------------------------------------------------------------------
def lan_addresses() -> list[str]:
    """IPv4-адреса этой машины в локальной сети — по ним заходят другие ПК."""
    addresses: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address and not address.startswith("127.") and address not in addresses:
                addresses.append(address)
    except OSError:
        pass
    if not addresses:
        # Запасной способ: узнать адрес, через который выходим в сеть.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
            if address and not address.startswith("127."):
                addresses.append(address)
        except OSError:
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
    return addresses


def port_is_free(host: str, port: int) -> bool:
    """True, если порт можно занять. Без SO_REUSEADDR — иначе Windows соврёт."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def http_get(url: str, timeout: float = PROBE_TIMEOUT) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "PlanFact-DesktopA/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read(4096)


def probe_ok(url: str, timeout: float = PROBE_TIMEOUT) -> tuple[bool, str]:
    try:
        status, _ = http_get(url, timeout)
        if status == 200:
            return True, "200 OK"
        return False, f"HTTP {status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 — нужен понятный текст, а не трейс
        return False, f"{type(exc).__name__}: {exc}"


def port_owner_hint(port: int) -> str:
    """Best-effort: какой процесс слушает порт (для понятного сообщения)."""
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            timeout=10,
            errors="replace",
        )
        pid = None
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].endswith(f":{port}"):
                pid = parts[4]
                break
        if not pid:
            return ""
        name = ""
        try:
            listing = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
                errors="replace",
            )
            first = listing.stdout.strip().splitlines()
            if first and first[0]:
                name = first[0].split(",")[0].strip('"')
        except Exception:  # noqa: BLE001
            pass
        return f" (PID {pid}{', ' + name if name else ''})"
    except Exception:  # noqa: BLE001
        return ""


# ----------------------------------------------------------------------------
# Бэкенд (существующий FastAPI из backend/, без единой правки)
# ----------------------------------------------------------------------------
class Backend:
    def __init__(self, backend_dir: Path, port: int):
        self.backend_dir = backend_dir
        self.port = port
        self.server = None
        self.thread = None
        self.owned = False
        self.error: str | None = None

    def start(self) -> None:
        if str(self.backend_dir) not in sys.path:
            sys.path.insert(0, str(self.backend_dir))

        import uvicorn  # локальный импорт: не грузим тяжёлое до проверок

        import app as backend_app  # backend/app.py

        config = uvicorn.Config(
            app=backend_app.app,
            host=BIND_HOST,
            port=self.port,
            log_level="warning",
            log_config=None,
            access_log=False,
        )
        self.server = uvicorn.Server(config)

        def _run() -> None:
            try:
                self.server.run()
            except BaseException as exc:  # noqa: BLE001
                self.error = f"{type(exc).__name__}: {exc}"
                LOG.info(f"❌ Поток бэкенда упал: {self.error}")

        self.thread = threading.Thread(target=_run, name="planfact-backend", daemon=True)
        self.thread.start()
        self.owned = True

    def wait_ready(self, timeout: float) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout
        url = f"http://{API_HOST}:{self.port}/health"
        while time.monotonic() < deadline:
            if self.error:
                return False, f"бэкенд упал при старте: {self.error}"
            if self.thread is not None and not self.thread.is_alive():
                return False, "поток бэкенда завершился до готовности"
            ok, note = probe_ok(url, 2.0)
            if ok:
                return True, note
            time.sleep(0.4)
        return False, f"бэкенд не ответил на {url} за {timeout:.0f} с"

    def stop(self) -> None:
        if not self.owned or self.server is None:
            return
        try:
            self.server.should_exit = True
        except Exception:  # noqa: BLE001
            pass
        if self.thread is not None:
            self.thread.join(timeout=10)
        if self.thread is not None and self.thread.is_alive():
            try:
                self.server.force_exit = True
            except Exception:  # noqa: BLE001
                pass
            self.thread.join(timeout=5)
        LOG.info("Бэкенд остановлен.")


# ----------------------------------------------------------------------------
# Статика (собранный React)
# ----------------------------------------------------------------------------
class SpaRequestHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler + SPA-fallback.

    Неизвестный путь без расширения (например /schedule/2026) отдаётся как
    index.html с кодом 200 — так работает клиентский роутинг. Запрос
    несуществующего файла с расширением (/static/js/x.js) честно вернёт 404.
    """

    server_version = "PlanFactDesktopA/1.0"
    protocol_version = "HTTP/1.1"

    def _existing_target(self) -> Path | None:
        raw_path = urllib.parse.urlsplit(self.path).path
        translated = Path(self.translate_path(raw_path))
        if translated.is_dir():
            index = translated / "index.html"
            return index if index.is_file() else None
        return translated if translated.is_file() else None

    def send_head(self):
        if self._existing_target() is None:
            raw_path = urllib.parse.urlsplit(self.path).path
            suffix = Path(raw_path).suffix.lower()
            index = Path(self.directory) / "index.html"
            if index.is_file() and suffix in ("", ".html"):
                self.path = "/index.html"
        return super().send_head()

    def end_headers(self):
        # index.html не кэшируем: статику можно пересобрать, не перезапуская прототип
        raw_path = urllib.parse.urlsplit(self.path).path
        if raw_path in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        LOG.debug(f"[web] {self.address_string()} {fmt % args}")


class StaticServer:
    def __init__(self, webapp_dir: Path, port: int):
        self.webapp_dir = webapp_dir
        self.port = port
        self.httpd: http.server.ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.owned = False

    def start(self) -> None:
        handler = lambda *args, **kwargs: SpaRequestHandler(  # noqa: E731
            *args, directory=str(self.webapp_dir), **kwargs
        )
        httpd = http.server.ThreadingHTTPServer((BIND_HOST, self.port), handler)
        httpd.daemon_threads = True
        self.httpd = httpd
        self.thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.3},
                                       name="planfact-static", daemon=True)
        self.thread.start()
        self.owned = True

    def stop(self) -> None:
        if not self.owned or self.httpd is None:
            return
        try:
            self.httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.httpd.server_close()
        except Exception:  # noqa: BLE001
            pass
        if self.thread is not None:
            self.thread.join(timeout=5)
        LOG.info("Веб-сервер статики остановлен.")


# ----------------------------------------------------------------------------
# Окно: pywebview (основной путь) + резервный вариант «окно-приложение» Edge/Chrome
# ----------------------------------------------------------------------------
BROWSER_CANDIDATES = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
)

WM_CLOSE = 0x0010

# --- минимальный Win32-хелпер: поиск и закрытие окон по точному заголовку -----
# Нужен, чтобы проверять факт появления окна (а не только «процесс жив») и чтобы
# автоматический тест окна (--window-test) мог сам его закрыть.
if sys.platform == "win32":
    from ctypes import wintypes

    _USER32 = ctypes.windll.user32
    _ENUM_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def iter_windows() -> list[tuple[int, str, int]]:
        """Видимые окна верхнего уровня: [(hwnd, заголовок, pid), ...]."""
        found: list[tuple[int, str, int]] = []

        def _callback(hwnd, _lparam):
            length = _USER32.GetWindowTextLengthW(hwnd)
            if length and _USER32.IsWindowVisible(hwnd):
                buffer = ctypes.create_unicode_buffer(length + 1)
                _USER32.GetWindowTextW(hwnd, buffer, length + 1)
                pid = wintypes.DWORD()
                _USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                found.append((int(hwnd), buffer.value, pid.value))
            return True

        _USER32.EnumWindows(_ENUM_PROC(_callback), 0)
        return found

    def is_window(hwnd: int) -> bool:
        return bool(_USER32.IsWindow(hwnd))

    def close_window(hwnd: int) -> None:
        _USER32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
else:  # pragma: no cover — прототип рассчитан на Windows
    def iter_windows() -> list[tuple[int, str, int]]:
        return []

    def is_window(hwnd: int) -> bool:
        return False

    def close_window(hwnd: int) -> None:
        return None


def find_window(titles: tuple[str, ...], timeout: float) -> tuple[int, str] | None:
    """Ждёт появления видимого окна с заголовком ровно из titles."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for hwnd, title, _pid in iter_windows():
            if title in titles:
                return hwnd, title
        time.sleep(0.4)
    return None


def runtime_dir() -> Path:
    """Папка для служебных файлов прототипа (профиль резервного окна и т.п.)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return HERE


def fix_index_title(webapp_dir: Path) -> None:
    """В собранном index.html заголовок CRA — «React App». В своей копии статики
    правим его на «План-Факт» (frontend/ не трогаем, правим только webapp/)."""
    index = webapp_dir / "index.html"
    try:
        html = index.read_text(encoding="utf-8")
    except OSError:
        return
    if f"<title>{APP_TITLE}</title>" in html:
        return
    fixed = html.replace("<title>React App</title>", f"<title>{APP_TITLE}</title>")
    if fixed != html:
        try:
            index.write_text(fixed, encoding="utf-8")
            LOG.info(f"Заголовок окна: index.html → «{APP_TITLE}»")
        except OSError as exc:
            LOG.info(f"Заголовок окна поправить не удалось ({exc}) — не критично.")


def pywebview_window_child(url: str, status_file: Path) -> int:
    """ВНУТРЕННИЙ режим (запускается дочерним процессом): только окно pywebview.

    Зачем отдельный процесс: на Windows pywebview тянет pythonnet/WebView2, а они
    при сбое инициализации способны уронить процесс (и подменить код возврата).
    Поэтому окно открывается в отдельном процессе, а основной процесс с серверами
    остаётся неуязвимым: не получилось — просто переходим к резервному варианту.

    Факт успеха пишется в файл статуса, чтобы родитель мог его дождаться.
    """
    def _write(text: str) -> None:
        try:
            status_file.parent.mkdir(parents=True, exist_ok=True)
            status_file.write_text(text, encoding="utf-8")
        except OSError:
            pass

    try:
        import webview
    except Exception as exc:  # noqa: BLE001
        _write(f"fail: модуль pywebview не импортируется ({type(exc).__name__}: {exc})")
        return EXIT_ERROR

    try:
        webview.create_window(
            APP_TITLE,
            url,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=WINDOW_MIN_SIZE,
            text_select=True,
        )

        def _monitor() -> None:
            """Сообщаем родителю, что окно открылось (и закрываем, если попросили)."""
            native = find_window((APP_TITLE,), 15.0)
            known = len(list(getattr(webview, "windows", [])))
            if native is not None:
                _write(f"ok: hwnd={native[0]}, заголовок «{native[1]}»")
            elif known:
                _write(f"ok: окон pywebview: {known} (заголовок окна не опознан через Win32)")
            else:
                _write("fail: окно pywebview не появилось")
            if status_file.with_suffix(".close").is_file():
                for item in list(getattr(webview, "windows", [])):
                    try:
                        item.destroy()
                    except Exception:  # noqa: BLE001
                        pass

        webview.start(_monitor)
    except Exception as exc:  # noqa: BLE001
        _write(f"fail: {type(exc).__name__}: {exc}")
        return EXIT_ERROR
    return EXIT_OK


def open_pywebview_isolated(url: str, timeout: float = 25.0) -> tuple[bool, str, "subprocess.Popen | None"]:
    """Основной путь: окно pywebview, открытое в отдельном процессе.

    Возвращает (успех, пояснение, процесс окна).
    """
    status_file = runtime_dir() / ".pywebview-status"
    try:
        status_file.unlink()
    except OSError:
        pass

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--window-only", url, "--status-file", str(status_file)]
    else:
        cmd = [sys.executable or "python", str(Path(__file__).resolve()),
               "--window-only", url, "--status-file", str(status_file)]

    LOG.info("Открываю окно pywebview в отдельном процессе (изоляция pythonnet/WebView2) ...")
    try:
        process = subprocess.Popen(cmd, close_fds=True)
    except OSError as exc:
        return False, f"не удалось запустить процесс окна: {exc}", None

    def _stop_child() -> None:
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if status_file.is_file():
            text = status_file.read_text(encoding="utf-8", errors="replace").strip()
            if text.startswith("ok"):
                return True, text, process
            _stop_child()
            return False, text, None
        if process.poll() is not None:
            return False, f"процесс окна завершился (код {process.returncode}) без сообщения о статусе", None
        time.sleep(0.3)

    _stop_child()
    return False, f"окно pywebview не появилось за {timeout:.0f} с", None


def find_browser() -> Path | None:
    for candidate in BROWSER_CANDIDATES:
        path = Path(os.path.expandvars(candidate))
        if path.is_file():
            return path
    return None


def _spawn_app_window(browser: Path, url: str, profile: Path | None) -> subprocess.Popen:
    cmd = [
        str(browser),
        f"--app={url}",
        f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,AutofillServerCommunication",
    ]
    if profile is not None:
        cmd.append(f"--user-data-dir={profile}")
    return subprocess.Popen(cmd, close_fds=True)


def open_browser_app_window(
    url: str,
    expected_titles: tuple[str, ...],
    per_attempt_timeout: float = 15.0,
) -> tuple[bool, str, "subprocess.Popen | None", tuple[int, str] | None]:
    """Резервный вариант: отдельное окно Edge/Chrome в режиме --app.

    Окно без вкладок и адресной строки (движок — тот же Chromium/Edge, что и
    WebView2 в pywebview). Сначала пробуем отдельный профиль (не трогаем сессию
    пользователя), затем — профиль браузера по умолчанию: если браузер уже
    запущен, окно откроет его процесс (важно там, где новый процесс браузера
    запрещён политиками/песочницей).

    Успех определяется по факту появления окна с ожидаемым заголовком.
    """
    browser = find_browser()
    if browser is None:
        return False, "не найден ни Edge, ни Chrome", None, None

    attempts: list[tuple[str, Path | None]] = []
    profile = runtime_dir() / ".webprofile"
    try:
        profile.mkdir(parents=True, exist_ok=True)
        attempts.append(("отдельный профиль", profile))
    except OSError:
        pass
    attempts.append(("профиль браузера по умолчанию", None))

    problems: list[str] = []
    for label, prof in attempts:
        LOG.info(f"Пробую окно-приложение {browser.name} --app ({label}) ...")
        try:
            process = _spawn_app_window(browser, url, prof)
        except OSError as exc:
            problems.append(f"{label}: {exc}")
            continue

        window = find_window(expected_titles, per_attempt_timeout)
        if window is not None:
            return True, (f"окно открыто ({browser.name}, {label}, hwnd={window[0]}, "
                          f"заголовок «{window[1]}»)"), process, window
        if process.poll() is None:
            return True, (f"процесс {browser.name} работает (PID {process.pid}, {label}), "
                          f"но окно с ожидаемым заголовком не опознано"), process, None
        problems.append(f"{label}: {browser.name} завершился сразу (код {process.returncode})")
        LOG.info(f"   не получилось: {problems[-1]}")

    return False, "; ".join(problems), None, None


def wait_until_window_closed(process: "subprocess.Popen | None", window: tuple[int, str] | None) -> None:
    """Ждём закрытия окна: по окну (надёжнее) или по процессу браузера."""
    try:
        if window is not None:
            hwnd = window[0]
            while is_window(hwnd):
                time.sleep(0.5)
            return
        if process is not None:
            while process.poll() is None:
                time.sleep(0.5)
            return
        # Определить окно не удалось и процесса нет — не держим серверы вечно
        time.sleep(2.0)
    except KeyboardInterrupt:
        LOG.info("Получен Ctrl+C, закрываю окно...")
        if window is not None:
            close_window(window[0])
        elif process is not None:
            try:
                process.terminate()
            except Exception:  # noqa: BLE001
                pass



# ----------------------------------------------------------------------------
# Диалоги и фатальные ошибки
# ----------------------------------------------------------------------------
def show_message_box(title: str, text: str, error: bool = True) -> None:
    try:
        icon = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, str(text), str(title), 0x0 | icon)
    except Exception:  # noqa: BLE001 — нет desktop-сессии и т.п.
        pass


def fatal(title: str, message: str, detail: str = "", window: bool = True) -> int:
    text = message if not detail else f"{message}\n\n{detail}"
    LOG.info(f"❌ {text}")
    if window:
        show_message_box(f"{APP_TITLE} — ошибка запуска", text)
    return EXIT_ERROR


# ----------------------------------------------------------------------------
# Основной сценарий
# ----------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="launcher.py",
        description="План-Факт (вариант А): бэкенд + статика + отдельное окно pywebview.",
    )
    parser.add_argument("--selftest", action="store_true",
                        help="поднять серверы, проверить HTTP (index.html, /health) и выйти; окно не открывать")
    parser.add_argument("--no-window", action="store_true",
                        help="как --selftest, но серверы продолжают работать до Ctrl+C")
    parser.add_argument("--api-port", type=int, default=None,
                        help=f"порт бэкенда (по умолчанию {DEFAULT_API_PORT}; менять не рекомендуется)")
    parser.add_argument("--web-port", type=int, default=None,
                        help=f"порт статики (по умолчанию {DEFAULT_WEB_PORT}; менять не рекомендуется)")
    parser.add_argument("--no-reuse", action="store_true",
                        help="не переиспользовать уже запущенные серверы на 8000/3000, а падать с ошибкой")
    parser.add_argument("--host", default=None,
                        help="адрес, на котором слушают серверы: 0.0.0.0 (по умолчанию) — программа "
                             "доступна и с других машин по http://<адрес этого ПК>:3000; "
                             "127.0.0.1 — только этот компьютер")
    parser.add_argument("--local-only", action="store_true",
                        help="слушать только этот компьютер (то же, что --host 127.0.0.1)")
    parser.add_argument("--window", choices=("auto", "pywebview", "browser"), default="auto",
                        help="auto (по умолчанию): pywebview, при неудаче — окно-приложение Edge/Chrome; "
                             "pywebview: только нативное окно; browser: сразу окно-приложение")
    parser.add_argument("--window-test", action="store_true",
                        help="открыть окно, убедиться, что оно реально появилось, и закрыть его; "
                             "результат в консоль и в launcher.log (проверка окна без участия человека)")
    parser.add_argument("--timeout", type=float, default=BACKEND_START_TIMEOUT,
                        help=f"сколько секунд ждать готовности бэкенда (по умолчанию {BACKEND_START_TIMEOUT:.0f})")
    # Внутренние ключи: используются только при запуске дочернего процесса окна.
    parser.add_argument("--window-only", metavar="URL", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--status-file", default=None, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

    global LOG
    LOG = Log(log_path())

    # Внутренний режим дочернего процесса: только окно, без серверов и портов.
    if args.window_only:
        status_file = Path(args.status_file) if args.status_file else runtime_dir() / ".pywebview-status"
        LOG.info(f"[окно] Дочерний процесс: открываю pywebview на {args.window_only}")
        return pywebview_window_child(args.window_only, status_file)

    api_port = args.api_port or int(os.environ.get("PLANFACT_API_PORT", DEFAULT_API_PORT))
    web_port = args.web_port or int(os.environ.get("PLANFACT_WEB_PORT", DEFAULT_WEB_PORT))

    # Адрес прослушивания: по умолчанию все интерфейсы (доступно и с других
    # машин), --local-only / PLANFACT_HOST=127.0.0.1 — только этот компьютер.
    global BIND_HOST, WEB_HOST, API_HOST
    bind_host = (args.host or os.environ.get("PLANFACT_HOST")
                 or (LOCAL_HOST if args.local_only else BIND_ALL_HOST))
    BIND_HOST = bind_host
    if bind_host in (BIND_ALL_HOST, "::", ""):
        WEB_HOST = API_HOST = LOCAL_HOST      # окно и проверки — через 127.0.0.1
    else:
        WEB_HOST = API_HOST = bind_host

    # Модальные окна с ошибками показываем только в обычном оконном режиме:
    # в --selftest / --no-window / --window-test вывод идёт в консоль и лог.
    show_window = not (args.selftest or args.no_window or args.window_test)

    LOG.info("=" * 62)
    LOG.info(f"  {APP_TITLE} — прототип «вариант А» (отдельное окно, без браузера)")
    LOG.info("=" * 62)
    LOG.info(f"Лог: {log_path()}")
    LOG.info(f"Порты: бэкенд {api_port}, статика {web_port}")
    if bind_host in (BIND_ALL_HOST, "::", ""):
        LOG.info("Доступ: этот компьютер и локальная сеть")
        addresses = lan_addresses()
        if addresses:
            for address in addresses:
                LOG.info(f"   другие машины: http://{address}:{web_port}  (API: http://{address}:{api_port})")
            LOG.info("   (если не открывается с другой машины — разрешите порты в брандмауэре Windows)")
        else:
            LOG.info("   сетевые адреса не найдены — проверьте подключение к сети")
    else:
        LOG.info(f"Доступ: только {bind_host} (с других машин не подключаются)")
        LOG.info("   чтобы открыть доступ в сети, запустите без --local-only")

    paths = resolve_paths()
    LOG.info(f"Режим: {'exe (PyInstaller)' if paths.mode == 'exe' else 'python (исходники)'}")
    LOG.info(f"backend: {paths.backend_dir}")
    LOG.info(f"webapp : {paths.webapp_dir}")

    if not paths.backend_dir.is_dir():
        return fatal("Backend не найден",
                     f"Не найден каталог backend:\n{paths.backend_dir}\n\n"
                     "Для запуска из исходников ожидается C:\\plan-fact-app\\backend.",
                     window=show_window)
    if not paths.webapp_dir.is_dir():
        return fatal("Статика не собрана",
                     f"Не найден каталог со статикой фронтенда:\n{paths.webapp_dir}\n\n"
                     "Соберите фронтенд:\n"
                     "  cd C:\\plan-fact-app\\frontend\n"
                     "  $env:BUILD_PATH='C:\\plan-fact-app\\desktop-a\\webapp'; npm.cmd run build",
                     window=show_window)
    if not paths.index_html.is_file():
        return fatal("Статика неполная",
                     f"В каталоге статики нет index.html:\n{paths.index_html}\n\n"
                     "Пересоберите фронтенд с BUILD_PATH=C:\\plan-fact-app\\desktop-a\\webapp.",
                     window=show_window)

    backend = Backend(paths.backend_dir, api_port)
    static = StaticServer(paths.webapp_dir, web_port)
    exit_code = EXIT_OK

    if show_window:
        fix_index_title(paths.webapp_dir)

    try:
        # ---------------- бэкенд на 8000 ----------------
        if port_is_free(BIND_HOST, api_port):
            LOG.info(f"Запускаю бэкенд на http://{API_HOST}:{api_port} ...")
            backend.start()
            ready, note = backend.wait_ready(args.timeout)
            if not ready:
                return fatal(
                    "Бэкенд не поднялся",
                    f"Бэкенд не отвечает на http://{API_HOST}:{api_port}/health.\n"
                    f"Причина: {note}\n\n"
                    "Что проверить:\n"
                    "  • ошибки импорта/данных — в этом логе;\n"
                    "  • свободен ли порт 8000;\n"
                    "  • на месте ли backend/plan_fact.db и backend/табель.xlsx.",
                    detail=f"Лог: {log_path()}",
                    window=show_window,
                )
            LOG.info(f"✅ Бэкенд жив ({note}) на http://{API_HOST}:{api_port}")
        else:
            ok, note = probe_ok(f"http://{API_HOST}:{api_port}/health", REUSE_PROBE_TIMEOUT)
            if ok and not args.no_reuse:
                LOG.info(f"⚠️  Порт {api_port} уже занят — похоже, работает обычная веб-версия"
                         f"{port_owner_hint(api_port)}.")
                LOG.info(f"   Переиспользую существующий бэкенд: /health вернул {note}.")
                LOG.info("   Свой бэкенд не запускаю (чужие процессы не трогаю).")
            else:
                return fatal(
                    "Порт 8000 занят",
                    f"Порт {api_port} уже занят{port_owner_hint(api_port)}, и это не похоже на бэкенд "
                    f"«План-Факт» ({note}).\n\n"
                    "Прототипу нужен именно порт 8000: frontend/src/config.js жёстко обращается к "
                    "http://127.0.0.1:8000.\n\n"
                    "Что сделать:\n"
                    "  • остановите обычную веб-версию (C:\\plan-fact-app\\stop.bat) и запустите прототип снова;\n"
                    "  • чужие процессы прототип не завершает намеренно.",
                    window=show_window,
                )

        # ---------------- статика на 3000 ----------------
        if port_is_free(BIND_HOST, web_port):
            LOG.info(f"Запускаю отдачу статики на http://{WEB_HOST}:{web_port} ...")
            static.start()
            url = f"http://{WEB_HOST}:{web_port}/index.html"
            deadline = time.monotonic() + 10
            ok, note = False, "нет ответа"
            while time.monotonic() < deadline:
                ok, note = probe_ok(url, 2.0)
                if ok:
                    break
                time.sleep(0.2)
            if not ok:
                return fatal("Статика не отдаётся",
                             f"{url} не отвечает ({note}).",
                             window=show_window)
            LOG.info(f"✅ Статика отдаётся ({note}): http://{WEB_HOST}:{web_port}/index.html")
        else:
            url = f"http://{WEB_HOST}:{web_port}/index.html"
            ok, note = probe_ok(url, REUSE_PROBE_TIMEOUT)
            if ok and not args.no_reuse:
                LOG.info(f"⚠️  Порт {web_port} уже занят{port_owner_hint(web_port)} — похоже, работает "
                         f"dev-сервер обычной веб-версии.")
                LOG.info(f"   Переиспользую его: /index.html вернул {note}.")
                LOG.info("   Внимание: в этом режиме окно показывает тот же dev-сервер, что и браузер, "
                         "а не собранную статику из desktop-a\\webapp.")
            else:
                return fatal(
                    "Порт 3000 занят",
                    f"Порт {web_port} уже занят{port_owner_hint(web_port)}, и /index.html на нём не отвечает "
                    f"({note}).\n\n"
                    "Прототипу нужен именно порт 3000: за ним закреплён адрес интерфейса "
                    "(http://<адрес этой машины>:3000).\n\n"
                    "Что сделать:\n"
                    "  • остановите обычную веб-версию (C:\\plan-fact-app\\stop.bat) и запустите прототип снова;\n"
                    "  • чужие процессы прототип не завершает намеренно.",
                    window=show_window,
                )

        # ---------------- проверка HTTP ----------------
        targets = [
            ("index.html (статика)", f"http://{WEB_HOST}:{web_port}/index.html"),
            ("/health (бэкенд)", f"http://{API_HOST}:{api_port}/health"),
        ]
        checks_ok = True
        LOG.info("-" * 62)
        for title, url in targets:
            ok, note = probe_ok(url, PROBE_TIMEOUT)
            checks_ok = checks_ok and ok
            LOG.info(f"{'✅' if ok else '❌'} {title:24} {note:10} {url}")
        LOG.info("-" * 62)

        if args.selftest:
            if checks_ok:
                LOG.info("SELFTEST: OK — index.html отдан, бэкенд жив.")
                exit_code = EXIT_OK
            else:
                LOG.info("SELFTEST: FAILED — см. строки ❌ выше.")
                exit_code = EXIT_ERROR
            return exit_code

        if args.no_window:
            LOG.info("Режим --no-window: серверы работают, окно не открывается.")
            LOG.info(f"Откройте вручную: http://{WEB_HOST}:{web_port}/index.html")
            LOG.info("Остановка — Ctrl+C.")
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                LOG.info("Получен Ctrl+C, останавливаю серверы...")
            return EXIT_OK

        # ---------------- окно ----------------
        url = f"http://{WEB_HOST}:{web_port}/index.html"
        # Ожидаемые заголовки окна: свой index.html мы переименовали в «План-Факт»,
        # а если статику отдаёт dev-сервер веб-версии — заголовок останется «React App».
        expected_titles = (APP_TITLE, "React App")

        if args.window_test:
            LOG.info("Проверка окна (--window-test): окно будет открыто и автоматически закрыто.")
            if args.window in ("auto", "pywebview"):
                ok, note, child = open_pywebview_isolated(url)
                if ok:
                    LOG.info(f"WINDOW TEST: OK — pywebview: {note}")
                    if child is not None:
                        try:
                            child.terminate()
                            child.wait(timeout=15)
                        except Exception:  # noqa: BLE001
                            pass
                    return EXIT_OK
                LOG.info(f"❌ pywebview: {note}")
                if args.window == "pywebview":
                    LOG.info("WINDOW TEST: FAILED — нативное окно pywebview не создано.")
                    return EXIT_ERROR
            ok, note, process, window = open_browser_app_window(url, expected_titles)
            if not ok:
                LOG.info(f"WINDOW TEST: FAILED — {note}")
                return EXIT_ERROR
            LOG.info(f"✅ {note}")
            time.sleep(3)
            if window is not None:
                close_window(window[0])
                LOG.info(f"Окно hwnd={window[0]} закрыто автоматически.")
            elif process is not None:
                try:
                    process.terminate()
                except Exception:  # noqa: BLE001
                    pass
            LOG.info("WINDOW TEST: OK — окно реально открылось (см. строку ✅ выше).")
            return EXIT_OK

        if args.window in ("auto", "pywebview"):
            ok, note, child = open_pywebview_isolated(url)
            if ok:
                LOG.info(f"✅ Окно pywebview открыто ({note}). Закройте окно, чтобы завершить программу.")
                try:
                    while child is not None and child.poll() is None:
                        time.sleep(0.5)
                except KeyboardInterrupt:
                    LOG.info("Получен Ctrl+C, закрываю окно...")
                    if child is not None:
                        try:
                            child.terminate()
                        except Exception:  # noqa: BLE001
                            pass
                LOG.info("Окно pywebview закрыто — завершаю работу.")
                return EXIT_OK
            LOG.info(f"❌ pywebview не смог открыть окно: {note}")
            if args.window == "pywebview":
                return fatal(
                    "Не удалось открыть окно",
                    f"pywebview не смог создать окно:\n{note}\n\n"
                    "Частые причины на Windows:\n"
                    "  • отсутствует WebView2 Runtime "
                    "(https://developer.microsoft.com/microsoft-edge/webview2/);\n"
                    "  • pythonnet (clr) не может инициализироваться — например, из-за "
                    "ограничений безопасности процесса.\n\n"
                    f"Пока окно не открылось, приложение доступно в браузере: {url}\n"
                    "Либо запустите с --window browser — откроется отдельное окно-приложение Edge/Chrome.",
                    window=True,
                )
            LOG.info("Перехожу к резервному варианту: отдельное окно-приложение Edge/Chrome "
                     "(--app, без вкладок и адресной строки).")

        ok, note, process, window = open_browser_app_window(url, expected_titles)
        if not ok:
            return fatal(
                "Не удалось открыть окно",
                f"Ни pywebview, ни окно-приложение Edge/Chrome не запустились.\n\n"
                f"Резервный вариант: {note}\n\n"
                f"Приложение работает — откройте вручную: {url}",
                window=True,
            )
        LOG.info(f"✅ {note}. Закройте окно, чтобы завершить программу.")
        wait_until_window_closed(process, window)
        LOG.info("Окно закрыто — завершаю работу.")
        return EXIT_OK
    finally:
        if static.owned:
            static.stop()
        if backend.owned:
            backend.stop()
        LOG.info("Прототип «План-Факт» (вариант А) завершён.")
        # Лог здесь НЕ закрываем: сообщение о непредвиденной ошибке пишется уже
        # в __main__ (иначе traceback уходил бы в закрытый файл).


def hard_exit(code: int) -> None:
    """Принудительный выход с нужным кодом.

    os._exit() на Windows вызывает ExitProcess → DLL_PROCESS_DETACH → завершение
    CLR, а у pythonnet в этом месте может падать финализатор («GIL must always be
    released»), из-за чего код возврата подменяется на код .NET-исключения
    (0xE0434352). TerminateProcess завершает процесс сразу, без detach-путей.
    """
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), int(code))
    except Exception:  # noqa: BLE001
        pass
    os._exit(int(code))


if __name__ == "__main__":
    # Гарантируем код возврата: см. hard_exit().
    try:
        _code = main()
    except KeyboardInterrupt:
        _code = EXIT_OK
    except Exception:  # noqa: BLE001
        import traceback

        _text = traceback.format_exc()
        LOG.info("❌ Непредвиденная ошибка launcher.py:\n" + _text)
        show_message_box(f"{APP_TITLE} — непредвиденная ошибка", _text)
        _code = EXIT_ERROR
    for _stream in (sys.stdout, sys.stderr):
        try:
            if _stream is not None:
                _stream.flush()
        except Exception:  # noqa: BLE001
            pass
    LOG.close()
    hard_exit(_code)
