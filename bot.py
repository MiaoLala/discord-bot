import discord
import os
from discord.ext import commands
from discord import app_commands
from notion_client import Client as NotionClient
from datetime import datetime, timedelta, timezone
from dateutil import parser
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


# ====== 設定區 ======
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
MEETING_DB_ID = "cd784a100f784e15b401155bc3313a1f"
USERID_DB_ID = "21bd8d0b09f180908e1df38429153325"
GUILD_ID = discord.Object(id=int(os.environ.get("GUILD_ID")))  # 你的 Discord Server ID

tz = timezone(timedelta(hours=8))
notion = NotionClient(auth=NOTION_TOKEN)

# ====== HTTP 假伺服器（Render 需要開 Port）======
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_dummy_server():
    port = int(os.environ.get("PORT", 5000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    print(f"Fake server running on port {port}")
    server.serve_forever()

threading.Thread(target=run_dummy_server).start()

# ====== Slash Command Bot 建立 ======
intents = discord.Intents.default()
client = commands.Bot(command_prefix="!", intents=intents)

@client.event
async def on_ready():
    print(f"✅ Bot 已上線：{client.user}")
    await client.tree.sync(guild=GUILD_ID)

# ====== Notion 查詢邏輯 ======
def get_today_meetings_for_user(staff_id):
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

# ====== Slash 指令 /會議 ======
@client.tree.command(name="會議", description="查詢今天你參加的 Notion 會議")
@app_commands.guilds(GUILD_ID)
async def meeting_command(interaction: discord.Interaction):
    ALLOWED_CHANNEL_ID = 1388039064166338612  # 你指定的頻道 ID

    # 檢查是否來自允許的頻道
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("❗此指令只能在指定頻道中使用喔～", ephemeral=True)
        return
        
    await interaction.response.defer(thinking=True)

    discord_user_id = interaction.user.id

    try:
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
            await interaction.followup.send("🙈 找不到你的員編喔，請先完成使用者綁定")
            return

        user_entry = user_response["results"][0]
        employee_id = user_entry["properties"]["Name"]["title"][0]["text"]["content"]

        reply_text = get_today_meetings_for_user(employee_id)
        await interaction.followup.send(reply_text)

    except Exception as e:
        await interaction.followup.send(f"❗ 發生錯誤：{e}")

# ====== 執行 Bot ======
client.run(DISCORD_TOKEN)
