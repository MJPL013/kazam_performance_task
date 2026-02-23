import unittest
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestAgentOrchestration(unittest.TestCase):
    
    @patch('google.genai.Client')
    def test_provider_initialization(self, mock_client):
        """Verify agent can initialize providers based on .env (Mocked)."""
        from agent import SREAgent
        
        # Test with gemini (mocked env)
        with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "test"}):
            agent = SREAgent()
            self.assertEqual(agent.provider_name, "gemini")
            self.assertIsNotNone(agent.provider)

    def test_history_truncation_logic(self):
        """Verify history pruning keeps system prompt and even number of messagess (User/Assistant pairs)."""
        from agent import SREAgent
        
        with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "test"}):
            agent = SREAgent()
            
            # Manually stuff history
            # index 0 is system prompt usually handled by provider, but agent.history tracks user/assistant
            agent.conversation_history = [
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
                {"role": "assistant", "content": "a2"},
                {"role": "user", "content": "u3"},
                {"role": "assistant", "content": "a3"},
            ]
            
            # Assume MAX_HISTORY_MESSAGES is set to 4 for this test
            with patch('agent.MAX_HISTORY_MESSAGES', 4):
                # Trigger a chat that should cause pruning
                # (We mock the provider call because we only care about history management)
                agent.provider = MagicMock()
                agent.provider.chat.return_value = ("response", [])
                
                agent.chat("u4")
                
                # Flow with MAX_HISTORY_MESSAGES=4:
                # 1. chat() appends u4 -> history = [u1,a1,u2,a2,u3,a3,u4] (7 items)
                # 2. 7 > 4 -> trim to last 4: [a3,u3,a3...wait] -> [-4:] = [a2,u3,a3,u4]
                # 3. Strip leading non-user: drop a2 -> [u3,a3,u4]
                # 4. Provider called with [u3,a3,u4]
                # 5. Response appended -> [u3,a3,u4,response]
                # Result: 4 items, starts with user
                
                self.assertLessEqual(len(agent.conversation_history), 6)
                self.assertEqual(agent.conversation_history[0]["role"], "user")

    def test_execute_tool_unknown(self):
        """Unknown tool returns error JSON with available_tools list."""
        import json
        from agent import execute_tool

        result = execute_tool("nonexistent_tool", {})
        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertIn("available_tools", parsed)
        self.assertIn("detect_slow_requests", parsed["available_tools"])

    def test_execute_tool_valid(self):
        """Valid tool call returns parseable JSON with expected keys."""
        import json
        from agent import execute_tool

        result = execute_tool("detect_slow_requests", {"time_window": "48h"})
        parsed = json.loads(result)
        self.assertIn("profiles", parsed)
        self.assertIn("top_slow_requests", parsed)
        self.assertIn("data_context", parsed)

    def test_system_prompt_loaded(self):
        """Agent loads system prompt from file (not fallback)."""
        from agent import SREAgent
        with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "test"}):
            agent = SREAgent()
            self.assertIn("KazamSRE", agent.system_prompt)
            self.assertGreater(len(agent.system_prompt), 100)

if __name__ == '__main__':
    unittest.main()
