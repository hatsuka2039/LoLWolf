import discord
import random
import asyncio
import os
from typing import List, Dict, Optional

TOKEN = os.environ["DISCORD_TOKEN"]

# TODO: 後々RiotAPIと連携してチャンピオンとリンクできるようにしたい
# TODO: Discordの表示名を自動的にチャンピオン名に変更するようになるといいね
# TODO: 設定はどこかで弄れるようにしたいね


class User(object):
    def __init__(self, info: discord.Member):
        self.info: discord.Member = info
        self.is_wolf: bool = False
        self.vote: int = -1 

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, User):
            return NotImplemented
        return self.info == other.info


class Game(object):
    def __init__(self, server_id: int):
        self.is_start: bool = False
        self.server_id: int = server_id
        self.host: Optional[User] = None
        self.red_team: List[User] = []
        self.blue_team: List[User] = []
        self.red_votes: List[int] = [0] * 5
        self.blue_votes: List[int] = [0] * 5

    async def start(self, channel: discord.TextChannel):
        if self.host is None:
            await channel.send("ホストが不在です。")
            # return

        if len(self.red_team) != 5 or len(self.blue_team) != 5:
            await channel.send("各陣営の必要メンバー数に達していません。")
            return

        if self.is_start:
            await channel.send("ゲームが既に開始されています。中断したい場合は")

        await channel.send("*** ゲームを開始します！ ***")
        self.is_start = True

        # 人狼を決定する
        self.red_team[random.randint(0, 4)].is_wolf = True
        self.blue_team[random.randint(0, 4)].is_wolf = True

        # ホストに全情報を送信
        # self.host.info.send(await self.generate_current_status_text(False))

        # テキストチャットに役職を伏せた全情報を送信
        await channel.send(await self.generate_current_status_text(True))

        # 個別にDMで連絡
        for user in self.red_team + self.blue_team:
            await user.info.send("あなたは{}です。".format("人狼" if user.is_wolf else "村人"))

        await channel.send("*** 役職が決定されました！DMを確認してください ***")
        await channel.send('もしDMが届かない人がいる場合は"/restart"コマンドを実行してください')
        await channel.send("なお、DMを受け取らないように制限している場合は解除してください")

        # Ban/Pick相談 - 5分
        await channel.send("*** ここから3分間のBan/Pick相談時間です ***")
        await asyncio.sleep(120)
        await channel.send("*** 残り1分です ***")
        await asyncio.sleep(60)

        # 試合開始コール
        if self.is_start:
            await channel.send("*** 相談時間は終わりです。試合を開始してください。GLHF!! ***")

    async def finish(self, channel: discord.TextChannel):
        await channel.send("*** 試合お疲れさまでした！ ***")
        await channel.send("*** ここから5分間のシンキング・相談タイムです！ ***")
        await asyncio.sleep(240)
        await channel.send("*** 残り1分です ***")
        await asyncio.sleep(60)

        await channel.send("*** シンキング・相談タイム終了です ***")
        await channel.send(
            "*** 参加者の皆様は私にDMで投票する人の名前を教えてください。名前は正確に入力してくださいね！敬称は不要です！ ***"
        )

    async def aggregate(self, channel: discord.TextChannel):
        redVotes = [redUser.vote for redUser in self.red_team]
        blueVotes = [blueUser.vote for blueUser in self.blue_team]
        if -1 in redVotes or -1 in blueVotes:
            await channel.send("投票数が足りないようです。どなたか忘れていませんか？")
        else:
            for i, j in zip(redVotes, blueVotes): 
                self.red_votes[i] += 1
                self.blue_votes[j] += 1

        await channel.send("*** 結果発表です！ ***")
        await channel.send(await self.generate_current_status_text(False))

    async def generate_current_status_text(self, is_blind: bool) -> str:
        text: str = ""
        text += "===ホスト===\n"
        if self.host is not None:
            text += f"{self.host.info.name} さん\n"
        else:
            text += "不在\n"

        text += "\n===赤陣営===\n"
        for user, vote in zip(self.red_team, self.red_votes):
            text += f"{user.info.name} さん: {vote}票"
            text += " 人狼\n" if not is_blind else "\n"

        text += "\n===青陣営===\n"
        for user, vote in zip(self.blue_team, self.blue_votes):
            text += f"{user.info.name} さん: {vote}票"
            text += " 人狼\n" if not is_blind else "\n"

        return text


client = discord.Client()
games: Dict[int, Game] = {}


@client.event
async def on_ready():
    print("LoL人狼ボット起動しました")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    server: discord.Guild = message.guild
    channel: discord.TextChannel = message.channel
    user: User = User(message.author)
    name: str = message.author.name

    # DMでの投票受付
    if (
        isinstance(message.channel, discord.DMChannel)
        and client.user == message.channel.me
    ):
        # TODO: この全検索、スケーラビリティやばそう
        for game in games.values():
            if user in game.red_team:
                for j, player in enumerate(game.red_team):
                    if player.info.name == message.content:
                        user.vote = j
                        await user.info.send("投票が正常に行われました。")
                        return

            if user in game.blue_team:
                for i, player in enumerate(game.blue_team):
                    if player.info.name == message.content:
                        user.vote = i 
                        await user.info.send("投票が正常に行われました。")
                        return

        await user.info.send("存在しない参加者のようです...")
        return

    # もしコマンド受付が初回だった場合はゲームオブジェクトを作成
    if server.id not in games:
        games[server.id] = Game(server.id)

    if not message.content.startswith("/"):
        return

    # サーバで開催されているゲーム情報を全てリセットし、チャット履歴を抹消
    if message.content == "/reset":
        if message.author.guild_permissions.administrator:
            if server.id in games:
                del games[server.id]
            await channel.send("ゲームをリセットしました。")
        else:
            await channel.send("あなたの権限ではリセット要請できません。サーバ管理者に問い合わせてみてください。")
        return

    # ゲームのホストを登録
    if message.content.startswith("/host"):
        if games[server.id].host is not None:
            await channel.send("ホストは既に登録済みです。")
            return

        games[server.id].host = user
        await channel.send(f"{name}さんがホストとして登録されました。コマンドの中にはホストのみ実行が許されたものがあります。")
        return

    # ゲームの参加者を登録
    if message.content.startswith("/join"):
        # 既にどちらかの陣営に参加している場合
        if user in games[server.id].blue_team or user in games[server.id].red_team:
            await channel.send(f"{name}さんは既にゲームに参加されているようです。")
            return

        # 赤陣営に追加
        if "red" in message.content:
            # 各陣営は5人まで
            if len(games[server.id].red_team) >= 5:
                await channel.send("赤陣営はいっぱいのようです。")
                return

            games[server.id].red_team.append(user)
            await channel.send(f"{name}さんが赤陣営に追加されました。")

        # 青陣営に追加
        elif "blue" in message.content:
            # 各陣営は5人まで
            if len(games[server.id].blue_team) >= 5:
                await channel.send("青陣営はいっぱいのようです。")
                return

            games[server.id].blue_team.append(user)
            await channel.send(f"{name}さんが青陣営に追加されました。")

        # 陣営が無効または入力されていない場合
        else:
            await channel.send('無効な陣営です。"red"もしくは"blue"で指定してください。')

        return

    if message.content == "/quit":
        # 赤陣営から抜ける
        if user in games[server.id].red_team:
            games[server.id].red_team.remove(user)
            await channel.send(f"{name}さんが赤陣営から抜けました。")

        # 青陣営から抜ける
        elif user in games[server.id].blue_team:
            games[server.id].blue_team.remove(user)
            await channel.send(f"{name}さんが青陣営から抜けました。")

        # ホストを辞める
        elif user == games[server.id].host:
            games[server.id].host = None
            await channel.send(f"{name}さんがホストでは無くなりました。")

        # どちらの陣営でもない場合
        else:
            await channel.send(f"{name}さんはまだゲームに参加していないようです。")

        return

    if message.content == "/status":
        if user == games[server.id].host:
            # ホストがこのコマンドを実行した場合、DMに追加の情報を送信する
            await user.info.send(
                await games[server.id].generate_current_status_text(False)
            )
            await channel.send(
                await games[server.id].generate_current_status_text(True)
            )
        else:
            await channel.send(
                await games[server.id].generate_current_status_text(True)
            )
        return

    if message.content == "/start":
        if user == games[server.id].host:
            await games[server.id].start(channel)
        else:
            await channel.send("ゲーム開始はホストが行ってください。")
        return

    if message.content == "/restart":
        if user == games[server.id].host:
            games[server.id].is_start = False
            await games[server.id].start(channel)
        else:
            await channel.send("ゲーム開始はホストが行ってください。")
        return

    if message.content == "/finish":
        if user == games[server.id].host:
            await games[server.id].finish(channel)
        else:
            await channel.send("ゲーム終了はホストが行ってください。")
        return

    if message.content == "/aggregate":
        if user == games[server.id].host:
            await games[server.id].aggregate(channel)
        else:
            await channel.send("集計要請はホストが行ってください。")
        return

    if message.content == "/help":
        text: str = ""
        text += "/reset : ゲームを完全に初期化します。\n"
        text += "/host : ゲームにホストとして参加します。\n"
        text += "/join [red|blue] : ゲームにプレイヤとして参加します。redまたはblueで各陣営を指定します。\n"
        text += "/quit : ゲームから抜けます。\n"

        text += "\n"
        text += "/start : ゲームを開始します。\n"
        text += "/restart : 途中不具合があった場合に再スタートします。\n"
        text += "/finish : LoLの試合が終了したことを合図します。\n"
        text += "/aggregate : 投票の結果を表示します。\n"

        await channel.send(text)
        return

    # どのコマンドにも一致しない場合
    await channel.send('お困りですか？"/help"でコマンド一覧を取得できます。')


client.run(TOKEN)
