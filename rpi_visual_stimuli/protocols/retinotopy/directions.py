from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DirectionDefinition:
    direction: str
    direction_code: int
    axis: str
    start_edge: str
    end_edge: str
    movement_axis: str


DIRECTION_DEFINITIONS = {
    "left_to_right": DirectionDefinition(
        direction="left_to_right",
        direction_code=0,
        axis="azimuth",
        start_edge="left",
        end_edge="right",
        movement_axis="x",
    ),
    "right_to_left": DirectionDefinition(
        direction="right_to_left",
        direction_code=1,
        axis="azimuth",
        start_edge="right",
        end_edge="left",
        movement_axis="x",
    ),
    "top_to_bottom": DirectionDefinition(
        direction="top_to_bottom",
        direction_code=2,
        axis="elevation",
        start_edge="top",
        end_edge="bottom",
        movement_axis="y",
    ),
    "bottom_to_top": DirectionDefinition(
        direction="bottom_to_top",
        direction_code=3,
        axis="elevation",
        start_edge="bottom",
        end_edge="top",
        movement_axis="y",
    ),
}


def get_direction(direction: str) -> DirectionDefinition:
    return DIRECTION_DEFINITIONS[direction]
