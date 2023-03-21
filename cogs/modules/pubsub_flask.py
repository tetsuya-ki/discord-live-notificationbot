import re
import logging
import defusedxml.ElementTree as ET
import requests
import datetime
from flask import Flask, request, abort
from threading import Thread
from dateutil.parser import parse
from dateutil.tz import gettz
from xml.etree.ElementTree import ParseError
from logging import getLogger

LOG = getLogger('live-notification-bot')
XML_NAMESPACE = {
    'atom': 'http://www.w3.org/2005/Atom',
    'yt': 'http://www.youtube.com/xml/schemas/2015',
    'media': 'http://search.yahoo.com/mrss/',
}

# ロガーの取得
werkzeug_logger = logging.getLogger('werkzeug')
# レベルの変更
werkzeug_logger.setLevel(logging.ERROR)

app = Flask('')
@app.route('/handler', methods=['GET', 'POST'])
def handler():
    try:
        LOG.debug(request)
        data = ''
        if request.method == 'GET':
            request_hub_mode = request.args.get('hub.mode', '')
            if request_hub_mode == 'unsubscribe' \
            or request_hub_mode == 'subscribe':
                data = request.args.get('hub.challenge', '')
                LOG.debug(data)
            return data
        elif request.method == 'POST':
            if hasattr(request, 'form'):
                data = request.form.get('hub.challenge', '')
                LOG.debug(data)
            binary = request.get_data()
            text = binary.decode(encoding='utf-8')
            LOG.debug(text)
            try :
                root = ET.fromstring(text)
                for entry in root.iter('{'+XML_NAMESPACE['atom']+'}entry'):
                    if entry is None:
                        continue
                    LOG.debug('********************* element *********************')
                    author = entry.find('atom:author', XML_NAMESPACE)
                    videoId=entry.find('yt:videoId', XML_NAMESPACE).text
                    channelId=entry.find('yt:channelId', XML_NAMESPACE).text
                    title=entry.find('atom:title', XML_NAMESPACE).text
                    link=entry.find('atom:link', XML_NAMESPACE).get('href')
                    authorName=author.find('atom:name', XML_NAMESPACE).text
                    authorUri=author.find('atom:uri', XML_NAMESPACE).text
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
                    LOG.debug(f'videoId:{videoId} from channelId:{channelId}')
                    LOG.debug(f'title:{title} / link:{link}')
                    LOG.debug(f'published:{published} / updated:{updated}')
                    LOG.debug('********************* end *********************')
                    # 更新処理、通知
                    # 添付
            except ParseError as e:
                LOG.error('ParseError:' + str(e))
            return data
        else:
            LOG.debug('error')
            return abort(400)
    except Exception as e:
        LOG.debug(str(e))
        return str(e)
def run():
    app.run(host='0.0.0.0', port=80)
def keep_alive():
    server = Thread(target=run)
    server.start()
if __name__ == '__main__':
    keep_alive()