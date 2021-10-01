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

    async def start(self, time: int = 180):
        if self.progress.state == "in-game":
            await self.channel.send(output["GameAlreadyBegin"][language])

        if len(self.red_team + self.blue_team) != 10:
            await self.channel.send(output["NotEnoughMember"][language])
            return

        await self.channel.send(output["BeginGame"][language])
        self.progress.begin()

        # プレイヤがホストを兼任しているかどうかの確認
        self.is_host_playing: bool = self.host in self.red_team + self.blue_team

        # 人狼を決定する
        self.red_team[random.randint(0, 0)].is_wolf = True
        self.blue_team[random.randint(0, 0)].is_wolf = True

        # ホストに全情報を送信(ホストがプレイヤでないときのみ)
        if not self.is_host_playing:
            await self.host.info.send(await self.current_status(False))

        # テキストチャットに役職を伏せた全情報を送信
        await self.channel.send(await self.current_status(True, True))

        # 個別にDMで連絡
        for player in self.red_team + self.blue_team:
            await player.info.send(
                output["WhatYouAre"][language].format(
                    output["werewolf"][language]
                    if player.is_wolf
                    else output["villager"][language]
                )
            )

        await self.channel.send(output["DecidedRoles"][language])

        # Ban/Pick相談
        await self.channel.send(output["AnnounceBanPick"][language].format(time))
        await asyncio.sleep(time)

        # 試合開始コール
        await self.channel.send(output["AnnounceStartGame"][language])
        self.progress.start()

    async def finish(self, time: int = 300):
        if self.progress.state != "in-game":
            await self.channel.send(output["WarningNotInGame"][language])
            return

        await self.channel.send(output["AnnounceGG"][language])
        self.progress.finish()

        await self.channel.send(
            output["AnnounceBeginThinkingTime"][language].format(time)
        )
        await asyncio.sleep(time)

        await self.channel.send(output["AnnounceEndThinkingTime"][language])
        self.progress.vote()

        await self.channel.send(output["AnnounceVoting"][language])

    async def aggregate(self):
        if self.progress.state != "voting":
            await self.channel.send(output["WarningNotInVoting"][language])
            return

        if sum([player.voted for player in self.red_team + self.blue_team]) != 10:
            await self.channel.send(output["NotEnoughVote"][language])
            return

        await self.channel.send(output["AnnounceResult"][language])

        # TODO: 点数計算などもここで行う
        await self.channel.send(await self.current_status(False, True))

    async def current_status(
        self, is_blind: bool = True, is_mention: bool = False
    ) -> str:
        text: str = ""
        text += "=== Host ===\n"
        if self.host is not None:
            text += (
                self.host.info.mention
                if is_mention
                else f"{self.host.info.display_name}"
            )
        else:
            text += "Not exist"
        text += "\n\n"

        def loop_player(text: str, team: List[User]) -> str:
            for player in team:
                text += player.info.mention if is_mention else f"{player.info.name}\t"
                text += f":\t{player.voted} voted "
                text += (
                    output["werewolf"][language]
                    if not is_blind and player.is_wolf
                    else "\n"
                )
            text += "\n"
            return text

        text += "=== Red Side ===\n"
        text = loop_player(text, self.red_team)

        text += "=== Blue Side ===\n"
        text = loop_player(text, self.blue_team)

        return text


client = discord.Client()
games: Dict[discord.TextChannel, Game] = {}
output = json.load(open("OutputMessage.json", "r"))
language = "ja"


@client.event
async def on_ready():
    print("Bot Started")


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

        async def check_correct_vote(voter: User, team: List[User]) -> bool:
            if voter not in team:
                return False

            # IDEA: 投票し直しを実装するべきか？
            i = team.index(voter)
            if team[i].is_vote:
                await voter.info.send(output["AlreadyVoted"][language])

            for player in team:
                if player.info.name == message.content:
                    team[i].is_vote = True
                    player.voted += 1
                    await voter.info.send(output["VoteAccepted"][language])
                    return True
            return False

        # OPTIMIZE: この全検索、スケーラビリティやばそう
        for game in games.values():
            if game.progress.state == "voting":
                if await check_correct_vote(author, game.red_team):
                    return
                if await check_correct_vote(author, game.blue_team):
                    return

        await author.info.send(output["WarningInvalidVote"][language])
        return

    # スラッシュから始まる文言以外は無視する
    if not message.content.startswith("/"):
        return

    # もしコマンド受付が初回だった場合はゲームオブジェクトを作成
    if channel not in games:
        games[channel] = Game(channel)

    # チャンネルで開催されているゲーム情報を全てリセット
    if message.content == "/reset":
        if games[channel].host is not None and author == games[channel].host:
            if channel in games:
                del games[channel]
            await channel.send(output["ResetGame"][language])
        else:
            await reply(output["WarningHostOnly"][language])
        return

    # ゲームのホストを登録
    if message.content.startswith("/host"):
        if games[channel].host is not None:
            await reply(output["HostAlreadyJoined"][language])
        else:
            games[channel].host = author
            await reply(output["HostJoined"][language])
        return

    # ゲームの参加者を登録
    if message.content.startswith("/join"):
        # 既にどちらかの陣営に参加している場合
        if author in games[channel].blue_team + games[channel].red_team:
            await reply(output["AlreadyJoined"][language])
        else:
            # 赤陣営に追加
            if "red" in message.content:
                # 各陣営は5人まで
                if len(games[channel].red_team) >= 5:
                    await channel.send(output["RedTeamFull"][language])
                    return

                games[channel].red_team.append(author)
                await reply(output["RedTeamJoined"][language])

            # 青陣営に追加
            elif "blue" in message.content:
                # 各陣営は5人まで
                if len(games[channel].blue_team) >= 5:
                    await reply(output["BlueTeamFull"][language])
                    return

                games[channel].blue_team.append(author)
                await reply(output["BlueTeamJoined"][language])

            # 陣営が無効または入力されていない場合
            else:
                await reply(output["WarningInvalidTeam"][language])
        return

    if message.content == "/quit":
        # 赤陣営から抜ける
        if author in games[channel].red_team:
            games[channel].red_team.remove(author)
            await reply(output["QuitGame"][language])

        # 青陣営から抜ける
        elif author in games[channel].blue_team:
            games[channel].blue_team.remove(author)
            await reply(output["QuitGame"][language])

        # ホストを辞める
        elif author == games[channel].host:
            games[channel].host = None
            await reply(output["QuitGame"][language])

        # どちらの陣営でもない場合
        else:
            await reply(output["NotJoinedYet"][language])
        return

    if message.content == "/status":
        await channel.send(await games[channel].current_status(True))
        return

    if message.content == "/start":
        if author == games[channel].host:
            await games[channel].start()
        else:
            await reply(output["WarningHostOnly"][language])
        return

    if message.content == "/restart":
        await reply("すみません、こちらは未実装です。")
        # if author == games[channel].host:
        #     games[channel].is_start = False
        #     await games[channel].start()
        # else:
        #     await reply(output["WarningHostOnly"][language])
        return

    if message.content == "/finish":
        if author == games[channel].host:
            await games[channel].finish()
        else:
            await reply(output["WarningHostOnly"][language])
        return

    if message.content == "/aggregate":
        if author == games[channel].host:
            await games[channel].aggregate()
        else:
            await reply(output["WarningHostOnly"][language])
        return

    if message.content == "/help":
        await channel.send(output["HelpMessage"][language])
        return

    # どのコマンドにも一致しない場合
    await reply(output["HelpMessage2"][language])


client.run(TOKEN)
