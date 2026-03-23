import base64
from datetime import datetime
import httpx
from config import GITHUB_TOKEN, GITHUB_REPO

ORDERS_PATH = "orders/pending"
COMPLETED_PATH = "orders/completed"


async def save_order(order_text: str) -> str:
    """注文をGitHubのorders/pending/に保存"""
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H%M%S")
    filename = f"{timestamp}.md"
    file_path = f"{ORDERS_PATH}/{filename}"

    content = (
        f"# AI注文\n\n"
        f"- **作成日時**: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- **ステータス**: pending\n\n"
        f"## 内容\n\n"
        f"{order_text}\n"
    )

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = {
        "message": f"Order: {order_text[:50]} ({timestamp})",
        "content": encoded,
    }

    async with httpx.AsyncClient() as client:
        response = await client.put(api_url, json=payload, headers=headers)
        response.raise_for_status()

    return response.json()["content"]["html_url"]


async def list_pending_orders() -> list[dict]:
    """未処理の注文一覧を取得"""
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{ORDERS_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(api_url, headers=headers)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        files = response.json()

    orders = []
    for f in files:
        if f["name"].endswith(".md"):
            # ファイル内容を取得
            content_resp = await _get_file_content(f["download_url"])
            orders.append({
                "filename": f["name"],
                "path": f["path"],
                "sha": f["sha"],
                "content": content_resp,
                "html_url": f["html_url"],
            })
    return orders


async def complete_order(filename: str) -> str:
    """注文をpendingからcompletedに移動"""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    # pending のファイルを取得
    src_path = f"{ORDERS_PATH}/{filename}"
    src_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{src_path}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(src_url, headers=headers)
        resp.raise_for_status()
        file_data = resp.json()

        content = base64.b64decode(file_data["content"]).decode("utf-8")
        sha = file_data["sha"]

        # ステータスを更新
        content = content.replace("**ステータス**: pending", "**ステータス**: completed")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content += f"\n## 完了\n\n- **完了日時**: {now}\n"

        # completedに保存
        dst_path = f"{COMPLETED_PATH}/{filename}"
        dst_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{dst_path}"
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        await client.put(dst_url, json={
            "message": f"Complete: {filename}",
            "content": encoded,
        }, headers=headers)

        # pendingから削除
        await client.delete(src_url, json={
            "message": f"Done: {filename}",
            "sha": sha,
        }, headers=headers)

    return dst_path


async def _get_file_content(download_url: str) -> str:
    """ファイルの内容をダウンロード"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(download_url)
        return resp.text
