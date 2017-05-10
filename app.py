#!/usr/bin/env python
from flask import Flask, render_template, session, request,send_from_directory
from flask_sockets import Sockets
import json

# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
app = Flask(__name__)
sockets = Sockets(app)
app.debug = True

print "start"
@app.route('/t')
def index():
    return render_template('flaxterm.html')

# @app.route('/static/<path:path>')
# def staticserve(path):
#     return path
#     #return send_from_directory('static', path)
import gevent,random
from ptyprocess import PtyProcessUnicode

from gevent.os import nb_read,nb_write,make_nonblocking
@sockets.route('/echo')
def echo_socket(ws):
    send_json_message(ws,["setup", {}])
    #send_json_message(ws,['stdout', "abcd@demo $ "])
    term = (PtyProcessUnicode.spawn(['/bin/bash']))
    print "started terminal", term.pid
    print("non blocked",make_nonblocking(term.fd))
    gevent.spawn(geen,ws,term)
    try:
        while not ws.closed:
            message = ws.receive()
            try:
                command = json.loads(message)
                msg_type = command[0]  
            except:
                # incorrect message
                continue
            if msg_type == "stdin":
                #send_json_message(ws,['stdout', command[1]])
                nb_write(term.fd,command[1])
                print "written"
            elif msg_type == "set_size":
                ws.send("SIZE SET")
    except Exception as oops:
        print "Exits downlink:  for %s : %s" % (repr(ws) ,repr(oops))
        pass


from  geventwebsocket.exceptions import WebSocketError
def geen(ws,term):
    try:
        # for i in range(10000):
        #     send_json_message(ws,['stdout','a'])
        #     gevent.sleep(1)
        print "hey"
        while True:
             x = nb_read(term.fd,1024)
             # Read up to n bytes from file descriptor fd. 
             # Return a string containing the bytes read. 
             # If end-of-file is reached, an empty string is returned.
             # The descriptor must be in non-blocking mode.
             print 'read : ',x
             if not x:
                 break
             send_json_message(ws,['stdout',x])
        print "end while"
    except WebSocketError as oops:
        print "Exits uplink:  for %s : %s" % (repr(ws) ,repr(oops))
        return
    print "Exits uplink: shouldnt be g=here"

def send_json_message(ws, content):
        json_msg = json.dumps(content)
        ws.send(json_msg)



import sys
if __name__ == "__main__":
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    server = pywsgi.WSGIServer(('', 8000), app, handler_class=WebSocketHandler,log=sys.stdout)
    server.serve_forever()



