import pytest

from ..store import ConversationStore, InMemoryConversationStore


@pytest.fixture
def store() -> InMemoryConversationStore:
    return InMemoryConversationStore()


async def test_an_unknown_thread_has_no_conversation(
    store: InMemoryConversationStore,
) -> None:
    assert await store.load("thread-1") is None


async def test_a_saved_conversation_comes_back_verbatim(
    store: InMemoryConversationStore,
) -> None:
    """The conversation belongs to the framework: a store must not reshape it."""
    conversation = '[{"parts": [{"content": "hi"}]}]'
    await store.save("thread-1", conversation)

    assert await store.load("thread-1") == conversation


async def test_saving_replaces_the_whole_conversation(
    store: InMemoryConversationStore,
) -> None:
    await store.save("thread-1", "first")
    await store.save("thread-1", "second")

    assert await store.load("thread-1") == "second"


async def test_threads_do_not_share_a_conversation(
    store: InMemoryConversationStore,
) -> None:
    await store.save("thread-1", "one")
    await store.save("thread-2", "two")

    assert await store.load("thread-1") == "one"
    assert await store.load("thread-2") == "two"


async def test_deleting_forgets_the_thread(store: InMemoryConversationStore) -> None:
    await store.save("thread-1", "one")
    await store.delete("thread-1")

    assert await store.load("thread-1") is None


async def test_deleting_an_unknown_thread_is_not_an_error(
    store: InMemoryConversationStore,
) -> None:
    await store.delete("never-existed")


def test_the_in_memory_default_satisfies_the_protocol() -> None:
    assert isinstance(InMemoryConversationStore(), ConversationStore)
