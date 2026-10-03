# ScholarHunter AI — V3

A polished Streamlit + CrewAI multi-agent scholarship discovery workspace for the Cohort 11 hackathon.

## What changed in V3

- Redesigned product-style UI instead of a plain Streamlit dashboard.
- Candidate profile is shown first so the user can understand what the agents extracted.
- Scholarship cards show profile match, deadline, urgency, source health, official page and application page.
- Rich evidence fields: requirements, eligibility, documents, funding/benefits, match reasons and potential gaps.
- Runtime HTTP checks for source links and redirects; the UI labels whether the source was reachable when checked.
- Application-link discovery from official pages where an application CTA can be found and the link is reachable.
- Known scholarship aggregators are excluded from the evidence pipeline rather than being treated as official sources.
- More source-page text is passed to the evidence agent so requirements are less likely to be truncated.
- Tracker editing is explicit: changes are saved with a button rather than on every widget rerun.
- Search Evidence tab makes the Scout's actual queries visible for demos/debugging.
- Existing agent architecture, gap analysis, tracker and Excel/CSV export are retained.

## Important link/deadline behavior

The app does **not** claim that a link will remain valid forever. At every run it checks the HTTP source at runtime, follows redirects, and records the time/status of the check. A scholarship is only shown as a current opportunity when its deadline is upcoming or explicitly rolling. Unknown deadlines go to **Needs Verification** and expired deadlines are separated.

Always confirm the final eligibility and deadline on the official page before submitting an application.

## Architecture

```text
CV + interests + target domain + countries
                  |
          Profile Analyst Agent
                  |
          Opportunity Scout Agent
                  |
       Web search + page fetching
                  |
     Deterministic source/link/deadline checks
                  |
       Database & Evidence Agent
                  |
          Gap / Fit Mentor Agent
                  |
            Tracker / Export
```

## Local setup

Python 3.11 is recommended.

```bash
python -m venv .venv
# Windows PowerShell
.venv\\Scripts\\Activate.ps1
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
```

Create `.env`:

```text
GROQ_API_KEY=your_real_key
GROQ_MODEL=groq/openai/gpt-oss-120b
```

Run:

```bash
streamlit run app.py
```

## Test suite

```bash
pip install pytest
pytest -q
```

The included tests cover deadline classification/extraction and freshness filtering. The app itself also needs the dependencies in `requirements.txt` before it can be imported/run.

## GitHub

From the project root:

```bash
git init
git add .
git commit -m "ScholarHunter AI V3"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

Do **not** commit `.env` or API keys.

## Streamlit Community Cloud

1. Push the project to GitHub.
2. Open Streamlit Community Cloud and create a new app.
3. Select the repository, branch `main`, and main file `app.py`.
4. In App Settings → Secrets, add:

```toml
GROQ_API_KEY = "your_real_key"
GROQ_MODEL = "groq/openai/gpt-oss-120b"
```

5. Deploy.

If the chosen Groq model ID changes, update the secret rather than hard-coding a new key into the repository.

## Demo flow

1. Upload a CV.
2. Enter research interests and choose countries.
3. Click **Find My Scholarships**.
4. Show the extracted profile.
5. Show live scholarship cards and source/application links.
6. Open a card to explain requirements, eligibility, funding and profile fit.
7. Show Gap Analysis.
8. Update the Application Tracker and save it.
9. Show Needs Verification to demonstrate conservative handling of uncertain sources.
10. Export Excel/CSV.
