from dataclasses import dataclass


@dataclass(frozen=True)
class PositionedInterval:
    index: int
    start: float
    end: float
    lane: int
    lanes: int


def arrange_intervals(intervals: list[tuple[float, float]]) -> list[PositionedInterval]:
    """Partition connected overlap groups; half-open touching intervals reuse a lane."""
    ordered = sorted(enumerate(intervals), key=lambda value: (value[1][0], value[1][1]))
    groups = []
    group = []
    right = float("-inf")
    for index, (start, end) in ordered:
        if end <= start:
            continue
        if group and start >= right:
            groups.append(group)
            group = []
        group.append((index, start, end))
        right = max(right, end) if len(group) > 1 else end
    if group:
        groups.append(group)
    result = []
    for group in groups:
        ends = []
        placed = []
        for index, start, end in group:
            lane = next(
                (number for number, last_end in enumerate(ends) if last_end <= start), len(ends)
            )
            if lane == len(ends):
                ends.append(end)
            else:
                ends[lane] = end
            placed.append((index, start, end, lane))
        result.extend(
            PositionedInterval(index, start, end, lane, len(ends))
            for index, start, end, lane in placed
        )
    return result
