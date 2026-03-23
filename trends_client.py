import httpx
from google import genai
from config import SERPER_API_KEY, GEMINI_API_KEY


async def get_trending_searches_japan() -> list[dict]:
    """Googleトレンド急上昇ワード（日本）をSerper API経由で取得"""
    # Serper APIのGoogle検索で「急上昇ワード」を取得
    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "q": "Google トレンド 急上昇 今日",
        "gl": "jp",
        "hl": "ja",
        "num": 10,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("organic", []):
        results.append({
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })

    return results


async def get_realtime_trends() -> list[dict]:
    """Google Trends RSS経由でリアルタイムトレンドを取得"""
    url = "https://trends.google.co.jp/trending/rss?geo=JP"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        xml_text = resp.text

    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_text)

    trends = []
    # RSS のアイテムを解析
    for item in root.findall("./channel/item"):
        title = item.find("title")
        link = item.find("link")
        # ht:approx_traffic
        traffic = item.find("{https://trends.google.co.jp/trends/trendingsearches/daily}approx_traffic")
        pub_date = item.find("pubDate")

        # 関連ニュース
        news_items = item.findall("{https://trends.google.co.jp/trends/trendingsearches/daily}news_item")
        news = []
        for ni in news_items:
            news_title = ni.find("{https://trends.google.co.jp/trends/trendingsearches/daily}news_item_title")
            news_url = ni.find("{https://trends.google.co.jp/trends/trendingsearches/daily}news_item_url")
            news_source = ni.find("{https://trends.google.co.jp/trends/trendingsearches/daily}news_item_source")
            if news_title is not None:
                news.append({
                    "title": news_title.text or "",
                    "url": news_url.text if news_url is not None else "",
                    "source": news_source.text if news_source is not None else "",
                })

        trends.append({
            "keyword": title.text if title is not None else "",
            "link": link.text if link is not None else "",
            "traffic": traffic.text if traffic is not None else "",
            "date": pub_date.text if pub_date is not None else "",
            "news": news[:3],  # 関連ニュース最大3件
        })

    return trends[:20]  # 最大20件


async def generate_matome(trends: list[dict]) -> str:
    """Gemini APIでトレンドまとめを生成"""
    client = genai.Client(api_key=GEMINI_API_KEY)

    trends_text = ""
    for i, t in enumerate(trends[:15], 1):
        trends_text += f"{i}. {t['keyword']}"
        if t.get("traffic"):
            trends_text += f"（検索数: {t['traffic']}）"
        trends_text += "\n"
        for n in t.get("news", []):
            trends_text += f"   - {n['title']}（{n['source']}）\n"

    prompt = (
        f"以下は本日のGoogleトレンド急上昇ワード（日本）です。\n\n"
        f"{trends_text}\n\n"
        f"これらのトレンドを分析し、以下のフォーマットでまとめてください：\n\n"
        f"## 本日のトレンドまとめ\n\n"
        f"### カテゴリ別整理\n"
        f"（ニュース、エンタメ、スポーツ、テクノロジー等に分類）\n\n"
        f"### 注目トピック TOP5\n"
        f"（各トピックについて2-3行で解説）\n\n"
        f"### ビジネス視点での考察\n"
        f"（ビジネスや起業に活かせるインサイト）"
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )

    return response.text
