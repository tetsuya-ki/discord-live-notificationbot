from sqlite3 import dbapi2
import aiohttp
import xml.etree.ElementTree as ET
from datetime import timedelta, timezone
from discord.ext import commands
from os.path import join, dirname
from logging import getLogger
from pytube import YouTube
from .aes_angou import Aes_angou
from . import setting, pubsub_subscribe
from xml.sax.saxutils import unescape

import datetime, discord, sqlite3, os, re, requests
LOG = getLogger('live-notification-bot')

class LiveNotification:
    DATABASE = 'live.db'
    FILE_PATH = join(dirname(__file__), 'files' + os.sep + DATABASE)
    JST = timezone(timedelta(hours=+9), 'JST')
    DATETIME_FORMAT = '%Y/%m/%d(%a) %H:%M:%S'
    DATETIME_FORMAT_TZ = '%Y-%m-%dT%H:%M:%S%z'
    DATETIME_FORMAT_DB = '%Y-%m-%d %H:%M:%S.%f%z'
    LIVE_CONTROL_CHANNEL = 'live_control_channel'
    YOUTUBE = 'YouTube'
    NICOLIVE = 'ニコ生'
    TWITCASTING = 'ツイキャス'
    YOUTUBE_URL = 'https://www.youtube.com/feeds/videos.xml?channel_id='
    YOUTUBE_VIDEO_URL = 'https://www.youtube.com/watch?v='
    YOUTUBE_URL_FOR_PUBSUB = 'https://www.youtube.com/xml/feeds/videos.xml?channel_id='
    TYPE_YOUTUBE = 1
    TYPE_NICOLIVE = 2
    TYPE_TWITCASTING = 3
    NOTIFICATION_MAX = 5
    STATUS_VALID = 'VALID'
    STATUS_INVALID = 'INVALID'
    LIVE_YOUTUBE_STATUS_DELIVERED = 'DELIVERED'
    LIVE_YOUTUBE_STATUS_ERROR = 'ERROR'
    LIVE_YOUTUBE_STATUS_UNDELIVERED = 'UNDELIVERED'
    DESCRIPTION_LENGTH = 1000
    SYSTEM_STATUS_DELETE = 'DELETE'
    SYSTEM_STATUS_DELETED = 'DELETED'

    def __init__(self, bot):
        self.bot = bot
        self.live_rows = None  # liveの一覧
        self.notification_rows = None  # notificationの結果
        self.aes = Aes_angou(setting.DISCORD_TOKEN)
        self.saved_dm_guild = int(setting.GUILD_ID_FOR_ATTACHMENTS) if str(setting.GUILD_ID_FOR_ATTACHMENTS).isdecimal() else None

    async def prepare(self):
        '''
        sqlite3のdbを準備する

        Parameters
        ----------
        なし

        Returns
        -------
        なし
        '''
        # Herokuの時のみ、チャンネルからファイルを取得する
        await self.get_discord_attachment_file()

        # 何回か使うので...
        create_table_live_youtube_sql = '''
                    CREATE TABLE IF NOT EXISTS live_youtube (
                        channel_id text,
                        video_id text,
                        status text,
                        title text,
                        scheduled_start_time datetime,
                        created_at datetime,
                        updated_at datetime
                    )
                    '''

        if not os.path.exists(self.aes.ENC_FILE_PATH):
            conn = sqlite3.connect(self.FILE_PATH)
            with conn:
                cur = conn.cursor()

                create_table_user_sql = '''
                                    CREATE TABLE IF NOT EXISTS user (
                                        id integer primary key autoincrement,
                                        discord_user_id integer,
                                        status text,
                                        filter_words text,
                                        long_description text,
                                        system_status test,
                                        created_at datetime,
                                        updated_at datetime
                                    )
                                    '''
                create_table_type_sql = '''
                                    CREATE TABLE IF NOT EXISTS type (
                                        id integer primary key autoincrement,
                                        name text,
                                        created_at datetime,
                                        updated_at datetime
                                    )
                                    '''
                create_table_live_sql = '''
                                    create table if not exists live (
                                        id integer primary key autoincrement,
                                        type_id integer,
                                        live_author_id integer,
                                        channel_id text,
                                        recent_id text,
                                        recent_movie_length integer,
                                        title text,
                                        created_at datetime,
                                        updated_at datetime
                                    )
                                    '''
                create_table_notification_sql = '''
                                    CREATE TABLE IF NOT EXISTS notification (
                                        id integer primary key autoincrement,
                                        type_id integer,
                                        user_id integer,
                                        live_id integer,
                                        notification_guild integer,
                                        notification_channel integer,
                                        mention text,
                                        created_at datetime,
                                        updated_at datetime
                                    )
                                    '''
                sql_list = [create_table_user_sql, create_table_type_sql, create_table_live_sql, create_table_notification_sql, create_table_live_youtube_sql]
                for create_table_sql in sql_list:
                    cur.execute(create_table_sql)
        else:
            self.decode()

        # add type
        conn = sqlite3.connect(self.FILE_PATH)
        with conn:
            cur = conn.cursor()
            now = datetime.datetime.now(self.JST)
            insert_sql = 'INSERT INTO type (name,created_at,updated_at) VALUES (?,?,?)'
            check_sql = 'SELECT COUNT(*) FROM type WHERE name = ? '
            cur.execute(check_sql, (self.YOUTUBE,))
            if cur.fetchall()[0][0] == 0:
                remind_param_youtube = (self.YOUTUBE, now, now)
                cur.execute(insert_sql, remind_param_youtube)
                conn.commit()
            cur.execute(check_sql, (self.NICOLIVE,))
            if cur.fetchall()[0][0] == 0:
                remind_param_nicolive = (self.NICOLIVE, now, now)
                cur.execute(insert_sql, remind_param_nicolive)
                conn.commit()
            cur.execute(check_sql, (self.TWITCASTING,))
            if cur.fetchall()[0][0] == 0:
                remind_param_twitcasting = (self.TWITCASTING, now, now)
                cur.execute(insert_sql, remind_param_twitcasting)
                conn.commit()

        # userテーブルにlong_descriptionカラムがない場合、追加
        conn = sqlite3.connect(self.FILE_PATH)
        with conn:
            cur = conn.cursor()
            now = datetime.datetime.now(self.JST)
            alter_user_add_log_description_sql = '''alter table user add column 'long_description' '''
            check_sql = '''PRAGMA table_info('user')'''
            cur.execute(check_sql)
            need_alter_table = True
            result = cur.fetchall()
            for column in result:
                if column[1] == 'long_description':
                    need_alter_table = False
            if need_alter_table:
                LOG.info('need_alter_table is ' + str(need_alter_table))
                cur.execute(alter_user_add_log_description_sql)

        # live_youtubeテーブルがない場合、追加
        conn = sqlite3.connect(self.FILE_PATH)
        with conn:
            cur = conn.cursor()
            cur.execute(create_table_live_youtube_sql)

        # userテーブルにsystem_statusカラムがない場合、追加
        conn = sqlite3.connect(self.FILE_PATH)
        with conn:
            cur = conn.cursor()
            now = datetime.datetime.now(self.JST)
            alter_user_add_system_status_sql = '''alter table user add column 'system_status' '''
            check_sql = '''PRAGMA table_info('user')'''
            cur.execute(check_sql)
            need_alter_table = True
            result = cur.fetchall()
            for column in result:
                if column[1] == 'system_status':
                    need_alter_table = False
            if need_alter_table:
                LOG.info('need_alter_table is ' + str(need_alter_table))
                cur.execute(alter_user_add_system_status_sql)

        self.read()
        self.encode()
        LOG.info('準備完了')

    async def get_discord_attachment_file(self):
        '''
        添付ファイルをdiscordから取得

        Parameters
        ----------
        なし

        Returns
        -------
        なし
        '''
        # Herokuの時のみ実施
        if setting.IS_HEROKU:
            # 環境変数によって、添付ファイルのファイル名を変更する
            file_name = self.aes.ENC_FILE if setting.KEEP_DECRYPTED_FILE else self.DATABASE
            LOG.debug('Heroku mode.start get_discord_attachment_file.')
            # ファイルをチェックし、存在しなければ最初と見做す
            file_path_first_time = join(dirname(__file__), 'files' + os.sep + 'first_time')
            if (setting.IS_HEROKU and not os.path.exists(file_path_first_time)):
                if setting.IS_HEROKU:
                    with open(file_path_first_time, 'w') as f:
                        now = datetime.datetime.now(self.JST)
                        f.write(now.strftime(self.DATETIME_FORMAT))
                        LOG.debug(f'{file_path_first_time}が存在しないので、作成を試みます')
                attachment_file_date = None

                if self.saved_dm_guild is None:
                    LOG.error('環境変数に「GUILD_ID_FOR_ATTACHMENTS」が登録されていません（必須です！）')
                    raise discord.errors.InvalidArgument 
                # BotがログインしているGuildごとに繰り返す
                for guild in self.bot.guilds:
                    # 指定されたギルド以外は無視
                    if self.saved_dm_guild != guild.id:
                        continue
                    # チャンネルのチェック
                    LOG.debug(f'{guild}: チャンネル読み込み')
                    get_control_channel = discord.utils.get(guild.text_channels, name=self.LIVE_CONTROL_CHANNEL)
                    if get_control_channel is not None:
                        try:
                            messages = await get_control_channel.history(limit=20).flatten()
                        except discord.errors.Forbidden:
                            msg = f'＊＊＊{guild}のチャンネル({self.LIVE_CONTROL_CHANNEL})読み込みに失敗しました！＊＊＊'
                            LOG.error(msg)
                            continue

                        for message in messages:
                            # 添付ファイルの読み込みを自分の投稿のみに制限する(環境変数で指定された場合のみ)
                            if setting.RESTRICT_ATTACHMENT_FILE and  message.author != guild.me:
                                continue
                            LOG.debug(f'con: {message.content}, attchSize:{len(message.attachments)}')
                            message_created_at = message.created_at.replace(tzinfo=timezone.utc)
                            message_created_at_jst = message_created_at.astimezone(self.JST)

                            if attachment_file_date is not None:
                                LOG.debug(f'date: {attachment_file_date} <<<<<<< {message_created_at_jst}, {attachment_file_date < message_created_at_jst}')
                            # file_nameが本文である場合、ファイルを取得する
                            if message.content == file_name:
                                if len(message.attachments) > 0:
                                    # 日付が新しい場合、ファイルを取得
                                    if attachment_file_date is None or attachment_file_date < message_created_at_jst:
                                        attachment_file_date = message_created_at_jst
                                        file_path = join(dirname(__file__), 'files' + os.sep + file_name)
                                        await message.attachments[0].save(file_path)
                                        LOG.info(f'channel_file_save:{guild.name} / datetime:{attachment_file_date.strftime(self.DATETIME_FORMAT)}')
                                        break
                    else:
                        LOG.warning(f'{guild}: に所定のチャンネルがありません')
            else:
                LOG.debug(f'{file_path_first_time}が存在します')

            LOG.debug('get_discord_attachment_file is over!')

    async def set_discord_attachment_file(self):
        '''
        discordにファイルを添付

        Parameters
        ----------
        なし

        Returns
        -------
        なし
        '''
        # Herokuの時のみ実施
        if setting.IS_HEROKU:
            # 環境変数によって、添付ファイルのファイル名を変更する
            file_name = self.aes.ENC_FILE if setting.KEEP_DECRYPTED_FILE else self.DATABASE
            LOG.debug('Heroku mode.start set_discord_attachment_file.')

            # チャンネルをチェック(チャンネルが存在しない場合は勝手に作成する)
            guild = discord.utils.get(self.bot.guilds, id=self.saved_dm_guild)
            get_control_channel = discord.utils.get(guild.text_channels, name=self.LIVE_CONTROL_CHANNEL)
            if get_control_channel is None:
                permissions = []
                target = []
                permissions.append(discord.PermissionOverwrite(read_messages=False,read_message_history=False))
                target.append(guild.default_role)
                permissions.append(discord.PermissionOverwrite(read_messages=True,read_message_history=True))
                target.append(self.bot.user)
                overwrites = dict(zip(target, permissions))

                try:
                    get_control_channel = await guild.create_text_channel(name=self.LIVE_CONTROL_CHANNEL, overwrites=overwrites)
                    LOG.info(f'＊＊＊{guild.name}に{self.LIVE_CONTROL_CHANNEL}を作成しました！＊＊＊')
                except discord.errors.Forbidden:
                    msg = f'＊＊＊{guild.name}で{self.LIVE_CONTROL_CHANNEL}の作成に失敗しました！＊＊＊'
                    LOG.error(msg)
                    raise

                if get_control_channel is None:
                    LOG.error(f'なんらかのエラーが発生しました')
                    return

            # チャンネルの最後のメッセージを確認し、所定のメッセージなら削除する
            try:
                last_message = await get_control_channel.history(limit=1).flatten()
            except discord.errors.Forbidden:
                # エラーが発生したら、適当に対応
                msg = f'＊＊＊{guild}のチャンネル({self.LIVE_CONTROL_CHANNEL})読み込みに失敗しました！＊＊＊'
                LOG.error(msg)
                return
            if len(last_message) != 0:
                if last_message[0].content == file_name:
                    await get_control_channel.purge(limit=1)

            # チャンネルにファイルを添付する
            file_path = join(dirname(__file__), 'files' + os.sep + file_name)
            await get_control_channel.send(file_name, file=discord.File(file_path))
            LOG.info(f'＊＊＊{guild.name}の{get_control_channel.name}へファイルを添付しました！＊＊＊')

            LOG.debug('set_discord_attachment_file is over!')

    def decode(self):
        '''
        暗号化されたファイルを復号します（以下の条件に合致する場合は何もしません）
        ＊KEEP_DECRYPTED_FILEがTRUE、かつ、復号済データが存在する場合、何もしない

        Parameters
        ----------
        なし

        Returns
        -------
        なし
        '''
        if not setting.KEEP_DECRYPTED_FILE and os.path.exists(self.aes.DEC_FILE_PATH):
            return
        elif os.path.exists(self.aes.ENC_FILE_PATH):
            self.aes.decode()
            os.remove(self.aes.ENC_FILE_PATH)

    def encode(self):
        '''
        暗号化し、復号データを削除します（以下の条件に合致する場合は削除はしません）
        ＊KEEP_DECRYPTED_FILEがTRUE

        Parameters
        ----------
        なし

        Returns
        -------
        なし
        '''
        if os.path.exists(self.aes.DEC_FILE_PATH):
            self.aes.encode()
            if setting.KEEP_DECRYPTED_FILE:
                os.remove(self.aes.DEC_FILE_PATH)

    def read(self):
        '''
        ファイルを読み込む(先頭2,000件のみ)

        Parameters
        ----------
        なし

        Returns
        -------
        なし
        '''
        # readはdecodeしない
        conn = sqlite3.connect(self.FILE_PATH)
        conn.row_factory = sqlite3.Row
        with conn:
            cur = conn.cursor()
            select_notification_sql = '''
                            select * from notification
                                inner join type on notification.type_id = type.id
                                inner join user on notification.user_id = user.id and user.status = 'VALID'
                                order by notification.id, user.id
                            '''
            LOG.debug(select_notification_sql)
            cur.execute(select_notification_sql)
            self.notification_rows = cur.fetchmany(3000)

            select_live_sql = f'''
                                select * from live
                                where exists (
                                    select 1 from notification
                                    inner join user on notification.user_id = user.id and user.status = 'VALID'
                                    where live.id = notification.live_id
                                )
                                order by live.id'''
            LOG.debug(select_live_sql)
            cur.execute(select_live_sql)
            self.live_rows = cur.fetchmany(2000)
            LOG.debug(self.live_rows)

            LOG.info('＊＊＊＊＊＊読み込みが完了しました＊＊＊＊＊＊')

    def get_user(self, conn, author_id):
        '''
        discordのuser_idをもとに、live notificationのuser_idを取得

        Parameters
        ----------
        conn: sqlite3.Connection
            SQLite データベースコネクション
        author_id: int
            discordのuser_id

        Returns
        -------
        user_id: int
            live notification userのid
        '''
        select_user_sql = 'SELECT id FROM user WHERE discord_user_id = ?'
        with conn:
            cur = conn.cursor()
            cur.execute(select_user_sql, (author_id,))
            fetch = cur.fetchone()
            user_id = fetch[0] if fetch is not None else None
            if user_id is None:
                now = datetime.datetime.now(self.JST)
                create_user_sql = 'INSERT INTO user (discord_user_id, status, created_at, updated_at) VALUES (?,?,?,?)'
                user_param = (author_id, self.STATUS_VALID, now, now)
                conn.execute(create_user_sql, user_param)
                # get id
                get_id_sql = 'SELECT id FROM user WHERE rowid = last_insert_rowid()'
                cur.execute(get_id_sql)
                user_id = cur.fetchone()[0]
                LOG.debug(f'userにid:{id}({author_id})を追加しました')
                conn.commit()
            return user_id

    def get_user_filterword(self, conn, author_id):
        '''
        フィルターワード、説明文の長さを取得

        Parameters
        ----------
        conn: sqlite3.Connection
            SQLite データベースコネクション
        author_id: int
            discordのuser_id

        Returns
        -------
        filter_words: str
            フィルターワード
        long_description: str
            説明文を長くするか
        '''
        select_user_filterword_sql = 'SELECT filter_words, long_description FROM user WHERE discord_user_id = ?'
        with conn:
            cur = conn.cursor()
            cur.execute(select_user_filterword_sql, (author_id,))
            fetch = cur.fetchone()
            if fetch is not None and len(fetch) > 0 and fetch[0] is not None:
                return list(fetch)
            else:
                return '',''

    def get_channel_id(self, conn, channel_id:str):
        '''
        channel_idをもとに、live notification idとtype_idを取得

        Parameters
        ----------
        conn: sqlite3.Connection
            SQLite データベースコネクション
        channel_id: str
            channel_id(YouTubeのchannel_idやニコニコ動画のコミュニティID)

        Returns
        -------
        id: int
            live notificationのid
        type_id: int
            対象のtype_id
        '''
        # 存在をチェック(あるならlive.idを返却)
        select_live_sql = 'SELECT id,type_id FROM live WHERE channel_id=:channel_id'
        with conn:
            cur = conn.cursor()
            list = [channel_id]
            list.append(channel_id.replace('co', ''))
            for channel in list:
                cur.execute(select_live_sql, {'channel_id':channel})
                result = cur.fetchall()
                LOG.debug(result)
                if len(result) != 0:
                    return result[0]
            else:
                return None,None

    def get_channel_name(self, conn, channel_id:str):
        '''
        channel_idをもとに、live notification titleとtype_nameを取得

        Parameters
        ----------
        conn: sqlite3.Connection
            SQLite データベースコネクション
        channel_id: str
            channel_id(YouTubeのchannel_idやニコニコ動画のコミュニティID)

        Returns
        -------
        title: str
            チャンネル名称
        name: str
            type_name(YouTubeやニコ生等)
        '''
        # 存在をチェック(あるならlive.title,type.nameを返却)
        select_live_sql = 'SELECT live.title,type.name FROM live INNER JOIN type on type.id = live.type_id WHERE channel_id=:channel_id'
        with conn:
            cur = conn.cursor()
            list = [channel_id]
            list.append(channel_id.replace('co', ''))
            for channel in list:
                cur.execute(select_live_sql, {'channel_id':channel})
                result = cur.fetchall()
                LOG.debug(result)
                if len(result) != 0:
                    return result[0]
            else:
                return None,None

    def get_live_youtube(self, channel_id:str):
        '''
        channel_idをもとに、live_youtubeを取得

        Parameters
        ----------
        channel_id: str
            channel_id(YouTubeのchannel_id)

        Returns
        -------
        live_youtube: live_youtube
            live_youtube
        '''
        self.decode()
        conn = sqlite3.connect(self.FILE_PATH)
        with conn:
            now = datetime.datetime.now(self.JST)
            overdue_date = now + datetime.timedelta(days=-setting.OVERDUE_DATE_NUM)
            overdue_date_ut = overdue_date.timestamp()
            future_date = now + datetime.timedelta(hours=1)
            future_date_ut = future_date.timestamp()

            # 存在をチェック
            select_live_youtube_sql = 'SELECT * FROM live_youtube WHERE channel_id=:channel_id AND scheduled_start_time>=:overdue_date AND scheduled_start_time<=:future_date AND status=:status'
            cur = conn.cursor()
            cur.execute(select_live_youtube_sql, {'channel_id':channel_id, 'overdue_date':overdue_date_ut, 'future_date':future_date_ut, 'status':self.LIVE_YOUTUBE_STATUS_UNDELIVERED})
            result = cur.fetchall()

        self.encode()
        if len(result) != 0:
            LOG.info(result)
            return result
        else:
            return None

    def select_live_youtube(self, channel_id:str, video_id:str):
        '''
        channel_id,video_idをもとに、live_youtubeを取得

        Parameters
        ----------
        channel_id: str
            channel_id(YouTubeのchannel_id)
        video_id: str
            video_id(YouTubeのvideo_id)

        Returns
        -------
        live_youtube: live_youtube
            live_youtube
        '''
        self.decode()
        conn = sqlite3.connect(self.FILE_PATH)
        with conn:
            # 存在をチェック
            select_live_youtube_sql = 'SELECT * FROM live_youtube WHERE channel_id=:channel_id AND video_id=:video_id'
            cur = conn.cursor()
            cur.execute(select_live_youtube_sql, {'channel_id':channel_id, 'video_id':video_id})
            result = cur.fetchall()
            LOG.debug(result)
        self.encode()
        if len(result) != 0:
            return result[0]
        else:
            return None

    async def set_youtube(self, conn, channel_id:str):
        '''
        YouTubeをセットします

        Parameters
        ----------
        conn: sqlite3.Connection
            SQLite データベースコネクション
        channel_id: str
            YouTubeのchannel_id

        Returns
        -------
        live_id: int
            登録したlive notificationのid
        type_id: int
            登録したlive notificationのtype_id(YouTubeのため、「1」)
        '''
        # xmlを確認
        async with aiohttp.ClientSession() as session:
            async with session.get(self.YOUTUBE_URL+channel_id) as r:
                if r.status == 200:
                    response = ET.fromstring(await r.text())
                    title = response[3].text if len(response) > 3 and response[3] is not None else None
                    recent_id = response[7][1].text if len(response) > 7 and response[7] is not None else None
                    youtube_recent_url = response[7][4].attrib['href'] if len(response) > 7 and response[7][4] is not None else ''
                else:
                    return None,None
        # データ登録
        with conn:
            cur = conn.cursor()
            now = datetime.datetime.now(self.JST)
            # pytubeでYouTube Objectを作成し、動画の長さを取得(長さが0なら未配信とみなす)
            youtube_recent_length = 0
            try:
                youtube_recent_length = YouTube(youtube_recent_url).length
            except:
                pass

            create_live_sql = 'INSERT INTO live (type_id, live_author_id, channel_id, recent_id, recent_movie_length, title, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)'
            live_param = (self.TYPE_YOUTUBE, None, channel_id, recent_id, youtube_recent_length, title, now, now)
            cur.execute(create_live_sql, live_param)
            if setting.LIVE_NOTIFICATION_V2:
                # subscribe
                await pubsub_subscribe.subscribe(channel_id)
            # get id
            get_id_sql = 'SELECT id FROM live WHERE rowid = last_insert_rowid()'
            cur.execute(get_id_sql)
            live_id = cur.fetchone()[0]
            LOG.info(f'liveにid:{live_id}({channel_id})を追加しました')
            conn.commit()
            return live_id,self.TYPE_YOUTUBE

    async def get_youtube_old(self, channel_id:str, recent_id:str, recent_movie_length:int, recent_updated_at:str):
        '''
        YouTubeを確認します(recent_idと比較し、現在最新のrecent_idに更新し、存在しないものを通知対象として返却します)

        Parameters
        ----------
        channel_id: str
            YouTubeのchannel_id
        recent_id: str
            最新のYouTubeの動画ID
        recent_movie_length: int
            最新のYouTubeの動画の長さ(未配信の予約配信の場合「0」になっている)
        recent_updated_at: str
            更新日時

        Returns
        -------
        response_list: list(dict)
            以下のdictを持つリスト
                title: タイトル
                raw_description: 元々の説明文
                description: 説明文(前の説明と同じ場合省略される)
                watch_url: 動画のURL
                started_at: 動画の開始日時
                thumbnail: 動画のサムネイル画像
                recent_id: 最新のYouTubeの動画ID
        '''
        # xmlを確認
        async with aiohttp.ClientSession() as session:
            async with session.get(self.YOUTUBE_URL+channel_id) as r:
                if r.status == 200:
                    response = ET.fromstring(await r.text())
                    youtube_recent_id = response[7][1].text if len(response) > 7 and response[7] is not None else None
                    youtube_recent_url = response[7][4].attrib['href'] if len(response) > 7 and response[7][4] is not None else ''

                    # 何もないなら何もしない
                    if youtube_recent_id is None:
                        return

                    # 謎の削除かチェック
                    recent_updated_at = datetime.datetime.strptime(recent_updated_at, self.DATETIME_FORMAT_DB)
                    started_at_text = response[7][6].text if len(response) > 7 and response[7][6] is not None else ''
                    if started_at_text != '':
                        dt_started_utc = datetime.datetime.fromisoformat(started_at_text)
                        dt_jst = dt_started_utc.astimezone(self.JST)
                        # DBの最近の更新日時の方がxmlの最新よりも新しい場合は、削除か何かと判断し、対応しない(配信前が登録されていた場合は先に進む)
                        if recent_updated_at >= dt_jst and recent_movie_length != 0:
                            return

                    # 動画が追加されたか、前回確認時に動画の長さが0だった場合のみ、pytubeでYouTube Objectを作成し、動画の長さを取得(長さが0なら未配信とみなす)
                    youtube = None
                    if (recent_id != youtube_recent_id) \
                        or (recent_id == youtube_recent_id and recent_movie_length == 0):
                        youtube_recent_length = 0
                        try:
                            youtube = YouTube(youtube_recent_url)
                            youtube_recent_length = youtube.length
                            if youtube_recent_length == 0:
                                youtube.streaming_data # 未配信の場合、Errorが発生
                                youtube_recent_length = 1 # Errorが発生しない場合、1扱いとする
                        except:
                            LOG.info(f'youtube.streaming_data({youtube_recent_id}) is None.')
                    else:
                        # 動画の追加がなく、動画の長さが登録されている場合は対応なし
                        return

                    # 配信開始として通知するべきかチェック
                    live_streaming_start_flg = None
                    # 今回チェックした際に配信開始していたパターン
                    if youtube is not None and recent_movie_length == 0 and youtube_recent_length != 0:
                        live_streaming_start_flg = True
                    # DBの最新動画の長さが0のまま変わってない場合は、対応なし
                    if recent_id == youtube_recent_id and youtube_recent_length == 0:
                        return
                    # 新しく予約配信が追加されたパターン
                    elif youtube_recent_length == 0:
                        live_streaming_start_flg = False
                        live_streaming_start_datetime = ''
                        async with aiohttp.ClientSession() as session:
                            headers={"accept-language": "ja-JP"}
                            async with session.get(youtube_recent_url, headers=headers) as r:
                                if r.status == 200:
                                    html = await r.text()
                                    match_object = re.search(r'subtitleText":{"simpleText":"(.+?) GMT[+-]\d+(:\d+)?"}', html)
                                    if match_object is not None and len(match_object.groups()) >= 1:
                                        live_streaming_start_datetime = match_object.group(1)

                    response_list = []
                    for entry in response[7:]:
                        video_id = entry[1].text if entry[1] is not None else ''
                        # recent_idまで来るか、元々未配信だったものが配信され次の動画に来た場合か、通知最大件数を超えたら追加をやめる
                        if (recent_movie_length != 0 and recent_id == video_id) \
                            or (recent_movie_length == 0 and recent_id != video_id) \
                            or (len(response_list) > self.NOTIFICATION_MAX):
                            break
                        title = entry[3].text if entry[3] is not None else ''
                        watch_url = entry[4].attrib['href'] if entry[4] is not None else ''
                        started_at_text = entry[6].text if entry[6] is not None else ''
                        dt_started_utc = datetime.datetime.fromisoformat(started_at_text)
                        dt_jst_text = dt_started_utc.astimezone(self.JST).strftime(self.DATETIME_FORMAT)

                        # media_groupに属する要素の処理
                        media_group = entry[8] if entry[8] is not None else None
                        thumbnail = ''
                        description = ''
                        if media_group is not None:
                            thumbnail = media_group[2].attrib['url'] if media_group[2] is not None else ''
                            media_group_3 = media_group[3].text if media_group[3] is not None else ''
                            description = self._str_truncate(media_group_3, self.DESCRIPTION_LENGTH, '(以下省略)')

                        # 前回と同じならメッセージを変更しておく
                        raw_description = description
                        if len(response_list) != 0 and response_list[-1].get('raw_description') == description:
                            description = '(1つ前と同じ説明文です)'
                        entry_dict = {'title': title
                                    ,'raw_description': raw_description
                                    ,'description': description
                                    ,'watch_url': watch_url
                                    ,'started_at': dt_jst_text
                                    ,'thumbnail': thumbnail
                                    ,'recent_id': youtube_recent_id}
                        response_list.append(entry_dict)

                    # 最初の1つだけライブ配信開始フラグを入れる
                    if len(response_list) > 0:
                        first_dict = response_list.pop(0)
                        first_dict['live_streaming_start_flg'] = live_streaming_start_flg
                        if live_streaming_start_flg is False:
                            first_dict['live_streaming_start_datetime'] = live_streaming_start_datetime
                        response_list.insert(0, first_dict)
                    # recent_idの更新処理
                    self.decode()
                    conn = sqlite3.connect(self.FILE_PATH)
                    with conn:
                        cur = conn.cursor()
                        now = datetime.datetime.now(self.JST)
                        update_recent_id_sql = 'UPDATE live SET recent_id = ?, recent_movie_length = ?, updated_at = ? WHERE channel_id = ?'
                        param = (youtube_recent_id, youtube_recent_length, now, channel_id)
                        cur.execute(update_recent_id_sql, param)
                        # get id
                        get_id_sql = 'SELECT id FROM live WHERE channel_id = ?'
                        cur.execute(get_id_sql, (channel_id,))
                        live_id = cur.fetchone()[0]
                        LOG.info(f'live(id:{live_id}({channel_id}))のrecent_idを{youtube_recent_id}に更新しました(更新前:{recent_id})')
                    conn.commit()
                    self.read()
                    self.encode()
                    # Herokuの時のみ、チャンネルにファイルを添付する
                    try:
                        await self.set_discord_attachment_file()
                    except discord.errors.Forbidden:
                        message = f'＊＊＊{self.saved_dm_guild}へのチャンネル作成に失敗しました＊＊＊'
                        LOG.error(message)
                        return message

                    return response_list

    async def get_youtube(self, channel_id:str, video_id:str, updated:int=None, db_flg:bool=False):
        '''
        YouTubeを確認します(予約リストを確認し、開始されているものを通知対象として返却します)

        Parameters
        ----------
        channel_id: str
            YouTubeのchannel_id
        video_id: str
            YouTubeのvideo_id
        updated: int
            updated
        db_flg: bool
            DBからアクセスしているか否か(デフォルトはFalse)

        Returns
        -------
        response_list: list(dict)
            以下のdictを持つリスト
                title: タイトル
                raw_description: 説明文(互換性維持のため同じものを入れている)
                description: 説明文
                watch_url: 動画のURL
                started_at: 動画の開始日時
                thumbnail: 動画のサムネイル画像
        '''
        updated_at = None
        if updated is not None:
            updated_at = updated.strftime(self.DATETIME_FORMAT)
        if not db_flg:
            result = self.select_live_youtube(channel_id, video_id)
            # 存在しない場合は、新規の情報がきた扱いとする
            if not result:
                LOG.info(f'<pubsub>channel_id:{channel_id}, video_id:{video_id}')
            else:
                # DBに存在し、DBのほうが新しい場合は無視
                LOG.debug(f'''pubsub:{updated.strftime(self.DATETIME_FORMAT)}''')
                db_updated_datetime = datetime.datetime.strptime(result[-1], self.DATETIME_FORMAT_DB)
                LOG.debug(f'''DB    :{db_updated_datetime.strftime(self.DATETIME_FORMAT)}''')
                # 1分以内は誤差と考える
                db_updated_datetime = db_updated_datetime + timedelta(minutes=1)
                if updated is not None and updated <= db_updated_datetime:
                    LOG.info(f'DBのほうが新しいため却下:{video_id} ->{db_updated_datetime.strftime(self.DATETIME_FORMAT)}')
                    return
                # 配信済となっている場合は無視
                if result[2] == self.LIVE_YOUTUBE_STATUS_DELIVERED:
                    LOG.info(f'DBが配信済扱いのため却下:{video_id} ->{result[3]}')
                    return
        # xmlを確認
        response_list = await self.get_youtube_and_write(channel_id, video_id, updated_at)
        return response_list

    async def get_youtube_and_write(self, channel_id:str, video_id:str, updated_at_by_page:str=''):
        # 動画が追加されたか、前回確認時に動画の長さが0だった場合のみ、pytubeでYouTube Objectを作成し、動画の長さを取得(長さが0なら未配信とみなす)
        youtube = None
        youtube_url = self.get_youtube_url(video_id)

        # 初期化
        liveStartTime,title,lengthSeconds,publish_datetime_str,live_streaming_start_datetime,live_streaming_start_jst,live_streaming_end_datetime = None,None,None,None,None,None,None
        description,author = '',''
        isLiveNow = False

        # 実際にアクセスしてみて、動画情報を取得
        async with aiohttp.ClientSession() as session:
            headers={"accept-language": "ja-JP"}
            async with session.get(youtube_url, headers=headers) as r:
                if r.status == 200:
                    html_raw = await r.text()
                    html = html_raw.replace('\u3000','  ').replace('\u200d',' ').replace('\u200D',' ').replace('\\u0026','&')
                    if html_raw != html:
                        LOG.info('html変換実施')
                    # title
                    match_object = re.search(r'"title":{"simpleText":"(.+?)"}', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        title = match_object.group(1)
                        LOG.debug(f'title:{title}')
                    # author
                    match_object = re.search(r'"viewCount":"\d+?","author":"(.+?)",', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        author = match_object.group(1)
                        LOG.debug(f'author:{author}')
                    # scheduledStartTime startTimestamp":"2023-11-19T05:17:18+00:00"},
                    match_object = re.search(r'"liveStreamOfflineSlateRenderer":{"scheduledStartTime":"(\d+)"', html)
                    match_object2 = re.search(r'"startTimestamp":"(.+?)"\}?,', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        liveStartTime = int(match_object.group(1))
                        dt = datetime.datetime.fromtimestamp(liveStartTime)
                        live_streaming_start_jst = dt.astimezone(self.JST)
                        live_streaming_start_datetime = dt.strftime(self.DATETIME_FORMAT)
                        LOG.debug(f'live_streaming_start_datetime:{live_streaming_start_datetime}')
                    elif match_object2 is not None and len(match_object2.groups()) >= 1:
                        liveStartTime_mo = match_object2.group(1)
                        live_streaming_start = datetime.datetime.strptime(liveStartTime_mo, self.DATETIME_FORMAT_TZ)
                        live_streaming_start_jst = live_streaming_start.astimezone(self.JST)
                        liveStartTime = int(live_streaming_start_jst.timestamp())
                        live_streaming_start_datetime = live_streaming_start_jst.strftime(self.DATETIME_FORMAT)
                        LOG.debug(f'live_streaming_start_datetime:{live_streaming_start_datetime}')
                    # thumbnail
                    match_object = re.search(r'"thumbnail":{"thumbnails":\[{"url":"(.+?)",', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        thumbnail = match_object.group(1)
                        LOG.debug(f'thumbnail:{thumbnail}')
                    match_object = re.search(r'"thumbnail":{"thumbnails":\[.+{"url":"(.+?)","width":1920,"height":1080}\]', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        thumbnail = match_object.group(1)
                        LOG.debug(f'thumbnail:{thumbnail}')
                    # lengthSeconds
                    match_object = re.search(r'"},"lengthSeconds":"(.+?)",', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        lengthSecondsStr = match_object.group(1)
                        lengthSeconds = int(lengthSecondsStr) if type(lengthSecondsStr) is str else lengthSecondsStr
                        LOG.debug(f'lengthSeconds:{lengthSecondsStr}')
                    # description
                    match_object = re.search(r'"shortDescription":"(.+?)",', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        description = self._str_truncate(match_object.group(1), self.DESCRIPTION_LENGTH, '(以下省略)')
                        LOG.debug(f'description:{description}')
                    # publishDate
                    match_object = re.search(r'"publishDate":"(.+?)",', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        publishDate = match_object.group(1)
                        publish_datetime = datetime.datetime.strptime(publishDate, self.DATETIME_FORMAT_TZ)
                        publish_datetime_jst = publish_datetime.astimezone(self.JST)
                        publish_datetime_str = publish_datetime_jst.strftime(self.DATETIME_FORMAT)
                        LOG.info(f'publishDate:{publish_datetime_str}')
                    # isLiveNow
                    match_object = re.search(r'"isLiveNow":(.+?)\}?,', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        isLiveNowStr = match_object.group(1)
                        if isLiveNowStr is not None and type(isLiveNowStr) is str:
                            isLiveNow = True if isLiveNowStr.upper() == 'TRUE' else False
                        LOG.info(f'isLiveNow:{isLiveNowStr}')
                    match_object = re.search(r'"endTimestamp":"(.+?)"\}?,', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        striemingEndTime = match_object.group(1)
                        live_streaming_end = datetime.datetime.strptime(striemingEndTime, self.DATETIME_FORMAT_TZ)
                        live_streaming_end_jst = live_streaming_end.astimezone(self.JST)
                        live_streaming_end_datetime = live_streaming_end_jst.strftime(self.DATETIME_FORMAT)

        # publishDateが古いものは対象外にする
        now = datetime.datetime.now(self.JST)
        days_1_ago = now - timedelta(days=1)
        if publish_datetime_str:
            if isLiveNow:
                LOG.info(f'ライブ中のためチェック(video_id: {video_id}, 開始時刻:{live_streaming_start_datetime})')
            elif live_streaming_start_jst is not None and live_streaming_start_jst > days_1_ago:
                LOG.info(f'開始時間が最近のためチェック(video_id: {video_id}, 開始時刻:{live_streaming_start_datetime})')
            elif publish_datetime_jst < days_1_ago:
                msg = f'1日以上古いため対応不要(video_id: {video_id}, publishDate:{publish_datetime_str})'
                if live_streaming_start_jst is not None:
                    msg += f', live_streaming_start_jst:{live_streaming_start_jst}'
                LOG.info(msg)
                return
            else:
                # TODO:デバッグ用のため、後で消す
                LOG.info(f'古くない:(video_id: {video_id}, publishDate:{publish_datetime_str})')

        update_flg = False
        # lengthSecondsが0の場合のみ、実際にストリーミングが開始しているか確認
        LOG.debug('length............')
        live_streaming_start_flg = None
        youtube_recent_length = lengthSeconds
        # 画面上でライブ中になっている場合配信中扱い
        if isLiveNow:
            youtube_recent_length = 1
            live_streaming_start_flg = True
            LOG.info(f'ライブ中: {youtube_url}')
            update_flg = True
        # 以下は不要かもしれないが、念の為チェック
        elif youtube_recent_length is not None and (youtube_recent_length == 0 or youtube_recent_length == '0'):
            try:
                LOG.info('youtube_check............')
                youtube = YouTube(youtube_url)
                youtube_recent_length = youtube.length
                if youtube_recent_length == 0:
                    youtube.streaming_data # 未配信の場合、Errorが発生
                    youtube_recent_length = 1 # Errorが発生しない場合、1扱いとする
                    live_streaming_start_flg = True
                    LOG.info('youtube_check_1')
                    update_flg = True
                else:
                    update_flg = True
                    LOG.info('youtube_check_2')
            except:
                LOG.info(f'youtube.streaming_data({video_id}) is None.')
                live_streaming_start_flg = False

        NOTIF = None
        try:
            # recent_idの更新処理
            self.decode()
            conn = sqlite3.connect(self.FILE_PATH)
            LOG.debug('conn')
            with conn:
                cur = conn.cursor()

                # 検索
                select_live_id = 'select updated_at FROM live WHERE recent_id = ?'
                param = (video_id,)
                cur.execute(select_live_id, param)
                row = cur.fetchone()
                updated_at = row[0] if row else None

                select_live_youtube_status = 'select status, scheduled_start_time FROM live_youtube WHERE video_id = ?'
                param = (video_id,)
                cur.execute(select_live_youtube_status, param)
                row = cur.fetchone()
                live_youtube_status = row[0] if row else None
                scheduled_start_time = row[1] if row else None
                # live_youtubeが取得できた場合
                if live_youtube_status is not None:
                    LOG.info(f'live_youtube_status:{live_youtube_status}')
                    # DELIVEREDされており、updateもあれば通知済
                    if updated_at is not None \
                    and live_youtube_status == self.LIVE_YOUTUBE_STATUS_DELIVERED \
                    and scheduled_start_time == liveStartTime:
                        LOG.info(f'通知済: {video_id} -> {updated_at}')
                        return

                # recent_idが違う場合のみ、liveを更新
                now = datetime.datetime.now(self.JST)
                if updated_at is None:
                    # liveの更新
                    update_recent_id_sql = 'UPDATE live SET recent_id = ?, recent_movie_length = ?, updated_at = ? WHERE channel_id = ?'
                    param = (video_id, youtube_recent_length, now, channel_id)
                    cur.execute(update_recent_id_sql, param)
                    # get id
                    get_id_sql = 'SELECT id FROM live WHERE channel_id = ?'
                    cur.execute(get_id_sql, (channel_id,))
                    live_id = cur.fetchone()[0]
                    LOG.info(f'live(id:{live_id}({channel_id}))のrecent_idを{video_id}に更新しました')

                # live_youtubeについて、データがあれば更新、それ以外の場合は登録
                if live_youtube_status is not None:
                    # 開始予定日時変更文言
                    scheduled_time = ''
                    if scheduled_start_time != liveStartTime:
                        scheduled_time = f'(変更あり:{str(scheduled_start_time)} -> {str(liveStartTime)})'
                    elif live_youtube_status == self.LIVE_YOUTUBE_STATUS_UNDELIVERED and not isLiveNow:
                        LOG.info(f'更新不要: {video_id}')
                        return
                    # youtube_liveの更新
                    LOG.debug('!!!!!!youtube_liveの更新!!!!!!')
                    update_recent_id_sql = 'UPDATE live_youtube SET status = ?, scheduled_start_time = ?, updated_at = ? WHERE video_id = ?'
                    if youtube_recent_length and youtube_recent_length > 0:
                        param = (self.LIVE_YOUTUBE_STATUS_DELIVERED, liveStartTime, now, video_id,)
                        LOG.info(f'live_youtube(id:{video_id}({channel_id}))を{self.LIVE_YOUTUBE_STATUS_DELIVERED}に更新しました{scheduled_time}')
                        NOTIF = '更新(開始)'
                    else:
                        param = (self.LIVE_YOUTUBE_STATUS_UNDELIVERED, liveStartTime, now, video_id,)
                        LOG.info(f'live_youtube(id:{video_id}({channel_id}))を{self.LIVE_YOUTUBE_STATUS_UNDELIVERED}に更新しました{scheduled_time}')
                        NOTIF = '更新(何か変更)'
                    cur.execute(update_recent_id_sql, param)
                    conn.commit()
                else:
                    LOG.debug('!!!!!!youtube_liveの追加!!!!!!')
                    insert_live_youtube_sql = 'INSERT INTO live_youtube (channel_id,video_id,status,title,scheduled_start_time,created_at,updated_at) VALUES (?,?,?,?,?,?,?)'
                    if youtube_recent_length and youtube_recent_length > 0 \
                    and (live_streaming_start_jst is None or (live_streaming_start_jst is not None and live_streaming_start_jst <= now)):
                        insert_param = (channel_id, video_id, self.LIVE_YOUTUBE_STATUS_DELIVERED, title, liveStartTime, now, now)
                        NOTIF = '追加(開始)'
                    else:
                        live_streaming_start_flg = False
                        LOG.debug('!!!!!!youtube_liveの追加(0sec)!!!!!!')
                        insert_param = (channel_id, video_id, self.LIVE_YOUTUBE_STATUS_UNDELIVERED, title, liveStartTime, now, now)
                        NOTIF = '追加(予約)'
                    cur.execute(insert_live_youtube_sql, insert_param)
                    conn.commit()
        finally:
            # 更新が発生していた場合のみ、再読み込み
            if NOTIF:
                self.read()
            self.encode()
            LOG.debug('!!!!!!db end!!!!!!')

        # 定期更新処理の場合(その場合、updated_atがNone)、ライブ再生開始じゃない場合は無視
        if updated_at_by_page is None and not update_flg:
            LOG.info('定期更新処理の場合、ライブ開始ではないパターンは通知なし')
            self.encode()
            return
        LOG.debug('!!!!!!return!!!!!!')
        # update_atをうめる
        if updated_at_by_page is None:
            if live_streaming_end_datetime is not None:
                updated_at_by_page = live_streaming_end_datetime
            elif live_streaming_start_datetime is not None:
                updated_at_by_page = live_streaming_start_datetime
            else:
                updated_at_by_page = publish_datetime_str
        LOG.info(f'{video_id}は何かしら通知されるはず！ -> {NOTIF}')
        return [{
            'title': title
            ,'raw_description': description
            ,'description': description
            ,'watch_url': youtube_url
            ,'started_at': live_streaming_start_datetime
            ,'thumbnail': thumbnail
            ,'live_streaming_start_flg': live_streaming_start_flg
            ,'channel_id': channel_id
            ,'author': author
            ,'updated_at': updated_at_by_page
            }]

    def get_youtube_url(self, video_id):
        return self.YOUTUBE_VIDEO_URL + video_id

    async def set_nicolive(self, conn, channel_id:str):
        '''
        ニコ生をセットします

        Parameters
        ----------
        conn: sqlite3.Connection
            SQLite データベースコネクション
        channel_id: str
            ニコ生のchannel_id

        Returns
        -------
        live_id: int
            登録したlive notificationのid
        type_id: int
            登録したlive notificationのtype_id(ニコ生のため、「2」)
        '''
        channel_id = channel_id.replace('co', '')
        nico_communities_url = f'https://com.nicovideo.jp/api/v1/communities/{channel_id}/lives.json?limit=1&offset=0'
        async with aiohttp.ClientSession() as session:
            async with session.get(nico_communities_url) as r:
                if r.status == 200:
                    nico_communities_response = await r.json()
                    nico_user_id = str(nico_communities_response['data']['lives'][0]['user_id'])
                    nico_recent_id = str(nico_communities_response['data']['lives'][0]['id'])
                else:
                    return None,None
        # get user
        nico_user_url = f'https://account.nicovideo.jp/api/public/v1/users/{nico_user_id}.json'
        async with aiohttp.ClientSession() as session:
            async with session.get(nico_user_url) as r:
                if r.status == 200:
                    nico_user_response = await r.json()
                    nico_nickname = nico_user_response['data']['nickname']
                else:
                    return None,None
        # データ登録
        with conn:
            cur = conn.cursor()
            now = datetime.datetime.now(self.JST)
            create_live_sql = 'INSERT INTO live (type_id, live_author_id, channel_id, recent_id, title, created_at, updated_at) VALUES (?,?,?,?,?,?,?)'
            live_param = (self.TYPE_NICOLIVE, int(nico_user_id), channel_id, nico_recent_id, nico_nickname, now, now)
            cur.execute(create_live_sql, live_param)
            # get id
            get_id_sql = 'SELECT id FROM live WHERE rowid = last_insert_rowid()'
            cur.execute(get_id_sql)
            live_id = cur.fetchone()[0]
            LOG.info(f'liveにid:{id}({channel_id})を追加しました')
            conn.commit()
            return live_id,self.TYPE_NICOLIVE

    async def get_nicolive(self, channel_id:str, recent_id:str):
        '''
        ニコ生を確認します(放送中の場合、recent_idに登録し、通知対象を返却します)

        Parameters
        ----------
        channel_id: str
            ニコ生のchannel_id
        recent_id: str
            最新の動画ID

        Returns
        -------
        response_list: list(dict)
            以下のdictを持つリスト
                title: タイトル
                description: 説明文(前の説明と同じ場合省略される)
                watch_url: 動画のURL
                started_at: 動画の開始日時
                recent_id: 最新の動画ID
        '''
        # json
        nico_live_url = f'https://com.nicovideo.jp/api/v1/communities/{channel_id}/lives/onair.json'
        async with aiohttp.ClientSession() as session:
            async with session.get(nico_live_url) as r:
                if r.status == 200:
                    nico_live_response = await r.json()
                    nico_live_status = nico_live_response['meta']['status']
                    LOG.debug(nico_live_status)
                    # 放送中かチェック
                    if nico_live_status != 200:
                        return
                    nico_live_id = nico_live_response['data']['live']['id']
                    # すでに通知済かチェック
                    if recent_id == nico_live_id:
                        return

                    # recent_idの更新処理
                    self.decode()
                    conn = sqlite3.connect(self.FILE_PATH)
                    with conn:
                        cur = conn.cursor()
                        now = datetime.datetime.now(self.JST)
                        update_recent_id_sql = 'UPDATE live SET recent_id = ?, updated_at = ? WHERE channel_id = ?'
                        param = (nico_live_id, now, channel_id)
                        cur.execute(update_recent_id_sql, param)
                        # get id
                        get_id_sql = 'SELECT id FROM live WHERE channel_id = ?'
                        cur.execute(get_id_sql, (channel_id,))
                        live_id = cur.fetchone()[0]
                        LOG.info(f'liveにid:{live_id}({channel_id})のrecent_idを{nico_live_id}に更新しました')
                    conn.commit()
                    self.read()
                    self.encode()
                    # Herokuの時のみ、チャンネルにファイルを添付する
                    try:
                        await self.set_discord_attachment_file()
                    except discord.errors.Forbidden:
                        message = f'＊＊＊{self.saved_dm_guild}へのチャンネル作成に失敗しました＊＊＊'
                        LOG.error(message)
                        return message

                    # ニコ生は地味にISOフォーマットではないので変換する(replace('+0900','+09:00'))
                    nico_started_at = nico_live_response['data']['live']['started_at'].replace('+0900','+09:00')
                    dt_started_jst = datetime.datetime.fromisoformat(nico_started_at)
                    dt_jst_text = dt_started_jst.strftime(self.DATETIME_FORMAT)

                    # 説明文の文字数削減
                    description = self._str_truncate(nico_live_response['data']['live']['description'], self.DESCRIPTION_LENGTH, '(以下省略)')

                    # 通知対象として返却
                    return [{'title': str(nico_live_response['data']['live']['title'])
                            ,'description': str(description)
                            ,'watch_url': str(nico_live_response['data']['live']['watch_url'])
                            ,'started_at': dt_jst_text
                            ,'recent_id': nico_live_id
                            }]

    async def set_twitcasting(self, conn, channel_id:str):
        '''
        ツイキャスをセットします

        Parameters
        ----------
        conn: sqlite3.Connection
            SQLite データベースコネクション
        channel_id: str
            ツイキャスのchannel_id

        Returns
        -------
        live_id: int
            登録したlive notificationのid
        type_id: int
            登録したlive notificationのtype_id(ツイキャスのため、「3」)
        '''
        # json
        twicas_latest_movie_url = f'https://frontendapi.twitcasting.tv/users/{channel_id}/latest-movie'
        nickname = channel_id
        async with aiohttp.ClientSession() as session:
            async with session.get(twicas_latest_movie_url) as r:
                if r.status == 200:
                    # 最新の動画IDをリクエスト。存在する場合はユーザーページを開き、投稿者名を取得
                    twicas_user_url = f'https://twitcasting.tv/{channel_id}'
                    async with aiohttp.ClientSession() as session:
                        async with session.get(twicas_user_url) as r:
                            if r.status == 200:
                                html = await r.text()
                                match_object = re.search(r'<span class="tw-user-nav-name">(.+?)\s*</span>', html)
                                if match_object is not None and len(match_object.groups()) >= 1:
                                    nickname = unescape(match_object.group(1))
                else:
                    return None,None
        # データ登録
        with conn:
            cur = conn.cursor()
            now = datetime.datetime.now(self.JST)
            create_live_sql = 'INSERT INTO live (type_id, live_author_id, channel_id, recent_id, title, created_at, updated_at) VALUES (?,?,?,?,?,?,?)'
            live_param = (self.TYPE_TWITCASTING, None, channel_id, None, nickname, now, now)
            cur.execute(create_live_sql, live_param)
            # get id
            get_id_sql = 'SELECT id FROM live WHERE rowid = last_insert_rowid()'
            cur.execute(get_id_sql)
            live_id = cur.fetchone()[0]
            LOG.info(f'liveにid:{id}({channel_id})を追加しました')
            conn.commit()
            return live_id,self.TYPE_TWITCASTING

    async def get_twitcasting(self, channel_id:str, recent_id:str):
        '''
        ツイキャスを確認します(放送中の場合、recent_idに登録し、通知対象を返却します)

        Parameters
        ----------
        channel_id: str
            ツイキャスのchannel_id
        recent_id: str
            最新の動画ID

        Returns
        -------
        response_list: list(dict)
            以下のdictを持つリスト
                title: タイトル
                description: 説明文
                watch_url: 動画のURL
                started_at: 動画の開始日時
                thumbnail: 動画のサムネイル画像(あれば)
                recent_id: 最新の動画ID
        '''
        # json
        twicas_latest_movie_url = f'https://frontendapi.twitcasting.tv/users/{channel_id}/latest-movie'
        async with aiohttp.ClientSession() as session:
            async with session.get(twicas_latest_movie_url) as r:
                if r.status == 200:
                    twicas_latest_movie_response = await r.json()
                    twicas_latest_movie = twicas_latest_movie_response['movie']
                    LOG.debug(channel_id + '-> ' + str(twicas_latest_movie))
                    # 放送中かチェック
                    if twicas_latest_movie is None or twicas_latest_movie.get('is_on_live') is None or twicas_latest_movie.get('is_on_live') is False:
                        return
                    twicas_latest_movie_id = twicas_latest_movie.get('id')
                    # すでに通知済かチェック
                    if recent_id == str(twicas_latest_movie_id):
                        return

                    # recent_idの更新処理
                    self.decode()
                    conn = sqlite3.connect(self.FILE_PATH)
                    with conn:
                        cur = conn.cursor()
                        now = datetime.datetime.now(self.JST)
                        update_recent_id_sql = 'UPDATE live SET recent_id = ?, updated_at = ? WHERE channel_id = ?'
                        param = (twicas_latest_movie_id, now, channel_id)
                        cur.execute(update_recent_id_sql, param)
                        # get id
                        get_id_sql = 'SELECT id FROM live WHERE channel_id = ?'
                        cur.execute(get_id_sql, (channel_id,))
                        live_id = cur.fetchone()[0]
                        LOG.info(f'liveにid:{live_id}({channel_id})のrecent_idを{twicas_latest_movie_id}に更新しました')
                    conn.commit()
                    self.read()
                    self.encode()
                    # Herokuの時のみ、チャンネルにファイルを添付する
                    try:
                        await self.set_discord_attachment_file()
                    except discord.errors.Forbidden:
                        message = f'＊＊＊{self.saved_dm_guild}へのチャンネル作成に失敗しました＊＊＊'
                        LOG.error(message)
                        return message

                    twicas_get_token_url = 'https://twitcasting.tv/happytoken.php'
                    form_data = aiohttp.FormData()
                    form_data.add_field(name='movie_id', value=twicas_latest_movie_id)
                    temp_description = ''
                    async with aiohttp.ClientSession() as session:
                        async with session.post(twicas_get_token_url, data=form_data) as r:
                            if r.status == 200:
                                twicas_get_token_response = await r.json()
                                if twicas_get_token_response is not None and twicas_get_token_response.get('token') is not None:
                                    # ユーザーページを開き、タイトル、説明文を取得
                                    twicas_user_url = f'https://twitcasting.tv/{channel_id}'
                                    async with aiohttp.ClientSession() as session:
                                        async with session.get(twicas_user_url) as r:
                                            if r.status == 200:
                                                html = await r.text()
                                                match_object_title = re.search(r'<meta property="og:title" content="(.*)"/>', html)
                                                if match_object_title is not None and len(match_object_title.groups()) >= 1:
                                                    title = unescape(match_object_title.group(1))
                                                match_object_description = re.search(r'<meta name="description"\n\s+content="(.*)"/>', html)
                                                if match_object_description is not None and len(match_object_description.groups()) >= 1:
                                                    temp_description = unescape(match_object_description.group(1))
                                                    temp_description = re.sub(title+r'\s*/\s*', '', temp_description)
                                    token = twicas_get_token_response.get('token')
                                    params = {'token': token}
                                    twicas_viewer_url = f'https://frontendapi.twitcasting.tv/movies/{twicas_latest_movie_id}/status/viewer'
                                    # 配信名など取得
                                    async with aiohttp.ClientSession() as session:
                                        async with session.get(twicas_viewer_url, params=params) as r:
                                            if r.status == 200:
                                                twicas_viewer_response = await r.json()
                                                twicas_viewer_movie = twicas_viewer_response.get('movie')
                                    # 配信開始時刻の取得
                                    twicas_info_url = f'https://frontendapi.twitcasting.tv/movies/{twicas_latest_movie_id}/info'
                                    async with aiohttp.ClientSession() as session:
                                        async with session.get(twicas_info_url, params=params) as r:
                                            if r.status == 200:
                                                twicas_info_response = await r.json()
                                                if twicas_info_response is not None and twicas_info_response.get('started_at') is not None:
                                                    started_datetime = datetime.datetime.fromtimestamp(twicas_info_response.get('started_at'), self.JST)
                                                    dt_jst_text = started_datetime.strftime(self.DATETIME_FORMAT)
                                    # サムネイルの取得(aiohttpだと上手くいかなかったのでrequestsを使用)
                                    twicas_thumbnail_url = f'https://twitcasting.tv/userajax.php?c=updateindexthumbnail&m={twicas_latest_movie_id}'
                                    resp = requests.get(twicas_thumbnail_url, allow_redirects=False)
                                    if resp.headers.get('Location'):
                                        thumbnail = resp.headers.get('Location')
                            else:
                                return

                    # 説明文の組み立て
                    twicas_viewer_movie_category = twicas_viewer_movie.get('category')
                    temp_description = temp_description + f'''\nカテゴリ: {twicas_viewer_movie_category.get('name')}''' if twicas_viewer_movie_category is not None and twicas_viewer_movie_category.get('name') is not None else temp_description
                    temp_description = temp_description + f'''\nピン留め: {twicas_viewer_movie.get('pin_message')}''' if twicas_viewer_movie.get('pin_message') is not None else temp_description
                    description = self._str_truncate(temp_description, self.DESCRIPTION_LENGTH, '(以下省略)')

                    twicas_url = f'https://twitcasting.tv/{channel_id}/movie/{twicas_latest_movie_id}'
                    twicas_dict = {'title': title
                                    ,'description': str(description)
                                    ,'watch_url': twicas_url
                                    ,'started_at': dt_jst_text
                                    ,'recent_id': str(twicas_latest_movie_id)}
                    if thumbnail:
                        twicas_dict['thumbnail'] = thumbnail

                    # 通知対象として返却
                    return [twicas_dict]

    def set_notification(self, conn, type_id:int, user_id:int, live_id:int, notification_guild:int, notification_channel:int, mention:str, channel_id:str):
        '''
        ((直接使わない想定)通知をセットします(すでに登録された通知の場合、登録しません)

        Parameters
        ----------
        conn: sqlite3.Connection
            SQLite データベースコネクション
        type_id: int
            live notificationのtype_id
        user_id: int
            live notificationのuser_id
        live_id: int
            live notificationのlive_id
        notification_guild: int
            通知先のguild_id(DMの場合None)
        notification_channel: int
            通知先のchannel_id(DMの場合None)
        mention: str
            メンション
        channel_id: str
            登録するchannel_id

        Returns
        -------
        message: str
            登録した配信通知についてのメッセージ
        '''
        LOG.debug('set_notification: ' + channel_id)
        # notificationを検索(live_id+user_id+notification_channelがあれば処理終了)
        where_notification_channel = 'notification_channel=:notification_channel'
        if notification_channel is None:
            where_notification_channel = 'notification_channel is null'
        select_notification_sql = f'SELECT id FROM notification WHERE user_id=:user_id and live_id=:live_id and {where_notification_channel}'
        with conn:
            cur = conn.cursor()
            param = {'user_id':user_id, 'live_id':live_id, 'notification_channel':notification_channel}
            cur.execute(select_notification_sql, param)
            fetch = cur.fetchone()
            notification_id = fetch[0] if fetch is not None else None
            if notification_id is not None:
                message = f'すでに通知対象として登録済みです(notificaiton_id: {str(notification_id)})'
                LOG.debug(message)
                return message
            else:
                now = datetime.datetime.now(self.JST)
                create_notificationsql = 'INSERT INTO notification (type_id, user_id, live_id, notification_guild, notification_channel, mention, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)'
                notification_param = (type_id, user_id, live_id, notification_guild, notification_channel, mention, now, now)
                cur.execute(create_notificationsql, notification_param)
                # get id
                get_id_sql = 'SELECT id FROM notification WHERE rowid = last_insert_rowid()'
                cur.execute(get_id_sql)
                id = cur.fetchone()[0]
                live_title,type_name = self.get_channel_name(conn, channel_id)
                message = f'notificationにid:{id}を追加しました({live_title}({type_name})のこと)'
                LOG.debug(message)
                conn.commit()
            return message

    async def register_live_notification(self, guild_id: int, author_id:int, channel_id:str, notification_channel_id: int, mention: str):
        '''
        配信通知を登録

        Parameters
        ----------
        guild_id: int
            guild_id(DMの場合None)
        author_id: int
            discordのuser_id
        channel_id: str
            登録するchannel_id
        notification_channel_id: int
            通知先のchannel_id(DMの場合None)
        mention: str
            メンション

        Returns
        ----------
        message: str
            登録した通知についてのメッセージ
        '''
        self.decode()
        conn = sqlite3.connect(self.FILE_PATH)
        with conn:
            user_id = self.get_user(conn, author_id)
            live_id,type_id = self.get_channel_id(conn, channel_id)
            if live_id is None:
                # YouTube @xxxxの変換、その後、チャンネル確認
                match_object = re.search(r'https://www.youtube.com/@(.+)$', channel_id)
                if match_object is not None and len(match_object.groups()) >= 1:
                    LOG.debug(f'変換前->channel_id: {channel_id}')
                    async with aiohttp.ClientSession() as session:
                        headers={"accept-language": "ja-JP"}
                        async with session.get(match_object.group(0), headers=headers) as r:
                            if r.status == 200:
                                html = await r.text()
                                match_object2 = re.search(r'"channelUrl":"(https://www.youtube.com/channel/.+?)"', html)
                                if match_object2 is not None and len(match_object2.groups()) >= 1:
                                    channel_id = match_object2.group(1)
                                    LOG.debug(f'変換後->channel_id: {channel_id}')
                match_object = re.search(r'https://www.youtube.com/channel/(.+)$', channel_id)
                if match_object is not None and len(match_object.groups()) >= 1:
                    live_id,type_id = self.get_channel_id(conn, match_object.group(1))
                    channel_id = match_object.group(1)
                    if live_id is None:
                        live_id,type_id = await self.set_youtube(conn, channel_id)
                # 下のelseはなんの意味があるんだ？(以降のやつも同じ...)
                else:
                    live_id,type_id = await self.set_youtube(conn, channel_id)
                if live_id is None:
                    # NicoLive
                    match_object = re.search(r'https://com.nicovideo.jp/community/(.+)$', channel_id)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        live_id,type_id = self.get_channel_id(conn, match_object.group(1))
                        channel_id = match_object.group(1)
                        if live_id is None:
                            live_id,type_id = await self.set_nicolive(conn, channel_id)
                    else:
                        live_id,type_id = await self.set_nicolive(conn, channel_id)
                if live_id is None:
                    # Twitcasting
                    match_object = re.search(r'https://twitcasting.tv/(.+?)((?=/)|$)', channel_id)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        live_id,type_id = self.get_channel_id(conn, match_object.group(1))
                        channel_id = match_object.group(1)
                        if live_id is None:
                            live_id,type_id = await self.set_twitcasting(conn, channel_id)
                    else:
                        live_id,type_id = await self.set_twitcasting(conn, channel_id)
                if live_id is None:
                    conn.commit()
                    self.read()
                    self.encode()
                    return '配信通知の登録に失敗しました(対応していないチャンネルIDです)'

            message = self.set_notification(conn, type_id, user_id, live_id, guild_id, notification_channel_id, mention, channel_id)
            conn.commit()
            self.read()
        self.encode()

        # Herokuの時のみ、チャンネルにファイルを添付する
        try:
            await self.set_discord_attachment_file()
        except discord.errors.Forbidden:
            message = f'＊＊＊{self.saved_dm_guild}へのチャンネル作成に失敗しました＊＊＊'
            LOG.error(message)
            return message
        return message

    def read_db(self):
        '''
        DBを再読込します

        Parameters
        ----------
        なし

        Returns
        ----------
        なし
        '''
        self.decode()
        self.read()
        self.encode()

    def list_live_notification(self, author_id:int, guild_id:str=None):
        '''
        登録した配信通知を表示します

        Parameters
        ----------
        author_id: int
            discordのuser_id
        guild_id: str
            discordのguild_id

        Returns
        ----------
        result_dict_list: list(result_dict)
            以下のdictを持つリスト
                notification_id: live notificationのid
                type: live notificationのtype_id
                title: チャンネルのタイトル
                channel_id: チャンネルのchannel_id
                channel: チャンネルのchannel_id
                recent_id: 最新の動画ID
                recent_movie_length: 最新の動画の長さ
                updated_at: 更新日時
        '''
        self.decode()
        conn = sqlite3.connect(self.FILE_PATH)
        # userの状態チェック
        status = self._check_user_status(conn, author_id)
        if status == None:
            return 'あなたのデータがありません。`/live-notification-add`で配信通知を登録してください'
        elif status == self.STATUS_INVALID:
            return 'あなたの通知状態が無効になっています(何も通知されません)\n`/live-notification-toggle`で有効にできます'

        # guild_idの有無でwhere句に条件を付与(対象ギルドのみにフィルタ)
        guild_filter = '' if guild_id is None else f'and notification.notification_guild = {guild_id}'

        # notification(type,live,userを結合)を取得
        conn.row_factory = sqlite3.Row
        with conn:
            cur = conn.cursor()
            select_notification_sql = f'''
                            select notification.id as "id"
                                , type.name as "name"
                                , live.title as "title"
                                , live.channel_id as "channel_id"
                                , live.recent_id as "recent_id"
                                , live.recent_movie_length as "recent_movie_length"
                                , live.updated_at as "updated_at"
                                , notification.notification_channel as "notification_channel"
                                from notification
                                inner join type on notification.type_id = type.id
                                inner join user on notification.user_id = user.id
                                inner join live on notification.live_id = live.id
                                where user.discord_user_id = ?
                                {guild_filter}
                                order by notification.id, live.id
                            '''
            param = (author_id,)
            LOG.debug(select_notification_sql)
            cur.execute(select_notification_sql, param)
            notification_rows = cur.fetchmany(1000)
            result_dict_list = []
            for notification_row in notification_rows:
                channel = f'''<#{notification_row['notification_channel']}>''' if notification_row['notification_channel'] is not None else 'DM'
                dt_updated_jst = datetime.datetime.fromisoformat(notification_row['updated_at'])
                dt_jst_text = dt_updated_jst.strftime(self.DATETIME_FORMAT)
                result_dict = {'notification_id': notification_row['id']
                                , 'type': notification_row['name']
                                , 'title': notification_row['title']
                                , 'channel_id': notification_row['channel_id']
                                , 'channel': channel
                                , 'recent_id': notification_row['recent_id']
                                , 'recent_movie_length': notification_row['recent_movie_length']
                                , 'updated_at': dt_jst_text}
                result_dict_list.append(result_dict)
        self.read()
        self.encode()
        LOG.debug(result_dict_list)
        if len(result_dict_list) == 0:
            message = 'あなたのデータがありません。`/live-notification-add`で配信通知を登録してください'
            LOG.debug(message)
            return message
        return result_dict_list

    async def toggle_user_status(self, author_id:int):
        '''
        userのステータスをトグルします(INVALID⇔VALID)

        Parameters
        ----------
        author_id: int
            discordのuser_id

        Returns
        ----------
        message: str
            変更されたuserのステータスについてのメッセージ
        '''
        self.decode()
        conn = sqlite3.connect(self.FILE_PATH)
        now = datetime.datetime.now(self.JST)
        # userの状態チェック
        status = self._check_user_status(conn, author_id)
        update_sql = 'UPDATE user SET status = ?, updated_at = ? WHERE discord_user_id = ?'
        message = 'あなたのデータがありません。`/live-notification-add`で配信通知を登録してください'
        if status == None:
            return message
        with conn:
            cur = conn.cursor()
            if status == self.STATUS_INVALID:
                param = (self.STATUS_VALID, now, author_id)
                cur.execute(update_sql, param)
                message = 'あなたの通知状態を有効にしました\n`/live-notification-toggle`で無効にできます'
            else:
                param = (self.STATUS_INVALID, now, author_id)
                cur.execute(update_sql, param)
                message = 'あなたの通知状態を無効にしました\n`/live-notification-toggle`で有効にできます'
        conn.commit()
        self.read()
        self.encode()
        # Herokuの時のみ、チャンネルにファイルを添付する
        try:
            await self.set_discord_attachment_file()
        except discord.errors.Forbidden:
            message = f'＊＊＊{self.saved_dm_guild}へのチャンネル作成に失敗しました＊＊＊'
            LOG.error(message)
            return message
        return message

    async def delete_live_notification(self, author_id:int, channel_id:str, notification_channel_id:int=None):
        '''
        配信通知を削除(notification_channel_idがない場合はwhere句から削除。0以下の場合はDM扱いでwhere句追加)


        Parameters
        ----------
        author_id: int
            discordのuser_id
        channel_id: str
            channel_id(YouTubeのchannel_idやニコニコ動画のコミュニティID)
        notification_channel_id: int
            通知先のchannel_id(DMの場合None)

        Returns
        ----------
        message: str
            削除した配信通知についてのメッセージ
        '''
        self.decode()
        conn = sqlite3.connect(self.FILE_PATH)
        user_id = self.get_user(conn, author_id)

        # YouTube @xxxxの変換、その後、チャンネル確認
        match_object = re.search(r'https://www.youtube.com/@(.+)$', channel_id)
        if match_object is not None and len(match_object.groups()) >= 1:
            LOG.debug(f'変換前->channel_id: {channel_id}')
            async with aiohttp.ClientSession() as session:
                headers={"accept-language": "ja-JP"}
                async with session.get(match_object.group(0), headers=headers) as r:
                    if r.status == 200:
                        html = await r.text()
                        match_object2 = re.search(r'"channelUrl":"(https://www.youtube.com/channel/.+?)"', html)
                        if match_object2 is not None and len(match_object2.groups()) >= 1:
                            channel_id = match_object2.group(1)
                            LOG.debug(f'変換後->channel_id: {channel_id}')
        # URLから変換
        match_object_youtube = re.search(r'https://www.youtube.com/channel/(.+)$', channel_id)
        match_object_nicovideo = re.search(r'https://com.nicovideo.jp/community/(.+)$', channel_id)
        match_object_twicas = re.search(r'https://twitcasting.tv/(.+?)((?=/)|$)', channel_id)
        if match_object_youtube is not None and len(match_object_youtube.groups()) >= 1:
            channel_id = match_object_youtube.group(1)
        elif match_object_nicovideo is not None and len(match_object_nicovideo.groups()) >= 1:
            channel_id = match_object_nicovideo.group(1)
        elif match_object_twicas is not None and len(match_object_twicas.groups()) >= 1:
            channel_id = match_object_twicas.group(1)
        live_id,type_id = self.get_channel_id(conn, channel_id)
        if live_id is None:
            return f'{channel_id}は配信通知に存在しません(正しいチャンネルIDを指定ください)'
        with conn:
            cur = conn.cursor()
            where_notification_channel_id,discord_channel = '',''
            delete_param = (user_id, live_id)
            if notification_channel_id is not None:
                if notification_channel_id > 0:
                    where_notification_channel_id = 'and notification_channel = ?'
                    delete_param = (user_id, live_id, notification_channel_id)
                    discord_channel = f'通知先: <#{notification_channel_id}> の'
                else:
                    where_notification_channel_id = 'and notification_channel is null'
                    discord_channel = '通知先: **DM**の'
            delete_sql = f'DELETE FROM notification WHERE user_id = ? and live_id = ? {where_notification_channel_id}'
            cur.execute(delete_sql, delete_param)
            live_title,type_name = self.get_channel_name(conn, channel_id)
        conn.commit()
        self.read()
        self.encode()
        # Herokuの時のみ、チャンネルにファイルを添付する
        try:
            await self.set_discord_attachment_file()
        except discord.errors.Forbidden:
            message = f'＊＊＊{self.saved_dm_guild}へのチャンネル作成に失敗しました＊＊＊'
            LOG.error(message)
            return message
        return f'配信通知({channel_id}(user_id:{user_id}, live_id:{live_id}))を削除しました\n＊{discord_channel}{live_title}({type_name})のこと\n　なお削除対象がなくても表示されるので、正確な情報は`/live-notification_list`で確認してください'

    async def set_filterword(self, author_id:int, filterword:str, is_long_description:bool):
        '''
        フィルターワードを設定

        Parameters
        ----------
        author_id: int
            discordのuser_id
        filterword: str
            フィルターワード
        is_long_description: bool
            説明短くするか

        Returns
        ----------
        なし
        '''
        self.decode()
        conn = sqlite3.connect(self.FILE_PATH)
        now = datetime.datetime.now(self.JST)
        # 空文字が来た場合、現在のフィルターワードを返却する
        db_filterword, db_log_description = self.get_user_filterword(conn, author_id)
        long_description_message = '長い' if db_log_description == 'True' else '短い(30文字)'
        if filterword == '' and is_long_description is None:
            return f'現在のfilterwordは「{db_filterword}」、説明文(長さ)は{long_description_message}です'

        # メッセージの投稿者からuser.idを取得
        user_id = self.get_user(conn, author_id)

        # 説明文の短縮要否を設定
        if is_long_description is not None:
            long_description_message = '長い' if is_long_description else '短い(30文字)'
            with conn:
                cur = conn.cursor()
                update_desc_sql = f'UPDATE user SET long_description = ?, updated_at = ? WHERE id = ?'
                update_desc_param = (str(is_long_description), now, user_id)
                cur.execute(update_desc_sql, update_desc_param)
                conn.commit()

    # フィルターワードがあれば、それを設定。説明文の設定も同様に指定
        if filterword != '':
            with conn:
                cur = conn.cursor()
                update_param = (filterword, now, user_id)
                update_sql = f'UPDATE user SET filter_words = ?, updated_at = ? WHERE id = ?'
                cur.execute(update_sql, update_param)
                conn.commit()
                filterword = f'に「{filterword}」を設定しました'
        else:
            # filterwordが空文字の場合、DBの文字列を表示
            filterword = f'は現在「{db_filterword}」が設定されています'
        self.read()
        self.encode()
        # Herokuの時のみ、チャンネルにファイルを添付する
        try:
            await self.set_discord_attachment_file()
        except discord.errors.Forbidden:
            message = f'＊＊＊{self.saved_dm_guild}へのチャンネル作成に失敗しました＊＊＊'
            LOG.error(message)
            return message
        return f'filterword{filterword}(説明文(長さ)は{long_description_message} / user_id:{user_id})'

    async def logic_delete_user(self, user_id:int):
        '''
        userのステータスを無効にし、論理削除も行います(status:INVALID, system_status:DELETE)

        Parameters
        ----------
        user_id: int
            live-notification用user_id

        Returns
        ----------
        message: str
            変更されたuserのステータスについてのメッセージ
        '''
        self.decode()
        conn = sqlite3.connect(self.FILE_PATH)
        now = datetime.datetime.now(self.JST)
        # userの状態チェック
        status = self._check_user_status_by_user_id(conn, user_id)
        update_sql = 'UPDATE user SET status = ?, system_status = ?, updated_at = ? WHERE id = ?'
        message = 'データがありません'
        if status == None:
            return message
        with conn:
            cur = conn.cursor()
            if status is not None:
                param = (self.STATUS_INVALID, self.SYSTEM_STATUS_DELETE, now, user_id)
                cur.execute(update_sql, param)
                message = 'ユーザーを削除しました'
                LOG.info(f'''<重要>userのステータス無効&論理削除 -> {str(user_id)}''')
        conn.commit()
        self.read()
        self.encode()
        # Herokuの時のみ、チャンネルにファイルを添付する
        try:
            await self.set_discord_attachment_file()
        except discord.errors.Forbidden:
            message = f'＊＊＊{self.saved_dm_guild}へのチャンネル作成に失敗しました＊＊＊'
            LOG.error(message)
            return message
        return message

    def _check_user_status(self, conn, author_id:int):
        '''
        userの状態を返却

        Parameters
        ----------
        conn: sqlite3.Connection
            SQLite データベースコネクション
        author_id: int
            discordのuser_id

        Returns
        ----------
        status: str
            live notificationのstatus(存在しない場合はNone)
        '''
        select_user_sql = 'SELECT status FROM user WHERE discord_user_id = ?'
        with conn:
            cur = conn.cursor()
            cur.execute(select_user_sql, (author_id,))
            fetch = cur.fetchone()
            status = fetch[0] if fetch is not None else None
            if status is None:
                return None
            else:
                return status

    def _check_user_status_by_user_id(self, conn, user_id:int):
        '''
        userの状態を返却

        Parameters
        ----------
        conn: sqlite3.Connection
            SQLite データベースコネクション
        user_id: int
            live-notification用user_id

        Returns
        ----------
        status: str
            live notificationのstatus(存在しない場合はNone)
        '''
        select_user_sql = 'SELECT status FROM user WHERE id = ?'
        with conn:
            cur = conn.cursor()
            cur.execute(select_user_sql, (user_id,))
            fetch = cur.fetchone()
            status = fetch[0] if fetch is not None else None
            if status is None:
                return None
            else:
                return status

    def _str_truncate(self, string:str, length:int, syoryaku:str='...'):
        '''
        文字列を切り詰める

        Parameters
        ----------
        string: str
            対象の文字列
        length: int
            切り詰め後の長さ
        syoryaku: str
            省略したとき表示する文字

        Returns
        ----------
        string: str
            切り詰められた文字列
        '''
        if string is None:
            return '(なし)'
        else:
            return string[:length] + (syoryaku if string[length:] else '')

    async def check_youtube_by_video_id(self, video_id:str):
        '''
        YouTubeのvideo_idからchannel_idを取り出す

        Parameters
        ----------
        video_id: str
            YouTubeのvideo_id(またはYouTubeの動画URL)

        Returns
        ----------
        channel_id: str
            YouTubeのchannel_id(UCなんとか)
        author: str
            YouTubeのauthor
        video_id: str
            YouTubeのvideo_id
        '''
        youtube_url,channel_id = None,None
        author = ''
        if video_id.startswith(self.YOUTUBE_VIDEO_URL):
            youtube_url = video_id
            video_id = video_id.replace(self.YOUTUBE_VIDEO_URL, '')
        else:
            youtube_url = self.YOUTUBE_VIDEO_URL + video_id

        # 実際にアクセスしてみて、動画情報を取得
        async with aiohttp.ClientSession() as session:
            headers={"accept-language": "ja-JP"}
            async with session.get(youtube_url, headers=headers) as r:
                if r.status == 200:
                    html = await r.text()
                    # title
                    match_object = re.search(r'"title":{"simpleText":"(.+?)"}', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        title = match_object.group(1)
                        LOG.debug(f'title:{title}')
                    # author
                    match_object = re.search(r'"viewCount":"\d+?","author":"(.+?)",', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        author = match_object.group(1)
                        LOG.debug(f'author:{author}')
                    # channel_id
                    match_object = re.search(r'"channelId":"(.+?)",', html)
                    if match_object is not None and len(match_object.groups()) >= 1:
                        channel_id = match_object.group(1)
                        LOG.debug(f'channel_id:{channel_id}')
        if channel_id is not None:
            return channel_id,author,video_id
        else:
            return None,None,None

    def get_by_result_dict(self, type_name:str, result_dict:dict, channel_title:str='', message_suffix:str='の動画が追加されました！'):
        video_title = result_dict.get('title')
        watch_url = result_dict.get('watch_url')
        if result_dict.get('live_streaming_start_flg') is None:
            message = f'''{type_name}で{channel_title}さん{message_suffix}\n動画名: {video_title}'''
        elif result_dict.get('live_streaming_start_flg') is True:
            # YouTubeで予約配信していたものが配信開始された場合を想定
            message = f'''{type_name}で{channel_title}さんの配信が開始されました(おそらく)！\n動画名: {video_title}'''
        elif result_dict.get('live_streaming_start_flg') is False:
            # YouTubeで予約配信が追加された場合を想定
            message = f'''{type_name}で{channel_title}さんの予約配信が追加されました！\n動画名: {video_title}'''
            if result_dict.get('live_streaming_start_datetime') is not None:
                message += f'''\n配信予定日時は**{result_dict.get('live_streaming_start_datetime')}**です！'''
        return video_title,watch_url,message

    def make_description(self, description_text: str, title: str, is_long: bool=False, length: int=setting.DESCRIPTION_LENGTH):
        '''
        説明文を生成する(短くする)

        Parameters
        ----------
        description_text: str
            説明文
        title: str
            タイトル
        is_long: bool
            長くするかどうか
        length: int
            切り詰め後の長さ

        Returns
        ----------
        string: str
            説明文
        '''
        if not is_long:
            return f'''{self._str_truncate(description_text, length)} by {title}'''
        return f'''{description_text} by {title}'''