from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class CloudAnswer:
    text: str
    recommend_cloud: bool = False


class CloudModelError(RuntimeError):
    pass


def chat_completions_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if not value.startswith(("https://", "http://")):
        raise CloudModelError("API 地址必须以 https:// 或 http:// 开头。")
    if value.endswith("/chat/completions"):
        return value
    if not value.endswith("/v1"):
        value += "/v1"
    return value + "/chat/completions"


class CloudModelBridge:
    """Minimal OpenAI-compatible chat-completions client."""

    def __init__(self, *, timeout_seconds: float = 35) -> None:
        self.timeout_seconds = timeout_seconds

    def answer(
        self,
        question: str,
        context: str,
        *,
        base_url: str,
        model: str,
        api_key: str,
    ) -> CloudAnswer:
        if not model.strip():
            raise CloudModelError("请先填写云端模型名称。")
        if not api_key.strip():
            raise CloudModelError("请先在“API 设置”中保存 API Key。")
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 KeyPilot 的中文语音助手。直接、可靠、简洁地回答当前问题；"
                    "优先给出适合立即朗读的简短结论，不要输出冗长前言。"
                    "你只负责回答，不声称已经操作电脑。"
                ),
            }
        ]
        if context.strip():
            messages.append(
                {
                    "role": "user",
                    "content": f"最近对话：\n{context}\n\n当前问题：{question}",
                }
            )
        else:
            messages.append({"role": "user", "content": question})
        payload = {
            "model": model.strip(),
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 500,
        }
        request = urllib.request.Request(
            chat_completions_url(base_url),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            messages_by_status = {
                401: "API Key 无效或没有权限。",
                403: "API 请求被服务商拒绝，请检查权限。",
                404: "没有找到 API 地址或模型，请检查配置。",
                429: "API 额度不足或请求过于频繁。",
            }
            raise CloudModelError(
                messages_by_status.get(exc.code, f"云端 API 返回错误 {exc.code}。")
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CloudModelError("无法连接云端 API，请检查网络和接口地址。") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CloudModelError("云端 API 返回了无法识别的数据。") from exc

        choices = result.get("choices") if isinstance(result, dict) else None
        if not isinstance(choices, list) or not choices:
            raise CloudModelError("云端 API 没有返回回答。")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", "")) for item in content if isinstance(item, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise CloudModelError("云端 API 返回了空回答。")
        return CloudAnswer(content.strip())


__all__ = ["CloudAnswer", "CloudModelBridge", "CloudModelError", "chat_completions_url"]
