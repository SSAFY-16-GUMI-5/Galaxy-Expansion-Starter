"""A finite 1 → 10 → 9 → 10 display scenario for the Python Runner."""

from dataclasses import dataclass
import os
import time

from framework.adapters.python import CosmicSpec


@dataclass
class DemoObject:
    name: str
    type: str
    color: str
    size: float


class DemoPool:
    """Keep storage in the fixture so tests can observe its reuse."""

    def __init__(self):
        self._free = []
        self._active = {}

    def acquire(self, spec):
        if self._free:
            obj = self._free.pop()
            obj.name = spec.name
            obj.type = spec.type
            obj.color = spec.color
            obj.size = spec.size
        else:
            obj = DemoObject(spec.name, spec.type, spec.color, spec.size)
        self._active[id(obj)] = obj
        return obj

    def release(self, obj):
        if self._active.get(id(obj)) is not obj:
            raise ValueError("Object is not borrowed from this pool")
        del self._active[id(obj)]
        self._free.append(obj)


def create_pool():
    return DemoPool()


def snapshot(obj):
    return CosmicSpec(obj.name, obj.type, obj.color, obj.size)


def scenario(context):
    delay = float(os.environ.get("GALAXY_TEST_PRESENTATION_DELAY", "0"))
    first = context.acquire(CosmicSpec("새벽", "seed", "#58a6ff", 0.8))
    time.sleep(delay)
    for index in range(1, 10):
        context.acquire(CosmicSpec(f"Orbit {index}", "planet", "#9bdcff", 0.6))
    time.sleep(delay)
    context.release(first)
    time.sleep(delay)
    reborn = CosmicSpec("Reborn Nova", "star", "#f4bd64", 1.6)
    lease = context.acquire(reborn)
    assert context.snapshot(lease) == reborn
    time.sleep(delay)
