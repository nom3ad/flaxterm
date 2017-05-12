"""Terminal management for exposing terminals to a web interface using Tornado.
"""
from __future__ import absolute_import, print_function

from collections import deque
import itertools
import logging
import os
import signal

from ptyprocess import PtyProcessUnicode

import gevent
from gevent.os import nb_read,nb_write,make_nonblocking

DEFAULT_TERM_TYPE = "xterm"

from gevent.socket import wait_read
from gevent.hub import get_hub

class FdWatcher(object):
    watchers = {}
    @classmethod
    def add_fd(cls, fd, cb):
        cls.watchers[fd] = gevent.spawn(FdWatcher.geen,fd,cb)
        print ("watching fd",fd,"by",cls.watchers[fd])
    @classmethod
    
    def remove_fd(cls,fd):
        pass

    @staticmethod
    def geen(fd,cb):
        import random
        id = random.randint(100,200)    
        while True:
            print (" [G:%s] agin wait" % id)
            wait_read(fd)
            print ("[G:%s]something to be read"%id)
            try:
                cb(fd)
            except Exception as oops:
                print("[G:%s]something happend in cb" %id ,repr(oops))
                if isinstance(oops,EOFError):
                    print("Exits fd watch for fd =",fd)
                    return

class Terminal(object):
    """Consists single pty object and tracks all assosiated web socket clients
    """
    def __init__(self, argv, cwd=None, env=None,
                                name='tty', dimensions=(24, 80)):
        ptyproc = PtyProcessUnicode.spawn(argv, env=env,cwd=cwd)
        self.ptyproc = ptyproc
        self.name = name

        # tracker for XtermSocketHandler connected to this terminal
        self.clients = []

        # Store the last few things read, so when a new client connects,
        # it can show e.g. the most recent prompt, rather than absolutely
        # nothing.
        self.read_buffer = deque([], maxlen=15)
    
    def __repr__(self):
        return ("<Terminal(name=%s, fd=%s, clients=[%r])>" % 
                    (self.name, self.ptyproc.fd, self.clients))
                    
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

def _update_removing(target, changes):
    """Like dict.update(), but remove keys where the value is None.
    """
    for k, v in changes.items():
        if v is None:
            target.pop(k, None)
        else:
            target[k] = v

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

        self.terminals_by_fd = {}

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

    def _new_terminal(self, **kwargs):
        """Make a new terminal, return a :class:`Terminal` instance."""
        options = self.term_settings.copy()
        options['shell_command'] = self.shell_command
        options.update(kwargs) 
        argv = options['shell_command']
        env = self._make_term_env(**options)
        terminal = Terminal(argv, env=env, cwd=options.get('cwd', None))
        self.log.info('New Termainal started %r' % terminal)
        return terminal

    def _start_reading(self, terminal):
        """Connect a terminal to the tornado event loop to read data from it."""
        fd = terminal.ptyproc.fd
        self.terminals_by_fd[fd] = terminal
        FdWatcher.add_fd(fd, self._pty_read)

    def _on_eof(self, ptywclients):
        """Called when the pty has closed.
        """
        # Stop trying to read from that terminal
        fd = ptywclients.ptyproc.fd
        self.log.info(" ******** EOF on FD %d; stopping reading", fd)
        del self.terminals_by_fd[fd]
        FdWatcher.remove_fd(fd)

        # This closes the fd, and should result in the process being reaped.
        ptywclients.ptyproc.close()

    def _pty_read(self, fd):
        """Called by the event loop when there is pty data ready to read."""
        ptywclients = self.terminals_by_fd[fd]
        try:
            s = ptywclients.ptyproc.read(65536)
            print("read %s bytes" % len(s))
            ptywclients.read_buffer.append(s)
            for client in ptywclients.clients:
                client.on_pty_read(s)
        except EOFError:
            self._on_eof(ptywclients)
            for client in ptywclients.clients:
                client.on_pty_died()
            raise

    def get_terminal(self, *args, **kwargs):
        """Override in a subclass to give a terminal to a new websocket connection
        The :class:`TermSocket` handler works with zero or one URL components
        (capturing groups in the URL spec regex). If it receives one, it is
        passed as the ``url_component`` parameter; otherwise, this is None.
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
        self.terminal = None

    def get_terminal(self, term_name=None):
        if self.terminal is None:
            #ie, first websocket connection
            self.terminal = self._new_terminal()
            self._start_reading(self.terminal)
        return self.terminal
    
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
        if self.max_terminals and len(self.terminals_by_fd) >= self.max_terminals:
            raise MaxTerminalsReached(self.max_terminals)

        term = self._new_terminal()
        self._start_reading(term)
        return term

    def client_disconnected(self, websocket):
        """Send terminal SIGHUP when client disconnects."""
        self.log.info("Websocket closed, sending SIGHUP to terminal.")
        if websocket.terminal:
            websocket.terminal.kill(signal.SIGHUP)


class NamedTermManager(TermManagerBase):
    """Share terminals between websockets connected to the same endpoint.
    """
    def __init__(self, max_terminals=None, **kwargs):
        super(NamedTermManager, self).__init__(**kwargs)
        self.max_terminals = max_terminals
        self.terminals = {}

    def get_terminal(self, term_name):
        assert term_name is not None
        
        if term_name in self.terminals:
            return self.terminals[term_name]
        
        if self.max_terminals and len(self.terminals) >= self.max_terminals:
            raise MaxTerminalsReached(self.max_terminals)

        # Create new terminal
        self.log.info("New terminal with specified name: %s", term_name)
        term = self._new_terminal()
        term.term_name = term_name
        self.terminals[term_name] = term
        self._start_reading(term)
        return term

    name_template = "%d"

    def _next_available_name(self):
        for n in itertools.count(start=1):
            name = self.name_template % n
            if name not in self.terminals:
                return name

    def new_named_terminal(self):
        name = self._next_available_name()
        term = self._new_terminal()
        self.log.info("New terminal with automatic name: %s", name)
        term.term_name = name
        self.terminals[name] = term
        self._start_reading(term)
        return name, term

    def kill(self, name, sig=signal.SIGTERM):
        term = self.terminals[name]
        term.kill()   # This should lead to an EOF
    
    # @gen.coroutine
    # def terminate(self, name, force=False):
    #     term = self.terminals[name]
    #     yield term.terminate(force=force)
    
    def on_eof(self, ptywclients):
        super(NamedTermManager, self)._on_eof(ptywclients)
        name = ptywclients.term_name
        self.log.info("Terminal %s closed", name)
        self.terminals.pop(name, None)
    
    # @gen.coroutine
    # def kill_all(self):
    #     yield super(NamedTermManager, self).kill_all()
    #     self.terminals = {}
