# Interactive terminal

ResearchAssistant includes a full PTY-backed terminal in the browser UI. Open it with the
**Terminal** action in the top bar or with `Ctrl+Shift+Backquote`.

The terminal supports normal shell input and output, ANSI colors, cursor control, scrollback,
copy/paste, terminal resizing, `Ctrl+C`, interactive Python/IPython, Conda activation, `htop`,
`vim`, `tmux`, and other TTY applications. Multiple terminal tabs can remain open at once.

Terminal processes belong to the running ResearchAssistant UI backend. Closing the terminal
dialog or the browser tab disconnects the display but does not terminate the shell. Reopening the
terminal reconnects to the session and replays its recent output. Closing an individual terminal
tab terminates that shell process.

The initial working directory is the active workspace. A different working directory, shell
command, and tab title can be entered before creating a terminal. The shell otherwise defaults to
`$SHELL`, then `bash`, `zsh`, or `sh`.

When the UI is opened with `ra connect`, the UI backend and PTY live on the remote server. The
browser remains local, while terminal commands execute directly in the remote workspace and its
environment. No additional SSH tunnel or browser process is required beyond the connection already
managed by `ra connect`.

Terminal sessions survive browser reconnects and transient SSH forwarding loss, but they do not
survive termination or restart of the ResearchAssistant UI backend itself. Use `tmux` or `screen`
inside the terminal for jobs that must survive a backend restart.
