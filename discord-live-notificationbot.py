from cogs.modules import setting
from discord.ext import commands
from logging import basicConfig, getLogger, StreamHandler, FileHandler, Formatter, NOTSET
from datetime import timedelta, timezone
import discord, os, datetime, asyncio

# 時間
JST = timezone(timedelta(hours=9), 'JST')
now = datetime.datetime.now(JST)

# ストリームハンドラの設定
stream_handler = StreamHandler()
stream_handler.setLevel(setting.LOG_LEVEL)
stream_handler.setFormatter(Formatter("%(asctime)s@ %(name)s [%(levelname)s] %(funcName)s: %(message)s"))

# 保存先の有無チェック
if not os.path.isdir('./Log'):
    os.makedirs('./Log', exist_ok=True)

# ファイルハンドラの設定
file_handler = FileHandler(
    f"./Log/log-{now:%Y%m%d_%H%M%S}.log"
)
file_handler.setLevel(setting.LOG_LEVEL)
file_handler.setFormatter(
    Formatter("%(asctime)s@ %(name)s [%(levelname)s] %(funcName)s: %(message)s")
)

# ルートロガーの設定
basicConfig(level=NOTSET, handlers=[stream_handler, file_handler])

LOG = getLogger('live-notification-bot')

# 読み込むCogの名前を格納しておく。
INITIAL_EXTENSIONS = [
    'cogs.livenotificationcog'
    , 'cogs.webservercog'
]

class DiscordLiveNotificationBot(commands.Bot):
    # MyBotのコンストラクタ。
    def __init__(self, command_prefix, intents, application_id):
        # スーパークラスのコンストラクタに値を渡して実行。
        super().__init__(command_prefix, case_insensitive=True, intents=intents, help_command=None, application_id=application_id) # application_idが必要


    async def setup_hook(self):
        # INITIAL_EXTENSIONに格納されている名前からCogを読み込む。
        LOG.info('cogを読むぞ！')
        for cog in INITIAL_EXTENSIONS:
            await self.load_extension(cog) # awaitが必要

        # テスト中以外は環境変数で設定しないことを推奨(環境変数があれば、ギルドコマンドとして即時発行される)
        if setting.ENABLE_SLASH_COMMAND_GUILD_ID is not None and len(setting.ENABLE_SLASH_COMMAND_GUILD_ID) > 0:
            LOG.info(setting.ENABLE_SLASH_COMMAND_GUILD_ID)
            for guild in setting.ENABLE_SLASH_COMMAND_GUILD_ID:
                LOG.info(guild)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
        else:
            await self.tree.sync() # グローバルコマンドとして発行(使用できるまで、最大1時間程度かかる)

    async def on_ready(self):
        LOG.info('We have logged in as {0.user}'.format(self))
        LOG.debug(f"### guilds ### \n{self.guilds}")

        # #### for delete slash command #####
        # guilds = [] if setting.ENABLE_SLASH_COMMAND_GUILD_ID_LIST is None else list(
        #     map(int, setting.ENABLE_SLASH_COMMAND_GUILD_ID_LIST.split(';')))
        # for guild in guilds:
        #     await manage_commands.remove_all_commands_in(self.user.id, setting.DISCORD_TOKEN, guild)
        #     LOG.info('remove all guild command for {0}.'.format(guild))

async def main():
    # Botの起動
    async with bot:
        LOG.info(setting.APPLICATION_ID)
        LOG.info(setting.CALLBACK_URL)
        LOG.info(setting.PORT)
        await bot.start(setting.DISCORD_TOKEN)
        LOG.info('We have logged in as {0}'.format(bot.user))

# discord-live-notificationbotのインスタンス化、および、起動処理
if __name__ == '__main__':
    intents = discord.Intents.default()
    intents.members = False
    intents.presences = False
    intents.message_content = False

    bot = DiscordLiveNotificationBot(
        command_prefix='/'
        , intents=intents
        ,application_id=setting.APPLICATION_ID)

    # start a server
    asyncio.run(main())