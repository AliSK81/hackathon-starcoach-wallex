"""How fast to trade, from the time left until trading ends (D45).

The time left sets the pace of the whole system: how often the agent decides, which candle sizes it reads
first, how long it plans to hold, and how long a limit buy waits. As the end comes closer, the profile moves to
sprint by itself. Without an end time the bot runs as a swing trader.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    cycle_seconds: int  # how often the agent decides
    timeframes: str  # what the agent reads first
    hold: str  # the holding times that fit
    max_hold_hours: float  # the longest hold the agent may plan
    fill_minutes: int  # how long a limit buy waits before it is cancelled
    skill: str  # the playbook to read first

    def as_dict(self) -> dict:
        return asdict(self)


SPRINT = Profile("sprint", 300, "1, 5 and 15-minute candles and the live book; 1h only for context",
                 "minutes to a few hours", 6, 10, "sprint-trading")
SHORT = Profile("short", 900, "15-minute and 1-hour candles", "hours to two days", 48, 30, "trader-core")
SWING = Profile("swing", 1800, "1-hour and 4-hour candles", "a day to a week", 168, 60, "trend-following")


def profile(hours_left: float | None) -> Profile:
    if hours_left is None:
        return SWING
    if hours_left <= 24:
        return SPRINT
    if hours_left <= 7 * 24:
        return SHORT
    return SWING
