# Integrated notebooks

ResearchAssistant opens `.ipynb` files directly in the workbench. The notebook editor is not an
embedded JupyterLab page: it uses the existing ResearchAssistant workspace boundary, Monaco editor,
SSH connection, terminal, launch history, model registry, and system monitor.

Open a notebook from Explorer or with **Notebooks** in the top bar. A notebook can contain code,
Markdown, and raw cells. Code cells support `Shift+Enter`, `Ctrl+Enter`, individual execution,
sequential **Run all**, streamed stdout/stderr, exceptions, rich text, JSON, PNG, and JPEG outputs.
Markdown preview is rendered without executing or directly inserting notebook HTML.

The kernel selector lists Jupyter kernelspecs visible to the Python environment that runs the UI.
With `ra connect`, both the notebook kernel and its code run on the remote server. Installing the UI
extra provides a default Python kernel:

```bash
python -m pip install 'research-assistant[ui]'
```

Additional Conda environments can be exposed as ordinary Jupyter kernelspecs. For example:

```bash
conda run -n another-env python -m ipykernel install --user \
  --name another-env --display-name 'Python (another-env)'
```

Kernel processes are detached from the browser and UI server. ResearchAssistant stores their
connection records under `.ra/notebook-kernels/` and reconnects when the browser, SSH forwarding,
or Uvicorn backend is replaced. Kernel variables and running computations therefore survive
`ra connect` reconnection. Explicit **Shut down kernel** terminates the process and removes its
record. Machine restart is not recovered automatically.

Notebook writes use the same optimistic-concurrency rule as the text editor. A save is rejected if
the file changed on disk after it was loaded. Notebook outputs and execution counts are written into
the `.ipynb` file when the notebook is saved.
