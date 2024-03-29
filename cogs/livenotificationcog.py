from datetime import timedelta, timezone
from discord.ext import tasks, commands
from discord_slash import cog_ext, SlashContext
from discord_slash.utils import manage_commands  # Allows us to manage the command settings.
from logging import getLogger
from .modules.live_notification import LiveNotification
from .modules import setting

import datetime, discord, re

LOG = getLogger('live-notification-bot')

# コグとして用いるクラスを定義。
class LiveNotificationCog(commands.Cog):
    guilds = [] if setting.ENABLE_SLASH_COMMAND_GUILD_ID_LIST is None else list(
        map(int, setting.ENABLE_SLASH_COMMAND_GUILD_ID_LIST.split(';')))

    # LiveNotificationCogクラスのコンストラクタ。Botを受取り、インスタンス変数として保持。
    def __init__(self, bot):
        self.bot = bot
        self.liveNotification = LiveNotification(bot)
        self.JST = timezone(timedelta(hours=+9), 'JST')
        self.FILTERWORD_MAX_SIZE = 1500
        self.task_is_excuting = False
        self.kicked_count = 0

    # 読み込まれた時の処理
    @commands.Cog.listener()
    async def on_ready(self):
        await self.liveNotification.prepare()  # dbを作成
        LOG.info(f'SQlite準備完了/ギルド件数:{len(self.bot.guilds)}')
        LOG.debug(self.bot.guilds)
        self.printer.start()

    def cog_unload(self):
        self.printer.cancel()

    @tasks.loop(seconds=120.0)
    async def printer(self):
        now = datetime.datetime.now(self.JST)
        LOG.debug(f'printer is kicked.({now})')
        # すでに起動していたら、何もしない
        if self.task_is_excuting:
            LOG.info(f'printer is already kicked.')
            self.kicked_count = self.kicked_count + 1
            if self.kicked_count > 3:
                LOG.info(f'3 count is over!!!')
                self.kicked_count = 0
                self.task_is_excuting = False
            else:
                return
        else:
            self.task_is_excuting = True

        update_count = 0
        # liveの分だけ確認していく
        for live in self.liveNotification.live_rows:
            if live['type_id'] == self.liveNotification.TYPE_YOUTUBE:
                result_dict_list = await self.liveNotification.get_youtube(live['channel_id'], live['recent_id'], live['recent_movie_length'], live['updated_at'])
                message_suffix = 'の動画が追加されました！'
            elif live['type_id'] == self.liveNotification.TYPE_NICOLIVE:
                result_dict_list = await self.liveNotification.get_nicolive(live['channel_id'], live['recent_id'])
                message_suffix = 'の配信が開始されました！'
            elif live['type_id'] == self.liveNotification.TYPE_TWITCASTING:
                result_dict_list = await self.liveNotification.get_twitcasting(live['channel_id'], live['recent_id'])
                message_suffix = 'の配信が開始されました！'

            if result_dict_list is None or len(result_dict_list) == 0:
                continue
            else:
                update_count = update_count + 1
                # notificationの分だけ確認していく
                for notification in self.liveNotification.notification_rows:
                    if live['id'] == notification['live_id']:
                        for result_dict in result_dict_list:
                            video_title = result_dict.get('title')
                            watch_url = result_dict.get('watch_url')
                            if result_dict.get('live_streaming_start_flg') is None:
                                message = f'''{notification['name']}で{live['title']}さん{message_suffix}\n動画名: {video_title}'''
                            elif result_dict.get('live_streaming_start_flg') is True:
                                # YouTubeで予約配信していたものが配信開始された場合を想定
                                message = f'''{notification['name']}で{live['title']}さんの配信が開始されました(おそらく)！\n動画名: {video_title}'''
                            elif result_dict.get('live_streaming_start_flg') is False:
                                # YouTubeで予約配信が追加された場合を想定
                                message = f'''{notification['name']}で{live['title']}さんの予約配信が追加されました！\n動画名: {video_title}'''
                                if result_dict.get('live_streaming_start_datetime') is not None:
                                    message += f'''\n配信予定日時は**{result_dict.get('live_streaming_start_datetime')}**です！'''

                            # 説明文短縮処理
                            description = self.liveNotification.make_description(result_dict.get('description'), live['title'], notification['long_description'] == 'True')

                            # フィルター処理
                            if notification['filter_words'] is not None:
                                filter_word_list = notification['filter_words'].split(',')
                                filter_continue_flag = False
                                target_message = video_title+description
                                for filter_word in filter_word_list:
                                    if filter_word in target_message:
                                        filter_continue_flag = True
                                if filter_continue_flag:
                                    continue

                            embed = discord.Embed(
                            title=video_title,
                            color=0x000000,
                            description=description,
                            url=watch_url
                            )
                            embed.set_author(name=self.bot.user,
                                            url='https://github.com/tetsuya-ki/discord-live-notificationbot/',
                                            icon_url=self.bot.user.avatar_url
                                            )
                            embed.add_field(name='配信日時',value=result_dict.get('started_at'))
                            if result_dict.get('thumbnail') is not None:
                                embed.set_thumbnail(url=result_dict.get('thumbnail'))

                            # メンション処理
                            mention = notification['mention'] if notification['mention'] is not None else ''

                            # DMの処理(notification_guild, notification_channelがNoneならDM扱い)
                            if notification['notification_guild'] is None and notification['notification_channel'] is None:
                                dm = await self.create_dm(notification['discord_user_id'])
                                await dm.send(f'{mention} {message}', embed=embed)
                            else:
                                channel = discord.utils.get(self.bot.get_all_channels(),
                                                            guild__id=notification['notification_guild'],
                                                            id=notification['notification_channel'])
                                if channel is not None:
                                    try:
                                        await channel.send(f'{mention} {message}', embed=embed)
                                    except discord.errors.Forbidden:
                                        msg = f'''＊＊＊{notification['notification_guild']}のチャンネルへの投稿に失敗しました！＊＊＊'''
                                        LOG.error(msg)
                                        try:
                                            # Bot管理者にお知らせ
                                            guild = await self.bot.fetch_guild(notification['notification_guild'])
                                            alert_message = f'''notification_id: {notification['id']}の通知先「{guild.name}/{channel.name}」は権限不足などの原因で通知できませんでした({notification['name']} - {live['title']})\n動画名: {video_title}\nURL: {watch_url}\n通知先のチャンネルの権限見直しをお願いします。'''
                                            get_control_channel = discord.utils.get(self.bot.get_all_channels(),guild__id=self.liveNotification.saved_dm_guild,name=self.liveNotification.LIVE_CONTROL_CHANNEL)
                                            await get_control_channel.send(alert_message)

                                            # 利用者にお知らせ
                                            dm = await self.create_dm(notification['discord_user_id'])
                                            await dm.send(alert_message)
                                        except:
                                            msg = f'＊＊＊さらに、{self.liveNotification.saved_dm_guild}のチャンネル({self.liveNotification.LIVE_CONTROL_CHANNEL})への投稿に失敗しました！＊＊＊'
                                            LOG.error(msg)
                                            continue
                                        continue
        else:
            # 更新があった場合のみ、最後にデータ保存を実行
            if update_count > 0:
                    # Herokuの時のみ、チャンネルにファイルを添付する
                    try:
                        await self.liveNotification.set_discord_attachment_file()
                    except discord.errors.Forbidden:
                        message = f'＊＊＊{self.liveNotification.saved_dm_guild}へのチャンネル作成に失敗しました＊＊＊'
                        LOG.error(message)

        # notificationを全て通知したら、ログを出力 & task_is_excutingをFalseにする
        LOG.info(f'task is finished. update count: {update_count}')
        self.task_is_excuting = False

    @cog_ext.cog_slash(
        name='live-notification_add',
        # guild_ids=guilds,
        description='配信通知(YouTube,ニコ生,ツイキャス)を作成する',
        options=[
            manage_commands.create_option(name='live_channel_id',
                                        description='YouTubeかニコ生のチャンネルID、またはツイキャスユーザーID。もしくはURL(＊非公開のニコ生コミュニティは登録失敗します)',
                                        option_type=3,
                                        required=True),
            manage_commands.create_option(name='notification_chanel',
                                        description='通知するチャンネル(#general等。「DM」でBotとのDMへ登録されます。未指定の場合は登録したチャンネルに投稿)',
                                        option_type=3,
                                        required=False),
            manage_commands.create_option(name='mention',
                                        description='通知する際のメンション(@XXXX, @here, @everyone)',
                                        option_type=3,
                                        required=False),
            manage_commands.create_option(name='reply_is_hidden',
                                        description='Botの実行結果を全員に見せるどうか(配信通知自体は普通です/他の人にも配信通知登録を使わせたい場合、全員に見せる方がオススメです))',
                                        option_type=3,
                                        required=False,
                                        choices=[
                                            manage_commands.create_choice(
                                            name='自分のみ',
                                            value='True'),
                                            manage_commands.create_choice(
                                            name='全員に見せる',
                                            value='False')
                                        ])
        ])
    async def live_notification_add(self,
                        ctx,
                        live_channel_id: str = None,
                        notification_chanel: str = None,
                        mention: str = None,
                        reply_is_hidden: str = 'True'):
        LOG.info('live-notificationをaddするぜ！')
        self.check_printer_is_running()

        # ギルドの設定
        if ctx.guild is not None:
            guild_id = ctx.guild.id
        else:
            if notification_chanel is not None and notification_chanel.upper() != 'DM':
                msg = 'DMでチャンネル指定はできません。チャンネルは未指定で配信通知を登録ください。'
                await ctx.send(msg, hidden = True)
                LOG.info(msg)
                return

            notification_chanel,guild_id = None,None

        # チャンネルの設定(指定なしなら投稿されたチャンネル、指定があればそちらのチャンネルとする)
        channel_id = None
        if notification_chanel is not None:
            temp_channel = discord.utils.get(ctx.guild.text_channels, name=notification_chanel)
            if notification_chanel.upper() == 'DM': # チャンネルが'DM'なら、ギルドとチャンネルをNoneとする
                guild_id = None
                if self.liveNotification.saved_dm_guild is None:
                    msg = 'ギルドが何も登録されていない段階で、DMを登録することはできません。ギルドを登録してから再度、配信通知の登録をしてください。'
                    await ctx.send(msg, hidden = True)
                    LOG.info(msg)
                    return

            elif temp_channel is None:
                temp_channel_id = re.sub(r'[<#>]', '', notification_chanel)
                if temp_channel_id.isdecimal() and '#' in notification_chanel:
                    channel_id = int(temp_channel_id)
                else:
                    msg = 'チャンネル名が不正です。もう一度、適切な名前で登録してください(#チャンネル名でもOK)。'
                    await ctx.send(msg, hidden = True)
                    LOG.info(msg)
                    return
            else:
                channel_id = temp_channel.id
        else:
            channel_id = ctx.channel.id

            # チャンネルが設定されておらず、ギルドが無いなら、ギルドとチャンネルをNoneとする
            if guild_id is None:
                channel_id = None

        # 実際の処理(live_notification.pyでやる)
        msg = await self.liveNotification.register_live_notification(guild_id, ctx.author.id, live_channel_id, channel_id, mention)
        hidden = True if reply_is_hidden == 'True' else False
        await ctx.send(msg, hidden = hidden)

    @cog_ext.cog_slash(
        name='live-notification_read',
        # guild_ids=guilds,
        description='[dev]DBを読み込む')
    async def live_notification_read(self,ctx):
        LOG.info('live-notificationのDBを再読込するぜ！')
        self.check_printer_is_running()
        self.liveNotification.read_db()
        await ctx.send('再読込しました!', hidden=True)

    @cog_ext.cog_slash(
        name='notification-task-check',
        description='live-notificationのTaskを確認する(live-notificationが発動しない場合に実行してください)',
        options=[
            manage_commands.create_option(name='reply_is_hidden',
                                        description='Botの実行結果を全員に見せるどうか',
                                        option_type=3,
                                        required=False,
                                        choices=[
                                            manage_commands.create_choice(
                                            name='自分のみ',
                                            value='True'),
                                            manage_commands.create_choice(
                                            name='全員に見せる',
                                            value='False')
                                        ])
        ])
    async def _live_task_check(self, ctx, reply_is_hidden: str = 'True'):
        LOG.info('live-notificationのTaskを確認するぜ！')
        msg = self.check_printer_is_running()
        hidden = True if reply_is_hidden == 'True' else False
        await ctx.send(msg, hidden = hidden)

    @cog_ext.cog_slash(
        name='live-notification_list',
        # guild_ids=guilds,
        description='登録した配信通知(YouTube,ニコ生)を確認する',
        options=[
            manage_commands.create_option(name='disp_all_flag',
                                        description='配信通知をすべて表示するかどうか(デフォルトはギルドの配信通知のみ)',
                                        option_type=3,
                                        required=False,
                                        choices=[
                                            manage_commands.create_choice(
                                            name='すべて表示',
                                            value='True'),
                                            manage_commands.create_choice(
                                            name='コマンドを実行するギルドへ登録した配信通知のみ表示',
                                            value='False')
                                        ]),
            manage_commands.create_option(name='filter',
                                        description='配信通知リストを検索',
                                        option_type=3,
                                        required=False),
            manage_commands.create_option(name='reply_is_hidden',
                                        description='Botの実行結果を全員に見せるどうか',
                                        option_type=3,
                                        required=False,
                                        choices=[
                                            manage_commands.create_choice(
                                            name='自分のみ',
                                            value='True'),
                                            manage_commands.create_choice(
                                            name='全員に見せる',
                                            value='False')
                                        ])
        ])
    async def live_notification_list(self, ctx, disp_all_flag:str = 'False', filter:str = '', reply_is_hidden: str = 'True'):
        LOG.info('live-notificationを確認するぜ！')
        self.check_printer_is_running()
        hidden = True if reply_is_hidden == 'True' else False

        # DMもしくは表示対象をall指定の場合、ギルドフィルタをOFFにする(それ以外はON)
        disp_all = True if disp_all_flag == 'True' else False
        guild_id = None if disp_all or ctx.guild is None else ctx.guild.id

        result = self.liveNotification.list_live_notification(ctx.author.id, guild_id)
        # エラーメッセージの場合、str型で返却。それ以外はリスト(辞書型が格納されている)
        if isinstance(result, str):
            await ctx.send(result, hidden = hidden)
        else:
            embed = discord.Embed(
                            title='配信通知(YouTube,ニコ生)のリスト',
                            color=0x000000,
                            # description=description,
                            )
            embed.set_author(name=self.bot.user,
                            url='https://github.com/tetsuya-ki/discord-live-notificationbot/',
                            icon_url=self.bot.user.avatar_url
                            )
            for result_dict in result:
                message_row = f'''
                                種類: {result_dict.get('type')} 配信者: {result_dict.get('title')}
                                チャンネルID: {result_dict.get('channel_id')} 最新動画ID: {result_dict.get('recent_id')}
                                通知先: {result_dict.get('channel')}
                                更新日時: {result_dict.get('updated_at')}
                                '''
                # filterが登録されている場合、message_rowに存在するもののみ表示する
                if filter:
                    if filter in message_row:
                        embed.add_field(name=f'''notification_id: {result_dict['notification_id']}''', value=message_row, inline=False)
                else:
                    embed.add_field(name=f'''notification_id: {result_dict['notification_id']}''', value=message_row, inline=False)
            await ctx.send('あなたの登録した配信通知はコチラです', embed=embed, hidden = hidden)

    @cog_ext.cog_slash(
        name='live-notification_toggle',
        # guild_ids=guilds,
        description='配信通知のON/OFFを切り替えます(OFFの場合、通知されません)',
        options=[
            manage_commands.create_option(name='reply_is_hidden',
                                            description='Botの実行結果を全員に見せるどうか',
                                            option_type=3,
                                            required=False,
                                            choices=[
                                                manage_commands.create_choice(
                                                name='自分のみ',
                                                value='True'),
                                                manage_commands.create_choice(
                                                name='全員に見せる',
                                                value='False')
                                            ])
        ])
    async def live_notification_toggle(self, ctx, reply_is_hidden: str = 'True'):
        LOG.info('live-notificationをトグルで切り替えるぜ！')
        self.check_printer_is_running()
        hidden = True if reply_is_hidden == 'True' else False
        msg = await self.liveNotification.toggle_user_status(ctx.author.id)
        await ctx.send(msg, hidden = hidden)

    @cog_ext.cog_slash(
        name='live-notification_delete',
        # guild_ids=guilds,
        description='配信通知(YouTube,ニコ生)を削除する',
        options=[
            manage_commands.create_option(name='live_channel_id',
                                        description='YouTubeかニコ生のチャンネルID',
                                        option_type=3,
                                        required=True),
            manage_commands.create_option(name='notification_chanel',
                                        description='削除対象の通知先チャンネル(#general等。「DM」でBotとのDMが削除対象。未指定の場合は通知先チャンネル関わらず削除)',
                                        option_type=3,
                                        required=False),
            manage_commands.create_option(name='reply_is_hidden',
                                        description='Botの実行結果を全員に見せるどうか',
                                        option_type=3,
                                        required=False,
                                        choices=[
                                            manage_commands.create_choice(
                                            name='自分のみ',
                                            value='True'),
                                            manage_commands.create_choice(
                                            name='全員に見せる',
                                            value='False')
                                        ])
        ])
    async def live_notification_delete(self, ctx, live_channel_id:str, notification_chanel:str=None, reply_is_hidden:str='True'):
        LOG.info('live-notificationを削除するぜ！')
        self.check_printer_is_running()
        hidden = True if reply_is_hidden == 'True' else False

        # ギルドの設定
        if ctx.guild is None:
            if notification_chanel is not None and notification_chanel.upper() != 'DM':
                msg = 'DMで削除対象の通知先チャンネル指定はできません。チャンネルは未指定か「DM」で配信通知を削除してください。'
                await ctx.send(msg, hidden = True)
                LOG.info(msg)
                return
        # チャンネルの設定
        channel_id = None
        if notification_chanel is not None:
            temp_channel = discord.utils.get(ctx.guild.text_channels, name=notification_chanel)
            if notification_chanel.upper() == 'DM': # DMの場合
                channel_id = -1 # DMと未指定を区別するため、-1として設定しておく
            elif temp_channel is None: # 名称で検索できない場合、#xxxxx形式として調査
                temp_channel_id = re.sub(r'[<#>]', '', notification_chanel)
                if temp_channel_id.isdecimal() and '#' in notification_chanel:
                    channel_id = int(temp_channel_id)
                else:
                    msg = '削除対象の通知先チャンネル名が不正です。もう一度、適切な名前で指定してください(#チャンネル名でもOK)。'
                    await ctx.send(msg, hidden = True)
                    LOG.info(msg)
                    return
            else: # 通知先チャンネルに名称が指定され、取得できた場合
                channel_id = temp_channel.id
        msg = await self.liveNotification.delete_live_notification(ctx.author.id, live_channel_id, channel_id)
        await ctx.send(msg, hidden = hidden)

    @cog_ext.cog_slash(
    name='live-notification_set-filterword',
    # guild_ids=guilds,
    description='通知対象外とする文字列をコンマ区切りで指定する(未指定だと現在のフィルターワードを表示)',
    options=[
        manage_commands.create_option(name='filterword',
                                    description='通知対象外とする文字列をコンマ区切りで指定(すべて削除は「,」のみ指定)',
                                    option_type=3,
                                    required=False),
        manage_commands.create_option(name='is_long_description',
                                    description='説明文を長くするかどうか',
                                    option_type=3,
                                    required=False,
                                    choices=[
                                        manage_commands.create_choice(
                                        name='長くする',
                                        value='True'),
                                        manage_commands.create_choice(
                                        name='短くする(30文字以降省略)',
                                        value='False')
                                    ]),
        manage_commands.create_option(name='reply_is_hidden',
                                    description='Botの実行結果を全員に見せるどうか',
                                    option_type=3,
                                    required=False,
                                    choices=[
                                        manage_commands.create_choice(
                                        name='自分のみ',
                                        value='True'),
                                        manage_commands.create_choice(
                                        name='全員に見せる',
                                        value='False')
                                    ])
    ])
    async def live_notification_set_filterword(self, ctx, filterword:str = '', is_long_description:str = None, reply_is_hidden: str = 'True'):
        LOG.info('filterwordを設定するぜ！')
        self.check_printer_is_running()
        hidden = True if reply_is_hidden == 'True' else False
        if is_long_description == 'True':
            is_long_description = True
        elif is_long_description == 'False':
            is_long_description =  False
        if len(filterword) > self.FILTERWORD_MAX_SIZE:
            await ctx.send(f'filterwordは{self.FILTERWORD_MAX_SIZE}字以下で設定してください({len(filterword)}字設定しようとしています)', hidden = True) 
            return
        result = await self.liveNotification.set_filterword(ctx.author.id, filterword, is_long_description)
        await ctx.send(result, hidden = hidden)

    def check_printer_is_running(self):
        if not self.printer.is_running():
            msg = 'Taskが停止していたので再起動します。'
            LOG.info(msg)
            self.printer.start()
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

    @commands.Cog.listener()
    async def on_slash_command_error(self, ctx, ex):
        '''
        slash_commandでエラーが発生した場合の動く処理
        '''
        try:
            raise ex
        except discord.ext.commands.PrivateMessageOnly:
            await ctx.send(f'エラーが発生しました(DM(ダイレクトメッセージ)でのみ実行できます)', hidden = True)
        except discord.ext.commands.NoPrivateMessage:
            await ctx.send(f'エラーが発生しました(ギルドでのみ実行できます(DMやグループチャットでは実行できません))', hidden = True)
        except discord.ext.commands.NotOwner:
            await ctx.send(f'エラーが発生しました(Botのオーナーのみ実行できます)', hidden = True)
        except discord.ext.commands.MissingPermissions:
            if ex.missing_perms[0] == 'administrator':
                await ctx.send(f'エラーが発生しました(ギルドの管理者のみ実行できます)', hidden = True)
        except:
            await ctx.send(f'エラーが発生しました({ex})', hidden = True)

# Bot本体側からコグを読み込む際に呼び出される関数。
def setup(bot):
    LOG.info('LiveNotificationBotを読み込む！')
    bot.add_cog(LiveNotificationCog(bot))  # LiveNotificationにBotを渡してインスタンス化し、Botにコグとして登録する。
