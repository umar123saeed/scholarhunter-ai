import pandas as pd
import tracker

def test_split_freshness():
    df=pd.DataFrame([
        {"scholarship_name":"A","deadline":"2099-01-01","deadline_status":"upcoming","status":"Not Started","fit_score":50,"notes":""},
        {"scholarship_name":"B","deadline":"2001-01-01","deadline_status":"expired","status":"Not Started","fit_score":50,"notes":""},
        {"scholarship_name":"C","deadline":None,"deadline_status":"unknown","status":"Not Started","fit_score":50,"notes":""},
    ])
    current, verify, expired = tracker.split_by_freshness(df)
    assert current["scholarship_name"].tolist()==["A"]
    assert expired["scholarship_name"].tolist()==["B"]
    assert verify["scholarship_name"].tolist()==["C"]
