# Managed remote workspaces

`ra connect` opens a ResearchAssistant workspace on an SSH host without starting a browser on the
server and without requiring a manually maintained `ssh -L` command.

The browser always runs on the local machine. The remote ResearchAssistant HTTP server remains
bound to the remote loopback interface, while the local CLI owns the SSH process and its loopback
forwarding. SSH authentication, host aliases, keys, `ProxyJump`, and agent forwarding remain the
responsibility of OpenSSH and `~/.ssh/config`.

## One-off connection

```bash
ra connect gpu-server \
  --workspace /home/akzium/Kuramoto-Neural-Operator \
  --conda-env KNO \
  --plugin ra_project.plugin
```

`gpu-server` may be a host alias from `~/.ssh/config`. By default ResearchAssistant:

1. chooses an unused local port and a high remote port;
2. starts the remote UI inside the selected environment;
3. forwards only `127.0.0.1` on both machines;
4. waits for `/api/bootstrap` to become available;
5. opens the resulting local URL in the local browser;
6. reconnects with bounded backoff after a transient SSH failure.

Workspace paths may be absolute or relative. Relative paths are resolved exactly once from the SSH
login directory. For example, `--workspace KNO-paper/` resolves to `$HOME/KNO-paper` for a normal
home-directory SSH login.

Use an explicit interpreter instead of Conda when needed:

```bash
ra connect gpu-server \
  --workspace /srv/project \
  --remote-python /srv/venvs/project/bin/python
```

The selected remote environment must contain ResearchAssistant and the optional UI dependencies:

```bash
python -m pip install -e '.[ui]'
```

The UI extra installs Uvicorn's WebSocket transport, which is required by the browser terminal.
Existing environments created with an older UI extra can be repaired with:

```bash
python -m pip install 'uvicorn[standard]'
```

For terminal tabs to survive `ra connect` reconnects and remote UI-backend restarts, install tmux on
the server. A Conda installation can be kept inside the selected environment:

```bash
conda install -n KNO -c conda-forge tmux
```

ResearchAssistant creates a dedicated tmux server for each resolved workspace. It does not reuse or
modify ordinary user tmux sessions. New UI backends rediscover the persistent tabs automatically.
Closing a terminal tab explicitly terminates its corresponding tmux session.

Closing `ra connect` stops only the temporary UI server and SSH connection. Detached schedulers,
workers, and tmux-backed terminal sessions continue running and are rediscovered after reconnecting.

## Profiles

Save a connection while opening it:

```bash
ra connect gpu-server \
  --workspace /home/akzium/Kuramoto-Neural-Operator \
  --conda-env KNO \
  --plugin ra_project.plugin \
  --save kno
```

Subsequent connections need only the profile name:

```bash
ra connect kno
```

Profiles can also be managed explicitly:

```bash
ra remote add kno \
  --target gpu-server \
  --workspace /home/akzium/Kuramoto-Neural-Operator \
  --conda-env KNO \
  --plugin ra_project.plugin

ra remote list
ra remote remove kno
```

Profiles are stored under `${XDG_CONFIG_HOME:-~/.config}/research-assistant/remotes.json`. They
contain only the SSH target, remote path, environment selector, and plugin names. Passwords,
private keys, and SSH tokens are never stored by ResearchAssistant.

## Connection options

Use fixed ports only when external tooling requires them:

```bash
ra connect kno --local-port 8765 --remote-port 38765
```

Disable browser opening or automatic reconnect:

```bash
ra connect kno --no-open
ra connect kno --no-reconnect
```

Additional OpenSSH options can be supplied without bypassing the normal SSH configuration:

```bash
ra connect kno --ssh-option ProxyJump=bastion
```

The older `ra ui --ssh` workflow remains available as a compatibility fallback, but `ra connect`
is the normal remote entry point.
