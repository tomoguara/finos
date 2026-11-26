"""Evaluation: measure the support system's quality layer by layer.

- :mod:`finos.evaluation.datasets` — the versioned datasets in ``evals/datasets/``
- :mod:`finos.evaluation.evaluators` — code evaluators (routing, MRR, keywords, rules)
- :mod:`finos.evaluation.judge` — judge evaluators (faithfulness, correctness, empathy)
- :mod:`finos.evaluation.runner` — variants, the local runner, the LangSmith runner
- :mod:`finos.evaluation.gates` — the quality gates

Importing this package loads no settings and imports neither LangChain nor
``langsmith``; each module imports them inside the functions that need them.
"""
