import discord
import os
import calendar
from discord.ext import commands
from discord import app_commands
from notion_client import Client as NotionClient
from datetime import datetime, timedelta, timezone
from dateutil import parser
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger


# ====== Discord Bot 初始化（⚠ 提早定義 client）======
intents = discord.Intents.default()
client = commands.Bot(command_prefix="!", intents=intents)

# ====== 設定區 ======
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
MEETING_DB_ID = "cd784a100f784e15b401155bc3313a1f"
USERID_DB_ID = "21bd8d0b09f180908e1df38429153325"
GUILD_ID = discord.Object(id=int(os.environ.get("GUILD_ID")))
tz = timezone(timedelta(hours=8))
notion = NotionClient(auth=NOTION_TOKEN)

# 預設頻道設定
REPORT_CHANNEL_ID = 1387409782553710663 # 公告
MEETING_ALLOWED_CHANNEL_ID = 1387988298668048434
DEBUG_ALLOWED_CHANNEL_ID = 1388000532572012685
TARGET_CHANNEL_ID = 1388083307476156466 # 提醒

# ====== HTTP 假伺服器（Render Ping 用）======
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
    print(f"✅ Dummy HTTP Server on port {port}")
    server.serve_forever()

threading.Thread(target=run_dummy_server).start()


# ====== 每月提醒邏輯 ======
def is_last_working_day(date: datetime.date) -> bool:
    # 找出該月最後一天
    last_day = calendar.monthrange(date.year, date.month)[1]
    last_date = datetime(date.year, date.month, last_day).date()

    # 從最後一天往前找，直到不是週六日
    while last_date.weekday() >= 5:  # 5: Saturday, 6: Sunday
        last_date -= timedelta(days=1)

    return date == last_date

def is_last_friday(date):
    return date.weekday() == 4 and (date + timedelta(weeks=1)).month != date.month
    
async def send_monthly_reminder():
    now = datetime.now(tz)
    if is_last_working_day(now.date()):
        channel = client.get_channel(TARGET_CHANNEL_ID)
        if channel:
            await channel.send("📌 記得寫5號報告唷~")


# 打卡提醒訊息
async def send_daily_reminder():
    now = datetime.now(tz)
    hour = now.hour
    channel = client.get_channel(TARGET_CHANNEL_ID)
    if channel:
        if hour < 12:
            await channel.send("⏰ 記得上班打卡唷！！")
        else:
            await channel.send("🕔 下班前記得打卡！")
        

# ====== Debug Modal 定義 ======
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
        # 本人看到確認訊息（ephemeral）
        await interaction.response.send_message(
            "✅ 已收到你的申請內容，我們會儘快處理！", ephemeral=True
        )

        # 公開發送申請內容
        channel = interaction.client.get_channel(DEBUG_ALLOWED_CHANNEL_ID)
        if channel:
            await channel.send(
                f"📨 <@{interaction.user.id}> 提交了一筆 Debug 查詢申請：\n```{self.content.value}```"
            )


# 按鈕互動
class DebugButtonView(discord.ui.View):
    @discord.ui.button(label="開啟 Debug 申請表單", style=discord.ButtonStyle.primary)
    async def open_debug_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DebugRequestModal())

# Slash 指令，送出按鈕訊息
@client.tree.command(name="debug申請", description="開啟 Debug 查詢申請按鈕")
@app_commands.guilds(GUILD_ID)
async def debug_command(interaction: discord.Interaction):
    ALLOWED_CHANNEL_ID = 1388000532572012685  # 你指定的頻道 ID
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("❗此指令只能在指定頻道中使用唷", ephemeral=True)
        return

    await interaction.response.send_message(
        "請點下面按鈕開啟 Debug 申請表單",
        view=DebugButtonView(),
        ephemeral=True  # 只有自己看得到
    )

# ====== /會議 查詢 ======
@client.tree.command(name="會議", description="查詢今天你參加的 Notion 會議")
@app_commands.guilds(GUILD_ID)
async def meeting_command(interaction: discord.Interaction):
    if interaction.channel_id != MEETING_ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("❗此指令只能在指定頻道中使用喔～", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)

    discord_user_id = interaction.user.id

    try:
        user_response = notion.databases.query(
            database_id=USERID_DB_ID,
            filter={
                "property": "DC ID",
                "number": {"equals": discord_user_id}
            }
        )
        if not user_response["results"]:
            await interaction.followup.send("🙈 找不到你的員編喔，請先完成使用者綁定", ephemeral=True)
            return

        user_entry = user_response["results"][0]
        employee_id = user_entry["properties"]["Name"]["title"][0]["text"]["content"]
        reply_text = get_today_meetings_for_user(employee_id)
        await interaction.followup.send(reply_text, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"❗ 發生錯誤：{e}", ephemeral=True)


# ====== 查詢 Notion 當日會議 ======
def get_today_meetings_for_user(staff_id):
    now = datetime.now(tz)
    today_str = now.date().isoformat()
    today_display = now.strftime("%Y/%m/%d")

    filter_conditions = {
        "and": [
            {"property": "日期", "date": {"on_or_after": today_str, "on_or_before": today_str}},
            {"property": "類別", "select": {"equals": "會議"}}
        ]
    }

    meeting_pages = notion.databases.query(database_id=MEETING_DB_ID, filter=filter_conditions).get("results", [])
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
        location = props.get("地點", {}).get("select", {}).get("name", "未填寫")

        meetings_for_user.append({
            "title": title_text,
            "datetime": date_time,
            "location": location
        })

    if not meetings_for_user:
        return f"{today_display} 今天沒有會議喔！"

    lines = [f"{today_display} 會議提醒"]
    for idx, m in enumerate(meetings_for_user, 1):
        lines.append(f"{idx}. {m['title']}")
        lines.append(f"－ 時間：{m['datetime']}")
        lines.append(f"－ 地點：{m['location']}")
        lines.append("")

    return "\n".join(lines).strip()

async def test_job():
    print("這是測試工作，每分鐘執行一次")

# ====== Bot 啟動與排程設定 ======
@client.event
async def on_ready():
    print(f"✅ Bot 已上線：{client.user}")
    await client.tree.sync(guild=GUILD_ID)

    scheduler = AsyncIOScheduler(timezone="Asia/Taipei")
    scheduler.add_job(send_monthly_reminder, CronTrigger(day_of_week="fri", hour=9, minute=0))
    scheduler.add_job(send_daily_reminder, CronTrigger(day_of_week="mon-fri", hour=8, minute=25))
    scheduler.add_job(send_daily_reminder, CronTrigger(day_of_week="mon-fri", hour=18, minute=0))
    scheduler.add_job(test_job, CronTrigger(second=0))
    scheduler.start()


client.run(DISCORD_TOKEN)
