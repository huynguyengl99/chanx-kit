# conversation-store

Where an agent's conversation lives between runs, as an opaque string per thread.

```bash
copit add @chanx-kit/conversation-store
```

## Why a string

Every agent framework has its own message type and its own serialisation for it.
Storing that type would mean a backend per framework — Postgres history for Pydantic AI,
then again for LangChain, then again for the next one. Storing serialised text instead
means one backend serves them all, and the framework kit converts at the edge:

```python
# pydantic-ai
await store.save(thread_id, result.all_messages_json().decode())
messages = ModelMessagesTypeAdapter.validate_json(conversation)
```

A store never inspects the conversation, so it cannot be wrong about a format it does
not own. Text rather than bytes because the far side is almost always a database, and a
`TEXT`/`JSONB` column can be read, migrated and grepped where a blob cannot.

The flip side: a conversation written by one framework is not readable by another, and
nothing checks that for you. One thread, one framework.

## Implement one

```python
from .ws_kits.conversation_store import ConversationStore


class PostgresConversationStore(ConversationStore):
    async def load(self, thread_id: str) -> str | None:
        return await fetch_conversation(thread_id)

    async def save(self, thread_id: str, conversation: str) -> None:
        await upsert_conversation(thread_id, conversation)

    async def delete(self, thread_id: str) -> None:
        await delete_conversation(thread_id)
```

Then hand it to whichever kit runs your agent:

```python
class TaskletTopic(PydanticAIAgUiTopic):
    agent = agent
    conversation_store = PostgresConversationStore()
```

!!! warning
    `InMemoryConversationStore` is process-local and not durable. It is for demos and
    tests; anything real wants a database.

## Interface

| Method | Returns | Notes |
|---|---|---|
| `load(thread_id)` | `str \| None` | `None` when the thread has no conversation yet |
| `save(thread_id, conversation)` | — | Replaces the whole conversation |
| `delete(thread_id)` | — | A missing thread is not an error |
