import discord
import os
from notion_client import Client
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
MEETING_DB_ID = "cd784a100f784e15b401155bc3313a1f" # 會議

notion = Client(auth=NOTION_TOKEN)

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'{client.user} 上線了！')
    # 可以在這邊加上排程或一啟動就跑的查詢
    await post_meeting_notes()

async def post_meeting_notes():
    response = notion.databases.query(database_id=NOTION_DB_ID)
    for page in response['results']:
        title = page['properties']['Name']['title'][0]['text']['content']
        date = page['properties']['日期']['date']['start']
        # 可根據格式調整
        channel = client.get_channel(你的頻道ID)  # 記得換成正確的channel id
        await channel.send(f"📅 {date} 會議：{title}")

client.run(DISCORD_TOKEN)
