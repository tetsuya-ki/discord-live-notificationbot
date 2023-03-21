import aiohttp
from logging import getLogger
from . import setting

LOG = getLogger('live-notification-bot')

async def subscribe(topic_url:str):
    # xmlがついてないURLやそれっぽいURLではない場合の修正
    if topic_url and topic_url.startswith(setting.YOUTUBE_FEEDS_URL):
        topic_url = topic_url.replace(setting.YOUTUBE_FEEDS_URL, setting.YOUTUBE_XML_URL)
    elif topic_url and not topic_url.startswith(setting.YOUTUBE_XML_URL):
        topic_url = setting.YOUTUBE_XML_URL + topic_url

    async with aiohttp.ClientSession() as session:
        URL = 'https://pubsubhubbub.appspot.com/subscribe'
        params = {
                    'hub.callback': setting.CALLBACK_URL ,
                    'hub.topic': topic_url,
                    'hub.verify': 'async',
                    'hub.mode': 'subscribe',
        }
        async with session.post(URL, params=params) as resp:
            LOG.info(f'url:{topic_url} status:{resp.status} text:{await resp.text()}')