"""Regression checks for production fixes (language, disposition, display helpers)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_rules import detect_call_kpis, resolve_disposition


def test_ritika_not_language_issue():
    t = """Agent: Hello, hmm, hello, is this Digendra Vishwakarma speaking?
Customer: Yes, please speak.
Agent: Good afternoon sir, I am Ritika speaking, a call is being recorded on behalf of the Tala application.
Agent: Your payment for the Tala application is pending, sir.
Customer: Oh ma'am, tell me how that app is not downloading.
Agent: There is an issue with the application, sir."""
    kpis = detect_call_kpis(t, filename_hint="1899703-RITIKA.wav")
    disp = resolve_disposition(t, kpis)
    assert disp != "LANGUAGE_ISSUE", f"expected not LANGUAGE_ISSUE, got {disp}"
    assert disp in ("NO_PTP", "APP_ISSUE", "OTHER", "CALLBACK"), disp


def test_language_only_from_customer():
    agent_only = """Agent: This call is being recorded on behalf of the Tala application.
Agent: Please speak in your preferred language for training purposes."""
    kpis = detect_call_kpis(agent_only)
    assert "LANGUAGE_ISSUE" not in (kpis.get("dispositions") or [])

    customer = """Agent: Hello sir.
Customer: Hindi nahi aati, English only."""
    kpis2 = detect_call_kpis(customer)
    assert "LANGUAGE_ISSUE" in (kpis2.get("dispositions") or [])


def test_client_display_scale():
    from client_display import scale_kpi_score

    os.environ["CARE_KPI_DISPLAY_MAX"] = "10"
    s, m = scale_kpi_score(2, 3)
    assert m == 10
    assert s == 7  # 2/3 * 10 rounded


if __name__ == "__main__":
    test_ritika_not_language_issue()
    test_language_only_from_customer()
    test_client_display_scale()
    print("All production fix tests passed.")
