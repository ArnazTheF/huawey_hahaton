# Evaluation agreement

User instruction: after the explicitly requested replay of the previously successful
three-task suite, run subsequent agent-quality comparisons on ALL registered tasks.

- Use `scripts/benchmark.py --suite all --comparison solution` for baseline versus
  the recommended profile (`--comparison memory` retains the older off/bounded
  ablation), and the frozen catalog in
  `benchmarks/all-v1/catalog.json` as the standard quality evaluation entry point.
- Include original `task-dir` examples and every distinct generated data variant.
  Exact copies may be deduplicated only with every source alias recorded.
- Report each task and each repetition by name: solved, wrong answer, skipped,
  stopped/error, and not attempted. Report score separately from task counts.
- Never present a narrow diagnostic or unit test as a full quality evaluation.
  A focused diagnostic needs an explicit user request and does not replace full-suite
  evaluation of the change.
- Keep task corpus, model and resource limits fixed between compared methods;
  disclose changes, incomplete coverage, repeated-case dependence and API failures.
- Run live model evaluation in Docker, externally grade answers and code, and
  keep reference answers/tests outside the agent's mounts. Never print `.env`.
- Use non-reasoning models unless the user explicitly requests a reasoning experiment.
