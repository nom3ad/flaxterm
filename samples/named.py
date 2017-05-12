#!/usr/bin/env python
import json,logging,sys
from flask_sockets import Sockets
from flask import Flask, render_template, request,send_from_directory,redirect
logging.basicConfig(level=logging.DEBUG,format="%(levelname)s [%(name)s] %(message)s")
# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
app = Flask(__name__)
sockets = Sockets(app)
app.debug = True

from flaxterm import TermSocketHandler, NamedTermManager

term_manager = NamedTermManager(shell_command=sys.argv[1:] or ['/bin/bash'])


@app.route('/term/<path:path>')
def index(path):
    return render_template('flaxterm.html',termname=path)

@app.route('/kill/<name>')
def killbyname(name):
    return  "killed %s" % (term_manager.kill_by_name(name))

@app.route('/new')
def newterm():
    name, terminal =term_manager.new_named_terminal()
    return "dd"
    redirect('/' + name)

@sockets.route('/websocket/<name>')
def echo_socket(ws,name=None):
    TermSocketHandler(ws,term_manager).serve()


import sys
if __name__ == "__main__":
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    server = pywsgi.WSGIServer(('', 8000), app, handler_class=WebSocketHandler,log=sys.stdout)
    server.serve_forever()



