# file name is keep_alive.py
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
@app.route('/test', methods=['GET', 'POST'])
def test():
    try:
        print(request)
        data = ''
        if request.method == 'GET':
            request_hub_mode = request.args.get('hub.mode', '')
            if request_hub_mode == 'unsubscribe' \
            or request_hub_mode == 'subscribe':
                data = request.args.get('hub.challenge', '')
                print(data)
            return data
        elif request.method == 'POST':
            if hasattr(request, 'form'):
                print(request.form)
                data = request.form.get('hub.challenge', '')
                print(data)
            binary = request.get_data()
            text = binary.decode(encoding='utf-8')
            # print(text)
            try :
                root = ET.fromstring(text)
                # for element in root.iter():
                for entry in root.iter('{'+XML_NAMESPACE['atom']+'}entry'):
                    if entry is None:
                        continue
                    print('********************* element *********************')
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
                        print(f'thumbnail:{thumbnail}')
                        print(f'description:{description}')
                    print(f'videoId:{videoId} from channelId:{channelId}')
                    print(f'title:{title} / link:{link}')
                    print(f'published:{published} / updated:{updated}')
                    live_streaming_start_datetime = ''
                    headers={"accept-language": "ja-JP"}
                    r = requests.get(link, headers=headers)
                    if r.status_code == 200:
                        html = r.text
                        # live_streaming_start_datetime
                        match_object = re.search(r'"liveStreamOfflineSlateRenderer":{"scheduledStartTime":"(\d+)"', html)
                        if match_object is not None and len(match_object.groups()) >= 1:
                            liveStartTime = int(match_object.group(1))
                            dt = datetime.datetime.fromtimestamp(liveStartTime)
                            live_streaming_start_datetime = dt.strftime('%Y/%m/%d(%a) %H:%M:%S')
                            print(f'live_streaming_start_datetime:{live_streaming_start_datetime}')
                        # thumbnail
                        match_object = re.search(r'"thumbnail":{"thumbnails":\[{"url":"(.+?)",', html)
                        if match_object is not None and len(match_object.groups()) >= 1:
                            thumbnail = match_object.group(1)
                            print(f'thumbnail:{thumbnail}')
                        match_object = re.search(r'"thumbnail":{"thumbnails":\[.+{"url":"(.+?)","width":1920,"height":1080}\]', html)
                        if match_object is not None and len(match_object.groups()) >= 1:
                            thumbnail = match_object.group(1)
                            print(f'thumbnail:{thumbnail}')
                        # description
                        match_object = re.search(r'"shortDescription":"(.+?)",', html)
                        if match_object is not None and len(match_object.groups()) >= 1:
                            description = match_object.group(1)
                            print(f'description:{description}')

                    print('********************* end *********************')
                    # 更新処理、通知
                    # 添付
            except ParseError as e:
                print(str(e))
            return data
        else:
            print('error')
            return abort(400)
    except Exception as e:
        print(str(e))
        return str(e)
def run():
    app.run(host='0.0.0.0', port=80)
def keep_alive():
    server = Thread(target=run)
    server.start()
if __name__ == '__main__':
    keep_alive()