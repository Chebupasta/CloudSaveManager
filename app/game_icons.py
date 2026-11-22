"""
Иконки игр: автоопределение и загрузка.

Порядок поиска автоматически:
  1) Steam App ID — из пресета, из манифеста Steam (appmanifest_*.acf рядом с
     установленной игрой) или поиском по названию в магазине Steam;
     по нему скачивается картинка из Steam CDN (библиотечная обложка или header);
  2) иконка из самого .exe-файла игры (средствами Qt);
  3) иначе — векторная иконка-геймпад по умолчанию (рисуется в интерфейсе).

Пользователь всегда может выбрать свою картинку с компьютера.
"""
import glob
import os
import re
import shutil
from functools import lru_cache
from typing import Optional

import requests
from PyQt5.QtCore import QFileInfo, Qt, QRectF
from PyQt5.QtGui import QPixmap, QPainter, QPainterPath
from PyQt5.QtWidgets import QFileIconProvider

from app import presets
from app.constants import get_app_dir
from app.logger import log_action

TIMEOUT = 12
STEAM_CDN = 'https://cdn.cloudflare.steamstatic.com/steam/apps/{id}/{name}'
# Порядок: вертикальная обложка библиотеки, затем горизонтальная шапка (есть у всех игр)
STEAM_ART = ('library_600x900.jpg', 'header.jpg', 'capsule_231x87.jpg')
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.ico', '.svg')


def icons_dir() -> str:
    path = os.path.join(get_app_dir(), 'icons')
    os.makedirs(path, exist_ok=True)
    return path


def _normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9а-яё]+', '', (text or '').lower())


# ---------- Steam ----------

def app_id_from_manifest(exe_path: str) -> Optional[str]:
    """Если игра установлена через Steam (…/steamapps/common/<Папка>/…), ищет
    её appmanifest_<id>.acf по имени папки установки и возвращает App ID."""
    if not exe_path:
        return None
    norm = os.path.normpath(exe_path)
    parts = norm.split(os.sep)
    lowered = [p.lower() for p in parts]
    if 'steamapps' not in lowered:
        return None
    idx = lowered.index('steamapps')
    if idx + 2 >= len(parts) or lowered[idx + 1] != 'common':
        return None
    install_dir = parts[idx + 2]
    steamapps = os.sep.join(parts[:idx + 1]) or os.sep
    for manifest in glob.glob(os.path.join(steamapps, 'appmanifest_*.acf')):
        try:
            with open(manifest, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        except OSError:
            continue
        m_dir = re.search(r'"installdir"\s+"([^"]+)"', text)
        m_id = re.search(r'"appid"\s+"(\d+)"', text)
        if m_dir and m_id and m_dir.group(1).lower() == install_dir.lower():
            return m_id.group(1)
    return None


def app_id_from_preset(process_names) -> Optional[str]:
    wanted = {p.lower() for p in process_names or [] if p}
    for preset in presets.PRESETS.values():
        if wanted & {p.lower() for p in preset.process_names}:
            for slot in preset.slots:
                if slot.steam_app_id:
                    return slot.steam_app_id
    return None


def app_id_by_name(name: str) -> Optional[str]:
    """Поиск игры по названию в магазине Steam (публичный API, без ключа).
    Принимаем только достаточно близкое совпадение, чтобы не подставить чужую игру."""
    name = (name or '').strip()
    if not name:
        return None
    try:
        r = requests.get('https://store.steampowered.com/api/storesearch/',
                         params={'term': name, 'l': 'english', 'cc': 'us'}, timeout=TIMEOUT)
        items = r.json().get('items', []) if r.status_code == 200 else []
    except (requests.RequestException, ValueError):
        return None
    target = _normalize(name)
    for item in items:
        if _normalize(item.get('name', '')) == target:
            return str(item['id'])
    for item in items:
        cand = _normalize(item.get('name', ''))
        if target and cand and (target in cand or cand in target) and abs(len(cand) - len(target)) <= 8:
            return str(item['id'])
    return None


def download_steam_art(app_id: str, game_id: str) -> str:
    """Скачивает арт игры из Steam CDN в папку иконок. Возвращает путь или ''."""
    for art in STEAM_ART:
        try:
            r = requests.get(STEAM_CDN.format(id=app_id, name=art), timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code == 200 and r.content and r.headers.get('Content-Type', '').startswith('image'):
            dest = os.path.join(icons_dir(), f'{game_id}.jpg')
            try:
                with open(dest, 'wb') as f:
                    f.write(r.content)
            except OSError:
                return ''
            return dest
    return ''


def find_icon_online(game_id: str, name: str, exe_path: str, process_names) -> str:
    """Весь онлайн-поиск (вызывается из фонового потока — без Qt-GUI)."""
    from app import manifest
    app_id = (app_id_from_preset(process_names) or app_id_from_manifest(exe_path)
              or manifest.steam_id_for({name}) or app_id_by_name(name))
    if not app_id:
        log_action('icon', 'no_steam_id', name)
        return ''
    path = download_steam_art(app_id, game_id)
    log_action('icon', 'steam_art' if path else 'steam_art_fail', f'{name} app_id={app_id}')
    return path


# ---------- иконка из .exe и пользовательские файлы (GUI-поток) ----------

def extract_exe_icon(exe_path: str, game_id: str) -> str:
    """Достаёт иконку из .exe средствами Qt. Только из GUI-потока."""
    if not exe_path or not os.path.isfile(exe_path):
        return ''
    icon = QFileIconProvider().icon(QFileInfo(exe_path))
    if icon.isNull():
        return ''
    pm = icon.pixmap(256, 256)
    if pm.isNull():
        return ''
    dest = os.path.join(icons_dir(), f'{game_id}.png')
    return dest if pm.save(dest, 'PNG') else ''


def import_custom_image(src: str, game_id: str) -> str:
    """Копирует выбранную пользователем картинку в папку иконок приложения."""
    ext = os.path.splitext(src)[1].lower()
    if ext not in IMAGE_EXTS or not os.path.isfile(src):
        return ''
    for old in glob.glob(os.path.join(icons_dir(), f'{game_id}.*')):
        if os.path.abspath(old) != os.path.abspath(src):
            try:
                os.remove(old)
            except OSError:
                pass
    dest = os.path.join(icons_dir(), f'{game_id}{ext}')
    try:
        shutil.copy2(src, dest)
    except OSError:
        return ''
    return dest


def _load_square_pixmap_uncached(path: str, size: int, radius_ratio: float = 0.18) -> Optional[QPixmap]:
    """Загружает картинку, обрезает до квадрата по центру и скругляет углы."""
    if not path or not os.path.isfile(path):
        return None
    src = QPixmap(path)
    if src.isNull():
        return None
    scale = 2
    side = size * scale
    scaled = src.scaled(side, side, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = (scaled.width() - side) // 2
    y = (scaled.height() - side) // 2
    cropped = scaled.copy(x, y, side, side)
    out = QPixmap(side, side)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, side, side), side * radius_ratio, side * radius_ratio)
    p.setClipPath(clip)
    p.drawPixmap(0, 0, cropped)
    p.end()
    out.setDevicePixelRatio(scale)
    return out


def _load_fit_pixmap_uncached(path: str, box_h: int, max_w: int, radius: int = 14,
                              dpr: float = 2.0) -> Optional[QPixmap]:
    """Обложка с сохранением пропорций: вписывается в max_w x box_h, без обрезки
    и без искусственного увеличения маленьких картинок. Скругляется по границам
    самого изображения."""
    if not path or not os.path.isfile(path):
        return None
    src = QPixmap(path)
    if src.isNull():
        return None
    w, h = src.width(), src.height()
    # масштаб в логических пикселях: вписываем в рамку, но не увеличиваем сверх оригинала
    scale = min(box_h / h, max_w / w, 1.0)
    lw, lh = max(1, round(w * scale)), max(1, round(h * scale))
    pw, ph = int(lw * dpr), int(lh * dpr)
    scaled = src.scaled(pw, ph, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out = QPixmap(pw, ph)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, pw, ph), radius * dpr, radius * dpr)
    p.setClipPath(clip)
    p.drawPixmap(0, 0, scaled)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


@lru_cache(maxsize=96)
def _square_cached(path: str, size: int, radius_ratio: float, mtime_ns: int) -> Optional[QPixmap]:
    return _load_square_pixmap_uncached(path, size, radius_ratio)


@lru_cache(maxsize=96)
def _fit_cached(path: str, box_h: int, max_w: int, radius: int, dpr: float,
                mtime_ns: int) -> Optional[QPixmap]:
    return _load_fit_pixmap_uncached(path, box_h, max_w, radius, dpr)


def _mtime_ns(path: str) -> int:
    """Время изменения файла входит в ключ кэша: замену картинки на диске
    программа подхватит без перезапуска."""
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return -1


def load_square_pixmap(path: str, size: int, radius_ratio: float = 0.18) -> Optional[QPixmap]:
    """Квадратная иконка с кэшем — файл читается и масштабируется один раз."""
    if not path or not os.path.isfile(path):
        return None
    return _square_cached(path, size, radius_ratio, _mtime_ns(path))


def load_fit_pixmap(path: str, box_h: int, max_w: int, radius: int = 14,
                    dpr: float = 2.0) -> Optional[QPixmap]:
    """Обложка с кэшем: перерисовка карточек слота больше не читает файл
    и не делает SmoothTransformation каждый раз."""
    if not path or not os.path.isfile(path):
        return None
    return _fit_cached(path, box_h, max_w, radius, dpr, _mtime_ns(path))
