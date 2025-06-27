import discord
import os
from notion_client import Client as NotionClient
from datetime import datetime, timedelta, timezone
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# 啟動假 HTTP server（為了 Render Web Service 檢查用）
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_dummy_server():
    port = int(os.environ.get("PORT", 5000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    print(f"Fake server running on port {port}")
    server.serve_forever()

threading.Thread(target=run_dummy_server).start()

# 台灣時區
tz_taiwan = timezone(timedelta(hours=8))
now = datetime.now(tz_taiwan)
today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
today_end = today_start + timedelta(days=1)
start_str = today_start.isoformat()
end_str = today_end.isoformat()

# Token 與資料庫設定
TOKEN = os.environ["DISCORD_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
MEETING_DB_ID = "cd784a100f784e15b401155bc3313a1f"
USERID_DB_ID = "21bd8d0b09f180908e1df38429153325"

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
notion = NotionClient(auth=NOTION_TOKEN)

@client.event
async def on_ready():
    print(f"✅ Bot 上線為 {client.user}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    content = message.content.lower()
    discord_user_id = int(message.author.id)  # 若 Notion DC ID 是 number

    # 查詢 User ID 資料庫
    user_response = notion.databases.query(
        database_id=USERID_DB_ID,
        filter={
            "property": "DC ID",
            "number": {
                "equals": discord_user_id
            }
        }
    )

    if not user_response["results"]:
        await message.channel.send("🙈 找不到你的員編喔，請先完成使用者綁定")
        return

    if content == "ping":
        await message.channel.send("pong！")

    elif content == "/會議":
        await message.channel.send("📡 正在查詢今天的會議...")

        try:
            user_entry = user_response["results"][0]
            employee_id = user_entry["properties"]["Name"]["title"][0]["text"]["content"]

            meeting_response = notion.databases.query(
                database_id=MEETING_DB_ID,
                filter={
                    "property": "日期",
                    "date": {
                        "on_or_after": start_str
                    }
                },
                sorts=[
                    {
                        "property": "日期",
                        "direction": "ascending"
                    }
                ]
            )

            related_meetings = []
            for i, page in enumerate(meeting_response["results"], start=1):
                props = page["properties"]
                people = props["相關人員"]["people"]

                # 比對是否相關
                if not any(employee_id in p["name"] for p in people):
                    continue

                # 安全取得欄位
                title = props["Name"]["title"][0]["text"]["content"] if props["Name"]["title"] else "(無標題)"
                datetime_str = props["日期"]["date"]["start"]
                dt = datetime.fromisoformat(datetime_str)
                date_str = dt.strftime("%Y/%m/%d")
                time_str = dt.strftime("%H:%M")

                location = ""
                if "地點" in props and props["地點"].get("rich_text"):
                    location = props["地點"]["rich_text"][0]["text"]["content"]

                meeting_str = f"{i}. {title} {time_str}\n－地點：{location}"
                related_meetings.append(meeting_str)

            # 組合回覆
            if related_meetings:
                header = f"{date_str} 會議通知"
                message_text = header + "\n" + "\n".join(related_meetings)
                await message.channel.send(message_text)
            else:
                await message.channel.send("🙅 今天沒有你參加的會議喔！")

        except Exception as e:
            await message.channel.send(f"❗ 發生錯誤：{e}")

client.run(TOKEN)
