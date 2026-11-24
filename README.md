# Evals in CI/CD

Starter code for the AI Shipping Labs workshop "Evals in CI/CD" (November 24, 2026).

The base is the FAQ agent and eval pipeline from
[Using Jev for LLM Evaluations](https://github.com/AI-Shipping-Labs/workshops/tree/main/2026/2026-09-22-using-jev-for-llm-evaluations).
I kept only the OpenAI baseline judge and removed the Jev and Laya judges.

## What's here

- `agent.py`, `search.py`, `renderer.py`, `cli.py`: the FAQ agent. It uses the
  OpenAI Responses API with one `search` tool over the DE Zoomcamp FAQ (`minsearch`).
- `evals/synthetic/run.py`: runs the agent over `questions_sample.csv` (50 questions)
  and saves answers plus tool trajectories to `evals_run_*.json`.
- `evals/synthetic/judge.py` and `run_judge.py`: an LLM judge (`gpt-5.4-mini`) with
  three good/bad checks: correctness, instruction following and trajectory. It writes
  `*_judged.json` and a Markdown/JSON report with the cost.
- `evals/synthetic/data/evals_run_sample.json`: a recorded 10-entry run. You can try
  the judge on it without running the agent.

## Setup

```bash
uv sync
cp env.example .env   # put OPENAI_API_KEY in .env
uv run python cli.py "How do I install Kafka?"
uv run python -m evals.synthetic.run --limit 5 --concurrency 3
uv run python -m evals.synthetic.run_judge --data evals/synthetic/data/evals_run_sample.json
```

## Tests and CI

```bash
uv run pytest -v
```

- `tests/test_search.py`: offline checks on the FAQ search. These don't need an API key.
- `tests/test_agent.py`: one real agent run (one question). It checks that the agent
  calls `search`, that the answer ends with a `Sources` section, and that the cited
  ids come from the search results. Locally these tests skip without
  `OPENAI_API_KEY`. In CI they fail without it.
- `.github/workflows/tests.yml` runs the suite on every push to `main` and on
  manual dispatch. It needs an `OPENAI_API_KEY` repository secret.

## Plan for the workshop (to build live)

1. Deterministic tests (`tests/`, pytest). These are cheap and run on every push:
   - search returns results
   - the agent calls `search`
   - the answer has a `Sources` section

   For the style, see `docs/test-guidelines.md` from the Investment Coach workshop.
2. An eval gate script. It runs the agent on a small fixed subset, judges the
   answers, computes pass rates per check, and compares them with thresholds or a
   committed baseline. If quality drops, it exits with a non-zero code.
3. GitHub Actions:
   - `tests.yml` runs on every push and PR.
   - `evals.yml` runs on PRs that touch the prompt, agent or search, or when
     triggered manually.

   The workflow reads `OPENAI_API_KEY` from repo secrets, uploads the report as an
   artifact and posts a summary to the PR. The deploy job only runs if the evals pass.
4. Cost control: use a small subset and a cheap judge in PRs, and run the full
   set on a schedule or with Batch.
