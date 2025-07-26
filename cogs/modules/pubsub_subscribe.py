import aiohttp
from logging import getLogger
from . import setting

LOG = getLogger('live-notification-bot')
YOUTUBE_FEEDS_XML_URL = 'https://www.youtube.com/xml/feeds/videos.xml?channel_id='
YOUTUBE_FEEDS_URL = 'https://www.youtube.com/feeds/videos.xml?channel_id='
URL = 'https://pubsubhubbub.appspot.com/subscribe'

async def subscribe_by_channel_id(channel_id:str):
    await subscribe(YOUTUBE_FEEDS_XML_URL + channel_id)

async def subscribe(topic_url:str):
    # xmlがついてないURLやそれっぽいURLではない場合の修正(てきとうなので期待しないで)
    if topic_url and topic_url.startswith(YOUTUBE_FEEDS_URL):
        topic_url = topic_url.replace(YOUTUBE_FEEDS_URL, YOUTUBE_FEEDS_XML_URL)
    elif topic_url and not topic_url.startswith(YOUTUBE_FEEDS_XML_URL):
        topic_url = YOUTUBE_FEEDS_XML_URL + topic_url

    async with aiohttp.ClientSession() as session:
        # LOG.info('CALLBACK_URL:'+ setting.CALLBACK_URL)
        params = {
                    'hub.callback': setting.CALLBACK_URL ,
                    'hub.topic': topic_url,
                    'hub.verify': 'async',
                    'hub.mode': 'unsubscribe',
                    'hub.lease_numbers': '604800', # 7日間
        }
        async with session.post(URL, params=params) as resp:
            text = await resp.text()
            text = '<None>' if text is None or text == '' else text
            LOG.info(f'unsubscribe-> url:{topic_url} status:{resp.status} text:{text}')

        params = {
                    'hub.callback': setting.CALLBACK_URL ,
                    'hub.topic': topic_url,
                    'hub.verify': 'async',
                    'hub.mode': 'subscribe',
        }
        async with session.post(URL, params=params) as resp:
            text = await resp.text()
            text = '<None>' if text is None or text == '' else text
            LOG.info(f'subscribe-> url:{topic_url} status:{resp.status} text:{text}')