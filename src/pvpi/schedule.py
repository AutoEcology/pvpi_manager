"""Power schedules: the times the Pi is on. Outside them the manager shuts it down, and sets the
PV PI's wake alarm for the next time on.

A schedule is a JSON file of rules, e.g.:

    {"rules": [
        {"kind": "daily", "on": "07:00", "off": "12:00", "days": ["mon", "tue", "wed", "thu", "fri"]},
        {"kind": "periodic", "on_for_mins": 5, "off_for_mins": 5, "start": "07:00", "end": "19:00"}
    ]}

The Pi is on whenever any rule says so; a schedule with no rules is always on. Each kind of rule
only says which periods it turns on in a day, so a new kind needs only its own class here.
"""

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAYS: list[Day] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MAX_ALARM_AHEAD = timedelta(hours=23)  # the wake alarm is a time of day, so it can't be a day or more ahead
_LOOK_AHEAD_DAYS = 8  # far enough to find the next change of any weekly schedule

Period = tuple[datetime, datetime]


def _span(day: date, start: time, end: time) -> Period:
    """From `start` to `end` on `day`, into the next day when `end` is at or before `start`."""
    begin, finish = datetime.combine(day, start), datetime.combine(day, end)
    return begin, finish if finish > begin else finish + timedelta(days=1)


class _Rule(BaseModel, extra="forbid"):
    days: list[Day] = Field(default_factory=lambda: list(DAYS), description="The days it starts on")

    def periods(self, day: date) -> list[Period]:
        """The periods it turns on that start on `day`."""
        return self._periods(day) if DAYS[day.weekday()] in self.days else []

    def _periods(self, day: date) -> list[Period]:
        raise NotImplementedError


class Daily(_Rule):
    """On from one time of day to another (into the next day if `off` is earlier than `on`)."""

    kind: Literal["daily"] = "daily"
    on: time = Field(description="Turn on at")
    off: time = Field(description="Turn off at")

    @model_validator(mode="after")
    def _not_empty(self):
        if self.on == self.off:
            raise ValueError(f"on and off are both {self.on}: a daily rule needs two different times")
        return self

    def _periods(self, day: date) -> list[Period]:
        return [_span(day, self.on, self.off)]


class Periodic(_Rule):
    """On and off in turn, e.g. 5 minutes on then 5 off, between `start` and `end` (all day when
    they're the same). The cycle begins at `start` each day, so the clock alone says where in it
    the Pi is, also after a reboot."""

    kind: Literal["periodic"] = "periodic"
    on_for_mins: float = Field(gt=0, description="Minutes on in each cycle")
    off_for_mins: float = Field(gt=0, description="Minutes off in each cycle")
    start: time = Field(time(0, 0), description="The cycle runs from")
    end: time = Field(time(0, 0), description="The cycle runs until")

    def _periods(self, day: date) -> list[Period]:
        begin, finish = _span(day, self.start, self.end)
        on, cycle = timedelta(minutes=self.on_for_mins), timedelta(minutes=self.on_for_mins + self.off_for_mins)
        found = []
        while begin < finish:
            found.append((begin, min(begin + on, finish)))
            begin += cycle
        return found


Rule = Annotated[Daily | Periodic, Field(discriminator="kind")]


def _duration(span: timedelta) -> str:
    secs = int(span.total_seconds())
    hours, rest = divmod(secs, 3600)
    mins, secs = divmod(rest, 60)
    return " ".join(f"{n} {unit}" for n, unit in ((hours, "h"), (mins, "min"), (secs, "s")) if n) or "0 s"


class Schedule(BaseModel, extra="forbid"):
    rules: list[Rule] = Field(default_factory=list, description="On whenever any rule is on; always on with none")

    @classmethod
    def load(cls, path: Path) -> "Schedule":
        return cls.model_validate(json.loads(Path(path).read_text()))

    def save(self, path: Path) -> None:
        """Write it as JSON, replacing the file in one step so the manager never reads half of it."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(self.model_dump(mode="json"), indent=2) + "\n")
        tmp.replace(path)

    @property
    def always_on(self) -> bool:
        return not self.rules

    def periods(self, start: datetime, end: datetime) -> list[Period]:
        """The on periods that overlap `start` to `end`, joined where they meet or overlap."""
        found = []
        day = start.date() - timedelta(days=1)  # a period that began the day before may still run
        while day <= end.date():
            found += [p for rule in self.rules for p in rule.periods(day) if p[1] > start and p[0] < end]
            day += timedelta(days=1)
        merged: list[Period] = []
        for begin, finish in sorted(found):
            if merged and begin <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], finish))
            else:
                merged.append((begin, finish))
        return merged

    def is_on(self, at: datetime) -> bool:
        return self.always_on or any(
            begin <= at < finish for begin, finish in self.periods(at, at + timedelta(seconds=1))
        )

    def next_on(self, at: datetime) -> datetime | None:
        """When it next turns on after `at` (None if never)."""
        if self.always_on:
            return None
        starts = [begin for begin, _ in self.periods(at, at + timedelta(days=_LOOK_AHEAD_DAYS)) if begin > at]
        return starts[0] if starts else None

    def alarm(self, at: datetime) -> datetime | None:
        """When the wake alarm should go off for a shutdown at `at`: the next time on, or, when that's
        too far ahead for the alarm, as late as it can be (the Pi then wakes, finds it's still off
        and shuts down again)."""
        wake = self.next_on(at)
        return None if wake is None else min(wake, at + MAX_ALARM_AHEAD)

    def problems(self, min_on: timedelta, min_off: timedelta) -> list[str]:
        """What makes it unworkable: on or off periods too short for the Pi to start up or shut
        down in. Checked over a whole week."""
        if self.always_on:
            return []
        monday = datetime.combine(date(2024, 1, 1), time(0, 0))  # any Monday
        periods = self.periods(monday - timedelta(days=7), monday + timedelta(days=14))
        if not periods:
            return ["No rule ever turns the Pi on"]
        found = []
        for (begin, finish), following in zip(periods, [*periods[1:], None], strict=True):
            if not monday <= begin < monday + timedelta(days=7):
                continue
            if finish - begin < min_on:
                found.append(
                    f"On {begin:%a %H:%M:%S} for {_duration(finish - begin)}: on periods need at least "
                    f"{_duration(min_on)} for the Pi to start up"
                )
            if following and following[0] - finish < min_off:
                found.append(
                    f"Off {finish:%a %H:%M:%S} for {_duration(following[0] - finish)}: off periods need at least "
                    f"{_duration(min_off)} for the Pi to shut down and the power to go off"
                )
        if len(found) > 5:
            found = [*found[:5], f"and {len(found) - 5} more like these"]
        return found
