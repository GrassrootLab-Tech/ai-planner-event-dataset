from __future__ import annotations

import httpx

from reddit.models import RedditComment, RedditThread
from reddit.url import extract_post_id
from utils.logger import log_pretty, logger

TOP_LEVEL_COMMENT_LIMIT = 40
MAX_FIRST_LEVEL_REPLIES = 3
MORECHILDREN_BATCH_SIZE = 100


class RedditFetchError(Exception):
    pass


class RedditClient:
    TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
    API_BASE = "https://oauth.reddit.com"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._access_token: str | None = None

    async def fetch_post(self, page_url: str) -> RedditThread:
        post_id = extract_post_id(page_url)
        token = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": self._user_agent,
        }

        url = f"{self.API_BASE}/comments/{post_id}"
        params = {
            "sort": "top",
            "limit": TOP_LEVEL_COMMENT_LIMIT,
            "raw_json": 1,
            "depth": 2,
        }

        log_pretty(
            "Calling Reddit API",
            {
                "url": url,
                "post_id": post_id,
                "params": params,
            },
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, params=params, headers=headers)
            logger.info("Reddit responded with status=%s", response.status_code)

            if response.status_code != 200:
                raise RedditFetchError(
                    f"Reddit request failed with status {response.status_code}: {response.text}"
                )

            data = response.json()
            if not isinstance(data, list) or len(data) < 2:
                raise RedditFetchError("Unexpected Reddit comments response shape")

            thread = self._parse_post_metadata(post_id, data)
            children = data[1].get("data", {}).get("children", [])
            comments, more_ids = self._collect_top_level(children)

            while len(comments) < TOP_LEVEL_COMMENT_LIMIT and more_ids:
                batch = more_ids[:MORECHILDREN_BATCH_SIZE]
                more_ids = more_ids[MORECHILDREN_BATCH_SIZE:]
                needed = TOP_LEVEL_COMMENT_LIMIT - len(comments)
                extra_comments, extra_more = await self._fetch_more_children(
                    client,
                    headers,
                    post_id,
                    batch,
                )
                comments.extend(extra_comments[:needed])
                more_ids.extend(extra_more)

        thread.comments = comments[:TOP_LEVEL_COMMENT_LIMIT]
        log_pretty(
            "Reddit fetch result",
            {
                "post_id": thread.post_id,
                "title": thread.title,
                "comment_count": len(thread.comments),
            },
        )
        return thread

    async def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token

        headers = {"User-Agent": self._user_agent}
        data = {"grant_type": "client_credentials"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.TOKEN_URL,
                data=data,
                headers=headers,
                auth=(self._client_id, self._client_secret),
            )

        if response.status_code != 200:
            raise RedditFetchError(
                f"Reddit OAuth failed with status {response.status_code}: {response.text}"
            )

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RedditFetchError("Reddit OAuth response missing access_token")

        self._access_token = token
        return token

    async def _fetch_more_children(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        post_id: str,
        comment_ids: list[str],
    ) -> tuple[list[RedditComment], list[str]]:
        if not comment_ids:
            return [], []

        url = f"{self.API_BASE}/api/morechildren"
        form = {
            "api_type": "json",
            "link_id": f"t3_{post_id}",
            "children": ",".join(comment_ids),
            "sort": "top",
            "depth": "2",
            "limit_children": "False",
        }

        log_pretty(
            "Calling Reddit morechildren",
            {
                "post_id": post_id,
                "batch_size": len(comment_ids),
            },
        )

        response = await client.post(url, data=form, headers=headers)
        logger.info("Reddit morechildren status=%s", response.status_code)

        if response.status_code != 200:
            raise RedditFetchError(
                f"Reddit morechildren failed with status {response.status_code}: {response.text}"
            )

        payload = response.json()
        things = payload.get("json", {}).get("data", {}).get("things", [])
        if not isinstance(things, list):
            return [], []

        return self._comments_from_things(things, post_id)

    def _parse_post_metadata(self, post_id: str, data: list) -> RedditThread:
        post_listing = data[0].get("data", {}).get("children", [])
        if not post_listing:
            raise RedditFetchError(f"No post found for id={post_id}")

        post_data = post_listing[0].get("data", {})
        title = (post_data.get("title") or "").strip()
        selftext = (post_data.get("selftext") or "").strip()
        permalink = post_data.get("permalink") or ""
        if permalink and not permalink.startswith("http"):
            permalink = f"https://www.reddit.com{permalink}"

        link_url: str | None = None
        is_self = bool(post_data.get("is_self"))
        url = (post_data.get("url") or "").strip()
        if not is_self and url:
            link_url = url

        return RedditThread(
            post_id=post_id,
            title=title,
            selftext=selftext,
            permalink=permalink,
            link_url=link_url,
            comments=[],
        )

    def _collect_top_level(
        self,
        children: list,
    ) -> tuple[list[RedditComment], list[str]]:
        comments: list[RedditComment] = []
        more_ids: list[str] = []

        for child in children:
            kind = child.get("kind")
            data = child.get("data", {}) or {}
            if kind == "t1":
                comment = self._parse_comment(data, include_replies=True)
                if comment is not None:
                    comments.append(comment)
            elif kind == "more":
                more_ids.extend(self._more_children_ids(data))

        return comments, more_ids

    def _comments_from_things(
        self,
        things: list,
        post_id: str,
    ) -> tuple[list[RedditComment], list[str]]:
        link_fullname = f"t3_{post_id}"
        comments: list[RedditComment] = []
        more_ids: list[str] = []

        children_by_parent: dict[str, list[dict]] = {}
        for thing in things:
            data = thing.get("data", {}) or {}
            parent_id = data.get("parent_id")
            if not parent_id:
                continue
            children_by_parent.setdefault(parent_id, []).append(thing)

        for thing in things:
            kind = thing.get("kind")
            data = thing.get("data", {}) or {}
            parent_id = data.get("parent_id")

            if kind == "more" and parent_id == link_fullname:
                more_ids.extend(self._more_children_ids(data))
                continue

            if kind != "t1" or parent_id != link_fullname:
                continue

            comment = self._parse_comment(data, include_replies=True)
            if comment is None:
                continue

            if len(comment.replies) < MAX_FIRST_LEVEL_REPLIES:
                name = data.get("name") or f"t1_{data.get('id', '')}"
                flat_replies = self._flat_replies_from_things(
                    children_by_parent.get(name, []),
                )
                existing = {r.body for r in comment.replies}
                for reply in flat_replies:
                    if reply.body in existing:
                        continue
                    comment.replies.append(reply)
                    existing.add(reply.body)
                    if len(comment.replies) >= MAX_FIRST_LEVEL_REPLIES:
                        break

            comments.append(comment)

        return comments, more_ids

    def _flat_replies_from_things(self, things: list) -> list[RedditComment]:
        replies: list[RedditComment] = []
        for thing in things:
            if thing.get("kind") != "t1":
                continue
            reply = self._parse_comment(
                thing.get("data", {}) or {},
                include_replies=False,
            )
            if reply is not None:
                replies.append(reply)
            if len(replies) >= MAX_FIRST_LEVEL_REPLIES:
                break
        return replies

    def _parse_comment(
        self,
        data: dict,
        *,
        include_replies: bool,
    ) -> RedditComment | None:
        body = self._usable_body(data)
        if body is None:
            return None

        replies: list[RedditComment] = []
        if include_replies:
            replies_raw = data.get("replies")
            if isinstance(replies_raw, dict):
                children = replies_raw.get("data", {}).get("children", [])
                for child in children:
                    if child.get("kind") != "t1":
                        continue
                    reply = self._parse_comment(
                        child.get("data", {}) or {},
                        include_replies=False,
                    )
                    if reply is not None:
                        replies.append(reply)
                    if len(replies) >= MAX_FIRST_LEVEL_REPLIES:
                        break

        return RedditComment(body=body, replies=replies)

    @staticmethod
    def _more_children_ids(data: dict) -> list[str]:
        children = data.get("children") or []
        return [str(child_id) for child_id in children if child_id]

    @staticmethod
    def _usable_body(data: dict) -> str | None:
        body = (data.get("body") or "").strip()
        if not body or body in {"[deleted]", "[removed]"}:
            return None
        return body
