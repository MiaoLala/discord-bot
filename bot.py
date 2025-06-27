import discord
import os

TOKEN = os.environ["DISCORD_TOKEN"]  # 用環境變數（Render 用這個）

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
    if message.content.lower() == "ping":
        await message.channel.send("pong！")

client.run(TOKEN)
