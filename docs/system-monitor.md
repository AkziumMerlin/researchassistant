# System monitor

ResearchAssistant includes a live host and GPU monitor in the browser UI. Open **Monitor** in the
top bar or press `Ctrl+Shift+M`.

The monitor combines the useful parts of `htop` and `nvtop` with ResearchAssistant run metadata:

- aggregate and per-core CPU utilization;
- load average, uptime, memory, swap, workspace-disk usage, and network throughput;
- NVIDIA GPU utilization, memory, power, temperature, PCI bus ID, and compute-process count;
- a sortable and filterable process table with CPU, resident memory, GPU memory, state, thread
  count, runtime, user, and command;
- filters for all processes, current-user processes, GPU processes, and ResearchAssistant-managed
  processes;
- correlation of scheduler, worker, and descendant PIDs with launch, study, trial, run, active
  stage, run state, and assigned GPU;
- process details with bounded tails of worker, scheduler, and resource-event logs;
- `SIGINT`, `SIGTERM`, `SIGKILL`, `SIGHUP`, `SIGSTOP`, and `SIGCONT` actions for processes owned by
  the current user, with an explicit browser confirmation.

No `RA_TRUSTED_DEV` switch or separate monitor permission mode is used. The UI server remains
loopback-only. Process signalling is limited to the operating-system user running the server and
cannot target PID 1 or the ResearchAssistant UI process itself.

## Remote work

When the UI is started through `ra connect`, all samples are collected on the selected remote
server. The browser remains local. CPU, memory, GPU, process, run, and log information therefore
refer to the remote workspace and machine without requiring a second tunnel or a remote browser.

## NVIDIA support

GPU monitoring uses the driver-provided `nvidia-smi` command. If it is absent or the host has no
NVIDIA GPU, the CPU, memory, disk, network, and process monitor remains available and the GPU panel
shows the query error. ResearchAssistant does not install NVIDIA drivers or `nvidia-smi`.

## Run correlation

The monitor reads current UI-launch records from `.ra/ui-launches/` and run-local `launcher.json`,
`status.json`, and `manifest.json` files. It also discovers conventional workspace artifact roots
with the layout `<root>/<study>/<run>/launcher.json`. Child processes inherit their nearest known
ResearchAssistant parent, which covers data-loader workers and subprocesses started by a run.

The run index is cached briefly so frequent UI polling does not repeatedly scan artifact metadata.
Process and log payloads are bounded; the monitor never sends an unbounded process table or full log
file to the browser.
