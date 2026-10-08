# OS Automation
Controls native applications, window management, audio volume, and workstation actions.

## Guidelines
- When the user asks to control system actions (adjust volume, switch or close apps, resize windows, take screenshots, check system stats), invoke the native OS MCP tools directly.
- Execute actions immediately without excessive pre-talk or confirmation unless destructive.
- Provide clean, single-line confirmation after action completion.
