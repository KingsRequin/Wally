# bot/core/llm/deepseek.py
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

from loguru import logger
from openai import AsyncOpenAI

from bot.core.llm.base import BaseLLMClient, FALLBACK_RESPONSE


# Coût DeepSeek par 1M tokens : (input cache hit, input cache miss, output) en USD.
# Source : https://api-docs.deepseek.com/quick_start/pricing/ (vérifié 2026-08-14).
# deepseek-chat / deepseek-reasoner = alias de flash, dépréciés le 2026-07-24.
#
# Deux grilles, parce que DeepSeek a relevé ses tarifs le 2026-08-16 à 16:00 UTC
# (×1,5 à ×12 selon la case) en introduisant des heures pleines. On garde
# l'ancienne : un appel daté du 15/08 doit rester chiffré au tarif que DeepSeek a
# réellement facturé ce jour-là, sinon le `cost_log` ment sur son propre passé.
_DEEPSEEK_COSTS_LEGACY: dict[str, tuple[float, float, float]] = {
    "deepseek-v4-pro": (0.003625, 0.435, 0.87),
    "deepseek-v4-flash": (0.0028, 0.14, 0.28),
    "deepseek-chat": (0.0028, 0.14, 0.28),
    "deepseek-reasoner": (0.0028, 0.14, 0.28),
}
_DEEPSEEK_FALLBACK_COST_LEGACY = (0.0028, 0.14, 0.28)

# Grille en vigueur. Elle porte les tarifs HEURES CREUSES ; les heures pleines
# sont le même tarif ×`_DEEPSEEK_PEAK_MULTIPLIER`.
_DEEPSEEK_COSTS: dict[str, tuple[float, float, float]] = {
    "deepseek-v4-pro": (0.022, 0.66, 1.98),
    "deepseek-v4-flash": (0.007, 0.22, 0.66),
    "deepseek-chat": (0.007, 0.22, 0.66),
    "deepseek-reasoner": (0.007, 0.22, 0.66),
}
_DEEPSEEK_FALLBACK_COST = (0.007, 0.22, 0.66)

# Instant exact de la bascule (annonce DeepSeek du 2026-08-13). Gouverne à la fois
# le changement de grille et l'apparition des heures pleines : les deux arrivent
# ensemble. Une `date` ne suffirait pas — la bascule tombe à 16:00, pas à minuit.
_NEW_PRICING_START = datetime(2026, 8, 16, 16, 0, tzinfo=timezone.utc)
_DEEPSEEK_PEAK_MULTIPLIER = 2.0

# Reprises sur panne transitoire — mêmes valeurs que le client OpenAI (1s, 2s, 4s).
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0


def _is_deepseek_peak(now: datetime | None = None) -> bool:
    """True si `now` (UTC) tombe dans une plage de pointe DeepSeek (tarif ×2).

    Plages UTC : 01:00–04:00 et 06:00–10:00 (04:00–06:00 = creux), **du lundi au
    vendredi seulement**. Le samedi et le dimanche sont creux 24 h sur 24 — la
    grille tarifaire le dit noir sur blanc, et la clause manquait ici : le
    `cost_log` majorait donc de ×2 tous les appels du week-end tombant dans ces
    tranches, sur une plateforme dont le pic d'activité EST le week-end. Le
    chiffrage du passé s'en trouvait faux à la hausse, sans que rien ne le dise.

    Les heures pleines n'existent qu'à partir de `_NEW_PRICING_START`. `now` est
    injectable pour les tests.
    """
    now = now or datetime.now(timezone.utc)
    if now < _NEW_PRICING_START:
        return False
    if now.weekday() >= 5:      # 5 = samedi, 6 = dimanche
        return False
    h = now.hour
    return (1 <= h < 4) or (6 <= h < 10)


def _deepseek_rates(model: str, now: datetime | None = None) -> tuple[float, float, float]:
    """Tarifs (hit, miss, output) par 1M tokens pour `model` à l'instant `now`.

    Le matching privilégie le préfixe le plus long (ex. `deepseek-v4-pro-2026...`
    → `deepseek-v4-pro`), et retombe sur le tarif flash pour un modèle inconnu.
    Avant `_NEW_PRICING_START`, c'est l'ancienne grille qui s'applique.
    """
    now = now or datetime.now(timezone.utc)
    table, fallback = (
        (_DEEPSEEK_COSTS, _DEEPSEEK_FALLBACK_COST)
        if now >= _NEW_PRICING_START
        else (_DEEPSEEK_COSTS_LEGACY, _DEEPSEEK_FALLBACK_COST_LEGACY)
    )
    return table.get(model) or next(
        (v for k, v in sorted(table.items(), key=lambda x: len(x[0]), reverse=True)
         if model.startswith(k)),
        fallback,
    )


def _deepseek_cost(model: str, usage: Any, now: datetime | None = None) -> float:
    """Coût USD d'un appel depuis l'`usage` retourné par l'API DeepSeek.

    DeepSeek expose `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`
    (leur somme = `prompt_tokens`). Si absents (vieux modèle, mock), tout est
    facturé au tarif cache miss.

    Le tarif de pointe (×2) s'applique si `_is_deepseek_peak(now)`.
    """
    rates = _deepseek_rates(model, now)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    hit = getattr(usage, "prompt_cache_hit_tokens", None)
    miss = getattr(usage, "prompt_cache_miss_tokens", None)
    if hit is None or miss is None:
        hit, miss = 0, prompt_tokens
    completion = getattr(usage, "completion_tokens", 0) or 0
    cost = (hit * rates[0] + miss * rates[1] + completion * rates[2]) / 1_000_000
    if _is_deepseek_peak(now):
        cost *= _DEEPSEEK_PEAK_MULTIPLIER
    return cost


# DeepSeek V4 émet parfois ses appels d'outils en texte brut, au format interne
# DSML, au lieu du champ `tool_calls` — surtout quand la requête ne porte plus de
# `tools`. Le markup part alors en clair dans le chat et pollue l'historique.
# Amont : deepseek-ai/DeepSeek-V3#1244, vllm-project/vllm#40801.
# Les `｜` sont des barres pleine largeur (U+FF5C) ; l'ASCII est accepté par prudence.
_DSML_MARK = r"[|｜]+DSML[|｜]+"
_DSML_BLOCK = re.compile(rf"<{_DSML_MARK}tool_calls>.*?</{_DSML_MARK}tool_calls>", re.DOTALL)
_DSML_INVOKE = re.compile(rf'<{_DSML_MARK}invoke\s+name="([^"]+)">(.*?)</{_DSML_MARK}invoke>', re.DOTALL)
_DSML_PARAM = re.compile(
    rf'<{_DSML_MARK}parameter\s+name="([^"]+)"([^>]*)>(.*?)</{_DSML_MARK}parameter>', re.DOTALL
)
# Fragments orphelins : marqueur coupé entre deux chunks en streaming.
_DSML_STRAY = re.compile(rf"</?{_DSML_MARK}[^>\n]*>?", re.DOTALL)


def _dsml_value(raw: str, attrs: str) -> Any:
    """Valeur d'un paramètre DSML : littérale si `string="true"`, sinon JSON."""
    raw = raw.strip()
    if 'string="true"' in attrs:
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _parse_dsml_tool_calls(text: str) -> list[tuple[str, dict]]:
    """Reconstruit les `(nom, arguments)` des appels d'outils fuités en texte."""
    if not text or "DSML" not in text:
        return []
    return [
        (name, {p: _dsml_value(raw, attrs) for p, attrs, raw in _DSML_PARAM.findall(body)})
        for name, body in _DSML_INVOKE.findall(text)
    ]


def _strip_dsml(text: str) -> str:
    """Retire tout markup DSML — blocs entiers compris, pas seulement les balises.

    Garde-fou de dernier recours : ce qui sort d'ici part en clair dans le chat
    ou dans l'historique du tour suivant.
    """
    if not text or "DSML" not in text:
        return text
    for pattern in (_DSML_BLOCK, _DSML_INVOKE, _DSML_STRAY):
        text = pattern.sub("", text)
    return text.strip()


class _SyntheticToolCall:
    """Appel d'outil reconstruit depuis du markup DSML, au format d'un vrai tool call."""

    def __init__(self, id_: str, name: str, arguments: str) -> None:
        self.id = id_
        self.type = "function"
        self.function = SimpleNamespace(name=name, arguments=arguments)

    def model_dump(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


class DeepSeekLLMClient(BaseLLMClient):
    """Client DeepSeek V4 via OpenAI-compatible API.

    Gère :
    - thinking mode (disabled/enabled) via extra_body
    - preservation de reasoning_content uniquement sur les turns avec tool_calls
    - JSON repair pour les arguments malformés
    - cap max_tool_iters sur les boucles tool calling
    - complete_structured via forced tool_choice
    """

    def __init__(
        self,
        model: str,
        db: Any,
        temperature: float = 1.0,
        max_tokens: int = 2048,
        thinking_type: str = "disabled",   # "disabled" | "enabled"
        thinking_effort: str = "low",       # "low" | "high" | "max"
        max_tool_iters: int = 6,
    ) -> None:
        self._model = model
        self._db = db
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._thinking_type = thinking_type
        self._thinking_effort = thinking_effort
        self._max_tool_iters = max_tool_iters
        self._client = AsyncOpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com",
        )

    # ── Réglages relus à chaud ────────────────────────────────────────────────
    #
    # `OpenAILLMClient` expose ces propriétés depuis toujours ; DeepSeek ne
    # stockait que `self._model`, `self._max_tokens`… sans accesseur public. Or
    # la factory ne construit QUE du DeepSeek : `state.primary_llm.model = …`,
    # écrit par le dashboard et par `/wally setup`, créait un attribut FANTÔME
    # jamais relu. Les réglages « thinking » étaient en plus gardés par un
    # `hasattr(..., "thinking_type")` toujours faux, donc ignorés en silence.
    # Résultat : « sauvegardé » s'affichait, et le client en vol gardait
    # l'ancienne valeur jusqu'au redémarrage.

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
    def thinking_type(self) -> str:
        return self._thinking_type

    @thinking_type.setter
    def thinking_type(self, value: str) -> None:
        self._thinking_type = value

    @property
    def thinking_effort(self) -> str:
        return self._thinking_effort

    @thinking_effort.setter
    def thinking_effort(self, value: str) -> None:
        self._thinking_effort = value

    async def list_models(self) -> list[str]:
        """Le catalogue DeepSeek, trié. Liste vide si l'API ne répond pas."""
        try:
            catalogue = await self._client.models.list()
            return sorted(m.id for m in catalogue.data)
        except Exception as e:
            logger.warning("DeepSeek list_models() a échoué : {e!r}", e=e)
            return []

    # ── Helpers privés ────────────────────────────────────────────────────────

    def _extra_body(self, thinking_override: str | None = None) -> dict:
        t = thinking_override or self._thinking_type
        if t == "enabled":
            return {
                "thinking": {"type": "enabled"},
                "reasoning_effort": self._thinking_effort,
            }
        return {"thinking": {"type": "disabled"}}

    def _api_params(self, thinking_override: str | None = None, max_tokens: int | None = None) -> dict:
        """Construit les kwargs communs pour chat.completions.create."""
        extra = self._extra_body(thinking_override)
        thinking_active = extra.get("thinking", {}).get("type") == "enabled"
        params: dict = {
            "model": self._model,
            "max_tokens": max_tokens or self._max_tokens,
            "extra_body": extra,
        }
        if not thinking_active:
            params["temperature"] = self._temperature
        return params

    async def _creer_avec_reprises(self, **kwargs) -> Any:
        """Appelle l'API en réessayant les pannes transitoires.

        DeepSeek est le SEUL provider texte en production et n'avait aucune
        reprise, là où le client OpenAI en fait trois avec backoff. Un 429 ou
        une coupure réseau d'une seconde suffisait donc à servir un message
        d'excuse à l'utilisateur.

        On ne rejoue PAS les erreurs définitives (4xx hors 408/429) : les
        renvoyer trois fois ne ferait que retarder l'échec.
        """
        derniere: Exception | None = None
        for tentative in range(_MAX_RETRIES):
            try:
                return await self._client.chat.completions.create(**kwargs)
            except Exception as e:  # noqa: BLE001 — on trie juste après
                derniere = e
                statut = getattr(e, "status_code", None) or getattr(
                    getattr(e, "response", None), "status_code", None
                )
                rejouable = statut is None or statut in (408, 429) or statut >= 500
                if not rejouable or tentative == _MAX_RETRIES - 1:
                    raise
                delai = _RETRY_BASE_DELAY * (2 ** tentative)
                logger.warning(
                    "DeepSeek: tentative {n}/{m} échouée ({e!r}) — nouvelle dans {d}s",
                    n=tentative + 1, m=_MAX_RETRIES, e=e, d=delai,
                )
                await asyncio.sleep(delai)
        # `derniere` est `Exception | None` : `raise None` lève un TypeError
        # « exceptions must derive from BaseException », qui masquerait la vraie
        # panne. Inatteignable tant que `_MAX_RETRIES >= 1` — mais une constante
        # se change, et ce jour-là l'erreur doit rester lisible.
        if derniere is None:  # pragma: no cover — la boucle sort toujours avant
            raise RuntimeError("DeepSeek : aucune tentative n'a été faite")
        raise derniere

    @staticmethod
    def _safe_parse_args(raw: str) -> dict:
        """Parse les arguments JSON d'un tool call avec réparation si malformé."""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            for suffix in ['"', '"}', '"}}', '}']:
                try:
                    return json.loads(raw + suffix)
                # Ce `continue` EST le mécanisme : on essaie plusieurs fermetures
                # possibles (`"`, `"}`, `"}}`, `}`) sur un JSON tronqué, et l'échec de
                # l'une n'est pas une erreur — c'est le tour suivant. L'abandon final,
                # lui, est journalisé juste en dessous avec le texte brut.
                except json.JSONDecodeError:
                    continue
            logger.warning("DeepSeek: impossible de réparer le JSON d'arguments: {raw!r}", raw=raw[:100])
            return {}

    async def _log_cost(self, response: Any, purpose: str, user_id: str | None) -> None:
        try:
            usage = response.usage
            model = response.model or self._model
            # `prompt_cache_hit_tokens` est déjà lu par `_deepseek_cost` pour
            # facturer au bon tarif, et perdu aussitôt. On le garde : c'est la
            # seule façon de savoir ce que coûterait de faire varier le préfixe
            # du prompt. Absent chez un vieux modèle ou un mock → 0, comme là-bas.
            await self._db.log_cost(
                model=model,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                cost_usd=_deepseek_cost(model, usage),
                purpose=purpose,
                user_id=user_id,
                cached_input_tokens=int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0),
            )
        except Exception as e:
            logger.warning(
                "DeepSeek : coût NON enregistré ({e!r}) — la facturation "
                "s'arrête là si ça se répète", e=e)

    # ── Interface publique ────────────────────────────────────────────────────

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        try:
            response = await self._creer_avec_reprises(
                messages=[{"role": "system", "content": system_prompt}] + messages,
                **self._api_params(max_tokens=max_tokens),
            )
            text = _strip_dsml(response.choices[0].message.content or "")
            await self._log_cost(response, purpose, user_id)
            # Une sortie amputée par `max_tokens` est indiscernable d'une sortie
            # finie une fois rendue en `str`. Le 2026-08-12, le journal du soir
            # est parti sur Discord coupé en pleine phrase sans une ligne de log.
            if getattr(response.choices[0], "finish_reason", None) == "length":
                logger.warning(
                    "DeepSeek complete() : réponse coupée au plafond de tokens "
                    "(purpose={p}, max_tokens={m})",
                    p=purpose,
                    m=max_tokens or self._max_tokens,
                )
            # Contrat de `BaseLLMClient.complete` : le texte du modèle, ou
            # FALLBACK_RESPONSE. Une sortie vide — contenu nul, ou intégralement
            # constituée de balises DSML retirées juste au-dessus — le violait :
            # Wally restait muet sans un log sur Discord, et `/ask` rendait un
            # HTTP 400. Un silence n'est pas une réponse.
            if not text.strip():
                logger.warning("DeepSeek complete() : réponse vide (purpose={p})", p=purpose)
                return FALLBACK_RESPONSE
            return text
        except Exception as e:
            logger.error("DeepSeek complete() failed: {e!r}", e=e)
            return FALLBACK_RESPONSE

    async def complete_with_reasoning(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "reasoning",
        user_id: str | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, str]:
        """Un appel avec le mode *thinking* forcé. Retourne (content, reasoning).

        - `reasoning` = `reasoning_content` exposé par DeepSeek = la pensée privée
          (le `<think>`), jamais montrée telle quelle à l'utilisateur.
        - `content` = la sortie publique (ici : la décision en tags d'action).
        Si le serveur ne renvoie pas de reasoning, `reasoning` vaut "".
        Fondation du reasoning unifié (un seul appel pense + décide).
        """
        try:
            response = await self._creer_avec_reprises(
                messages=[{"role": "system", "content": system_prompt}] + messages,
                **self._api_params(thinking_override="enabled", max_tokens=max_tokens),
            )
            msg = response.choices[0].message
            # `_strip_dsml` comme sur les trois autres chemins : ce `content`
            # alimente `parse_decisions` puis devient `thought_text`, stocké en
            # base et diffusé sur le flux cognitif PUBLIC. C'est le mode d'échec
            # du correctif `2be2c64`, sur un chemin qu'il n'avait pas couvert.
            content = _strip_dsml(msg.content or "")
            reasoning = getattr(msg, "reasoning_content", None) or ""
            await self._log_cost(response, purpose, user_id)
            return content, reasoning
        except Exception as e:
            logger.error("DeepSeek complete_with_reasoning() failed: {e!r}", e=e)
            return "", ""

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
        history = list(messages)
        tools_called: list[str] = []
        params = self._api_params()

        for iteration in range(self._max_tool_iters):
            try:
                response = await self._creer_avec_reprises(
                    messages=[{"role": "system", "content": system_prompt}] + history,
                    tools=tools,
                    **params,
                )
            except Exception as e:
                logger.error("DeepSeek complete_with_tools() iter {i} failed: {e!r}", i=iteration, e=e)
                return (FALLBACK_RESPONSE, tools_called)

            msg = response.choices[0].message

            tool_calls = list(msg.tool_calls or [])
            if not tool_calls:
                text = msg.content or ""
                # L'appel a pu fuiter en texte au lieu du champ `tool_calls` : on le
                # rejoue plutôt que de rendre le markup à l'utilisateur.
                recovered = _parse_dsml_tool_calls(text)
                if not recovered:
                    # Pas de tool call → NE PAS inclure reasoning_content (règle DeepSeek)
                    await self._log_cost(response, purpose, user_id)
                    propre = _strip_dsml(text)
                    if not propre.strip():
                        logger.warning(
                            "DeepSeek complete_with_tools() : réponse vide (purpose={p})",
                            p=purpose,
                        )
                        return (FALLBACK_RESPONSE, tools_called)
                    return (propre, tools_called)
                logger.warning(
                    "DeepSeek: appel d'outil émis en texte DSML, récupéré: {names}",
                    names=[name for name, _ in recovered],
                )
                tool_calls = [
                    _SyntheticToolCall(f"dsml_{iteration}_{k}", name, json.dumps(args))
                    for k, (name, args) in enumerate(recovered)
                ]

            # Tool call → reasoning_content DOIT être préservé
            assistant_entry: dict = {
                "role": "assistant",
                "content": _strip_dsml(msg.content or ""),
                "tool_calls": [tc.model_dump() for tc in tool_calls],
            }
            reasoning = getattr(msg, "reasoning_content", None)
            if reasoning:
                assistant_entry["reasoning_content"] = reasoning
            history.append(assistant_entry)

            # Les tool_calls d'un même tour sont indépendants → exécution en parallèle.
            # (ex. plusieurs web_search enchaînés : 4×4s séquentiel → ~4s en parallèle)
            async def _run_tool(tc):
                brut = tc.function.arguments
                args = self._safe_parse_args(brut)
                # Un JSON irréparable rendait `{}` et l'outil s'exécutait À VIDE
                # — un rappel sans texte, une recherche sans requête — sans que
                # le modèle apprenne jamais que ses arguments étaient illisibles.
                # On le lui dit : il peut réémettre l'appel correctement.
                if not args and (brut or "").strip() not in ("", "{}"):
                    logger.warning(
                        "DeepSeek: arguments illisibles pour {name}, renvoyés au modèle",
                        name=tc.function.name,
                    )
                    return (
                        f"Erreur : les arguments de {tc.function.name} sont un JSON "
                        f"invalide et n'ont pas pu être lus. Réémets l'appel avec un "
                        f"JSON valide."
                    )
                try:
                    return await tool_executor(tc.function.name, json.dumps(args))
                except Exception as e:
                    logger.warning("Tool executor error for {name}: {e!r}", name=tc.function.name, e=e)
                    return f"Tool error: {e}"

            for tc in tool_calls:
                tools_called.append(tc.function.name)
            results = await asyncio.gather(*(_run_tool(tc) for tc in tool_calls))
            for tc, result in zip(tool_calls, results):
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result),
                })

        # Cap atteint → réponse finale. Les `tools` restent dans la requête, avec
        # `tool_choice="none"` : les retirer alors que l'historique est saturé
        # d'appels pousse le modèle à écrire l'appel suivant en texte (markup DSML).
        logger.warning("DeepSeek: max_tool_iters={n} atteint, génération finale sans appel d'outil", n=self._max_tool_iters)
        try:
            # Via `_creer_avec_reprises` comme les autres : cette génération
            # FINALE contournait le backoff. Un 429 d'une seconde ici rendait
            # FALLBACK_RESPONSE à l'utilisateur, alors que le même incident un
            # tour plus tôt aurait été absorbé.
            response = await self._creer_avec_reprises(
                messages=[{"role": "system", "content": system_prompt}] + history,
                tools=tools,
                tool_choice="none",
                **params,
            )
            text = _strip_dsml(response.choices[0].message.content or "") or FALLBACK_RESPONSE
            await self._log_cost(response, purpose, user_id)
            return (text, tools_called)
        except Exception as e:
            logger.error("DeepSeek complete_with_tools() final fallback failed: {e!r}", e=e)
            return (FALLBACK_RESPONSE, tools_called)

    async def complete_structured(
        self,
        system_prompt: str,
        messages: list[dict],
        schema: dict,
        schema_name: str = "response",
        purpose: str = "structured",
        user_id: str | None = None,
    ) -> dict:
        """Force un tool_choice pour obtenir du JSON structuré conforme au schema."""
        tool_def = {
            "type": "function",
            "function": {
                "name": schema_name,
                "description": f"Retourne une réponse structurée {schema_name}",
                "parameters": schema,
            },
        }
        # Thinking désactivé pour le structured output (incompatible + inutile)
        params = self._api_params(thinking_override="disabled")
        # « pas de tool_call » / « JSON vide après repair » sont souvent transitoires
        # (non-déterminisme du LLM) → un réessai immédiat évite la majorité des échecs.
        for attempt in range(2):
            try:
                # Idem : la boucle `range(2)` rejouait immédiatement, sans la
                # moindre attente — le pire schéma face à un rate-limit.
                response = await self._creer_avec_reprises(
                    messages=[{"role": "system", "content": system_prompt}] + messages,
                    tools=[tool_def],
                    tool_choice={"type": "function", "function": {"name": schema_name}},
                    **params,
                )
                msg = response.choices[0].message
                if not msg.tool_calls:
                    raise RuntimeError("DeepSeek complete_structured: pas de tool_call dans la réponse")
                raw_args = msg.tool_calls[0].function.arguments
                result = self._safe_parse_args(raw_args)
                if not result:
                    raise RuntimeError("DeepSeek complete_structured: JSON vide après repair")
                await self._log_cost(response, purpose, user_id)
                return result
            except Exception as e:
                if attempt == 0:
                    logger.warning("DeepSeek complete_structured() échec, réessai: {e!r}", e=e)
                    continue
                logger.error("DeepSeek complete_structured() failed: {e!r}", e=e)
                raise RuntimeError(f"DeepSeek structured output failed: {e}") from e
        # Inatteignable : chaque tour rend, relance ou lève. Mais la méthode
        # PROMET un dict — sans cette ligne, changer le nombre de tentatives
        # lui ferait rendre `None`, et l'appelant planterait bien plus loin,
        # sur un `.get()` incompréhensible.
        raise RuntimeError("DeepSeek complete_structured : aucune tentative n'a abouti")

    async def complete_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        tools: list[dict] | None = None,
        tool_executor: Optional[Callable[[str, str], Awaitable[str]]] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming via SSE DeepSeek. Fallback non-streamé si tools présents."""
        if tools and tool_executor:
            # Pas de streaming avec tools — fallback sur complete_with_tools
            text, _ = await self.complete_with_tools(
                system_prompt, messages, tools, tool_executor,
                purpose=purpose, user_id=user_id,
            )
            yield text
            return

        emis = False
        try:
            params = self._api_params()
            async with self._client.chat.completions.stream(
                messages=[{"role": "system", "content": system_prompt}] + messages,
                stream_options={"include_usage": True},
                **params,
            ) as stream:
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        emis = True
                        yield delta.content
                # Log du coût après épuisement du flux : l'usage (tokens + cache)
                # n'arrive que dans le chunk final via stream_options.include_usage.
                # Isolé : une erreur ici ne doit jamais injecter le fallback.
                try:
                    await self._log_cost(await stream.get_final_completion(), purpose, user_id)
                except Exception as e:
                    logger.debug("DeepSeek stream cost log failed (non-fatal): {e!r}", e=e)
        except Exception as e:
            logger.error("DeepSeek complete_stream() failed: {e!r}", e=e)
            # Le fallback ne remplace que ce qui n'est PAS déjà parti. Émis en
            # plus, il donnait au lecteur une demi-phrase suivie de « Je
            # rencontre un problème technique… ».
            if not emis:
                yield FALLBACK_RESPONSE
