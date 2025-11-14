import httpx
from agent_core.domain.models import ChatRequest, ChatResult, ChatMessage, ChatChoice, ChatUsage
from agent_core.domain.exceptions import NetworkError, ApiError, RateLimitError, ValidationError
from agent_core.providers.registry import KIMI_CONFIG, ModelConfig


class KimiClient:
    name = "kimi"

    def __init__(self, settings):
        self._settings = settings

    def chat(self, req: ChatRequest) -> ChatResult:
        if not getattr(self._settings, "kimi_api_key", None):
            raise ValidationError(code="MISSING_API_KEY", message="KIMI_API_KEY not set")
        model_cfg = KIMI_CONFIG.models[req.model]
        payload = self._build_payload(req, model_cfg)
        try:
            with httpx.Client(timeout=self._settings.http_timeout, trust_env=False) as client:
                base = getattr(self._settings, "kimi_base_url", None) or KIMI_CONFIG.base_url
                resp = client.post(
                    f"{base}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._settings.kimi_api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.RequestError as e:
            raise NetworkError(code="NETWORK_ERROR", message=str(e))
        if resp.status_code == 429:
            raise RateLimitError(code="RATE_LIMIT", message="Kimi rate limit")
        if resp.status_code >= 400:
            raise ApiError(code="API_ERROR", message=resp.text, http_status=resp.status_code)
        data = resp.json()
        return self._parse_response(data, req)

    def _build_payload(self, req: ChatRequest, model_cfg: ModelConfig) -> dict:
        msgs = [{"role": m.role, "content": m.content} for m in req.messages]
        payload = {
            "model": model_cfg.provider_model,
            "messages": msgs,
            "temperature": req.temperature or model_cfg.default_temperature,
            "max_tokens": req.max_tokens or model_cfg.max_tokens,
            "top_p": req.top_p,
        }
        return payload

    def _parse_response(self, data: dict, req: ChatRequest) -> ChatResult:
        choices: list[ChatChoice] = []
        for i, ch in enumerate(data.get("choices", [])):
            msg = ch.get("message") or {}
            cm = ChatMessage(role=msg.get("role") or "assistant", content=msg.get("content") or "")
            choices.append(ChatChoice(index=i, message=cm, finish_reason=ch.get("finish_reason")))
        usage_raw = data.get("usage") or {}
        usage = ChatUsage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )
        return ChatResult(provider="kimi", model=req.model, choices=choices, usage=usage, raw=data)