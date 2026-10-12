#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генерирует новый contents.json по .wcp, которые лежат в папках репозитория.
Без сети. Запуск из корня репо:   python update_contents.py

Правила:
  * папка = тип (Box64, WOWBox64, DXVK, FEXCore, VKD3D, WINE -> Wine);
    если в profile.json внутри .wcp указан type — берётся он
  * verName / verCode: если файл уже был в старом манифесте — остаются старые;
    иначе берутся из profile.json, а если его не прочитать — из имени файла
  * записи старого манифеста, которые не относятся к файлам в папках
    (например, Proton/Wine по ссылкам на релизы) — сохраняются как есть
  * файлов, которых уже нет в папках, в манифесте не будет
  * старый манифест сохраняется в contents.json.bak
"""
import io, json, os, re, shutil, subprocess, sys, tarfile
from collections import Counter

FALLBACK_BASE = "https://github.com/teldommm/Winlator-Contents/raw/refs/heads/main"
TYPE_BY_DIR = {"wine": "Wine", "proton": "Proton"}
EXTS = (".wcp", ".wcp.xz")

root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
mpath = os.path.join(root, "contents.json")


def read_profile(path):
    try:
        with open(path, "rb") as f:
            head = f.read(6)
        if head.startswith(b"\xfd7zXZ"):
            t = tarfile.open(path, "r:xz")
        elif head[:4] == b"\x28\xb5\x2f\xfd":
            if shutil.which("zstd"):
                data = subprocess.run(["zstd", "-dc", path], capture_output=True, check=True).stdout
            else:
                from compression import zstd  # Python 3.14+
                with open(path, "rb") as f:
                    data = zstd.decompress(f.read())
            t = tarfile.open(fileobj=io.BytesIO(data))
        else:
            return None
        for n in ("./profile.json", "profile.json"):
            try:
                return json.load(t.extractfile(n))
            except KeyError:
                pass
    except Exception:
        pass
    return None


def base_url():
    try:
        g = lambda *a: subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, check=True).stdout.strip()
        m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", g("remote", "get-url", "origin"))
        if m:
            return "https://github.com/%s/%s/raw/refs/heads/%s" % (m[1], m[2], g("rev-parse", "--abbrev-ref", "HEAD"))
    except Exception:
        pass
    return FALLBACK_BASE


old = []
if os.path.isfile(mpath):
    with open(mpath, encoding="utf-8") as f:
        old = json.load(f)
BASE = base_url()
print("База ссылок:", BASE)

# старые записи: путь файла -> запись
def rel_of(url):
    m = re.search(r"/raw/(?:refs/heads/)?[^/]+/(.+)$", url)
    return m[1] if m else None

old_by_path = {}
for e in old:
    p = rel_of(e["remoteUrl"])
    if p:
        old_by_path[p] = e

# файлы на диске
files = []
for d in sorted(os.listdir(root)):
    full = os.path.join(root, d)
    if os.path.isdir(full) and not d.startswith("."):
        for n in sorted(os.listdir(full)):
            if n.lower().endswith(EXTS):
                files.append(d + "/" + n)

out, used = [], set()
# 1) порядок старого манифеста сохраняем
for e in old:
    p = rel_of(e["remoteUrl"])
    if p is None or not re.match(r"^[^/]+/[^/]+$", p):
        out.append(e)                       # ссылка не на файл папки (релизы) — как есть
    elif p in files:
        e = dict(e); e["remoteUrl"] = BASE + "/" + p
        out.append(e); used.add(p)
# 2) новые файлы
for p in files:
    if p in used:
        continue
    d, n = p.split("/")
    prof = read_profile(os.path.join(root, d, n)) or {}
    typ = prof.get("type") or TYPE_BY_DIR.get(d.lower(), d)
    ver = str(prof.get("versionName") or re.sub(r"\.wcp(\.xz)?$", "", n, flags=re.I))
    code = str(prof.get("versionCode", 1))
    out.append({"type": typ, "verName": ver, "verCode": code, "remoteUrl": BASE + "/" + p})
    print("  + %-9s %s" % (typ, ver))

if os.path.isfile(mpath):
    shutil.copyfile(mpath, mpath + ".bak")
with open(mpath, "w", encoding="utf-8") as f:
    f.write("[\n")
    f.write(",\n".join(
        '  {\n    "type": %s,\n    "verName": %s,\n    "verCode": %s,\n    "remoteUrl": %s\n  }' % tuple(
            json.dumps(e[k], ensure_ascii=False) for k in ("type", "verName", "verCode", "remoteUrl")) for e in out))
    f.write("\n]\n")

cnt = Counter(e["type"] for e in out)
print("Готово: %d записей  (%s)" % (len(out), ", ".join("%s %d" % kv for kv in sorted(cnt.items()))))
