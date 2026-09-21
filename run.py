"""VenTrax entrypoint - gevent + gevent-websocket (no flask-sock)"""
import os, logging
from gevent import pywsgi
from geventwebsocket.handler import WebSocketHandler
from app import app, init_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    print(f'\nVenTrax -> http://0.0.0.0:{port}\n')
    server = pywsgi.WSGIServer(
        ('0.0.0.0', port), app,
        handler_class=WebSocketHandler,
        log=logging.getLogger('gevent'),
    )
    server.serve_forever()
