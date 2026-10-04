"""CrewAI + Groq orchestration for ScholarHunter Agents V2."""
from __future__ import annotations
import json, os, re, time
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY","true")
os.environ.setdefault("CREWAI_TRACING_ENABLED","false")
os.environ.setdefault("OTEL_SDK_DISABLED","true")
from crewai import LLM, Agent, Crew, Process, Task
import tools, tracker
from schemas import CandidateProfile, GapReport, RawResult, ScholarshipRecord

MODEL=os.getenv("GROQ_MODEL","groq/openai/gpt-oss-120b")
SEED_PATH=Path(__file__).parent/"data"/"seed_scholarships.json"
_REACT_LINE=re.compile(r"^\s*(thought|action|action input|observation|final answer)\s*:",re.I)
_PLAIN="Reply directly with the requested content as plain text. Do not call any tools or functions."
NO_TOOLS="\n\nDo not call any tools or functions. Reply with plain text only."

def _sanitize(messages):
    out=[]
    for m in messages:
        content=m.get("content") if isinstance(m,dict) else None
        if not isinstance(content,str): out.append(m); continue
        keep=[]
        for line in content.split("\n"):
            low=line.lower()
            if _REACT_LINE.match(line) or "i must use these formats" in low or "to give my best complete final answer" in low: continue
            keep.append(line)
        out.append({**m,"content":re.sub(r"(?i)final answer","answer","\n".join(keep))})
    out.append({"role":"user","content":_PLAIN}); return out

class GptOssGroqLLM(LLM):
    def __init__(self,api_key,temperature=0.1):
        super().__init__(model=MODEL,api_key=api_key,temperature=temperature,max_tokens=4200); self._groq_key=api_key; self._temp=temperature
    def call(self,messages,*args,**kwargs):
        import litellm
        if isinstance(messages,str): messages=[{"role":"user","content":messages}]
        clean=_sanitize(messages); last=None
        for attempt in range(2):
            try:
                resp=litellm.completion(model=MODEL,api_key=self._groq_key,messages=clean,temperature=self._temp,max_tokens=4200)
                text=(resp.choices[0].message.content or "").strip()
                if not text: raise ValueError("Model returned an empty answer")
                return "Thought: done\nFinal Answer: "+text
            except Exception as exc:
                last=exc
                if attempt==0 and any(k in str(exc).lower() for k in ("tool_use_fail","tool choice is none","empty answer")):
                    clean.append({"role":"user","content":"Return ordinary text only."}); time.sleep(1); continue
                raise
        raise last

def get_llm(api_key,temperature=0.1): return GptOssGroqLLM(api_key,temperature)

def _balanced(text,start):
    open_c=text[start]; close_c="}" if open_c=="{" else "]"; depth=0; in_str=False; esc=False
    for j in range(start,len(text)):
        c=text[j]
        if in_str:
            if esc: esc=False
            elif c=="\\": esc=True
            elif c=='"': in_str=False
            continue
        if c=='"': in_str=True
        elif c==open_c: depth+=1
        elif c==close_c:
            depth-=1
            if depth==0: return text[start:j+1]
    return None

def extract_json(text):
    t=re.sub(r"^```(?:json)?\s*|\s*```$","",str(text or "").strip(),flags=re.I).strip()
    try: return json.loads(t)
    except Exception: pass
    for i,ch in enumerate(t):
        if ch in "{[":
            chunk=_balanced(t,i)
            if chunk:
                try: return json.loads(chunk)
                except Exception: pass
    raise ValueError("Could not find valid JSON in model output")

def _run(agent_factory:Callable[[],Agent],description,expected,inputs,attempts=3):
    last=None
    for attempt in range(attempts):
        agent=agent_factory(); task=Task(description=description+NO_TOOLS,expected_output=expected,agent=agent)
        try:
            out=Crew(agents=[agent],tasks=[task],process=Process.sequential,verbose=False).kickoff(inputs={k:str(v) for k,v in inputs.items()})
            return getattr(out,"raw",None) or str(out)
        except Exception as exc:
            last=exc
            if attempt<attempts-1 and any(k in str(exc).lower() for k in ("429","rate limit","timeout","overloaded","tool_use_fail")):
                time.sleep(6*(attempt+1)); continue
            raise
    raise last

def _run_json(factory,description,expected,inputs):
    raw=_run(factory,description,expected,inputs)
    try: return extract_json(raw)
    except ValueError: return extract_json(_run(factory,description+"\nReturn ONLY valid JSON. No prose or code fences.",expected,inputs,attempts=2))

def analyze_profile(cv_text,interests,domain,countries,level,llm):
    def factory(): return Agent(role="Academic Profile Analyst",goal="Convert candidate information into a precise search-ready profile.",backstory="Extract only stated facts; missing information stays null.",llm=llm,tools=[],allow_delegation=False,verbose=False,max_iter=2)
    desc=("Build a candidate profile. Never invent facts.\nLevel: {level}\nInterests: {interests}\nDomain: {domain}\nCountries: {countries}\nCV:\n{cv_text}\n\nReturn JSON with name, highest_degree, field_of_study, institution, gpa, english_test, publications, research_experience(list), skills(list), research_interests(list), target_domain, target_level, countries(list), keywords(list of 6-10 concise search terms).")
    data=_run_json(factory,desc,"One JSON object.",dict(level=level,interests=interests or "not provided",domain=domain or "not provided",countries=", ".join(countries),cv_text=(cv_text or "not provided")[:6000]))
    if isinstance(data,list): data=data[0] if data else {}
    p=CandidateProfile(**data); p.countries=countries; p.target_level=level
    if domain: p.target_domain=domain
    if interests and not p.research_interests: p.research_interests=[x.strip() for x in re.split(r"[,;\n]",interests) if x.strip()]
    kws=list(p.keywords)
    for x in [*p.research_interests,p.field_of_study,p.target_domain,f"{level} scholarship","fully funded"]:
        if x and x.lower() not in {k.lower() for k in kws}: kws.append(x)
    p.keywords=kws[:10]; return p

def _fallback_queries(profile,level):
    year=date.today().year; base=profile.target_domain or (profile.research_interests[0] if profile.research_interests else profile.field_of_study or ""); countries=profile.countries or [""]
    qs=[f'{level} fully funded scholarship {c} {base} application deadline {year} open' for c in countries]
    qs += [f'{level} fully funded {base} deadline {year} university',f'{level} fellowship {base} applications open {year}']
    return [re.sub(r"\s+"," ",q).strip() for q in qs]

def scout_opportunities(profile,level,max_searches,llm)->Tuple[List[RawResult],List[str],str]:
    max_searches=max(1,min(int(max_searches),5)); tools.reset_budget(max_searches)
    def factory(): return Agent(role="Scholarship Intelligence Scout",goal="Plan searches for current open funded opportunities on official sources.",backstory="Prefer current-cycle university, government and programme pages.",llm=llm,tools=[],allow_delegation=False,verbose=False,max_iter=2)
    desc=("Today is {today}. Plan exactly {n} searches for CURRENT or UPCOMING scholarships/funded positions.\nKeywords: {keywords}\nCountries: {countries}\nLevel: {level}\nEach query should include level, country where possible, current year, and freshness terms like 'applications open' or 'application deadline'. Prefer official sources. Return ONLY a JSON array of strings.")
    warning=""; queries=[]
    try:
        data=_run_json(factory,desc,"JSON array of search query strings.",dict(today=date.today().isoformat(),n=max_searches,keywords=", ".join(profile.keywords),countries=", ".join(profile.countries),level=level))
        if isinstance(data,dict): data=data.get("queries",[])
        queries=[str(q).strip() for q in data if str(q).strip()]
    except Exception: warning="We used a backup search plan because the search planner was unavailable."
    for q in _fallback_queries(profile,level):
        if len(queries)>=max_searches: break
        if q not in queries: queries.append(q)
    for q in queries[:max_searches]: tools.run_search(q)
    items=[]
    for item in tools.collected_results():
        url=item.get("url","")
        if not url.startswith("http") or tools.is_blocked(url): continue
        item["trust"]=tools.trust_score(url)
        if item["trust"] <= 0: continue
        items.append(item)
    items=tools.dedupe_results(sorted(items,key=lambda x:-x["trust"]))[:18]
    pages=tools.fetch_pages([i["url"] for i in items[:12]],max_chars=10000)
    raw=[]
    for item in items:
        page=pages.get(item["url"],""); v=tools.verify_page(item["url"],page,item.get("snippet",""))
        if v["deadline_status"]=="expired": continue
        raw.append(RawResult(title=item.get("title",""),url=item["url"],snippet=item.get("snippet",""),query=item.get("query",""),page_text=page,trust=item["trust"],deadline=v["deadline"],deadline_status=v["deadline_status"],days_remaining=v["days_remaining"],deadline_verified=v["deadline_verified"],final_url=v.get("final_url",item["url"]),link_ok=v.get("link_verified",False),application_link=tools.extract_application_link(v.get("final_url",item["url"]))))
    return raw,tools.queries_used(),warning

def _load_seed():
    try: return json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except Exception: return []
def seed_records(level,countries):
    wanted={c.lower() for c in countries}; out=[]
    for s in _load_seed():
        if level and level.lower() not in s.get("level","").lower(): continue
        out.append(ScholarshipRecord(**s,deadline=None,confidence="low",verification_status="unverified",notes="Seed discovery hint only. Verify live cycle and deadline on official site."))
    out.sort(key=lambda r:0 if r.country.lower() in wanted else 1); return out[:10]

def _architect(llm): return Agent(role="Scholarship Data Architect",goal="Turn web evidence into clean scholarship records.",backstory="Never invent deadlines or eligibility facts.",llm=llm,tools=[],allow_delegation=False,verbose=False,max_iter=2)
def _task_database(raw,level,llm):
    payload=[{"title":r.title[:140],"url":r.final_url or r.url,"snippet":r.snippet[:800],"page":r.page_text[:7000],"detected_deadline":r.deadline,"detected_status":r.deadline_status,"application_link":r.application_link} for r in raw[:12]]
    desc=("Build one record per DISTINCT scholarship/fellowship/funded position. Use only supplied evidence. Never invent a deadline. Preserve detected_deadline when provided. Prefer supplied URL as official_link. Target level: {level}\nRESULTS:\n{results}\nReturn ONLY JSON array with country, scholarship_name, provider, level, deadline, requirements, eligibility, documents, funding, benefits, official_link, application_link, confidence. Extract every requirement/eligibility/document/benefit explicitly supported by the supplied page evidence. Never guess.")
    data=_run_json(lambda:_architect(llm),desc,"JSON array.",dict(level=level,results=json.dumps(payload,ensure_ascii=False)))
    if isinstance(data,dict): data=data.get("records") or data.get("scholarships") or []
    out=[]
    for item in data if isinstance(data,list) else []:
        try: out.append(ScholarshipRecord(**item))
        except Exception: pass
    return out

def _gap_agent(llm): return Agent(role="Application Readiness Mentor",goal="Explain strengths, gaps and next actions without overclaiming.",backstory="Reason only from profile and scholarship evidence.",llm=llm,tools=[],allow_delegation=False,verbose=False,max_iter=2)
def _task_gap(profile,records,llm):
    payload=[{"url":r.official_link,"name":r.scholarship_name,"country":r.country,"level":r.level,"requirements":r.requirements} for r in records[:12]]
    desc=("Candidate profile: {profile}\nScholarships: {items}\nReturn JSON with strengths(3-5), gaps(3-5), recommendations(3-5), per_item. Each per_item has url, fit_score(0-100 AI-estimated), top_gaps(max3), fit_reasons(max3). Use known facts only.")
    data=_run_json(lambda:_gap_agent(llm),desc,"One JSON gap report.",dict(profile=profile.model_dump_json(),items=json.dumps(payload,ensure_ascii=False)))
    if isinstance(data,list): data={"per_item":data}
    return GapReport(**data)
def _heuristic_fit(profile,rec,level):
    text=f"{rec.scholarship_name} {rec.provider} {rec.country} {rec.level} {rec.requirements}".lower(); hits=0
    for kw in profile.keywords:
        words=re.findall(r"[a-z]{4,}",kw.lower())
        if words and any(w in text for w in words): hits+=1
    return max(0,min(100,30+7*hits+(10 if level.lower() in text else 0)))
def _post_verify(records,raw,profile,level):
    raw_by_url={tools.norm_url(r.url):r for r in raw}
    raw_by_url.update({tools.norm_url(r.final_url):r for r in raw if r.final_url}); out=[]; seen=set()
    for rec in records:
        key=tools.norm_url(rec.official_link) or re.sub(r"[^a-z0-9]+","",rec.scholarship_name.lower())
        if key in seen: continue
        seen.add(key); evidence=raw_by_url.get(tools.norm_url(rec.official_link))
        if evidence is None:
            evidence=next((x for x in raw if rec.scholarship_name.lower() in (x.title+" "+x.snippet).lower()),None)
        if evidence:
            v=tools.verify_page(rec.official_link,evidence.page_text,evidence.snippet)
            if v["deadline"]: rec.deadline=v["deadline"]
            rec.deadline_status=v["deadline_status"]; rec.days_remaining=v["days_remaining"]; rec.is_expired=v["is_expired"]; rec.deadline_verified=v["deadline_verified"]; rec.deadline_source=v["deadline_source"]; rec.verification_status=v["verification_status"]; rec.source_type=v["source_type"]; rec.link_verified=v.get("link_verified",False); rec.link_checked_at=v.get("link_checked_at","")
            rec.official_link=v.get("final_url") or rec.official_link
            if not rec.application_link: rec.application_link=evidence.application_link or tools.extract_application_link(rec.official_link)
        else:
            st,days,expired=tracker.classify_deadline(rec.deadline); rec.deadline_status=st; rec.days_remaining=days; rec.is_expired=expired; rec.verification_status="expired" if expired else "unverified"
            health=tools.inspect_url(rec.official_link) if rec.official_link else {"ok":False,"status":None,"final_url":"","checked_at":""}
            rec.link_verified=health.get("ok",False); rec.link_checked_at=health.get("checked_at","")
            if health.get("final_url"): rec.official_link=health["final_url"]
            if rec.official_link and not rec.application_link: rec.application_link=tools.extract_application_link(rec.official_link)
        if rec.is_expired: continue
        if not rec.fit_score: rec.fit_score=_heuristic_fit(profile,rec,level)
        rec.fit_level="High" if rec.fit_score>=70 else "Medium" if rec.fit_score>=45 else "Low"; out.append(rec)
    return out

def build_database_and_gaps(profile,raw,level,llm,parallel=False):
    warning=""
    if not raw:
        seeds=seed_records(level,profile.countries)
        return seeds,GapReport(gaps=["No live opportunity with a verifiable current cycle was found in this search."],recommendations=["Broaden countries/keywords or retry later, then verify seed hints on official sites."]),"No live current opportunities were verified. Seed discovery hints are shown separately and are not treated as current."
    try: records=_task_database(raw,level,llm)
    except Exception as exc:
        warning="Some scholarship details could not be fully organized, so we used the available source information. Please review the official pages before applying."
        records=[ScholarshipRecord(scholarship_name=r.title or urlparse(r.url).netloc,provider=urlparse(r.url).netloc.replace("www.",""),country=next((c for c in profile.countries if c.lower() in (r.title+" "+r.snippet).lower()),"Unknown"),level=level,deadline=r.deadline,official_link=r.url,confidence="low",notes="Auto-built from search evidence; review official page.") for r in raw]
    records=_post_verify(records,raw,profile,level)
    try: gap=_task_gap(profile,records,llm) if records else GapReport()
    except Exception as exc: gap=GapReport(); warning += " Some profile matching details could not be calculated, so the available results are shown without that extra comparison."
    by_url={tools.norm_url(x.url):x for x in gap.per_item if x.url}
    for rec in records:
        item=by_url.get(tools.norm_url(rec.official_link))
        if item:
            rec.fit_score=item.fit_score or rec.fit_score; rec.top_gaps=item.top_gaps; rec.fit_reasons=item.fit_reasons; rec.fit_level="High" if rec.fit_score>=70 else "Medium" if rec.fit_score>=45 else "Low"
    return records,gap,warning.strip()

def tracker_summary(df,llm): return tracker.plain_summary(df)
