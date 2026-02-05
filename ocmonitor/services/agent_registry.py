"""Agent registry for detecting main vs sub-agent types."""

from pathlib import Path
from typing import Dict, Any, Set, Optional


class AgentRegistry:
    """Discovers and manages agent definitions from OpenCode config."""

    # Built-in agents (fallback if no config directory exists)
    BUILTIN_MAIN_AGENTS = {'plan', 'build'}
    BUILTIN_SUB_AGENTS = {'explore'}

    def __init__(self, agents_dir: Optional[Path] = None):
        """Initialize the agent registry.

        Args:
            agents_dir: Path to OpenCode agent config directory.
                       Defaults to ~/.config/opencode/agent
        """
        self.agents_dir = agents_dir or Path.home() / ".config" / "opencode" / "agent"
        self._sub_agents: Set[str] = set()
        self._main_agents: Set[str] = set()
        self._load_agents()

    def _load_agents(self):
        """Scan ~/.config/opencode/agent/ for agent definitions."""
        # Start with built-in agents
        self._main_agents = self.BUILTIN_MAIN_AGENTS.copy()
        self._sub_agents = self.BUILTIN_SUB_AGENTS.copy()

        if not self.agents_dir.exists():
            return

        for md_file in self.agents_dir.glob("*.md"):
            agent_name = md_file.stem  # filename without .md
            agent_config = self._parse_agent_file(md_file)

            mode = agent_config.get('mode', '').lower()
            if mode == 'subagent':
                self._sub_agents.add(agent_name.lower())
            elif mode == 'primary':
                self._main_agents.add(agent_name.lower())
            # If no mode specified, agent is treated as main (default behavior)

    def _parse_agent_file(self, file_path: Path) -> Dict[str, Any]:
        """Parse YAML frontmatter from markdown agent file.

        Args:
            file_path: Path to the agent markdown file

        Returns:
            Dictionary of parsed YAML frontmatter, or empty dict if parsing fails
        """
        try:
            content = file_path.read_text()

            # Extract YAML frontmatter between --- markers
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    import yaml
                    return yaml.safe_load(parts[1]) or {}
        except Exception:
            pass
        return {}

    def is_sub_agent(self, agent_name: Optional[str]) -> bool:
        """Check if an agent is a sub-agent.

        Args:
            agent_name: Name of the agent to check

        Returns:
            True if the agent is a sub-agent, False otherwise
        """
        if agent_name is None:
            return False
        return agent_name.lower() in self._sub_agents

    def is_main_agent(self, agent_name: Optional[str]) -> bool:
        """Check if an agent is a main agent.

        Args:
            agent_name: Name of the agent to check

        Returns:
            True if the agent is a main agent or unknown, False if it's a sub-agent
        """
        if agent_name is None:
            return True  # Default to main if unknown
        agent_lower = agent_name.lower()
        return agent_lower in self._main_agents or agent_lower not in self._sub_agents

    def get_all_sub_agents(self) -> Set[str]:
        """Get all registered sub-agent names.

        Returns:
            Set of sub-agent names
        """
        return self._sub_agents.copy()

    def get_all_main_agents(self) -> Set[str]:
        """Get all registered main agent names.

        Returns:
            Set of main agent names
        """
        return self._main_agents.copy()

    def reload(self):
        """Reload agent definitions (for when user adds new agents)."""
        self._sub_agents.clear()
        self._main_agents.clear()
        self._load_agents()
