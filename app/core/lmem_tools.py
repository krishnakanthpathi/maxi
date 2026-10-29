"""
Maxi Native LightMem (LMEM) Memory Tools
Provides direct, first-class LangChain tool interfaces to the local LMEM engine:
- lmem_recall: Search and retrieve stored user preferences, facts, and context.
- lmem_answer: Direct semantic Q&A over persistent memories.
- lmem_remember: Explicitly persist confirmed user facts.
"""

import json
import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import List, Optional
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
    existing = env.get("PATH", os.defpath)
    # Respect the daemon's active environment before looking in fallback installs.
    env["PATH"] = os.pathsep.join(dict.fromkeys(existing.split(os.pathsep) + extra_paths))
    env["HOME"] = home
    return env


def _run_lmem(args: List[str], timeout_s: float = 12.0) -> str:
    env = _get_lmem_env()
    bin_path = env.get("MAXI_LMEM_BIN") or shutil.which("lmem", path=env["PATH"]) or "lmem"
    try:
        res = subprocess.run(
            [bin_path] + args,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_s,
        )
        output = (res.stdout or "").strip()
        error = (res.stderr or "").strip()
        if res.returncode != 0:
            details = "\n".join(part for part in (error, output) if part)
            if "schema is newer" in details.lower():
                return (
                    f"Error: LightMem at {bin_path} is older than the memory database schema. "
                    "Upgrade that LightMem executable to a version supporting this schema. "
                    "Keep the existing database; do not downgrade or recreate it.\n" + details
                )
            return f"Error: LightMem exited with code {res.returncode}.\n{details or 'No error details returned.'}"
        if not output and args and args[0] == "remember":
            return "Error: LightMem exited without confirming that the memory was saved."
        return output or "No memories found matching query."
    except subprocess.TimeoutExpired:
        return f"Error: LightMem did not finish within {timeout_s:g} seconds. The operation may still need verification."
    except FileNotFoundError:
        return f"Error: LightMem executable not found at {bin_path}. Install lmem or set MAXI_LMEM_BIN to its executable path."
    except OSError as e:
        logger.error("Could not launch LightMem: %s", type(e).__name__)
        return f"Error executing LightMem: {e}"


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
    return _run_lmem(["answer", clean_q, "--global"])


@tool
def lmem_remember(content: str) -> str:
    """
    Save a confirmed fact, preference, or learning to persistent LightMem memory.
    IMPORTANT: Never store arbitrary memories automatically; only call this tool when
    the user explicitly confirms or asks to save/remember something.
    """
    clean_content = content.strip().strip("'\"")
    logger.info(f"🧠 Persisting memory to LMEM: \"{clean_content}\"")
    return _run_lmem(["remember", clean_content, "--global"])


def auto_recall_memories(prompt: str, limit: int = 2, min_score: float = 0.35) -> str:
    """
    Fast pre-flight LightMem hybrid vector/keyword search.
    Returns a formatted <relevant_memories> block for top matches, or empty string.
    Runs in ~20ms without burning any LLM tool turns.
    """
    clean = prompt.strip().strip("'\"")
    if not clean or len(clean) < 3:
        return ""
    try:
        raw_json = _run_lmem(["recall", clean, "--limit", str(limit), "--global", "--json"], timeout_s=1.5)
        if not raw_json or not raw_json.startswith("["):
            return ""
        items = json.loads(raw_json)
        if not isinstance(items, list):
            return ""
        hits = []
        for item in items:
            score = item.get("score", 0.0)
            mem = item.get("memory", {})
            content = mem.get("content", "").strip()
            cat = mem.get("category", "memory")
            if score >= min_score and content:
                hits.append(f"- [{cat}] {content}")
        if hits:
            return "<relevant_memories>\n" + "\n".join(hits) + "\n</relevant_memories>"
    except Exception as e:
        logger.debug(f"Auto-recall memory hook failed: {e}")
    return ""


def get_lmem_tools() -> List[BaseTool]:
    """Returns the list of first-class LMEM tools."""
    return [lmem_recall, lmem_answer, lmem_remember]
