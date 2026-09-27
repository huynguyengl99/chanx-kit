import asyncio

from ..jobs import SerialJobs
from ..replay import InMemoryReplayStore


async def test_jobs_for_a_key_run_in_order_one_at_a_time() -> None:
    jobs = SerialJobs()
    seen: list[str] = []
    running = 0

    def job(name: str):
        async def run() -> None:
            nonlocal running
            running += 1
            assert running == 1
            await asyncio.sleep(0.01)
            seen.append(name)
            running -= 1

        return run

    for name in ("a", "b", "c"):
        jobs.submit("s", job(name))
    await jobs.wait("s")

    assert seen == ["a", "b", "c"]
    assert not jobs.busy("s")


async def test_keys_run_independently() -> None:
    jobs = SerialJobs()
    gate = asyncio.Event()
    done: list[str] = []

    async def blocked() -> None:
        await gate.wait()
        done.append("blocked")

    async def quick() -> None:
        done.append("quick")

    jobs.submit("one", blocked)
    jobs.submit("two", quick)
    await jobs.wait("two")
    assert done == ["quick"]
    gate.set()
    await jobs.wait("one")


async def test_cancel_stops_the_current_job_and_drops_the_queue() -> None:
    jobs = SerialJobs()
    started = asyncio.Event()
    seen: list[str] = []

    async def long() -> None:
        started.set()
        await asyncio.sleep(10)
        seen.append("long")

    async def next_one() -> None:
        seen.append("next")

    jobs.submit("s", long)
    jobs.submit("s", next_one)
    await started.wait()

    assert await jobs.cancel("s") is True
    assert seen == []
    assert not jobs.busy("s")
    assert await jobs.cancel("s") is False


async def test_a_failing_job_does_not_stop_the_next() -> None:
    jobs = SerialJobs()
    seen: list[str] = []

    async def boom() -> None:
        raise RuntimeError("provider down")

    async def after() -> None:
        seen.append("after")

    jobs.submit("s", boom)
    jobs.submit("s", after)
    await jobs.wait("s")
    assert seen == ["after"]


async def test_replay_numbers_from_one_and_restarts_after_clear() -> None:
    store = InMemoryReplayStore()
    assert await store.append("s", {"n": 1}) == 1
    assert await store.append("s", {"n": 2}) == 2
    assert await store.replay("s") == [(1, {"n": 1}), (2, {"n": 2})]
    await store.clear("s")
    assert await store.replay("s") == []
    assert await store.append("s", {"n": 3}) == 1


async def test_replay_is_bounded() -> None:
    store = InMemoryReplayStore(max_messages=2)
    for n in range(3):
        await store.append("s", {"n": n})
    assert [seq for seq, _ in await store.replay("s")] == [2, 3]
