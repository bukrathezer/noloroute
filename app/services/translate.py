"""Machine translation with the Google Cloud Translation API (Basic, v2).

Only scripts/localize_pois.py uses it: a place whose Wikipedia article exists in one language only
gets the other language's description translated from it, once, and the result is stored. Plans
never call it. Google bills by the character (the first 500,000 a month are free), so the client
counts what it sends.
"""

import time
from collections.abc import Sequence
from typing import Any, Self

import httpx

TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"
BATCH = 50  # texts per request; the API takes up to 128
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


class TranslateError(Exception):
    pass


class TranslateClient:
    def __init__(self, api_key: str, timeout: float = 30.0, transport: httpx.BaseTransport | None = None) -> None:
        # The key goes in a header rather than the URL, so it stays out of logs.
        self._http = httpx.Client(timeout=timeout, transport=transport, headers={"X-Goog-Api-Key": api_key})
        self.characters = 0  # sent for translation so far: what Google bills

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def translate(self, texts: Sequence[str], source: str, target: str) -> list[str]:
        """The texts translated from `source` into `target` ("en", "tr"), in the same order."""
        translated: list[str] = []
        for i in range(0, len(texts), BATCH):
            batch = list(texts[i : i + BATCH])
            # "text" format: plain text in and out, no HTML entities like &#39;.
            data = self._post({"q": batch, "source": source, "target": target, "format": "text"})
            results = data.get("data", {}).get("translations", [])
            if len(results) != len(batch):
                raise TranslateError(f"asked for {len(batch)} translations, got {len(results)}")
            self.characters += sum(len(text) for text in batch)
            translated += [result["translatedText"] for result in results]
        return translated

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(MAX_ATTEMPTS):
            try:
                resp = self._http.post(TRANSLATE_URL, json=body)
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:  # never reached Google: retry
                if attempt == MAX_ATTEMPTS - 1:
                    raise TranslateError(str(e)) from e
                time.sleep(2**attempt)
                continue
            except httpx.HTTPError as e:  # e.g. no answer in time: Google may have billed it already
                raise TranslateError(str(e)) from e
            if resp.status_code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS - 1:
                time.sleep(2**attempt)  # 1 s, then 2 s
                continue
            if resp.is_error:
                raise TranslateError(f"Translation API error {resp.status_code}: {_error_message(resp)}")
            return resp.json()
        raise AssertionError("unreachable")


def _error_message(resp: httpx.Response) -> str:
    try:
        return resp.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return resp.text
