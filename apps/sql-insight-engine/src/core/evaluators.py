from concurrent.futures import ThreadPoolExecutor
from core.gemini_client import GeminiClient
from core.langfuse_client import get_langfuse

_eval_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="langfuse-eval")

JUDGE_MODEL = "gemini-2.0-flash"


def _call_judge(prompt: str) -> tuple[float, str]:
    """Call Gemini and parse SCORE / REASON tags. Returns (score, reason)."""
    agent = GeminiClient(model_name=JUDGE_MODEL)
    response = agent.generate_content(prompt)
    if not response:
        return 0.5, "Evaluation unavailable"
    try:
        text = response.text or ""
    except (ValueError, AttributeError):
        text = str(response)

    score, reason = 0.5, text.strip()
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("SCORE:"):
            try:
                score = float(line.split(":", 1)[1].strip())
                score = max(0.0, min(1.0, score))
            except ValueError:
                pass
        elif line.upper().startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()
    return score, reason


def _score_answer_relevance(question: str, response: str) -> tuple[float, str]:
    prompt = f"""You are an evaluation judge. Score how well the response answers the user's question.

QUESTION: {question}

RESPONSE: {response}

SCORING GUIDE:
- 1.0: Response fully and directly answers the question with specific, relevant data.
- 0.5: Response partially answers or is vague about the key findings.
- 0.0: Response does not answer the question at all.

Reply ONLY with:
SCORE: [a number between 0.0 and 1.0]
REASON: [one concise sentence]"""
    return _call_judge(prompt)


def _score_response_quality(question: str, response: str) -> tuple[float, str]:
    prompt = f"""You are an evaluation judge. Score the quality of this executive summary for a non-technical business user.

QUESTION: {question}

RESPONSE: {response}

SCORING GUIDE:
- 1.0: Professional, concise, insight-driven, avoids technical jargon, starts with the key finding.
- 0.5: Acceptable but could be clearer, more concise, or more business-focused.
- 0.0: Unprofessional, confusing, overly technical, or contains raw SQL/column names.

Reply ONLY with:
SCORE: [a number between 0.0 and 1.0]
REASON: [one concise sentence]"""
    return _call_judge(prompt)


def _score_sql_correctness(question: str, sql: str) -> tuple[float, str]:
    prompt = f"""You are an evaluation judge. Score whether the SQL query is logically correct for the user's question.

QUESTION: {question}

SQL: {sql}

SCORING GUIDE:
- 1.0: SQL is well-formed, uses appropriate tables and conditions, and would return the right data.
- 0.5: SQL is plausible but has minor issues (e.g. suboptimal joins, missing filters).
- 0.0: SQL is logically wrong, uses incorrect tables/columns, or would not answer the question.

Reply ONLY with:
SCORE: [a number between 0.0 and 1.0]
REASON: [one concise sentence]"""
    return _call_judge(prompt)


def _run_all_evaluations(saga_id: str, question: str, sql: str, formatted_response: str):
    lf = get_langfuse()
    if not lf:
        return

    trace = lf.trace(id=saga_id)
    evaluators = [
        ("answer_relevance", _score_answer_relevance, (question, formatted_response)),
        ("response_quality", _score_response_quality, (question, formatted_response)),
        ("sql_correctness",  _score_sql_correctness,  (question, sql)),
    ]

    for name, fn, args in evaluators:
        try:
            score, comment = fn(*args)
            trace.score(name=name, value=score, comment=comment)
            print(f"[EVAL] {name}={score:.2f} — {comment}")
        except Exception as e:
            print(f"[EVAL] {name} failed: {e}")

    lf.flush()


def run_evaluations_async(saga_id: str, question: str, sql: str, formatted_response: str):
    """Fire-and-forget: submit LLM evaluations to a background thread."""
    _eval_executor.submit(_run_all_evaluations, saga_id, question, sql, formatted_response)
