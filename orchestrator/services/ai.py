"""OpenAI (ChatGPT) client used by the AI assistant."""
import requests

API_URL = 'https://api.openai.com/v1'
# Model ids that can't hold a chat (embeddings, audio, images...)
NON_CHAT_MARKERS = ('embedding', 'whisper', 'tts', 'dall-e', 'moderation', 'audio', 'realtime', 'image',
                    'transcribe', 'search', 'davinci', 'babbage', 'sora', 'computer-use')


class AIError(Exception):
    pass


def get_ai_config():
    from ..permissions import get_global_config
    config = get_global_config()
    if not config or not config.ai_enabled or not config.openai_api_key or not config.openai_model:
        return None
    return config


def _request(method, path, api_key, **kwargs):
    try:
        response = requests.request(
            method, f'{API_URL}{path}', headers={'Authorization': f'Bearer {api_key}'}, timeout=kwargs.pop('timeout', 120), **kwargs,
        )
    except requests.RequestException as e:
        raise AIError(f'No se pudo conectar con OpenAI: {e}')
    if response.status_code >= 400:
        try:
            message = response.json().get('error', {}).get('message') or response.text
        except ValueError:
            message = response.text
        raise AIError(f'OpenAI respondió {response.status_code}: {message[:300]}')
    return response.json()


def list_chat_models(api_key):
    data = _request('GET', '/models', api_key, timeout=20)
    ids = [m['id'] for m in data.get('data', [])]
    return sorted(i for i in ids if not any(marker in i for marker in NON_CHAT_MARKERS))


def chat(config, messages, tools=None):
    """One Chat Completions call. Returns the assistant message dict (content and/or tool_calls)."""
    payload = {'model': config.openai_model, 'messages': messages}
    if tools:
        payload['tools'] = tools
    data = _request('POST', '/chat/completions', config.openai_api_key, json=payload, timeout=180)
    return data['choices'][0]['message']
