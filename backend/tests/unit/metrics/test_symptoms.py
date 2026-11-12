from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.domain.associations import preceding_sessions
from app.metrics.symptoms import CheckinIn, ReportIn, activity_outcome, bucket, run_end, window_outcome

END = datetime(2026, 11, 15, 15, tzinfo=UTC)


def checkin(when: datetime, kind: str, severity: float, timing: str, gait: str | None = None,
            site: str = " Medial Ankle ", id_: str = "c1") -> CheckinIn:
    report = ReportIn(id_, when, kind, gait, site, "left", severity, timing)
    return CheckinIn(id_, when, kind, gait, [report])


def test_hours_and_buckets() -> None:
    row = checkin(datetime(2026, 11, 16, 23, tzinfo=UTC), "post_run", 4, "hours_24_48", "yes")
    result = activity_outcome(END, False, [row])
    assert result["value"]["reports"][0]["hours_after_end"] == 32.0
    assert result["value"]["sites"][0]["site"] == "medial ankle"
    assert result["value"]["sites"][0]["max_severity_24_48h"] == 4.0
    assert result["value"]["sites"][0]["max_severity_0_24h"] is None
    assert result["value"]["gait_change"] == "yes"
    assert result["quality_flags"] == ["DELAYED_FOLLOWUP_MISSING"]
    assert bucket("unknown", 25.5) == "24_48"


def test_unknown_timing_thresholds_use_unrounded_hours() -> None:
    before_24 = checkin(END.replace(day=16, hour=14, minute=59, second=40), "post_run", 2, "unknown")
    after_48 = checkin(END.replace(day=17, hour=15, minute=0, second=20), "post_run", 3, "unknown", id_="c2")
    result = activity_outcome(END, False, [before_24, after_48])
    assert result["value"]["sites"][0]["max_severity_0_24h"] == 2.0
    assert result["value"]["sites"][0]["max_severity_24_48h"] is None


def test_immediate_and_delayed_no_score() -> None:
    rows = [checkin(datetime(2026, 11, 15, 16, tzinfo=UTC), "post_run", 3, "immediately_after"),
            checkin(datetime(2026, 11, 16, 21, tzinfo=UTC), "delayed_followup", 4, "hours_24_48", id_="c2")]
    result = activity_outcome(END, False, rows)
    assert [r["timing"] for r in result["value"]["reports"]] == ["immediately_after", "hours_24_48"]
    assert result["value"]["sites"][0]["max_severity_0_24h"] == 3.0
    assert result["value"]["sites"][0]["max_severity_24_48h"] == 4.0
    assert result["value"]["delayed_followup_answered"] is True
    assert result["quality_flags"] == []
    assert not any("score" in key for key in result["value"])


def test_unknown_end_and_no_checkin() -> None:
    assert run_end(END, None, 3000) == (None, True)
    assert activity_outcome(None, True, [])["reason_codes"] == ["NO_LINKED_CHECKIN"]
    row = checkin(END, "post_run", 3, "unknown")
    result = activity_outcome(None, True, [row])
    assert result["quality_flags"][0] == "END_TIME_UNKNOWN"
    assert result["value"]["reports"][0]["hours_after_end"] is None
    assert bucket("unknown", None) == "unknown"


def test_gait_and_recurrence() -> None:
    first = checkin(datetime(2026, 11, 1, tzinfo=UTC), "post_run", 2, "during", "no")
    second = checkin(datetime(2026, 11, 1, 1, tzinfo=UTC), "post_run", 0, "during", "unsure", id_="c2")
    third = checkin(datetime(2026, 11, 5, tzinfo=UTC), "post_run", 3, "later", id_="c3")
    assert activity_outcome(END, False, [first, second])["value"]["gait_change"] == "unsure"
    result = window_outcome([first, second, third], ZoneInfo("UTC"))
    assert result["value"]["sites"][0]["recurrence_days"] == 2
    assert result["value"]["sites"][0]["report_count"] == 3
    assert result["value"]["sites"][0]["max_severity"] == 3.0
    assert window_outcome([], ZoneInfo("UTC"))["reason_codes"] == ["NO_CHECKINS_IN_WINDOW"]


def test_preceding_association_uses_known_end() -> None:
    observed = datetime(2026, 11, 17, tzinfo=UTC)
    sessions = [{"id": str(i), "start_at": observed.replace(day=16), "elapsed_s": 3600,
                 "sport": "running"} for i in (1, 2)]
    sessions[0]["start_at"] = observed.replace(day=16, hour=13)
    sessions[1]["start_at"] = observed.replace(day=16, hour=17)
    hits = preceding_sessions(observed, sessions, "UTC", hours=48)
    assert hits[0]["activity_id"] == "2"
