from research_assistant.cli_remote import install as install_remote_cli
from research_assistant.cli_research import app
from research_assistant.cli_workspace_v2 import install as install_workspace_v2_cli
from research_assistant.explorer_ui import install as install_explorer_ui

__all__ = ["app"]

install_remote_cli(app)
install_workspace_v2_cli(app)
install_explorer_ui()
