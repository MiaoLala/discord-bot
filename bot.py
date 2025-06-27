import discord
import os
from notion_client import Client as NotionClient
from datetime import datetime, timedelta, timezone
from dateutil import parser
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# 台灣時區
tz = timezone(timedelta(hours=8))

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

# Token 與資料庫設定
TOKEN = os.environ["DISCORD_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
MEETING_DB_ID = "cd784a100f784e15b401155bc3313a1f"
USERID_DB_ID = "21bd8d0b09f180908e1df38429153325"

notion = NotionClient(auth=NOTION_TOKEN)

def get_today_meetings_for_user(staff_id):
    """取得該員編在今天（台灣時間）的所有會議資訊"""
    now = datetime.now(tz)
    today_str = now.date().isoformat()
    today_display = now.strftime("%Y/%m/%d")

    filter_conditions = {
        "and": [
            {
                "property": "日期",
                "date": {
                    "on_or_after": today_str,
                    "on_or_before": today_str
                }
            },
            {
                "property": "類別",
                "select": {
                    "equals": "會議"
                }
            }
        ]
    }

    meeting_pages = notion.databases.query(
        database_id=MEETING_DB_ID,
        filter=filter_conditions
    ).get("results", [])

    meetings_for_user = []

    for page in meeting_pages:
        props = page["properties"]
        persons = props.get("相關人員", {}).get("people", [])

        if not any(staff_id in p.get("name", "") for p in persons):
            continue

        title = props.get("Name", {}).get("title", [])
        title_text = title[0]["text"]["content"] if title else "未命名會議"

        datetime_str = props["日期"]["date"]["start"]
        dt_obj = parser.isoparse(datetime_str).astimezone(tz)
        if dt_obj.date() != now.date():
            continue

        date_time = dt_obj.strftime("%Y/%m/%d %H:%M")

        location = "未填寫"
        location_prop = props.get("地點")
        if location_prop and location_prop.get("select"):
            location = location_prop["select"].get("name", "未填寫")

        meetings_for_user.append({
            "title": title_text,
            "datetime": date_time,
            "location": location
        })

    if not meetings_for_user:
        return f"{today_display} 今天沒有會議喔！"

    lines = [f"{today_display} 會議提醒"]
    for idx, m in enumerate(meetings_for_user, start=1):
        lines.append(f"{idx}. {m['title']}")
        lines.append(f"－ 時間：{m['datetime']}")
        lines.append(f"－ 地點：{m['location']}")
        lines.append("")

    return "\n".join(lines).strip()

# 建立 Discord Bot
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✅ Bot 上線為 {client.user}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    content = message.content.lower()
    discord_user_id = int(message.author.id)

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
        channel = message.channel
        if channel != "1387988298668048434":
            return
        
        await message.channel.send("📡 正在查詢今天的會議...")      
        
        try:
            user_entry = user_response["results"][0]
            employee_id = user_entry["properties"]["Name"]["title"][0]["text"]["content"]

            if not employee_id:
                await message.channel.send("🙅 找不到你的員編名稱")
                return

            reply_text = get_today_meetings_for_user(employee_id)
            await message.channel.send(reply_text)

        except Exception as e:
            await message.channel.send(f"❗ 發生錯誤：{e}")

client.run(TOKEN)
