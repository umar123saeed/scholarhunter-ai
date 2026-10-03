"""Web search, page extraction, deadline verification and CV parsing."""
from __future__ import annotations
import re, threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
try:
    from ddgs import DDGS
except Exception:
    try:
        from duckduckgo_search import DDGS
    except Exception:
        DDGS = None
import tracker

class _Budget:
    def __init__(self):
        self.lock=threading.Lock(); self.max_calls=5; self.used=0; self.results=[]; self.queries=[]
BUDGET=_Budget()
def reset_budget(max_calls=5):
    with BUDGET.lock:
        BUDGET.max_calls=max(1,min(int(max_calls),5)); BUDGET.used=0; BUDGET.results=[]; BUDGET.queries=[]
def collected_results():
    with BUDGET.lock: return list(BUDGET.results)
def queries_used():
    with BUDGET.lock: return list(BUDGET.queries)
def run_search(query):
    if DDGS is None:
        return "Search dependency missing. Install requirements.txt."
    with BUDGET.lock:
        if BUDGET.used>=BUDGET.max_calls: return "SEARCH LIMIT REACHED"
        BUDGET.used+=1; BUDGET.queries.append(query); call_no=BUDGET.used
    hits=[]; last_err=""
    for _ in range(2):
        try:
            hits=list(DDGS().text(query,max_results=10) or [])
            if hits: break
        except Exception as exc: last_err=str(exc)
    if not hits: return f"No results ({call_no}/{BUDGET.max_calls}). {last_err[:120]}"
    lines=[]
    with BUDGET.lock:
        for h in hits[:8]:
            url=h.get("href") or h.get("url") or ""; title=(h.get("title") or "").strip(); snippet=(h.get("body") or h.get("snippet") or "").strip()
            if url:
                BUDGET.results.append({"title":title,"url":url,"snippet":snippet,"query":query}); lines.append(f"- {title} | {url} | {snippet[:180]}")
    return "\n".join(lines)

_AGGREGATORS=("scholars4dev","scholarshipportal","scholarship-positions","opportunitiesforyouth","scholarshipsads","youthop","opportunitydesk","findaphd","fastweb","scholarshipdb","studyportals","topuniversities","scholarshipscorner","afterschoolafrica")
_BLOCKED=("facebook.","youtube.","youtu.be","linkedin.","reddit.","quora.","twitter.","x.com","instagram.","tiktok.","pinterest.")
def is_blocked(url): return any(b in urlparse(url).netloc.lower() for b in _BLOCKED)
def trust_score(url):
    host=urlparse(url).netloc.lower()
    if any(a in host for a in _AGGREGATORS): return 0
    if host.endswith(".edu") or ".edu." in host or ".ac." in host or host.endswith(".gov") or ".gov." in host or host.endswith(".int"): return 3
    if host.endswith(".org") or any(k in host for k in ("scholarship","fellowship","daad","chevening","fulbright")): return 2
    return 1
def norm_url(url):
    p=urlparse((url or "").strip().lower()); host=p.netloc[4:] if p.netloc.startswith("www.") else p.netloc; path=re.sub(r"/+","/",p.path or "").rstrip("/"); return f"{host}{path}"

_HEADERS={"User-Agent":"Mozilla/5.0 (compatible; ScholarHunterAgents/2.0)"}
def fetch_page(url,max_chars=6000):
    try:
        r=requests.get(url,headers=_HEADERS,timeout=10,allow_redirects=True)
        if r.status_code!=200 or "html" not in r.headers.get("content-type","").lower(): return ""
        soup=BeautifulSoup(r.text,"html.parser")
        for t in soup(["script","style","nav","footer","header","noscript","form","svg"]): t.decompose()
        return re.sub(r"\s+"," ",soup.get_text(" ",strip=True))[:max_chars]
    except Exception: return ""
def fetch_pages(urls,max_chars=6000):
    if not urls: return {}
    with ThreadPoolExecutor(max_workers=6) as ex: texts=list(ex.map(lambda u:fetch_page(u,max_chars),urls))
    return dict(zip(urls,texts))

_DEADLINE_WORDS=re.compile(r"(application\s+deadline|applications?\s+(?:close|closing|must be submitted)|closing\s+date|submission\s+deadline|deadline|apply\s+by|last\s+date)",re.I)
_ROLLING_WORDS=re.compile(r"\b(rolling admissions?|rolling deadline|open year[- ]round|applications? accepted year[- ]round)\b",re.I)
_DATE_PATTERNS=[
 re.compile(r"\b20\d{2}-\d{1,2}-\d{1,2}\b"),
 re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]20\d{2}\b"),
 re.compile(r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+20\d{2}\b",re.I),
 re.compile(r"\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+20\d{2}\b",re.I)]
def extract_deadline(text,today:Optional[date]=None)->Tuple[Optional[str],str,Optional[int],bool]:
    if not text: return None,"unknown",None,False
    if _ROLLING_WORDS.search(text): return None,"rolling",None,True
    candidates=[]
    for kw in _DEADLINE_WORDS.finditer(text):
        start,end=max(0,kw.start()-80),min(len(text),kw.end()+220); window=text[start:end]
        for pattern in _DATE_PATTERNS:
            for m in pattern.finditer(window):
                d=tracker.parse_deadline(m.group(0))
                if d: candidates.append((abs((start+m.start())-kw.start()),d))
    if not candidates: return None,"unknown",None,False
    _,d=sorted(candidates,key=lambda x:x[0])[0]; status,days,_=tracker.classify_deadline(d,today=today); return d.isoformat(),status,days,True
def verify_page(url,page_text="",snippet=""):
    deadline,status,days,verified=extract_deadline(" ".join(x for x in [page_text,snippet] if x)); trust=trust_score(url)
    health=inspect_url(url)
    return {"deadline":deadline,"deadline_status":status,"days_remaining":days,"is_expired":status=="expired","deadline_verified":verified and status in {"upcoming","expired","rolling"},"deadline_source":url if verified else "","verification_status":"expired" if status=="expired" else "verified" if verified and trust>=2 else "partially_verified" if verified else "unverified","source_type":"official/preferred" if trust>=2 else "web","link_verified":health["ok"],"link_checked_at":health.get("checked_at","")+"|"+str(health.get("status","")),"final_url":health.get("final_url",url)}
def dedupe_results(items):
    seen_urls=set(); seen_titles=set(); out=[]
    for item in items:
        u=norm_url(item.get("url","")); t=re.sub(r"[^a-z0-9]+"," ",item.get("title","").lower()).strip()
        if (u and u in seen_urls) or (t and t in seen_titles): continue
        if u: seen_urls.add(u)
        if t: seen_titles.add(t)
        out.append(item)
    return out

def clean_text(text):
    text=text.replace("\x00"," "); text=re.sub(r"[ \t\u00a0]+"," ",text); text=re.sub(r"[^\x09\x0A\x20-\x7E\u00A1-\uFFFF]","",text); text=re.sub(r"\n\s*\n+","\n\n",text); return text.strip()
def parse_cv(file_obj,filename="",max_chars=6000):
    if filename.lower().endswith(".txt"):
        raw=file_obj.read(); raw=raw.decode("utf-8",errors="ignore") if isinstance(raw,bytes) else str(raw); return clean_text(raw)[:max_chars]
    from pypdf import PdfReader
    reader=PdfReader(file_obj)
    if getattr(reader,"is_encrypted",False):
        try: reader.decrypt("")
        except Exception as exc: raise ValueError("The PDF is password protected.") from exc
    pages=[]
    for page in reader.pages:
        try: pages.append(page.extract_text() or "")
        except Exception: pass
    text=clean_text("\n".join(pages))
    if not text: raise ValueError("No readable text found. The PDF may be scanned and require OCR.")
    return text[:max_chars]
