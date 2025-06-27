import discord
import os
from discord.ext import commands
from discord import app_commands
from notion_client import Client as NotionClient
from datetime import datetime, timedelta, timezone
from dateutil import parser
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger  # 這行要加上


# ====== 設定區 ======
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
MEETING_DB_ID = "cd784a100f784e15b401155bc3313a1f"
USERID_DB_ID = "21bd8d0b09f180908e1df38429153325"
GUILD_ID = discord.Object(id=int(os.environ.get("GUILD_ID")))  # 你的 Discord Server ID


# ====== Slash Command Bot 建立 ======
intents = discord.Intents.default()
client = commands.Bot(command_prefix="!", intents=intents)

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

# 發送每月五號報告提醒
REPORT_CHANNEL_ID = 1387409782553710663  # 修改為你要發送的頻道 ID

def is_last_friday(date):
    """判斷該日期是否為該月最後一個星期五"""
    next_week = date + timedelta(weeks=1)
    return date.weekday() == 4 and next_week.month != date.month

async def send_monthly_reminder():
    now = datetime.now(tz)
    if is_last_friday(now.date()):
        channel = client.get_channel(REPORT_CHANNEL_ID)
        if channel:
            await channel.send("📌 記得寫5號報告唷~")

# debug查詢
# 指定頻道 ID（限制只能該頻道使用）
ALLOWED_CHANNEL_ID = 1388000532572012685

# Modal 視窗
class DebugRequestModal(discord.ui.Modal, title="🛠️ Debug 查詢申請"):
    content = discord.ui.TextInput(
        label="請填寫以下內容",
        style=discord.TextStyle.paragraph,
        default=(
            "請幫我開Debug\n"
            "類別：查詢或修改\n"
            "作業項目：\n"
            "k1：\n"
            "k2：\n"
            "k3："
        ),
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"✅ 已收到你的申請內容：\n\n```{self.content.value}```",
            ephemeral=True
        )

# Slash 指令：/debug申請
@bot.tree.command(name="debug申請", description="開啟 Debug 查詢申請表單")
async def debug_request(interaction: discord.Interaction):
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("❗此指令只能在指定頻道中使用唷", ephemeral=True)
        return

    await interaction.response.send_modal(DebugRequestModal())

@client.event
async def on_ready():
    print(f"✅ Bot 已上線：{client.user}")
    await client.tree.sync(guild=GUILD_ID)

    # ✅ 指定一次性排程：2025/06/27 14:32 台灣時間
    scheduler = AsyncIOScheduler(timezone="Asia/Taipei")
    # 每週五早上 9:00 執行（函式內部再判斷是不是「最後一個週五」）
    scheduler.add_job(send_monthly_reminder, CronTrigger(day_of_week="fri", hour=9, minute=0))
    scheduler.start()

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
    ALLOWED_CHANNEL_ID = 1387988298668048434  # 你指定的頻道 ID

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
