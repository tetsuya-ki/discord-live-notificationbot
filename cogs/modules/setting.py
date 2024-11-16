import os,discord
from os.path import join, dirname
from dotenv import load_dotenv
from logging import DEBUG, INFO, WARNING, ERROR

def if_env(string:str):
    '''
    strをTrue／Falseに変換(NoneのときはFalse)
    '''
    if string is None:
        return False
    elif string.upper() == 'TRUE':
        return True
    else:
        return False

def get_log_level(string:str):
    '''
    ログレベルを設定(Noneや無効のときはWARNING)
    '''
    if string is None:
        return WARNING

    upper_str = string.upper()
    if upper_str == 'DEBUG':
        return DEBUG
    elif upper_str == 'INFO':
        return INFO
    elif upper_str == 'ERROR':
        return ERROR
    else:
        return WARNING

def num_env(string:str):
    '''
    strをintに変換(Noneのときは0)
    '''
    if string is None or not string.isdecimal():
        return 0
    else:
        return int(string)

def add_path_env(string:str):
    path = '/handler'
    if not string.endswith(path):
        return string + path
    else:
        return string

def split_guild_env(str):
    guilds = []
    if str is None or str == '':
        pass
    elif not ';' in str:
        guilds.append(discord.Object(str))
    else:
        guilds = list(map(discord.Object, str.split(';')))
    return guilds

# 環境変数をファイルから読み込む
load_dotenv(verbose=True)
dotenv_path = join(dirname(__file__), 'files' + os.sep + '.env')
load_dotenv(dotenv_path)

DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
LOG_LEVEL = get_log_level(os.environ.get('LOG_LEVEL'))
ENABLE_SLASH_COMMAND_GUILD_ID_LIST = os.environ.get('ENABLE_SLASH_COMMAND_GUILD_ID_LIST')
KEEP_DECRYPTED_FILE = not if_env(os.environ.get('KEEP_DECRYPTED_FILE'))
IS_HEROKU = if_env(os.environ.get('IS_HEROKU'))
RESTRICT_ATTACHMENT_FILE = if_env(os.environ.get('RESTRICT_ATTACHMENT_FILE'))
GUILD_ID_FOR_ATTACHMENTS = os.environ.get('GUILD_ID_FOR_ATTACHMENTS')
YOUTUBE_FEEDS_URL = os.environ.get('YOUTUBE_FEEDS_URL')
YOUTUBE_XML_URL = os.environ.get('YOUTUBE_XML_URL')
YOUTUBE_VIDEO_URL = os.environ.get('YOUTUBE_VIDEO_URL')
CALLBACK_URL = add_path_env(os.environ.get('CALLBACK_URL'))
LIVE_NOTIFICATION_V2 = if_env(os.environ.get('LIVE_NOTIFICATION_V2'))
OVERDUE_DATE_NUM = num_env(os.environ.get('OVERDUE_DATE_NUM', '1'))
PORT = num_env(os.environ.get('PORT', '80'))
NG_MAX_COUNT = num_env(os.environ.get('NG_MAX_COUNT', '20'))
DESCRIPTION_LENGTH = num_env(os.environ.get('DESCRIPTION_LENGTH', '150'))
APPLICATION_ID = os.environ.get('APPLICATION_ID2')
ENABLE_SLASH_COMMAND_GUILD_ID = split_guild_env(os.environ.get('ENABLE_SLASH_COMMAND_GUILD_ID'))
EXCLUDE_NICONICO = if_env(os.environ.get('EXCLUDE_NICONICO'))