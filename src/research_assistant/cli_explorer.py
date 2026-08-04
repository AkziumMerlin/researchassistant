from research_assistant.cli_remote import install as install_remote_cli
from research_assistant.cli_research import app

__all__ = ["app"]

install_remote_cli(app)
