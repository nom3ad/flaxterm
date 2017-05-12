from __future__ import absolute_import, print_function
import json
import logging

class  TermSocketHandler(object):
        
    def __init__(self, ws, term_manager):
        self.ws = ws
        self.term_manager = term_manager
        #print(ws.environ)
        self.term_size = (None,None)
        self.terminal = None # instant of PtyWithClients
        self._logger = logging.getLogger(__name__)
    
    def __repr__(self):
        return "<TermSocketHandler:%s>" % hex(id(self))
    def on_open(self):
        """Websocket connection opened.
        Call term_manager to get a terminal insatnce,and add this client to it
        """
        tname = self.create_name_for_terminal() or 'tty'
        self.terminal = self.term_manager.get_terminal(tname)
        for s in self.terminal.read_buffer:
            # create fake pty_read event for recent data in buffer
            self.on_pty_read(s)
        self.terminal.clients.append(self)
        self.send_json_message(["setup", {}])
        self._logger.info("added new client %s in %s" % (self.ws,self.terminal))

    def on_message(self,message):
        """Handle incoming websocket message
        We send JSON arrays, where the first element is a string indicating
        what kind of message this is. Data associated with the message follows.
        """
        command = json.loads(message)
        msg_type = command[0]    

        if msg_type == "stdin":
            logging.info("writes to pty with fd %s" % self.terminal.ptyproc.fd)
            print(self.terminal.ptyproc.write(command[1]))
        elif msg_type == "set_size":
            self.size = command[1:3]
            logging.info("resize command arrived") 
            self.terminal.resize_to_smallest()
    
    def on_close(self):
        """Handle websocket closing.
        Disconnect from our terminal, remove handler from clientlist
        and tell the terminal manager we're disconnecting.
        """
        self._logger.info("connection closing gracefully. %s",self.ws)
        if self.terminal:
            self.terminal.clients.remove(self)
            self.terminal.resize_to_smallest()
        self.term_manager.client_disconnected(self)

    def serve(self):
        self.on_open()

        while not self.ws.closed:
            message = self.ws.receive()
            try:
                self.on_message(message)  
            except:
                # incorrect message
                continue
        self.on_close()

    def send_json_message(self, content):
        json_msg = json.dumps(content)
        self.ws.send(json_msg)

    def create_name_for_terminal(self):
        return self.ws.environ['PATH_INFO'].split('/')[-1]

# events send by term_manager
    def on_pty_died(self):
        """Terminal closed: tell the frontend, and close the socket.
        called by manager
        """
        self.send_json_message(['disconnect', 1])
        self.ws.close()

    def on_pty_read(self, text):
        """Data read from pty; send to frontend
        called by manager
        """
        self.send_json_message(['stdout', text])

