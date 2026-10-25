# Contributing

Thanks for helping. Issues and pull requests are welcome.

## Setup

```bash
git clone https://github.com/harelhz/echoscope && cd echoscope
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check src tests
```

## Good first contributions

- A collector for another platform. It only needs to yield `echoscope.models.Post` objects;
  see `collectors/jsonl.py` for the smallest example.
- Normalisation rules for another language or script
- New scenarios in `demo.py` that break the detector. Hard negatives are especially valuable.

## Guidelines

- Every detection change should keep `tests/test_pipeline.py::test_benchmark_scenario`
  green. If it doesn't, explain the trade-off in the pull request.
- New signals must explain themselves: each `Signal` needs a human-readable `reason`.
- Features have to respect [ETHICS.md](ETHICS.md). Pull requests that deanonymise
  individuals or access non-public data won't be merged.
