
import http.server
import socketserver
# import json
import datetime
from urllib.parse import parse_qs, urlparse

class MyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        print('path = {}'.format(self.path))
        parsed_path = urlparse(self.path)
        print('parsed: path = {}, query = {}'.format(parsed_path.path, parse_qs(parsed_path.query)))
        print('headers\r\n-----\r\n{}-----'.format(self.headers))

        query = parse_qs(parsed_path.query)
        challenge = ''
        if query.get('hub.challenge'):
            challenge = query.get('hub.challenge')[0]
            print(challenge)

        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(bytes(challenge, 'utf-8'))

    def do_POST(self):
        print('path = {}'.format(self.path))
        parsed_path = urlparse(self.path)
        print('parsed: path = {}, query = {}'.format(parsed_path.path, parse_qs(parsed_path.query)))
        print('headers\r\n-----\r\n{}-----'.format(self.headers))
        content_length = int(self.headers['content-length'])

        #Body書き出し
        now = datetime.datetime.now()
        file_name = 'wbhk_out_' + now.strftime('%Y%m%d_%H%M%S') + '.json'
        req_body = self.rfile.read(content_length).decode("utf-8")
        with open(file_name, 'w') as f:
            f.write(req_body)
        print(req_body)

        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'Hello from do_POST')
        keys = []
        values = []
        req_params = req_body.split('&')
        for param in req_params:
            key,value=param.split('=')
            keys.append(key)
            values.append(value)
        d = dict(zip(keys, values))
        challenge = ''
        if d.get('hub.challenge'):
            challenge = d.get('hub.challenge')
            print(challenge)

        self.send_response(200, challenge)
        self.end_headers()

with socketserver.TCPServer(("", 80), MyHandler) as httpd:
    httpd.serve_forever()