import httpx


async def geocode(place_name: str) -> dict | None:
    """地名から緯度経度を取得（Nominatim/OpenStreetMap）"""
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": place_name,
        "format": "json",
        "limit": 1,
        "accept-language": "ja",
    }
    headers = {"User-Agent": "TelegramSearchBot/1.0"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    if not data:
        return None

    return {
        "name": data[0].get("display_name", place_name),
        "lat": float(data[0]["lat"]),
        "lon": float(data[0]["lon"]),
    }


async def get_plateau_buildings(lat: float, lon: float, radius_m: int = 300) -> list[dict]:
    """PLATEAU GeoJSON APIから周辺の建物情報を取得"""
    # PLATEAU VIEW の 3D Tiles APIから建物属性を取得
    # まずSerper経由でPLATEAU情報を補完し、直接APIでビル情報取得を試みる

    # PLATEAU の CityGML 属性情報API (plateau-api)
    # 緯度経度のバウンディングボックスで検索
    delta = radius_m / 111000  # 度に変換（概算）
    bbox = f"{lon - delta},{lat - delta},{lon + delta},{lat + delta}"

    # Overpass API で建物情報を取得（PLATEAU補完用）
    overpass_url = "https://overpass-api.de/api/interpreter"
    query = f"""
    [out:json][timeout:10];
    (
      way["building"](around:{radius_m},{lat},{lon});
    );
    out body 5;
    >;
    out skel qt;
    """

    buildings = []

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(overpass_url, data={"data": query})
            resp.raise_for_status()
            data = resp.json()

            for element in data.get("elements", []):
                if element.get("type") == "way" and "tags" in element:
                    tags = element["tags"]
                    building = {
                        "name": tags.get("name", "名称不明"),
                        "type": tags.get("building", "yes"),
                        "levels": tags.get("building:levels", "不明"),
                        "height": tags.get("height", "不明"),
                        "addr": tags.get("addr:full", tags.get("addr:street", "")),
                        "amenity": tags.get("amenity", ""),
                        "shop": tags.get("shop", ""),
                        "office": tags.get("office", ""),
                    }
                    buildings.append(building)
        except Exception:
            pass

    return buildings[:15]  # 最大15件


async def get_area_info(lat: float, lon: float) -> dict:
    """周辺エリアの概要情報を取得"""
    # Nominatim reverse geocoding でエリア情報取得
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "zoom": 16,
        "accept-language": "ja",
    }
    headers = {"User-Agent": "TelegramSearchBot/1.0"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    address = data.get("address", {})
    return {
        "display_name": data.get("display_name", ""),
        "city": address.get("city", address.get("town", address.get("village", ""))),
        "suburb": address.get("suburb", address.get("neighbourhood", "")),
        "road": address.get("road", ""),
        "postcode": address.get("postcode", ""),
    }


def format_plateau_results(location: dict, area: dict, buildings: list[dict]) -> str:
    """PLATEAU結果をTelegram用にフォーマット"""
    lines = [
        f"🏙 *PLATEAU 都市情報*",
        f"📍 {location['name']}",
        f"🗺 緯度: {location['lat']:.6f} / 経度: {location['lon']:.6f}",
        "",
    ]

    if area.get("suburb") or area.get("road"):
        lines.append(f"📮 {area.get('suburb', '')} {area.get('road', '')}")
    if area.get("postcode"):
        lines.append(f"〒 {area['postcode']}")
    lines.append("")

    # PLATEAU VIEW リンク
    view_url = f"https://plateauview.mlit.go.jp/?lng={location['lon']}&lat={location['lat']}&z=16"
    lines.append(f"🔗 PLATEAU VIEW: {view_url}")
    lines.append("")

    if buildings:
        lines.append(f"🏢 *周辺の建物情報（{len(buildings)}件）*")
        lines.append("")

        for i, b in enumerate(buildings, 1):
            name = b["name"]
            btype = _translate_building_type(b["type"])
            details = []
            if b["levels"] != "不明":
                details.append(f"{b['levels']}階")
            if b["height"] != "不明":
                details.append(f"高さ{b['height']}m")
            if b["amenity"]:
                details.append(_translate_amenity(b["amenity"]))
            if b["shop"]:
                details.append(f"店舗({b['shop']})")
            if b["office"]:
                details.append(f"オフィス({b['office']})")

            detail_str = " | ".join(details) if details else ""
            lines.append(f"  {i}. {name} [{btype}]")
            if detail_str:
                lines.append(f"     {detail_str}")
    else:
        lines.append("建物情報が見つかりませんでした。")

    return "\n".join(lines)


def _translate_building_type(btype: str) -> str:
    types = {
        "yes": "建物",
        "residential": "住宅",
        "commercial": "商業",
        "retail": "小売",
        "office": "オフィス",
        "industrial": "工業",
        "apartments": "マンション",
        "house": "一戸建て",
        "school": "学校",
        "university": "大学",
        "hospital": "病院",
        "hotel": "ホテル",
        "church": "教会",
        "temple": "寺院",
        "shrine": "神社",
        "train_station": "駅",
        "parking": "駐車場",
        "warehouse": "倉庫",
    }
    return types.get(btype, btype)


def _translate_amenity(amenity: str) -> str:
    amenities = {
        "restaurant": "レストラン",
        "cafe": "カフェ",
        "bank": "銀行",
        "hospital": "病院",
        "pharmacy": "薬局",
        "school": "学校",
        "parking": "駐車場",
        "post_office": "郵便局",
        "library": "図書館",
        "police": "警察署",
        "fire_station": "消防署",
    }
    return amenities.get(amenity, amenity)
