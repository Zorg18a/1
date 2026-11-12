#!/usr/bin/env python3
"""GameSweep — находит старые версии игр в библиотеке и отправляет их в Корзину.
Реализовано по SPEC.md. Только стандартная библиотека. Окно — в браузере (127.0.0.1).

  python gamesweep.py [--root G:\\PG] [--port 8765] [--no-browser]
  python gamesweep.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from storage import game_scan

APP, VERSION = "GameSweep", "1.1"
IS_WIN = os.name == "nt"

# ===========================================================================
#  1. Что считается игрой (SPEC §2)
# ===========================================================================
ARCH = (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz")
_tree_stats = game_scan.tree_stats
list_games = game_scan.list_games


def scan_library(root: str, layout: str = "auto", progress=None, workers: int = 4) -> list[dict]:
    games = list_games(root, layout)

    def fill(g):
        try:
            if g["type"] == "folder":
                g["size"], g["mtime"] = _tree_stats(g["path"])
            else:
                st = os.stat(g["path"])
                g["size"], g["mtime"] = st.st_size, st.st_mtime
        except OSError:
            g["size"], g["mtime"] = 0, 0.0
        if progress:
            progress()
        return g

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fill, games))


# ===========================================================================
#  2. Название и версия из имени (SPEC §3)
# ===========================================================================
JUNK = set("win windows pc x64 x86 linux mac macos android apk public release final full rus eng multi "
           "setup portable".split())
NA, NB = r"(?<![^\W_])", r"(?![^\W_])"                    # «не буква/цифра рядом» (подчёркивание — разделитель)
COPY = re.compile(r"(?i)\(\s*\d+\s*\)|\(\s*(?:copy|копия)\s*\d*\s*\)|" + NA + r"(?:copy|копия)\s*\d*" + NB)
DOTTED = re.compile(r"(?i)" + NA + r"(?:ver(?:sion)?\.?\s*|v\s*)?(\d+(?:\.\d+)+)([a-z]?)" + NB)
V_ONLY = re.compile(r"(?i)" + NA + r"v\s*(\d+)([a-z]?)" + NB)
CHAPTER = re.compile(r"(?i)" + NA + r"(?:ch(?:apter)?|ep(?:isode)?)\.?\s*(\d+)" + NB)


def parse_name(name: str) -> dict:
    """{'base','key','nums','suffix','text','kind'}; nums=None, если версии в имени нет."""
    label = name
    for ext in ARCH:
        if label.lower().endswith(ext):
            label = label[:-len(ext)]
            break
    nums, suffix, text, kind, m = None, "", "", None, None
    ms = list(DOTTED.finditer(label)) or list(V_ONLY.finditer(label))
    if ms:
        m = ms[-1]                                          # последнее: «Game 2 v1.0» — двойка часть названия
        nums, suffix, kind = tuple(int(x) for x in m.group(1).split(".")), m.group(2).lower(), "v"
        text = m.group(1) + suffix
    else:
        ms = list(CHAPTER.finditer(label))
        if ms:
            m = ms[-1]
            nums, kind, text = (int(m.group(1)),), "ch", "Ch." + m.group(1)
    rest = label if m is None else label[:m.start()] + " " + label[m.end():]
    tokens = [t for t in re.split(r"[\W_]+", COPY.sub(" ", rest)) if t and t.lower() not in JUNK]
    return {"base": " ".join(tokens), "key": "".join(tokens).casefold(),
            "nums": nums, "suffix": suffix, "text": text, "kind": kind}


# ===========================================================================
#  3. Группы и решения (SPEC §4)
# ===========================================================================
def _vkey(m: dict, width: int):
    return tuple(m["nums"]) + (0,) * (width - len(m["nums"])), m["suffix"]


def _ambiguous(a: str, b: str) -> bool:
    """0.9 и 0.10: как числа 10 > 9, как дроби 0.10 < 0.9. Целые (v2/v10) не спорные."""
    pa, pb = re.sub(r"[a-z]$", "", a).split("."), re.sub(r"[a-z]$", "", b).split(".")
    for i, (x, y) in enumerate(zip(pa, pb)):
        if x != y:
            if i == 0:
                return False
            n = max(len(x), len(y))
            return (int(x) > int(y)) != (x.ljust(n, "0") > y.ljust(n, "0"))
    return False


def _row(m: dict, status: str, reason: str) -> dict:
    ver = ("v" + m["text"]) if m["kind"] == "v" else (m["text"] or "—")
    return {"path": m["path"], "name": m["name"], "type": m["type"], "size": m["size"], "mtime": m["mtime"],
            "version": ver, "status": status, "reason": reason}


def build_groups(games: list[dict]) -> list[dict]:
    buckets: dict[str, list] = {}
    for g in games:
        m = {**g, **parse_name(g["name"])}
        if m["key"]:
            buckets.setdefault(m["key"], []).append(m)
    groups = []
    for key, ms in buckets.items():
        if len(ms) < 2:
            continue
        grp = _group_by_version(ms) or _group_by_date(ms)
        if grp:
            grp["key"] = key
            grp["free"] = sum(r["size"] for r in grp["members"] if r["status"] in ("старая", "дубль"))
            groups.append(grp)
    groups.sort(key=lambda g: g["title"].casefold())
    return groups


def _group_by_version(ms):
    dominant = "v" if any(m["kind"] == "v" for m in ms) else "ch"
    comp = [m for m in ms if m["kind"] == dominant]
    if len({(m["nums"], m["suffix"]) for m in comp}) < 2:
        return None
    w = max(len(m["nums"]) for m in comp)
    comp.sort(key=lambda m: _vkey(m, w), reverse=True)
    top_key = _vkey(comp[0], w)
    tops = [m for m in comp if _vkey(m, w) == top_key]
    keeper = sorted(tops, key=lambda m: (m["type"] != "folder", -m["mtime"]))[0]      # папка лучше архива
    notes, sure, rows = [], True, []
    if len(tops) > 1:
        sure = False
        notes.append("новейшая версия лежит в нескольких экземплярах")
    for m in comp:
        if m is keeper:
            rows.append(_row(m, "оставить", "новейшая версия"))
        elif _vkey(m, w) == top_key:
            rows.append(_row(m, "дубль", "та же версия, что у оставляемой"))
        else:
            rows.append(_row(m, "старая", f"{m['text']} < {keeper['text']}"))
            if _ambiguous(m["text"], keeper["text"]):
                sure = False
                notes.append(f"{m['text']} и {keeper['text']}: порядок зависит от того, дробь это или число")
    for m in ms:
        if m not in comp:
            sure = False
            rows.append(_row(m, "вручную", "версия в имени не найдена или другого вида"))
    return {"title": keeper["base"], "sure": sure, "mode": "версия", "notes": notes, "members": rows}


def _group_by_date(ms):
    dated = sorted((m for m in ms if m["mtime"]), key=lambda m: -m["mtime"])
    if len(dated) < 2:
        return None
    top = dated[0]
    rows = [_row(top, "оставить", "самые свежие файлы (версию определить не удалось)")]
    for m in dated[1:]:
        days = (top["mtime"] - m["mtime"]) / 86400
        rows.append(_row(m, "старая", f"файлы старее на {int(days)} дн.") if days >= 1
                    else _row(m, "вручную", "даты почти совпадают"))
    return {"title": top["base"], "sure": False, "mode": "дата", "members": rows,
            "notes": ["версия в именах не найдена — решение по дате изменения, проверьте вручную"]}


def summary(games: list[dict], groups: list[dict]) -> dict:
    old = [r for g in groups for r in g["members"] if r["status"] in ("старая", "дубль")]
    return {"games": len(games), "groups": len(groups), "old": len(old), "free": sum(r["size"] for r in old)}


# ===========================================================================
#  4. Сохранения и Корзина (SPEC §5)
# ===========================================================================
SAVE_DIRS = {"save", "saves", "savedata", "savegame", "savegames"}
SAVE_FILE = re.compile(r"(?i)\.(rpgsave|sav|save)$|^save[\w\- ]*\.(dat|rvdata2?|rxdata|json)$")


def game_root(path: str) -> str:
    """Если папка — обёртка с единственной подпапкой, спускаемся в неё (до 3 раз)."""
    cur = path
    for _ in range(3):
        try:
            with os.scandir(cur) as it:
                ents = list(it)
        except OSError:
            break
        if len(ents) == 1 and ents[0].is_dir() and not ents[0].is_symlink():
            cur = ents[0].path
        else:
            break
    return cur


def find_saves(path: str, limit: int = 5) -> list[str]:
    top, found, stack = game_root(path), [], []
    stack.append(top)
    while stack and len(found) < limit:
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir():
                        if e.name.lower() in SAVE_DIRS and any(True for _ in os.scandir(e.path)):
                            found.append(os.path.relpath(e.path, top) + os.sep)
                        if not e.is_symlink():
                            stack.append(e.path)
                    elif SAVE_FILE.search(e.name):
                        found.append(os.path.relpath(e.path, top))
                except OSError:
                    continue
    return found


def copy_saves(src: dict, dst: dict) -> tuple[int, list[str]]:
    """Сохранения старой версии → новая (папка→папка, на то же место, существующее не перезаписываем)."""
    if src["type"] != "folder" or dst["type"] != "folder":
        return 0, ["одна из версий — архив: распакуйте её"]
    s_root, d_root = game_root(src["path"]), game_root(dst["path"])
    rels = find_saves(src["path"], limit=100000)
    dirs = [r for r in rels if r.endswith(os.sep)]
    rels = [r for r in rels if r.endswith(os.sep) or not any(r.startswith(d) for d in dirs)]
    copied, errors = 0, []
    for r in rels:
        pairs = []
        if r.endswith(os.sep):
            for cur, _d, files in os.walk(os.path.join(s_root, r)):
                pairs += [(os.path.join(cur, f), os.path.join(d_root, os.path.relpath(os.path.join(cur, f), s_root)))
                          for f in files]
        else:
            pairs.append((os.path.join(s_root, r), os.path.join(d_root, r)))
        for sf, df in pairs:
            if os.path.exists(df):
                continue
            try:
                os.makedirs(os.path.dirname(df), exist_ok=True)
                shutil.copy2(sf, df)
                copied += 1
            except OSError as e:
                errors.append(f"{os.path.basename(sf)}: {e}")
    return copied, errors


def to_trash(path: str, root: str) -> tuple[bool, str]:
    """Windows — системная Корзина (восстановимо). Иначе — _GameSweep_Trash в корне библиотеки."""
    path = os.path.abspath(path)
    if IS_WIN:
        import ctypes
        from ctypes import wintypes

        class OP(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                        ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("aborted", wintypes.BOOL),
                        ("maps", ctypes.c_void_p), ("title", wintypes.LPCWSTR)]
        op = OP(None, 3, path + "\0", None, 0x40 | 0x10 | 0x400 | 0x4, False, None, None)   # FO_DELETE + ALLOWUNDO
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return (rc == 0 and not op.aborted), ("" if rc == 0 else f"код {rc}")
    try:
        dest = Path(root) / "_GameSweep_Trash" / time.strftime("%Y%m%d_%H%M%S")
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(path, str(dest / os.path.basename(path)))
        return True, ""
    except OSError as e:
        return False, str(e)


# ===========================================================================
#  4б. Вкладки браузера против игр (SPEC §8)
# ===========================================================================
GAME_HOSTS = ("f95zone.to", "allthefallen.moe", "pornolab.net")
TAB_MARKS = {"final", "completed", "complete", "demo", "prologue", "teaser"}
_VTOK = re.compile(r"^(?:v\d+[a-z]?|(?:ch|ep)\d+)$")
_NTOK = re.compile(r"^(\d+)([a-z]?)$")
_PRE = re.compile(r"^(?:dev|alpha|beta|rc|hotfix|fix|test)\d*$")
_TITLE_BR = re.compile(r"^(?P<name>.+?)\s*\[(?P<ver>[^\]]+)\]\s*\[(?P<dev>[^\]]+)\]")
_MD = re.compile(r"^\[(.*)\]\((\S+)\)$")
_TU = re.compile(r"^(?:(.*?)\s*[\t|–—-]\s*)?(https?://\S+)$")


def _ver(nums, suffix="", kind="v", pre=False) -> dict:
    text = (".".join(str(n) for n in nums) + suffix) if kind == "v" else f"Ch.{nums[0]}"
    return {"nums": tuple(nums), "suffix": suffix, "kind": kind, "text": text, "pre": pre}


def version_of(text: str):
    p = parse_name(text)
    return None if p["nums"] is None else _ver(p["nums"], p["suffix"], p["kind"])


def slug_info(slug: str):
    """'noir-v0-1-3-bawtsforbrains' -> (['noir'], версия 0.1.3, []). Студия после версии отбрасывается."""
    toks = [t for t in slug.lower().split("-") if t]
    idx = next((i for i in range(1, len(toks)) if _VTOK.match(toks[i])), None)
    if idx is None:                                            # без «v»: два числа подряд (1-0-0)
        idx = next((i for i in range(1, len(toks) - 1) if _NTOK.match(toks[i]) and _NTOK.match(toks[i + 1])), None)
    flags = sorted(t for t in set(toks) if t in TAB_MARKS)
    if idx is None:
        return [t for t in toks if t not in TAB_MARKS], None, flags
    c, j = re.match(r"^(ch|ep)(\d+)$", toks[idx]), idx
    if c:
        ver = _ver([int(c.group(2))], kind="ch")
    else:
        m = _NTOK.match(toks[idx].lstrip("v"))
        nums, suf = [int(m.group(1))], m.group(2)
        while not suf and j + 1 < len(toks) and _NTOK.match(toks[j + 1]):
            m = _NTOK.match(toks[j + 1])
            nums.append(int(m.group(1)))
            suf = m.group(2)
            j += 1
        ver = _ver(nums, suf)
    ver["pre"] = j + 1 < len(toks) and bool(_PRE.match(toks[j + 1]))
    return toks[:idx], ver, flags


def pornolab_info(title: str):
    """Название(я) и версия из заголовка темы; блок меток не разбирается и не сохраняется."""
    t = re.sub(r"\s*::\s*PornoLab.*$", "", title).strip()
    head = re.split(r"\s*[\[(]", t, 1)[0]
    names = [a.strip() for a in head.split("/") if re.search(r"[A-Za-z]{3}", a)]
    ver = None
    for b in re.findall(r"\[([^\]]*)\]", t):
        b = b.strip()
        if re.match(r"^\d{4}\b", b):
            continue
        if re.match(r"(?i)^(v|ver\.?\s*)?\d", b):
            ver = version_of(b)
            break
    return names, ver


def analyze_tab(title: str, url: str, line: str) -> dict:
    tab = {"line": line, "url": url, "title": title, "host": "", "kind": "other", "names": [], "ver": None,
           "flags": [], "source": "", "id": ""}
    if not url.startswith("http"):
        tab["kind"] = "service"
        return tab
    p = urlparse(url)
    host = tab["host"] = p.netloc.lower().removeprefix("www.")
    if host not in GAME_HOSTS:
        return tab
    loaded = bool(title) and title != url
    if host == "pornolab.net":
        m = re.search(r"[?&]t=(\d+)", url)
        if "viewtopic" not in p.path or not m:
            tab["kind"] = "service"
            return tab
        tab.update(id=m.group(1), kind="game", source="заголовок")
        if loaded:
            tab["names"], tab["ver"] = pornolab_info(title)
        return tab
    m = re.search(r"(?:/threads/|resources/|threads/)([^/?#]+?)\.(\d+)(?:[/?#]|$)", url)
    if not m:
        tab["kind"] = "service"
        return tab
    slug, tab["id"], tab["kind"] = m.group(1), m.group(2), "game"
    tm = _TITLE_BR.match(title) if loaded else None
    if tm:
        word = tm.group("ver").strip().lower()
        tab.update(names=[tm.group("name").strip()], ver=version_of(tm.group("ver")),
                   flags=[word] if word in TAB_MARKS else [], source="заголовок")
    else:
        toks, ver, flags = slug_info(slug)
        tab.update(names=[" ".join(toks)], ver=ver, flags=flags, source="адрес")
    return tab


def parse_tabs(text: str):
    """(вкладки без дублей, сколько дублей убрано). Форматы: [заголовок](адрес), «заголовок – адрес», адрес."""
    tabs, seen, dups = [], set(), 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = _MD.match(s) or _TU.match(s)
        title, url = ((m.group(1) or "").strip(), m.group(2)) if m else (s, "")
        tab = analyze_tab(title or url, url, s)
        key = (tab["host"], tab["id"]) if tab["id"] else (url.split("#")[0] or s)
        if key in seen:
            dups += 1
            continue
        seen.add(key)
        tabs.append(tab)
    return tabs, dups


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[\W_]+", s.casefold()) if t and t not in JUNK]


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def index_locals(games: list[dict]) -> dict:
    """ключ названия -> {tokens, entries, best}; best — новейшая версия игры на ПК."""
    by_key: dict[str, dict] = {}
    for g in games:
        p = parse_name(g["name"])
        if p["key"]:
            by_key.setdefault(p["key"], {"key": p["key"], "tokens": _tokens(p["base"]), "entries": []})["entries"].append((p, g))

    def rank(e):
        p, g = e
        nums = tuple(p["nums"] or ())
        return (p["nums"] is not None, nums + (0,) * (8 - len(nums)), p["suffix"], g["mtime"])
    for loc in by_key.values():
        loc["best"] = max(loc["entries"], key=rank)
    return by_key


def match_tab(tab: dict, by_key: dict):
    """(оценка, игра, почему, слов) для лучшего совпадения или None (SPEC §8.4)."""
    best, has_v = None, tab["ver"] is not None
    for name in tab["names"]:
        T = _tokens(name)
        if not T:
            continue
        key, tset = "".join(T), set(T)
        dT = {t for t in T if t.isdigit()}
        cands = []
        if key in by_key and len(key) >= 3:
            cands.append((1.0, by_key[key], "точное совпадение", len(T)))
        else:
            for loc in by_key.values():
                L = loc["tokens"]
                Ls, dL = set(L), {t for t in L if t.isdigit()}
                if len(L) >= 2 and Ls == tset:
                    cands.append((0.9, loc, "те же слова", len(L)))
                elif len(L) >= 2 and Ls < tset:
                    if dT <= dL:                                       # лишнее число = другая часть игры
                        cands.append((0.55 if has_v else 0.8, loc, "слова игры внутри названия вкладки", len(L)))
                elif len(T) >= 2 and tset < Ls and dL <= dT:
                    cands.append((0.75, loc, "слова вкладки внутри названия игры", len(T)))
                elif len(key) >= 8 and len(loc["key"]) >= 8 and abs(len(key) - len(loc["key"])) <= 1 \
                        and _lev(key, loc["key"]) <= 1:
                    cands.append((0.7, loc, "опечатка в названии", len(T)))
        for c in cands:
            if best is None or c[0] > best[0]:
                best = c + (key,)
    return best


def tab_verdict(tab: dict, loc: dict):
    """(вердикт, уверенно) для найденной игры (SPEC §8.5)."""
    pv, (lp, _g) = tab["ver"], loc["best"]
    if not pv or lp["nums"] is None or lp["kind"] != pv["kind"]:
        return "unknown_ver", True
    w = max(len(pv["nums"]), len(lp["nums"]))
    a = _vkey({"nums": pv["nums"], "suffix": pv["suffix"]}, w)
    b = _vkey({"nums": lp["nums"], "suffix": lp["suffix"]}, w)
    if a == b:
        return "same", True
    return ("update" if b < a else "newer_pc"), not _ambiguous(pv["text"], lp["text"])


def analyze_tabs(text: str, games: list[dict]) -> dict:
    tabs, dups = parse_tabs(text)
    by_key = index_locals(games)
    out, counts = [], {}
    for t in tabs:
        r = {"line": t["line"], "url": t["url"], "title": t["title"], "host": t["host"], "kind": t["kind"],
             "name": "", "version": "", "flags": t["flags"], "source": t["source"], "verdict": "", "sure": True,
             "why": "", "local": None}
        if t["names"]:
            r["name"] = t["names"][0] if t["source"] == "заголовок" else " ".join(w.capitalize() for w in t["names"][0].split())
        if t["ver"]:
            r["version"] = ("v" + t["ver"]["text"]) if t["ver"]["kind"] == "v" else t["ver"]["text"]
        if t["kind"] == "game":
            m = match_tab(t, by_key) if t["names"] else None
            if not t["names"]:
                r.update(verdict="unparsed", why="название не удалось разобрать (нет латинского названия или заголовок не загружен)")
            elif not m:
                r.update(verdict="missing", why="похожей игры на ПК нет")
            else:
                score, loc, why, ntok, key = m
                verdict, vsure = tab_verdict(t, loc)
                lp, lg = loc["best"]
                sure_match = (score == 1.0 and len(key) >= 5) or (score in (0.9, 0.8, 0.75) and ntok >= 3)
                r.update(verdict=verdict, why=why, sure=vsure and sure_match,
                         local={"name": lg["name"], "path": lg["path"], "type": lg["type"], "count": len(loc["entries"]),
                                "version": (("v" + lp["text"]) if lp["kind"] == "v" else lp["text"]) if lp["nums"] else ""})
        if r["verdict"]:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        out.append(r)
    games_n = sum(1 for r in out if r["kind"] == "game")
    return {"tabs": out, "summary": {
        "total": len(out), "dups": dups, "games": games_n, "other": sum(1 for r in out if r["kind"] == "other"),
        "service": sum(1 for r in out if r["kind"] == "service"), "counts": counts,
        "have": counts.get("same", 0) + counts.get("newer_pc", 0) + counts.get("unknown_ver", 0), "update": counts.get("update", 0)}}


def reveal(path: str) -> bool:
    """Показать место файла: Windows — выделить в Проводнике, macOS — в Finder, Linux — открыть папку."""
    path = os.path.abspath(path)
    try:
        if IS_WIN:
            subprocess.Popen('explorer /select,"%s"' % path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
        return True
    except OSError:
        return False


# ===========================================================================
#  5. Состояние и сервер (SPEC §5.2, §5.4)
# ===========================================================================
class Store:
    def __init__(self, root=""):
        self.lock = threading.Lock()
        self.root, self.layout = root, "auto"
        self.running, self.done, self.total, self.error = False, 0, 0, ""
        self.games: list[dict] = []
        self.groups: list[dict] = []
        self.scanned = False
        self.on_done = None

    def _notify(self):
        cb = self.on_done
        if cb:
            with self.lock:
                games, root = list(self.games), self.root
            try:
                cb(games, root)
            except Exception as e:
                with self.lock: self.error = 'Синхронизация библиотеки не завершена (возможны частичные изменения): ' + str(e)[:300]

    def rebuild(self):
        self.groups = build_groups(self.games)

    def snapshot(self) -> dict:
        with self.lock:
            d = {"root": self.root, "layout": self.layout, "running": self.running, "done": self.done,
                 "total": self.total, "error": self.error, "scanned": self.scanned}
            if self.scanned and not self.running:
                d.update(groups=self.groups, summary=summary(self.games, self.groups))
            return d

    def start_scan(self, root: str, layout: str):
        with self.lock:
            if self.running:
                return False
            self.root, self.layout, self.running, self.error = root, layout, True, ""
            self.done = self.total = 0
        threading.Thread(target=self._scan, args=(root, layout), daemon=True).start()
        return True

    def _scan(self, root, layout):
        try:
            with self.lock:
                self.total = len(list_games(root, layout))

            def tick():
                with self.lock:
                    self.done += 1
            games = scan_library(root, layout, tick)
            with self.lock:
                self.games = games
                self.rebuild()
                self.scanned = True
            self._notify()
        except Exception as e:                                   # покажем пользователю, а не молча упадём
            with self.lock:
                self.error = str(e)
        finally:
            with self.lock:
                self.running = False

    def lookup(self, paths):
        index = {m["path"]: (g, m) for g in self.groups for m in g["members"]}
        return [index.get(p) for p in paths]

    def trash(self, paths: list[str], saves_mode: str, force: bool = False) -> list[dict]:
        """Сервер сам решает, что можно удалить: клиенту не доверяем (SPEC §5.2).
        Старые версии и дубли удаляются как раньше. Актуальную версию («оставить», «вручную») можно удалить
        только с явным подтверждением force=True (человек видел предупреждение). Корзина восстановима."""
        results, removed, chosen = [], set(), set(paths)
        with self.lock:
            for p, ent in zip(paths, self.lookup(paths)):
                def fail(msg):
                    results.append({"path": p, "ok": False, "msg": msg})
                if not ent:
                    fail("нет в списке — не трогаю")
                    continue
                grp, m = ent
                if m["status"] not in ("старая", "дубль") and not force:
                    fail("не старая версия — нужно отдельное подтверждение")
                    continue
                keeper = next((x for x in grp["members"] if x["status"] == "оставить"), None)
                if not force and (not keeper or keeper["path"] == p or not os.path.exists(keeper["path"])):
                    fail("новейшая версия не найдена на диске")
                    continue
                if not os.path.exists(p):
                    fail("уже нет на диске")
                    continue
                alive = [x for x in grp["members"] if x["path"] not in chosen and os.path.exists(x["path"])]
                target = keeper if keeper in alive else (alive[0] if alive else None)   # куда переносить сохранения
                saves = find_saves(p) if m["type"] == "folder" else []
                if saves and saves_mode == "skip":
                    fail("пропущено: есть сохранения")
                    continue
                if saves and saves_mode == "copy":
                    if not target:
                        fail("некуда скопировать сохранения: не останется ни одной версии")
                        continue
                    _n, errs = copy_saves(m, target)
                    if errs:
                        fail("сохранения не скопированы: " + errs[0])
                        continue
                ok, msg = to_trash(p, self.root)
                results.append({"path": p, "ok": ok, "msg": msg})
                if ok:
                    removed.add(p)
            if removed:
                self.games = [g for g in self.games if g["path"] not in removed]
                self.rebuild()
        if removed:
            self._notify()
        return results


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self) -> bool:                                  # защита от DNS-rebinding
        return (self.headers.get("Host") or "").split(":")[0] in ("127.0.0.1", "localhost")

    def _json_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        u, srv = urlparse(self.path), self.server
        if not self._host_ok():
            return self._send(403, "{}")
        if u.path == "/":
            if parse_qs(u.query).get("t", [""])[0] != srv.token:
                return self._send(403, "Откройте адрес, напечатанный в консоли (с ?t=…)", "text/plain; charset=utf-8")
            page = PAGE.replace("__TOKEN__", srv.token)
            if parse_qs(u.query).get("theme", [""])[0] == "dark":  # тёмная тема принудительно (когда GameSweep встроен в MediaHub)
                page = page.replace('<html lang="ru">', '<html lang="ru" data-theme="dark">', 1)
            return self._send(200, page, "text/html; charset=utf-8")
        if u.path.startswith("/api/") and self.headers.get("X-Token") != srv.token:
            return self._send(403, "{}")
        if u.path == "/api/state":
            return self._send(200, json.dumps(srv.store.snapshot(), ensure_ascii=False))
        self._send(404, "{}")

    def do_POST(self):
        srv = self.server
        if not self._host_ok() or self.headers.get("X-Token") != srv.token:
            return self._send(403, "{}")
        path, body = urlparse(self.path).path, self._json_body()
        if path == "/api/scan":
            root = str(body.get("root") or "").strip()
            if not os.path.isdir(root):
                return self._send(400, json.dumps({"error": f"Папка не найдена: {root}"}, ensure_ascii=False))
            layout = body.get("layout") if body.get("layout") in game_scan.LAYOUTS else "auto"
            return self._send(200, json.dumps({"started": srv.store.start_scan(root, layout)}))
        if path == "/api/saves":
            with srv.store.lock:
                found = {p: find_saves(p) for p, ent in zip(body.get("paths", []), srv.store.lookup(body.get("paths", [])))
                         if ent and ent[1]["type"] == "folder"}
            return self._send(200, json.dumps({p: v for p, v in found.items() if v}, ensure_ascii=False))
        if path == "/api/tabs":
            st = srv.store
            with st.lock:
                ready, games = st.scanned and not st.running, list(st.games)
            if not ready:
                return self._send(409, json.dumps({"error": "Сначала просканируйте папку с играми (раздел «Версии»)."}, ensure_ascii=False))
            return self._send(200, json.dumps(analyze_tabs(str(body.get("text", ""))[:5_000_000], games), ensure_ascii=False))
        if path == "/api/trash":
            mode = body.get("saves") if body.get("saves") in ("copy", "ignore", "skip") else "skip"
            res = srv.store.trash([str(p) for p in body.get("paths", [])], mode, bool(body.get("force")))
            return self._send(200, json.dumps({"results": res, "state": srv.store.snapshot()}, ensure_ascii=False))
        if path == "/api/reveal":                       # двойной щелчок по строке: показать место в проводнике
            p = str(body.get("path") or "")
            with srv.store.lock:
                known = p in {x["path"] for x in srv.store.games}
            return self._send(200, json.dumps({"ok": bool(known and os.path.exists(p) and reveal(p))}))
        self._send(404, "{}")


def make_server(root: str = "", port: int = 0):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.token, httpd.store = secrets.token_urlsafe(16), Store(root)
    return httpd


# ===========================================================================
#  6. Страница (SPEC §6)
# ===========================================================================
PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GameSweep</title>
<style>
:root{--bg:#f4f5f7;--card:#fff;--line:#d8dce3;--text:#1f2933;--muted:#6b7785;--accent:#2563eb;--ok:#0a7a0a;--okb:#e3f4e3;
--old:#b3261e;--oldb:#fdecea;--dup:#8a5a00;--dupb:#fdf1d8;--man:#555;--manb:#e8eaee;--sel:#eaf1ff;--mark:#ffe58a}
@media(prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1c2026;--line:#2d333c;--text:#e6e9ee;--muted:#8b96a5;--accent:#6b9bff;
--ok:#6fd36f;--okb:#17301b;--old:#ff8a80;--oldb:#3a1d1b;--dup:#f0c060;--dupb:#3a2f14;--man:#b5bcc7;--manb:#2a2f37;--sel:#1f2d4a;--mark:#6b5a10}}
:root[data-theme=dark]{--bg:#0d0f14;--card:#151821;--line:#262b3a;--text:#e9ebf3;--muted:#8f96ab;--accent:#f2b84b;
--ok:#6fd36f;--okb:#17301b;--old:#ff8a80;--oldb:#3a1d1b;--dup:#f0c060;--dupb:#3a2f14;--man:#b5bcc7;--manb:#232838;--sel:#232a3d;--mark:#6b5a10;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.4 "Segoe UI",system-ui,sans-serif}
header.top{display:flex;gap:8px;align-items:center;padding:12px 16px;position:sticky;top:0;background:var(--bg);z-index:5;flex-wrap:wrap}
h1{font-size:16px;margin:0 8px 0 0}input,select,button{font:inherit;color:inherit}
input[type=text],select{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:7px 10px}
#root{flex:1;min-width:220px}button{border:0;border-radius:8px;padding:7px 14px;background:var(--line);cursor:pointer}
button:hover{filter:brightness(.95)}button.primary{background:var(--accent);color:#fff;font-weight:600}
button.danger{background:var(--oldb);color:var(--old);font-weight:600}button:disabled{opacity:.45;cursor:default}
.bar{height:4px;background:var(--line);margin:0 16px;border-radius:2px;overflow:hidden}#prog{height:100%;width:0;background:var(--accent);transition:width .2s}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;padding:12px 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.card small{color:var(--muted)}.card b{display:block;font-size:22px}.card.free b{color:var(--accent)}
.tools{display:flex;gap:8px;align-items:center;padding:0 16px 10px;flex-wrap:wrap}
#q{width:340px}.chip{border:1px solid var(--line);background:var(--card);border-radius:16px;padding:4px 12px;cursor:pointer;user-select:none}
.chip.on{background:var(--sel);border-color:var(--accent);color:var(--accent)}.muted{color:var(--muted)}
.layout{display:grid;grid-template-columns:1fr 320px;gap:12px;padding:0 16px 80px}
#list{min-width:0}.grp{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:10px;overflow:hidden}
.gh{display:flex;gap:10px;align-items:center;padding:8px 12px;background:var(--bg);cursor:pointer;border-bottom:1px solid var(--line)}
.gh b{font-size:14px}.gh .sp{flex:1}.tag{font-size:11px;padding:1px 7px;border-radius:10px;background:var(--dupb);color:var(--dup)}
.row{display:grid;grid-template-columns:26px 92px 84px 88px 78px 1fr;gap:8px;align-items:center;padding:6px 12px;border-bottom:1px solid var(--line);cursor:pointer}
.row:last-child{border:0}.row:hover{background:var(--sel)}.row.cur{background:var(--sel);outline:1px solid var(--accent);outline-offset:-1px}
.badge{font-size:12px;padding:2px 8px;border-radius:10px;text-align:center}
.s-оставить{background:var(--okb);color:var(--ok)}.s-старая{background:var(--oldb);color:var(--old)}
.s-дубль{background:var(--dupb);color:var(--dup)}.s-вручную{background:var(--manb);color:var(--man)}
.nm{min-width:0}.nm div{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.nm .p{font-size:12px;color:var(--muted)}
mark{background:var(--mark);color:inherit;border-radius:3px}
aside{position:sticky;top:76px;align-self:start;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;max-height:70vh;overflow:auto}
aside h3{margin:0 0 8px;font-size:14px}aside dl{margin:0;display:grid;grid-template-columns:90px 1fr;gap:4px 8px}aside dt{color:var(--muted)}aside dd{margin:0;word-break:break-all}
.empty{padding:60px 20px;text-align:center;color:var(--muted)}
footer{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px;display:flex;gap:12px;align-items:center}
footer .sp{flex:1}dialog{border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--text);max-width:560px;width:92%}
dialog::backdrop{background:#0006}dialog pre{white-space:pre-wrap;max-height:200px;overflow:auto;background:var(--bg);padding:8px;border-radius:8px;font-size:12px}
dialog label{display:block;margin:6px 0}.err{color:var(--old);padding:0 16px}
.keepck{accent-color:var(--old)}.warnbox{margin:10px 0;padding:8px 12px;border:1px solid var(--old);border-radius:8px;background:var(--oldb)}.warnbox pre{margin:6px 0}
@media(max-width:900px){.layout{grid-template-columns:1fr}aside{display:none}.cards{grid-template-columns:repeat(2,1fr)}}
nav{display:flex;gap:4px;margin-right:8px}.nav{background:transparent;border-radius:8px;padding:6px 14px;font-weight:600;color:var(--muted)}
.nav.on{background:var(--sel);color:var(--accent)}.btnlike{display:inline-block;background:var(--accent);color:#fff;font-weight:600;border-radius:8px;padding:7px 14px;cursor:pointer}
.trow{display:grid;grid-template-columns:150px 1.3fr 1fr 28px;gap:10px;align-items:center;padding:7px 12px;border-bottom:1px solid var(--line);cursor:pointer}
.trow:last-child{border:0}.trow:hover,.trow.cur{background:var(--sel)}
.v-ok{background:var(--okb);color:var(--ok)}.v-upd{background:var(--dupb);color:var(--dup);font-weight:600}.v-man{background:var(--manb);color:var(--man)}.v-none{background:var(--sel);color:var(--accent)}
.site{font-size:11px;padding:1px 6px;border:1px solid var(--line);border-radius:6px;color:var(--muted);margin-left:6px}
#tlist .grp{margin-bottom:10px}textarea{width:100%;background:var(--card);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px;font:12px monospace}
</style></head><body>
<header class="top"><h1>🧹 GameSweep</h1><nav><button class="nav on" data-v="v">Версии</button><button class="nav" data-v="t">Вкладки</button></nav>
<input type="text" id="root" placeholder="Папка с играми, например G:\PG">
<select id="layout" aria-label="Структура папок игр"><option value="auto">Авто (new1 и т. п.)</option><option value="flat">Корень → игра</option><option value="nested">Корень → категория → игра</option><option value="nested2">Корень → категория → подпапка → игра</option></select>
<button class="primary" id="scan">Сканировать</button></header>
<p class="muted" style="margin:8px 16px">Выберите точный уровень папок игр; внутренние папки игры не должны становиться отдельными играми. Проверяйте найденные пути до удаления. Для автоматического запуска задайте структуру в настройках MediaHub.</p><div class="bar"><div id="prog"></div></div><div class="err" id="err"></div>
<div id="vv"><div class="cards"><div class="card"><small>Игр в библиотеке</small><b id="c1">—</b></div><div class="card"><small>Игр с несколькими версиями</small><b id="c2">—</b></div>
<div class="card"><small>Старых версий</small><b id="c3">—</b></div><div class="card free"><small>Можно освободить</small><b id="c4">—</b></div></div>
<div class="tools"><input type="text" id="q" placeholder="Поиск: слова, -исключить, >500мб   ( / )" autocomplete="off"><button id="qx" title="Очистить (Esc)">✕</button>
<span class="chip" data-c="old">Только старые</span><span class="chip" data-c="sure">Только уверенные</span><span class="chip" data-c="keep">Скрыть оставляемые</span>
<select id="sort"><option value="name">Порядок: по названию</option><option value="free">Больше места сначала</option><option value="new">Новые сначала</option><option value="sure">Уверенные сначала</option></select>
<span class="muted" id="count"></span></div>
<div class="layout"><div id="list"><div class="empty">Укажите папку и нажмите «Сканировать».</div></div>
<aside id="detail"><h3>Подробности</h3><div class="muted">Выберите строку.</div></aside></div>
<footer><button id="selOld">Все старые</button><button id="selSure">Старые в уверенных</button><button id="selNone">Снять</button>
<span class="sp muted" id="selinfo">Ничего не выбрано</span><button class="danger" id="trash" disabled>В Корзину…</button></footer>
</div>
<div id="tv" hidden>
<div class="cards"><div class="card"><small>Вкладок (без дублей)</small><b id="t1">—</b></div><div class="card"><small>Игровых</small><b id="t2">—</b></div>
<div class="card"><small>Уже есть на ПК</small><b id="t3">—</b></div><div class="card free"><small>Нужно обновить</small><b id="t4">—</b></div></div>
<div class="tools"><label class="btnlike">📂 Выбрать файл со вкладками<input type="file" id="tfile" accept=".txt,.md,.csv,.html,text/*" hidden></label>
<button id="tpaste">Вставить текст…</button><span class="muted" id="tname">Нужен выполненный скан папки. Форматы: [заголовок](ссылка), «заголовок – ссылка», ссылка.</span></div>
<div class="tools" id="ttools" hidden><input type="text" id="tq" placeholder="Поиск по вкладкам и играм   ( / )" autocomplete="off" style="width:340px"><button id="tqx">✕</button>
<span class="chip" data-t="close">Можно закрыть</span><span class="chip" data-t="update">Обновить</span><span class="chip" data-t="missing">Нет на ПК</span>
<span class="chip" data-t="unsure">Не уверен</span><span class="chip" data-t="other">Показать прочее</span>
<select id="tsort"><option value="verdict">Порядок: по вердикту</option><option value="name">По названию</option><option value="site">По сайту</option></select><span class="muted" id="tcount"></span></div>
<div class="layout"><div id="tlist"><div class="empty">Выберите файл со вкладками — здесь появится сравнение с играми на ПК.</div></div>
<aside id="tdetail"><h3>Подробности</h3><div class="muted">Выберите строку.</div></aside></div>
<footer><button id="eClose" disabled>Ссылки для закрытия</button><button id="eUpd" disabled>Список на обновление</button><button id="eKeep" disabled>Вкладки, которые остаются</button>
<span class="sp muted" id="tmsg">Приложение ничего не открывает и не закрывает само: списки копируются и сохраняются в файл.</span></footer>
</div>
<dialog id="pdlg"><h3>Вставьте вкладки</h3><textarea id="ptext" rows="12" placeholder="[Заголовок](https://…) — по строке на вкладку"></textarea>
<div style="text-align:right;margin-top:12px"><button id="pno">Отмена</button> <button class="primary" id="pyes">Сравнить</button></div></dialog>

<dialog id="dlg"><div id="dbody"></div><div style="text-align:right;margin-top:12px"><button id="dno">Отмена</button> <button class="danger" id="dyes">Отправить в Корзину</button></div></dialog>

<script id="searchlib">
const norm = s => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
const RU = "йцукенгшщзфывапролдячсмить", EN = "qwertyuiopasdfghjklzxcvbnm", LAY = {};
for (let i = 0; i < RU.length; i++) { LAY[RU[i]] = EN[i]; LAY[EN[i]] = RU[i]; }
const UNIT = {"б":1,b:1,"кб":1024,kb:1024,k:1024,"мб":1048576,mb:1048576,m:1048576,"гб":1073741824,gb:1073741824,g:1073741824};
function parseQuery(q) {
  const pq = {terms: [], raw: [], nots: [], sizes: [], any: false};
  for (const tok of q.trim().split(/\s+/).filter(Boolean)) {
    const m = tok.match(/^([<>])(\d+(?:[.,]\d+)?)\s*(б|кб|мб|гб|b|kb|mb|gb|k|m|g)?$/i);
    if (m) pq.sizes.push([m[1], parseFloat(m[2].replace(",", ".")) * UNIT[(m[3] || "мб").toLowerCase()]]);
    else if (tok[0] === "-" && tok.length > 1) { const n = norm(tok.slice(1)); if (n) pq.nots.push(n); }
    else if (norm(tok)) { pq.terms.push(norm(tok)); pq.raw.push(tok.toLowerCase()); }
  }
  pq.any = !!(pq.terms.length || pq.nots.length || pq.sizes.length);
  return pq;
}
function lev(a, b) {
  if (a === b) return 0; if (!a.length) return b.length; if (!b.length) return a.length;
  let prev = Array.from({length: b.length + 1}, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) cur[j] = Math.min(cur[j-1] + 1, prev[j] + 1, prev[j-1] + (a[i-1] !== b[j-1] ? 1 : 0));
    prev = cur;
  }
  return prev[b.length];
}
function termIn(t, text, compact, words) {
  if (text.includes(t) || compact.includes(t.replace(/ /g, ""))) return true;
  const sw = [...t].map(c => LAY[c] || c).join(""); // другая раскладка
  if (sw !== t && text.includes(sw)) return true;
  if (/^\p{L}{4,}$/u.test(t)) {                                                    // опечатка; цифры — только точно
    const tol = t.length <= 6 ? 1 : 2;
    return words.some(w => Math.abs(w.length - t.length) <= tol && lev(t, w) <= tol);
  }
  return false;
}
function accepts(pq, text, size) {
  const n = norm(text), compact = n.replace(/ /g, ""), words = n.split(" ");
  if (pq.nots.some(x => n.includes(x) || compact.includes(x.replace(/ /g, "")))) return false;
  if (!pq.terms.every(t => termIn(t, n, compact, words))) return false;
  return pq.sizes.every(([op, v]) => size != null && (op === ">" ? size > v : size < v));
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function highlight(text, pq) {            // подсвечиваем только прямые вхождения слов запроса
  const low = text.toLowerCase(), r = [];
  for (const t of pq.raw) { let i = low.indexOf(t); while (t && i >= 0) { r.push([i, i + t.length]); i = low.indexOf(t, i + t.length); } }
  r.sort((a, b) => a[0] - b[0]);
  let out = "", pos = 0;
  for (const [s, e] of r) { if (e <= pos) continue; const st = Math.max(s, pos); out += esc(text.slice(pos, st)) + "<mark>" + esc(text.slice(st, e)) + "</mark>"; pos = e; }
  return out + esc(text.slice(pos));
}
</script>
<script>
const TOKEN = "__TOKEN__", $ = id => document.getElementById(id);
const S = {groups: [], summary: null, sel: new Set(), cur: null, collapsed: new Set(), chips: {old: false, sure: false, keep: false}};
const OLD = m => m.status === "старая" || m.status === "дубль";
const fmt = b => b >= 2**30 ? (b/2**30).toFixed(2) + " ГБ" : b >= 2**20 ? (b/2**20).toFixed(1) + " МБ" : b >= 1024 ? Math.round(b/1024) + " КБ" : b + " Б";
const dt = t => t ? new Date(t * 1000).toLocaleDateString("ru-RU") : "—";
async function api(path, body) {
  const r = await fetch(path, {method: body ? "POST" : "GET", headers: {"X-Token": TOKEN, "Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined});
  return r.json();
}
function rowText(g, m) { return [g.title, m.name, m.path, m.version, m.status, dt(m.mtime)].join(" "); }
function visible() {
  const pq = parseQuery($("q").value), out = [];
  for (const g of S.groups) {
    if (S.chips.sure && !g.sure) continue;
    const members = g.members.filter(m => !(S.chips.old && !OLD(m)) && !(S.chips.keep && m.status === "оставить"));
    if (!members.length || (pq.any && !members.some(m => accepts(pq, rowText(g, m), m.size)))) continue;
    out.push({g, members});
  }
  const by = $("sort").value, newest = v => Math.max(...v.g.members.map(m => m.mtime || 0));
  out.sort((a, b) => by === "free" ? b.g.free - a.g.free : by === "new" ? newest(b) - newest(a)
    : by === "sure" ? (b.g.sure - a.g.sure) || a.g.title.localeCompare(b.g.title, "ru") : a.g.title.localeCompare(b.g.title, "ru"));
  return {pq, out};
}
function render() {
  const {pq, out} = visible();
  $("count").textContent = S.groups.length ? `Групп: ${out.length} из ${S.groups.length}` : "";
  if (!out.length) { $("list").innerHTML = `<div class="empty">${S.groups.length ? "Ничего не найдено — измените запрос или снимите фильтры.<br>Подсказка: слова через пробел, «-слово» исключает, «>500мб» — по размеру." : "Групп с несколькими версиями нет — или папка ещё не просканирована."}</div>`; return footer(); }
  $("list").innerHTML = out.map(({g, members}) => {
    const closed = S.collapsed.has(g.key);
    return `<section class="grp"><div class="gh" data-k="${esc(g.key)}"><span>${closed ? "▸" : "▾"}</span><b>${highlight(g.title, pq)}</b>
      ${g.sure ? "" : '<span class="tag">проверьте вручную</span>'}<span class="sp"></span><span class="muted">${g.members.length} верс. · освободится ${fmt(g.free)}</span></div>` +
      (closed ? "" : members.map(m => `<div class="row${S.cur === m.path ? " cur" : ""}" data-p="${esc(m.path)}" data-k="${esc(g.key)}">
        <span><input type="checkbox" ${OLD(m) ? "" : 'class="keepck" title="Актуальная версия: удаление потребует отдельного подтверждения"'} ${S.sel.has(m.path) ? "checked" : ""}></span><span class="badge s-${m.status}">${m.status}</span>
        <span>${esc(m.version)}</span><span class="muted">${dt(m.mtime)}</span><span>${fmt(m.size)}</span>
        <span class="nm"><div>${highlight(m.name, pq)}</div><div class="p">${highlight(m.path, pq)}</div></span></div>`).join("")) + "</section>";
  }).join("");
  footer();
}
function members() { return S.groups.flatMap(g => g.members.map(m => ({g, m}))); }
function footer() {
  const chosen = members().filter(x => S.sel.has(x.m.path)), size = chosen.reduce((s, x) => s + x.m.size, 0), keep = chosen.filter(x => !OLD(x.m)).length;
  $("selinfo").textContent = chosen.length ? `Выбрано ${chosen.length} · освободится ${fmt(size)}${keep ? ` · актуальных: ${keep}` : ""}` : "Ничего не выбрано";
  $("trash").disabled = !chosen.length;
}
function detail(path) {
  const x = members().find(x => x.m.path === path); S.cur = path; if (!x) return;
  const {g, m} = x;
  $("detail").innerHTML = `<h3>${esc(g.title)}</h3><span class="badge s-${m.status}">${m.status}</span> <span class="muted">${esc(m.reason)}</span>
    <dl style="margin-top:10px"><dt>Версия</dt><dd>${esc(m.version)}</dd><dt>Тип</dt><dd>${m.type === "folder" ? "папка" : "архив"}</dd><dt>Размер</dt><dd>${fmt(m.size)}</dd>
    <dt>Изменено</dt><dd>${dt(m.mtime)}</dd><dt>Имя</dt><dd>${esc(m.name)}</dd><dt>Путь</dt><dd>${esc(m.path)}</dd></dl>` +
    (g.notes.length ? `<p class="muted">⚠ ${g.notes.map(esc).join("<br>⚠ ")}</p>` : "") + `<p><button id="rv">Показать в папке</button> <span class="muted">или двойной щелчок по строке</span></p>`;
  $("rv").onclick = () => reveal(m.path);
}
function setState(st) {
  $("prog").style.width = st.running && st.total ? (100 * st.done / st.total) + "%" : "0";
  $("err").textContent = st.error || ""; $("scan").disabled = st.running;
  if (st.running) return;
  if (st.scanned) {
    S.groups = st.groups; const live = new Set(members().map(x => x.m.path)); S.sel = new Set([...S.sel].filter(p => live.has(p)));
    const s = st.summary; $("c1").textContent = s.games; $("c2").textContent = s.groups; $("c3").textContent = s.old; $("c4").textContent = fmt(s.free);
    render();
  }
}
async function poll() { const st = await api("/api/state"); setState(st); if (st.running) setTimeout(poll, 350); }
$("scan").onclick = async () => {
  const root = $("root").value.trim(); localStorage.gsRoot = root; localStorage.gsLayout = $("layout").value;
  const r = await api("/api/scan", {root, layout: $("layout").value});
  if (r.error) { $("err").textContent = r.error; return; }
  S.sel.clear(); $("prog").style.width = "2%"; poll();
};
$("list").onclick = e => {
  const gh = e.target.closest(".gh"), row = e.target.closest(".row");
  if (gh) { const k = gh.dataset.k; S.collapsed.has(k) ? S.collapsed.delete(k) : S.collapsed.add(k); render(); }
  else if (row) {
    if (e.target.type === "checkbox") { e.target.checked ? S.sel.add(row.dataset.p) : S.sel.delete(row.dataset.p); footer(); detail(row.dataset.p); return; }
    const now = Date.now();                                            // двойной щелчок по строке: показать в проводнике
    if (S.lc && S.lc.p === row.dataset.p && now - S.lc.t < 450) { S.lc = null; reveal(row.dataset.p); return; }
    S.lc = {p: row.dataset.p, t: now}; detail(row.dataset.p); render();
  }
};
async function reveal(p) { const r = await api("/api/reveal", {path: p}); $("err").textContent = r.ok ? "" : "Не удалось открыть проводник (файла уже нет?)"; }
let timer; $("q").oninput = () => { clearTimeout(timer); timer = setTimeout(render, 120); };
$("qx").onclick = () => { $("q").value = ""; render(); $("q").focus(); }; $("sort").onchange = render;
document.querySelectorAll(".chip").forEach(c => c.onclick = () => { S.chips[c.dataset.c] = !S.chips[c.dataset.c]; c.classList.toggle("on"); render(); });
const pick = pred => { S.sel = new Set(members().filter(x => OLD(x.m) && pred(x.g)).map(x => x.m.path)); render(); };
$("selOld").onclick = () => pick(() => true); $("selSure").onclick = () => pick(g => g.sure); $("selNone").onclick = () => { S.sel.clear(); render(); };
document.addEventListener("keydown", e => {
  if (e.key === "/" && document.activeElement.tagName !== "INPUT") { e.preventDefault(); $("q").focus(); }
  if (e.key === "Escape") { $("q").value = ""; render(); }
});
$("trash").onclick = async () => {
  const paths = [...S.sel], saves = await api("/api/saves", {paths}), withSaves = Object.keys(saves);
  const chosen = members().filter(x => S.sel.has(x.m.path)), total = chosen.reduce((s, x) => s + x.m.size, 0), keepSel = chosen.filter(x => !OLD(x.m));
  const emptied = S.groups.filter(g => g.members.every(m => S.sel.has(m.path)));
  let html = `<h3>В Корзину: ${paths.length} шт. · ${fmt(total)}</h3><pre>${esc(paths.slice(0, 8).join("\n"))}${paths.length > 8 ? "\n… и ещё " + (paths.length - 8) : ""}</pre><p class="muted">${keepSel.length ? "" : "Новейшие версии остаются. "}Корзина — восстановимо. Сохранения в архивах не проверяются.</p>`;
  if (keepSel.length) html += `<div class="warnbox"><b>⚠ Вы выбрали актуальные версии (${keepSel.length}):</b><pre>${esc(keepSel.slice(0, 6).map(x => x.g.title + " · " + x.m.version).join("\n"))}${keepSel.length > 6 ? "\n… и ещё " + (keepSel.length - 6) : ""}</pre>${emptied.length ? `<p><b>У ${emptied.length} игр не останется ни одной версии.</b></p>` : ""}<label><input type="checkbox" id="force"> Понимаю, это актуальные версии, всё равно удалить</label></div>`;
  if (withSaves.length) html += `<p><b>⚠ Найдены сохранения (версий: ${withSaves.length}):</b></p><pre>${esc(withSaves.slice(0, 5).map(p => p.split(/[\\/]/).pop() + ": " + saves[p].slice(0, 2).join(", ")).join("\n"))}</pre>
    <label><input type="radio" name="sv" value="copy" checked> Скопировать сохранения в оставшуюся версию, затем удалить</label>
    <label><input type="radio" name="sv" value="skip"> Пропустить версии с сохранениями</label><label><input type="radio" name="sv" value="ignore"> Удалить вместе с сохранениями</label>`;
  $("dbody").innerHTML = html; $("dyes").disabled = keepSel.length > 0; $("dlg").showModal();
  if (keepSel.length) $("force").onchange = () => { $("dyes").disabled = !$("force").checked; };
  $("dno").onclick = () => $("dlg").close();
  $("dyes").onclick = async () => {
    const mode = (document.querySelector("input[name=sv]:checked") || {}).value || "skip"; $("dlg").close();
    const r = await api("/api/trash", {paths, saves: mode, force: keepSel.length > 0}), bad = r.results.filter(x => !x.ok);
    S.sel.clear(); setState(r.state);
    $("err").textContent = bad.length ? `Не тронуто: ${bad.length} — ` + bad.slice(0, 3).map(x => x.path.split(/[\\/]/).pop() + " (" + x.msg + ")").join("; ") : "";
  };
};
$("root").value = localStorage.gsRoot || ""; $("layout").value = localStorage.gsLayout || "auto";
api("/api/state").then(st => { if (!$("root").value && st.root) $("root").value = st.root; if (!localStorage.gsLayout && st.layout) $("layout").value = st.layout; setState(st); if (st.running) poll(); });
// ---------- раздел «Вкладки» (SPEC §8) ----------
const TS = {tabs: [], sum: null, cur: null, chips: {close: false, update: false, missing: false, unsure: false, other: false}};
const VL = {same: ["есть · та же версия", "v-ok"], newer_pc: ["на ПК новее", "v-ok"], update: ["обновить", "v-upd"],
  unknown_ver: ["есть · версию не сравнить", "v-man"], missing: ["нет на ПК", "v-none"], unparsed: ["не разобрано", "v-man"]};
const VORD = {update: 0, unknown_ver: 1, unparsed: 2, missing: 3, newer_pc: 4, same: 5};
const isClose = (t, sureOnly) => (t.verdict === "same" || t.verdict === "newer_pc") && (!sureOnly || t.sure);
const tabText = t => [t.name, t.title, t.host, t.url, t.version, (t.local || {}).name, (t.local || {}).path, (VL[t.verdict] || [""])[0]].join(" ");
function tabsVisible() {
  const pq = parseQuery($("tq").value), c = TS.chips, vOn = c.close || c.update || c.missing;
  const out = TS.tabs.filter(t => {
    if (t.kind !== "game") return c.other && (!pq.any || accepts(pq, tabText(t), null));
    if (vOn && !((c.close && isClose(t, false)) || (c.update && t.verdict === "update") || (c.missing && t.verdict === "missing"))) return false;
    if (c.unsure && t.sure) return false;
    return !pq.any || accepts(pq, tabText(t), null);
  });
  const by = $("tsort").value, nm = (a, b) => a.name.localeCompare(b.name, "ru");
  out.sort((a, b) => by === "name" ? nm(a, b) : by === "site" ? a.host.localeCompare(b.host) || nm(a, b)
    : ((VORD[a.verdict] ?? 9) - (VORD[b.verdict] ?? 9)) || nm(a, b));
  return {pq, out};
}
function renderTabs() {
  const {pq, out} = tabsVisible();
  $("ttools").hidden = !TS.tabs.length;
  $("tcount").textContent = TS.tabs.length ? `Показано ${out.length} из ${TS.tabs.length}` : "";
  $("tlist").innerHTML = !out.length ? `<div class="empty">${TS.tabs.length ? "Ничего не найдено — измените запрос или снимите фильтры." : "Выберите файл со вкладками — здесь появится сравнение с играми на ПК."}</div>` :
    `<section class="grp">` + out.map((t, i) => {
      const v = VL[t.verdict] || ["прочее", "v-man"], loc = t.local;
      return `<div class="trow${TS.cur === t.url ? " cur" : ""}" data-i="${TS.tabs.indexOf(t)}"><span class="badge ${v[1]}">${v[0]}</span>
        <span class="nm"><div>${highlight(t.name || t.title, pq)} <b>${esc(t.version)}</b><span class="site">${esc(t.host || "—")}</span></div><div class="p">${highlight(t.url, pq)}</div></span>
        <span class="nm">${loc ? `<div>${highlight(loc.name, pq)} <b>${esc(loc.version)}</b></div><div class="p">${highlight(loc.path, pq)}</div>` : '<span class="muted">—</span>'}</span>
        <span title="${t.sure ? "уверенно" : "не уверен"}">${t.kind === "game" && t.verdict && t.verdict !== "missing" && t.verdict !== "unparsed" ? (t.sure ? "✓" : "?") : ""}</span></div>`;
    }).join("") + "</section>";
  const s = TS.sum;
  if (s) { $("t1").textContent = s.total; $("t2").textContent = s.games; $("t3").textContent = s.have; $("t4").textContent = s.update; }
  const closeN = TS.tabs.filter(t => isClose(t, true)).length, updN = TS.tabs.filter(t => t.verdict === "update").length;
  $("eClose").textContent = `Ссылки для закрытия (${closeN})`; $("eUpd").textContent = `Список на обновление (${updN})`;
  $("eKeep").textContent = `Вкладки, которые остаются (${TS.tabs.length - closeN})`;
  ["eClose", "eUpd", "eKeep"].forEach(id => $(id).disabled = !TS.tabs.length);
}
async function loadTabs(text, name) {
  const r = await api("/api/tabs", {text});
  if (r.error) { $("tname").textContent = "⚠ " + r.error; return; }
  TS.tabs = r.tabs; TS.sum = r.summary; TS.cur = null;
  const s = r.summary;
  $("tname").textContent = `${name || "вставленный текст"}: ${s.total} вкладок` + (s.dups ? `, дублей убрано ${s.dups}` : "") + `, игровых ${s.games}, прочих ${s.other + s.service}`;
  renderTabs();
}
$("tfile").onchange = e => { const f = e.target.files[0]; if (!f) return; const rd = new FileReader(); rd.onload = () => loadTabs(String(rd.result).replace(/^\ufeff/, ""), f.name); rd.readAsText(f, "utf-8"); e.target.value = ""; };
$("tpaste").onclick = () => $("pdlg").showModal(); $("pno").onclick = () => $("pdlg").close();
$("pyes").onclick = () => { $("pdlg").close(); loadTabs($("ptext").value, ""); };
let ttimer; $("tq").oninput = () => { clearTimeout(ttimer); ttimer = setTimeout(renderTabs, 120); };
$("tqx").onclick = () => { $("tq").value = ""; renderTabs(); $("tq").focus(); }; $("tsort").onchange = renderTabs;
document.querySelectorAll(".chip[data-t]").forEach(c => c.onclick = () => { TS.chips[c.dataset.t] = !TS.chips[c.dataset.t]; c.classList.toggle("on"); renderTabs(); });
$("tlist").onclick = e => {
  const row = e.target.closest(".trow"); if (!row) return;
  const t = TS.tabs[+row.dataset.i]; TS.cur = t.url; const v = VL[t.verdict] || ["прочее", "v-man"], l = t.local;
  $("tdetail").innerHTML = `<h3>${esc(t.name || t.title)}</h3><span class="badge ${v[1]}">${v[0]}</span> <span class="muted">${esc(t.why)}</span>
    <dl style="margin-top:10px"><dt>Версия в теме</dt><dd>${esc(t.version || "—")}</dd><dt>Сайт</dt><dd>${esc(t.host || "—")}</dd><dt>Название взято</dt><dd>${esc(t.source || "—")}</dd>
    <dt>Адрес</dt><dd><a href="${esc(t.url)}" target="_blank" rel="noopener noreferrer">${esc(t.url)}</a></dd>` +
    (l ? `<dt>На ПК</dt><dd>${esc(l.name)} ${esc(l.version)}${l.count > 1 ? " (всего версий: " + l.count + ")" : ""}</dd><dt>Путь</dt><dd>${esc(l.path)}</dd>` : "") + `</dl>`;
  renderTabs();
};
function exportText(name, text, what) {
  const done = ok => { $("tmsg").textContent = `${what}: ${text ? text.split("\n").length : 0} строк — ` + (ok ? "скопировано и сохранено в файл" : "сохранено в файл"); };
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["\ufeff" + text], {type: "text/plain;charset=utf-8"})); a.download = name; a.click();
  (navigator.clipboard ? navigator.clipboard.writeText(text).then(() => done(true), () => done(false)) : Promise.resolve(done(false)));
}
const closeList = () => TS.tabs.filter(t => isClose(t, true));
$("eClose").onclick = () => exportText("tabs_to_close.txt", closeList().map(t => t.url).join("\n"), "Ссылки для закрытия");
$("eUpd").onclick = () => exportText("tabs_to_update.txt", TS.tabs.filter(t => t.verdict === "update").map(t => `${t.name} — на ПК ${t.local.version || "?"} → в теме ${t.version} — ${t.url}`).join("\n"), "Список на обновление");
$("eKeep").onclick = () => { const closed = new Set(closeList().map(t => t.url)); exportText("tabs_keep.txt", TS.tabs.filter(t => !closed.has(t.url)).map(t => t.line).join("\n"), "Вкладки, которые остаются"); };
document.querySelectorAll(".nav").forEach(b => b.onclick = () => {
  document.querySelectorAll(".nav").forEach(x => x.classList.toggle("on", x === b));
  $("vv").hidden = b.dataset.v !== "v"; $("tv").hidden = b.dataset.v !== "t";
});
</script></body></html>"""


# ===========================================================================
#  7. Самопроверка (примеры из SPEC §7)
# ===========================================================================
def selftest() -> int:
    import http.client
    import subprocess
    import tempfile

    ok_n = fail_n = 0

    def check(name, cond, extra=""):
        nonlocal ok_n, fail_n
        ok_n, fail_n = ok_n + bool(cond), fail_n + (not cond)
        print(f"  {'OK  ' if cond else 'FAIL'} {name}" + ("" if cond else f"   {extra}"))

    print("== Имена и версии (SPEC §3, §7) ==")
    table = [("Slave_Of_Passion_1.0.3_-_Win.zip", "slaveofpassion", "1.0.3"),
             ("Together_Again_1.0.3_-_Win.zip", "togetheragain", "1.0.3"),
             ("Dwarfing_Dreams_v0.2.3.1a.zip", "dwarfingdreams", "0.2.3.1a"),
             ("REC_v0.5.6.0.zip", "rec", "0.5.6.0"), ("nemurimouto_v0.10_win.zip", "nemurimouto", "0.10"),
             ("YesIamAFurry-0.2.7-pc.zip", "yesiamafurry", "0.2.7"), ("Hypno_card.zip", "hypnocard", ""),
             ("TogetherAgain v1.1.zip", "togetheragain", "1.1"), ("wife_schooooool (2).rar", "wifeschooooool", ""),
             ("Mystery Tale copy2", "mysterytale", "")]
    for name, key, ver in table:
        p = parse_name(name)
        check(f"{name} → {key} / {ver or '—'}", p["key"] == key and p["text"] == ver, str(p))
    check("«Game 2 v1.0»: двойка — часть названия", parse_name("Game 2 v1.0")["key"] == "game2")

    print("\n== Группы (SPEC §4) ==")
    mk = lambda name, mt=1.7e9, tp="archive": {"name": name, "path": "/x/" + name, "type": tp, "size": 100, "mtime": mt}
    g = build_groups([mk("ADeckOfHex-v1.15.zip"), mk("ADeckOfHex-v1.21.zip"), mk("Hypno_card.zip")])
    check("ADeckOfHex: 1.21 оставить, 1.15 старая, уверенная; Hypno_card (одна) не показана",
          len(g) == 1 and [(r["version"], r["status"]) for r in g[0]["members"]] == [("v1.21", "оставить"), ("v1.15", "старая")]
          and g[0]["sure"])
    g = build_groups([mk("Lust_Academy_v1.0"), mk("Lust_Academy_2_v1.0"), mk("Lust_Academy_2_v1.3")])
    check("Lust Academy и Lust Academy 2 — разные игры", len(g) == 1 and g[0]["title"] == "Lust Academy 2")
    g = build_groups([mk("Zephyr_v0.9"), mk("Zephyr_v0.10")])
    check("Zephyr 0.9/0.10: новее 0.10, группа неуверенная", g[0]["members"][0]["version"] == "v0.10" and not g[0]["sure"])
    g = build_groups([mk("Zephyr_v2"), mk("Zephyr_v10")])
    check("Zephyr v2/v10: новее 10, уверенно", g[0]["members"][0]["version"] == "v10" and g[0]["sure"])
    g = build_groups([mk("Game Ch.2"), mk("Game Ch.10")])
    check("главы: Ch.10 новее Ch.2", g[0]["members"][0]["version"] == "Ch.10")
    g = build_groups([mk("Foo_v1.0"), mk("Foo_v1.0 (2)"), mk("Foo_v0.5"), mk("Foo")])
    st = sorted(r["status"] for r in g[0]["members"])
    check("одна версия дважды → дубль; без версии → вручную", st == sorted(["дубль", "оставить", "старая", "вручную"]), str(st))
    g = build_groups([mk("Hypno_card.zip", 1.7e9), mk("Hypno_card (2).zip", 1.7e9 + 5 * 86400)])
    check("версий нет → по дате, неуверенно: новее (2)",
          g[0]["mode"] == "дата" and not g[0]["sure"] and g[0]["members"][0]["name"] == "Hypno_card (2).zip")
    g = build_groups([mk("Bar.zip", 1.7e9), mk("Bar (2).zip", 1.7e9 + 60)])
    check("даты почти совпадают → вручную", g[0]["members"][1]["status"] == "вручную")

    print("\n== Библиотека на диске, сохранения, Корзина (SPEC §2, §5) ==")
    tmp = tempfile.mkdtemp()
    lib = Path(tmp) / "lib"

    def put(rel, data=b"x", age_days=0):
        p = lib / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
    put("new6/ADeckOfHex-v1.15.zip", b"a" * 10)
    put("new6/ADeckOfHex-v1.21.zip", b"b" * 20)
    put("RPG v1.0/www/save/file1.rpgsave", b"OLD1")
    put("RPG v1.0/www/save/file2.rpgsave", b"OLD2")
    put("RPG v1.0/www/game.exe", b"e")
    put("RPG v1.1/www/save/file2.rpgsave", b"NEW2")
    put("RPG v1.1/www/game.exe", b"e2")
    put("Solo v1.0/a.bin")
    put(".hidden/x.bin")
    put("_GameSweep_Trash/skip.bin")
    games = scan_library(str(lib))
    names = sorted(g["name"] for g in games)
    check("auto: new6 раскрыта; скрытые и служебные пропущены",
          names == ["ADeckOfHex-v1.15.zip", "ADeckOfHex-v1.21.zip", "RPG v1.0", "RPG v1.1", "Solo v1.0"], str(names))
    check("flat: new6 — одна игра", "new6" in [g["name"] for g in list_games(str(lib), "flat")])
    check("размер папки = сумма файлов; mtime папки — самый свежий файл",
          next(g for g in games if g["name"] == "RPG v1.0")["size"] == 4 + 4 + 1)
    check("find_saves: save/ и *.rpgsave внутри обёртки", len(find_saves(str(lib / "RPG v1.0"))) >= 1
          and find_saves(str(lib / "Solo v1.0")) == [])

    httpd = make_server(str(lib))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def call(method, path, body=None, token=True, host=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        h = {"Content-Type": "application/json", "Host": host or f"127.0.0.1:{port}"}
        if token:
            h["X-Token"] = httpd.token
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        data = r.read()
        return r.status, (json.loads(data) if data.startswith(b"{") else data.decode("utf-8", "ignore"))

    check("без токена API закрыт (403), страница без ?t= закрыта", call("GET", "/api/state", token=False)[0] == 403
          and call("GET", "/")[0] == 403)
    check("чужой Host (rebinding) отклонён", call("GET", "/api/state", host="evil.com")[0] == 403)
    check("страница с токеном отдаётся", "GameSweep" in call("GET", f"/?t={httpd.token}")[1])
    check("scan: несуществующая папка → 400", call("POST", "/api/scan", {"root": "/нет/такой"})[0] == 400)
    call("POST", "/api/scan", {"root": str(lib), "layout": "auto"})
    for _ in range(100):
        st = call("GET", "/api/state")[1]
        if st["scanned"] and not st["running"]:
            break
        time.sleep(0.05)
    titles = sorted(g["title"] for g in st["groups"])
    check("API: найдены группы ADeckOfHex и RPG", titles == ["ADeckOfHex", "RPG"], str(titles))
    check("сводка: 5 игр, 2 группы, 2 старых", st["summary"]["games"] == 5 and st["summary"]["groups"] == 2 and st["summary"]["old"] == 2)
    old_deck, old_rpg = str(lib / "new6" / "ADeckOfHex-v1.15.zip"), str(lib / "RPG v1.0")
    keep_deck = str(lib / "new6" / "ADeckOfHex-v1.21.zip")
    check("trash: «оставить» и чужой путь не трогаются (SPEC §5.2)",
          not any(r["ok"] for r in call("POST", "/api/trash", {"paths": [keep_deck, "/etc/passwd"], "saves": "ignore"})[1]["results"])
          and os.path.exists(keep_deck))
    check("saves: API видит сохранения только у RPG v1.0", list(call("POST", "/api/saves", {"paths": [old_deck, old_rpg]})[1]) == [old_rpg])
    r = call("POST", "/api/trash", {"paths": [old_rpg], "saves": "skip"})[1]["results"][0]
    check("saves=skip: игра с сохранениями пропущена, на диске осталась", not r["ok"] and os.path.exists(old_rpg))
    r = call("POST", "/api/trash", {"paths": [old_rpg, old_deck], "saves": "copy"})[1]
    check("saves=copy: старые ушли в корзину", all(x["ok"] for x in r["results"]) and not os.path.exists(old_rpg) and not os.path.exists(old_deck))
    check("сохранение скопировано в новую версию, существующее не перезаписано",
          (lib / "RPG v1.1/www/save/file1.rpgsave").read_bytes() == b"OLD1"
          and (lib / "RPG v1.1/www/save/file2.rpgsave").read_bytes() == b"NEW2")
    if not IS_WIN:
        check("корзина (не Windows): файлы в _GameSweep_Trash, не удалены насовсем",
              len(list((lib / "_GameSweep_Trash").glob("*/ADeckOfHex-v1.15.zip"))) == 1)
    check("после удаления групп с несколькими версиями не осталось", r["state"]["summary"]["groups"] == 0)
    httpd.shutdown()

    print("\n== Вкладки (SPEC §8) ==")
    tb = lambda url, title=None: analyze_tab(title or url, url, url)
    F = "https://f95zone.to/threads/"
    t = tb(F + "noir-v0-1-3-bawtsforbrains.318738/")
    check("слаг: noir · 0.1.3", t["names"] == ["noir"] and t["ver"]["text"] == "0.1.3", str(t["names"]))
    t = tb(F + "beyond-worlds-university-v0-9-0a-mister-crowne.282591/")
    check("слаг: beyond worlds university · 0.9.0a", t["names"] == ["beyond worlds university"] and t["ver"]["text"] == "0.9.0a")
    t = tb(F + "dream-team-69-v0-9-0-shodo-games.271262/")
    check("слаг: dream team 69 · 0.9.0 (число в названии не версия)", t["names"] == ["dream team 69"] and t["ver"]["text"] == "0.9.0")
    t = tb("https://allthefallen.moe/forum/index.php?resources/kisaki-another-memory-1-0-0-dixy.9754/")
    check("allthefallen, версия без «v»: kisaki another memory · 1.0.0", t["names"] == ["kisaki another memory"] and t["ver"]["text"] == "1.0.0")
    t = tb(F + "beauties-of-blackfall-demo-flephouse-games.318886/")
    check("слаг без версии: пометка demo, студия остаётся в названии",
          t["ver"] is None and t["flags"] == ["demo"] and t["names"] == ["beauties of blackfall flephouse games"])
    t = tb(F + "some-game-ch2-devname.10/")
    check("слаг: глава ch2 → Ch.2", t["ver"]["text"] == "Ch.2" and t["names"] == ["some game"])
    t = tb(F + "tool-v1-4-0-dev5-someone.20/")
    check("слаг: dev5 после версии — предварительная", t["ver"]["text"] == "1.4.0" and t["ver"]["pre"])
    t = tb("https://f95zone.to/threads/x-y-v1-0-z.5/", "Real Name [v2.5] [SomeDev] | F95zone")
    check("f95: загруженный заголовок важнее слага", t["names"] == ["Real Name"] and t["ver"]["text"] == "2.5" and t["source"] == "заголовок")
    pl = "https://pornolab.net/forum/viewtopic.php?t=777"
    t = tb(pl, "ダンジョンズ / Dungeons And Cat [v1.2.40 + DLC] (Studio / Pub) [uncen] [2026, RPG, Fantasy] [rus] :: PornoLab.Net")
    check("pornolab: латинское название и версия, год/метки не версия", t["names"] == ["Dungeons And Cat"] and t["ver"]["text"] == "1.2.40")
    check("pornolab: заголовок = адрес → названия нет", tb(pl)["names"] == [] and tb(pl)["kind"] == "game")
    check("служебные и прочие: about:, каталог f95, чужой сайт",
          (tb("about:home")["kind"], tb("https://f95zone.to/sam/latest_alpha/")["kind"], tb("https://example.com/x")["kind"]) == ("service", "service", "other"))
    tabs_, dups_ = parse_tabs("[Noir](https://f95zone.to/threads/noir-v0-1-3-x.1/)\nNoir 2 – https://f95zone.to/threads/noir-v0-1-3-x.1/page-3#post-9\nhttps://example.com/a\n\nabout:blank")
    check("форматы строк и дубли по id темы: markdown, «заголовок – адрес», адрес, about:",
          len(tabs_) == 3 and dups_ == 1 and [x["kind"] for x in tabs_] == ["game", "other", "service"])
    mkg = lambda name, tp="folder": {"name": name, "path": "/lib/" + name, "type": tp, "size": 1, "mtime": 1.7e9}
    locs = [mkg("Noir v0.1.1"), mkg("Beyond Worlds University v0.9.0a"), mkg("Dream Team 69 v1.0"), mkg("Kisaki Another Memory"),
            mkg("Dungeons and Cat_v1.2.40.zip", "archive"), mkg("Lust Academy v1.0"), mkg("Beauties of Blackfall")]
    text = "\n".join([F + "noir-v0-1-3-bawtsforbrains.318738/", F + "noir-v0-1-3-bawtsforbrains.318738/page-3#post-1",
                      F + "beyond-worlds-university-v0-9-0a-mister-crowne.282591/", F + "dream-team-69-v0-9-0-shodo-games.271262/",
                      "https://allthefallen.moe/forum/index.php?resources/kisaki-another-memory-1-0-0-dixy.9754/",
                      "[Dungeons And Cat [v1.2.40 + DLC] (Studio) [uncen] [2026, RPG] [rus] :: PornoLab.Net](" + pl + "9)",
                      F + "lust-academy-2-v1-0-somedev.555/", F + "beauties-of-blackfall-demo-flephouse-games.318886/",
                      pl + "1", "about:home", "https://example.com/page"])
    res = analyze_tabs(text, locs)
    vd = {r["name"] or r["url"][-12:]: r["verdict"] for r in res["tabs"] if r["kind"] == "game"}
    want = {"Noir": "update", "Beyond Worlds University": "same", "Dream Team 69": "newer_pc", "Kisaki Another Memory": "unknown_ver",
            "Dungeons And Cat": "same", "Lust Academy 2": "missing", "Beauties Of Blackfall Flephouse Games": "unknown_ver"}
    check("вердикты §8.7: обновить / та же / на ПК новее / не сравнить / нет на ПК",
          all(vd.get(k) == v for k, v in want.items()) and sorted(vd.values()).count("unparsed") == 1, str(vd))
    sm = res["summary"]
    check("сводка: 10 вкладок, 1 дубль, 8 игровых, 1 прочая, 1 служебная, есть на ПК 5, обновить 1",
          (sm["total"], sm["dups"], sm["games"], sm["other"], sm["service"], sm["have"], sm["update"]) == (10, 1, 8, 1, 1, 5, 1), str(sm))
    byname = {r["name"]: r for r in res["tabs"] if r["kind"] == "game" and r["name"]}
    check("«Lust Academy 2» не склеена с «Lust Academy» (лишнее число)", byname["Lust Academy 2"]["local"] is None)
    check("уверенность: длинное точное — да, короткое «noir» — нет, вхождение в 3 слова — да",
          byname["Beyond Worlds University"]["sure"] and not byname["Noir"]["sure"] and byname["Beauties Of Blackfall Flephouse Games"]["sure"])
    check("у найденной игры есть путь и версия на ПК", byname["Noir"]["local"]["path"] == "/lib/Noir v0.1.1" and byname["Noir"]["local"]["version"] == "v0.1.1")
    g2 = index_locals([mkg("Noir v0.1.1"), mkg("Noir v0.3.0"), mkg("Noir v0.2.0")])
    check("несколько версий на ПК: сравнивается новейшая", tab_verdict(tb(F + "noir-v0-3-0-x.1/")["ver"] and tb(F + "noir-v0-3-0-x.1/"), g2["noir"])[0] == "same")
    check("0.9 против 0.10 в вкладках: вердикт есть, но «не уверен»",
          tab_verdict(tb(F + "zed-v0-10-x.2/"), index_locals([mkg("Zed v0.9")])["zed"]) == ("update", False))

    httpd2 = make_server("")
    port2 = httpd2.server_address[1]
    threading.Thread(target=httpd2.serve_forever, daemon=True).start()

    def post2(path, body):
        c = http.client.HTTPConnection("127.0.0.1", port2, timeout=10)
        c.request("POST", path, json.dumps(body), {"X-Token": httpd2.token, "Content-Type": "application/json", "Host": f"127.0.0.1:{port2}"})
        r = c.getresponse()
        return r.status, json.loads(r.read())
    check("API вкладок до сканирования: 409 с понятным текстом", post2("/api/tabs", {"text": "x"})[0] == 409)
    httpd2.store.games, httpd2.store.scanned = locs, True
    code2, data2 = post2("/api/tabs", {"text": text})
    check("API вкладок после сканирования: тот же результат", code2 == 200 and data2["summary"]["update"] == 1)
    httpd2.shutdown()

    print("\n== Страница: синтаксис и поиск (SPEC §6) ==")
    node = shutil.which("node")
    if not node:
        print("  --   node не найден — проверка JS пропущена")
    else:
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", PAGE, re.S)
        for i, code in enumerate(scripts):
            f = Path(tmp) / f"s{i}.js"
            f.write_text(code.replace("__TOKEN__", "t"), encoding="utf-8")
            res = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
            check(f"JS-блок {i + 1}: синтаксис", res.returncode == 0, res.stderr[:200])
        harness = scripts[0] + """
const A = (q, t, s) => accepts(parseQuery(q), t, s), N = "Slave_Of_Passion_1.0.3_-_Win.zip";
const r = [A("slaveofpassion", N), A("passion slave", N), A("pasion", N), A("ыдфму", N), !A("new6", "G:\\\\PG\\\\new7\\\\Game"),
  A("new6", "G:\\\\PG\\\\new6\\\\Game"), !A("slave -win", N), !A("slave zzzz", N), A(">1мб", N, 5*1048576), !A(">1мб", N, 100), A("1.0.3", N),
  highlight("Slave Of Passion", parseQuery("passion")) === "Slave Of <mark>Passion</mark>", highlight("a<b", parseQuery("zz")) === "a&lt;b"];
console.log(JSON.stringify(r));"""
        f = Path(tmp) / "h.js"
        f.write_text(harness, encoding="utf-8")
        res = subprocess.run([node, str(f)], capture_output=True, text=True)
        try:
            flags = json.loads(res.stdout.strip().splitlines()[-1])
        except Exception:
            flags = []
        labels = ["слитно", "порядок слов", "опечатка", "раскладка", "new6≠new7", "new6=new6", "-исключение", "лишнее слово",
                  ">размер", "<размер", "версия 1.0.3", "подсветка", "экранирование HTML"]
        for lab, v in zip(labels, flags):
            check(f"поиск (JS): {lab}", v is True)
        check("поиск (JS): все 13 проверок выполнены", len(flags) == 13, res.stderr[:200])

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 60 + f"\n ИТОГО: успешно {ok_n}, ошибок {fail_n}\n" + "=" * 60)
    return 1 if fail_n else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="GameSweep — старые версии игр в Корзину")
    ap.add_argument("--root", default="", help="папка с играми (подставится в окно)")
    ap.add_argument("--port", type=int, default=0, help="порт (по умолчанию свободный)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    httpd = make_server(args.root, args.port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/?t={httpd.token}"
    print(f"{APP} {VERSION}: {url}\nЗакройте это окно, чтобы остановить.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
