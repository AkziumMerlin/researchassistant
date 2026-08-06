# Importing an existing experiment project

ResearchAssistant can adopt an existing Python/YAML experiment repository without rewriting its
source tree or replacing its original runner.

## Preview the import

Run the scanner from the project root:

```bash
ra project scan .
```

The scanner:

- parses Python files through the standard-library AST and does not execute them;
- detects conventional model, dataset, loss, optimizer, scheduler, transform, and stage symbols;
- detects legacy experiment YAMLs;
- searches for common YAML runners such as `examples/train_from_yaml.py`;
- ignores generated outputs, virtual environments, VCS metadata, caches, runs, checkpoints, and
  previously generated `configs/registered` wrappers;
- marks high-confidence candidates as recommended while retaining medium-confidence candidates for
  review.

Use JSON when another tool needs the complete plan or candidate IDs:

```bash
ra project scan . --json
```

## Import the recommended candidates

Interactive use:

```bash
ra project import .
```

Unattended use:

```bash
ra project import . --yes
```

The default import includes only recommended candidates. To include every discovered candidate:

```bash
ra project import . --all --yes
```

To import an explicit subset, copy IDs from `ra project scan . --json`:

```bash
ra project import . \
  --candidate py-0123456789abcdef \
  --candidate cfg-fedcba9876543210 \
  --yes
```

Other useful modes:

```bash
ra project import . --dry-run
ra project import . --no-python --yes
ra project import . --no-configs --yes
```

## Files created by the import

Project-local component and legacy-config registrations are stored in:

```text
.research-assistant/registrations.yaml
```

The last batch-import result is stored in:

```text
.research-assistant/import.yaml
```

Legacy YAMLs are not modified. ResearchAssistant creates current-format wrappers while preserving
their relative layout. For example:

```text
configs/baselines/fno.yaml
    -> configs/registered/baselines/fno.yaml
```

The wrapper delegates to the original project runner, so the old registry, data-loading logic,
training protocol, sweep semantics, resume flags, and existing YAML structure remain active.

Python registrations are validated individually in the current project environment. A failed
optional component is rolled back without preventing valid components and legacy configs from being
imported. Running the command again is idempotent: existing registrations are reported rather than
duplicated.

## Desktop workflow

In ResearchAssistant Desktop, open:

```text
Register -> Import project
```

Then:

1. Choose whether to discover Python components and legacy YAMLs.
2. Select **Scan project**.
3. Review the candidates and confidence labels.
4. Keep the recommended checkboxes or change the selection.
5. Select **Import checked**.

The live component catalog is refreshed after a successful import; restarting the sidecar is not
required.

## KNO/RPB example

For a project containing `models/kno.py`, RPB factories, old experiment YAMLs, and
`examples/train_from_yaml.py`:

```bash
cd /home/akzium/Kuramoto-Neural-Operator
ra project scan .
ra project import .
```

The scanner should recommend architecture entry points such as `KNO`, explicit RPB/dataset
factories, and the legacy experiment YAMLs. Ordinary internal layers are left as review candidates
or omitted instead of filling the component catalog automatically.

A legacy experiment can then be run through its generated wrapper:

```bash
ra run configs/registered/path/to/experiment.yaml
```
