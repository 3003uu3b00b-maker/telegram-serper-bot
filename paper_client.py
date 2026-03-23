import httpx
import xml.etree.ElementTree as ET
from config import SERPER_API_KEY


async def search_openalex(query: str, num_results: int = 5) -> list[dict]:
    """OpenAlex APIで論文検索（無料・キー不要）"""
    url = "https://api.openalex.org/works"
    params = {
        "search": query,
        "per_page": num_results,
        "mailto": "bot@example.com",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for work in data.get("results", []):
        # abstract は inverted index 形式 → テキストに変換
        abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))

        authors = work.get("authorships", [])
        author_names = ", ".join(
            a.get("author", {}).get("display_name", "") for a in authors[:3]
        )
        if len(authors) > 3:
            author_names += f" 他{len(authors) - 3}名"

        pdf_url = ""
        oa = work.get("open_access", {})
        if oa.get("oa_url"):
            pdf_url = oa["oa_url"]

        results.append({
            "title": work.get("title", ""),
            "abstract": abstract,
            "authors": author_names,
            "year": work.get("publication_year", ""),
            "citations": work.get("cited_by_count", 0),
            "venue": work.get("primary_location", {}).get("source", {}).get("display_name", "") if work.get("primary_location") else "",
            "url": work.get("doi", work.get("id", "")),
            "pdf_url": pdf_url,
            "source": "OpenAlex",
        })

    return results


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """OpenAlexのinverted index形式のabstractをテキストに変換"""
    if not inverted_index:
        return ""
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(word for _, word in word_positions)


async def search_arxiv(query: str, num_results: int = 5) -> list[dict]:
    """arXiv APIで論文検索（無料・キー不要）"""
    url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": num_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        xml_text = resp.text

    # XML パース
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_text)

    results = []
    for entry in root.findall("atom:entry", ns):
        title = entry.find("atom:title", ns)
        summary = entry.find("atom:summary", ns)
        published = entry.find("atom:published", ns)
        arxiv_id = entry.find("atom:id", ns)

        authors = []
        for author in entry.findall("atom:author", ns):
            name = author.find("atom:name", ns)
            if name is not None:
                authors.append(name.text)

        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += f" 他{len(authors) - 3}名"

        year = ""
        if published is not None and published.text:
            year = published.text[:4]

        paper_id = ""
        pdf_url = ""
        if arxiv_id is not None and arxiv_id.text:
            paper_id = arxiv_id.text
            # arXiv PDF URL
            aid = arxiv_id.text.split("/abs/")[-1] if "/abs/" in arxiv_id.text else arxiv_id.text.split("/")[-1]
            pdf_url = f"https://arxiv.org/pdf/{aid}"

        results.append({
            "title": title.text.strip().replace("\n", " ") if title is not None else "",
            "abstract": summary.text.strip().replace("\n", " ")[:500] if summary is not None else "",
            "authors": author_str,
            "year": year,
            "citations": 0,
            "venue": "arXiv",
            "url": paper_id,
            "pdf_url": pdf_url,
            "source": "arXiv",
        })

    return results


async def search_google_scholar(query: str, num_results: int = 5) -> list[dict]:
    """Serper API経由でGoogle Scholar検索"""
    url = "https://google.serper.dev/scholar"
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "q": query,
        "num": num_results,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("organic", []):
        pub_info = item.get("publicationInfo", {})
        results.append({
            "title": item.get("title", ""),
            "abstract": item.get("snippet", ""),
            "authors": pub_info.get("authors", [""]) if isinstance(pub_info.get("authors"), list) else pub_info.get("summary", ""),
            "year": item.get("year", ""),
            "citations": item.get("citedBy", {}).get("total", 0) if isinstance(item.get("citedBy"), dict) else 0,
            "venue": pub_info.get("summary", ""),
            "url": item.get("link", ""),
            "pdf_url": item.get("resources", [{}])[0].get("link", "") if item.get("resources") else "",
            "source": "Google Scholar",
        })

    return results


async def search_all_papers(query: str) -> dict[str, list[dict]]:
    """3つのソースから同時に論文検索"""
    import asyncio

    results = {"openalex": [], "arxiv": [], "scholar": []}

    async def _search_openalex():
        try:
            results["openalex"] = await search_openalex(query, 5)
        except Exception:
            pass

    async def _search_arxiv():
        try:
            results["arxiv"] = await search_arxiv(query, 3)
        except Exception:
            pass

    async def _search_scholar():
        try:
            results["scholar"] = await search_google_scholar(query, 5)
        except Exception:
            pass

    await asyncio.gather(_search_openalex(), _search_arxiv(), _search_scholar())
    return results
