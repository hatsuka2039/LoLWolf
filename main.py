import discord
import random
import asyncio
import os
import json
import urllib
import requests
from transitions import Machine
from typing import List, Dict, Optional

TOKEN = os.environ["DISCORD_TOKEN"]
# RIOT_API_KEY = os.environ["RIOT_API_KEY"]
RIOT_API_KEY = "RGAPI-476cb5df-154e-426c-bfaf-b47ca4e1023a"

# TODO: 後々RiotAPIと連携してチャンピオンとリンクできるようにしたい
# TODO: Discordの表示名を自動的にチャンピオン名に変更するようになるといいね
# TODO: 設定はどこかで弄れるようにしたいね


class User(object):
    def __init__(self, info: discord.Member):
        self.info: discord.Member = info
        self.is_wolf: bool = False
        self.is_vote: bool = False
        self.is_votable: bool = True
        self.voted_to: int = -1
        self.voted_from: int = 0
        self.summoner_name: Optional[str] = None
        self.summoner_id: Optional[str] = None
        self.champion_name: Optional[str] = None
        self.position: str = "mid"
        self.display_name = self.info.display_name

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, User):
            raise NotImplementedError("Different type equality check happned.")
        return self.info == other.info


class Game(object):
    MAX_TEAMMATES = 5

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
        self.blue_team: List[User] = []
        self.red_team: List[User] = []

    def only_host(func):
        async def wrapper(self, user: User, *args, **kwargs):
            if not await self._is_host(user):
                await self._reply(user, output["WarningHostOnly"][language])
                return
            await func(self, user, *args, **kwargs)

        return wrapper

    def only_player(func):
        async def wrapper(self, user: User, *args, **kwargs):
            if not await self._is_player(user):
                await self._reply(user, "プレイヤーのみ実行できます。")
                return
            await func(self, user, *args, **kwargs)

        return wrapper

    async def _send_dm_all_(self, text: str):
        for player in self.blue_team + self.red_team:
            await player.info.send(text)

    async def _send_dm_team(self, text: str, team: str):
        if team == "blue":
            for player in self.blue_team:
                await player.info.send(text)
        elif team == "red":
            for player in self.red_team:
                await player.info.send(text)
        else:
            raise RuntimeError("Invalid Team Color")

    async def _reply(self, user: User, text: str):
        text_m = f"{user.info.mention} " + text
        await self.channel.send(text_m)

    async def _is_host(self, user: User) -> bool:
        return self.host is not None and user == self.host

    async def _is_in_blue(self, user: User) -> bool:
        return user in self.blue_team

    async def _is_in_red(self, user: User) -> bool:
        return user in self.red_team

    async def _is_player(self, user: User) -> bool:
        return await self._is_in_blue(user) or await self._is_in_red(user)

    async def is_exist(self, user: User) -> bool:
        return await self._is_host(user) or await self._is_player(user)

    async def join_as_host(self, user: User):
        if self.host is None:
            self.host = user
            await self._reply(user, "ホストとして登録されました。")
        else:
            await self._reply(user, "既にホストがいます。")

    async def join_as_player(self, user: User, team: str):
        if self.progress.state != "pre-game":
            await self._reply(user, "pre-game中では無いため、参加できません。")
            return

        if await self._is_player(user):
            await self._reply(user, output["AlreadyJoined"][language])
            return

        if team == "blue":
            if len(self.blue_team) >= Game.MAX_TEAMMATES:
                await self._reply(user, output["BlueTeamFull"][language])
                return

            self.blue_team.append(user)
            await self._reply(user, output["BlueTeamJoined"][language])
            await user.info.send("/name [あなたのサモナーネーム]で名前を教えてください。")
        elif team == "red":
            if len(self.red_team) >= Game.MAX_TEAMMATES:
                await self._reply(user, output["RedTeamFull"][language])
                return

            self.red_team.append(user)
            await self._reply(user, output["RedTeamJoined"][language])
            await user.info.send("/name [あなたのサモナーネーム]で名前を教えてください。")
        else:
            await self._reply(user, output["WarningInvalidTeam"][language])

    @only_player
    async def inform_summoner_name(self, user: User, summoner_name: str):
        url = "https://jp1.api.riotgames.com/lol/summoner/v4/summoners/by-name/{}".format(
            urllib.parse.quote(summoner_name)
        )
        api_key = "?api_key={}".format(RIOT_API_KEY)

        result = requests.get(url + api_key)

        if result.status_code == 404:
            await user.info.send("サモナーが見つかりませんでした。名前はあっていますか？")
            return

        if result.status_code != 200:
            await user.info.send("何らかの問題により、Riot APIが正常に完了しませんでした。(エラーコード: {})".format(result.status_code))
            return

        if await self._is_in_blue(user):
            index = self.blue_team.index(user)
            if self.blue_team[index].summoner_name is None:
                await user.info.send("サモナーネームとして{}が登録されました。".format(summoner_name))
            else:
                await user.info.send("サモナーネームとして{}が再登録されました。".format(summoner_name))

            self.blue_team[index].summoner_name = summoner_name
            self.blue_team[index].summoner_id = result.json()["id"]
        else:
            index = self.red_team.index(user)
            if self.red_team[index].summoner_name is None:
                await user.info.send("サモナーネームとして{}が登録されました。".format(summoner_name))
            else:
                await user.info.send("サモナーネームとして{}が再登録されました。".format(summoner_name))
            self.red_team[index].summoner_name = summoner_name
            self.red_team[index].summoner_id = result.json()["id"]

    @only_host
    async def quit_host(self, user: User):
        if self.progress.state != "pre-game":
            await self._reply(user, "pre-game中では無いため、抜けられません。")
            return

        self.host = None
        await self._reply(user, "ホストを辞めました。")

    @only_player
    async def quit_player(self, user: User, team: str):
        if self.progress.state != "pre-game":
            await self._reply(user, "pre-game中では無いため、抜けられません。")
            return

        if team not in ["red", "blue"]:
            await self._reply(user, output["WarningInvalidTeam"][language])
            return

        if await self._is_in_blue(user):
            self.blue_team.remove(user)
        else:
            self.red_team.remove(user)
        await self._reply(user, "プレイヤーを辞めました。")

    @only_host
    async def reset(self, user: User):
        self.host = None
        self.blue_team = []
        self.red_team = []
        self.progress.set_state("pre-game")
        await self.channel.send("ゲームがリセットされました。")

    @only_host
    async def start(self, user: User, time: int = 180):
        if time <= 0 or time > 600:
            await self.channel.send("指定可能な秒数は600までです。")
            return

        if self.progress.state != "pre-game":
            await self.channel.send("開始可能な状態ではありません。")
            return

        if self.progress.state == "in-game":
            await self.channel.send(output["GameAlreadyBegin"][language])
            return

        if len(self.blue_team + self.red_team) != 2 * Game.MAX_TEAMMATES:
            await self.channel.send(output["NotEnoughMember"][language])
            return

        for player in self.blue_team + self.red_team:
            if player.summoner_name is None:
                await self.channel.send("サモナーネーム未登録のプレイヤーがいます。")
                return

        await self.channel.send(output["BeginGame"][language])
        self.progress.begin()

        # プレイヤがホストを兼任しているかどうかの確認
        self.is_host_playing: bool = self.host in self.red_team + self.blue_team

        # 人狼を決定する
        self.red_team[random.randint(0, Game.MAX_TEAMMATES - 1)].is_wolf = True
        self.blue_team[random.randint(0, Game.MAX_TEAMMATES - 1)].is_wolf = True

        # ホストに全情報を送信(ホストがプレイヤでないときのみ)
        if not self.is_host_playing:
            await self.host.info.send(await self.get_current_status(False))

        # テキストチャットに役職を伏せた全情報を送信
        await self.channel.send(await self.get_current_status(True, True))

        # 個別にDMで連絡
        for player in self.red_team + self.blue_team:
            await player.info.send(
                output["WhatYouAre"][language].format(
                    output["werewolf"][language] if player.is_wolf else output["villager"][language]
                )
            )

        await self.channel.send(output["DecidedRoles"][language])

        # Ban/Pick相談
        await self.channel.send(output["AnnounceBanPick"][language].format(time))
        await asyncio.sleep(time)
        if self.progress.state != "ban-pick":
            return

        # 試合開始コール
        await self.channel.send(output["AnnounceStartGame"][language])
        self.progress.start()

        count: int = 0
        while self.progress.state == "in-game" or count >= 30:
            if count % 5 == 0:
                await self.channel.send("アクティブなゲームを探しています。")

            await asyncio.sleep(30)

            url = "https://jp1.api.riotgames.com/lol/spectator/v4/active-games/by-summoner/{}".format(
                self.red_team[0].summoner_id
            )
            api_key = "?api_key={}".format(RIOT_API_KEY)
            result = requests.get(url + api_key)
            count += 1

            if result.status_code != 200:
                print("Not in active")
                continue

            summoners = result.json()["participants"]
            summoner_names = set([summoner["summonerName"] for summoner in summoners])
            informed_names = set([player.summoner_name for player in self.blue_team + self.red_team])
            print(summoner_names)
            print(informed_names)

            if summoner_names != informed_names:
                # TODO: 途中で修正できるようにする -> リアクションなどで簡単に修正できると良いか？
                await self.channel.send("申請されたサモナーネームと異なるサモナーを見つけました。\n表示名自動変更をオフにします。")
                return

            await self.channel.send("アクティブなゲームを見つけました！\n皆さんの表示名を一時的にチャンピオン名に変更します！")
            for player in self.blue_team + self.red_team:
                for summoner in summoners:
                    if summoner["summonerName"] == player.summoner_name:
                        for champion in champions.values():
                            if int(champion["key"]) == summoner["championId"]:
                                player.champion_name = champion["name"]
                                await player.info.edit(nick=champion["name"])
                                break
            return

    @only_host
    async def restart(self, user: User):
        await self.channel.send("すみません、こちらは未実装です。")

    @only_host
    async def finish(self, user: User, time: int = 300):
        if time <= 0 or time > 600:
            await self.channel.send("指定可能な秒数は600までです。")
            return

        if self.progress.state != "in-game":
            await self.channel.send(output["WarningNotInGame"][language])
            return

        await self.channel.send(output["AnnounceGG"][language])
        self.progress.finish()

        await self.channel.send(output["AnnounceBeginThinkingTime"][language].format(time))
        await asyncio.sleep(time)
        if self.progress.state != "thinking-time":
            return

        await self.channel.send(output["AnnounceEndThinkingTime"][language])
        self.progress.vote()

        await self.channel.send(output["AnnounceVoting"][language])

    @only_host
    async def aggregate(self, user: User):
        if self.progress.state != "voting":
            await self.channel.send(output["WarningNotInVoting"][language])
            return

        if sum([player.voted_from for player in self.red_team + self.blue_team]) != 2 * Game.MAX_TEAMMATES:
            await self.channel.send(output["NotEnoughVote"][language])
            return

        # TODO: 同票数がいる場合に再投票の処理
        # TODO: 点数計算

        await self.channel.send(output["AnnounceResult"][language])
        # TODO: 画像を出力
        # await self.channel.send(await self.get_current_status(False, True))

        self.progress.aggregate()

        for player in self.blue_team + self.red_team:
            await player.info.edit(nick=player.display_name)

    @only_player
    async def vote(self, voter: User, vote_to: int) -> bool:
        if self.progress.state != "voting":
            await voter.info.send("投票期間ではありません。")
            return False

        if vote_to <= 0 or vote_to > Game.MAX_TEAMMATES:
            await voter.info.send("無効な投票先です。")
            return False

        team = self.red_team if voter in self.red_team else self.blue_team
        i = team.index(voter)

        # 既に投票済みの場合
        if team[i].is_vote:
            await voter.info.send(output["AlreadyVoted"][language])
            return False

        # 投票不可能な対象の場合 (再投票の場合など)
        if not team[vote_to - 1].is_votable:
            await voter.info.send("投票不可能な対象です。")
            return False

        team[i].is_vote = True
        team[i].voted_to = vote_to - 1
        team[vote_to - 1].voted_from += 1
        await voter.info.send(output["VoteAccepted"][language])
        return True

    async def get_current_status(self, is_blind: bool = True, is_mention: bool = False):
        text = "=== Game Stats ===\n"
        text += self.progress.state
        text += "\n\n=== Host ===\n"
        if self.host is not None:
            text += self.host.info.mention if is_mention else f"{self.host.info.display_name}"
        else:
            text += "Not exist"
        text += "\n\n"

        def loop_player(text: str, team: List[User]) -> str:
            for i, player in enumerate(team):
                text += "Player{} ({}):\t".format(i + 1, player.champion_name)
                text += player.info.mention if is_mention else f"{player.info.display_name}"
                text += "({})".format(player.summoner_name)
                text += "\t{}".format("投票済み" if player.is_vote else "未投票")
                text += "\t" + output["werewolf"][language] if not is_blind and player.is_wolf else ""
                text += "\n"
            text += "\n"
            return text

        text += "=== Blue Side (Left Side) ===\n"
        text = loop_player(text, self.blue_team)

        text += "=== Red Side (Right Side) ===\n"
        text = loop_player(text, self.red_team)

        return text


client = discord.Client()
games: Dict[discord.TextChannel, Game] = {}
champions = json.load(open("resources/champion.json"))["data"]
output = json.load(open("OutputMessage.json", "r"))
language = "ja"


@client.event
async def on_ready():
    print("Bot Started")


@client.event
async def on_message(message: discord.Message):

    # bot自身の発言は無視する
    if message.author.bot:
        return

    # スラッシュから始まる文言以外は無視する
    if not message.content.startswith("/"):
        return

    channel: discord.TextChannel = message.channel
    author: User = User(message.author)
    commands = message.content.split()

    # DMでのコマンド
    if isinstance(message.channel, discord.DMChannel) and client.user == message.channel.me:
        if commands[0] == "/vote":
            if len(commands) != 2 or not commands[1].isdecimal():
                await author.info.send("投票先を整数で入力してください。")
                return

            for game in games.values():
                if await game.is_exist(author) and await game.vote(author, int(commands[1])):
                    return
            return

        if commands[0] == "/name":
            if len(commands) != 2:
                await author.info.send("サモナーネームを入力してください。")
                return

            for game in games.values():
                if await game.is_exist(author):
                    await game.inform_summoner_name(author, commands[1])
                    return

        return

    # もしコマンド受付が初回だった場合はゲームオブジェクトを作成
    if channel not in games:
        games[channel] = Game(channel)

    # チャンネルで開催されているゲーム情報を全てリセット
    if commands[0] == "/reset":
        await games[channel].reset(author)
        return

    if commands[0] == "/join":
        if len(commands) != 2:
            await channel.send(author.info.mention + "無効なコマンドです。")
            return

        if commands[1] == "host":
            await games[channel].join_as_host(author)
        else:
            await games[channel].join_as_player(author, commands[1])
        return

    if commands[0] == "/quit":
        if len(commands) != 2:
            await channel.send(author.info.mention + "無効なコマンドです。")
            return

        if commands[1] == "host":
            await games[channel].quit_host(author)
        else:
            await games[channel].quit_player(author, commands[1])
        return

    if commands[0] == "/status":
        await channel.send(await games[channel].get_current_status(True))
        return

    if commands[0] == "/start":
        if len(commands) == 2:
            if commands[1].isdecimal():
                await games[channel].start(author, int(commands[1]))
            else:
                await channel.send("不正な引数です。")
        else:
            await games[channel].start(author)
        return

    if commands[0] == "/restart":
        await games[channel].restart(author)
        return

    if commands[0] == "/finish":
        if len(commands) == 2:
            if commands[1].isdecimal():
                await games[channel].finish(author, int(commands[1]))
            else:
                await channel.send("不正な引数です。")
        else:
            await games[channel].finish(author)
        return

    if commands[0] == "/aggregate":
        await games[channel].aggregate(author)
        return

    if commands[0] == "/help":
        await channel.send(output["HelpMessage"][language])
        return

    # どのコマンドにも一致しない場合
    await channel.send(output["HelpMessage2"][language])


client.run(TOKEN)
