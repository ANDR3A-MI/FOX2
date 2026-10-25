"""Provider di generazione e router a cascata.

Ogni provider espone la stessa interfaccia: `ready()` dice se e' utilizzabile
adesso, `stream()` produce la risposta pezzo per pezzo. Il Router li prova
nell'ordine scelto nelle impostazioni e scende al successivo quando uno non
risponde o non ha quel modello, che e' il comportamento descritto nel README.
"""

from __future__ import annotations

from typing import Iterator

import local_llm
from settings import PROVIDER_LABELS, settings

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


class ProviderError(RuntimeError):
    """Errore recuperabile: il router passa al provider successivo."""


class Provider:
    id = ""
    label = ""

    def ready(self) -> bool:
        raise NotImplementedError

    def why_not_ready(self) -> str:
        return "Non configurato."

    def stream(self, messages: list[dict], system: str) -> Iterator[str]:
        raise NotImplementedError


# ------------------------------------------------------------------ locale --

class LocalProvider(Provider):
    id = "local"
    label = PROVIDER_LABELS["local"]

    def ready(self) -> bool:
        return local_llm.available() and (
            settings.local_model_path() is not None or bool(local_llm.installed_models())
        )

    def why_not_ready(self) -> str:
        if not local_llm.available():
            return local_llm.unavailable_reason()
        return "Nessun modello .gguf installato. Scaricane uno dalle impostazioni."

    def stream(self, messages: list[dict], system: str) -> Iterator[str]:
        try:
            yield from local_llm.engine.stream(messages, system)
        except Exception as exc:
            raise ProviderError(str(exc)) from exc


# --------------------------------------------------------------- Anthropic --

class AnthropicProvider(Provider):
    id = "anthropic"
    label = PROVIDER_LABELS["anthropic"]

    def ready(self) -> bool:
        return bool(settings.api_key("anthropic"))

    def why_not_ready(self) -> str:
        return "Manca la chiave API. Incollala in Impostazioni."

    def stream(self, messages: list[dict], system: str) -> Iterator[str]:
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderError("Pacchetto anthropic non installato.") from exc

        client = anthropic.Anthropic(api_key=settings.api_key("anthropic"))
        try:
            with client.messages.stream(
                model=settings.get("model_anthropic"),
                max_tokens=1024,
                system=system or anthropic.NOT_GIVEN,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except Exception as exc:
            raise ProviderError("Anthropic: %s" % exc) from exc


# ----------------------------------------------- OpenAI e compatibili (NIM) --

class _OpenAICompatible(Provider):
    base_url: str | None = None
    model_key = ""

    def ready(self) -> bool:
        return bool(settings.api_key(self.id))

    def why_not_ready(self) -> str:
        return "Manca la chiave API. Incollala in Impostazioni."

    def stream(self, messages: list[dict], system: str) -> Iterator[str]:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError("Pacchetto openai non installato.") from exc

        client = OpenAI(
            api_key=settings.api_key(self.id),
            base_url=self.base_url,
        )
        payload = ([{"role": "system", "content": system}] if system else []) + messages
        try:
            response = client.chat.completions.create(
                model=settings.get(self.model_key),
                messages=payload,
                stream=True,
                max_tokens=1024,
            )
            for chunk in response:
                if not chunk.choices:
                    continue
                text = chunk.choices[0].delta.content
                if text:
                    yield text
        except Exception as exc:
            raise ProviderError("%s: %s" % (self.label, exc)) from exc


class OpenAIProvider(_OpenAICompatible):
    id = "openai"
    label = PROVIDER_LABELS["openai"]
    base_url = None
    model_key = "model_openai"


class NvidiaProvider(_OpenAICompatible):
    id = "nvidia"
    label = PROVIDER_LABELS["nvidia"]
    base_url = NVIDIA_BASE_URL
    model_key = "model_nvidia"

    def why_not_ready(self) -> str:
        return "Manca la chiave. Le chiavi NVIDIA NIM iniziano con nvapi- e si ottengono su build.nvidia.com."


ALL: dict[str, Provider] = {
    p.id: p for p in (LocalProvider(), AnthropicProvider(), OpenAIProvider(), NvidiaProvider())
}


# ------------------------------------------------------------------ router --

class Router:
    """Prova i provider in ordine e usa il primo che risponde."""

    def __init__(self) -> None:
        self.last_provider: Provider | None = None
        self.last_errors: list[str] = []

    def order(self) -> list[Provider]:
        wanted = settings.get("provider_order") or list(ALL)
        chosen = [ALL[key] for key in wanted if key in ALL]
        # eventuali provider nuovi non ancora presenti nelle preferenze salvate
        chosen += [p for key, p in ALL.items() if key not in wanted]
        return chosen

    def stream(self, messages: list[dict], system: str | None = None) -> Iterator[str]:
        system = settings.get("system_prompt") if system is None else system
        self.last_errors = []

        for provider in self.order():
            if not provider.ready():
                self.last_errors.append("%s: %s" % (provider.label, provider.why_not_ready()))
                continue

            produced = False
            try:
                for piece in provider.stream(messages, system):
                    produced = True
                    yield piece
            except ProviderError as exc:
                # Se aveva gia' iniziato a rispondere non si ricomincia altrove:
                # l'utente vedrebbe due risposte diverse incollate.
                if produced:
                    raise
                self.last_errors.append(str(exc))
                continue

            self.last_provider = provider
            return

        raise RuntimeError(
            "Nessun provider disponibile.\n" + "\n".join(self.last_errors)
        )


router = Router()
