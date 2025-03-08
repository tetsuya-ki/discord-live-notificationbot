from datetime import timedelta, timezone
from discord.ext import tasks, commands
from discord import app_commands
from logging import getLogger
from collections import Counter
from .modules.live_notification import LiveNotification
from .modules import setting
from typing import Literal

import datetime, discord, re

LOG = getLogger('live-notification-bot')


# コグとして用いるクラスを定義。
class LiveNotificationCog(commands.Cog):
    # guilds = [] if setting.ENABLE_SLASH_COMMAND_GUILD_ID_LIST is None else list(
    #     map(int, setting.ENABLE_SLASH_COMMAND_GUILD_ID_LIST.split(';')))
    guilds = setting.ENABLE_SLASH_COMMAND_GUILD_ID
    SHOW_ME = '自分のみ'

    # LiveNotificationCogクラスのコンストラクタ。Botを受取り、インスタンス変数として保持。
    def __init__(self, bot):
        self.bot = bot
        self.liveNotification = LiveNotification(bot)
        self.JST = timezone(timedelta(hours=+9), 'JST')
        self.FILTERWORD_MAX_SIZE = 1500
        self.task_is_excuting = False
        self.ng_counter = Counter()

    # 読み込まれた時の処理
    @commands.Cog.listener()
    async def on_ready(self):
        await self.liveNotification.prepare()  # dbを作成
        LOG.info(f'SQlite準備完了/NG回数:{str(setting.NG_MAX_COUNT)}/ギルド件数:{len(self.bot.guilds)}')
        LOG.info(self.bot.guilds)
        if not self.printer.is_running():
            self.task_is_excuting = False
            await self.printer.start()
            # self.printer.restart()
        elif self.task_is_excuting:
            self.task_is_excuting = False
            # self.printer.stop()
            self.printer.cancel()
            # await self.printer.start()
            self.printer.restart()

    def cog_unload(self):
        self.printer.cancel()

    @tasks.loop(seconds=120.0)
    async def printer(self):
        now = datetime.datetime.now(self.JST)
        # すでに起動していたら、何もしない
        if self.task_is_excuting:
            LOG.warning(f'printer is already kicked.({now})')
            return
        else:
            # 実行中とする
            LOG.info(f'printer is kicked.({now})')
            self.task_is_excuting = True

        try:
            # liveの分だけ確認していく
            task_count = 0
            task_count_all = 0
            for live in self.liveNotification.live_rows:
                result_dict_list = None
                if live['type_id'] == self.liveNotification.TYPE_YOUTUBE:
                    # V2の場合、YouTubeだけはそこそこ制限して取得
                    if setting.LIVE_NOTIFICATION_V2:
                        live_youtube_list = self.liveNotification.get_live_youtube(live['channel_id'])
                        if live_youtube_list:
                            # TODO:お試しで表示しておく。
                            LOG.info(f'''{live['channel_id']}: list num -> {str(len(live_youtube_list))}''')
                            for live_youtube in live_youtube_list:
                                result_dict_list = await self.liveNotification.get_youtube(live_youtube[0], live_youtube[1], None, True)
                                task_count += 1
                                task_count_all += 1
                    else:
                        result_dict_list = await self.liveNotification.get_youtube_old(live['channel_id'], live['recent_id'], live['recent_movie_length'], live['updated_at'])
                        task_count_all += 1
                        # ループ中に何度も更新しないように、最新の動画を更新しておく
                        if result_dict_list is not None and len(result_dict_list) > 0:
                            live['recent_id'] = result_dict_list[0]['recent_id']
                            task_count = task_count + 1
                    message_suffix = 'の動画が追加されました！'
                elif live['type_id'] == self.liveNotification.TYPE_NICOLIVE and not setting.EXCLUDE_NICONICO:
                    result_dict_list = await self.liveNotification.get_nicolive(live['channel_id'], live['recent_id'])
                    task_count_all += 1
                    # ループ中に何度も更新しないように、最新の動画を更新しておく
                    if result_dict_list is not None and len(result_dict_list) > 0:
                        task_count = task_count + 1
                    message_suffix = 'の配信が開始されました！'
                elif live['type_id'] == self.liveNotification.TYPE_TWITCASTING:
                    result_dict_list = await self.liveNotification.get_twitcasting(live['channel_id'], live['recent_id'])
                    task_count_all += 1
                    message_suffix = 'の配信が開始されました！'
                    # ループ中に何度も更新しないように、最新の動画を更新しておく
                    if result_dict_list is not None and len(result_dict_list) > 0:
                        task_count = task_count + 1

                if result_dict_list is None or len(result_dict_list) == 0:
                    continue
                else:
                    # notificationの分だけ確認していく
                    for notification in self.liveNotification.notification_rows:
                        if live['id'] == notification['live_id']:
                            for result_dict in result_dict_list:
                                # いろいろ設定
                                video_title,watch_url,message = self.liveNotification.get_by_result_dict(notification['name'],result_dict,live['title'],message_suffix)

                                # 説明文短縮処理
                                description = self.liveNotification.make_description(result_dict.get('description'), live['title'], notification['long_description'] == 'True')
                                LOG.info(description)

                                # フィルター処理
                                if notification['filter_words'] is not None:
                                    filter_word_list = notification['filter_words'].split(',')
                                    filter_continue_flag = False
                                    target_message = video_title+description
                                    for filter_word in filter_word_list:
                                        if filter_word in target_message:
                                            filter_continue_flag = True
                                    if filter_continue_flag:
                                        LOG.info(f'''notification:{notification['id']}, nitification_user_id:{notification['user_id']}はフィルタで切り捨てられました。\n{watch_url}''')
                                        continue

                                # embedを作成
                                embed = self.liveNotification.make_embed_from_dict(description, result_dict)

                                # メンション処理
                                mention = notification['mention'] if notification['mention'] is not None else ''

                                # DMの処理(notification_guild, notification_channelがNoneならDM扱い)
                                if notification['notification_guild'] is None and notification['notification_channel'] is None:
                                    dm = await self.create_dm(notification['discord_user_id'])
                                    try:
                                        await dm.send(f'{mention} {message}', embed=embed)
                                        LOG.info(f'''{notification['name']}をDMに通知-> {watch_url} ''')
                                    except Exception as e:
                                        self.ng_counter[notification['discord_user_id']] += 1
                                        LOG.error(f'''DMに対する投稿関連処理でエラーが発生({self.ng_counter[notification['discord_user_id']]}回目)->{notification['discord_user_id']}(user:{notification['user_id']})''')
                                        LOG.error(e)
                                    finally:
                                        # NG回数がリミットを超えた場合、NGとする
                                        if self.ng_counter.get(notification['discord_user_id']) is not None and self.ng_counter.get(notification['discord_user_id']) >= setting.NG_MAX_COUNT:
                                            LOG.info(f'''NG回数リミット超え: {notification['discord_user_id']}({notification['user_id']})''')
                                            self.liveNotification.logic_delete_user(notification['user_id'])
                                            # Bot管理者にお知らせ
                                            try:
                                                alert_message = f'''notification_id: {notification['id']}の通知先「DM({notification['user_id']})」は権限不足などの原因で通知できませんでした({notification['name']} - {live['title']})\n動画名: {video_title}\nURL: {watch_url}\n{limit_msg}'''
                                                get_control_channel = discord.utils.get(self.bot.get_all_channels(),guild__id=self.liveNotification.saved_dm_guild,name=self.liveNotification.LIVE_CONTROL_CHANNEL)
                                                await get_control_channel.send(alert_message)
                                            except Exception as e:
                                                LOG.error(e)
                                else:
                                    channel = discord.utils.get(self.bot.get_all_channels(),
                                                                guild__id=notification['notification_guild'],
                                                                id=notification['notification_channel'])
                                    target = f'''-> guild: {notification['notification_guild']}, channel: {notification['notification_channel']}'''
                                    try:
                                        if channel is not None:
                                            await channel.send(f'{mention} {message}', embed=embed)
                                            LOG.info(f'''{notification['name']}をCHに通知-> {watch_url} P1 {target}''')
                                        else:
                                            # target_guildを取得(見つからないならfetchする)
                                            target_guild = self.bot.get_guild(notification['notification_guild'])
                                            if target_guild is None:
                                                LOG.info(f'''ギルドが見つからないのでfetchする -> guild: {notification['notification_guild']}''')
                                                try:
                                                    target_guild = await self.bot.fetch_guild(notification['notification_guild'])
                                                except:
                                                    pass

                                            # ギルドを取得し、チャンネルに投稿していく
                                            if target_guild is not None:
                                                # TODO:ギルド
                                                LOG.info(type(target_guild))
                                                LOG.info(target_guild)

                                                # チャンネルの取得
                                                target_channel = None
                                                if hasattr(target_guild, 'get_channel_or_thread'):
                                                    target_channel = target_guild.get_channel_or_thread(notification['notification_channel'])
                                                else:
                                                    LOG.warning('target_guild.get_channel_or_threadがないよ')
                                                    LOG.info(f'''get_channel_or_threadがないし、ギルドが見つからないのでfetchする -> guild: {notification['notification_guild']}''')
                                                    try:
                                                        target_guild = await self.bot.fetch_guild(notification['notification_guild'])
                                                    except:
                                                        pass
                                                if target_channel is None and target_guild is not None and hasattr(target_guild, 'fetch_channel'):
                                                    target_channel = await target_guild.fetch_channel(notification['notification_channel'])

                                                # チャンネルへ書き込み
                                                if target_channel is not None:
                                                    await target_channel.send(f'{mention} {message}', embed=embed)
                                                    LOG.info(f'''{notification['name']}をCHに通知-> {watch_url} P2 {target}''')
                                                else:
                                                    self.ng_counter[notification['notification_guild']] += 1
                                                    LOG.error(f'''ギルドはあるが、チャンネルが結局見つからない({self.ng_counter[notification['notification_guild']]}回目)。。。。 {target}''')
                                            else:
                                                self.ng_counter[notification['notification_guild']] += 1
                                                LOG.error(f'''結局ギルドが見つからない({self.ng_counter[notification['notification_guild']]}回目)。。。。 {target}''')
                                    except discord.errors.Forbidden:
                                        try:
                                            self.ng_counter[notification['notification_guild']] += 1
                                            alert_message = f'''notification_id: {notification['id']}の通知先「{notification['notification_guild']}/{notification['notification_channel']}(<#{notification['notification_channel']}>)」は権限不足などの原因で通知できませんでした({notification['name']} - {live['title']})\n動画名: {video_title}\nURL: {watch_url}\n通知先のチャンネルの権限見直しをお願いします。'''
                                            LOG.error(alert_message + f'''\n({self.ng_counter[notification['notification_guild']]}回目)''')

                                            # Bot管理者にお知らせ(別にいらないか...)
                                            # get_control_channel = discord.utils.get(self.bot.get_all_channels(),guild__id=self.liveNotification.saved_dm_guild,name=self.liveNotification.LIVE_CONTROL_CHANNEL)
                                            # await get_control_channel.send(alert_message)

                                            # 利用者にお知らせ
                                            dm = await self.create_dm(notification['discord_user_id'])
                                            await dm.send(alert_message)
                                        except Exception as e:
                                            msg = f'＊＊＊さらに、{self.liveNotification.saved_dm_guild}のチャンネル({self.liveNotification.LIVE_CONTROL_CHANNEL})への投稿に失敗しました！＊＊＊'
                                            LOG.error(msg)
                                            LOG.info(type(e))
                                            LOG.error(e)
                                            continue
                                        continue
                                    except (discord.errors.NotFound, discord.NotFound) as ne:
                                        self.ng_counter[notification['notification_guild']] += 1
                                        LOG.error(f'''投稿関連処理でNotFoundエラーが発生({self.ng_counter[notification['notification_guild']]}回目)->{notification['notification_guild']}''')
                                        LOG.error(ne)
                                    except Exception as e:
                                        self.ng_counter[notification['notification_guild']] += 1
                                        LOG.error(f'''投稿関連処理でForbidden以外のエラーが発生({self.ng_counter[notification['notification_guild']]}回目)->{notification['notification_guild']}''')
                                        LOG.error(e)
                                        continue
                                    finally:
                                        # NG回数がリミットを超えた場合、NGとする
                                        if self.ng_counter.get(notification['notification_guild']) is not None and self.ng_counter.get(notification['notification_guild']) >= setting.NG_MAX_COUNT:
                                            limit_msg = f'''NG回数リミット超え: guild: {notification['notification_guild']}, {notification['discord_user_id']} (user: {notification['user_id']})'''
                                            LOG.info(limit_msg)
                                            msg2 = await self.liveNotification.logic_delete_user(notification['user_id'])
                                            LOG.info(msg2)
                                            guild = None
                                            # Bot管理者にお知らせ
                                            try:
                                                guild = await self.bot.fetch_guild(notification['notification_guild'])
                                                LOG.info(f'''お知らせのため、ギルド取得({notification['notification_guild']})''')
                                            except Exception as e:
                                                LOG.error(e)
                                            finally:
                                                guild_name = f'''不明なギルド({notification['notification_guild']})'''
                                                channel_name = f'''不明なチャンネル({notification['notification_channel']})'''
                                                if guild is not None and hasattr(guild, 'name'):
                                                    guild_name = guild.name
                                                    if channel is not None:
                                                        channel_name = channel.name
                                                alert_message = f'''notification_id: {notification['id']}の通知先「{guild_name}/{channel_name}」は権限不足などの原因で通知できませんでした({notification['name']} - {live['title']})\n動画名: {video_title}\nURL: {watch_url}\n{limit_msg}'''
                                                get_control_channel = discord.utils.get(self.bot.get_all_channels(),guild__id=self.liveNotification.saved_dm_guild,name=self.liveNotification.LIVE_CONTROL_CHANNEL)
                                                await get_control_channel.send(alert_message)
            after = datetime.datetime.now(self.JST)
            sec = after - now
            # notificationを全て通知したら、ログを出力 & task_is_excutingをFalseにする
            LOG.info(f'task is finished.{str(sec.seconds)}[sec].tasks={str(task_count)}.tasks(all)={str(task_count_all)}.')
            self.task_is_excuting = False
        except Exception as e:
            if 'notification' in locals() and notification is not None:
                self.ng_counter[notification['notification_guild']] += 1
                LOG.error(f'''なにかエラーが発生-> guild: {notification['notification_guild']}, channel: {notification['notification_channel']}''')
            else:
                LOG.error('不明なエラーが発生')
            LOG.error(e)
            self.printer.cancel()
            self.printer.restart()
            self.task_is_excuting = False
        finally:
            pass

    @app_commands.command(
        name='live-notification_add',
        description='配信通知(YouTube,ニコ生,ツイキャス)を作成する')
    @app_commands.describe(
        live_channel_id='YouTubeかニコ生のチャンネルID、またはツイキャスユーザーID。もしくはURL(＊非公開のニコ生コミュニティは登録失敗します)')
    @app_commands.describe(
        notification_chanel='通知するチャンネル(#general等。「DM」でBotとのDMへ登録されます。未指定の場合は登録したチャンネルに投稿)')
    @app_commands.describe(
        mention='通知する際のメンション(@XXXX, @here, @everyone)')
    @app_commands.describe(
        reply_is_hidden='Botの実行結果を全員に見せるどうか(配信通知自体は普通です/他の人にも配信通知登録を使わせたい場合、全員に見せる方がオススメです))')
    async def live_notification_add(self,
                        interaction: discord.Interaction,
                        live_channel_id: str,
                        notification_chanel: str = None,
                        mention: str = None,
                        reply_is_hidden: Literal['自分のみ', '全員に見せる'] = SHOW_ME):
        LOG.info('live-notificationをaddするぜ！')
        hidden = True if reply_is_hidden == self.SHOW_ME else False
        await self.check_printer_is_running()

        # ギルドの設定
        if interaction.guild is not None:
            guild_id = interaction.guild.id
        else:
            if notification_chanel is not None and notification_chanel.upper() != 'DM':
                msg = 'DMでチャンネル指定はできません。チャンネルは未指定で配信通知を登録ください。'
                await interaction.response.send_message(msg, ephemeral=True)
                LOG.info(msg)
                return

            notification_chanel,guild_id = None,None

        # チャンネルの設定(指定なしなら投稿されたチャンネル、指定があればそちらのチャンネルとする)
        channel_id = None
        if notification_chanel is not None:
            temp_channel = discord.utils.get(interaction.guild.text_channels, name=notification_chanel)
            if notification_chanel.upper() == 'DM': # チャンネルが'DM'なら、ギルドとチャンネルをNoneとする
                guild_id = None
                if self.liveNotification.saved_dm_guild is None:
                    msg = 'ギルドが何も登録されていない段階で、DMを登録することはできません。ギルドを登録してから再度、配信通知の登録をしてください。'
                    await interaction.response.send_message(msg, ephemeral=True)
                    LOG.info(msg)
                    return

            elif temp_channel is None:
                temp_channel_id = re.sub(r'[<#>]', '', notification_chanel)
                if temp_channel_id.isdecimal() and '#' in notification_chanel:
                    channel_id = int(temp_channel_id)
                else:
                    msg = 'チャンネル名が不正です。もう一度、適切な名前で登録してください(#チャンネル名でもOK)。'
                    await interaction.response.send_message(msg, ephemeral=True)
                    LOG.info(msg)
                    return
            else:
                channel_id = temp_channel.id
        else:
            channel_id = interaction.channel.id

            # チャンネルが設定されておらず、ギルドが無いなら、ギルドとチャンネルをNoneとする
            if guild_id is None:
                channel_id = None

        # 実際の処理(live_notification.pyでやる)
        msg = await self.liveNotification.register_live_notification(guild_id, interaction.user.id, live_channel_id, channel_id, mention)
        await interaction.response.send_message(msg, ephemeral=hidden)

    @app_commands.command(
        name='live-notification_read',
        description='[dev]DBを読み込む')
    @app_commands.describe(
        reply_is_hidden='Botの実行結果を全員に見せるどうか')
    async def live_notification_read(self,interaction: discord.Interaction,reply_is_hidden: Literal['自分のみ', '全員に見せる'] = SHOW_ME):
        LOG.info('live-notificationのDBを再読込するぜ！')
        hidden = True if reply_is_hidden == self.SHOW_ME else False
        await self.check_printer_is_running()
        self.liveNotification.read_db()
        await interaction.response.send_message('再読込しました!', ephemeral=hidden)

    @app_commands.command(
        name='live-notification-task-check',
        description='live-notificationのTaskを確認する(live-notificationが発動しない場合に実行してください)')
    @app_commands.describe(
        reply_is_hidden='Botの実行結果を全員に見せるどうか(配信通知自体は普通です/他の人にも配信通知登録を使わせたい場合、全員に見せる方がオススメです)')
    async def _live_task_check(self, interaction: discord.Interaction, reply_is_hidden: Literal['自分のみ', '全員に見せる'] = SHOW_ME):
        LOG.info('live-notificationのTaskを確認するぜ！')
        hidden = True if reply_is_hidden == self.SHOW_ME else False
        msg = await self.check_printer_is_running()
        await interaction.response.send_message(msg, ephemeral=hidden)

    @app_commands.command(
        name='live-notification_list',
        description='登録した配信通知(YouTube,ニコ生)を確認する')
    @app_commands.describe(
        disp_all_flag='配信通知をすべて表示するかどうか(デフォルトはギルドの配信通知のみ)')
    @app_commands.describe(
        reply_is_hidden='Botの実行結果を全員に見せるどうか')
    async def live_notification_list(self, interaction: discord.Interaction, disp_all_flag:Literal['すべて表示', 'コマンドを実行するギルドへ登録した配信通知のみ表示'] = 'コマンドを実行するギルドへ登録した配信通知のみ表示', reply_is_hidden: Literal['自分のみ', '全員に見せる'] = SHOW_ME):
        LOG.info('live-notificationを確認するぜ！')
        await self.check_printer_is_running()
        hidden = True if reply_is_hidden == self.SHOW_ME else False

        # DMもしくは表示対象をall指定の場合、ギルドフィルタをOFFにする(それ以外はON)
        disp_all = True if disp_all_flag == 'すべて表示' else False
        guild_id = None if disp_all or interaction.guild is None else interaction.guild.id

        result = self.liveNotification.list_live_notification(interaction.user.id, guild_id)
        # エラーメッセージの場合、str型で返却。それ以外はリスト(辞書型が格納されている)
        if isinstance(result, str):
            await interaction.response.send_message(result, ephemeral=hidden)
        else:
            embed = discord.Embed(
                            title='配信通知(YouTube,ニコ生)のリスト',
                            color=0x000000,
                            # description=description,
                            )
            embed.set_author(name=self.bot.user,
                            url='https://github.com/tetsuya-ki/discord-live-notificationbot/',
                            icon_url=self.bot.user.display_avatar
                            )
            for result_dict in result:
                message_row = f'''
                                種類: {result_dict.get('type')} 配信者: {result_dict.get('title')}
                                チャンネルID: {result_dict.get('channel_id')} 最新動画ID: {result_dict.get('recent_id')}
                                通知先: {result_dict.get('channel')}
                                更新日時: {result_dict.get('updated_at')}
                                '''
                embed.add_field(name=f'''notification_id: {result_dict['notification_id']}''', value=message_row, inline=False)
            await interaction.response.send_message('あなたの登録した配信通知はコチラです', embed=embed, ephemeral=hidden)


    @app_commands.command(
        name='live-notification_toggle',
        description='配信通知のON/OFFを切り替えます(OFFの場合、通知されません)')
    @app_commands.describe(
        reply_is_hidden='Botの実行結果を全員に見せるどうか')
    async def live_notification_toggle(self, interaction: discord.Interaction, reply_is_hidden: Literal['自分のみ', '全員に見せる'] = SHOW_ME):
        LOG.info('live-notificationをトグルで切り替えるぜ！')
        hidden = True if reply_is_hidden == self.SHOW_ME else False
        await self.check_printer_is_running()
        msg = await self.liveNotification.toggle_user_status(interaction.user.id)
        await interaction.response.send_message(msg, ephemeral=hidden)


    @app_commands.command(
        name='live-notification_delete',
        description='配信通知(YouTube,ニコ生)を削除する')
    @app_commands.describe(
        live_channel_id='削除対象のチャンネルID(YouTubeかニコ生かツイキャス)')
    @app_commands.describe(
        notification_chanel='削除対象の通知先チャンネル(#general等。「DM」でBotとのDMが削除対象。未指定の場合は通知先チャンネル関わらず削除)')
    @app_commands.describe(
        reply_is_hidden='Botの実行結果を全員に見せるどうか')
    async def live_notification_delete(self, interaction: discord.Interaction, live_channel_id:str, notification_chanel:str=None, reply_is_hidden: Literal['自分のみ', '全員に見せる'] = SHOW_ME):
        LOG.info('live-notificationを削除するぜ！')
        hidden = True if reply_is_hidden == self.SHOW_ME else False
        await self.check_printer_is_running()

        # ギルドの設定
        if interaction.guild is None:
            if notification_chanel is not None and notification_chanel.upper() != 'DM':
                msg = 'DMで削除対象の通知先チャンネル指定はできません。チャンネルは未指定か「DM」で配信通知を削除してください。'
                await interaction.response.send_message(msg, ephemeral=True)
                LOG.info(msg)
                return
        # チャンネルの設定
        channel_id = None
        if notification_chanel is not None:
            temp_channel = discord.utils.get(interaction.guild.text_channels, name=notification_chanel)
            if notification_chanel.upper() == 'DM': # DMの場合
                channel_id = -1 # DMと未指定を区別するため、-1として設定しておく
            elif temp_channel is None: # 名称で検索できない場合、#xxxxx形式として調査
                temp_channel_id = re.sub(r'[<#>]', '', notification_chanel)
                if temp_channel_id.isdecimal() and '#' in notification_chanel:
                    channel_id = int(temp_channel_id)
                else:
                    msg = '削除対象の通知先チャンネル名が不正です。もう一度、適切な名前で指定してください(#チャンネル名でもOK)。'
                    await interaction.response.send_message(msg, ephemeral=True)
                    LOG.info(msg)
                    return
            else: # 通知先チャンネルに名称が指定され、取得できた場合
                channel_id = temp_channel.id
        msg = await self.liveNotification.delete_live_notification(interaction.user.id, live_channel_id, channel_id)
        await interaction.response.send_message(msg, ephemeral=hidden)


    @app_commands.command(
        name='live-notification_set-filterword',
        description='通知対象外とする文字列をコンマ区切りで指定する(未指定だと現在のフィルターワードを表示)')
    @app_commands.describe(
        filterword='通知対象外とする文字列をコンマ区切りで指定(すべて削除は「,」のみ指定)')
    @app_commands.describe(
        is_long_description='説明文を長くするかどうか')
    @app_commands.describe(
        reply_is_hidden='Botの実行結果を全員に見せるどうか')
    async def live_notification_set_filterword(self, interaction: discord.Interaction, filterword:str = '', is_long_description:Literal['長くする', '短くする(150文字以降省略)'] = '短くする(150文字以降省略)', reply_is_hidden: Literal['自分のみ', '全員に見せる'] = SHOW_ME):
        LOG.info('filterwordを設定するぜ！')
        await self.check_printer_is_running()
        hidden = True if reply_is_hidden == self.SHOW_ME else False
        if is_long_description == '長くする':
            is_long_description = True
        else:
            is_long_description =  False
        if len(filterword) > self.FILTERWORD_MAX_SIZE:
            await interaction.response.send_message(f'filterwordは{self.FILTERWORD_MAX_SIZE}字以下で設定してください({len(filterword)}字設定しようとしています)', ephemeral = True)
            return
        result = await self.liveNotification.set_filterword(interaction.user.id, filterword, is_long_description)
        await interaction.response.send_message(result, ephemeral=hidden)


    @app_commands.command(
        name='live-notification_video_check',
        description='YouTubeのVideoIDをチェックする')
    @app_commands.describe(
        video_id='YouTubeの動画ID(または動画URL)')
    @app_commands.describe(
        reply_is_hidden='Botの実行結果を全員に見せるどうか')
    async def live_notification_video_check(self,
                        interaction: discord.Interaction,
                        video_id: str,
                        reply_is_hidden: str = 'True'):
        LOG.info('live-notificationの動画をcheckするぜ！')
        await self.check_printer_is_running()

        hidden = True if reply_is_hidden == self.SHOW_ME else False

        channel_id, auhor_name, video_id = await self.liveNotification.check_youtube_by_video_id(video_id)
        if channel_id is not None:
            result_dict_list = await self.liveNotification.get_youtube(channel_id, video_id, datetime.datetime.now(self.JST))
            if result_dict_list is not None and len(result_dict_list) > 0:
                for result_dict in result_dict_list:
                    _,_,message = self.liveNotification.get_by_result_dict('YouTube', result_dict, auhor_name)
                    description = self.liveNotification.make_description(result_dict.get('description'), auhor_name)
                    LOG.info(description)

                    # embedを作成
                    embed = self.liveNotification.make_embed_from_dict(description, result_dict)
                    await interaction.response.send_message(message, embed=embed, ephemeral=hidden)
            else:
                await interaction.response.send_message('何もありませんでした', ephemeral=hidden)
        else:
            await interaction.response.send_message('何もありませんでした', ephemeral=hidden)

    async def check_printer_is_running(self):
        now = datetime.datetime.now(self.JST)
        if not self.printer.is_running():
            msg = 'Taskが停止していたので再起動します。'
            LOG.info(msg)
            self.task_is_excuting = False
            await self.printer.start()
            LOG.warning(f'printer restart.({now})')
            return msg
        else:
            return 'Taskは問題なく起動しています。'

    async def create_dm(self, discord_user_id:int):
        notification_user = self.bot.get_user(discord_user_id)
        text = notification_user or ''
        if notification_user is None:
            notification_user = await self.bot.fetch_user(discord_user_id)
            text = notification_user or ''
        LOG.debug(f'user id :{discord_user_id}, user:{text}')
        return await notification_user.create_dm()

    async def cog_app_command_error(self, interaction, error):
        '''
        slash_commandでエラーが発生した場合の動く処理
        '''
        LOG.error(error)
        if isinstance(error, app_commands.CheckFailure):
            if interaction.command.name == 'remind-list-all':
                await interaction.followup.send(f'エラーが発生しました(DM(ダイレクトメッセージ)でのみ実行できます)', ephemeral=True)
            else:
                await interaction.followup.send(f'エラーが発生しました(コマンドが実行できません)', ephemeral=True)
        elif isinstance(error, discord.ext.commands.PrivateMessageOnly):
            await interaction.followup.send(f'エラーが発生しました(DM(ダイレクトメッセージ)でのみ実行できます)', ephemeral=True)
        elif isinstance(error, app_commands.NoPrivateMessage):
            await interaction.followup.send(f'エラーが発生しました(ギルドでのみ実行できます(DMやグループチャットでは実行できません))', ephemeral=True)
        elif isinstance(error, discord.ext.commands.NotOwner):
            await interaction.followup.send(f'エラーが発生しました(Botのオーナーのみ実行できます)', ephemeral=True)
        elif isinstance(error, app_commands.MissingPermissions):
            if error.missing_perms[0] == 'administrator':
                await interaction.followup.send(f'エラーが発生しました(ギルドの管理者のみ実行できます)', ephemeral=True)
            else:
                await interaction.followup.send(f'エラーが発生しました(権限が足りません)', ephemeral=True)
        elif isinstance(error, discord.errors.Forbidden):
            await interaction.followup.send(f'エラーが発生しました(権限が足りません(おそらくBotが表示/編集できない))', ephemeral=True)
        else:
            await interaction.followup.send(f'エラーが発生しました({error})', ephemeral=True)

# Bot本体側からコグを読み込む際に呼び出される関数。
async def setup(bot):
    LOG.info('LiveNotificationBotを読み込む！')
    await bot.add_cog(LiveNotificationCog(bot))  # LiveNotificationにBotを渡してインスタンス化し、Botにコグとして登録する。
