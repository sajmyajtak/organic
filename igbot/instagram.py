"""Thin client for Meta's official Instagram Platform API.

Two hosts are supported because Meta offers two login flavours:

* ``graph.facebook.com`` - Instagram API with Unified Login (Meta's
  recommended setup, needs a free business portfolio) or with Facebook Login
  (account linked to a Facebook Page). Unlocks Business Discovery, which
  `discover` needs.
* ``graph.instagram.com`` - Instagram API with Instagram Login. Simplest
  setup, but no Business Discovery / Hashtag Search.

Publishing works the same on both: create a media container from a public
URL, wait until it is FINISHED, then publish it.
"""

from __future__ import annotations

import time

import requests

from .config import env

DEFAULT_VERSION = "v26.0"


class InstagramError(RuntimeError):
    pass


class Instagram:
    def __init__(self, user_id: str, token: str, host: str = "graph.facebook.com",
                 version: str = DEFAULT_VERSION, dry_run: bool = False):
        self.user_id = user_id
        self.token = token
        self.base = f"https://{host}/{version}"
        self.host = host
        self.dry_run = dry_run

    @classmethod
    def from_env(cls, dry_run: bool = False) -> "Instagram":
        return cls(
            user_id=env("IG_USER_ID", required=not dry_run) or "dry-run",
            token=env("IG_ACCESS_TOKEN", required=not dry_run) or "dry-run",
            host=env("IG_API_HOST", "graph.facebook.com"),
            version=env("IG_API_VERSION", DEFAULT_VERSION),
            dry_run=dry_run,
        )

    # -- low level ---------------------------------------------------------

    def _request(self, method: str, path: str, **params) -> dict:
        params["access_token"] = self.token
        url = path if path.startswith("https://") else f"{self.base}/{path.lstrip('/')}"
        for attempt in range(4):
            resp = requests.request(method, url, params=params if method == "GET" else None,
                                    data=params if method != "GET" else None, timeout=60)
            if resp.status_code < 500 and resp.status_code != 429:
                break
            time.sleep(2 ** attempt * 5)
        payload = resp.json() if resp.content else {}
        if resp.status_code >= 400 or "error" in payload:
            err = payload.get("error", {})
            raise InstagramError(f"{resp.status_code} {err.get('type')} {err.get('code')}: {err.get('message')}")
        return payload

    def get(self, path: str, **params) -> dict:
        return self._request("GET", path, **params)

    def post(self, path: str, **params) -> dict:
        if self.dry_run:
            print(f"[dry-run] POST {path} {sorted(params)}")
            return {"id": f"dry-{path.strip('/').replace('/', '-')}"}
        return self._request("POST", path, **params)

    # -- publishing --------------------------------------------------------

    def _container(self, **params) -> str:
        return self.post(f"{self.user_id}/media", **params)["id"]

    def wait_until_ready(self, container_id: str, timeout: int = 300, interval: int = 20) -> None:
        """Poll the container; Meta asks for roughly one check a minute, max ~5 minutes.

        Images are usually FINISHED on the first check, so that one is immediate.
        """
        if self.dry_run:
            return
        deadline = time.time() + timeout
        while True:
            data = self.get(container_id, fields="status_code,status")
            status = data.get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Kontejner {container_id} skončil ve stavu {status}: {data.get('status')}")
            if time.time() + interval > deadline:
                raise InstagramError(f"Kontejner {container_id} nebyl hotový do {timeout} s")
            time.sleep(interval)

    def _publish(self, container_id: str) -> str:
        self.wait_until_ready(container_id)
        return self.post(f"{self.user_id}/media_publish", creation_id=container_id)["id"]

    def publish_image(self, image_url: str, caption: str, alt_text: str = "", ai_generated: bool = False) -> str:
        params = {"image_url": image_url, "caption": caption}
        if alt_text:
            params["alt_text"] = alt_text[:1000]
        if ai_generated:
            params["is_ai_generated"] = "true"
        return self._publish(self._container(**params))

    def publish_carousel(self, image_urls: list[str], caption: str, ai_generated: bool = False) -> str:
        # Children carry no caption and must not carry is_ai_generated (API error).
        children = [self._container(image_url=url, is_carousel_item="true") for url in image_urls[:20]]
        for child in children:
            self.wait_until_ready(child)
        params = {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption}
        if ai_generated:
            params["is_ai_generated"] = "true"
        return self._publish(self._container(**params))

    def publish_story(self, image_url: str | None = None, video_url: str | None = None,
                      ai_generated: bool = False) -> str:
        """Stories via API cannot carry link, poll or location stickers."""
        params = {"media_type": "STORIES"}
        if ai_generated:
            params["is_ai_generated"] = "true"
        if video_url:
            params["video_url"] = video_url
        else:
            params["image_url"] = image_url
        return self._publish(self._container(**params))

    def publish_reel(self, video_url: str, caption: str, cover_url: str | None = None,
                     share_to_feed: bool = True, trial: bool = False, ai_generated: bool = False) -> str:
        params = {"media_type": "REELS", "video_url": video_url, "caption": caption,
                  "share_to_feed": str(share_to_feed).lower()}
        if cover_url:
            params["cover_url"] = cover_url
        if trial:
            # Trial reels go to non-followers first and graduate to followers
            # automatically when they perform well.
            params["trial_params"] = '{"graduation_strategy":"SS_PERFORMANCE"}'
        if ai_generated:
            params["is_ai_generated"] = "true"
        container = self._container(**params)
        self.wait_until_ready(container, timeout=600, interval=60)
        return self.post(f"{self.user_id}/media_publish", creation_id=container)["id"]

    def publishing_quota(self) -> dict:
        data = self.get(f"{self.user_id}/content_publishing_limit", fields="quota_usage,config")
        return (data.get("data") or [{}])[0]

    # -- analytics ---------------------------------------------------------

    def media_list(self, limit: int = 50) -> list[dict]:
        fields = "id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count"
        return self.get(f"{self.user_id}/media", fields=fields, limit=limit).get("data", [])

    def media_insights(self, media_id: str, metrics: list[str]) -> dict:
        data = self.get(f"{media_id}/insights", metric=",".join(metrics)).get("data", [])
        return {m["name"]: (m.get("values") or [{}])[0].get("value", m.get("total_value", {}).get("value"))
                for m in data}

    def account(self) -> dict:
        return self.get(self.user_id, fields="username,followers_count,follows_count,media_count")

    # -- discovery (Facebook Login host only) ------------------------------

    MEDIA_FIELDS = ("caption,media_type,media_product_type,view_count,like_count,comments_count,"
                    "permalink,shortcode,timestamp,media_url,thumbnail_url")

    def business_discovery(self, username: str, media_limit: int = 25, after: str | None = None,
                           media_fields: str = MEDIA_FIELDS) -> dict:
        """Public profile + one page of recent posts of another Business/Creator account."""
        if self.host != "graph.facebook.com":
            raise InstagramError("Business Discovery vyžaduje IG_API_HOST=graph.facebook.com")
        cursor = f".after({after})" if after else ""
        media = f"media{cursor}.limit({media_limit}){{{media_fields}}}"
        fields = (f"business_discovery.username({username})"
                  f"{{username,biography,website,followers_count,media_count,{media}}}")
        return self.get(self.user_id, fields=fields)["business_discovery"]

    def account_posts(self, username: str, limit: int = 60) -> tuple[dict, list[dict]]:
        """Profile and up to `limit` most recent posts, following pagination cursors."""
        posts: list[dict] = []
        after = None
        profile: dict = {}
        while len(posts) < limit:
            page = self.business_discovery(username, min(25, limit - len(posts)), after)
            media = page.pop("media", {}) or {}
            profile = profile or page
            posts += media.get("data", [])
            after = (media.get("paging") or {}).get("cursors", {}).get("after")
            if not after or not media.get("data"):
                break
        return profile, posts[:limit]

    # -- tokens ------------------------------------------------------------

    def refresh_instagram_login_token(self) -> dict:
        """Extend a long-lived Instagram Login token by another 60 days."""
        return self.get("https://graph.instagram.com/refresh_access_token", grant_type="ig_refresh_token")
