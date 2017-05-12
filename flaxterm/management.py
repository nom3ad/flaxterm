"""Terminal manageme module
"""
from __future__ import absolute_import, print_function

from collections import deque
import itertools
import logging
import os
import signal

from ptyprocess import PtyProcessUnicode

import gevent
from gevent.socket import wait_read
# from gevent.os import nb_read,nb_write,make_nonblocking
# from gevent.hub import get_hub

DEFAULT_TERM_TYPE = "xterm"

class FdWatcher(object):

    def __init__(self,terminal):
        self.callback = None
        self.terminal = terminal
        self.g = None

    def start(self, callback):
        self.callback = callback
        self.g = gevent.spawn(FdWatcher.green_watch,self)
        print ("watching fd for terminal %r" % self.terminal)
    
    def remove(self):
        self.callback = None
        self.g = None

    @staticmethod
    def green_watch(watcher):
        import random
        id = random.randint(1000,9000)
        fd = watcher.terminal.ptyproc.fd
        while watcher.callback:
            print (" [G:%s] on wait" % id)
            wait_read(fd)
            print (" [G:%s] after wait,something to be read"%id)
            try:
                watcher.callback(watcher.terminal)
            except Exception as oops:
                if isinstance(oops,EOFError):
                    print(" [G:%sExits fd watch for fd =" % id,fd)
                    return
                raise
        print("green watcher for fd=%s ended gracefully" % fd)

def _update_removing(target, changes):
    """Like dict.update(), but remove keys where the value is None.
    """
    for k, v in changes.items():
        if v is None:
            target.pop(k, None)
        else:
            target[k] = v

class Terminal(object):
    """Consists single pty object and tracks all assosiated web socket clients
    """
    def __init__(self, argv, cwd=None, env=None,
                                name='tty', dimensions=(24, 80)):
        ptyproc = PtyProcessUnicode.spawn(argv, env=env,cwd=cwd)
        self.ptyproc = ptyproc
        self.name = name
        self.read_watch = FdWatcher(self)
        # tracker for XtermSocketHandler connected to this terminal
        self.clients = []

        # Store the last few things read, so when a new client connects,
        # it can show e.g. the most recent prompt, rather than absolutely
        # nothing.
        self.read_buffer = deque([], maxlen=15)
    
    def __repr__(self):
        return ("<Terminal(name=%s, fd=%s, clients=%r)>" % 
                    (self.name, self.ptyproc.fd, self.clients))

    # this method is not needed. directly calling ptyprc.write
    # from socketHandler is good.
    # def write(self,data):  
    #     if not self.ptyproc.write(data):
    #         if self.ptyproc.fd < 0:
    #             print("broad cast death new")
    #             [c.on_pty_died for c in self.clients]

    def start_reading(self,cb):
        self.read_watch.start(cb)
    
    def stop_reading(self):
        self.read_watch.remove()

    def resize_to_smallest(self):
        """Set the terminal size to that of the smallest client dimensions.
        A terminal not using the full space available is much nicer than a
        terminal trying to use more than the available space, so we keep it 
        sized to the smallest client.
        """
        minrows = mincols = 10001
        for client in self.clients:
            rows, cols = client.size
            if rows is not None and rows < minrows:
                minrows = rows
            if cols is not None and cols < mincols:
                mincols = cols

        if minrows == 10001 or mincols == 10001:
            return
        
        rows, cols = self.ptyproc.getwinsize()
        if (rows, cols) != (minrows, mincols):
            self.ptyproc.setwinsize(minrows, mincols)

    def kill(self, sig=signal.SIGTERM):
        self.ptyproc.kill(sig)
    
    #@gen.coroutine
    def terminate(self, force=False):
        '''This forces a child process to terminate. It starts nicely with
        SIGHUP and SIGINT. If "force" is True then moves onto SIGKILL. This
        returns True if the child was terminated. This returns False if the
        child could not be terminated. '''
        
        #sleep = lambda : gevent.sleep(self.ptyproc.delayafterterminate)
        def sleep():
            print('sleeps %ss',self.ptyproc.delayafterterminate)
            gevent.sleep(self.ptyproc.delayafterterminate)

        if not self.ptyproc.isalive():
            return(True)
        try:
            self.kill(signal.SIGHUP)
            sleep()
            if not self.ptyproc.isalive():
                return(True)
            self.kill(signal.SIGCONT)
            sleep()
            if not self.ptyproc.isalive():
                return(True)
            self.kill(signal.SIGINT)
            sleep()
            if not self.ptyproc.isalive():
                return(True)
            self.kill(signal.SIGTERM)
            sleep()
            if not self.ptyproc.isalive():
                rreturn(True)
            if force:
                self.kill(signal.SIGKILL)
                sleep()
                if not self.ptyproc.isalive():
                    return(True)
                else:
                    return(False)
            return(False)
        except OSError:
            # I think there are kernel timing issues that sometimes cause
            # this to happen. I think isalive() reports True, but the
            # process is dead to the kernel.
            # Make one last attempt to see if the kernel is up to date.
            sleep()
            if not self.ptyproc.isalive():
                return(True)
            else:
                return(False)



class TermManagerBase(object):
    """Base class for a terminal manager."""
    def __init__(self, shell_command, term_settings={}, extra_env=None):
        """
        term_settings : dict of settings : eg type, cwd etc
        """
        self.shell_command = shell_command
        self.term_settings = term_settings
        self.extra_env = extra_env

        self.log = logging.getLogger(__name__)

        self.terminals = []

    def _make_term_env(self, height=25, width=80, winheight=0, winwidth=0, **kwargs):
        """Build the environment variables for the process in the terminal."""
        env = os.environ.copy()
        env["TERM"] = self.term_settings.get("type",DEFAULT_TERM_TYPE)
        dimensions = "%dx%d" % (width, height)
        if winwidth and winheight:
            dimensions += ";%dx%d" % (winwidth, winheight)
        env["DIMENSIONS"] = dimensions
        env["COLUMNS"] = str(width)
        env["LINES"] = str(height)

        if self.extra_env:
            _update_removing(env, self.extra_env)

        return env

    def _new_terminal(self, name='tty',**kwargs):
        """Make a new terminal, return a :class:`Terminal` instance."""
        options = self.term_settings.copy()
        options['shell_command'] = self.shell_command
        options.update(kwargs) 
        argv = options['shell_command']
        env = self._make_term_env(**options)
        terminal = Terminal(argv,env=env, cwd=options.get('cwd', None),name=name)
        self.log.info('New Termainal started %r' % terminal)
        self.terminals.append(terminal)
        return terminal
       

    def _on_eof(self, terminal):
        """Called when the pty of a Terminal instance has closed.
        """
        # Stop trying to read from that terminal
        #self.log.info(" ******** EOF on FD %d; stopping reading", fd)
        self.terminals.remove(terminal)
        terminal.stop_reading()
        
        # This closes the fd, and should result in the process being reaped.
        terminal.ptyproc.close()

    def _pty_read_callback(self, terminal):
        """Called by the Terminal FdWatcher greenlet when
        there is pty data ready to be read."""
        try:
            s = terminal.ptyproc.read(65536)
            print("read %s bytes" % len(s))
            terminal.read_buffer.append(s)
            for client in terminal.clients:
                client.on_pty_read(s)
        except EOFError:
            self._on_eof(terminal)
            for client in terminal.clients:
                client.on_pty_died()
            # raise so that FDwatchet eventloop will close : TODO remove
            # raise

    def get_terminal(self, *args, **kwargs):
        """Should be implemented in a subclass.
        Provides a terminal instance (object of :class:Terminal) 
        to a new websocket connection
        """
        raise NotImplementedError

    def client_disconnected(self, websocket):
        """Override this to e.g. kill terminals on client disconnection.
        """
        pass

    # @gen.coroutine
    # def shutdown(self):
    #     yield self.kill_all()

    # @gen.coroutine
    # def kill_all(self):
    #     futures = []
    #     for term in self.ptys_by_fd.values():
    #         futures.append(term.terminate(force=True))
    #     # wait for futures to finish
    #     for f in futures:
    #         yield f


class SingleTermManager(TermManagerBase):
    """All connections to the websocket share a common terminal."""
    def __init__(self, **kwargs):
        super(SingleTermManager, self).__init__(**kwargs)

    def get_terminal(self,term_name=None):
        if not self.terminals:
            #ie, first websocket connection
            term = self._new_terminal()
            term.start_reading(self._pty_read_callback)
            return term
        assert len(self.terminals) == 1
        return self.terminals[0]
    
    # @gen.coroutine
    # def kill_all(self):
    #     yield super(SingleTermManager, self).kill_all()
    #     self.terminal = None


class MaxTerminalsReached(Exception):
    def __init__(self, max_terminals):
        self.max_terminals = max_terminals
    
    def __str__(self):
        return "Cannot create more than %d terminals" % self.max_terminals

class UniqueTermManager(TermManagerBase):
    """Give each websocket a unique terminal to use."""
    def __init__(self, max_terminals=None, **kwargs):
        super(UniqueTermManager, self).__init__(**kwargs)
        self.max_terminals = max_terminals

    def get_terminal(self, term_name=None):
        if self.max_terminals and len(self.terminals) >= self.max_terminals:
            raise MaxTerminalsReached(self.max_terminals)

        term = self._new_terminal()
        term.start_reading(self._pty_read_callback)
        return term

    def client_disconnected(self, websocket):
        """Send terminal SIGHUP when client disconnects."""
        self.log.info("Websocket closed, sending SIGHUP to terminal.")
        if websocket.terminal:
            websocket.terminal.kill(signal.SIGHUP)


class NamedTermManager(TermManagerBase):
    """Share terminals between websockets connected to the same endpoint.
    """
    
    name_template = "%d"

    def __init__(self, max_terminals=None, **kwargs):
        super(NamedTermManager, self).__init__(**kwargs)
        self.max_terminals = max_terminals

    def get_terminal(self, term_name):
        assert term_name is not None
        self.log.info("Gets terminal by specified name: %s", term_name)
        term = next((t for t in self.terminals if t.name == term_name),None)
        if term:
            return term
        
        if self.max_terminals and len(self.terminals) >= self.max_terminals:
            raise MaxTerminalsReached(self.max_terminals)

        # Create new terminal
        
        term = self._new_terminal(name=term_name)
        term.start_reading(self._pty_read_callback)
        return term

    def _next_available_name(self):
        taken_names = [t.name  for t in self.terminals]
        for n in itertools.count(start=1):
            name = self.name_template % n
            if name not in taken_names:
                return name

    def new_named_terminal(self):
        name = self._next_available_name()
        term = self._new_terminal(name=name)
        self.log.info("New terminal with automatic name: %s", name)
        term.start_reading(self._pty_read_callback)
        return name, term

    def kill_by_name(self, name, sig=signal.SIGTERM):
        term = next((t for t in self.terminals if t.name == name),None)
        print("killing",name,"from list",[t.name for t in self.terminals])
        if term:
            term.kill()   # This should lead to an EOF
            return term
    
    # @gen.coroutine
    # def terminate(self, name, force=False):
    #     term = self.terminals[name]
    #     yield term.terminate(force=force)
    
    # @gen.coroutine
    # def kill_all(self):
    #     yield super(NamedTermManager, self).kill_all()
    #     self.terminals = {}
