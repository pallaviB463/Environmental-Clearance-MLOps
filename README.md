# Environmental Clearance Pre-Screening Service

An agentic MLOps mini-project for environmental clearance pre-screening.

The system analyzes a project request, retrieves relevant regulatory provisions, applies applicable conditions, verifies the generated determination against retrieved evidence, and either returns a screening result or escalates the case when it cannot safely determine an answer.

> **Disclaimer:** This system provides a screening opinion only. It is not an authoritative environmental clearance determination.

---

## Current Development Status

This repository currently contains the **Person 1 – Agent Core Workflow** implementation.

The current version uses a **stub regulatory corpus for development and testing**. The stub content is not authoritative legal or regulatory text and will later be replaced by the confirmed retrieval/corpus component during team integration.

---

## Agent Workflow

```text
Project Request
      |
      v
Input Guardrail
      |
      v
Extractor
      |
      v
Analyst
      |
      +----> Search Schedule
      |
      +----> Search Modifying Provisions
      |      (General Condition / Amendment)
      |
      v
Draft Determination
      |
      v
Verifier
      |
      +----> Citation validation
      +----> Required evidence validation
      +----> Category-route consistency
      |
      v
Output Guardrail
      |
      +----> Safe ----> Final Answer
      |
      +----> Unsafe --> Escalation
```

---

## Person 1 – Agent Core

The current implementation includes:

- Typed agent state and request contracts
- LangGraph-based workflow orchestration
- Entity extraction
- Provision analysis
- Schedule retrieval
- Modifier retrieval
- Self-verification
- Citation validation
- Category and route consistency checks
- Controlled escalation
- Maximum step and tool-call limits
- Provider-independent LLM interface
- Stub LLM client
- Retry with exponential backoff
- Timeout handling
- Circuit breaker
- Safe LLM failure handling
- Prompt-injection detection
- Input guardrail
- Output guardrail
- Screening disclaimer
- Local end-to-end execution

---

## Project Structure

```text
Environmental-Clearance-MLOps/
|
├── agent/
│   ├── agents/
│   │   ├── extractor.py
│   │   ├── analyst.py
│   │   └── verifier.py
│   │
│   ├── guardrails/
│   │   ├── injection.py
│   │   ├── output_filter.py
│   │   └── toxicity.py
│   │
│   ├── llm/
│   │   ├── client.py
│   │   ├── stub_client.py
│   │   ├── resilient_client.py
│   │   └── safe_call.py
│   │
│   ├── resilience/
│   │   ├── circuit_breaker.py
│   │   ├── retry.py
│   │   └── timeouts.py
│   │
│   ├── tools/
│   │   ├── search_corpus.py
│   │   ├── get_clause.py
│   │   └── request_fields.py
│   │
│   ├── prompts/
│   │   └── v1/
│   │
│   ├── stub_data/
│   │   └── corpus.json
│   │
│   ├── config.py
│   ├── graph.py
│   └── state.py
│
├── tests/
├── run_local.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Example Scenario

The current development scenario represents an industrial project located near a protected area.

The stub Schedule evidence initially classifies the example project as:

```text
Category B
```

The agent does not stop after the first retrieval. It searches for modifying provisions and retrieves the stub General Condition.

The resulting development-stage determination is:

```text
Category B
    |
    | General Condition applies
    v
Category A
    |
    v
Central Route
```

Both the Schedule and General Condition evidence are retained and verified before the answer is accepted.

> The regulatory text used in this example is test/stub data and must not be interpreted as an actual legal determination.

---

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd Environmental-Clearance-MLOps
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

### 3. Activate the environment

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

---

## Environment Configuration

Copy:

```text
.env.example
```

to:

```text
.env
```

The configuration supports settings such as:

```text
MAX_STEPS
MAX_TOOL_CALLS
MAX_VERIFICATION_RETRIES
LLM_TIMEOUT_SECONDS
TOOL_TIMEOUT_SECONDS
MAX_RETRIES
LLM_PROVIDER
LLM_MODEL
LLM_BASE_URL
LLM_API_KEY
PROMPT_VERSION
```

Do not commit the real `.env` file or API keys.

---

## Run the Agent Locally

Execute:

```bash
python run_local.py
```

A successful development run should produce:

```text
FINAL STATUS
------------------------------------------------------------
answered
```

The current test scenario should produce:

```text
Category : A
Route    : category_a_central
```

with evidence from both:

```text
Schedule
General Condition
```

The verifier checks that the citations were actually retrieved during the current run and that the category and route are consistent.

---

## Guardrails

### Input Guardrail

Project descriptions are checked for suspicious prompt-injection instructions before entering the reasoning workflow.

Unsafe input is escalated instead of being processed normally.

### Output Guardrail

Before a verified determination is returned, the output is checked for:

- Invalid routing values
- Unsupported authoritative claims
- Statements implying official approval
- Statements implying that no further clearance is required

Safe responses include the disclaimer:

> This is a screening opinion, not an authoritative environmental clearance determination.

---

## Reliability and Resilience

The LLM layer includes:

- Provider-independent client interface
- Configurable timeouts
- Retry with exponential backoff
- Circuit breaker
- Controlled error handling
- Stub provider for local testing

Provider failures are handled without allowing uncontrolled exceptions to become final agent answers.

---

## Testing

Manual development tests are available in the `tests/` directory.

Examples:

```bash
python -m tests.test_circuit_breaker_manual
python -m tests.test_timeout_manual
python -m tests.test_resilient_client_manual
python -m tests.test_safe_llm_manual
python -m tests.test_injection_manual
python -m tests.test_output_filter_manual
python -m tests.test_graph_injection_manual
```

---

## Current Limitations

The current implementation is a development-stage Agent Core.

- The regulatory corpus is currently stub data.
- Stub regulatory text must not be treated as authoritative.
- The final corpus/retrieval component must be integrated with the agent.
- Team-level API, deployment, evaluation, and other integration components are outside the current Person 1 implementation.
- Final regulatory correctness depends on the confirmed corpus and rules supplied during integration.

---

## Next Integration Phase

The Agent Core is designed so that the current stub retrieval layer can later be replaced with the team's confirmed retrieval component while keeping the agent workflow stable.

```text
Person 1 Agent Core
        |
        v
Confirmed Retrieval / Corpus
        |
        v
Team Integration
        |
        v
Evaluation and Deployment
```

---

## Important Notice

This project is developed for academic and experimental purposes.

It must not be used as a substitute for official environmental clearance procedures, regulatory authorities, legal advice, or authoritative government documentation.
