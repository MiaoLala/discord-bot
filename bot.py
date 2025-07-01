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
from concurrent.futures import ThreadPoolExecutor
import asyncio

# ====== Discord Bot 初始化 ======
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

# 頻道ID
REPORT_CHANNEL_ID = 1387409782553710663
MEETING_ALLOWED_CHANNEL_ID = 1387988298668048434
DEBUG_ALLOWED_CHANNEL_ID = 1388000532572012685
TARGET_CHANNEL_ID = 1388083307476156466
SENDMAIL_CHANNEL_ID = 1388000512875696128
TEST_CHANNEL_ID = 1388040404385136791

# ====== 執行緒池，用來包同步 Notion 查詢 ======
executor = ThreadPoolExecutor(max_workers=5)

async def query_notion_database(database_id, filter_conditions):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        executor,
        lambda: notion.databases.query(database_id=database_id, filter=filter_conditions)
    )


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

threading.Thread(target=run_dummy_server, daemon=True).start()


# ====== 找國定假日 ======
async def is_today_public_holiday():
    today = datetime.now(tz).date().isoformat()
    filter_conditions = {
        "and": [
            {"property": "日期", "date": {"equals": today}},
            {"property": "類別", "select": {"equals": "國定假日"}}
        ]
    }
    try:
        results = await query_notion_database(MEETING_DB_ID, filter_conditions)
        is_holiday = len(results.get("results", [])) > 0
        print(f"✅ 是否國定假日：{is_holiday}")
        return is_holiday
    except Exception as e:
        print(f"❗ 查詢國定假日時發生錯誤：{e}")
        return False


# ====== 每月提醒邏輯 ======
def get_last_valid_workday(notion_holidays: set, year: int, month: int) -> datetime.date:
    last_day = calendar.monthrange(year, month)[1]
    date = datetime(year, month, last_day).date()

    while True:
        is_weekend = date.weekday() >= 5
        is_holiday = date.isoformat() in notion_holidays

        if not is_weekend and not is_holiday:
            return date
        date -= timedelta(days=1)


async def send_monthly_reminder():
    now = datetime.now(tz)

    # 取得 Notion 假日
    try:
        holiday_pages = await query_notion_database(
            MEETING_DB_ID,
            {"property": "類別", "select": {"equals": "國定假日"}}
        )
    except Exception as e:
        print(f"❗ 查詢國定假日失敗：{e}")
        return

    holidays = set()
    for page in holiday_pages.get("results", []):
        date_prop = page["properties"].get("日期", {}).get("date", {})
        if date_prop and date_prop.get("start"):
            date_str = parser.isoparse(date_prop["start"]).date().isoformat()
            holidays.add(date_str)

    last_workday = get_last_valid_workday(holidays, now.year, now.month)

    if now.date() == last_workday:
        channel = client.get_channel(TARGET_CHANNEL_ID)
        if channel:
            await channel.send("📌 記得寫5號報告唷~")


# ====== 每日打卡提醒 ======
async def send_daily_reminder():
    if await is_today_public_holiday():
        print("今天是國定假日，不發送提醒訊息。")
        return

    now = datetime.now(tz)
    hour = now.hour
    channel = client.get_channel(TARGET_CHANNEL_ID)
    if channel:
        if hour < 12:
            await channel.send("⏰ 記得上班打卡唷！！")
        else:
            await channel.send("🕔 下班前記得打卡！")


# ====== 工具函式：將長訊息分段 ======
def split_text(text, max_length=1900):
    lines = text.split('\n')
    result = []
    buffer = ""
    for line in lines:
        if len(buffer) + len(line) + 1 > max_length:
            result.append(buffer)
            buffer = ""
        buffer += line + "\n"
    if buffer:
        result.append(buffer)
    return result

# ====== /會議 查詢指令 ======
@client.tree.command(name="會議", description="查詢今天你參加的 Notion 會議")
@app_commands.guilds(GUILD_ID)
async def meeting_command(interaction: discord.Interaction):
    if interaction.channel_id != MEETING_ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("❗此指令只能在指定頻道中使用喔～", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)

    discord_user_id = interaction.user.id

    try:
        # 查詢使用者員編
        try:
            user_response = await query_notion_database(
                USERID_DB_ID,
                {
                    "property": "DC ID",
                    "number": {"equals": discord_user_id}
                }
            )
        except Exception as e:
            print(f"查詢使用者員編失敗: {e}", exc_info=True)
            await interaction.followup.send("❗查詢使用者員編時發生錯誤，請稍後再試。", ephemeral=True)
            return

        if not user_response["results"]:
            await interaction.followup.send("🙈 找不到你的員編喔，請先完成使用者綁定", ephemeral=True)
            return

        user_entry = user_response["results"][0]
        employee_id = user_entry["properties"]["Name"]["title"][0]["text"]["content"]

        # 查詢今日會議
        today_str = datetime.now(tz).date().isoformat()
        meeting_filter = {
            "and": [
                {"property": "日期", "date": {"equals": today_str}},
                {"property": "類別", "select": {"equals": "會議"}}
            ]
        }

        try:
            meeting_pages = await query_notion_database(MEETING_DB_ID, meeting_filter)
        except Exception as e:
            print(f"查詢今日會議失敗: {e}", exc_info=True)
            await interaction.followup.send("❗查詢今日會議時發生錯誤，請稍後再試。", ephemeral=True)
            return

        meetings_for_user = []

        for page in meeting_pages.get("results", []):
            props = page["properties"]
            persons = props.get("相關人員", {}).get("people", [])
            if not any(employee_id in p.get("name", "") for p in persons):
                continue

            title = props.get("Name", {}).get("title", [])
            title_text = title[0]["text"]["content"] if title else "未命名會議"
            datetime_str = props["日期"]["date"]["start"]
            dt_obj = parser.isoparse(datetime_str).astimezone(tz)
            if dt_obj.date() != datetime.now(tz).date():
                continue

            date_time = dt_obj.strftime("%Y/%m/%d %H:%M")
            location = props.get("地點", {}).get("select", {}).get("name", "未填寫")

            meetings_for_user.append({
                "title": title_text,
                "datetime": date_time,
                "location": location
            })

        # 組訊息內容
        today_display = datetime.now(tz).strftime('%Y/%m/%d')
        if not meetings_for_user:
            await interaction.followup.send(f"{today_display} 今天沒有會議喔！", ephemeral=True)
            return

        lines = [f"{today_display} 會議提醒"]
        for idx, m in enumerate(meetings_for_user, 1):
            lines.append(f"{idx}. {m['title']}")
            lines.append(f"－ 時間：{m['datetime']}")
            lines.append(f"－ 地點：{m['location']}")
            lines.append("")

        # 分段送出
        for chunk in split_text("\n".join(lines).strip()):
            await interaction.followup.send(chunk, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"❗ 發生錯誤：{e}", ephemeral=True)


# ====== 作業需求 寄信申請 ======
class PersonSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="依廷", value="依廷"),
            discord.SelectOption(label="豐全", value="豐全"),
            discord.SelectOption(label="湘鈴", value="湘鈴"),
        ]
        super().__init__(
            placeholder="請選擇要寄信的人",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected_name = self.values[0]
        await interaction.response.send_message(
            "請點下面按鈕開啟寄信申請表單",
            view=SendMailWithNameView(selected_name),
            ephemeral=True
        )

class PersonSelectView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(PersonSelect())

class SendMailRequestModal(discord.ui.Modal):
    def __init__(self, selected_name: str):
        super().__init__(title="📧 寄信申請")
        self.selected_name = selected_name

        self.content = discord.ui.TextInput(
            label="請填寫以下內容",
            style=discord.TextStyle.paragraph,
            default=(
                f"{selected_name}，請幫我寄信 謝謝！\n"
                "資料庫：\n"
                "執行時間："
            ),
            required=True,
            max_length=1000
        )
        self.add_item(self.content)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ 已收到你的寄信申請內容！", ephemeral=True)
        channel = interaction.client.get_channel(SENDMAIL_CHANNEL_ID)
        if channel:
            await channel.send(f"📨 <@{interaction.user.id}> 提交了一筆寄信申請：\n```{self.content.value}```")

class SendMailWithNameView(discord.ui.View):
    def __init__(self, selected_name: str):
        super().__init__()
        self.selected_name = selected_name

    @discord.ui.button(label="開啟寄信申請表單", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SendMailRequestModal(self.selected_name))

@client.tree.command(name="寄信申請", description="寄信申請（選擇對象）")
@app_commands.guilds(GUILD_ID)
async def send_mail_select(interaction: discord.Interaction):
    await interaction.response.send_message(
        "請選擇收件對象 👇",
        view=PersonSelectView(),
        ephemeral=True
    )


# ====== Debug 申請 ======
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
        await interaction.response.send_message("✅ 已收到你的申請內容，我們會儘快處理！", ephemeral=True)
        channel = interaction.client.get_channel(DEBUG_ALLOWED_CHANNEL_ID)
        if channel:
            await channel.send(
                f"📨 <@{interaction.user.id}> 提交了一筆 Debug 授權申請：\n```{self.content.value}```"
            )

class DebugButtonView(discord.ui.View):
    @discord.ui.button(label="開啟 Debug 申請表單", style=discord.ButtonStyle.primary)
    async def open_debug_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DebugRequestModal())

@client.tree.command(name="debug申請", description="開啟 Debug 授權申請按鈕")
@app_commands.guilds(GUILD_ID)
async def debug_command(interaction: discord.Interaction):
    if interaction.channel_id != DEBUG_ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("❗此指令只能在指定頻道中使用喔～", ephemeral=True)
        return

    await interaction.response.send_message(
        "請點下面按鈕開啟 Debug 申請表單",
        view=DebugButtonView(),
        ephemeral=True
    )


# ====== Bot 啟動與排程設定 ======
@client.event
async def on_ready():
    print(f"✅ Bot 已上線：{client.user}")
    await client.tree.sync(guild=GUILD_ID)

    scheduler = AsyncIOScheduler(timezone="Asia/Taipei")
    # 每月提醒（最後一個工作天上午10點）
    scheduler.add_job(send_monthly_reminder, CronTrigger(hour=10, minute=0, timezone="Asia/Taipei"), misfire_grace_time=300)
    # 每日提醒（工作日早上8:25 & 晚上6點）
    scheduler.add_job(send_daily_reminder, CronTrigger(day_of_week="mon-fri", hour=8, minute=25, timezone="Asia/Taipei"), misfire_grace_time=300)
    scheduler.add_job(send_daily_reminder, CronTrigger(day_of_week="mon-fri", hour=18, minute=0, timezone="Asia/Taipei"), misfire_grace_time=300)
    scheduler.start()

client.run(DISCORD_TOKEN)
