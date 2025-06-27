import discord
import os
from notion_client import Client as NotionClient
from datetime import datetime, timedelta, timezone


# 台灣時區
tz_taiwan = timezone(timedelta(hours=8))

# 今天起訖時間（台灣時間）
now = datetime.now(tz_taiwan)
today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
today_end = today_start + timedelta(days=1)

# 轉為 ISO 格式給 Notion
start_str = today_start.isoformat()
end_str = today_end.isoformat()

TOKEN = os.environ["DISCORD_TOKEN"]  # 用環境變數（Render 用這個）
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
    discord_user_id = str(message.author.id)

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
    await message.channel.send("找不到你的員編喔 🙈")
    return
    
    if message.content.lower() == "ping":
        await message.channel.send("pong！")

    elif content == "/會議":
        await message.channel.send("📡 正在查詢 Notion 會議記錄...")
        try:            
            user_entry = user_response["results"][0]
            employee_id = user_entry["properties"]["Name"]["title"][0]["text"]["content"]

            response = notion.databases.query(database_id=MEETING_DB_ID)
            results = response["results"]
            if not results:
                await message.channel.send("🙅 沒有查到任何會議記錄！")
                return

            meeting_response = notion.databases.query(
                database_id=MEETING_DB_ID,
                # 可加入其他條件，例如日期篩選
                    filter={
                        "property": "日期",
                        "date": {
                            "on_or_after": start_str,
                        }
                    },
                    sorts=[
                        {
                            "property": "日期",
                            "direction": "ascending"
                        }
                    ]
            )
            
            # 會議資料組合
            related_meetings = []
            for i, page in enumerate(today_meetings, start=1):
                props = page["properties"]
            
                title = props["Name"]["title"][0]["text"]["content"]
                datetime_str = props["日期"]["date"]["start"]
                dt = datetime.fromisoformat(datetime_str)
                date_str = dt.strftime("%Y/%m/%d")
                time_str = dt.strftime("%H:%M")
            
                location_prop = props.get("地點", {})
                location = ""
                if "rich_text" in location_prop and location_prop["rich_text"]:
                    location = location_prop["rich_text"][0]["text"]["content"]
            
                meeting_str = f"{i}. {title} {time_str}\n－ 地點：{location}"
                related_meetings.append(meeting_str)
            
            # 組合整體訊息
            if related_meetings:
                header = f"{date_str} 會議通知"
                message_text = header + "\n" + "\n".join(related_meetings)
                await message.channel.send(message_text)
            else:
                await message.channel.send("🙅 沒有查到你參加的會議")

        except Exception as e:
            await message.channel.send(f"❗ 發生錯誤：{e}")
            
client.run(TOKEN)
