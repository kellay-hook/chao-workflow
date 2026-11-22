from __future__ import annotations

from app.api.resources import _normalize_base_url
from app.schemas import ModelProfileOut


def test_deepseek_base_url_normalization():
    assert _normalize_base_url('openai_compatible', 'https://api.deepseek.com/anthropic') == 'https://api.deepseek.com/v1'
    assert _normalize_base_url('openai_compatible', 'https://api.deepseek.com') == 'https://api.deepseek.com/v1'
    assert _normalize_base_url('openai_compatible', 'https://api.deepseek.com/v1/') == 'https://api.deepseek.com/v1'
    assert _normalize_base_url('ollama', 'http://localhost:11434/v1') == 'http://localhost:11434/v1'


def test_model_profile_output_hides_key_but_reports_presence():
    profile = ModelProfileOut(
        id='m1',
        tenant_id='t1',
        name='DeepSeek',
        provider='openai_compatible',
        base_url='https://api.deepseek.com/v1',
        model='deepseek-chat',
        api_key_secret='model_m1',
        embedding_dimension=1024,
        max_tokens=2048,
        temperature=0.2,
        timeout_sec=60,
        is_default=True,
    )
    payload = profile.model_dump()
    assert payload['has_api_key'] is True
    assert 'api_key_secret' not in payload
