import aiohttp, asyncio
import xml.etree.ElementTree as ET

async def main():
    async with aiohttp.ClientSession() as session:
        URL = 'https://pubsubhubbub.appspot.com/subscribe'
        params = {
                    'hub.callback': 'https://825f-2400-4051-43c3-f000-e848-ad0-2ae-8b2f.jp.ngrok.io/test',
                    'hub.topic': 'https://www.youtube.com/feeds/videos.xml?channel_id=UCtHhkR8spzOc0E4buQZwfBw',
                    'hub.verify': 'async',
                    'hub.mode': 'subscribe',
        }
        #                     'hub.lease_seconds': '120'
        # https://www.youtube.com/feeds/videos.xml?channel_id=UCmovZ2th3Sqpd00F5RdeigQ
        # https://www.youtube.com/feeds/videos.xml?channel_id=UCD-miitqNY3nyukJ4Fnf4_A
        # https://www.youtube.com/feeds/videos.xml?channel_id=UCtHhkR8spzOc0E4buQZwfBw
        async with session.post(URL, params=params) as resp:
            print(resp.status)
            print(await resp.text())

asyncio.run(main())