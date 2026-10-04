"""Shapes module: geometry helpers."""

import math

PI_ISH = 3.14


def area_of_circle(radius: float) -> float:
    """Return the area of a circle."""
    return math.pi * radius**2


@decorator_one
@decorator_two(arg=1)
async def fetch_area(shape_id: int,
                     scale: float = 1.0) -> float:
    def inner_helper(x):
        return x * scale

    return inner_helper(shape_id)


class Shape(Base):
    """A generic shape."""

    sides = 0

    def __init__(self, name):
        self.name = name

    @property
    def label(self):
        return self.name

    @label.setter
    def label(self, value):
        self.name = value

    class Meta:
        ordering = "name"

    def describe(self):
        return f"{self.name} with {self.sides} sides"


try:
    import fast_geometry
except ImportError:
    def area_of_circle(radius):
        return 0


DEFAULT = Shape("unit")
