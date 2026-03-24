import os
import tempfile
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from config import TELEGRAM_BOT_TOKEN
from serper_client import search_google, format_results
from tts_client import text_to_mp3
from github_client import save_to_github
from youtube_client import search_youtube, summarize_youtube
from order_client import save_order, list_pending_orders
from plateau_client import geocode, get_plateau_buildings, get_area_info, format_plateau_results
from paper_client import search_all_papers
from trends_client import get_realtime_trends, generate_matome

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """起動メッセージ"""
    await update.message.reply_text(
        "🤖 検索Botへようこそ!\n\n"
        "使い方:\n"
        "/search キーワード — Google検索\n"
        "/youtube キーワード — YouTube検索+要約\n"
        "/plateau 場所名 — 都市情報を表示\n"
        "/paper キーワード — 論文検索\n"
        "/trends — Googleトレンド急上昇ワード\n"
        "/matome — トレンドをAI分析してまとめ\n"
        "/order 内容 — AIへの注文を登録\n"
        "/orders — 未処理の注文一覧\n\n"
        "テキスト貼り付けでGitHub保存・MP3化も可能。"
    )


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Google検索を実行"""
    if not context.args:
        await update.message.reply_text("使い方: /search キーワード")
        return

    query = " ".join(context.args)
    await update.message.reply_text(f"🔍 「{query}」を検索中...")

    try:
        results = await search_google(query)
    except Exception as e:
        await update.message.reply_text(f"検索エラー: {e}")
        return

    if not results:
        await update.message.reply_text("検索結果が見つかりませんでした。")
        return

    # 検索結果をコンテキストに保存
    context.user_data["search_results"] = results

    # 各結果にボタンを付けてリッチ表示
    for i, r in enumerate(results):
        # ナレッジグラフ or 通常結果で表示を変える
        if r.get("is_kg"):
            icon = "📚"
            label = "Knowledge Graph"
        else:
            icon = f"🔍"
            label = f"検索結果 {i+1}"

        lines = [f"*{icon} {label}*"]
        lines.append(f"*{_escape_md(r['title'])}*")

        # ソース名 + 日付
        meta = []
        if r.get("source"):
            meta.append(r["source"])
        if r.get("date"):
            meta.append(r["date"])
        if meta:
            lines.append(f"📰 {_escape_md(' | '.join(meta))}")

        lines.append("")
        lines.append(f"{_escape_md(r['snippet'])}")
        lines.append("")
        lines.append(f"🔗 {r['link']}")

        text = "\n".join(lines)

        keyboard = [
            [
                InlineKeyboardButton("📄 詳細抽出", callback_data=f"detail_{i}"),
            ],
            [
                InlineKeyboardButton("🎵 MP3にする", callback_data=f"mp3_{i}"),
                InlineKeyboardButton("📁 GitHubに保存", callback_data=f"github_{i}"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=reply_markup
        )


async def youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """YouTube検索を実行"""
    if not context.args:
        await update.message.reply_text("使い方: /youtube キーワード")
        return

    query_text = " ".join(context.args)
    await update.message.reply_text(f"🎬 「{query_text}」をYouTubeで検索中...")

    try:
        results = await search_youtube(query_text)
    except Exception as e:
        await update.message.reply_text(f"検索エラー: {e}")
        return

    if not results:
        await update.message.reply_text("動画が見つかりませんでした。")
        return

    context.user_data["youtube_results"] = results

    for i, r in enumerate(results):
        lines = [f"*🎬 動画 {i+1}*"]
        lines.append(f"*{_escape_md(r['title'])}*")

        meta = []
        if r.get("channel"):
            meta.append(r["channel"])
        if r.get("duration"):
            meta.append(r["duration"])
        if r.get("date"):
            meta.append(r["date"])
        if meta:
            lines.append(f"📺 {_escape_md(' | '.join(meta))}")

        if r.get("snippet"):
            lines.append("")
            lines.append(_escape_md(r["snippet"]))

        lines.append("")
        lines.append(f"🔗 {r['link']}")

        keyboard = [
            [
                InlineKeyboardButton("📝 要約する", callback_data=f"ytsummary_{i}"),
                InlineKeyboardButton("🎵 MP3にする", callback_data=f"ytmp3_{i}"),
            ],
            [
                InlineKeyboardButton("📁 GitHubに保存", callback_data=f"ytgithub_{i}"),
            ],
        ]

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def plateau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """PLATEAU都市情報を表示"""
    if not context.args:
        await update.message.reply_text(
            "使い方: /plateau 場所名\n\n"
            "例:\n"
            "/plateau 東京駅\n"
            "/plateau 渋谷スクランブル交差点\n"
            "/plateau 大阪城"
        )
        return

    place = " ".join(context.args)
    await update.message.reply_text(f"🏙 「{place}」の都市情報を取得中...")

    try:
        # 地名→緯度経度
        location = await geocode(place)
        if not location:
            await update.message.reply_text(f"❌ 「{place}」の場所が見つかりませんでした。")
            return

        # エリア情報と建物情報を取得
        area = await get_area_info(location["lat"], location["lon"])
        buildings = await get_plateau_buildings(location["lat"], location["lon"])

        # フォーマットして送信
        result_text = format_plateau_results(location, area, buildings)

        # コンテキストに保存
        context.user_data["plateau_data"] = {
            "location": location,
            "area": area,
            "buildings": buildings,
            "text": result_text,
        }

        keyboard = [
            [
                InlineKeyboardButton("📁 GitHubに保存", callback_data="plateau_github"),
                InlineKeyboardButton("🎵 MP3にする", callback_data="plateau_mp3"),
            ],
            [
                InlineKeyboardButton("🔍 この場所をGoogle検索", callback_data="plateau_search"),
            ],
        ]

        await update.message.reply_text(
            result_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        logger.error(f"PLATEAUエラー: {e}")
        await update.message.reply_text(f"❌ エラー: {e}")


async def paper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """論文検索（OpenAlex + arXiv + Google Scholar 同時検索）"""
    if not context.args:
        await update.message.reply_text(
            "使い方: /paper キーワード\n\n"
            "例:\n"
            "/paper 3D city model urban planning\n"
            "/paper PLATEAU digital twin\n"
            "/paper 深層学習 都市計画"
        )
        return

    query_text = " ".join(context.args)
    await update.message.reply_text(
        f"📚 「{query_text}」を3つのソースで同時検索中...\n"
        f"  - OpenAlex（学術論文2.5億件）\n"
        f"  - arXiv（プレプリント）\n"
        f"  - Google Scholar"
    )

    try:
        all_results = await search_all_papers(query_text)
    except Exception as e:
        await update.message.reply_text(f"検索エラー: {e}")
        return

    # 全ソースの結果を統合してフラットリストに
    combined = []
    source_icons = {"OpenAlex": "📗", "arXiv": "📙", "Google Scholar": "📘"}

    for source_key, icon_label in [("openalex", "OpenAlex"), ("arxiv", "arXiv"), ("scholar", "Google Scholar")]:
        papers = all_results.get(source_key, [])
        if papers:
            await update.message.reply_text(f"{source_icons[icon_label]} *{icon_label}* — {len(papers)}件", parse_mode="Markdown")

        for p in papers:
            combined.append(p)
            idx = len(combined) - 1

            lines = [f"*{source_icons.get(p.get('source', ''), '📄')} {_escape_md(p['title'])}*"]

            meta = []
            if p.get("authors"):
                authors_str = p["authors"] if isinstance(p["authors"], str) else ", ".join(p["authors"][:3])
                meta.append(authors_str)
            if p.get("year"):
                meta.append(str(p["year"]))
            if p.get("venue"):
                meta.append(p["venue"])
            if meta:
                lines.append(f"👤 {_escape_md(' | '.join(meta))}")

            if p.get("citations"):
                lines.append(f"📊 被引用数: {p['citations']}")

            if p.get("abstract"):
                abstract = p["abstract"][:300] + ("..." if len(p["abstract"]) > 300 else "")
                lines.append("")
                lines.append(_escape_md(abstract))

            lines.append("")
            if p.get("url"):
                lines.append(f"🔗 {p['url']}")
            if p.get("pdf_url"):
                lines.append(f"📎 PDF: {p['pdf_url']}")

            keyboard = [
                [
                    InlineKeyboardButton("📁 GitHubに保存", callback_data=f"papergithub_{idx}"),
                    InlineKeyboardButton("🎵 要旨をMP3", callback_data=f"papermp3_{idx}"),
                ],
            ]

            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    context.user_data["paper_results"] = combined

    total = len(combined)
    if total == 0:
        await update.message.reply_text("論文が見つかりませんでした。")
    else:
        await update.message.reply_text(f"合計 {total} 件の論文が見つかりました。")


async def trends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Googleトレンド急上昇ワードを表示"""
    await update.message.reply_text("🔥 Googleトレンド急上昇ワードを取得中...")

    try:
        trend_list = await get_realtime_trends()
    except Exception as e:
        await update.message.reply_text(f"❌ トレンド取得エラー: {e}")
        return

    if not trend_list:
        await update.message.reply_text("トレンドが取得できませんでした。")
        return

    context.user_data["trends"] = trend_list

    # トレンド一覧を送信
    lines = ["🔥 *Googleトレンド急上昇ワード（日本）*\n"]

    for i, t in enumerate(trend_list[:20], 1):
        keyword = _escape_md(t["keyword"])
        traffic = f" （{t['traffic']}）" if t.get("traffic") else ""
        lines.append(f"*{i}\\. {keyword}*{_escape_md(traffic)}")

        for n in t.get("news", [])[:2]:
            lines.append(f"   📰 {_escape_md(n['title'])}")
            if n.get("source"):
                lines.append(f"      — {_escape_md(n['source'])}")
        lines.append("")

    # 分割送信（4096文字制限）
    text = "\n".join(lines)
    if len(text) > 4000:
        mid = len(lines) // 2
        await update.message.reply_text("\n".join(lines[:mid]), parse_mode="Markdown")
        await update.message.reply_text("\n".join(lines[mid:]), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

    keyboard = [
        [
            InlineKeyboardButton("📝 AIまとめ生成", callback_data="trends_matome"),
            InlineKeyboardButton("📁 GitHubに保存", callback_data="trends_github"),
        ],
        [
            InlineKeyboardButton("🎵 MP3にする", callback_data="trends_mp3"),
        ],
    ]
    await update.message.reply_text(
        "このトレンドをどうしますか？",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def matome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """今日のTelegram記事+トレンドをAIまとめ生成"""
    await update.message.reply_text("📝 本日の情報を収集中...")

    # 1. GitHubから今日の保存記事を取得
    today_articles = ""
    try:
        today_articles = await _fetch_today_articles()
        if today_articles:
            await update.message.reply_text(f"📄 今日の保存記事を取得しました")
    except Exception as e:
        logger.error(f"GitHub記事取得エラー: {e}")

    # 2. トレンドも取得
    trend_list = []
    try:
        trend_list = await get_realtime_trends()
        if trend_list:
            await update.message.reply_text(f"🔥 トレンド {len(trend_list)} 件を取得")
    except Exception as e:
        logger.error(f"トレンド取得エラー: {e}")

    if not today_articles and not trend_list:
        await update.message.reply_text("❌ まとめる情報がありません。記事を保存するか、/trendsでトレンドを確認してください。")
        return

    context.user_data["trends"] = trend_list

    await update.message.reply_text("🤖 Gemini AIでまとめを生成中...")

    try:
        summary = await _generate_daily_matome(today_articles, trend_list)
        context.user_data["matome_text"] = summary

        # 分割送信
        header = "📝 *本日のまとめ*\n\n"
        chunks = []
        remaining = summary
        while remaining:
            chunk = remaining[:3900]
            remaining = remaining[3900:]
            chunks.append(chunk)

        await update.message.reply_text(header + _escape_md(chunks[0]), parse_mode="Markdown")
        for chunk in chunks[1:]:
            await update.message.reply_text(_escape_md(chunk), parse_mode="Markdown")

        keyboard = [
            [
                InlineKeyboardButton("📁 GitHubに保存", callback_data="matome_github"),
                InlineKeyboardButton("🎵 MP3にする", callback_data="matome_mp3"),
            ],
        ]
        await update.message.reply_text(
            "このまとめをどうしますか？",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        logger.error(f"まとめ生成エラー: {e}")
        await update.message.reply_text(f"❌ まとめ生成エラー: {e}")


async def order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AIへの注文を登録"""
    if not context.args:
        await update.message.reply_text(
            "使い方: /order やりたいこと\n\n"
            "例: /order Kindle本のOCRスクリプトを改善して"
        )
        return

    order_text = " ".join(context.args)
    await update.message.reply_text(f"📋 注文を登録中...\n「{order_text}」")

    try:
        html_url = await save_order(order_text)
        await update.message.reply_text(
            f"✅ 注文を登録しました!\n\n"
            f"📋 {order_text}\n"
            f"🔗 {html_url}\n\n"
            f"Claude Codeが後で実行します。"
        )
    except Exception as e:
        logger.error(f"注文登録エラー: {e}")
        await update.message.reply_text(f"❌ 注文登録エラー: {e}")


async def orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """未処理の注文一覧を表示"""
    await update.message.reply_text("📋 未処理の注文を確認中...")

    try:
        pending = await list_pending_orders()
        if not pending:
            await update.message.reply_text("✅ 未処理の注文はありません。")
            return

        for o in pending:
            text = (
                f"📋 *{_escape_md(o['filename'])}*\n\n"
                f"{_escape_md(o['content'][:500])}\n\n"
                f"🔗 {o['html_url']}"
            )
            await update.message.reply_text(text, parse_mode="Markdown")

        await update.message.reply_text(f"合計 {len(pending)} 件の未処理注文があります。")

    except Exception as e:
        logger.error(f"注文一覧エラー: {e}")
        await update.message.reply_text(f"❌ エラー: {e}")


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """スラッシュコマンド以外のテキストメッセージを処理"""
    text = update.message.text
    if not text or len(text.strip()) < 5:
        return

    # テキストを保存
    context.user_data["pasted_text"] = text

    # プレビュー表示（先頭200文字）
    preview = text[:200] + ("..." if len(text) > 200 else "")

    keyboard = [
        [
            InlineKeyboardButton("📁 GitHubに保存", callback_data="paste_github"),
            InlineKeyboardButton("🎵 MP3にする", callback_data="paste_mp3"),
        ]
    ]

    await update.message.reply_text(
        f"📋 テキストを受け取りました（{len(text)}文字）\n\n"
        f"どうしますか？",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ボタン押下時の処理"""
    query = update.callback_query
    await query.answer()

    data = query.data

    # トレンド系
    if data == "trends_matome":
        trend_list = context.user_data.get("trends", [])
        if trend_list:
            await query.edit_message_text("📝 AIまとめ生成中...")
            try:
                summary = await generate_matome(trend_list)
                context.user_data["matome_text"] = summary
                await query.edit_message_text("✅ まとめ生成完了")
                chunks = [summary[i:i+3900] for i in range(0, len(summary), 3900)]
                for chunk in chunks:
                    await query.message.reply_text(chunk)
                keyboard = [[
                    InlineKeyboardButton("📁 GitHubに保存", callback_data="matome_github"),
                    InlineKeyboardButton("🎵 MP3にする", callback_data="matome_mp3"),
                ]]
                await query.message.reply_text("このまとめをどうしますか？", reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception as e:
                await query.edit_message_text(f"❌ まとめエラー: {e}")
        return
    elif data == "trends_github":
        trend_list = context.user_data.get("trends", [])
        if trend_list:
            text = "# Googleトレンド急上昇ワード\n\n"
            for i, t in enumerate(trend_list, 1):
                text += f"## {i}. {t['keyword']}\n"
                if t.get("traffic"):
                    text += f"- 検索数: {t['traffic']}\n"
                for n in t.get("news", []):
                    text += f"- {n['title']}（{n['source']}）\n"
                text += "\n"
            try:
                html_url = await save_to_github(title="[トレンド] Google急上昇ワード", url="https://trends.google.co.jp/trending?geo=JP", snippet=text)
                await query.edit_message_text(f"✅ トレンドをGitHubに保存!\n🔗 {html_url}")
            except Exception as e:
                await query.edit_message_text(f"❌ 保存エラー: {e}")
        return
    elif data == "trends_mp3":
        trend_list = context.user_data.get("trends", [])
        if trend_list:
            try:
                await query.edit_message_text("🎵 トレンドMP3生成中...")
                text = "本日のGoogleトレンド急上昇ワードです。\n"
                for i, t in enumerate(trend_list[:10], 1):
                    text += f"{i}位、{t['keyword']}。"
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    mp3_path = tmp.name
                await text_to_mp3(text, mp3_path)
                with open(mp3_path, "rb") as af:
                    await query.message.reply_audio(audio=af, title="Googleトレンド急上昇ワード")
                await query.edit_message_text("✅ MP3生成完了")
                os.remove(mp3_path)
            except Exception as e:
                await query.edit_message_text(f"❌ MP3エラー: {e}")
        return
    elif data == "matome_github":
        matome_text = context.user_data.get("matome_text", "")
        if matome_text:
            try:
                html_url = await save_to_github(title="[まとめ] 本日のトレンド分析", url="https://trends.google.co.jp/trending?geo=JP", snippet=matome_text)
                await query.edit_message_text(f"✅ まとめをGitHubに保存!\n🔗 {html_url}")
            except Exception as e:
                await query.edit_message_text(f"❌ 保存エラー: {e}")
        return
    elif data == "matome_mp3":
        matome_text = context.user_data.get("matome_text", "")
        if matome_text:
            try:
                await query.edit_message_text("🎵 まとめMP3生成中...")
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    mp3_path = tmp.name
                await text_to_mp3(matome_text, mp3_path)
                with open(mp3_path, "rb") as af:
                    await query.message.reply_audio(audio=af, title="トレンドまとめ")
                await query.edit_message_text("✅ MP3生成完了")
                os.remove(mp3_path)
            except Exception as e:
                await query.edit_message_text(f"❌ MP3エラー: {e}")
        return

    # PLATEAU系
    if data == "plateau_github":
        pdata = context.user_data.get("plateau_data", {})
        if pdata:
            try:
                html_url = await save_to_github(
                    title=f"[PLATEAU] {pdata['location']['name'][:50]}",
                    url=f"https://plateauview.mlit.go.jp/?lng={pdata['location']['lon']}&lat={pdata['location']['lat']}&z=16",
                    snippet=pdata["text"],
                )
                await query.edit_message_text(f"✅ PLATEAUデータをGitHubに保存しました!\n🔗 {html_url}")
            except Exception as e:
                await query.edit_message_text(f"❌ 保存エラー: {e}")
        return
    elif data == "plateau_mp3":
        pdata = context.user_data.get("plateau_data", {})
        if pdata:
            try:
                await query.edit_message_text("🎵 MP3生成中...")
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    mp3_path = tmp.name
                await text_to_mp3(pdata["text"], mp3_path)
                with open(mp3_path, "rb") as af:
                    await query.message.reply_audio(audio=af, title=f"PLATEAU {pdata['location']['name'][:30]}")
                await query.edit_message_text("✅ MP3生成完了")
                os.remove(mp3_path)
            except Exception as e:
                await query.edit_message_text(f"❌ MP3エラー: {e}")
        return
    elif data == "plateau_search":
        pdata = context.user_data.get("plateau_data", {})
        if pdata:
            context.args = [pdata["location"]["name"]]
            await search(Update(update.update_id, callback_query=query), context)
        return

    # 論文系
    if data.startswith("papergithub_"):
        idx = int(data.split("_")[1])
        papers = context.user_data.get("paper_results", [])
        if idx < len(papers):
            p = papers[idx]
            try:
                html_url = await save_to_github(
                    title=f"[論文] {p['title'][:50]}",
                    url=p.get("url", ""),
                    snippet=f"著者: {p['authors']}\n年: {p.get('year','')}\n被引用: {p.get('citations',0)}\n\n{p.get('abstract','')}",
                )
                await query.edit_message_text(f"✅ 論文情報をGitHubに保存!\n🔗 {html_url}")
            except Exception as e:
                await query.edit_message_text(f"❌ 保存エラー: {e}")
        return
    elif data.startswith("papermp3_"):
        idx = int(data.split("_")[1])
        papers = context.user_data.get("paper_results", [])
        if idx < len(papers):
            p = papers[idx]
            try:
                await query.edit_message_text("🎵 論文要旨→MP3生成中...")
                text = f"{p['title']}。{p.get('abstract', '')}"
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    mp3_path = tmp.name
                await text_to_mp3(text, mp3_path)
                with open(mp3_path, "rb") as af:
                    await query.message.reply_audio(audio=af, title=p["title"][:50])
                await query.edit_message_text("✅ MP3生成完了")
                os.remove(mp3_path)
            except Exception as e:
                await query.edit_message_text(f"❌ MP3エラー: {e}")
        return

    # テキスト貼り付け系
    if data == "paste_github":
        await _handle_paste_github(query, context)
        return
    elif data == "paste_mp3":
        await _handle_paste_mp3(query, context)
        return

    # YouTube要約のGitHub保存 / MP3
    if data == "ytsave_summary":
        await _handle_yt_save_github(query, context)
        return
    elif data == "ytsave_mp3":
        await _handle_yt_save_mp3(query, context)
        return

    # YouTube系ボタン
    if data.startswith("ytsummary_"):
        idx = int(data.split("_")[1])
        results = context.user_data.get("youtube_results", [])
        if idx < len(results):
            await _handle_yt_summary(query, results[idx], context)
        return
    elif data.startswith("ytmp3_"):
        idx = int(data.split("_")[1])
        results = context.user_data.get("youtube_results", [])
        if idx < len(results):
            await _handle_yt_mp3(query, results[idx])
        return
    elif data.startswith("ytgithub_"):
        idx = int(data.split("_")[1])
        results = context.user_data.get("youtube_results", [])
        if idx < len(results):
            await _handle_github(query, results[idx])
        return

    # 通常の検索結果ボタン
    results = context.user_data.get("search_results", [])

    # インデックス取得
    action, idx_str = data.rsplit("_", 1)
    idx = int(idx_str)

    if idx >= len(results):
        await query.edit_message_text("検索結果の有効期限が切れました。再度検索してください。")
        return

    article = results[idx]

    if action == "detail":
        await _handle_detail(query, article, idx)
    elif action == "mp3":
        await _handle_mp3(query, article)
    elif action == "github":
        await _handle_github(query, article)


async def _handle_detail(query, article: dict, idx: int):
    """記事のテキストを抽出してTelegramに送信"""
    await query.edit_message_text(f"📄 記事を抽出中...\n{article['title']}")

    try:
        article_text = await _fetch_article_text(article["link"])

        if not article_text:
            await query.edit_message_text(f"❌ テキストを取得できませんでした:\n{article['link']}")
            return

        # Telegramメッセージは4096文字制限 → 分割送信
        header = f"📄 *{_escape_md(article['title'])}*\n🔗 {article['link']}\n\n"
        max_len = 4000 - len(header)
        text_chunk = article_text[:max_len]

        await query.edit_message_text(f"✅ 抽出完了: {article['title']}")

        # 本文を送信
        await query.message.reply_text(header + _escape_md(text_chunk), parse_mode="Markdown")

        # 残りがあれば続きも送信
        remaining = article_text[max_len:]
        while remaining:
            chunk = remaining[:4000]
            remaining = remaining[4000:]
            await query.message.reply_text(chunk)

        # 抽出後のアクションボタン
        keyboard = [
            [
                InlineKeyboardButton("🎵 この内容をMP3にする", callback_data=f"mp3_{idx}"),
                InlineKeyboardButton("📁 GitHubに保存", callback_data=f"github_{idx}"),
            ]
        ]
        await query.message.reply_text(
            "この記事をどうしますか？",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        logger.error(f"詳細抽出エラー: {e}")
        await query.edit_message_text(f"❌ 抽出エラー: {e}")


async def _handle_mp3(query, article: dict):
    """記事内容を取得してMP3に変換"""
    await query.edit_message_text(f"🎵 MP3を生成中...\n{article['title']}")

    try:
        # 記事のテキストを取得
        article_text = await _fetch_article_text(article["link"])
        text_for_tts = f"{article['title']}。{article_text}"

        # MP3を生成
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            mp3_path = tmp.name

        await text_to_mp3(text_for_tts, mp3_path)

        # Telegramに音声送信
        with open(mp3_path, "rb") as audio_file:
            await query.message.reply_audio(
                audio=audio_file,
                title=article["title"],
                caption=f"🎵 {article['title']}",
            )

        await query.edit_message_text(f"✅ MP3生成完了: {article['title']}")

    except Exception as e:
        logger.error(f"MP3生成エラー: {e}")
        await query.edit_message_text(f"❌ MP3生成エラー: {e}")
    finally:
        if os.path.exists(mp3_path):
            os.remove(mp3_path)


async def _handle_github(query, article: dict):
    """記事をGitHubに保存"""
    await query.edit_message_text(f"📁 GitHubに保存中...\n{article['title']}")

    try:
        html_url = await save_to_github(
            title=article["title"],
            url=article["link"],
            snippet=article["snippet"],
        )
        await query.edit_message_text(
            f"✅ GitHubに保存しました!\n\n"
            f"📄 {article['title']}\n"
            f"🔗 {html_url}"
        )
    except Exception as e:
        logger.error(f"GitHub保存エラー: {e}")
        await query.edit_message_text(f"❌ GitHub保存エラー: {e}")


async def _handle_yt_summary(query, video: dict, context=None):
    """YouTube動画をGeminiで要約"""
    await query.edit_message_text(f"📝 動画を要約中...\n{video['title']}")

    try:
        summary = await summarize_youtube(video["link"], video["title"])

        # 要約をコンテキストに保存（GitHub保存用）
        if context:
            context.user_data["last_yt_summary"] = {
                "title": video["title"],
                "link": video["link"],
                "summary": summary,
            }

        header = f"📝 *{_escape_md(video['title'])}*\n🔗 {video['link']}\n\n"

        # 4096文字制限対応
        max_len = 4000 - len(header)
        summary_chunk = summary[:max_len]

        await query.edit_message_text(f"✅ 要約完了: {video['title']}")
        await query.message.reply_text(header + _escape_md(summary_chunk), parse_mode="Markdown")

        remaining = summary[max_len:]
        while remaining:
            chunk = remaining[:4000]
            remaining = remaining[4000:]
            await query.message.reply_text(_escape_md(chunk), parse_mode="Markdown")

        # 要約後のアクションボタン
        keyboard = [
            [
                InlineKeyboardButton("📁 要約をGitHubに保存", callback_data="ytsave_summary"),
                InlineKeyboardButton("🎵 要約をMP3にする", callback_data="ytsave_mp3"),
            ]
        ]
        await query.message.reply_text(
            "この要約をどうしますか？",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        logger.error(f"YouTube要約エラー: {e}")
        await query.edit_message_text(f"❌ 要約エラー: {e}")


async def _handle_yt_mp3(query, video: dict):
    """YouTube動画の要約をMP3に変換"""
    await query.edit_message_text(f"🎵 動画要約→MP3生成中...\n{video['title']}")

    try:
        summary = await summarize_youtube(video["link"], video["title"])
        text_for_tts = f"{video['title']}。{summary}"

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            mp3_path = tmp.name

        await text_to_mp3(text_for_tts, mp3_path)

        with open(mp3_path, "rb") as audio_file:
            await query.message.reply_audio(
                audio=audio_file,
                title=video["title"],
                caption=f"🎵 {video['title']}",
            )

        await query.edit_message_text(f"✅ MP3生成完了: {video['title']}")

    except Exception as e:
        logger.error(f"YouTube MP3エラー: {e}")
        await query.edit_message_text(f"❌ MP3生成エラー: {e}")
    finally:
        if os.path.exists(mp3_path):
            os.remove(mp3_path)


async def _handle_paste_github(query, context):
    """貼り付けテキストをGitHubに保存"""
    text = context.user_data.get("pasted_text")
    if not text:
        await query.edit_message_text("❌ テキストが見つかりません。")
        return

    await query.edit_message_text("📁 GitHubに保存中...")

    try:
        # タイトルはテキストの先頭30文字
        title = text[:30].replace("\n", " ") + ("..." if len(text) > 30 else "")
        html_url = await save_to_github(
            title=f"[メモ] {title}",
            url="",
            snippet=text,
        )
        await query.edit_message_text(
            f"✅ GitHubに保存しました!\n\n"
            f"📄 {title}\n"
            f"🔗 {html_url}"
        )
    except Exception as e:
        logger.error(f"テキスト保存エラー: {e}")
        await query.edit_message_text(f"❌ 保存エラー: {e}")


async def _handle_paste_mp3(query, context):
    """貼り付けテキストをMP3に変換"""
    text = context.user_data.get("pasted_text")
    if not text:
        await query.edit_message_text("❌ テキストが見つかりません。")
        return

    await query.edit_message_text("🎵 MP3を生成中...")

    try:
        title = text[:30].replace("\n", " ")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            mp3_path = tmp.name

        await text_to_mp3(text, mp3_path)

        with open(mp3_path, "rb") as audio_file:
            await query.message.reply_audio(
                audio=audio_file,
                title=title,
                caption=f"🎵 {title}",
            )

        await query.edit_message_text(f"✅ MP3生成完了")

    except Exception as e:
        logger.error(f"テキストMP3エラー: {e}")
        await query.edit_message_text(f"❌ MP3エラー: {e}")
    finally:
        if os.path.exists(mp3_path):
            os.remove(mp3_path)


async def _handle_yt_save_github(query, context):
    """YouTube要約をGitHubに保存"""
    yt_data = context.user_data.get("last_yt_summary")
    if not yt_data:
        await query.edit_message_text("❌ 要約データが見つかりません。再度要約してください。")
        return

    await query.edit_message_text(f"📁 要約をGitHubに保存中...")

    try:
        html_url = await save_to_github(
            title=f"[YouTube] {yt_data['title']}",
            url=yt_data["link"],
            snippet=yt_data["summary"],
        )
        await query.edit_message_text(
            f"✅ YouTube要約をGitHubに保存しました!\n\n"
            f"🎬 {yt_data['title']}\n"
            f"🔗 {html_url}"
        )
    except Exception as e:
        logger.error(f"YouTube要約GitHub保存エラー: {e}")
        await query.edit_message_text(f"❌ 保存エラー: {e}")


async def _handle_yt_save_mp3(query, context):
    """YouTube要約をMP3に変換"""
    yt_data = context.user_data.get("last_yt_summary")
    if not yt_data:
        await query.edit_message_text("❌ 要約データが見つかりません。再度要約してください。")
        return

    await query.edit_message_text(f"🎵 要約→MP3生成中...")

    try:
        text_for_tts = f"{yt_data['title']}。{yt_data['summary']}"

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            mp3_path = tmp.name

        await text_to_mp3(text_for_tts, mp3_path)

        with open(mp3_path, "rb") as audio_file:
            await query.message.reply_audio(
                audio=audio_file,
                title=yt_data["title"],
                caption=f"🎵 {yt_data['title']}",
            )

        await query.edit_message_text(f"✅ MP3生成完了: {yt_data['title']}")

    except Exception as e:
        logger.error(f"YouTube要約MP3エラー: {e}")
        await query.edit_message_text(f"❌ MP3エラー: {e}")
    finally:
        if os.path.exists(mp3_path):
            os.remove(mp3_path)


async def _fetch_article_text(url: str) -> str:
    """記事URLからテキストを取得（簡易版）"""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

        # 簡易的にHTMLタグを除去してテキスト取得
        import re
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        # 最初の3000文字を返す（TTS用）
        return text[:3000]
    except Exception:
        return ""


async def _fetch_today_articles() -> str:
    """GitHubから今日の保存記事を取得"""
    from datetime import datetime
    from config import GITHUB_TOKEN, GITHUB_REPO, GITHUB_SAVE_PATH
    import base64

    date_str = datetime.now().strftime("%Y-%m-%d")
    file_path = f"{GITHUB_SAVE_PATH}/{date_str}.md"
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(api_url, headers=headers)
        if resp.status_code == 200:
            content = base64.b64decode(resp.json()["content"]).decode("utf-8")
            return content
        else:
            return ""


async def _generate_daily_matome(articles: str, trends: list[dict]) -> str:
    """Gemini APIで今日の記事+トレンドまとめを生成"""
    import asyncio
    from google import genai
    from config import GEMINI_API_KEY

    # トレンドテキスト
    trends_text = ""
    if trends:
        for i, t in enumerate(trends[:15], 1):
            trends_text += f"{i}. {t['keyword']}"
            if t.get("traffic"):
                trends_text += f"（検索数: {t['traffic']}）"
            trends_text += "\n"
            for n in t.get("news", []):
                trends_text += f"   - {n['title']}（{n['source']}）\n"

    prompt = "以下の情報を基に、本日のまとめレポートを作成してください。\n\n"

    if articles:
        prompt += f"## 今日保存した記事・メモ\n\n{articles[:3000]}\n\n"

    if trends_text:
        prompt += f"## Googleトレンド急上昇ワード\n\n{trends_text}\n\n"

    prompt += (
        "以下のフォーマットでまとめてください：\n\n"
        "## 📋 本日の活動サマリー\n"
        "（保存した記事があれば、その内容と学びを整理）\n\n"
        "## 🔥 注目トレンド TOP5\n"
        "（各トピックについて2-3行で解説）\n\n"
        "## 💡 ビジネス視点での考察\n"
        "（ビジネスや起業に活かせるインサイト）\n\n"
        "## 📌 明日のアクション提案\n"
        "（今日の情報を基にした次のステップ）"
    )

    def _sync_generate():
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text

    return await asyncio.to_thread(_sync_generate)


def _escape_md(text: str) -> str:
    """Markdownの特殊文字をエスケープ"""
    for char in ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]:
        text = text.replace(char, f"\\{char}")
    return text


async def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("youtube", youtube))
    app.add_handler(CommandHandler("plateau", plateau))
    app.add_handler(CommandHandler("paper", paper))
    app.add_handler(CommandHandler("trends", trends))
    app.add_handler(CommandHandler("matome", matome))
    app.add_handler(CommandHandler("order", order))
    app.add_handler(CommandHandler("orders", orders))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    logger.info("Bot起動中...")
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logger.info("Bot起動完了! Ctrl+Cで終了")
        # 停止シグナルまで待機
        import asyncio
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
