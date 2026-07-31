"""Gemini Structured Output provider used only by CHANGE_INPUT final analysis."""

from google import genai
from google.genai import types

from app.core.config import get_gemini_api_key, get_gemini_model


class GeminiChangeInputError(Exception):
    """Gemini transport/envelope failures without exposing prompt or response content."""


async def generate_change_input(*, prompt: str, response_json_schema: dict) -> str:
    try:
        client = genai.Client(api_key=get_gemini_api_key())
        response = await client.aio.models.generate_content(
            model=get_gemini_model(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=response_json_schema,
            ),
        )
    except Exception as exc:
        raise GeminiChangeInputError("Gemini CHANGE_INPUT request failed") from exc
    content = response.text
    if not isinstance(content, str) or not content.strip():
        raise GeminiChangeInputError("Gemini CHANGE_INPUT response is blank")
    return content
