"""Participant starter for the Python Object Pooling assignment."""

from dataclasses import dataclass
from typing import Literal

from framework.adapters.python import CosmicSpec, ScenarioContext


@dataclass
class CosmicObject:
    name: str
    type: Literal["seed", "star", "planet"]
    color: str
    size: float
    # TODO: Decide how the pool will represent ownership and active state.


class ObjectPool:
    def acquire(self, spec: CosmicSpec) -> CosmicObject:
        """Borrow one active storage instance with all fields initialized from spec."""
        # TODO: Select available storage or allocate it according to your capacity policy.
        # TODO: Reinitialize every field on reused storage before returning it.
        raise NotImplementedError("Implement ObjectPool.acquire")

    def release(self, obj: CosmicObject) -> None:
        """Return an active object owned by this pool. Its caller must stop using it."""
        # TODO: Reject foreign objects and double returns before changing pool state.
        # TODO: Mark the storage available for a later acquire.
        raise NotImplementedError("Implement ObjectPool.release")


def create_pool() -> ObjectPool:
    return ObjectPool()


def snapshot(obj: CosmicObject) -> CosmicSpec:
    return CosmicSpec(obj.name, obj.type, obj.color, obj.size)


def scenario(context: ScenarioContext[CosmicObject]) -> None:
    # TODO: Acquire through context, inspect the snapshot, and release the lease.
    # TODO: Acquire again with different fields to exercise the reuse path.
    # Test actual object identity by calling ObjectPool directly in a domain test.
    raise NotImplementedError("Implement the participant scenario")
