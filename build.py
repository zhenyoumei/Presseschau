#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Presseschau · 德國報紙每日導覽
------------------------------------------------------------
1. 讀取 feeds.toml 裡各報的 RSS
2. 去除重複、依主題整理，找出「多家報紙同時報導」的新聞
3. 標題與導言機器翻譯成繁體中文（免費，不需金鑰）
4. 產生網頁：docs/index.html（今天）＋ docs/archiv/（歷史存檔）

用法：python build.py            （正式執行）
      python build.py --no-translate   （不翻譯，測試用）
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import html
import json
import math
import re
import sys
import time
import tomllib
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
import urllib.parse
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import feedparser

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Taipei")
UA = "Mozilla/5.0 (X11; Linux x86_64) Presseschau-RSS-Reader/1.0"

# ============================================================
# Text-Hilfen
# ============================================================
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(s: str | None, limit: int | None = None) -> str:
    if not s:
        return ""
    s = html.unescape(TAG_RE.sub(" ", s))
    s = WS_RE.sub(" ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0].rstrip(",;:") + " …"
    return s


def norm_link(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", ""))


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


# ============================================================
# 1. RSS abrufen
# ============================================================
def fetch_feed(url: str, timeout: int = 25):
    """回傳 (feedparser 結果, 錯誤訊息)。失敗時重試一次。"""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA,
                 "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"},
    )
    err = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            parsed = feedparser.parse(data)
            if parsed.entries:
                return parsed, None
            err = "keine Einträge" + (f" ({parsed.get('bozo_exception')})" if parsed.get("bozo") else "")
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        time.sleep(2)
    return None, err


FETCH = fetch_feed  # 測試時可替換


def entry_time(e) -> dt.datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return dt.datetime.fromtimestamp(calendar.timegm(t), tz=dt.timezone.utc)
    return None


def collect(cfg: dict, now_utc: dt.datetime):
    s = cfg["settings"]
    max_age = dt.timedelta(hours=s.get("max_age_hours", 30))
    items, status = [], []
    for paper in cfg["papers"]:
        for topic, urls in paper["feeds"].items():
            urls = [urls] if isinstance(urls, str) else urls
            limit = s.get("top_items_per_paper", 5) if topic == "top" else s.get("items_per_feed", 6)
            for entry in urls:
                # 「網址A | 網址B」＝備用網址：第一個成功的就用它
                parsed, err, url = None, None, entry
                for url in [u.strip() for u in entry.split("|") if u.strip()]:
                    parsed, err = FETCH(url)
                    if parsed is not None:
                        break
                if parsed is None:
                    status.append(dict(paper=paper["id"], topic=topic, url=url, ok=False, info=err))
                    print(f"  ✗ {paper['name']:8} {topic:12} {err}", file=sys.stderr)
                    continue
                n = 0
                for e in parsed.entries:
                    title = clean_text(e.get("title"))
                    link = (e.get("link") or "").strip()
                    if not title or not link.startswith(("http://", "https://")):
                        continue
                    when = entry_time(e)
                    if when and now_utc - when > max_age:
                        continue
                    summary = clean_text(e.get("summary") or e.get("description"), s.get("summary_chars", 280))
                    if summary == title:
                        summary = ""
                    items.append(dict(paper=paper["id"], topic=topic, title=title, link=link,
                                      key=norm_link(link), summary=summary,
                                      time=when.isoformat() if when else None))
                    n += 1
                    if n >= limit:
                        break
                status.append(dict(paper=paper["id"], topic=topic, url=url, ok=True, info=f"{n} Artikel"))
                print(f"  ✓ {paper['name']:8} {topic:12} {n}", file=sys.stderr)
    return items, status


# ============================================================
# 2. Ordnen: Top-Meldungen, Rubriken, gemeinsame Themen
# ============================================================
def sort_key(it):
    return it["time"] or ""


def organize(cfg: dict, items: list[dict]):
    seen = set()
    top = defaultdict(list)
    for it in items:
        if it["topic"] == "top" and it["key"] not in seen:
            seen.add(it["key"])
            top[it["paper"]].append(it)
    sections = defaultdict(list)
    for it in items:
        if it["topic"] == "top" or it["key"] in seen:
            continue
        seen.add(it["key"])
        sections[it["topic"]].append(it)
    for lst in sections.values():
        lst.sort(key=sort_key, reverse=True)
    unique = [it for lst in top.values() for it in lst] + [it for lst in sections.values() for it in lst]
    return top, sections, find_clusters(unique)


STOP = set("""
der die das den dem des ein eine einer eines einem einen und oder aber doch nicht kein keine keinen
wie was wer wem wen wo warum wann wieso weshalb welche welcher welches nach mit bei von vor für über
unter gegen ohne durch seit trotz wegen zum zur vom beim auf aus ist sind war waren wird werden wurde
wurden hat haben hatte kann können soll sollen muss müssen will wollen darf jetzt heute gestern morgen
neue neuer neues neuen erste ersten erster mehr viele vielen alle alles allem diese dieser dieses diesen
hier dort auch noch schon nur sehr immer wieder dann denn wenn weil dass sich ihre ihren seine seinen
zwischen nachdem während bevor damit etwa rund fast kaum mal eben ganz gibt geht macht steht bleibt
liveblog newsblog ticker live news video videos podcast kommentar analyse interview meinung exklusiv
spiegel zeit focus faz süddeutsche plus abo montag dienstag mittwoch donnerstag freitag samstag sonntag
januar februar märz april juni juli august september oktober november dezember woche wochen tage jahr
jahre jahren jahres prozent euro millionen milliarden menschen leute deutschland deutsche deutschen
deutscher frau mann kinder bilder foto fotos news update überblick fragen antworten
""".split())
TOKEN_RE = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]{3,}")


def _stem(w: str) -> str:
    w = w.lower().strip("-")
    if len(w) > 5 and w.endswith("s"):
        w = w[:-1]
    return w


def keywords(it, surface: dict) -> set[str]:
    """標題＋導言前段中，大寫開頭的詞（名詞、專有名詞）。"""
    toks = set()
    for w in TOKEN_RE.findall(it["title"] + " " + it["summary"][:220]):
        if not w[0].isupper():
            continue
        st = _stem(w)
        if st in STOP or len(st) < 4:
            continue
        toks.add(st)
        surface[st][w.strip("-")] += 1
    return toks


def find_clusters(items: list[dict], max_size: int = 6, max_clusters: int = 8):
    """找出至少兩家報紙都在報導的同一件事（簡單的關鍵字重疊法）。"""
    n = len(items)
    if n < 2:
        return []
    surface = defaultdict(Counter)
    kws = [keywords(it, surface) for it in items]
    df = Counter(t for k in kws for t in k)
    too_common = max(3, int(0.15 * n))
    idf = {t: math.log(n / c) for t, c in df.items()}

    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            if items[i]["paper"] == items[j]["paper"]:
                continue
            shared = {t for t in kws[i] & kws[j] if df[t] <= too_common}
            if len(shared) >= 2:
                pairs.append((sum(idf[t] for t in shared), i, j))
    pairs.sort(reverse=True)

    parent = list(range(n))
    members = {i: {i} for i in range(n)}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for _, i, j in pairs:
        a, b = find(i), find(j)
        if a == b or len(members[a]) + len(members[b]) > max_size:
            continue
        parent[b] = a
        members[a] |= members.pop(b)

    clusters = []
    for root, mem in members.items():
        papers = {items[i]["paper"] for i in mem}
        if len(papers) < 2:
            continue
        cnt = Counter(t for i in mem for t in kws[i] if df[t] <= too_common)
        label_toks = [t for t, c in cnt.most_common() if c >= 2][:3]
        label = " · ".join(surface[t].most_common(1)[0][0] for t in label_toks)
        its = sorted((items[i] for i in mem), key=lambda x: x["paper"])
        clusters.append(dict(label=label, papers=len(papers), items=its))
    clusters.sort(key=lambda c: (c["papers"], len(c["items"])), reverse=True)
    return clusters[:max_clusters]


# ============================================================
# 3. Übersetzung (Google Translate über deep-translator, kostenlos)
# ============================================================
TR_ERRORS: list[str] = []   # 翻譯失敗的原因，會寫進網頁頁尾與 data/*.json


def _backend_gtx(target: str):
    """Google Translate 的公開端點（不需金鑰）。"""
    base = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=de&tl={target}&dt=t&q="

    def f(text: str) -> str:
        req = urllib.request.Request(base + urllib.parse.quote(text), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            js = json.loads(r.read().decode("utf-8"))
        return "".join(seg[0] for seg in (js[0] or []) if seg and seg[0])
    return f


def _backend_deep(target: str):
    from deep_translator import GoogleTranslator
    tr = GoogleTranslator(source="de", target=target)
    return lambda text: tr.translate(text) or ""


def _translate_with(fn, name: str, texts: list[str], chunk_chars: int = 1500) -> dict[str, str]:
    out: dict[str, str] = {}
    fails = 0

    def one(t: str) -> str:
        nonlocal fails
        if fails >= 3:
            return ""
        try:
            r = (fn(t) or "").strip()
            fails = 0
            return r
        except Exception as e:  # noqa: BLE001
            fails += 1
            msg = f"{name}: {type(e).__name__}: {str(e)[:200]}"
            TR_ERRORS.append(msg)
            print("  Übersetzung fehlgeschlagen –", msg, file=sys.stderr)
            return ""

    def flush(chunk: list[str]):
        if not chunk or fails >= 3:
            return
        res = one("\n".join(chunk))
        lines = [l.strip() for l in res.split("\n")] if res else []
        if len(lines) == len(chunk):
            out.update(zip(chunk, lines))
            return
        for t in chunk:  # 行數對不上時逐則翻
            out[t] = one(t)
            time.sleep(0.2)

    chunk, size = [], 0
    for t in dict.fromkeys(t for t in texts if t):
        if chunk and size + len(t) + 1 > chunk_chars:
            flush(chunk)
            chunk, size = [], 0
            time.sleep(0.4)
        chunk.append(t)
        size += len(t) + 1
    flush(chunk)
    return out


def translate_all(texts: list[str], target: str) -> dict[str, str]:
    """先用 Google 公開端點；不行再試 deep-translator。"""
    for name, make in (("gtx", _backend_gtx), ("deep-translator", _backend_deep)):
        try:
            fn = make(target)
        except Exception as e:  # noqa: BLE001
            TR_ERRORS.append(f"{name}: {type(e).__name__}: {e}")
            continue
        out = _translate_with(fn, name, texts)
        n = len({t for t in texts if t}) or 1
        if sum(1 for v in out.values() if v) >= 0.5 * n:
            print(f"  übersetzt mit {name}", file=sys.stderr)
            return out
    return {}


TRANSLATE = translate_all  # 測試時可替換


# ============================================================
# 4. HTML
# ============================================================
WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
ZH_WEEK = "一二三四五六日"


def fmt_time(iso: str | None, today: dt.date) -> str:
    if not iso:
        return ""
    t = dt.datetime.fromisoformat(iso).astimezone(TZ)
    return t.strftime("%H:%M") if t.date() == today else t.strftime("%d.%m. %H:%M")


def render_item(it, papers, today, compact=False) -> str:
    p = papers[it["paper"]]
    t = fmt_time(it["time"], today)
    h = [f'<article class="item{" compact" if compact else ""}" data-p="{p["id"]}">',
         f'<div class="meta"><span class="badge" style="--c:{esc(p["color"])}">{esc(p["name"])}</span>'
         + (f'<time>{t}</time>' if t else "") + "</div>",
         f'<h3 lang="de"><a href="{esc(it["link"])}" target="_blank" rel="noopener">{esc(it["title"])}</a></h3>']
    if it.get("title_zh"):
        h.append(f'<p class="zh zh-title" lang="zh-Hant">{esc(it["title_zh"])}</p>')
    if not compact:
        if it["summary"]:
            h.append(f'<p class="teaser" lang="de">{esc(it["summary"])}</p>')
        if it.get("summary_zh"):
            h.append(f'<p class="teaser zh" lang="zh-Hant">{esc(it["summary_zh"])}</p>')
    h.append("</article>")
    return "\n".join(h)


def render_page(cfg, top, sections, clusters, status, now: dt.datetime, root: str, translated: bool) -> str:
    papers = {p["id"]: p for p in cfg["papers"]}
    today = now.date()
    de_date = f"{WOCHENTAGE[now.weekday()]}, {now.day}. {MONATE[now.month - 1]} {now.year}"
    zh_date = f"{now:%Y/%m/%d}（週{ZH_WEEK[now.weekday()]}）"

    nav = ['<a href="#top">頭條 Top</a>']
    if clusters:
        nav.append('<a href="#gemeinsam">多報共同 Gemeinsam</a>')
    body = []

    # Top-Meldungen
    cols = []
    for p in cfg["papers"]:
        lst = top.get(p["id"], [])
        if not lst:
            continue
        cols.append(f'<div class="col" data-p="{p["id"]}"><h3 class="colhead" style="--c:{esc(p["color"])}">'
                    f'{esc(p["full"])}</h3>' + "\n".join(render_item(it, papers, today) for it in lst) + "</div>")
    body.append('<section id="top"><h2>今日頭條 <span>Die Top-Meldungen</span></h2>'
                f'<div class="cols">{"".join(cols) or "<p class=empty>—</p>"}</div></section>')

    # Gemeinsame Themen
    if clusters:
        cards = []
        for c in clusters:
            lab = esc(c["label"]) or "Gemeinsames Thema"
            cards.append(f'<div class="cluster"><div class="clhead"><strong lang="de">{lab}</strong>'
                         f'<span class="count">{c["papers"]} 家報紙</span></div>'
                         + "\n".join(render_item(it, papers, today, compact=True) for it in c["items"]) + "</div>")
        body.append('<section id="gemeinsam"><h2>多家報紙共同報導 <span>Worüber mehrere Zeitungen berichten</span></h2>'
                    '<p class="hint">同一件事，看各報怎麼下標題。（依關鍵字自動比對，偶有誤差）</p>'
                    f'<div class="clusters">{"".join(cards)}</div></section>')

    # Rubriken
    for tp in cfg["topics"]:
        lst = sections.get(tp["id"], [])
        if not lst:
            continue
        nav.append(f'<a href="#{tp["id"]}">{esc(tp["zh"])}</a>')
        body.append(f'<section id="{tp["id"]}"><h2>{esc(tp["zh"])} <span>{esc(tp["de"])}</span></h2>'
                    '<div class="grid">' + "\n".join(render_item(it, papers, today) for it in lst) + "</div></section>")

    chips = "".join(f'<button class="chip" data-chip="{p["id"]}" style="--c:{esc(p["color"])}" aria-pressed="true">'
                    f'{esc(p["name"])}</button>' for p in cfg["papers"])

    # Quellenstatus
    rows = []
    topic_names = {t["id"]: t["zh"] for t in cfg["topics"]} | {"top": "頭條"}
    for p in cfg["papers"]:
        cells = []
        for st in (s for s in status if s["paper"] == p["id"]):
            mark = "✓" if st["ok"] else "✗"
            cells.append(f'<span class="{"ok" if st["ok"] else "bad"}" title="{esc(st["url"])} — {esc(st["info"] or "")}">'
                         f'{mark} {esc(topic_names.get(st["topic"], st["topic"]))}</span>')
        rows.append(f'<tr><th>{esc(p["name"])}</th><td>{" ".join(cells)}</td></tr>')
    bad = sum(1 for s in status if not s["ok"])
    status_summary = f"來源狀態 Quellenstatus：{len(status) - bad}/{len(status)} 正常" + (f"，{bad} 個無法讀取" if bad else "")
    if translated:
        tr_note = "中文為機器翻譯（Google Translate），僅供參考。"
    elif TR_ERRORS:
        tr_note = f"本次未產生中文翻譯（{esc(TR_ERRORS[-1][:160])}）。"
    else:
        tr_note = "本次未產生中文翻譯。"

    return PAGE.format(
        de_date=esc(de_date), zh_date=esc(zh_date), gen=now.strftime("%H:%M"),
        nav="".join(nav), chips=chips, body="\n".join(body), root=root,
        status_summary=esc(status_summary), status_rows="".join(rows), tr_note=tr_note,
        zh_btn_hidden="" if translated else " hidden",
    )


PAGE = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Presseschau · {zh_date}</title>
<style>
:root {{ --bg:#f7f6f2; --card:#fff; --ink:#1d1d1f; --muted:#6b6b70; --line:#e4e2dc; --accent:#8a2b1f; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#17171a; --card:#222226; --ink:#ececee; --muted:#a0a0a8; --line:#34343a; --accent:#e08a6f; }}
}}
* {{ box-sizing:border-box; }}
html {{ scroll-behavior:smooth; scroll-padding-top:110px; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", sans-serif; }}
a {{ color:inherit; }}
header {{ padding:28px 20px 14px; max-width:1180px; margin:0 auto; }}
header h1 {{ margin:0; font:700 30px/1.15 Georgia, "Times New Roman", serif; letter-spacing:-.01em; }}
header h1 small {{ font:500 16px/1 inherit; color:var(--muted); margin-left:8px; font-family:inherit; }}
.date {{ margin-top:6px; color:var(--muted); }}
.date b {{ color:var(--ink); font-weight:600; }}
.bar {{ position:sticky; top:0; z-index:5; background:color-mix(in srgb, var(--bg) 92%, transparent);
  backdrop-filter:blur(8px); border-bottom:1px solid var(--line); }}
.bar-in {{ max-width:1180px; margin:0 auto; padding:8px 20px; display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; }}
.chips, .toggles {{ display:flex; flex-wrap:wrap; gap:6px; }}
.chip, .tog {{ border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:999px;
  padding:4px 11px; font:600 13px/1.4 inherit; cursor:pointer; }}
.chip[aria-pressed="true"] {{ background:var(--c); border-color:var(--c); color:#fff; }}
.chip[aria-pressed="false"] {{ opacity:.55; text-decoration:line-through; }}
.tog[aria-pressed="true"] {{ background:var(--ink); color:var(--bg); border-color:var(--ink); }}
nav {{ display:flex; gap:4px 14px; flex-wrap:wrap; font-size:14px; width:100%; }}
nav a {{ text-decoration:none; color:var(--muted); }}
nav a:hover {{ color:var(--accent); }}
main {{ max-width:1180px; margin:0 auto; padding:6px 20px 40px; }}
section {{ margin-top:30px; }}
h2 {{ font:700 22px/1.3 inherit; margin:0 0 12px; padding-bottom:6px; border-bottom:2px solid var(--ink); }}
h2 span {{ font:italic 400 17px/1 Georgia, serif; color:var(--muted); margin-left:6px; }}
.hint {{ color:var(--muted); font-size:14px; margin:-4px 0 12px; }}
.cols {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:16px; }}
.colhead {{ margin:0 0 8px; font:700 15px/1.3 inherit; color:var(--c); border-bottom:1px solid var(--line); padding-bottom:4px; }}
.col .item {{ margin-bottom:10px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(320px, 1fr)); gap:12px; }}
.item {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:11px 13px; }}
.meta {{ display:flex; gap:8px; align-items:center; font-size:12px; color:var(--muted); margin-bottom:3px; }}
.badge {{ background:var(--c); color:#fff; border-radius:4px; padding:1px 6px; font-weight:700; letter-spacing:.02em; font-size:11px; }}
.item h3 {{ margin:0; font:600 16.5px/1.38 Georgia, "Times New Roman", serif; }}
.item h3 a {{ text-decoration:none; }}
.item h3 a:hover {{ text-decoration:underline; color:var(--accent); }}
.zh-title {{ margin:3px 0 0; font-size:15px; color:var(--ink); opacity:.82; }}
.teaser {{ margin:6px 0 0; font-size:14px; color:var(--muted); }}
.teaser.zh {{ margin-top:3px; }}
.clusters {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(340px, 1fr)); gap:14px; }}
.cluster {{ border:1px solid var(--line); border-left:4px solid var(--accent); border-radius:10px; padding:10px 12px; background:var(--card); }}
.clhead {{ display:flex; justify-content:space-between; gap:8px; margin-bottom:6px; }}
.clhead strong {{ font:600 15px/1.3 Georgia, serif; }}
.count {{ font-size:12px; color:var(--muted); white-space:nowrap; }}
.item.compact {{ border:0; border-top:1px dashed var(--line); border-radius:0; padding:7px 0 4px; background:none; }}
.item.compact h3 {{ font-size:15px; }}
.item.compact .zh-title {{ font-size:14px; }}
body.no-zh .zh {{ display:none; }}
body.no-teaser .teaser {{ display:none; }}
[hidden] {{ display:none !important; }}
footer {{ max-width:1180px; margin:0 auto; padding:16px 20px 40px; color:var(--muted); font-size:13px; border-top:1px solid var(--line); }}
footer table {{ border-collapse:collapse; margin-top:8px; }}
footer th {{ text-align:left; padding:3px 12px 3px 0; vertical-align:top; color:var(--ink); }}
footer td {{ padding:3px 0; }}
footer td span {{ display:inline-block; margin:0 10px 2px 0; }}
.ok {{ color:#2c7a57; }} .bad {{ color:#c0392b; font-weight:600; }}
.empty {{ color:var(--muted); }}
@media (max-width:600px) {{
  header h1 {{ font-size:25px; }}
  .grid, .cols, .clusters {{ grid-template-columns:1fr; }}
  html {{ scroll-padding-top:130px; }}
  nav {{ flex-wrap:nowrap; overflow-x:auto; white-space:nowrap; padding-bottom:2px; }}
}}
</style>
</head>
<body>
<header>
  <h1>Presseschau<small>德國報紙每日導覽</small></h1>
  <div class="date"><b>{zh_date}</b> · <span lang="de">{de_date}</span> · 更新於 {gen}（台灣時間） · <a href="{root}archiv/">存檔 Archiv</a></div>
</header>
<div class="bar"><div class="bar-in">
  <div class="chips" aria-label="報紙篩選">{chips}</div>
  <div class="toggles">
    <button class="tog" id="t-zh" aria-pressed="true"{zh_btn_hidden}>中文</button>
    <button class="tog" id="t-teaser" aria-pressed="true">導言 Teaser</button>
  </div>
  <nav>{nav}</nav>
</div></div>
<main>
{body}
</main>
<footer>
  <p>{tr_note}標題與導言著作權屬各報社，點標題閱讀原文（部分為付費內容）。時間為台灣時間。</p>
  <details><summary>{status_summary}</summary><table>{status_rows}</table></details>
</footer>
<script>
(function () {{
  var KEY = "presseschau-prefs", prefs = {{ zh: true, teaser: true, hidden: [] }};
  try {{ var s = JSON.parse(localStorage.getItem(KEY) || "{{}}"); for (var k in s) prefs[k] = s[k]; }} catch (e) {{}}
  function apply() {{
    document.body.classList.toggle("no-zh", !prefs.zh);
    document.body.classList.toggle("no-teaser", !prefs.teaser);
    document.getElementById("t-zh").setAttribute("aria-pressed", prefs.zh);
    document.getElementById("t-teaser").setAttribute("aria-pressed", prefs.teaser);
    document.querySelectorAll("[data-chip]").forEach(function (b) {{
      b.setAttribute("aria-pressed", prefs.hidden.indexOf(b.dataset.chip) < 0);
    }});
    document.querySelectorAll("[data-p]").forEach(function (el) {{
      el.hidden = prefs.hidden.indexOf(el.dataset.p) >= 0;
    }});
    try {{ localStorage.setItem(KEY, JSON.stringify(prefs)); }} catch (e) {{}}
  }}
  document.getElementById("t-zh").onclick = function () {{ prefs.zh = !prefs.zh; apply(); }};
  document.getElementById("t-teaser").onclick = function () {{ prefs.teaser = !prefs.teaser; apply(); }};
  document.querySelectorAll("[data-chip]").forEach(function (b) {{
    b.onclick = function () {{
      var id = b.dataset.chip, i = prefs.hidden.indexOf(id);
      if (i >= 0) prefs.hidden.splice(i, 1); else prefs.hidden.push(id);
      apply();
    }};
  }});
  apply();
}})();
</script>
</body>
</html>
"""

ARCHIVE_PAGE = """<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Presseschau · 存檔 Archiv</title>
<style>
body {{ font:16px/1.6 -apple-system, "Segoe UI", "PingFang TC", "Noto Sans TC", sans-serif; max-width:640px; margin:0 auto; padding:30px 20px; background:#f7f6f2; color:#1d1d1f; }}
@media (prefers-color-scheme: dark) {{ body {{ background:#17171a; color:#ececee; }} }}
h1 {{ font:700 28px Georgia, serif; }} a {{ color:inherit; }} li {{ margin:4px 0; }}
</style></head><body>
<h1>存檔 Archiv</h1><p><a href="../">← 今天的 Presseschau</a></p>
<ul>{items}</ul></body></html>
"""


def write_archive_index(docs: Path):
    arch = docs / "archiv"
    days = sorted((p.stem for p in arch.glob("????-??-??.html")), reverse=True)
    lis = []
    for d in days:
        y, m, dd = map(int, d.split("-"))
        wd = dt.date(y, m, dd).weekday()
        lis.append(f'<li><a href="{d}.html">{y}/{m:02d}/{dd:02d}（週{ZH_WEEK[wd]}）</a> · '
                   f'<span lang="de">{WOCHENTAGE[wd]}, {dd}. {MONATE[m - 1]}</span></li>')
    (arch / "index.html").write_text(ARCHIVE_PAGE.format(items="".join(lis)), "utf-8")


# ============================================================
# main
# ============================================================
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs"), help="輸出資料夾")
    ap.add_argument("--no-translate", action="store_true")
    args = ap.parse_args(argv)

    cfg = tomllib.loads((ROOT / "feeds.toml").read_text("utf-8"))
    now_utc = dt.datetime.now(dt.timezone.utc)
    now = now_utc.astimezone(TZ)
    docs = Path(args.out)
    (docs / "archiv").mkdir(parents=True, exist_ok=True)
    (docs / "data").mkdir(parents=True, exist_ok=True)
    (docs / ".nojekyll").touch()

    print("RSS abrufen …", file=sys.stderr)
    items, status = collect(cfg, now_utc)
    if not items:
        print("Keine Artikel gefunden – Seite wird nicht überschrieben.", file=sys.stderr)
        return 1
    top, sections, clusters = organize(cfg, items)
    shown = [it for l in top.values() for it in l] + [it for l in sections.values() for it in l]

    translated = False
    if cfg["settings"].get("translate", True) and not args.no_translate:
        print(f"Übersetzen ({len(shown)} Artikel) …", file=sys.stderr)
        tr = TRANSLATE([it["title"] for it in shown] + [it["summary"] for it in shown],
                       cfg["settings"].get("target_language", "zh-TW"))
        for it in shown:
            it["title_zh"] = tr.get(it["title"], "")
            it["summary_zh"] = tr.get(it["summary"], "") if it["summary"] else ""
        translated = any(it["title_zh"] for it in shown)

    day = now.strftime("%Y-%m-%d")
    (docs / "index.html").write_text(
        render_page(cfg, top, sections, clusters, status, now, "", translated), "utf-8")
    (docs / "archiv" / f"{day}.html").write_text(
        render_page(cfg, top, sections, clusters, status, now, "../", translated), "utf-8")
    write_archive_index(docs)
    (docs / "data" / f"{day}.json").write_text(json.dumps(
        dict(generated=now.isoformat(), translated=translated, translation_errors=TR_ERRORS[:20],
             items=shown, status=status), ensure_ascii=False, indent=1), "utf-8")

    bad = sum(1 for s in status if not s["ok"])
    print(f"Fertig: {len(shown)} Artikel, {len(clusters)} gemeinsame Themen, "
          f"{bad} Feeds fehlgeschlagen, übersetzt: {translated}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
