"""No provider key, remote hosts, environment proxies, redirects, or cloud fallback."""
from urllib.parse import urlparse
import requests
from django.conf import settings
from rest_framework.exceptions import APIException

class Unavailable(APIException):
    status_code=503
    default_detail='Local AI unavailable. Start Ollama and download the configured model. No cloud fallback was used.'

def endpoint():
    base=settings.OLLAMA_BASE_URL.rstrip('/')
    url=urlparse(base)
    if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost','::1') or url.username or url.password or url.path or url.query or url.fragment:
        raise Unavailable('OLLAMA_BASE_URL must be an HTTP loopback address; remote inference is disabled.')
    # Only explicitly approved local model tags, never arbitrary model names or cloud aliases.
    if settings.OLLAMA_MODEL not in ('qwen3:4b','qwen3:8b','qwen3:14b'):
        raise Unavailable('Use a supported local model: qwen3:4b, qwen3:8b, or qwen3:14b.')
    return base

def status():
    if not settings.AI_ENABLED: return {'ready':False,'detail':'AI is disabled in backend settings.'}
    try:
        with requests.Session() as session:
            session.trust_env=False
            response=session.get(endpoint()+'/api/tags',timeout=(3,5),allow_redirects=False)
            if response.status_code!=200: raise Unavailable()
            models=response.json().get('models',[])
            ready=any(m.get('name')==settings.OLLAMA_MODEL for m in models)
            return {'ready':ready,'model':settings.OLLAMA_MODEL,'provider':'Ollama (local only)',
                'detail':'Local model is installed.' if ready else f'Run: ollama pull {settings.OLLAMA_MODEL}'}
    except (requests.RequestException,ValueError,Unavailable):
        return {'ready':False,'model':settings.OLLAMA_MODEL,'provider':'Ollama (local only)','detail':'Start Ollama locally and pull the configured qwen3 model. Check OLLAMA_BASE_URL if needed.'}

def chat(messages,tools):
    if not settings.AI_ENABLED: raise Unavailable('AI is disabled in backend settings.')
    try:
        with requests.Session() as session:
            session.trust_env=False
            response=session.post(endpoint()+'/api/chat',json={'model':settings.OLLAMA_MODEL,'messages':messages,'tools':tools,
                'stream':False,'think':False,'options':{'temperature':0,'num_ctx':16384,'num_predict':1600}},
                timeout=(5,settings.OLLAMA_TIMEOUT),allow_redirects=False)
            if response.status_code!=200: raise Unavailable()
            message=response.json().get('message')
            if not isinstance(message,dict): raise Unavailable('Local model returned an invalid response.')
            return message
    except (requests.RequestException,ValueError): raise Unavailable()
