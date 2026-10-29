# Maxi MCP Servers & Skills Management
Guides the user on how to add, configure, and customize MCP tools, skills, and LLM models in Hey Maxi.

<!-- triggers: skill, skills, mcp, mcps, add skill, create skill, add mcp, new skill, tool, configure mcp, install mcp, model, change model, switch model, how to add, how do i add, add tools, custom tools -->

## Guidelines
Whenever the user asks how to add a skill, add an MCP tool, change/switch models, or extend Maxi, give them direct, punchy, actionable instructions explaining exactly where to go and what files to create or edit.

### 1. How to Add a Skill to Maxi
- **Location**: `~/.maxi/skills/`
- **Steps**:
  1. Create a markdown file (e.g. `~/.maxi/skills/my_skill.md`).
  2. Put the skill title on line 1: `# My Skill Name`
  3. Add trigger keywords as an HTML comment: `<!-- triggers: keyword1, keyword2, phrase -->`
  4. Write the behavioral instructions, rules, and guidelines for the agent below.
- **Reloading**: Maxi automatically scans `~/.maxi/skills/` dynamically on every turn. No restart is needed!

### 2. How to Add an MCP Server to Maxi
- **Location**: `~/.maxi/mcp_config.json`
- **Steps**:
  1. Open `~/.maxi/mcp_config.json`.
  2. Add your MCP server configuration under `"mcpServers"`:
     ```json
     {
       "mcpServers": {
         "my-service": {
           "command": "/path/to/python_or_node",
           "args": ["/path/to/server.py"],
           "env": {
             "API_KEY": "..."
           }
         }
       }
     }
     ```
  3. Reload MCP servers by clicking the menu bar icon -> **Reload Skills & MCP Servers**, or run:
     `curl -X POST http://127.0.0.1:4848/api/reload`

### 3. How to Switch or Add Models
- **Via Menu Bar**: Click the Maxi status bar icon (waveform circle) at the top right of your screen -> **Model** -> select a model or click **Custom Model...**.
- **Via CLI / API**:
  `curl -X POST http://127.0.0.1:4848/api/config -H "Content-Type: application/json" -d '{"model": "gemma4:31b-cloud"}'`
- **Via `.env` file**: Edit `OPENAI_MODEL=<model_name>` in `~/.maxi/.env`.
- **Supported Models**: Any local Ollama model (`gemma4:31b-cloud`, `gpt-oss:120b-cloud`), Groq models (`llama-3.3-70b-versatile`), or OpenRouter models.
