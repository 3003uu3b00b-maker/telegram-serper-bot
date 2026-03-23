import httpx
from config import SERPER_API_KEY


async def search_google(query: str, num_results: int = 5) -> list[dict]:
    """Serper APIでGoogle検索を実行し、結果を返す"""
    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "q": query,
        "num": num_results,
        "gl": "jp",
        "hl": "ja",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    results = []

    # ナレッジグラフがあれば先頭に追加
    kg = data.get("knowledgeGraph")
    if kg:
        results.append({
            "title": kg.get("title", ""),
            "link": kg.get("website", kg.get("descriptionLink", "")),
            "snippet": kg.get("description", ""),
            "source": kg.get("descriptionSource", "Knowledge Graph"),
            "date": "",
            "is_kg": True,
        })

    for item in data.get("organic", []):
        results.append({
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "source": item.get("source", ""),
            "date": item.get("date", ""),
            "is_kg": False,
        })
    return results


def format_results(results: list[dict]) -> str:
    """検索結果をTelegram用にフォーマット"""
    if not results:
        return "検索結果が見つかりませんでした。"

    lines = ["🔍 *検索結果:*\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"*{i}. {r['title']}*")
        lines.append(f"   {r['snippet']}")
        lines.append(f"   🔗 {r['link']}\n")
    return "\n".join(lines)
