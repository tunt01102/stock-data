"""Optional AI assistant: Claude, Gemini or OpenAI via their HTTP APIs.

Keys live only in data/settings.json on this computer and are sent only to the
provider the user picked. Without a key the app works fully without AI.
"""
import os

from . import store
from .net import post_json, FetchError

DEFAULT_MODELS = {
    "claude": "claude-opus-5-5",
    "openai": "gpt-5-mini",
    "gemini": "gemini-2.5-flash",
}
SETTINGS = lambda: store.path("settings.json")

SYSTEM_VI = (
    "Bạn là trợ lý phân tích dữ liệu cho học sinh, sinh viên Việt Nam đang học về thị trường "
    "chứng khoán bất động sản. Chỉ dựa vào số liệu được cung cấp; nếu thiếu số liệu thì nói rõ "
    "là thiếu, không tự bịa. Giải thích công thức bằng lời dễ hiểu. Đây là mục đích học tập, "
    "không đưa ra khuyến nghị mua/bán. Trả lời bằng {lang}.")


def load_settings():
    s = store.read_json(SETTINGS(), {}) or {}
    s.setdefault("lang", "vi")
    s.setdefault("provider", "")
    s.setdefault("keys", {})
    s.setdefault("models", {})
    return s


def save_settings(new):
    s = load_settings()
    for k in ("lang", "provider"):
        if k in new:
            s[k] = new[k]
    for prov, key in (new.get("keys") or {}).items():
        if prov in DEFAULT_MODELS:
            if key is None or key == "":
                s["keys"].pop(prov, None)
            elif "•" not in key:  # masked value sent back unchanged -> ignore
                s["keys"][prov] = key.strip()
    for prov, m in (new.get("models") or {}).items():
        if prov in DEFAULT_MODELS:
            s["models"][prov] = (m or "").strip() or DEFAULT_MODELS[prov]
    store.write_json(SETTINGS(), s)
    try:
        os.chmod(SETTINGS(), 0o600)
    except OSError:
        pass
    return public_settings()


def public_settings():
    """Settings safe to show in the browser: keys masked to the last 4 chars."""
    s = load_settings()
    return {
        "lang": s["lang"], "provider": s["provider"],
        "keys": {p: ("••••" + k[-4:]) for p, k in s["keys"].items() if k},
        "models": {p: s["models"].get(p) or m for p, m in DEFAULT_MODELS.items()},
        "configured": [p for p, k in s["keys"].items() if k],
    }


def ask(question, context, provider=None, lang="vi"):
    s = load_settings()
    provider = provider or s.get("provider") or next(iter(s["keys"]), None)
    key = s["keys"].get(provider or "")
    if not key:
        raise FetchError("Chưa cấu hình API key cho %s (vào tab Cài đặt)." % (provider or "AI"))
    model = s["models"].get(provider) or DEFAULT_MODELS[provider]
    system = SYSTEM_VI.format(lang="tiếng Việt" if lang == "vi" else "English")
    user = "DỮ LIỆU (JSON):\n%s\n\nCÂU HỎI:\n%s" % (context, question)
    if provider == "claude":
        js = post_json("https://api.anthropic.com/v1/messages", {
            "model": model, "max_tokens": 16000, "system": system,
            "messages": [{"role": "user", "content": user}],
        }, headers={"x-api-key": key, "anthropic-version": "2026-10-21"}, timeout=300)
        if js.get("stop_reason") == "refusal":
            return "(Claude từ chối trả lời câu hỏi này.)", model
        return "".join(b.get("text", "") for b in js.get("content", []) if b.get("type") == "text"), model
    if provider == "openai":
        js = post_json("https://api.openai.com/v1/chat/completions", {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }, headers={"Authorization": "Bearer " + key}, timeout=300)
        return js["choices"][0]["message"]["content"], model
    if provider == "gemini":
        url = ("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model)
        js = post_json(url, {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
        }, headers={"x-goog-api-key": key}, timeout=300)
        parts = js["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts), model
    raise FetchError("Nhà cung cấp không hợp lệ: %s" % provider)
