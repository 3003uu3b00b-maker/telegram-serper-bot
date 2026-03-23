import base64
from datetime import datetime
import httpx
from config import GITHUB_TOKEN, GITHUB_REPO, GITHUB_SAVE_PATH


async def save_to_github(title: str, url: str, snippet: str) -> str:
    """記事情報を日付ベースのMDファイルに追記してGitHubにPush"""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    filename = f"{date_str}.md"
    file_path = f"{GITHUB_SAVE_PATH}/{filename}"

    new_entry = (
        f"\n---\n\n"
        f"## {title}\n\n"
        f"- **URL**: {url}\n"
        f"- **保存日時**: {now.strftime('%H:%M:%S')}\n\n"
        f"{snippet}\n"
    )

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    async with httpx.AsyncClient() as client:
        # 既存ファイルがあれば取得して追記
        get_resp = await client.get(api_url, headers=headers)

        if get_resp.status_code == 200:
            existing = get_resp.json()
            existing_content = base64.b64decode(existing["content"]).decode("utf-8")
            sha = existing["sha"]
            content = existing_content + new_entry
        else:
            # 新規作成
            content = f"# {date_str} 検索ログ\n" + new_entry
            sha = None

        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        payload = {
            "message": f"Add: {title} ({date_str})",
            "content": encoded,
        }
        if sha:
            payload["sha"] = sha

        response = await client.put(api_url, json=payload, headers=headers)
        response.raise_for_status()

    return response.json()["content"]["html_url"]


def _sanitize(text: str) -> str:
    """ファイル名に使えない文字を除去"""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)[:50]
