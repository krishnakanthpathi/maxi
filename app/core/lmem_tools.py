"""
Maxi Native LightMem (LMEM) Memory Tools
Provides direct, first-class LangChain tool interfaces to the local LMEM engine:
- lmem_recall: Search and retrieve stored user preferences, facts, and context.
- lmem_answer: Direct semantic Q&A over persistent memories.
- lmem_remember: Explicitly persist confirmed user facts.
"""

import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import List
from langchain_core.tools import tool, BaseTool

logger = logging.getLogger("maxi.lmem")


def _get_lmem_env() -> dict:
    home = str(Path.home())
    extra_paths = [
        f"{home}/.local/bin",
        f"{home}/.lightmem/bin",
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        "/Library/Frameworks/Python.framework/Versions/3.14/bin",
        "/Library/Frameworks/Python.framework/Versions/3.12/bin",
    ]
    env = dict(os.environ)
    existing = env.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    env["PATH"] = ":".join(extra_paths) + ":" + existing
    env["HOME"] = home
    return env


def _run_lmem(args: List[str], timeout_s: float = 12.0) -> str:
    env = _get_lmem_env()
    bin_path = shutil.which("lmem", path=env["PATH"]) or "lmem"
    try:
        res = subprocess.run(
            [bin_path] + args,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_s,
        )
        output = (res.stdout or "").strip()
        if not output and res.stderr:
            output = res.stderr.strip()
        return output or "No memories found matching query."
    except Exception as e:
        logger.error(f"Error running lmem with args {args}: {e}")
        return f"Error executing lmem: {str(e)}"


@tool
def lmem_recall(query: str) -> str:
    """
    Search and retrieve stored user memories, facts, preferences, favorite songs/movies/items,
    credentials, project setups, and personal knowledge from LightMem persistent storage.
    ALWAYS call this tool first whenever the user mentions personal preferences ('my favorite ...',
    'my song', 'what I like', 'who is my ...'), past conversations, or personal details.
    """
    clean_query = query.strip().strip("'\"")
    logger.info(f"🧠 Querying LMEM memory recall for: \"{clean_query}\"")
    return _run_lmem(["recall", clean_query, "--global", "--multi-hop"])


@tool
def lmem_answer(question: str) -> str:
    """
    Ask the LightMem memory engine directly to answer a question based on verified persistent user memories.
    Use this to get direct factual answers about the user (e.g. 'what is my favorite song?', 'what is my nickname?').
    """
    clean_q = question.strip().strip("'\"")
    logger.info(f"🧠 Querying LMEM memory answer for: \"{clean_q}\"")
    return _run_lmem(["answer", clean_q])


@tool
def lmem_remember(content: str) -> str:
    """
    Save a confirmed fact, preference, or learning to persistent LightMem memory.
    IMPORTANT: Never store arbitrary memories automatically; only call this tool when
    the user explicitly confirms or asks to save/remember something.
    """
    clean_content = content.strip().strip("'\"")
    logger.info(f"🧠 Persisting memory to LMEM: \"{clean_content}\"")
    return _run_lmem(["remember", clean_content])


def get_lmem_tools() -> List[BaseTool]:
    """Returns the list of first-class LMEM tools."""
    return [lmem_recall, lmem_answer, lmem_remember]
