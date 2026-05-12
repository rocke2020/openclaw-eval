import asyncio
import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI


async def locomo_grader(
    llm_client, model: str, question: str, gold_answer: str, response: str
) -> dict:
    system_prompt = """
        You are an expert grader that determines if answers to questions match a gold standard answer
        """

    ACCURACY_PROMPT = f"""
    Your task is to label an answer to a question as 'CORRECT' or 'WRONG'. You will be given the following data:
        (1) a question (posed by one user to another user),
        (2) a 'gold' (ground truth) answer,
        (3) a generated answer
    which you will score as CORRECT/WRONG.

    The point of the question is to ask about something one user should know about the other user based on their prior conversations.
    The gold answer will usually be a concise and short answer that includes the referenced topic, for example:
    Question: Do you remember what I got the last time I went to Hawaii?
    Gold answer: A shell necklace
    The generated answer might be much longer, but you should be generous with your grading - as long as it touches on the same topic as the gold answer, it should be counted as CORRECT.

    For time related questions, the gold answer will be a specific date, month, year, etc. The generated answer might be much longer or use relative time references (like "last Tuesday" or "next month"), but you should be generous with your grading - as long as it refers to the same date or time period as the gold answer, it should be counted as CORRECT. Even if the format differs (e.g., "May 7th" vs "7 May"), consider it CORRECT if it's the same date.

    Now it's time for the real question:
    Question: {question}
    Gold answer: {gold_answer}
    Generated answer: {response}

    First, provide a short (one sentence) explanation of your reasoning, then finish with CORRECT or WRONG.
    Do NOT include both CORRECT and WRONG in your response, or it will break the evaluation script.

    Respond with JSON only: {{"is_correct": "CORRECT" or "WRONG", "reasoning": "your explanation"}}
    """

    create_kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": ACCURACY_PROMPT},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = await _create_with_retries(llm_client, create_kwargs)
    except Exception:
        create_kwargs.pop("response_format", None)
        resp = await _create_with_retries(llm_client, create_kwargs)

    content = resp.choices[0].message.content
    result = parse_json_object(content)

    label = result.get("is_correct", result.get("label", "WRONG"))
    normalized = str(label).strip().upper()
    return {
        "grade": normalized == "CORRECT",
        "label": normalized,
        "reasoning": result.get("reasoning", ""),
        "judge_model": model,
    }


async def _create_with_retries(llm_client, kwargs: dict) -> Any:
    last_exc = None
    for attempt in range(3):
        try:
            return await llm_client.chat.completions.create(**kwargs)
        except Exception as exc:
            last_exc = exc
            if not _is_transient_error(exc) or attempt == 2:
                raise
            await asyncio.sleep(0.25 * (attempt + 1))
    raise last_exc


def _is_transient_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    return status in {429, 500, 502, 503, 504}


def parse_json_object(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def load_answers(path: str) -> list[dict]:
    """Load answers from a JSON file.

    Expected format: list of dicts with keys: question, expected, response.
    Optional keys: sample_id, qi, category, evidence.
    """
    with open(path, "r", encoding="utf-8") as f:
        if path.endswith(".jsonl"):
            return [json.loads(line) for line in f if line.strip()]
        data = json.load(f)
        if isinstance(data, dict):
            return data.get("results", [])
        return data


async def grade_answers(
    answers: list[dict],
    base_url: str | None = None,
    api_key: str | None = None,
    model: str = "gpt-4o-mini",
    parallel: int = 8,
) -> list[dict]:
    """Grade a list of answer dicts using the LLM grader.

    Each answer dict must have: question, expected, response.
    Returns a new list with a 'grade' field added (bool).
    """
    load_dotenv()
    client = AsyncOpenAI(
        base_url=base_url or os.getenv("OPENAI_BASE_URL"),
        api_key=api_key or os.getenv("OPENAI_API_KEY"),
    )

    semaphore = asyncio.Semaphore(parallel)

    async def grade_one(item: dict) -> dict:
        async with semaphore:
            try:
                payload = await locomo_grader(
                    client,
                    model,
                    item["question"],
                    item["expected"],
                    item["response"],
                )
                return {**item, **payload}
            except Exception as exc:
                return {
                    **item,
                    "grade": False,
                    "label": "ERROR",
                    "reasoning": str(exc),
                    "judge_model": model,
                }

    return await asyncio.gather(*(grade_one(item) for item in answers))
