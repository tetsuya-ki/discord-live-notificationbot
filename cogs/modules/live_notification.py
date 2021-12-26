from sqlite3 import dbapi2
import aiohttp
import xml.etree.ElementTree as ET
from datetime import timedelta, timezone
from discord.ext import commands
from os.path import join, dirname
from logging import getLogger
from pytube import YouTube
from .aes_angou import Aes_angou
from . import setting

import datetime, discord, sqlite3, os, pytube
LOG = getLogger('live-notification-bot')

class LiveNotification:
    DATABASE = 'live.db'
    FILE_PATH = join(dirname(__file__), 'files' + os.sep + DATABASE)
    JST = timezone(timedelta(hours=+9), 'JST')
    DATETIME_FORMAT = '%Y/%m/%d(%a) %H:%M:%S'
    LIVE_CONTROL_CHANNEL = 'live_control_channel'
    YOUTUBE = 'YouTube'
    NICOLIVE = 'ニコ生'
    YOUTUBE_URL = 'https://www.youtube.com/feeds/videos.xml?channel_id='
    TYPE_YOUTUBE = 1
    TYPE_NICOLIVE = 2
    NOTIFICATION_MAX = 5
    STATUS_VALID = 'VALID'
    STATUS_INVALID = 'INVALID'
    DESCRIPTION_LENGTH = 2000

    def __init__(self, bot):
        self.bot = bot
        self.live_rows = None  # liveの一覧
        self.notification_rows = None  # notificationの結果
        self.aes = Aes_angou(setting.DISCORD_TOKEN)
        self.saved_dm_guild = int(setting.GUILD_ID_FOR_ATTACHMENTS) if str(setting.GUILD_ID_FOR_ATTACHMENTS).isdecimal() else None

    async def prepare(self):
        '''
        sqlite3のdbを準備する
        '''
        # Herokuの時のみ、チャンネルからファイルを取得する
        await self.get_discord_attachment_file()

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
                sql_list = [create_table_user_sql, create_table_type_sql, create_table_live_sql, create_table_notification_sql]
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

        self.read()
        self.encode()
        LOG.info('準備完了')

    async def get_discord_attachment_file(self):
        # HerokuかRepl.itの時のみ実施
        if setting.IS_HEROKU or setting.IS_REPLIT:
            # 環境変数によって、添付ファイルのファイル名を変更する
            file_name = self.aes.ENC_FILE if setting.KEEP_DECRYPTED_FILE else self.DATABASE
            LOG.debug('Heroku mode.start get_discord_attachment_file.')
            # ファイルをチェックし、存在しなければ最初と見做す
            file_path_first_time = join(dirname(__file__), 'files' + os.sep + 'first_time')
            if (setting.IS_HEROKU and not os.path.exists(file_path_first_time)) or setting.IS_REPLIT:
                if setting.IS_HEROKU:
                    with open(file_path_first_time, 'w') as f:
                        now = datetime.datetime.now(self.JST)
                        f.write(now.strftime('%Y/%m/%d(%a) %H:%M:%S'))
                        LOG.debug(f'{file_path_first_time}が存在しないので、作成を試みます')
                attachment_file_date = None

                # 
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
                                        LOG.info(f'channel_file_save:{guild.name} / datetime:{attachment_file_date.strftime("%Y/%m/%d(%a) %H:%M:%S")}')
                                        break
                    else:
                        LOG.warning(f'{guild}: に所定のチャンネルがありません')
            else:
                LOG.debug(f'{file_path_first_time}が存在します')

            LOG.debug('get_discord_attachment_file is over!')

    async def set_discord_attachment_file(self):
        # HerokuかRepl.itの時のみ実施
        if setting.IS_HEROKU or setting.IS_REPLIT:
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
        '''
        if os.path.exists(self.aes.DEC_FILE_PATH):
            self.aes.encode()
            if setting.KEEP_DECRYPTED_FILE:
                os.remove(self.aes.DEC_FILE_PATH)

    def read(self):
        # readはdecodeしない
        conn = sqlite3.connect(self.FILE_PATH)
        conn.row_factory = sqlite3.Row
        with conn:
            cur = conn.cursor()
            select_notification_sql = '''
                            select * from notification
                                inner join type on notification.type_id = type.id
                                inner join user on notification.user_id = user.id
                                order by notification.id, user.id
                            '''
            LOG.debug(select_notification_sql)
            cur.execute(select_notification_sql)
            self.notification_rows = cur.fetchmany(1000)

            select_live_sql = f'select * from live order by live.id'
            LOG.debug(select_live_sql)
            cur.execute(select_live_sql)
            self.live_rows = cur.fetchmany(1000)
            LOG.debug(self.live_rows)

            LOG.info('＊＊＊＊＊＊読み込みが完了しました＊＊＊＊＊＊')

    def get_user(self, conn, author_id):
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

    def get_channel_id(self, conn, channel_id:str):
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

    async def set_youtube(self, conn, channel_id:str):
        '''
        YouTubeをセットします
        '''
        # xmlを確認
        async with aiohttp.ClientSession() as session:
            async with session.get(self.YOUTUBE_URL+channel_id) as r:
                if r.status == 200:
                    response = ET.fromstring(await r.text())
                    title = response[3].text if len(response) > 3 and response[3] is not None else None
                    recent_id = response[7][1].text if len(response) > 8 and response[7] is not None else None
                    youtube_recent_url = response[7][4].attrib['href'] if response[7][4] is not None else ''
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
            live_param = (1, None, channel_id, recent_id, youtube_recent_length, title, now, now)
            cur.execute(create_live_sql, live_param)
            # get id
            get_id_sql = 'SELECT id FROM live WHERE rowid = last_insert_rowid()'
            cur.execute(get_id_sql)
            live_id = cur.fetchone()[0]
            LOG.info(f'liveにid:{live_id}({channel_id})を追加しました')
            conn.commit()
            return live_id,1

    async def get_youtube(self, channel_id:str, recent_id:str, recent_movie_length:int, recent_updated_at:str):
        '''
        YouTubeを確認します(recent_idと比較し、現在最新のrecent_idに更新し、存在しないものを通知対象として返却します)
        '''
        # xmlを確認
        async with aiohttp.ClientSession() as session:
            async with session.get(self.YOUTUBE_URL+channel_id) as r:
                if r.status == 200:
                    response = ET.fromstring(await r.text())
                    youtube_recent_id = response[7][1].text if len(response) > 8 and response[8] is not None else None
                    youtube_recent_url = response[7][4].attrib['href'] if response[7][4] is not None else ''

                    # 謎の削除かチェック
                    recent_updated_at = datetime.datetime.strptime(recent_updated_at, '%Y-%m-%d %H:%M:%S.%f%z')
                    started_at_text = response[7][6].text if len(response) > 7 and response[7][6] is not None else ''
                    if started_at_text != '':
                        dt_started_utc = datetime.datetime.fromisoformat(started_at_text)
                        dt_jst = dt_started_utc.astimezone(self.JST)
                        # DBの最近の更新日時の方がxmlの最新よりも新しい場合は、削除か何かと判断し、対応しない(配信前が登録されていた場合は先に進む)
                        if recent_updated_at >= dt_jst and recent_movie_length != 0:
                            return

                    # 動画が追加されたか、前回確認時に動画の長さが0だった場合のみ、pytubeでYouTube Objectを作成し、動画の長さを取得(長さが0なら未配信とみなす)
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
                    if youtube.length == 0 and youtube_recent_length != 0:
                        live_streaming_start_flg = True
                    # DBの最新動画の長さが0のまま変わってない場合は、対応なし
                    if recent_id == youtube_recent_id and youtube_recent_length == 0:
                        return
                    # 新しく予約配信が追加されたパターン
                    elif youtube_recent_length == 0:
                        live_streaming_start_flg = False

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
                                    , 'thumbnail': thumbnail}
                        response_list.append(entry_dict)

                    # 最初の1つだけライブ配信開始フラグを入れる
                    if len(response_list) > 0:
                        first_dict = response_list.pop(0)
                        first_dict['live_streaming_start_flg'] = live_streaming_start_flg
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

    async def set_nicolive(self, conn, channel_id:str):
        '''
        ニコ生をセットします
        '''
        # json
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
            live_param = (2, int(nico_user_id), channel_id, nico_recent_id, nico_nickname, now, now)
            cur.execute(create_live_sql, live_param)
            # get id
            get_id_sql = 'SELECT id FROM live WHERE rowid = last_insert_rowid()'
            cur.execute(get_id_sql)
            live_id = cur.fetchone()[0]
            LOG.info(f'liveにid:{id}({channel_id})を追加しました')
            conn.commit()
            return live_id,2

    async def get_nicolive(self, channel_id:str, recent_id:str):
        '''
        ニコ生を確認します(放送中の場合、recent_idに登録し、通知対象を返却します)
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
                            ,'started_at': dt_jst_text}]

    def set_notification(self, conn, type_id:int, user_id:int, live_id:int, notification_guild:int, notification_channel:int, mention:str, channel_id:str):
        '''
        通知をセットします(すでに登録された通知の場合、登録しません)
        '''
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
        '''
        self.decode()
        conn = sqlite3.connect(self.FILE_PATH)
        with conn:
            user_id = self.get_user(conn, author_id)
            live_id,type_id = self.get_channel_id(conn, channel_id)
            if live_id is None:
                live_id,type_id = await self.set_youtube(conn, channel_id)
                if live_id is None:
                    live_id,type_id = await self.set_nicolive(conn, channel_id)
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
        '''
        self.decode()
        self.read()
        self.encode()

    def list_live_notification(self, author_id:int, guild_id:str=None):
        '''
        登録した配信通知を表示します
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
        '''
        self.decode()
        conn = sqlite3.connect(self.FILE_PATH)
        user_id = self.get_user(conn, author_id)
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
        return f'配信通知({channel_id}(user_id:{user_id}, live_id:{live_id}))を削除しました\n＊{discord_channel}{live_title}({type_name})のこと。なお削除対象がなくても表示されるので、正確な情報は`/live-notification_list`で確認してください'

    def _check_user_status(self, conn, author_id:int):
        '''
        userの状態を返却
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

    def _str_truncate(self, string, length, syoryaku='...'):
        '''
        文字列を切り詰める

        string: 対象の文字列
        length: 切り詰め後の長さ
        syoryaku: 省略したとき表示する文字
        '''
        if string is None:
            return '(なし)'
        else:
            return string[:length] + (syoryaku if string[length:] else '')