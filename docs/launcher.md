# Local subprocess and shared-GPU launcher

The local launcher assigns one immutable run manifest to one subprocess. CUDA assignment happens
outside model and training code through `CUDA_VISIBLE_DEVICES`, so a worker always sees its
assigned physical device as local `cuda:0`.

Launcher policy is stored in a separate YAML file. Operational changes such as a different memory
threshold do not change scientific run or trial identities.

```yaml
version: 1
type: core/local-subprocess

params:
  max_parallel: 4
  poll_interval_seconds: 2
  sample_interval_seconds: 2
  fail_fast: false

  gpu:
    devices: [0, 1, 2, 3]
    min_free_memory_gb: 6
    reserve_memory_gb: 1
    default_required_memory_gb: 4
    max_utilization_percent: 70
    foreign_processes: allow
    max_our_jobs_per_gpu: 1
    historical_memory_safety_factor: 1.2
```

Run a plan with that policy:

```bash
ra launch configs/experiment.yaml --launcher configs/shared-gpu-launcher.yaml
```

Any launcher field can be changed without editing YAML:

```bash
ra launch configs/experiment.yaml \
  --launcher configs/shared-gpu-launcher.yaml \
  --launcher-set params.gpu.min_free_memory_gb=10 \
  --launcher-set params.gpu.max_utilization_percent=50
```

## Shared GPU policy

Foreign CUDA processes are allowed by default. A GPU is eligible when all these constraints hold:

1. its physical index is permitted by `devices`, when the list is configured;
2. current device utilization is at most `max_utilization_percent`;
3. current free memory satisfies both the global free-memory floor and the run estimate plus
   `reserve_memory_gb`;
4. ResearchAssistant has fewer than `max_our_jobs_per_gpu` active workers on it.

`foreign_processes: block` is available for an exclusive workstation, but is not the default. The
launcher never terminates or modifies foreign processes. Its filesystem leases coordinate only
ResearchAssistant schedulers on the same host.

The scheduler chooses the least-utilized eligible device. Free memory is measured after allocations
from other users, so those jobs naturally participate in the placement decision without making a
partially occupied GPU unusable.

## Memory prediction

Required memory is selected in this order:

1. explicit `resources.memory_gb` from the experiment;
2. maximum observed process-memory peak for the exact `trial_id`, multiplied by
   `historical_memory_safety_factor`;
3. `default_required_memory_gb` for a configuration that has no history.

Because `trial_id` excludes the random seed but includes the resolved model, data, recipe, stages,
and their parameters, observations from repeated seeds are reusable without confusing different
architectures or hyperparameters.

## Resource artifacts

Each launcher-managed run adds:

```text
run-dir/
├── launcher.json
├── worker.log
├── resource-events.jsonl
└── resources.json
```

`resources.json` keeps all attempts, including failed attempts followed by a resume. Its `total`
therefore represents the compute actually spent to obtain the completed run.

The fields have intentionally different attribution guarantees:

| Field | Attribution | Meaning |
|---|---|---|
| `wall_seconds` | run process | total elapsed time across attempts |
| `gpu_wall_seconds` | run process | time for which the worker was assigned a GPU |
| `process_memory_peak_mb` | sampled run PID | peak seen by periodic compute-app queries |
| `framework_memory_reserved_peak_mb` | exact PyTorch worker | allocator high-water mark |
| `placement_memory_peak_mb` | run estimate | maximum of sampled process and framework peaks |
| `device_memory_peak_mb` | whole GPU | includes every user on the device |
| `device_active_seconds` | whole GPU | sampled utilization integral, not model-only compute |
| `device_energy_joules` | whole GPU | sampled device power, not attributable on a shared GPU |

The honest cross-run compute comparison is GPU wall time plus `placement_memory_peak_mb`. PyTorch
allocator peaks are captured inside the worker, so a short allocation between `nvidia-smi` samples
is not lost. Device-wide utilization and energy remain useful context, but ResearchAssistant does
not label them as costs of one model when foreign processes were present.

Aggregate exact configurations across seeds:

```bash
ra report resources runs
ra report resources runs --config configs/experiment.yaml
ra report resources runs --trial 12ab34cd56 --json
```

## Current limits

- NVIDIA GPUs on Linux, discovered through the driver-provided `nvidia-smi` command;
- one GPU per run;
- no MIG-specific placement policy yet;
- the scheduler process currently remains attached while monitoring workers;
- process GPU-memory reporting depends on driver support for the compute-app query.
