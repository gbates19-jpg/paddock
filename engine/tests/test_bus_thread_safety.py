"""asyncio.Queue.put_nowait is documented as NOT thread-safe. Once a sim
run is driven from a background thread (paddock.api.main's POST
/sim/start), EventBus.publish() gets called from that thread — and from
flumine's own internal LoggingControl thread — neither of which is the
event loop's thread. Calling put_nowait directly from there doesn't
reliably crash; it can silently corrupt the queue's internal waiter
bookkeeping, which would surface as "the UI randomly misses events" under
load, not as a test failure you'd stumble into by accident. So this
doesn't just check "no exception" — it captures the exact sequence
received and asserts nothing was lost, duplicated, or reordered.

The event loop is run on its own real thread here (rather than using
pytest-asyncio) deliberately: it's the same shape as the actual bug this
protects against — publish() being called from a thread other than the
one that owns the subscriber queues — and it keeps this test in the same
plain-synchronous style as the rest of the suite (no new test-runner
dependency, TestClient already hides an equivalent loop thread the same
way in test_bus_api.py).
"""
from __future__ import annotations

import asyncio
import threading

from paddock.bus.bus import EventBus
from paddock.bus.events import WorkerHeartbeat, WorkerState


def test_publish_from_a_worker_thread_is_delivered_in_order_and_uncorrupted():
    bus = EventBus()

    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()

    def _bind() -> None:
        bus.bind_loop(loop)

    asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop).result(timeout=2)
    loop.call_soon_threadsafe(_bind)

    queue = bus.subscribe(maxsize=0)

    n = 2000

    def _publish_from_worker_thread() -> None:
        for i in range(n):
            bus.publish(WorkerHeartbeat(name=str(i), state=WorkerState.BUSY))

    publisher = threading.Thread(target=_publish_from_worker_thread)
    publisher.start()
    publisher.join(timeout=10)
    assert not publisher.is_alive(), "publisher thread never finished"

    async def _drain() -> list[WorkerHeartbeat]:
        return [await asyncio.wait_for(queue.get(), timeout=5) for _ in range(n)]

    received = asyncio.run_coroutine_threadsafe(_drain(), loop).result(timeout=15)

    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=2)

    assert [int(e.name) for e in received] == list(range(n))
    assert queue.empty()
