import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, BaseMessage
from app.config import settings
from app.core.skills import skill_registry
from app.core.mcp_client import mcp_manager

logger = logging.getLogger("maxi.agent")


class MaxiAgent:
    """Stateless agent loop using OpenAI-compatible endpoints with dynamic skills and MCP tools."""

    def __init__(self):
        self.settings = settings

    def _get_llm(self, streaming: bool = False) -> ChatOpenAI:
        return ChatOpenAI(
            base_url=self.settings.openai_base_url,
            api_key=self.settings.openai_api_key or "sk-dummy-key",
            model=self.settings.openai_model,
            streaming=streaming,
            temperature=0.3,
        )

    def _format_tool_output(self, output: Any) -> str:
        """Normalizes MCP tool outputs (strings, content blocks, lists, dicts) into clean text."""
        if isinstance(output, str):
            return output
        if isinstance(output, list):
            texts = []
            for item in output:
                if isinstance(item, dict) and "text" in item:
                    texts.append(str(item["text"]))
                else:
                    texts.append(str(item))
            return "\n".join(texts)
        if isinstance(output, dict):
            if "text" in output:
                return str(output["text"])
            return json.dumps(output, ensure_ascii=False)
        return str(output)

    def _build_system_prompt(self, prompt: str = "", source: str = "text") -> str:
        """Injects only the base persona and relevant markdown skills for this prompt."""
        base_prompt = self.settings.system_prompt
        skills_prompt = skill_registry.compile_instructions_for_prompt(prompt, source=source)
        if skills_prompt:
            return f"{base_prompt}\n\n## Dynamically Loaded Skills\n{skills_prompt}"
        return base_prompt

    def _record_turn(self, source: str, prompt: str, output: str, tools_used: List[str], status: str):
        """Appends conversation turn to audit history file for external logging/analytics."""
        try:
            history_path = Path(self.settings.history_file_path)
            history_path.parent.mkdir(parents=True, exist_ok=True)
            
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "model": self.settings.openai_model,
                "prompt": prompt,
                "output": output,
                "tools_used": tools_used,
                "status": status,
            }
            with open(history_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to record turn to history log: {e}")

    async def run(self, prompt: str, source: str = "text") -> Dict[str, Any]:
        """Execute prompt statelessly against OpenAI-compatible endpoint with full MCP tool execution."""
        await mcp_manager.ensure_connected()
        system_instruction = self._build_system_prompt(prompt=prompt, source=source)
        tools = mcp_manager.get_tools()
        tool_map = {t.name: t for t in tools}

        logger.info(f"Dispatching [{source}] prompt to {self.settings.openai_model} @ {self.settings.openai_base_url} ({len(tools)} tools loaded)")

        messages: List[BaseMessage] = [
            SystemMessage(content=system_instruction),
            HumanMessage(content=prompt)
        ]

        executed_tools: List[str] = []
        max_turns = 5
        output_text = ""

        try:
            llm = self._get_llm(streaming=False)
            if tools:
                llm = llm.bind_tools(tools)

            for turn in range(max_turns):
                response = await llm.ainvoke(messages)
                messages.append(response)

                tool_calls = getattr(response, "tool_calls", [])
                if not tool_calls:
                    output_text = response.content if isinstance(response.content, str) else str(response.content)
                    break

                for call in tool_calls:
                    call_name = call.get("name")
                    call_args = call.get("args", {})
                    call_id = call.get("id") or f"call_{call_name}"

                    logger.info(f"Turn {turn + 1}: Executing tool '{call_name}' with args {call_args}")
                    executed_tools.append(call_name)

                    tool = tool_map.get(call_name)
                    if tool:
                        try:
                            if hasattr(tool, "ainvoke"):
                                raw_res = await tool.ainvoke(call_args)
                            else:
                                raw_res = tool.invoke(call_args)
                            tool_result = self._format_tool_output(raw_res)
                        except Exception as e:
                            logger.error(f"Error executing '{call_name}': {e}")
                            tool_result = f"Error executing tool '{call_name}': {str(e)}"
                    else:
                        tool_result = f"Tool '{call_name}' not found."

                    messages.append(ToolMessage(
                        content=tool_result,
                        tool_call_id=call_id
                    ))
            else:
                last_msg = messages[-1]
                output_text = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)

            # Fallback confirmation if tools executed but no text returned
            if not output_text.strip() and executed_tools:
                output_text = f"Executed {', '.join(executed_tools)} successfully."

            self._record_turn(
                source=source,
                prompt=prompt,
                output=output_text,
                tools_used=executed_tools,
                status="success"
            )

            return {
                "source": source,
                "model": self.settings.openai_model,
                "endpoint": self.settings.openai_base_url,
                "input": prompt,
                "output": output_text,
                "tools_used": executed_tools,
                "status": "success"
            }
        except Exception as e:
            err_msg = f"LLM Endpoint Error: {str(e)}"
            logger.error(f"Error communicating with LLM endpoint ({self.settings.openai_base_url}): {e}")
            self._record_turn(
                source=source,
                prompt=prompt,
                output=err_msg,
                tools_used=executed_tools,
                status="error"
            )
            return {
                "source": source,
                "model": self.settings.openai_model,
                "input": prompt,
                "output": err_msg,
                "tools_used": executed_tools,
                "status": "error"
            }

    async def run_stream(self, prompt: str, source: str = "text") -> AsyncGenerator[str, None]:
        """Stream token-by-token response over WebSockets, executing tool calls when requested."""
        await mcp_manager.ensure_connected()
        system_instruction = self._build_system_prompt(prompt=prompt, source=source)
        tools = mcp_manager.get_tools()
        tool_map = {t.name: t for t in tools}

        messages: List[BaseMessage] = [
            SystemMessage(content=system_instruction),
            HumanMessage(content=prompt)
        ]

        full_output: List[str] = []
        executed_tools: List[str] = []
        max_turns = 5

        try:
            llm = self._get_llm(streaming=False)
            if tools:
                llm = llm.bind_tools(tools)

            for turn in range(max_turns):
                response = await llm.ainvoke(messages)
                messages.append(response)

                tool_calls = getattr(response, "tool_calls", [])
                if not tool_calls:
                    text_chunk = response.content if isinstance(response.content, str) else str(response.content)
                    if text_chunk:
                        full_output.append(text_chunk)
                        yield text_chunk
                    break

                for call in tool_calls:
                    call_name = call.get("name")
                    call_args = call.get("args", {})
                    call_id = call.get("id") or f"call_{call_name}"

                    logger.info(f"Stream turn {turn + 1}: Executing tool '{call_name}' with args {call_args}")
                    executed_tools.append(call_name)

                    tool = tool_map.get(call_name)
                    if tool:
                        try:
                            if hasattr(tool, "ainvoke"):
                                raw_res = await tool.ainvoke(call_args)
                            else:
                                raw_res = tool.invoke(call_args)
                            tool_result = self._format_tool_output(raw_res)
                        except Exception as e:
                            logger.error(f"Error executing '{call_name}': {e}")
                            tool_result = f"Error executing tool '{call_name}': {str(e)}"
                    else:
                        tool_result = f"Tool '{call_name}' not found."

                    messages.append(ToolMessage(
                        content=tool_result,
                        tool_call_id=call_id
                    ))
            else:
                last_msg = messages[-1]
                text_chunk = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
                if text_chunk:
                    full_output.append(text_chunk)
                    yield text_chunk

            final_text = "".join(full_output).strip()
            if not final_text and executed_tools:
                fallback = f"Executed {', '.join(executed_tools)} successfully."
                full_output.append(fallback)
                yield fallback

            self._record_turn(
                source=source,
                prompt=prompt,
                output="".join(full_output),
                tools_used=executed_tools,
                status="success"
            )
        except Exception as e:
            err_chunk = f"\n[Error streaming from {self.settings.openai_base_url}: {str(e)}]"
            logger.error(f"Streaming error from {self.settings.openai_base_url}: {e}")
            yield err_chunk
            self._record_turn(
                source=source,
                prompt=prompt,
                output="".join(full_output) + err_chunk,
                tools_used=executed_tools,
                status="error"
            )


agent = MaxiAgent()

