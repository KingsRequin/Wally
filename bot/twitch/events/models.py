# bot/twitch/events/models.py
from __future__ import annotations


class _ChatBadge:
    """Wraps an EventSub badge entry.

    EventSub badge format: {"set_id": "moderator", "id": "1", "info": ""}
    The type identifier is in `set_id` ("moderator", "broadcaster", "subscriber", "vip", "bot"…).
    We expose it as `.id` so existing callers (b.id if hasattr(b,'id') else str(b)) work without change.
    """

    __slots__ = ("id", "set_id")

    def __init__(self, data: dict):
        self.set_id: str = data.get("set_id", "")
        self.id: str = self.set_id  # callers check b.id for type names


class ChatMessageData:
    """Minimal data model for channel.chat.message EventSub notifications.

    Registered into twitchio v2's SubscriptionTypes at runtime in
    start_eventsub_client() since twitchio v2 does not natively support
    channel.chat.message.

    Attributes:
      chatter.id / chatter.name — chatter_user_id / chatter_user_login
      chatter_display           — chatter_user_name (le pseudo AFFICHÉ)
      message.text              — message.text
      broadcaster.name          — broadcaster_user_login
      badges                    — list[_ChatBadge] from top-level "badges" array

    Twitch distingue le `login` (minuscules, immuable, celui des mentions) du
    `user_name` (ce que la personne a choisi d'afficher : casse, accents, autre
    alphabet). Ce modèle ne lisait que le login, et Wally appelait donc les gens
    « malef__ » ou « kingsrequin » là où Discord dit « Malef ». L'information
    était pourtant DANS la charge utile reçue — jetée à la construction, pas
    absente. Aucun appel d'API à faire pour la récupérer.
    """

    __slots__ = "chatter", "chatter_display", "message", "broadcaster", "message_id", "badges"

    def __init__(self, client, data: dict):
        self.chatter = client.client.create_user(
            int(data["chatter_user_id"]), data["chatter_user_login"]
        )
        self.chatter_display: str = (
            data.get("chatter_user_name") or data["chatter_user_login"]
        )
        self.message = _ChatMessageText(data["message"])
        self.broadcaster = client.client.create_user(
            int(data["broadcaster_user_id"]), data["broadcaster_user_login"]
        )
        self.message_id: str = data.get("message_id", "")
        self.badges: list[_ChatBadge] = [
            _ChatBadge(b) for b in data.get("badges", [])
        ]


class _ChatMessageText:
    __slots__ = ("text",)

    def __init__(self, data: dict):
        self.text: str = data["text"]
