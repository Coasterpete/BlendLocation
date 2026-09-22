"""Optional named-place lookup boundary for future providers.

M1 intentionally has no public geocoder: coordinates can be entered directly,
and a provider can be added here later with an explicit submit action and its
own usage-policy checks. No lookup runs while the user types or pans the map.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Place:
    label: str
    latitude: float
    longitude: float


class Geocoder(ABC):
    @abstractmethod
    def search(self, query: str) -> list[Place]:
        """Resolve one explicitly submitted query into WGS84 locations."""
