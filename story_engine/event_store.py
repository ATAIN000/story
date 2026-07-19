"""[向后兼容 shim] EventStore 已迁移到 story_engine.world.event_store"""
from .world.event_store import EventStore

__all__ = ["EventStore"]
