import httpx
from google import genai
from config import SERPER_API_KEY, GEMINI_API_KEY


async def search_youtube(query: str, num_results: int = 5) -> list[dict]:
    """Serper APIでYouTube検索"""
    url = "https://google.serper.dev/videos"
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
    for item in data.get("videos", []):
        results.append({
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "channel": item.get("channel", ""),
            "date": item.get("date", ""),
            "duration": item.get("duration", ""),
        })
    return results


async def summarize_youtube(url: str, title: str) -> str:
    """Gemini APIでYouTube動画を要約"""
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = (
        f"以下のYouTube動画を詳しく要約してください。\n"
        f"動画タイトル: {title}\n"
        f"動画URL: {url}\n\n"
        f"要約のフォーマット:\n"
        f"## 概要\n"
        f"（動画の全体的な内容を3-5行で）\n\n"
        f"## 主なポイント\n"
        f"（箇条書きで5-10個）\n\n"
        f"## まとめ\n"
        f"（結論・重要な学び）"
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )

    return response.text
