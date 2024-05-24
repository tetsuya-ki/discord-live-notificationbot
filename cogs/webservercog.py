from .modules import pubsub_subscribe
from .modules import setting
from .modules.live_notification import LiveNotification
from datetime import timedelta, timezone
from dateutil.parser import parse
from dateutil.tz import gettz
from discord.ext import tasks, commands
from logging import getLogger
from xml.etree.ElementTree import ParseError
from aiohttp import web

import defusedxml.ElementTree as ET
import datetime, discord, asyncio, copy

LOG = getLogger('live-notification-bot')

XML_NAMESPACE = {
    'atom': 'http://www.w3.org/2005/Atom',
    'yt': 'http://www.youtube.com/xml/schemas/2015',
    'media': 'http://search.yahoo.com/mrss/',
}

app = web.Application()
routes = web.RouteTableDef()

# コグとして用いるクラスを定義。
class WebServerCog(commands.Cog):
    # WebServerCogクラスのコンストラクタ。Botを受取り、インスタンス変数として保持。
    def __init__(self, bot):
        self.bot = bot
        self.liveNotification = LiveNotification(bot)
        self.JST = timezone(timedelta(hours=+9), 'JST')
        self.FILTERWORD_MAX_SIZE = 1500
        self.task_is_excuting = False
        self.noticeList = []
        self.web_server.start()
        # Trueの場合、最初はsubscribeしない
        self.first = False

        # ref.https://stackoverflow.com/questions/48693069/running-flask-a-discord-bot-in-the-same-application
        @routes.get('/handler')
        async def get(request):
            try:
                # LOG.debug(request)
                LOG.debug(request.query)
                data = '200'
                request_hub_mode = request.query.get('hub.mode', '')
                if request_hub_mode == 'unsubscribe' \
                or request_hub_mode == 'subscribe':
                    data = request.query.get('hub.challenge', '')
                    LOG.debug(data)
                else:
                    LOG.debug('Not (un)!subscribe')
                return web.Response(text=data)
            except Exception as e:
                LOG.debug(str(e))
                return web.Response(text='OK')

        @routes.post('/handler')
        async def post(request):
            try:
                LOG.debug(request)
                binary = await request.read()
                text = binary.decode(encoding='utf-8')
                LOG.debug(text)
                try :
                    root = ET.fromstring(text)
                    for entry in root.iter('{'+XML_NAMESPACE['atom']+'}entry'):
                        if entry is None:
                            continue
                        # TODO:確認するため出力
                        LOG.info('********************* element *********************')
                        # author = entry.find('atom:author', XML_NAMESPACE)
                        videoId=entry.find('yt:videoId', XML_NAMESPACE).text
                        channelId=entry.find('yt:channelId', XML_NAMESPACE).text
                        title=entry.find('atom:title', XML_NAMESPACE).text
                        link=entry.find('atom:link', XML_NAMESPACE).get('href')
                        # authorName=author.find('atom:name', XML_NAMESPACE).text
                        # authorUri=author.find('atom:uri', XML_NAMESPACE).text
                        published=parse(entry.find('atom:published', XML_NAMESPACE).text).astimezone(gettz('Asia/Tokyo'))
                        updated=parse(entry.find('atom:updated', XML_NAMESPACE).text).astimezone(gettz('Asia/Tokyo'))
                        group = entry.find('media:group', XML_NAMESPACE)
                        thumbnail = ''
                        description = ''
                        if group:
                            thumbnail=group.find('media:thumbnail', XML_NAMESPACE).get('url')
                            description=group.find('media:description', XML_NAMESPACE).text
                            LOG.debug(f'thumbnail:{thumbnail}')
                            LOG.debug(f'description:{description}')
                        LOG.info(f'videoId:{videoId} from channelId:{channelId}')
                        LOG.info(f'title: {title} / link: {link}')
                        LOG.info(f'published: {published} / updated: {updated}')
                        LOG.info('********************* end *********************')
                        # DBチェック(&更新処理), 予約でない(ライブ配信開始or動画の)場合、通知
                        list = await self.liveNotification.get_youtube(channelId, videoId, updated)
                        if list:
                            self.noticeList.extend(list)
                            LOG.debug(self.noticeList)
                            LOG.debug('********************* start check_and_send!!!!! *********************')
                            try:
                                # await self.check_and_send()
                                loop = asyncio.get_event_loop()
                                task = loop.create_task(self.check_and_send())
                            except Exception as e:
                                LOG.error(str(e))
                                return
                            LOG.debug('********************* end check_and_send!!!!! *********************')
                except ParseError as e:
                    LOG.error('ParseError:' + str(e))
                    return
                return
            except Exception as e:
                LOG.error(str(e))
                return

        self.webserver_port = setting.PORT
        app.add_routes(routes)

    # 読み込まれた時の処理
    @commands.Cog.listener()
    async def on_ready(self):
        await asyncio.sleep(15)
        await self.liveNotification.prepare()  # db準備
        if not self.day_printer.is_running() and not self.first:
            await self.day_printer.start()
            pass
        else:
            self.first = False

    def cog_unload(self):
        self.printer.cancel()

    # TODO:1日1回PubSub登録(&3日?すぎた未済リザーブの整理&180日?すぎたリザーブの整理)
    @tasks.loop(hours=24.0)
    async def day_printer(self):
        now_d = datetime.datetime.now(self.JST)
        LOG.info(f'day printer is kicked.({now_d})')

        # V2の場合、liveがYouTubeの分だけサブスクライブしていく
        if setting.LIVE_NOTIFICATION_V2:
            subscribe_count = 0
            LOG.info(f'対象数:{str(len(self.liveNotification.live_rows))}')
            for live in self.liveNotification.live_rows:
                if live['type_id'] == self.liveNotification.TYPE_YOUTUBE:
                    await pubsub_subscribe.subscribe_by_channel_id(live['channel_id'])
                    subscribe_count += 1
                    LOG.info(f'実行数:{str(subscribe_count)} (簡易的な)残数:{str(len(self.liveNotification.live_rows)-subscribe_count)}')
                    pass
        LOG.info(f'day printer task is finished.')

    async def create_dm(self, discord_user_id:int):
        notification_user = self.bot.get_user(discord_user_id)
        text = notification_user or ''
        if notification_user is None:
            notification_user = await self.bot.fetch_user(discord_user_id)
            text = notification_user or ''
        LOG.debug(f'user id :{discord_user_id}, user:{text}')
        return await notification_user.create_dm()

    async def check_and_send(self):
        # day_printerの確認もしておく
        if not self.day_printer.is_running():
            LOG.info('days_printerが停止してたので起動')
            await self.day_printer.start()
        if len(self.noticeList) == 0:
            LOG.info('len:0.\n no loop')
            return
        else:
            LOG.debug('len:'+str(len(self.noticeList)))
            target_list = copy.deepcopy(self.noticeList)
            self.noticeList = []
            for result_dict in target_list:
                video_title = result_dict.get('title')
                watch_url = result_dict.get('watch_url')
                author = result_dict.get('author')
                if author is None or author == '':
                    author = '(不明)'
                if video_title is None or author == '':
                    video_title = '(名前なし)'
                updated_at = result_dict.get('updated_at')

                if result_dict.get('live_streaming_start_flg') is True:
                    # YouTubeで予約配信していたものが配信開始された場合を想定
                    message = f'''YouTubeで{author}さんの配信が開始されました(おそらく)！\n動画名: {video_title}'''
                elif result_dict.get('live_streaming_start_flg') is False:
                    # YouTubeで予約配信が追加された場合を想定
                    message = f'''YouTubeで{author}さんの予約配信が追加されました！\n動画名: {video_title}'''
                    if result_dict.get('live_streaming_start_datetime') is not None:
                        message += f'''\n配信予定日時は**{result_dict.get('live_streaming_start_datetime')}**です！'''
                else: # result_dict.get('live_streaming_start_flg') is None:
                    message = f'''YouTubeで{author}さんの動画が追加されました！\n動画名: {video_title}'''

                LOG.info(f'{message}\n{watch_url}')
                LOG.info(result_dict)

                channel_id = result_dict.get('channel_id')
                count = 0
                # 対象YouTubeチャンネルをNotificationしている人ごと対応
                for live in self.liveNotification.live_rows:
                    if live['type_id'] == self.liveNotification.TYPE_YOUTUBE:
                        for notification in self.liveNotification.notification_rows:
                            if live['id'] == notification['live_id'] \
                                and channel_id == live['channel_id']:
                                # 説明文短縮処理 & 改行のエスケープをやめる
                                description = self.liveNotification.make_description(result_dict.get('description'), author, notification['long_description'] == 'True')
                                description = description.replace('\\n','\n').replace('\u3000', '  ')
                                LOG.info(description)

                                # フィルター処理
                                if notification['filter_words'] is not None:
                                    LOG.info(f'''フィルタあり: notification:{notification['id']}, nitification_user_id:{notification['user_id']}-> {notification['filter_words']}''')
                                    filter_word_list = notification['filter_words'].split(',')
                                    filter_continue_flag = False
                                    target_message = video_title+description
                                    for filter_word in filter_word_list:
                                        if filter_word in target_message:
                                            filter_continue_flag = True
                                    if filter_continue_flag:
                                        LOG.info(f'''notification:{notification['id']}, notification_user_id:{notification['user_id']}はフィルタで切り捨てられました。\n{watch_url}''')
                                        continue

                                embed = discord.Embed(
                                    title=video_title,
                                    color=0x000000,
                                    description=description,
                                    url=watch_url)
                                embed.set_author(name=self.bot.user,
                                                url='https://github.com/tetsuya-ki/discord-live-notificationbot/',
                                                icon_url=self.bot.user.display_avatar
                                                )
                                started_at = ''
                                if result_dict.get('started_at') is not None:
                                    started_at = result_dict.get('started_at')
                                    embed.add_field(name='配信日時',value=started_at)
                                LOG.info(f'''notification:{notification['id']}: started_at:{started_at}''')
                                if updated_at:
                                    embed.add_field(name='更新日時',value=updated_at)
                                if result_dict.get('thumbnail') is not None and str(result_dict.get('thumbnail')).startswith('http'):
                                    embed.set_thumbnail(url=result_dict.get('thumbnail'))

                                # メンション処理
                                if notification['mention']:
                                    mention = notification['mention'] + ' '
                                    LOG.info(f'''notification:{notification['id']}: mention:{mention}''')
                                else:
                                    mention = ''

                                count += 1
                                # DMの処理(notification_guild, notification_channelがNoneならDM扱い)
                                if notification['notification_guild'] is None and notification['notification_channel'] is None:
                                    LOG.info('DM通知予定:'+str(notification['discord_user_id']))
                                    try:
                                        dm = await self.create_dm(notification['discord_user_id'])
                                        await dm.send(f'{mention} {message}', embed=embed)
                                        LOG.info('DM通知完了:'+str(notification['discord_user_id']))
                                    except Exception as e:
                                        LOG.error('投稿関連処理(DM)でエラーが発生')
                                        LOG.error(e)
                                else:
                                    # よくわからない状態なので、以下のやり方は使わない
                                    #                             channel = discord.utils.get(self.bot.get_all_channels(),
                                    #                             guild__id=notification['notification_guild'],
                                    #                             id=notification['notification_channel'])
                                    target = f'''-> guild: {notification['notification_guild']}, channel: {notification['notification_channel']}'''
                                    LOG.info(f'''{notification['name']}をCHに通知予定 {target}''')
                                    try:
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
                                            # チャンネルの取得
                                            target_channel = None
                                            if hasattr(target_guild, 'get_channel_or_thread'):
                                                LOG.info(f'''target_guild.get_channel_or_threadがあるので、それを使って取得:{notification['notification_guild']}''')
                                                target_channel = target_guild.get_channel_or_thread(notification['notification_channel'])
                                            else:
                                                LOG.warning('target_guild.get_channel_or_threadがないよ')
                                                LOG.info(f'''get_channel_or_threadがないし、ギルドが見つからないのでfetchする -> guild: {notification['notification_guild']}''')
                                                try:
                                                    target_guild = await self.bot.fetch_guild(notification['notification_guild'])
                                                except:
                                                    pass
                                            # 今までチャンネルとれておらず、ギルドがある場合
                                            if target_channel is None and target_guild is not None:
                                                if hasattr(target_guild, 'get_channel_or_thread'):
                                                    target_channel = target_guild.get_channel_or_thread(notification['notification_channel'])
                                                elif hasattr(target_guild, 'fetch_channel'):
                                                    target_channel = await target_guild.fetch_channel(notification['notification_channel'])

                                            # チャンネルへ書き込み
                                            if target_channel is not None:
                                                LOG.info(f'''{notification['name']}をCHに通知(直前)-> {watch_url} P2 {target}''')
                                                await target_channel.send(f'{mention} {message}', embed=embed)
                                                LOG.info(f'''{notification['name']}をCHに通知-> {watch_url} P2 {target}''')
                                            else:
                                                LOG.error(f'''ギルドはあるが、チャンネルが結局見つからない。。。。  {target}''')
                                        else:
                                            LOG.error(f'''フェッチしても結局ギルドが見つからない。。。。  {target}''')
                                    except discord.errors.Forbidden:
                                        try:
                                            alert_message = f'''notification_id: {notification['id']}の通知先「{notification['notification_guild']}/{notification['notification_channel']}(<#{notification['notification_channel']}>)」は権限不足などの原因で通知できませんでした({notification['name']} - {live['title']})\n動画名: {video_title}\nURL: {watch_url}\n通知先のチャンネルの権限見直しをお願いします。'''
                                            LOG.error(alert_message)

                                            # Bot管理者にお知らせ
                                            # get_control_channel = discord.utils.get(self.bot.get_all_channels(),guild__id=self.liveNotification.saved_dm_guild,name=self.liveNotification.LIVE_CONTROL_CHANNEL)
                                            # await get_control_channel.send(alert_message)

                                            # 利用者にお知らせ
                                            dm = await self.create_dm(notification['discord_user_id'])
                                            await dm.send(alert_message)
                                        except (discord.errors.NotFound, discord.NotFound) as ne:
                                            LOG.error(f'''投稿関連処理でNotFoundエラーが発生({notification['notification_guild']})''')
                                            LOG.error(ne)
                                        except Exception as e:
                                            msg = f'＊＊＊さらに、{self.liveNotification.saved_dm_guild}のチャンネル({self.liveNotification.LIVE_CONTROL_CHANNEL})への投稿に失敗しました！＊＊＊'
                                            LOG.error(msg)
                                            LOG.error(e)
                                    except Exception as e:
                                        LOG.error('投稿関連処理でForbidden以外のエラーが発生')
                                        LOG.info(type(e))
                                        LOG.info(e.args)
                                        LOG.error(e)
                if count == 0:
                    LOG.info(f'★通知対象者なし -> {message}')
                else:
                    LOG.info(f'★{str(count)}件通知 -> {message}')

    @tasks.loop()
    async def web_server(self):
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host='0.0.0.0', port=self.webserver_port)
        await site.start()
        LOG.info(f'server is started(port:{self.webserver_port})')

    @web_server.before_loop
    async def web_server_before_loop(self):
        await self.bot.wait_until_ready()

# Bot本体側からコグを読み込む際に呼び出される関数。
async def setup(bot):
    LOG.info('WebServerCogを読み込む！')
    cog = WebServerCog(bot)
    await bot.add_cog(cog)  # WebServerCogにBotを渡してインスタンス化し、Botにコグとして登録する。
    LOG.info('WebServerCogおわり')