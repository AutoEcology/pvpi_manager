"""Schedules: when they're on, when they next turn on, the wake alarm, and what's refused."""

import time as time_module
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from pvpi.schedule import Schedule, find_place

MON = datetime(2026, 10, 19)  # a Monday


def at(hhmm: str, days: int = 0) -> datetime:
    return datetime.combine(MON.date(), time.fromisoformat(hhmm)) + timedelta(days=days)


def schedule(*rules) -> Schedule:
    return Schedule.model_validate({"rules": list(rules)})


DAY = {"kind": "daily", "on": "07:00", "off": "19:00"}
NIGHT = {"kind": "daily", "on": "22:00", "off": "02:00"}  # across midnight
WEEKDAYS = {"kind": "daily", "on": "09:00", "off": "10:00", "days": ["mon", "tue", "wed", "thu", "fri"]}
CYCLE = {"kind": "periodic", "on_for_mins": 5, "off_for_mins": 5, "start": "07:00", "end": "08:00"}
ALL_DAY_CYCLE = {"kind": "periodic", "on_for_mins": 5, "off_for_mins": 5}


@pytest.mark.parametrize(
    "rules, moment, on",
    [
        ([], at("03:00"), True),  # no rules: always on
        ([DAY], at("06:59:59"), False),
        ([DAY], at("07:00"), True),
        ([DAY], at("19:00"), False),
        ([NIGHT], at("01:59", days=1), True),
        ([NIGHT], at("02:00", days=1), False),
        ([NIGHT], at("01:00"), True),  # the period that began on Sunday night
        ([WEEKDAYS], at("09:30", days=5), False),  # Saturday
        ([CYCLE], at("07:04"), True),
        ([CYCLE], at("07:05"), False),
        ([CYCLE], at("07:10"), True),
        ([CYCLE], at("08:00"), False),  # past its end
        ([ALL_DAY_CYCLE], at("13:17"), False),  # the cycle keeps its place from midnight
        ([DAY, CYCLE], at("07:06"), True),  # on whenever any rule is
    ],
)
def test_is_on(rules, moment, on):
    assert schedule(*rules).is_on(moment) is on


@pytest.mark.parametrize(
    "rules, moment, wake",
    [
        ([], at("03:00"), None),
        ([DAY], at("19:00"), at("07:00", days=1)),
        ([DAY, {"kind": "daily", "on": "12:00", "off": "13:00"}], at("19:00"), at("07:00", days=1)),
        ([CYCLE], at("07:05"), at("07:10")),
        ([CYCLE], at("08:00"), at("07:00", days=1)),
        ([WEEKDAYS], at("10:00", days=4), at("09:00", days=7)),  # Friday to Monday
    ],
)
def test_next_on(rules, moment, wake):
    assert schedule(*rules).next_on(moment) == wake


def test_the_alarm_is_never_a_day_or_more_ahead():
    weekdays = schedule(WEEKDAYS)
    assert weekdays.alarm(at("10:00")) == at("09:00", days=1)
    friday = at("10:00", days=4)
    assert weekdays.alarm(friday) == friday + timedelta(hours=23)  # it wakes, finds it's off, sleeps again


def test_overlapping_periods_join():
    periods = schedule(DAY, {"kind": "daily", "on": "18:00", "off": "20:00"}).periods(at("00:00"), at("23:59"))
    assert periods == [(at("07:00"), at("20:00"))]


@pytest.mark.parametrize(
    "rules, problems",
    [
        ([DAY], 0),
        ([], 0),
        ([CYCLE], 0),
        ([{"kind": "periodic", "on_for_mins": 5, "off_for_mins": 1}], 6),  # 1 min off is too short (5 + "and more")
        ([{"kind": "daily", "on": "07:00", "off": "07:01"}], 7),  # 1 min on, every day
        ([{"kind": "daily", "on": "07:00", "off": "06:59"}], 7),  # 1 min off, every day
        ([{"kind": "daily", "on": "07:00", "off": "19:00", "days": []}], 1),  # never on
    ],
)
def test_unworkable_periods_are_found(rules, problems):
    found = schedule(*rules).problems(min_on=timedelta(minutes=2), min_off=timedelta(minutes=2))
    assert len(found) == min(problems, 6)


@pytest.mark.parametrize(
    "rule",
    [
        {"kind": "daily", "on": "07:00", "off": "07:00"},
        {"kind": "daily", "on": "25:00", "off": "07:00"},
        {"kind": "daily", "on": "07:00", "off": "19:00", "days": ["monday"]},
        {"kind": "periodic", "on_for_mins": 0, "off_for_mins": 5},
        {"kind": "hourly", "on": "07:00"},
        {"kind": "daily", "on": "07:00", "off": "19:00", "extra": 1},
    ],
)
def test_bad_rules_are_refused(rule):
    with pytest.raises(ValidationError):
        schedule(rule)


def test_a_saved_schedule_reads_back(tmp_path):
    path = tmp_path / "schedules" / "field.json"
    schedule(DAY, CYCLE).save(path)
    assert Schedule.load(path) == schedule(DAY, CYCLE)
    assert not list(path.parent.glob(".*.tmp"))


DEMOS = sorted((Path(__file__).parent.parent / "schedules").glob("*.json"))


@pytest.mark.parametrize("path", DEMOS, ids=[p.stem for p in DEMOS])
def test_every_demo_schedule_works_with_the_default_config(path):
    from pvpi.config import PvPiConfig

    config = PvPiConfig(location="Melbourne")  # for the sunrise and sunset demos
    assert config.check_schedule(Schedule.load(path)) == []


def test_there_are_demo_schedules():
    assert len(DEMOS) >= 6


@pytest.fixture
def melbourne(monkeypatch):
    """Times in Melbourne's zone, and its coordinates."""
    monkeypatch.setenv("TZ", "Australia/Melbourne")
    time_module.tzset()
    yield find_place("Melbourne")
    monkeypatch.undo()
    time_module.tzset()


@pytest.mark.parametrize(
    "rule, begin, end",
    [
        ({"on": "sunrise", "off": "sunset"}, "sunrise", "sunset"),
        ({"on": "sunset", "off": "sunrise"}, "sunset", "sunrise+1"),  # the night, into the next morning
        ({"on": "sunrise", "on_offset_mins": -30, "off": "sunset", "off_offset_mins": 15}, "sunrise-30", "sunset+15"),
    ],
)
def test_sun_rules_follow_sunrise_and_sunset(melbourne, rule, begin, end):
    from zoneinfo import ZoneInfo

    from astral import Observer
    from astral.sun import sunrise, sunset

    def when(text):  # worked out by astral in Melbourne's zone, without the rule's own conversion
        event, _, shift = text.replace("-", "+-").partition("+")
        day = date(2026, 11, 2) + timedelta(days=1 if text == "sunrise+1" else 0)
        find = sunrise if event == "sunrise" else sunset
        found = find(Observer(*melbourne), day, tzinfo=ZoneInfo("Australia/Melbourne")).replace(tzinfo=None)
        return found + timedelta(minutes=int(shift) if shift not in ("", "1") else 0)

    made = schedule({"kind": "sun", **rule}).at_place(melbourne)
    (found,) = [
        p for p in made.periods(datetime(2026, 11, 2), datetime(2026, 11, 4)) if p[0].date() == date(2026, 11, 2)
    ]
    assert abs(found[0] - when(begin)) < timedelta(minutes=1) and abs(found[1] - when(end)) < timedelta(minutes=1)


def test_a_sun_rule_needs_a_location_and_refuses_the_same_event_twice():
    made = schedule({"kind": "sun", "on": "sunrise", "off": "sunset"})
    assert "location" in made.problems(timedelta(minutes=1), timedelta(minutes=1))[0]
    with pytest.raises(ValidationError):
        schedule({"kind": "sun", "on": "sunrise", "off": "sunrise"})
