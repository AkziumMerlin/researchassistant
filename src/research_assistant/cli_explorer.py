from research_assistant.cli_desktop import install as install_desktop_cli
from research_assistant.cli_legacy import install as install_legacy_cli
from research_assistant.cli_remote import install as install_remote_cli
from research_assistant.cli_research import app
from research_assistant.cli_update import install as install_update_cli

__all__ = ["app"]

install_remote_cli(app)
install_desktop_cli(app)
install_update_cli(app)
install_legacy_cli(app)
