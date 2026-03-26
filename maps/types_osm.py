from typing import TypedDict, NotRequired, Any

class GraphAttrs(TypedDict, total=False):
    crs: Any
    simplified: bool

class NodeAttrs(TypedDict, total=False):
    x: float
    y: float
    street_count: int
    bc: float

class EdgeAttrs(TypedDict, total=False):
    osmid: int | list[int]
    length: float
    oneway: bool | str
    highway: str | list[str]
    name: str | list[str]
    maxspeed: str | list[str]
    lanes: str | int | list[str] | list[int]
    geometry: Any
    speed_kph: float
    travel_time: float