#!/usr/bin/env python
from flask import Flask, render_template, session, request,send_from_directory,redirect
from flask_sockets import Sockets
import json,logging
logging.basicConfig(level=logging.INFO)
# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
app = Flask(__name__)
sockets = Sockets(app)
app.debug = True

print "start"




# @app.route('/static/<path:path>')
# def staticserve(path):
#     return path
#     #return send_from_directory('static', path)
import gevent,random,sys
from ptyprocess import PtyProcessUnicode

from gevent.os import nb_read,nb_write,make_nonblocking

from management import SingleTermManager,UniqueTermManager,NamedTermManager
from termsocket import XtermSocketHandler

term_manager = NamedTermManager(shell_command=sys.argv[1:] or ['bash'])


@app.route('/<path:path>')
def index(path):
    return render_template('flaxterm.html',termname=path)


@app.route('/new')
def newterm():
    #name, terminal =term_manager.new_named_terminal()
    return "dd"
    #redirect('/' + name)

@sockets.route('/websocket/<name>')
def echo_socket(ws,name=None):
    XtermSocketHandler(ws,term_manager).serve()


import sys
if __name__ == "__main__":
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    server = pywsgi.WSGIServer(('', 8000), app, handler_class=WebSocketHandler,log=sys.stdout)
    server.serve_forever()



