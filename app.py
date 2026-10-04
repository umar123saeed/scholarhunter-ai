"""ScholarHunter Agents V3 - polished Streamlit experience."""
import os,sys
try:
    __import__("pysqlite3");sys.modules["sqlite3"]=sys.modules.pop("pysqlite3")
except Exception:pass
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY","true");os.environ.setdefault("CREWAI_TRACING_ENABLED","false");os.environ.setdefault("OTEL_SDK_DISABLED","true")
from datetime import datetime,timezone
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import crew as sh_crew, export, tracker
from tools import parse_cv

st.set_page_config(page_title="ScholarHunter AI",page_icon="🎓",layout="wide",initial_sidebar_state="expanded")
COUNTRIES=["United Kingdom","United States","Germany","Canada","Australia","China","Turkey","Hungary","Japan","South Korea","Sweden","Netherlands","France","Italy","Malaysia","Norway","Finland"]
DEFAULT={"profile":None,"raw":[],"queries":[],"all_df":None,"current_df":None,"verify_df":None,"expired_df":None,"work_df":None,"gap":None,"summary":"","warnings":[],"run_id":0,"export_csv":None,"export_xlsx":None,"last_checked":""}
for k,v in DEFAULT.items():st.session_state.setdefault(k,v)

def get_api_key():
    try:
        if "GROQ_API_KEY" in st.secrets:return str(st.secrets["GROQ_API_KEY"]).strip().strip('"').strip("'")
    except Exception:pass
    return os.getenv("GROQ_API_KEY","").strip()

def persist_frames(df):
    df=tracker.recompute(df);current,verify,expired=tracker.split_by_freshness(df)
    st.session_state.all_df=df;st.session_state.work_df=df;st.session_state.current_df=current;st.session_state.verify_df=verify;st.session_state.expired_df=expired
    st.session_state.export_csv=export.to_csv_bytes(df);st.session_state.export_xlsx=export.to_excel_bytes(df,st.session_state.gap)

def css():
    st.markdown("""<style>
    .stApp{background:linear-gradient(180deg,#f7fbff 0%,#ffffff 45%);color:#172033}
    .block-container{max-width:1450px;padding-top:1.2rem;padding-bottom:3rem}
    [data-testid="stSidebar"]{background:#101a2e;border-right:1px solid #243653}
    [data-testid="stSidebar"] *{color:#eef5ff!important}
    .hero{padding:30px 34px;border-radius:24px;background:linear-gradient(135deg,#12233f,#285a8f);color:white;box-shadow:0 18px 45px rgba(28,63,105,.18);margin-bottom:22px}
    .hero h1{font-size:42px;line-height:1.05;margin:0 0 10px;font-weight:800;letter-spacing:-1.5px}.hero p{margin:0;opacity:.88;font-size:17px}
    .pill{display:inline-block;padding:6px 11px;border-radius:999px;background:rgba(255,255,255,.13);margin:12px 6px 0 0;font-size:12px}
    .section-title{font-size:25px;font-weight:800;margin:18px 0 8px;color:#13243d}.muted{color:#66758b;font-size:14px}
    .card{background:white;border:1px solid #e4ebf3;border-radius:18px;padding:20px 22px;margin:12px 0;box-shadow:0 8px 25px rgba(34,56,82,.07)}
    .card h3{margin:0 0 5px;font-size:20px;color:#152844}.provider{color:#68788f;font-size:13px}.tag{display:inline-block;border:1px solid #dbe4ee;border-radius:999px;padding:4px 9px;margin:5px 5px 0 0;font-size:12px;background:#f8fbfe}
    .deadline{font-size:22px;font-weight:800;color:#173d68}.verified{color:#18794e;font-weight:700}.warning{color:#9b6500;font-weight:700}.score{font-size:28px;font-weight:900;color:#285a8f}
    .profilebox{background:#fff;border:1px solid #e3eaf2;border-radius:18px;padding:20px;box-shadow:0 7px 24px rgba(34,56,82,.06)}
    .metricbox{background:#fff;border:1px solid #e3eaf2;border-radius:16px;padding:16px 18px;min-height:90px}.metricnum{font-size:28px;font-weight:900;color:#1d4f7a}.metriclabel{font-size:12px;color:#718096;text-transform:uppercase;letter-spacing:.5px}
    .stButton>button{border-radius:11px;font-weight:700}.stDownloadButton>button{border-radius:11px}

    /* Sidebar form controls: keep the white fields readable. */
    [data-testid="stFileUploader"] *,
    [data-testid="stFileUploaderDropzone"] *{
        color:#111827 !important;
    }
    [data-testid="stFileUploaderDropzone"]{
        background:#ffffff !important;
        border:1px solid #d7e0ea !important;
    }
    [data-testid="stTextArea"] textarea,
    [data-testid="stTextInput"] input{
        color:#111827 !important;
        background:#ffffff !important;
        -webkit-text-fill-color:#111827 !important;
    }
    [data-testid="stTextArea"] textarea::placeholder,
    [data-testid="stTextInput"] input::placeholder{
        color:#667085 !important;
        opacity:1 !important;
    }
    [data-baseweb="select"] *,
    [data-baseweb="multi-select"] *{
        color:#111827 !important;
    }
    </style>""",unsafe_allow_html=True)
css()

st.markdown('''<div class="hero"><h1>🎓 ScholarHunter AI</h1><p>Your personal scholarship intelligence workspace — discover relevant opportunities, verify live sources, understand your fit, and track applications.</p><span class="pill">Multi-Agent AI</span><span class="pill">Live web discovery</span><span class="pill">Evidence-first</span><span class="pill">Application tracker</span></div>''',unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## 🎯 Build your profile")
    st.caption("Add a little information about your studies so we can find scholarships that match you.")
    cv_file=st.file_uploader("CV / Resume",type=["pdf","txt"])
    interests=st.text_area("Research interests",placeholder="e.g. Generative AI, NLP, Computer Vision",height=95)
    domain=st.text_input("Target field / domain",placeholder="e.g. Artificial Intelligence")
    level=st.selectbox("Study level",["MS","PhD","Postdoc"])
    selected=st.multiselect("Preferred countries",COUNTRIES,default=["United Kingdom","Germany","Turkey"])
    custom=st.text_input("Other countries",placeholder="Pakistan, Sweden")
    max_searches=st.slider("Live searches",1,5,4,help="More searches can find more opportunities, but may take a little longer.")
    run_clicked=st.button("🚀 Find My Scholarships",type="primary",use_container_width=True)
    if st.session_state.last_checked: st.caption(f"Last run: {st.session_state.last_checked}")

def execute():
    api_key=get_api_key();countries=list(dict.fromkeys(selected+[c.strip() for c in custom.split(",") if c.strip()]))
    if not api_key:st.error("GROQ_API_KEY is missing. Add it to .env locally or Streamlit Secrets when deployed.");return
    if not cv_file and not interests.strip():st.error("Upload a CV or enter research interests first.");return
    if not countries:st.error("Select at least one country.");return
    cv_text=""
    if cv_file:
        try:cv_text=parse_cv(cv_file,cv_file.name)
        except Exception:st.error("We could not read that CV. Please try a PDF or TXT file with readable text.");return
    with st.status("ScholarHunter is working…",expanded=True) as status:
        try:
            llm=sh_crew.get_llm(api_key)
            st.write("① Profile Analyst — understanding your academic profile")
            profile=sh_crew.analyze_profile(cv_text,interests,domain,countries,level,llm)
            st.write("② Opportunity Scout — discovering current opportunities")
            raw,queries,warn=sh_crew.scout_opportunities(profile,level,max_searches,llm)
            st.write("③ Scholarship details — checking requirements and your match")
            records,gap,warn2=sh_crew.build_database_and_gaps(profile,raw,level,llm)
            st.write("④ Final check — organizing deadlines and application status")
            df=tracker.apply_state(tracker.records_to_df(records))
            st.session_state.profile=profile;st.session_state.raw=raw;st.session_state.queries=queries;st.session_state.gap=gap;st.session_state.warnings=[x for x in (warn,warn2) if x];st.session_state.summary=tracker.plain_summary(df);st.session_state.run_id+=1;st.session_state.last_checked=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC");persist_frames(df)
            status.update(label=f"Done — {len(df)} opportunities processed",state="complete",expanded=False)
        except Exception:
            status.update(label="Something went wrong",state="error")
            st.error("We could not complete the search right now. Please check your information and try again.")
if run_clicked:execute()

profile=st.session_state.profile;work=st.session_state.work_df;current=st.session_state.current_df;verify=st.session_state.verify_df;gap=st.session_state.gap
if profile:
    st.markdown('<div class="section-title">👤 Your profile</div>',unsafe_allow_html=True)
    pcols=st.columns([1.4,1,1,1])
    with pcols[0]:
        name=profile.name or "Candidate";field=profile.field_of_study or profile.target_domain or "Academic profile"
        st.markdown(f'<div class="profilebox"><b style="font-size:22px">{name}</b><br><span class="muted">{field}</span><br><br><b>Level:</b> {profile.target_level or "—"}<br><b>Degree:</b> {profile.highest_degree or "—"}<br><b>Institution:</b> {profile.institution or "—"}</div>',unsafe_allow_html=True)
    with pcols[1]:st.markdown(f'<div class="metricbox"><div class="metricnum">{profile.gpa or "—"}</div><div class="metriclabel">GPA / CGPA</div></div>',unsafe_allow_html=True)
    with pcols[2]:st.markdown(f'<div class="metricbox"><div class="metricnum">{len(profile.skills)}</div><div class="metriclabel">Skills detected</div></div>',unsafe_allow_html=True)
    with pcols[3]:st.markdown(f'<div class="metricbox"><div class="metricnum">{len(profile.research_interests)}</div><div class="metriclabel">Research interests</div></div>',unsafe_allow_html=True)
    interests_show=profile.research_interests or profile.keywords
    if interests_show: st.markdown(" ".join(f'<span class="tag">{x}</span>' for x in interests_show[:12]),unsafe_allow_html=True)

if work is not None:
    c=tracker.status_counts(work);m=st.columns(5)
    for col,num,label in zip(m,[len(current) if current is not None else 0,c["critical"],c["preparing"],c["applied"],len(verify) if verify is not None else 0],["Live opportunities","Urgent deadlines","Preparing","Applied / Submitted","Needs verification"]):
        col.markdown(f'<div class="metricbox"><div class="metricnum">{num}</div><div class="metriclabel">{label}</div></div>',unsafe_allow_html=True)

st.markdown('<div class="section-title">🔎 Scholarship discovery</div>',unsafe_allow_html=True)
if current is None:
    st.info("Start from the sidebar: upload your CV and/or enter your research interests, choose countries, then click **Find My Scholarships**.")
else:
    st.caption("We separate current opportunities from results that need checking. Always confirm the final eligibility and deadline on the official page before applying.")
    if st.session_state.warnings:
        for w in st.session_state.warnings:st.warning(w)
    if current.empty:st.warning("No opportunity with a currently usable deadline/rolling status was verified. Check Needs Verification or broaden your search.")
    for _,r in current.sort_values(["fit_score","days_remaining"],ascending=[False,True]).iterrows():
        deadline_text="Rolling / year-round" if r["deadline_status"]=="rolling" else (str(r["deadline"]) if pd.notna(r["deadline"]) else "Needs verification")
        link_state="✓ Source reachable when checked" if bool(r.get("link_verified")) else "⚠ Source link could not be fully verified"
        source=r.get("official_link") or ""
        apply_link=r.get("application_link") or ""
        st.markdown(f'''<div class="card"><div style="display:flex;justify-content:space-between;gap:18px"><div><h3>{r["scholarship_name"]}</h3><div class="provider">{r["provider"]} · {r["country"]} · {r["level"]}</div></div><div style="text-align:right"><div class="score">{int(r["fit_score"])}%</div><div class="muted">profile match</div></div></div><hr style="border:none;border-top:1px solid #edf1f5"><div style="display:grid;grid-template-columns:1fr 1fr;gap:18px"><div><div class="muted">DEADLINE</div><div class="deadline">{deadline_text}</div><div class="{'verified' if r['deadline_verified'] else 'warning'}">{'✓ Verified from source page' if r['deadline_verified'] else '⚠ Needs verification'}</div></div><div><div class="muted">SOURCE</div><div class="{'verified' if r.get('link_verified') else 'warning'}">{link_state}</div><div class="muted" style="margin-top:6px">Confidence: {r.get('confidence','low').title()}</div></div></div></div>''',unsafe_allow_html=True)
        cols=st.columns([1,1,1,1])
        if source:cols[0].link_button("🌐 Official scholarship page",source,use_container_width=True)
        if apply_link:cols[1].link_button("📝 Application page",apply_link,use_container_width=True)
        cols[2].markdown(f"**Urgency:** {r['urgency']}")
        cols[3].markdown(f"**Status:** {r['status']}")
        with st.expander("View full scholarship details & your match"):
            a,b=st.columns(2)
            with a:
                st.markdown("**Requirements**");st.write(r.get("requirements") or "Not clearly extracted from source.")
                st.markdown("**Eligibility**");st.write(r.get("eligibility") or "Not clearly extracted from source.")
                st.markdown("**Documents**");st.write(r.get("documents") or "Not clearly extracted from source.")
            with b:
                st.markdown("**Funding / benefits**");st.write(r.get("funding") or r.get("benefits") or "Not clearly extracted from source.")
                st.markdown("**Why it matches you**");st.write(r.get("fit_reasons") or "No specific reasons returned.")
                st.markdown("**Potential gaps**");st.write(r.get("top_gaps") or "No specific gaps returned.")
                st.caption("AI match is an estimate based on the supplied profile and extracted scholarship evidence — not an admission decision.")

# Secondary workspace
if work is not None:
    tabs=st.tabs(["📊 Your Match","📌 Application Tracker","⚠️ Needs Verification","📤 Export"])
    with tabs[0]:
        if gap:
            a,b,c=st.columns(3)
            with a:
                st.markdown("### Strengths");[st.success(x) for x in (gap.strengths or ["No strong evidence returned."])]
            with b:
                st.markdown("### Gaps");[st.warning(x) for x in (gap.gaps or ["No major gap was identified."])]
            with c:
                st.markdown("### Next actions");[st.info(x) for x in (gap.recommendations or ["Review the requirements of your shortlisted opportunities."])]
    with tabs[1]:
        st.markdown("### Track your applications")
        editable=work[[c for c in ["scholarship_name","country","deadline","days_remaining","urgency","status","notes","official_link"] if c in work.columns]].copy()
        edited=st.data_editor(editable,hide_index=True,use_container_width=True,column_config={"official_link":st.column_config.LinkColumn("Official",display_text="Open"),"status":st.column_config.SelectboxColumn("Status",options=tracker.STATUSES)},disabled=[c for c in editable.columns if c not in {"status","notes"}],key=f"tracker_{st.session_state.run_id}")
        if st.button("💾 Save tracker changes"):
            master=work.copy()
            for _,row in pd.DataFrame(edited).iterrows():
                mask=master["scholarship_name"]==row["scholarship_name"]
                master.loc[mask,"status"]=row["status"];master.loc[mask,"notes"]=row["notes"]
            tracker.save_state(master);persist_frames(master);st.success("Tracker saved.")
    with tabs[2]:
        if verify is None or verify.empty:st.success("No uncertain opportunities in this run.")
        else:
            st.info("These opportunities need a quick manual check because we could not confirm enough current information from the source page.")
            st.dataframe(verify[[c for c in ["scholarship_name","country","deadline","verification_status","link_verified","confidence","official_link","application_link"] if c in verify.columns]],hide_index=True,use_container_width=True,column_config={"official_link":st.column_config.LinkColumn("Official",display_text="Open"),"application_link":st.column_config.LinkColumn("Apply",display_text="Open")})
        expired=st.session_state.expired_df
        with st.expander(f"Expired / historical ({0 if expired is None else len(expired)})"):
            if expired is not None and not expired.empty:st.dataframe(expired[[c for c in ["scholarship_name","country","deadline","official_link"] if c in expired.columns]],hide_index=True,use_container_width=True)
            else:st.write("No expired opportunities to show.")
    with tabs[3]:
        st.caption("Download your scholarship results and application notes for later review.")
        st.download_button("⬇️ Download Excel",st.session_state.export_xlsx,"scholarhunter.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
        st.download_button("⬇️ Download CSV",st.session_state.export_csv,"scholarhunter.csv","text/csv",use_container_width=True)
