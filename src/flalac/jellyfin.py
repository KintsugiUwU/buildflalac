"""The few Jellyfin calls flalac needs: read and set play counts of the songs in one library.

Jellyfin 10.9 or later. Authentication is an API key (Dashboard → API Keys) sent with the
`Authorization: MediaBrowser` scheme, the only one Jellyfin 12 accepts by default.
"""

from __future__ import annotations

import json
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from . import __version__
from .config import Settings


class JellyfinError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    plays: int


class Jellyfin:
    def __init__(
        self,
        url: str,
        api_key: str,
        user: str,
        music_path: str,
        opener: Callable = urllib.request.urlopen,
    ) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.user = user
        self.music_path = music_path.rstrip("/")
        self._open = opener
        self._user_id = ""

    @classmethod
    def from_settings(cls, settings: Settings) -> Jellyfin | None:
        if not (settings.jellyfin_url and settings.jellyfin_api_key and settings.jellyfin_user):
            return None
        return cls(
            settings.jellyfin_url,
            settings.jellyfin_api_key,
            settings.jellyfin_user,
            settings.jellyfin_music_path,
        )

    def _call(self, method: str, path: str, body: dict | None = None) -> object:
        auth = (
            f'MediaBrowser Client="flalac", Device="flalac", DeviceId="flalac", '
            f'Version="{__version__}", Token="{self.api_key}"'
        )
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.url + path, data=data, method=method)
        request.add_header("Authorization", auth)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self._open(request, timeout=60) as response:
                raw = response.read()
        except Exception as error:
            raise JellyfinError(f"{method} {path.split('?')[0]}: {error}") from error
        return json.loads(raw) if raw else None

    def user_id(self) -> str:
        if not self._user_id:
            users = self._call("GET", "/Users") or []
            for user in users if isinstance(users, list) else []:
                if str(user.get("Name", "")).casefold() == self.user.casefold():
                    self._user_id = str(user["Id"])
                    break
            else:
                raise JellyfinError(f"no Jellyfin user named {self.user!r}")
        return self._user_id

    def play_counts(self) -> dict[str, Item]:
        """Songs under the music path, by path relative to it (NFC), with their play counts."""
        query = urllib.parse.urlencode(
            {
                "userId": self.user_id(),
                "IncludeItemTypes": "Audio",
                "Recursive": "true",
                "Fields": "Path",
                "EnableUserData": "true",
            }
        )
        result = self._call("GET", f"/Items?{query}") or {}
        prefix = self.music_path + "/"
        found: dict[str, Item] = {}
        for item in result.get("Items", []) if isinstance(result, dict) else []:
            path = str(item.get("Path") or "")
            if not path.startswith(prefix):
                continue
            rel = unicodedata.normalize("NFC", path[len(prefix) :])
            plays = int((item.get("UserData") or {}).get("PlayCount") or 0)
            found[rel] = Item(str(item["Id"]), plays)
        return found

    def set_play_count(self, item_id: str, plays: int) -> None:
        query = urllib.parse.urlencode({"userId": self.user_id()})
        item = urllib.parse.quote(item_id, safe="")
        self._call(
            "POST",
            f"/UserItems/{item}/UserData?{query}",
            {"PlayCount": plays, "Played": plays > 0},
        )
