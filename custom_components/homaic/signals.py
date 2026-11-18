"""Tell Homaic when a battery runs low, a filter is due, or water is found.

Home Assistant decides here, on the house. Homaic gets one small message when
a line is crossed and one when the reading is back: the device's own number,
which of the three it is, the percent, and when. Nothing else leaves: no
entity ids or names, no other state, no history. Smoke, CO, gas, doors, locks
and motion are never sent; Home Assistant and the alarm own those moments.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED, PERCENTAGE, STATE_ON
from homeassistant.core import CoreState, Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import DOMAIN, SIGNAL_TOOL
from .send import SendError, async_call, call_body

_LOGGER = logging.getLogger(__name__)

BATTERY_LOW = 15  # percent, at or under
FILTER_DUE = 10  # percent of life left, at or under
# back over this, the reading has come back (a new battery, a new filter);
# between the two lines nothing changes, so a reading near the line never flaps
BACK_OVER = 50
MAX_SIGNALS = 100  # in one call; more goes in the next
SETTLE_S = 10  # a burst of changes goes as one call
RETRY = timedelta(hours=1)

STORE_VERSION = 1

# binary_sensor classes a filter alert may carry; a smoke, gas or door class is never one
FILTER_BINARY_CLASSES = frozenset({None, "problem"})


def _level(state: State) -> float | None:
    try:
        return float(state.state)
    except ValueError:
        return None


def reading_of(entry: er.RegistryEntry, state: State | None) -> tuple[str, bool, int | None] | None:
    """(kind, crossed, level) for an entity Homaic watches; None for any other.

    crossed is True past the line, False back over it, and the entity is left
    out (None) between the two or while it reads unknown or unavailable.
    """
    if state is None or entry.device_id is None or entry.disabled_by is not None:
        return None
    dc = state.attributes.get("device_class")
    words = " ".join(filter(None, (entry.entity_id, entry.translation_key, entry.original_name))).lower()

    if entry.domain == "sensor":
        if state.attributes.get("unit_of_measurement") != PERCENTAGE:
            return None
        if dc == "battery":
            kind, line = "battery", BATTERY_LOW
        elif dc is None and "filter" in words:
            kind, line = "filter", FILTER_DUE
        else:
            return None
        level = _level(state)
        if level is None or not 0 <= level <= 100:
            return None
        if level <= line:
            return kind, True, round(level)
        if level > BACK_OVER:
            return kind, False, round(level)
        return None

    if entry.domain == "binary_sensor":
        if dc == "battery":
            kind = "battery"
        elif dc == "moisture":
            kind = "water"
        elif dc in FILTER_BINARY_CLASSES and "filter" in words:
            kind = "filter"
        else:
            return None
        if state.state not in (STATE_ON, "off"):
            return None
        return kind, state.state == STATE_ON, None

    return None


def readings(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """What each watched device reads now, one per device and kind.

    Any entity past the line puts the device past it (at its lowest level);
    the device is back only when every entity that reads is back.
    """
    out: dict[str, dict[str, Any]] = {}
    for entry in er.async_get(hass).entities.values():
        state = hass.states.get(entry.entity_id)
        r = reading_of(entry, state)
        if r is None:
            continue
        kind, crossed, level = r
        key = f"{entry.device_id}|{kind}"
        at = state.last_changed
        cur = out.get(key)
        if cur is None:
            out[key] = {"device_id": entry.device_id, "kind": kind, "crossed": crossed, "level": level, "at": at}
            continue
        if crossed and not cur["crossed"]:
            out[key] = {**cur, "crossed": True, "level": level, "at": at}
        elif crossed == cur["crossed"]:
            if level is not None and (cur["level"] is None or (level < cur["level"] if crossed else level > cur["level"])):
                cur["level"] = level
            if at > cur["at"]:
                cur["at"] = at
    return out


def due(now: dict[str, dict[str, Any]], sent: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The signals Homaic has not heard yet: a new crossing, a lower level on
    one it has, or a reading back on one it was told about."""
    out = []
    for key, r in sorted(now.items()):
        before = sent.get(key)
        if r["crossed"]:
            if before is None or before.get("cleared") or before.get("level") != r["level"]:
                out.append({"key": key, "device_id": r["device_id"], "kind": r["kind"], "level": r["level"], "at": r["at"].isoformat(), "cleared": False})
        elif before is not None and not before.get("cleared"):
            out.append({"key": key, "device_id": r["device_id"], "kind": r["kind"], "level": r["level"], "at": r["at"].isoformat(), "cleared": True})
    return out


class SignalWatch:
    """Watches the readings and keeps what Homaic has been told across restarts."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store: Store[dict[str, dict[str, Any]]] = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.signals")
        self.sent: dict[str, dict[str, Any]] = {}
        self._later: Callable[[], None] | None = None
        self._unsubs: list[Callable[[], None]] = []

    async def async_start(self) -> None:
        self.sent = await self.store.async_load() or {}
        self._unsubs.append(self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._changed))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, RETRY))
        if self.hass.state is CoreState.running:
            self._soon()
        else:
            self._unsubs.append(self.hass.bus.async_listen_once("homeassistant_started", lambda _e: self._soon()))

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._later:
            self._later()
            self._later = None

    @callback
    def _changed(self, event: Event) -> None:
        entry = er.async_get(self.hass).async_get(event.data["entity_id"])
        if entry is None:
            return
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if reading_of(entry, new) is not None or reading_of(entry, old) is not None:
            self._soon()

    @callback
    def _tick(self, _now: datetime) -> None:
        self._soon()

    @callback
    def _soon(self) -> None:
        if self._later is None:
            self._later = async_call_later(self.hass, SETTLE_S, self._fire)

    async def _fire(self, _now: datetime) -> None:
        self._later = None
        await self.async_sync()

    async def async_sync(self) -> int:
        """Send what Homaic has not heard; return how many went. Never raises:
        a send that does not go through is tried again within the hour."""
        todo = due(readings(self.hass), self.sent)
        went = 0
        for i in range(0, len(todo), MAX_SIGNALS):
            part = todo[i : i + MAX_SIGNALS]
            body = call_body(SIGNAL_TOOL, {"signals": [{k: v for k, v in s.items() if k != "key"} for s in part]})
            try:
                await async_call(self.hass, self.entry, body)
            except SendError as err:
                _LOGGER.debug("Homaic did not take %s signals: %s", len(part), err.translation_key)
                break
            for s in part:
                self.sent[s["key"]] = {"level": s["level"], "at": s["at"], "cleared": s["cleared"]}
            went += len(part)
        if went:
            self.store.async_delay_save(lambda: self.sent, 1)
        return went
