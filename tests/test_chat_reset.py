import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from app.core.agent import MaxiAgent


@pytest.fixture
def local_agent(monkeypatch):
    agent = MaxiAgent()
    monkeypatch.setattr("app.core.agent.mcp_manager.ensure_connected", AsyncMock())
    monkeypatch.setattr(agent, "_get_all_tools", lambda: [])
    monkeypatch.setattr(agent, "_record_turn", MagicMock())
    monkeypatch.setattr(agent, "_build_system_prompt", lambda **kwargs: "Test assistant")
    return agent


@pytest.mark.parametrize("streaming", [False, True])
def test_new_chat_does_not_send_old_history_to_llm(local_agent, monkeypatch, streaming):
    async def scenario():
        local_agent.append_turn("Unwanted old topic", "Old answer")
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="Fresh answer"))
        monkeypatch.setattr(local_agent, "_get_llm", lambda **kwargs: llm)

        if streaming:
            reset = [chunk async for chunk in local_agent.run_stream("new chat")]
            assert "Starting fresh" in "".join(reset)
            assert local_agent.get_history() == []
            llm.ainvoke.assert_not_called()
            _ = [chunk async for chunk in local_agent.run_stream("Tell me about trees")]
        else:
            result = await local_agent.run("new chat")
            assert result["status"] == "success"
            assert local_agent.get_history() == []
            llm.ainvoke.assert_not_called()
            await local_agent.run("Tell me about trees")

        messages = llm.ainvoke.call_args.args[0]
        assert not any("Unwanted old topic" in str(message.content) for message in messages)

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
def test_inflight_old_response_cannot_repopulate_new_chat(local_agent, monkeypatch, streaming):
    async def scenario():
        entered = asyncio.Event()
        finish = asyncio.Event()

        async def delayed_response(messages):
            entered.set()
            await finish.wait()
            return AIMessage(content="Late old answer")

        llm = MagicMock()
        llm.ainvoke = delayed_response
        monkeypatch.setattr(local_agent, "_get_llm", lambda **kwargs: llm)

        async def old_request():
            if streaming:
                return [chunk async for chunk in local_agent.run_stream("Old request")]
            return await local_agent.run("Old request")

        task = asyncio.create_task(old_request())
        await asyncio.wait_for(entered.wait(), timeout=2)
        local_agent.clear_history()
        local_agent.append_turn("New request", "New answer")
        finish.set()
        await asyncio.wait_for(task, timeout=2)

        assert [message.content for message in local_agent.get_history()] == ["New request", "New answer"]

    asyncio.run(scenario())


def test_reset_endpoint_stops_voice_and_preserves_long_term_memory(monkeypatch):
    from app.api.routes import clear_context
    from app.core.voice_service import voice_service
    from app.core.agent import agent

    cancel = MagicMock()
    clear = MagicMock()
    memory = MagicMock()
    monkeypatch.setattr(voice_service, "abort_current_command", cancel)
    monkeypatch.setattr(agent, "clear_history", clear)
    monkeypatch.setattr("app.core.lmem_tools._run_lmem", memory)

    result = asyncio.run(clear_context())

    assert result["status"] == "cleared"
    cancel.assert_called_once_with(reason="new_chat")
    clear.assert_called_once_with()
    memory.assert_not_called()
