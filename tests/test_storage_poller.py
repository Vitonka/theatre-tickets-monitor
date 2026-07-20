"""Storage CRUD and the newly-available diff logic."""
import pytest

from bot.models import Performance
from bot.poller import newly_available
from bot.storage import Storage


@pytest.mark.asyncio
async def test_storage_monitor_crud(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    await s.connect()
    try:
        mid = await s.add_monitor(1, "https://x/y", "T", "Play")
        assert mid is not None
        # duplicate (same chat + url) rejected
        assert await s.add_monitor(1, "https://x/y", "T", "Play") is None
        # different chat is fine
        assert await s.add_monitor(2, "https://x/y", "T", "Play") is not None

        assert len(await s.list_monitors(1)) == 1
        assert (await s.get_monitor(1, mid)).title == "Play"
        assert await s.remove_monitor(1, mid) is True
        assert await s.remove_monitor(1, mid) is False
        assert await s.list_monitors(1) == []
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_state_roundtrip_and_cascade(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    await s.connect()
    try:
        mid = await s.add_monitor(1, "u", "T", "P")
        await s.set_state(mid, "k1", True)
        await s.set_state(mid, "k2", False)
        assert await s.get_state(mid) == {"k1": True, "k2": False}
        await s.set_state(mid, "k1", False)  # upsert
        assert (await s.get_state(mid))["k1"] is False
        # removing the monitor cascades its state away
        await s.remove_monitor(1, mid)
        assert await s.get_state(mid) == {}
    finally:
        await s.close()


def _p(iso, avail):
    return Performance(iso, iso, avail)


def test_newly_available_first_time():
    perfs = [_p("2026-09-01T19:30:00", True), _p("2026-09-02T19:30:00", False)]
    fresh = newly_available(perfs, prior={})
    assert [p.date_iso for p in fresh] == ["2026-09-01T19:30:00"]


def test_newly_available_no_repeat_while_available():
    perfs = [_p("2026-09-01T19:30:00", True)]
    prior = {"2026-09-01T19:30:00": True}
    assert newly_available(perfs, prior) == []


def test_newly_available_realerts_after_soldout_then_back():
    perfs = [_p("2026-09-01T19:30:00", True)]
    prior = {"2026-09-01T19:30:00": False}  # was sold out, now back
    assert len(newly_available(perfs, prior)) == 1
