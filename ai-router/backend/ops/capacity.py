"""
Capacity planning for the hosted-scale plan (Section 5 of the architecture
document). Pure arithmetic, no I/O - use it to size a purchase BEFORE
spending. All results are order-of-magnitude planning numbers, not quotes.

  training memory  ~ 16 bytes/param (mixed precision + Adam) + activations
  inference memory ~ 2 bytes/param (16-bit) or 1 (8-bit) + KV cache
  training compute C = 6 * N * D
  compute-optimal D ~ 20 * N
  time = C / (GPUs * peak FLOP/s * utilisation)
"""

H100_PEAK_FLOPS = 989e12          # dense BF16, NVIDIA H100 SXM
H100_MEMORY_GB = 80
DEFAULT_UTILISATION = 0.40
DEFAULT_PRICE_RANGE = (2.0, 4.5)  # USD per GPU-hour; verify current prices before budgeting
TOKENS_PER_PARAM = 20
BYTES_PER_PARAM_TRAINING = 16
EXPERIMENT_MULTIPLIER = (3, 10)   # planning assumption: experiments, failed runs, evals
CHARS_PER_TOKEN = 4
SYNAPSE_BYTES = 8                 # index + weight, sparse storage


def training_flops(params: float, tokens: float) -> float:
    return 6.0 * params * tokens


def compute_optimal_tokens(params: float) -> float:
    return TOKENS_PER_PARAM * params


def training_memory_gb(params: float) -> float:
    return params * BYTES_PER_PARAM_TRAINING / 1e9


def serving_memory_gb(params: float, bits: int = 16) -> float:
    return params * (bits / 8) / 1e9


def gpu_hours(flops: float, gpus: int = 1, peak_flops: float = H100_PEAK_FLOPS,
              utilisation: float = DEFAULT_UTILISATION) -> float:
    return flops / (gpus * peak_flops * utilisation) / 3600.0


def plan_language_model(params: float, tokens: float | None = None, gpus: int = 1,
                        price_range: tuple = DEFAULT_PRICE_RANGE, bits: int = 16) -> dict:
    """One clean final training run, plus the planning range once experiments
    and failed runs are included."""
    tokens = compute_optimal_tokens(params) if tokens is None else tokens
    flops = training_flops(params, tokens)
    hours = gpu_hours(flops, gpus=gpus)
    gpu_hours_total = hours * gpus
    lo, hi = price_range
    train_gb = training_memory_gb(params)
    return {
        "parameters": params, "tokens": tokens, "training_flops": flops,
        "gpu_hours": round(gpu_hours_total, 1), "wall_clock_hours": round(hours, 1), "gpus": gpus,
        "cost_usd": {"low": round(gpu_hours_total * lo), "high": round(gpu_hours_total * hi)},
        "cost_with_experiments_usd": {"low": round(gpu_hours_total * lo * EXPERIMENT_MULTIPLIER[0]),
                                      "high": round(gpu_hours_total * hi * EXPERIMENT_MULTIPLIER[1])},
        "training_state_gb": round(train_gb, 2),
        "fits_one_h100_for_training": train_gb < H100_MEMORY_GB,
        "serving_memory_gb": round(serving_memory_gb(params, bits), 2),
        "raw_text_gb": round(tokens * CHARS_PER_TOKEN / 1e9, 1),
        "assumptions": {"utilisation": DEFAULT_UTILISATION, "gpu": "H100 SXM 989 TFLOPS BF16",
                        "price_usd_per_gpu_hour": list(price_range),
                        "note": "order-of-magnitude estimate; verify prices and re-measure utilisation"},
    }


def spiking_memory(neurons: float, synapses_per_neuron: float) -> dict:
    synapses = neurons * synapses_per_neuron
    gb = synapses * SYNAPSE_BYTES / 1e9
    return {"neurons": neurons, "synapses": synapses, "memory_gb": round(gb, 3),
            "fits_one_h100": gb < H100_MEMORY_GB,
            "comment": "use procedural connectivity or several GPUs" if gb >= H100_MEMORY_GB else "fits on one GPU"}


# Section 10: scale only when the previous rung passes its test.
LADDER = [
    {"rung": 0, "what": "Lesson 1-2 networks, math unit tests", "hosting": "any CPU server", "go_test": "all tests pass"},
    {"rung": 1, "what": "Mind v0.1 'Forager' in a simulated world", "hosting": "one CPU server + Postgres",
     "go_test": "reward learning, replay benefit and calibration tests pass"},
    {"rung": 2, "what": "Neuron-level math library validated against reference results", "hosting": "one GPU, on demand",
     "go_test": "HH, STDP, Hopfield and drift-diffusion tests pass"},
    {"rung": 3, "what": "100M-parameter language model from scratch", "hosting": "one GPU, hours",
     "go_test": "validation loss falls; coherent samples"},
    {"rung": 4, "what": "Specialists and Council running as services", "hosting": "multi-service deployment",
     "go_test": "Council beats the best single specialist on the test set"},
    {"rung": 5, "what": "1B-parameter model, sleep jobs, canary releases", "hosting": "one to a few GPUs",
     "go_test": "passes the regression and calibration gate"},
    {"rung": 6, "what": "Spiking research tier at 1e5-1e7 neurons", "hosting": "one GPU",
     "go_test": "reproduces published reference behaviour"},
    {"rung": 7, "what": "7B+ model", "hosting": "multi-GPU cluster",
     "go_test": "only if scaling curves from rungs 3-5 justify it and the data exists"},
]