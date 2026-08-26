# bot/core/llm/openai_client.py
from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Awaitable

from loguru import logger
import os

from openai import (AsyncOpenAI, APIConnectionError, APIStatusError,
                    APITimeoutError, RateLimitError)

from bot.core.llm.base import BaseLLMClient, FALLBACK_RESPONSE, FALLBACK_IMAGE_RESPONSE

if TYPE_CHECKING:
    from bot.config import ImageGenerationConfig
    from bot.db.database import Database

_RESPONSES_API_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _uses_responses_api(model: str) -> bool:
    return any(model.startswith(p) for p in _RESPONSES_API_PREFIXES)


# Coût par 1M de tokens en USD : (input, cached input, output).
# Source : https://developers.openai.com/api/docs/pricing (relevé le 2026-08-25).
#
# La table ne portait auparavant que deux valeurs, et les ONZE lignes étaient
# fausses — arrondies à la louche sur une génération de tarifs antérieure. Le
# `cost_log` mentait donc sur chaque appel OpenAI : `gpt-5.4-mini` sous-estimé
# d'un facteur 7,5 en sortie, `gpt-5-pro` d'un facteur 3, `gpt-5` d'un facteur
# 1,25. C'est `gpt-5-nano` qui sert la VisionService en production, et son coût
# d'entrée était surestimé du double.
#
# Le prix caché est désormais une colonne à part plutôt qu'une remise devinée :
# OpenAI facture le cache à 10 % de l'entrée, pas à 50 % comme le calculait
# `estimate_cost`. Un chiffrage de cache était donc cinq fois trop cher.
#
# `gpt-5-pro` et `gpt-5.4-pro` n'ont AUCUN tarif caché publié : on y répète le
# prix plein plutôt que d'inventer une remise, pour ne jamais sous-estimer.
#
# ⚠️ Les `gpt-5.6-*` doublent leurs tarifs au-delà de 272 000 tokens d'entrée
# (0,40/1,80 pour luna). Ce n'est pas modélisé ici : les appels de Wally font
# 2 805 tokens en moyenne, deux ordres de grandeur sous le seuil. Le jour où un
# prompt s'en approche, cette table devient fausse à la baisse.
MODEL_COSTS: dict[str, tuple[float, float, float]] = {
    "gpt-5": (1.25, 0.125, 10.0),
    "gpt-5-mini": (0.25, 0.025, 2.0),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5-pro": (15.0, 15.0, 120.0),
    "gpt-5.1": (1.25, 0.125, 10.0),
    "gpt-5.2": (1.75, 0.175, 14.0),
    "gpt-5.3": (1.75, 0.175, 14.0),
    "gpt-5.4": (2.50, 0.25, 15.0),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "gpt-5.4-pro": (30.0, 30.0, 180.0),
    "gpt-5.5": (5.0, 0.50, 30.0),
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
    "gpt-5.6-terra": (2.0, 0.20, 12.0),
    "gpt-5.6-sol": (4.0, 0.40, 20.0),
}

# Repli d'un modèle inconnu : cher exprès, pour qu'une facture surprise se voie
# dans le log plutôt que de s'y fondre.
FALLBACK_COST = (5.0, 0.50, 15.0)

IMAGE_COSTS: dict[str, dict[tuple[str, str], float]] = {
    "gpt-image-1.5": {
        ("low", "1024x1024"): 0.009, ("low", "1024x1536"): 0.013, ("low", "1536x1024"): 0.013,
        ("medium", "1024x1024"): 0.034, ("medium", "1024x1536"): 0.05, ("medium", "1536x1024"): 0.05,
        ("high", "1024x1024"): 0.133, ("high", "1024x1536"): 0.20, ("high", "1536x1024"): 0.20,
    },
    "gpt-image-1": {
        ("low", "1024x1024"): 0.011, ("low", "1024x1536"): 0.016, ("low", "1536x1024"): 0.016,
        ("medium", "1024x1024"): 0.042, ("medium", "1024x1536"): 0.063, ("medium", "1536x1024"): 0.063,
        ("high", "1024x1024"): 0.167, ("high", "1024x1536"): 0.25, ("high", "1536x1024"): 0.25,
    },
    "gpt-image-1-mini": {
        ("low", "1024x1024"): 0.005, ("low", "1024x1536"): 0.0075, ("low", "1536x1024"): 0.0075,
        ("medium", "1024x1024"): 0.019, ("medium", "1024x1536"): 0.0285, ("medium", "1536x1024"): 0.0285,
        ("high", "1024x1024"): 0.076, ("high", "1024x1536"): 0.114, ("high", "1536x1024"): 0.114,
    },
}

DATA_GALLERY_DIR = Path("data/gallery")


def _tools_for_responses_api(tools: list[dict]) -> list[dict]:
    """Convert Chat Completions tool format to Responses API format."""
    converted = []
    for tool in tools:
        if "function" in tool:
            fn = tool["function"]
            converted.append({
                "type": "function",
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            })
        else:
            converted.append(tool)
    return converted


def compter_jetons(usage: object) -> tuple[int, int, int]:
    """(entrée, sortie, cachés) depuis un `usage` de l'UNE ou l'AUTRE API.

    Deux formes cohabitent et le même code les traverse : Responses rend
    `input_tokens`/`output_tokens`, Chat Completions rend
    `prompt_tokens`/`completion_tokens`. Les lire à la main aux dix endroits où
    l'on compte finissait par diverger.

    Surtout : le SDK type `response.usage` comme `CompletionUsage | None`, et le
    code le lisait sans garde. Un `usage` absent — que le type prévoit — levait
    un `AttributeError` en plein milieu d'une réponse DÉJÀ générée et payée.
    Ici, l'absence coûte un comptage à zéro : la facture devient imprécise, la
    réponse arrive quand même. C'est le bon sens de l'échange.

    `cached_tokens` est facultatif et varie d'un modèle à l'autre : son absence
    ne rend pas le comptage faux, seulement moins précis.
    """
    if usage is None:
        return 0, 0, 0
    entree = getattr(usage, "input_tokens", None)
    if entree is None:
        entree = getattr(usage, "prompt_tokens", 0)
    sortie = getattr(usage, "output_tokens", None)
    if sortie is None:
        sortie = getattr(usage, "completion_tokens", 0)
    details = (getattr(usage, "input_tokens_details", None)
               or getattr(usage, "prompt_tokens_details", None))
    caches = getattr(details, "cached_tokens", 0)
    return int(entree or 0), int(sortie or 0), int(caches or 0)


def estimate_cost(
    model: str, input_tokens: int, output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    costs = MODEL_COSTS.get(model) or next(
        (v for k, v in sorted(MODEL_COSTS.items(), key=lambda x: len(x[0]), reverse=True)
         if model.startswith(k)),
        FALLBACK_COST,
    )
    prix_entree, prix_cache, prix_sortie = costs
    non_cached = input_tokens - cached_input_tokens
    return (
        non_cached * prix_entree
        + cached_input_tokens * prix_cache
        + output_tokens * prix_sortie
    ) / 1_000_000


class OpenAILLMClient(BaseLLMClient):
    """OpenAI LLM client supporting both Chat Completions and Responses API."""

    # Plafond de tours d'outils en streaming (cf. `complete_stream`).
    STREAM_MAX_TOOL_ITERS = 6

    def __init__(
        self,
        model: str,
        db: "Database",
        temperature: float = 0.8,
        max_tokens: int = 1000,
        reasoning_effort: str = "medium",
        text_verbosity: str = "medium",
    ):
        self._model = model
        self._db = db
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self._text_verbosity = text_verbosity
        api_key = os.environ.get("OPENAI_API_KEY", "dummy-key-for-testing")
        self._client = AsyncOpenAI(api_key=api_key)

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        self._model = value

    @property
    def temperature(self) -> float:
        return self._temperature

    @temperature.setter
    def temperature(self, value: float) -> None:
        self._temperature = value

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @max_tokens.setter
    def max_tokens(self, value: int) -> None:
        self._max_tokens = value

    @property
    def reasoning_effort(self) -> str:
        return self._reasoning_effort

    @reasoning_effort.setter
    def reasoning_effort(self, value: str) -> None:
        self._reasoning_effort = value

    @property
    def text_verbosity(self) -> str:
        return self._text_verbosity

    @text_verbosity.setter
    def text_verbosity(self, value: str) -> None:
        self._text_verbosity = value

    async def list_models(self) -> list[str]:
        """Le catalogue OpenAI, UNI aux modèles que ce fichier sait chiffrer.

        `/v1/models` n'est PAS exhaustif : `gpt-5.6-luna` répond parfaitement aux
        appels sans figurer dans le catalogue rendu par la clé. S'en tenir à
        l'API rendrait donc invisible, dans le menu « Modèle principal », le
        modèle même qu'on cherche à choisir — et un modèle qu'on ne peut pas
        désigner depuis l'UI se pose à la main dans `config.yaml`, hors de tout
        garde-fou.

        L'union avec `MODEL_COSTS` est le bon complément parce que cette table
        dit exactement une chose : « le projet sait facturer ce modèle ». Un
        modèle qu'on ne sait pas chiffrer n'a rien à faire dans le menu, et un
        modèle chiffrable est par construction un modèle qu'on assume.

        Liste vide si l'API ne répond pas — jamais d'exception, l'appelant
        affiche « aucun modèle compatible ».
        """
        connus = set(MODEL_COSTS)
        try:
            catalogue = await self._client.models.list()
            return sorted(connus | {m.id for m in catalogue.data})
        except Exception as e:
            logger.warning("OpenAI list_models() a échoué : {e!r}", e=e)
            return []

    async def _log_cost(
        self, *, input_tokens: int, output_tokens: int, cost: float,
        purpose: str, user_id: str | None,
    ) -> None:
        """Écrit le coût en base. Jamais bloquant.

        Les deux chemins de `complete()` calculaient le coût et le passaient à
        `logger.info` SANS jamais appeler `log_cost` — seules les variantes
        outillées le faisaient. Or le seul chemin OpenAI texte réellement vivant
        aujourd'hui est la VisionService : AUCUNE description d'image n'était
        comptabilisée, et `get_daily_cost` / le seuil d'alerte sous-estimaient
        d'autant la dépense réelle.
        """
        try:
            await self._db.log_cost(
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                purpose=purpose,
                user_id=user_id,
            )
        except Exception as e:  # noqa: BLE001 — une compta ratée n'est pas fatale
            logger.debug("OpenAI log_cost failed (non-fatal): {e!r}", e=e)

    def _params_raisonnement(
        self, max_tokens: int | None = None, *, avec_plafond: bool = True
    ) -> dict:
        """Les kwargs `reasoning` / `max_output_tokens` de la Responses API.

        Cette logique vivait RECOPIÉE en trois endroits (`_complete_responses_api`,
        `_complete_with_tools_responses`, `complete_structured`), avec la même
        erreur aux trois : `effort == "none"` faisait OMETTRE le paramètre.

        Or `none` est une valeur que l'API accepte, et qui rend zéro token de
        raisonnement. L'omettre ne désactive rien — cela laisse le modèle
        appliquer SON défaut, qui raisonne. Un `reasoning_effort: none` en config
        produisait donc exactement l'inverse de ce qu'il demande : mesuré au banc
        sur `gpt-5.6-luna`, 2 234 tokens de sortie contre 1 051 en `low`, pour des
        réponses de même longueur.

        `max_output_tokens` reste omis quand le raisonnement est ACTIF : la
        Responses API partage ce budget entre réflexion et texte, et un petit
        modèle l'épuise avant d'écrire un mot — c'est ce qui rend des réponses
        vides. Sans raisonnement, aucune famine possible : le plafond revient, et
        c'est lui qui borne la dépense.

        `avec_plafond=False` pour la sortie STRUCTURÉE, qui n'en pose jamais :
        un JSON coupé au plafond serait un schéma invalide, et l'appelant
        préfère lire `status != "completed"` et relancer.
        """
        params: dict = {}
        effort = self._reasoning_effort
        if effort:
            params["reasoning"] = {"effort": effort}
        raisonne = bool(effort) and effort != "none"
        effective_max = max_tokens or self._max_tokens
        if avec_plafond and effective_max and not raisonne:
            params["max_output_tokens"] = effective_max
        return params

    def _build_image_content(
        self, text: str, image_urls: list[str], use_responses_api: bool
    ) -> list[dict]:
        if use_responses_api:
            content = [{"type": "input_text", "text": text}]
            for url in image_urls:
                content.append({"type": "input_image", "image_url": url})
        else:
            content = [{"type": "text", "text": text}]
            for url in image_urls:
                content.append({"type": "image_url", "image_url": {"url": url}})
        return content

    async def _complete_responses_api(
        self, messages: list[dict], purpose: str,
        user_id: str | None = None, max_tokens: int | None = None,
    ) -> str:
        kwargs: dict = {
            "model": self._model,
            "input": messages,
        }
        if self._text_verbosity:
            kwargs["text"] = {"format": {"type": "text"}, "verbosity": self._text_verbosity}
        kwargs.update(self._params_raisonnement(max_tokens))
        response = await self._client.responses.create(**kwargs)
        text = response.output_text
        if response.usage:
            entree, sortie, cached = compter_jetons(response.usage)
            cost = estimate_cost(
                self._model, entree, sortie,
                cached_input_tokens=cached,
            )
            logger.info(
                "OpenAI {model} (Responses) — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
                model=self._model, inp=entree,
                out=sortie, cost=cost, purpose=purpose,
            )
            await self._log_cost(
                input_tokens=entree,
                output_tokens=sortie,
                cost=cost, purpose=purpose, user_id=user_id,
            )
        # Contrat de `BaseLLMClient.complete` : le texte, ou FALLBACK_RESPONSE.
        # Le chemin Chat Completions avait été corrigé, celui-ci non — alors que
        # c'est le SEUL emprunté par la config actuelle (`vision_model:
        # gpt-5-nano` déclenche `_uses_responses_api`). Avec `reasoning` actif,
        # `max_output_tokens` est volontairement omis et `output_text` peut
        # valoir "" : `VisionService` loggait alors « le modèle n'a rien rendu »
        # sans distinguer un échec API d'une réponse vide.
        propre = (text or "").strip()
        if not propre:
            logger.warning(
                "OpenAI {m} (Responses) : réponse vide pour {p}",
                m=self._model, p=purpose,
            )
            return FALLBACK_RESPONSE
        return propre

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        effective_max_tokens = max_tokens or self._max_tokens
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        if image_urls:
            last_msg = dict(full_messages[-1])
            last_msg["content"] = self._build_image_content(
                last_msg["content"], image_urls, _uses_responses_api(self._model)
            )
            full_messages[-1] = last_msg

        if _uses_responses_api(self._model):
            fallback = FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE
            for attempt in range(3):
                try:
                    return await self._complete_responses_api(
                        full_messages, purpose, user_id=user_id, max_tokens=effective_max_tokens,
                    )
                except RateLimitError:
                    wait = 2 ** attempt
                    logger.warning(
                        "Rate limited by OpenAI (Responses API), retrying in {w}s (attempt {a}/3)",
                        w=wait, a=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                except APIStatusError as exc:
                    if exc.status_code >= 500:
                        wait = 2 ** attempt
                        logger.warning(
                            "OpenAI Responses API server error {code}, retrying in {w}s",
                            code=exc.status_code, w=wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error("OpenAI Responses API error {code}: {e!r}", code=exc.status_code, e=exc)
                        return fallback
                # `APIConnectionError` / `APITimeoutError` ne dérivent PAS de
                # `APIStatusError` : ils tombaient dans le `except Exception`
                # ci-dessous, qui sort sans rejouer. Autrement dit, aucune reprise
                # sur la panne la PLUS fréquente, là où un 503 en a trois.
                except (APIConnectionError, APITimeoutError) as exc:
                    wait = 2 ** attempt
                    logger.warning("OpenAI réseau ({e!r}) — reprise dans {w}s", e=exc, w=wait)
                    await asyncio.sleep(wait)
                except Exception as exc:
                    logger.error("OpenAI Responses API error: {e!r}", e=exc)
                    return fallback
            logger.error("OpenAI Responses API failed after 3 retries")
            return fallback

        for attempt in range(3):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=full_messages,
                    temperature=self._temperature,
                    max_completion_tokens=effective_max_tokens,
                )
                entree, sortie, cached = compter_jetons(response.usage)
                cost = estimate_cost(
                    self._model, entree, sortie,
                    cached_input_tokens=cached,
                )
                logger.info(
                    "OpenAI {model} — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
                    model=self._model, inp=entree,
                    out=sortie, cost=cost, purpose=purpose,
                )
                await self._log_cost(
                    input_tokens=entree,
                    output_tokens=sortie,
                    cost=cost, purpose=purpose, user_id=user_id,
                )
                # `content` est None dès que le message porte un refus, un
                # filtrage de contenu ou des `tool_calls` : l'AttributeError
                # était avalée par le `except Exception` générique, qui loguait
                # « OpenAI unexpected error » — on cherchait une panne réseau
                # alors que l'API avait répondu 200. La variante outillée se
                # protégeait déjà de la même façon.
                return (response.choices[0].message.content or "").strip() or FALLBACK_RESPONSE

            except RateLimitError:
                wait = 2 ** attempt
                logger.warning(
                    "Rate limited by OpenAI, retrying in {w}s (attempt {a}/3)",
                    w=wait, a=attempt + 1,
                )
                await asyncio.sleep(wait)
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning(
                        "OpenAI server error {code}, retrying in {w}s",
                        code=exc.status_code, w=wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("OpenAI API error {code}: {e!r}", code=exc.status_code, e=exc)
                    break
            # `APIConnectionError` / `APITimeoutError` ne dérivent PAS de
            # `APIStatusError` : ils tombaient dans le `except Exception`
            # ci-dessous, qui sort sans rejouer. Autrement dit, aucune reprise
            # sur la panne la PLUS fréquente, là où un 503 en a trois.
            except (APIConnectionError, APITimeoutError) as exc:
                wait = 2 ** attempt
                logger.warning("OpenAI réseau ({e!r}) — reprise dans {w}s", e=exc, w=wait)
                await asyncio.sleep(wait)
            except Exception as exc:
                logger.error("OpenAI unexpected error: {e!r}", e=exc)
                break

        return FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE

    async def complete_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        tools: list[dict] | None = None,
        tool_executor=None,
    ):
        """Stream completion as text chunks, with optional tool call support.

        Responses API models yield the full response as a single chunk via complete().
        When tools are provided and the model requests tool calls, executes them
        and continues streaming the final response.
        """
        if _uses_responses_api(self._model):
            result = await self.complete(
                system_prompt, messages, purpose=purpose,
                image_urls=image_urls, user_id=user_id,
            )
            yield result
            return

        current_messages = [{"role": "system", "content": system_prompt}] + list(messages)

        if image_urls:
            last_msg = dict(current_messages[-1])
            last_msg["content"] = self._build_image_content(
                last_msg["content"], image_urls, False
            )
            current_messages[-1] = last_msg

        try:
            # Plafond d'itérations, comme `_complete_with_tools_chat` (3) et
            # `DeepSeekLLMClient` (`max_tool_iters=6`). Un `while True:` nu :
            # un modèle qui redemande un outil en boucle bloquait la coroutine
            # indéfiniment en consommant du quota. Non atteignable aujourd'hui —
            # `complete_stream` n'a pas d'appelant hors tests — mais le piège
            # était armé pour le premier qui câblerait le streaming.
            for _iteration in range(self.STREAM_MAX_TOOL_ITERS):
                create_kwargs: dict = dict(
                    model=self._model,
                    messages=current_messages,
                    temperature=self._temperature,
                    max_completion_tokens=self._max_tokens,
                    stream=True,
                )
                if tools:
                    create_kwargs["tools"] = tools

                stream = await self._client.chat.completions.create(**create_kwargs)

                text_parts: list[str] = []
                tool_calls_acc: dict[int, dict] = {}
                finish_reason: str | None = None

                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    finish_reason = choice.finish_reason or finish_reason
                    delta = choice.delta

                    if delta.content:
                        text_parts.append(delta.content)
                        yield delta.content

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                            if tc.id:
                                tool_calls_acc[idx]["id"] += tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_acc[idx]["name"] += tc.function.name
                                if tc.function.arguments:
                                    tool_calls_acc[idx]["arguments"] += tc.function.arguments

                if finish_reason == "tool_calls" and tool_calls_acc and tool_executor:
                    sorted_tcs = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
                    current_messages.append({
                        "role": "assistant",
                        "content": "".join(text_parts) or None,
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {"name": tc["name"], "arguments": tc["arguments"]},
                            }
                            for tc in sorted_tcs
                        ],
                    })
                    # Tool calls indépendants d'un même tour → exécution en parallèle.
                    results = await asyncio.gather(
                        *(tool_executor(tc["name"], tc["arguments"]) for tc in sorted_tcs)
                    )
                    for tc, result in zip(sorted_tcs, results):
                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        })
                    # Continue loop: next iteration streams the final response after tool calls
                else:
                    break
            else:
                # Plafond atteint et le modèle redemandait encore un outil.
                logger.warning(
                    "OpenAI streaming: plafond de {n} tours d'outils atteint",
                    n=self.STREAM_MAX_TOOL_ITERS,
                )

        except Exception as exc:
            logger.error("OpenAI streaming error: {e!r}", e=exc)
            yield FALLBACK_RESPONSE

    async def complete_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, str], Awaitable[str]],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
    ) -> tuple[str, list[str]]:
        use_responses = _uses_responses_api(self._model)
        tools_called: list[str] = []

        if use_responses:
            return await self._complete_with_tools_responses(
                system_prompt, messages, tools, tool_executor,
                purpose, image_urls, user_id, tools_called,
            )
        else:
            return await self._complete_with_tools_chat(
                system_prompt, messages, tools, tool_executor,
                purpose, image_urls, user_id, tools_called,
            )

    async def _complete_with_tools_responses(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, str], Awaitable[str]],
        purpose: str,
        image_urls: list[str] | None,
        user_id: str | None,
        tools_called: list[str],
    ) -> tuple[str, list[str]]:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        if image_urls:
            last_msg = dict(full_messages[-1])
            last_msg["content"] = self._build_image_content(
                last_msg["content"], image_urls, True
            )
            full_messages[-1] = last_msg

        try:
            resp_tools = _tools_for_responses_api(tools)
            resp_kwargs: dict = {
                "model": self._model,
                "input": full_messages,
                "tools": resp_tools,
            }
            resp_kwargs.update(self._params_raisonnement())
            response = await self._client.responses.create(**resp_kwargs)

            total_input = 0
            total_output = 0
            total_cached = 0

            if response.usage:
                entree, sortie, caches = compter_jetons(response.usage)
                total_input += entree
                total_output += sortie
                total_cached += caches

            max_iterations = 3
            for _ in range(max_iterations):
                function_calls = [
                    item for item in response.output
                    if item.type == "function_call"
                ]
                if not function_calls:
                    break

                full_messages.extend(response.output)
                for fc in function_calls:
                    tools_called.append(fc.name)
                    result = await tool_executor(fc.name, fc.arguments)
                    full_messages.append({
                        "type": "function_call_output",
                        "call_id": fc.call_id,
                        "output": result,
                    })

                resp_kwargs["input"] = full_messages
                response = await self._client.responses.create(**resp_kwargs)
                if response.usage:
                    entree, sortie, caches = compter_jetons(response.usage)
                    total_input += entree
                    total_output += sortie
                    total_cached += caches

            text = response.output_text
            if not text:
                # Après les 3 itérations, la sortie peut ne contenir QUE des
                # appels d'outils : `output_text` vaut "" et la méthode rendait
                # cette chaîne vide comme un succès. Un message Discord/Twitch
                # vide, ou une pensée cognitive vide, indiscernables d'un modèle
                # silencieux. Le contrat de `BaseLLMClient` prévoit le fallback.
                logger.warning(
                    "OpenAI (Responses+tools): sortie sans texte après {n} tours",
                    n=max_iterations,
                )
                text = FALLBACK_RESPONSE
            cost = estimate_cost(self._model, total_input, total_output, cached_input_tokens=total_cached)
            logger.info(
                "OpenAI {model} (Responses+tools) — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
                model=self._model, inp=total_input, out=total_output, cost=cost, purpose=purpose,
            )
            try:
                await self._db.log_cost(
                    model=self._model,
                    input_tokens=total_input,
                    output_tokens=total_output,
                    cost_usd=cost,
                    purpose=purpose,
                    user_id=user_id,
                )
            except Exception as e:
                logger.debug("OpenAI log_cost failed (non-fatal): {e!r}", e=e)
            return text, tools_called

        except Exception as exc:
            logger.error("OpenAI Responses API (tools) error: {e!r}", e=exc)
            fallback = FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE
            return fallback, tools_called

    async def _complete_with_tools_chat(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, str], Awaitable[str]],
        purpose: str,
        image_urls: list[str] | None,
        user_id: str | None,
        tools_called: list[str],
    ) -> tuple[str, list[str]]:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        if image_urls:
            last_msg = dict(full_messages[-1])
            last_msg["content"] = self._build_image_content(
                last_msg["content"], image_urls, False
            )
            full_messages[-1] = last_msg

        total_input = 0
        total_output = 0
        total_cached = 0

        for attempt in range(3):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=full_messages,
                    tools=tools,
                    temperature=self._temperature,
                    max_completion_tokens=self._max_tokens,
                )

                entree, sortie, caches = compter_jetons(response.usage)
                total_input += entree
                total_output += sortie
                total_cached += caches

                msg = response.choices[0].message

                max_iterations = 3
                for _ in range(max_iterations):
                    if not msg.tool_calls:
                        break

                    full_messages.append(msg)
                    for tc in msg.tool_calls:
                        tools_called.append(tc.function.name)
                    # Tool calls indépendants d'un même tour → exécution en parallèle.
                    results = await asyncio.gather(
                        *(tool_executor(tc.function.name, tc.function.arguments) for tc in msg.tool_calls)
                    )
                    for tc, result in zip(msg.tool_calls, results):
                        full_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })

                    response = await self._client.chat.completions.create(
                        model=self._model,
                        messages=full_messages,
                        tools=tools,
                        temperature=self._temperature,
                        max_completion_tokens=self._max_tokens,
                    )
                    entree, sortie, caches = compter_jetons(response.usage)
                    total_input += entree
                    total_output += sortie
                    total_cached += caches
                    msg = response.choices[0].message

                cost = estimate_cost(self._model, total_input, total_output, cached_input_tokens=total_cached)
                logger.info(
                    "OpenAI {model} (Chat+tools) — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
                    model=self._model, inp=total_input, out=total_output, cost=cost, purpose=purpose,
                )
                try:
                    await self._db.log_cost(
                        model=self._model,
                        input_tokens=total_input,
                        output_tokens=total_output,
                        cost_usd=cost,
                        purpose=purpose,
                        user_id=user_id,
                    )
                except Exception as e:
                    logger.debug("OpenAI log_cost failed (non-fatal): {e!r}", e=e)
                return msg.content.strip() if msg.content else FALLBACK_RESPONSE, tools_called

            except RateLimitError:
                wait = 2 ** attempt
                logger.warning("Rate limited (tools), retrying in {w}s", w=wait)
                await asyncio.sleep(wait)
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning("OpenAI server error {code} (tools), retrying in {w}s", code=exc.status_code, w=wait)
                    await asyncio.sleep(wait)
                else:
                    logger.error("OpenAI API error {code} (tools): {e!r}", code=exc.status_code, e=exc)
                    break
            # `APIConnectionError` / `APITimeoutError` ne dérivent PAS de
            # `APIStatusError` : ils tombaient dans le `except Exception`
            # ci-dessous, qui sort sans rejouer. Autrement dit, aucune reprise
            # sur la panne la PLUS fréquente, là où un 503 en a trois.
            except (APIConnectionError, APITimeoutError) as exc:
                wait = 2 ** attempt
                logger.warning("OpenAI réseau ({e!r}) — reprise dans {w}s", e=exc, w=wait)
                await asyncio.sleep(wait)
            except Exception as exc:
                logger.error("OpenAI unexpected error (tools): {e!r}", e=exc)
                break

        fallback = FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE
        return fallback, tools_called

    async def complete_structured(
        self,
        system_prompt: str,
        messages: list[dict],
        schema: dict,
        schema_name: str = "response",
        purpose: str = "structured",
        user_id: str | None = None,
    ) -> dict:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        if _uses_responses_api(self._model):
            for attempt in range(3):
                try:
                    kwargs: dict = {
                        "model": self._model,
                        "input": full_messages,
                        "text": {
                            "format": {
                                "type": "json_schema",
                                "name": schema_name,
                                "schema": schema,
                            }
                        },
                    }
                    kwargs.update(self._params_raisonnement(avec_plafond=False))

                    response = await self._client.responses.create(**kwargs)

                    if response.status != "completed":
                        raise RuntimeError(
                            f"Structured output truncated or incomplete "
                            f"(status={response.status!r})"
                        )

                    text = response.output_text
                    if not text:
                        for item in response.output:
                            if hasattr(item, "content"):
                                for block in item.content:
                                    t = getattr(block, "text", None)
                                    if t:
                                        text = t
                                        break
                            if text:
                                break
                    if not text:
                        output_types = [f"{item.type}" for item in response.output]
                        raise RuntimeError(
                            f"Structured output empty despite status=completed "
                            f"(output_types={output_types})"
                        )

                    parsed = json.loads(text)

                    if response.usage:
                        try:
                            cached = response.usage.input_tokens_details.cached_tokens or 0
                        except (AttributeError, TypeError):
                            cached = 0
                        cost = estimate_cost(
                            self._model, response.usage.input_tokens,
                            response.usage.output_tokens, cached_input_tokens=cached,
                        )
                        logger.info(
                            "OpenAI {model} (Responses/structured) — {inp}in/{out}out tokens, "
                            "${cost:.6f} [{purpose}]",
                            model=self._model, inp=response.usage.input_tokens,
                            out=response.usage.output_tokens, cost=cost, purpose=purpose,
                        )
                        # Le coût était CALCULÉ puis seulement journalisé, jamais
                        # écrit en base — `complete()` et les deux chemins
                        # outillés le font pourtant. `get_daily_cost()` et le
                        # seuil d'alerte sous-estimaient donc tous les appels
                        # structurés (gate, émotions, extraction de faits…).
                        await self._log_cost(
                            input_tokens=response.usage.input_tokens,
                            output_tokens=response.usage.output_tokens,
                            cost=cost, purpose=purpose, user_id=user_id,
                        )

                    return parsed

                except RuntimeError:
                    raise
                except RateLimitError:
                    wait = 2 ** attempt
                    logger.warning(
                        "Rate limited by OpenAI (structured), retrying in {w}s (attempt {a}/3)",
                        w=wait, a=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                except APIStatusError as exc:
                    if exc.status_code >= 500:
                        wait = 2 ** attempt
                        logger.warning(
                            "OpenAI server error {code} (structured), retrying in {w}s",
                            code=exc.status_code, w=wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "OpenAI API error {code} (structured): {e!r}",
                            code=exc.status_code, e=exc,
                        )
                        break
                # `APIConnectionError` / `APITimeoutError` ne dérivent PAS de
                # `APIStatusError` : ils tombaient dans le `except Exception`
                # ci-dessous, qui sort sans rejouer. Autrement dit, aucune reprise
                # sur la panne la PLUS fréquente, là où un 503 en a trois.
                except (APIConnectionError, APITimeoutError) as exc:
                    wait = 2 ** attempt
                    logger.warning("OpenAI réseau ({e!r}) — reprise dans {w}s", e=exc, w=wait)
                    await asyncio.sleep(wait)
                except Exception as exc:
                    logger.error("OpenAI unexpected error (structured/responses): {e!r}", e=exc)
                    break

            raise RuntimeError(
                f"complete_structured failed after 3 attempts (model={self._model!r})"
            )

        else:
            for attempt in range(3):
                try:
                    response = await self._client.chat.completions.create(
                        model=self._model,
                        messages=full_messages,
                        temperature=self._temperature,
                        response_format={
                            "type": "json_schema",
                            "json_schema": {
                                "name": schema_name,
                                "schema": schema,
                                "strict": True,
                            },
                        },
                    )

                    choice = response.choices[0]
                    if choice.finish_reason == "length":
                        raise RuntimeError(
                            "Structured output truncated (finish_reason='length')"
                        )

                    parsed = json.loads(choice.message.content)

                    entree, sortie, cached = compter_jetons(response.usage)
                    cost = estimate_cost(
                        self._model, entree, sortie,
                        cached_input_tokens=cached,
                    )
                    logger.info(
                        "OpenAI {model} (Chat/structured) — {inp}in/{out}out tokens, "
                        "${cost:.6f} [{purpose}]",
                        model=self._model, inp=entree,
                        out=sortie, cost=cost, purpose=purpose,
                    )
                    await self._log_cost(
                        input_tokens=entree,
                        output_tokens=sortie,
                        cost=cost, purpose=purpose, user_id=user_id,
                    )

                    return parsed

                except RuntimeError:
                    raise
                except RateLimitError:
                    wait = 2 ** attempt
                    logger.warning(
                        "Rate limited by OpenAI (structured), retrying in {w}s (attempt {a}/3)",
                        w=wait, a=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                except APIStatusError as exc:
                    if exc.status_code >= 500:
                        wait = 2 ** attempt
                        logger.warning(
                            "OpenAI server error {code} (structured), retrying in {w}s",
                            code=exc.status_code, w=wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "OpenAI API error {code} (structured): {e!r}",
                            code=exc.status_code, e=exc,
                        )
                        break
                # `APIConnectionError` / `APITimeoutError` ne dérivent PAS de
                # `APIStatusError` : ils tombaient dans le `except Exception`
                # ci-dessous, qui sort sans rejouer. Autrement dit, aucune reprise
                # sur la panne la PLUS fréquente, là où un 503 en a trois.
                except (APIConnectionError, APITimeoutError) as exc:
                    wait = 2 ** attempt
                    logger.warning("OpenAI réseau ({e!r}) — reprise dans {w}s", e=exc, w=wait)
                    await asyncio.sleep(wait)
                except Exception as exc:
                    logger.error("OpenAI unexpected error (structured/chat): {e!r}", e=exc)
                    break

            raise RuntimeError(
                f"complete_structured failed after 3 attempts (model={self._model!r})"
            )

    # ── Image generation (OpenAI-specific, not part of BaseLLMClient) ─────────

    @staticmethod
    def estimate_image_cost(model: str, quality: str, size: str) -> float:
        model_costs = IMAGE_COSTS.get(model)
        if not model_costs:
            return 0.25
        cost = model_costs.get((quality, size))
        if cost is not None:
            return cost
        return max(model_costs.values())

    async def generate_image(self, prompt: str, config: "ImageGenerationConfig", sender_id: str | None = None) -> dict:
        model = config.model
        quality = config.quality
        size = config.size

        if config.daily_limit != -1:
            today_total = await self._db.get_total_image_count_today()
            if today_total >= config.daily_limit:
                raise ValueError("Limite quotidienne de génération d'images atteinte.")
        if config.per_user_limit != -1 and sender_id:
            user_today = await self._db.get_user_image_count_today(sender_id)
            if user_today >= config.per_user_limit:
                raise ValueError("Tu as atteint ta limite d'images pour aujourd'hui.")

        DATA_GALLERY_DIR.mkdir(parents=True, exist_ok=True)

        last_error = None
        for attempt in range(3):
            try:
                response = await self._client.images.generate(
                    model=model,
                    prompt=prompt,
                    n=1,
                    size=size,
                    quality=quality,
                    background=config.background,
                    output_format=config.format if config.format in ("png", "jpeg", "webp") else "png",
                )
                break
            except RateLimitError as e:
                last_error = e
                logger.warning("Image rate limit, attempt {a}/3: {e!r}", a=attempt + 1, e=e)
                await asyncio.sleep(2 ** attempt)
            except APIStatusError as e:
                if e.status_code == 400:
                    body = getattr(e, "body", None) or {}
                    detail = body.get("error", {}).get("message", str(e)) if isinstance(body, dict) else str(e)
                    logger.warning("Image API 400: {detail}", detail=detail)
                    raise ValueError(f"Erreur API image : {detail}") from e
                if e.status_code >= 500:
                    last_error = e
                    logger.warning("Image API 5xx, attempt {a}/3: {e!r}", a=attempt + 1, e=e)
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
        else:
            logger.error("Image generation failed after 3 attempts: {e}", e=last_error)
            raise RuntimeError("Échec de la génération d'image après 3 tentatives.")

        image_data = base64.b64decode(response.data[0].b64_json)
        file_ext = config.format if config.format in ("png", "jpeg", "webp") else "png"
        file_id = str(uuid.uuid4())
        file_name = f"{file_id}.{file_ext}"
        file_path = DATA_GALLERY_DIR / file_name
        file_path.write_bytes(image_data)

        cost_usd = self.estimate_image_cost(model, quality, size)

        revised = getattr(response.data[0], "revised_prompt", None)

        return {
            "file_id": file_id,
            "file_name": file_name,
            "file_path": str(file_path),
            "cost_usd": cost_usd,
            "revised_prompt": revised,
            "model": model,
            "quality": quality,
            "size": size,
        }

    async def get_daily_cost(self) -> float:
        return await self._db.get_cost_since(time.time() - 86_400)

    async def get_monthly_cost(self) -> float:
        return await self._db.get_cost_since(time.time() - 86_400 * 30)
