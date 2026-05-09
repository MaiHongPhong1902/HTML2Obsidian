"""
summarizer.py — Summarise page content using a small LLM before passing to a large LLM.

Supports:
- Ollama (local, default — small models: llama3.2:3b, phi3:mini, gemma2:2b)
- OpenAI-compatible API (gpt-4o-mini, Groq, etc.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class SummaryResult:
    summary: str
    model: str
    provider: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error: Optional[str] = None


SUMMARY_PROMPT = """You are an information extraction assistant. Summarise the following web page content into concise Markdown.

Requirements:
- Keep only the most important information
- Use bullet points and clear headings
- No extra explanation, no greetings
- Maximum {max_words} words

Page content:
---
{content}
---

Summary:"""


class PageSummarizer:
    """
    Summarise web page content using a small LLM.

    Example:
        summarizer = PageSummarizer(provider="ollama", model="llama3.2:3b")
        result = summarizer.summarize(clean_markdown)
    """

    def __init__(
        self,
        provider: str = "ollama",          # "ollama" | "openai"
        model: str = "llama3.2:3b",        # model name
        base_url: str = "http://localhost:11434",  # Ollama default
        api_key: str = "",
        max_words: int = 300,
        temperature: float = 0.1,
    ):
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_words = max_words
        self.temperature = temperature

    def summarize(self, content: str, custom_prompt: Optional[str] = None) -> SummaryResult:
        """Summarise content. Returns SummaryResult."""
        if not content.strip():
            return SummaryResult(
                summary="",
                model=self.model,
                provider=self.provider,
                error="Input content is empty",
            )

        prompt = custom_prompt or SUMMARY_PROMPT.format(
            content=content[:8000],  # limit input to save tokens
            max_words=self.max_words,
        )

        if self.provider == "ollama":
            return self._call_ollama(prompt)
        elif self.provider == "openai":
            return self._call_openai(prompt)
        else:
            return SummaryResult(
                summary="",
                model=self.model,
                provider=self.provider,
                error=f"Unsupported provider: {self.provider}",
            )

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------

    def _call_ollama(self, prompt: str) -> SummaryResult:
        try:
            import httpx

            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": self.temperature},
            }
            resp = httpx.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()

            return SummaryResult(
                summary=data.get("response", "").strip(),
                model=self.model,
                provider="ollama",
                input_tokens=data.get("prompt_eval_count"),
                output_tokens=data.get("eval_count"),
            )
        except Exception as exc:
            return SummaryResult(
                summary="",
                model=self.model,
                provider="ollama",
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # OpenAI-compatible
    # ------------------------------------------------------------------

    def _call_openai(self, prompt: str) -> SummaryResult:
        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": self.temperature,
            }
            base = self.base_url if self.base_url != "http://localhost:11434" else "https://api.openai.com/v1"
            resp = httpx.post(
                f"{base}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()

            choice = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})

            return SummaryResult(
                summary=choice,
                model=self.model,
                provider="openai",
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            )
        except Exception as exc:
            return SummaryResult(
                summary="",
                model=self.model,
                provider="openai",
                error=str(exc),
            )
