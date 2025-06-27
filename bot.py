import discord
import os
from notion_client import Client as NotionClient

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
    if message.content.lower() == "ping":
        await message.channel.send("pong！")

    elif content == "/會議":
        await message.channel.send("📡 正在查詢 Notion 會議記錄...")
        try:
            response = notion.databases.query(database_id=MEETING_DB_ID)
            results = response["results"]
            if not results:
                await message.channel.send("🙅 沒有查到任何會議記錄！")
                return

            # 假設每一筆都有一個「名稱」欄位（title）
            lines = []
            for page in results[:5]:  # 只取前 5 筆
                props = page["properties"]
                title = props["Name"]["title"][0]["text"]["content"] if props["Name"]["title"] else "未命名會議"
                date = props["日期"]["date"]["start"]
                lines.append(f"📌 {title}（{date}）")

            await message.channel.send("\n".join(lines))

        except Exception as e:
            await message.channel.send(f"❗ 發生錯誤：{e}")
            
client.run(TOKEN)
