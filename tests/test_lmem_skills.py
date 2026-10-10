import unittest
from unittest.mock import patch, MagicMock
from app.core.lmem_tools import get_lmem_tools, lmem_recall, lmem_answer, lmem_remember, _run_lmem
from app.core.skills import SkillRegistry, Skill
from app.core.agent import MaxiAgent


class TestLmemTools(unittest.TestCase):
    def test_get_lmem_tools_returns_all_three_tools(self):
        tools = get_lmem_tools()
        self.assertEqual(len(tools), 3)
        tool_names = [t.name for t in tools]
        self.assertIn("lmem_recall", tool_names)
        self.assertIn("lmem_answer", tool_names)
        self.assertIn("lmem_remember", tool_names)

    @patch("subprocess.run")
    def test_lmem_recall_invokes_cli_with_global_and_multi_hop(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.stdout = "Stefan's favorite theme song: https://youtube.com/..."
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        result = lmem_recall.invoke({"query": "favorite song"})
        self.assertIn("Stefan's favorite", result)
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        self.assertTrue(cmd[0].endswith("lmem") or "lmem" in cmd[0])
        self.assertEqual(cmd[1:], ["recall", "favorite song", "--global", "--multi-hop"])

    @patch("subprocess.run")
    def test_lmem_answer_invokes_cli_answer(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.stdout = "Your favorite song is theme song"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        result = lmem_answer.invoke({"question": "what is my favorite song?"})
        self.assertEqual(result, "Your favorite song is theme song")
        args, kwargs = mock_run.call_args
        cmd = args[0]
        self.assertEqual(cmd[1:], ["answer", "what is my favorite song?"])

    @patch("subprocess.run")
    def test_lmem_remember_invokes_cli_remember(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.stdout = "Memory saved successfully [id: mem_123]"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        result = lmem_remember.invoke({"content": "Prefers dark mode on all IDEs"})
        self.assertIn("saved successfully", result)
        args, kwargs = mock_run.call_args
        cmd = args[0]
        self.assertEqual(cmd[1:], ["remember", "Prefers dark mode on all IDEs"])


class TestSkillRegistryMemoryTriggers(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry()

    def test_memory_skill_loaded_with_triggers(self):
        memory_skill = self.registry.get("memory")
        self.assertIsNotNone(memory_skill)
        # Check that triggers defined in comment are loaded
        self.assertTrue("favorite" in memory_skill.keywords or "song" in memory_skill.keywords)

    def test_find_relevant_skills_matches_favorite_song(self):
        skills = self.registry.find_relevant_skills("Play my favorite song", source="text")
        skill_names = [s.name for s in skills]
        self.assertIn("memory", skill_names)

    def test_find_relevant_skills_matches_who_is(self):
        skills = self.registry.find_relevant_skills("Who is Farhan?", source="text")
        skill_names = [s.name for s in skills]
        self.assertIn("memory", skill_names)

    def test_find_relevant_skills_matches_my_routine(self):
        skills = self.registry.find_relevant_skills("What is my routine for tomorrow?", source="text")
        skill_names = [s.name for s in skills]
        self.assertIn("memory", skill_names)

    def test_find_relevant_skills_matches_remember_prompt(self):
        skills = self.registry.find_relevant_skills("Remember that I prefer coffee over tea", source="text")
        skill_names = [s.name for s in skills]
        self.assertIn("memory", skill_names)


class TestAgentToolsBinding(unittest.TestCase):
    def test_agent_get_all_tools_includes_lmem(self):
        agent = MaxiAgent()
        tools = agent._get_all_tools()
        names = {t.name for t in tools}
        self.assertIn("lmem_recall", names)
        self.assertIn("lmem_answer", names)
        self.assertIn("lmem_remember", names)


if __name__ == "__main__":
    unittest.main()
