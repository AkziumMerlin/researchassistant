# Interactive terminal

ResearchAssistant includes a full PTY-backed terminal in the browser UI. Open it with the
**Terminal** action in the top bar or with `Ctrl+Shift+Backquote`.

The terminal supports normal shell input and output, ANSI colors, cursor control, scrollback,
copy/paste, terminal resizing, `Ctrl+C`, interactive Python/IPython, Conda activation, `htop`,
`vim`, and other TTY applications. Multiple terminal tabs can remain open at once.

## Persistent sessions

When `tmux` is installed on the machine running the UI backend, each browser tab is backed by a
workspace-scoped tmux session. The tmux server is independent of the browser, SSH connection, and
ResearchAssistant Uvicorn process. Consequently, the shell process, current directory, environment,
running foreground program, terminal screen, and tmux scrollback survive:

- closing and reopening the terminal dialog;
- reloading or closing the browser;
- temporary SSH-forwarding loss;
- `ra connect` reconnects that start a new remote UI backend;
- manually stopping and later restarting `ra ui` for the same workspace.

A restarted UI backend discovers the existing workspace-scoped tmux sessions and reconnects the
terminal tabs automatically. Closing an individual terminal tab explicitly kills that tmux session.
The sessions do not survive a server reboot unless the host separately restores its tmux server.

ResearchAssistant uses a dedicated tmux socket derived from the resolved workspace path. It does not
attach to, rename, or modify the user's ordinary tmux sessions.

Install tmux through the host package manager or Conda, for example:

```bash
conda install -n KNO -c conda-forge tmux
```

If `tmux` is absent, the terminal falls back to a process owned by the current UI backend. The UI
reports that fallback explicitly; those fallback sessions cannot survive a backend restart.

## Working directory and remote execution

The initial working directory is the active workspace. A different working directory, shell
command, and tab title can be entered before creating a terminal. The shell otherwise defaults to
`$SHELL`, then `bash`, `zsh`, or `sh`.

When the UI is opened with `ra connect`, the terminal and tmux server live on the remote server. The
browser remains local, while commands execute directly in the remote workspace and selected
environment. No additional SSH tunnel or remote browser process is required beyond the connection
already managed by `ra connect`.

The UI extra includes Uvicorn's WebSocket transport. Existing installations made before this change
can be repaired with:

```bash
python -m pip install 'uvicorn[standard]'
```
