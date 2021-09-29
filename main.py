import discord
import random
import asyncio
import os
import json
from transitions import Machine
from typing import List, Dict, Optional

TOKEN = os.environ["DISCORD_TOKEN"]

# TODO: 後々RiotAPIと連携してチャンピオンとリンクできるようにしたい
# TODO: Discordの表示名を自動的にチャンピオン名に変更するようになるといいね
# TODO: 設定はどこかで弄れるようにしたいね


class User(object):
    def __init__(self, info: discord.Member):
        self.info: discord.Member = info
        self.is_wolf: bool = False
        self.is_vote: bool = False
        self.voted: int = 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, User):
            raise NotImplementedError("Different type equality check happned.")
        return self.info == other.info


class Game(object):
    def __init__(self, channel: discord.TextChannel):
        states = [
            "pre-game",
            "ban-pick",
            "in-game",
            "thinking-time",
            "voting",
            "end",
        ]
        transitions = [
            {"trigger": "begin", "source": "pre-game", "dest": "ban-pick"},
            {"trigger": "start", "source": "ban-pick", "dest": "in-game"},
            {"trigger": "finish", "source": "in-game", "dest": "thinking-time"},
            {"trigger": "vote", "source": "thinking-time", "dest": "voting"},
            {"trigger": "aggregate", "source": "voting", "dest": "end"},
        ]
        self.progress: Machine = Machine(
            states=states,
            transitions=transitions,
            initial="pre-game",
            auto_transitions=False,
        )
        self.channel: discord.TextChannel = channel
        self.host: Optional[User] = None
        self.red_team: List[User] = []
        self.blue_team: List[User] = []

    async def start(self):
        if self.progress.state == "in-game":
            await self.channel.send("ゲームが既に開始されています。")

        if len(self.red_team + self.blue_team) != 10:
            await self.channel.send("必要メンバー数に達していません。")
            return

        await self.channel.send("*** ゲームを開始します！ ***")
        self.progress.begin()

        # プレイヤがホストを兼任しているかどうかの確認
        self.is_host_playing: bool = self.host in self.red_team + self.blue_team

        # 人狼を決定する
        self.red_team[random.randint(0, 4)].is_wolf = True
        self.blue_team[random.randint(0, 4)].is_wolf = True

        # ホストに全情報を送信
        if not self.is_host_playing:
            await self.host.info.send(await self.generate_current_status_text(False))

        # テキストチャットに役職を伏せた全情報を送信
        await self.channel.send(await self.generate_current_status_text(True))

        # 個別にDMで連絡
        for player in self.red_team + self.blue_team:
            await player.info.send("あなたは{}です。".format("人狼" if player.is_wolf else "村人"))

        await self.channel.send(
            '*** 役職が決定されました！DMを確認してください\n***もしDMが届かない人がいる場合は"/restart"コマンドを実行してください。\nなお、DMを受け取らないように制限している場合は解除してください。'
        )

        # Ban/Pick相談 - 5分
        # TODO: パラメータを指定できるようにする
        await self.channel.send("*** ここから3分間のBan/Pick相談時間です ***")
        await self.asyncio.sleep(120)
        await self.channel.send("*** 残り1分です ***")
        await asyncio.sleep(60)

        # 試合開始コール
        await self.channel.send("*** 相談時間は終わりです。試合を開始してください。GLHF!! ***")
        self.progress.start()

    async def finish(self):
        if self.progress.state != "in-game":
            await self.channel.send("まだゲームは開始されていないようです。")
            return

        await self.channel.send("*** 試合お疲れさまでした！ ***")
        self.progress.finish()

        await self.channel.send("*** ここから5分間のシンキング・相談タイムです！ ***")
        await asyncio.sleep(240)
        await self.channel.send("*** 残り1分です ***")
        await asyncio.sleep(60)

        await self.channel.send("*** シンキング・相談タイム終了です ***")
        self.progress.vote()

        await self.channel.send(
            "*** 参加者の皆様は私にDMで投票する人の名前を教えてください。名前は正確に入力してくださいね！敬称は不要です！ ***"
        )

    async def aggregate(self):
        if self.progress.state != "voting":
            await self.channel.send("まだ投票期間では無いようです。")

        if sum([player.voted for player in self.red_team + self.blue_team]) != 10:
            await self.channel.send("投票数が足りないようです。現在の投票状況は/statusで確認することができます。")

        await self.channel.send("*** 結果発表です！ ***")

        # TODO: 点数計算などもここで行う
        await self.channel.send(await self.generate_current_status_text(False))

    async def generate_current_status_text(self, is_blind: bool) -> str:
        text: str = ""
        text += "===ホスト===\n"
        if self.host is not None:
            text += f"{self.host.info.name} さん\n"
        else:
            text += "不在\n"

        text += "\n===赤陣営===\n"
        for player in self.red_team:
            text += f"{player.info.name} さん: {player.voted}票"
            text += " 人狼\n" if not is_blind and player.is_wolf else "\n"

        text += "\n===青陣営===\n"
        for player in self.blue_team:
            text += f"{player.info.name} さん: {player.voted}票"
            text += " 人狼\n" if not is_blind and player.is_wolf else "\n"

        return text


client = discord.Client()
games: Dict[discord.TextChannel, Game] = {}


@client.event
async def on_ready():
    print("LoL人狼ボット起動しました")


@client.event
async def on_message(message: discord.Message):
    async def reply(text: str):
        reply = f"{message.author.mention} " + text
        await message.channel.send(reply)

    # bot自身の発言は無視する
    if message.author.bot:
        return

    channel: discord.TextChannel = message.channel
    author: User = User(message.author)

    # DMでの投票受付
    if (
        isinstance(message.channel, discord.DMChannel)
        and client.user == message.channel.me
    ):
        # IDEA: 投票し直しを実装するべきか？
        if author.is_vote:
            await author.info.send("既に投票されているようです。")

        # OPTIMIZE: この全検索、スケーラビリティやばそう
        for game in games.values():

            async def check_correct_vote(voter: User, team: List[User]) -> bool:
                if voter in team:
                    for player in team:
                        # あえて、自分に投票できる遊びを残しておく
                        if player.info.name == message.content:
                            voter.is_vote = True
                            player.voted += 1
                            await voter.info.send("再投票が正常に行われました。")
                            return True
                return False

            if check_correct_vote(author, game.red_team):
                return

            if check_correct_vote(author, game.blue_team):
                return

        await author.info.send("無効な投票です。")
        return

    # スラッシュから始まる文言以外は無視する
    if not message.content.startswith("/"):
        return

    # もしコマンド受付が初回だった場合はゲームオブジェクトを作成
    if channel not in games:
        games[channel] = Game(channel)

    # チャンネルで開催されているゲーム情報を全てリセットし、チャット履歴を抹消
    if message.content == "/reset":
        if author == games[channel].host:
            if channel in games:
                del games[channel]
            await channel.send("ゲームがリセットされました。")
        else:
            await channel.send("ゲームのリセットはホストのみが可能です。")
        return

    # ゲームのホストを登録
    if message.content.startswith("/host"):
        if games[channel].host is not None:
            await reply("ホストは既に登録済みです。")
        else:
            games[channel].host = author
            await reply("ホストとして登録されました。")
        return

    # ゲームの参加者を登録
    if message.content.startswith("/join"):
        # 既にどちらかの陣営に参加している場合
        if author in games[channel].blue_team + games[channel].red_team:
            await reply("既にゲームに参加されているようです。")
        else:
            # 赤陣営に追加
            if "red" in message.content:
                # 各陣営は5人まで
                if len(games[channel].red_team) >= 5:
                    await channel.send("赤陣営はいっぱいのようです。")
                    return

                games[channel].red_team.append(author)
                await reply("赤陣営に追加されました。")

            # 青陣営に追加
            elif "blue" in message.content:
                # 各陣営は5人まで
                if len(games[channel].blue_team) >= 5:
                    await reply("青陣営はいっぱいのようです。")
                    return

                games[channel].blue_team.append(author)
                await reply("青陣営に追加されました。")

            # 陣営が無効または入力されていない場合
            else:
                await reply('無効な陣営です。"red"もしくは"blue"で指定してください。')
        return

    if message.content == "/quit":
        # 赤陣営から抜ける
        if author in games[channel].red_team:
            games[channel].red_team.remove(author)
            await reply("赤陣営から抜けました。")

        # 青陣営から抜ける
        elif author in games[channel].blue_team:
            games[channel].blue_team.remove(author)
            await reply("青陣営から抜けました。")

        # ホストを辞める
        elif author == games[channel].host:
            games[channel].host = None
            await reply("ホストでは無くなりました。")

        # どちらの陣営でもない場合
        else:
            await reply("まだゲームに参加していないようです。")

        return

    if message.content == "/status":
        if author == games[channel].host:
            # ホストがこのコマンドを実行した場合、DMに追加の情報を送信する
            await author.info.send(
                await games[channel].generate_current_status_text(False)
            )
        await channel.send(await games[channel].generate_current_status_text(True))
        return

    if message.content == "/start":
        if author == games[channel].host:
            await games[channel].start()
        else:
            await reply("ゲーム開始はホストが行ってください。")
        return

    if message.content == "/restart":
        if author == games[channel].host:
            games[channel].is_start = False
            await games[channel].start()
        else:
            await reply("ゲームの再開始はホストが行ってください。")
        return

    if message.content == "/finish":
        if author == games[channel].host:
            await games[channel].finish()
        else:
            await reply("ゲーム終了はホストが行ってください。")
        return

    if message.content == "/aggregate":
        if author == games[channel].host:
            await games[channel].aggregate()
        else:
            await reply("集計要請はホストが行ってください。")
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
