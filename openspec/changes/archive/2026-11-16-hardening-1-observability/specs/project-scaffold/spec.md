# Spec Delta

## MODIFIED Requirements

### Requirement: Project installs from a locked dependency set
The project SHALL install with `uv sync` on Python 3.12 from a committed `uv.lock`, using the LangChain 0.3 generation. `langchain-text-splitters` SHALL be a direct dependency, because the policy agent imports it, and `langsmith` SHALL be a direct dependency, because the observability support imports it. Core dependencies SHALL NOT include `langchain-community`, which belongs to the hardening layers.

#### Scenario: Clean install
- **WHEN** `uv sync --locked` runs in a fresh checkout
- **THEN** it succeeds, and importing the OpenAI and Ollama chat and embedding models, the graph builder, the Chroma integration, the text splitter, and the tracing client all succeed

#### Scenario: Stack stays on the chosen generation
- **WHEN** the installed versions are listed
- **THEN** `langchain` is 0.3.x, `langgraph` is 0.2.x, `langchain-text-splitters` and `langsmith` are declared in `pyproject.toml`, and `langchain-community` is not a direct dependency
