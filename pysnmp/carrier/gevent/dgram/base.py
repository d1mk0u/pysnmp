# 
# Copyright (C) 2012 Credo Semiconductor Inc.
# Author: Xiongfei GUO, <xfguo@credosemi.com>
#
# This work is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License Version 2 as published by the 
# Free Software Foundation.
#
# This work is distributed in the hope that it will be useful, but without
# any warranty; without even the implied warranty of merchantability or
# fitness for a particular purpose. See the GNU General Public License for 
# more details. You should have received a copy of the GNU General Public 
# License along with this program; if not, write to: Free Software Foundation,
# Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA
#

from gevent import socket, select, Greenlet
from gevent.queue import Queue, Empty
from gevent.event import Event
from time import time
import errno, sys
from pysnmp.carrier.gevent.base import AbstractGeventTransport
from pysnmp.carrier import error

from pysnmp import debug
#debug.setLogger(debug.Debug('all', '!mibbuild', '!mibinstrum', '!mibview'))

sockErrors = { # Ignore these socket errors
    errno.ESHUTDOWN: 1,
    errno.ENOTCONN: 1,
    errno.ECONNRESET: 0,
    errno.ECONNREFUSED: 0,
    errno.EAGAIN: 0,
    errno.EWOULDBLOCK: 0
    }
try:
    # bad FD may happen upon FD closure on n-1 select() event
    sockErrors[errno.EBADFD] = 1
except AttributeError:
    # Windows sockets do not have EBADFD
    pass

class SocketRecvWaiter(Greenlet):
    def __init__(self, socket, outbox, event):
        self.socket = socket
        self.outbox = outbox
        self.event = event

        Greenlet.__init__(self)
    def _run(self):
        self.running = True
        while self.running:
            rlist, wlist, xlist = select.select([self.socket.fileno()], [], [])
            if rlist:
                incomingMessage, transportAddress = self.socket.recvfrom(65535)
                debug.logger & debug.flagIO and debug.logger('loop: transportAddress %r -> %r incomingMessage %s' % (transportAddress, self.socket.getsockname(), "" and debug.hexdump(incomingMessage)))
                
                self.outbox.put_nowait((transportAddress, incomingMessage))
                self.event.set()


class DgramGeventTransport(AbstractGeventTransport):
    sockType = socket.SOCK_DGRAM
    retryCount = 3; retryInterval = 1
    def __init__(self, sock=None):
        self.__outQueue = Queue()
        self.__inQueue = Queue()
        self.__queuesEvent = Event()
        AbstractGeventTransport.__init__(self, sock)
    
    def sendMessage(self, outgoingMessage, transportAddress):
        self.__outQueue.put_nowait(
            (outgoingMessage, transportAddress)
            )
        self.__queuesEvent.set()
    
    def openClientMode(self, iface=None):
        if iface is not None:
            try:
                self.socket.bind(iface)
            except socket.error:
                raise error.CarrierError('bind() for %s failed: %s' % (iface is None and "<all local>" or iface, sys.exc_info()[1],))
        
        self.srw = SocketRecvWaiter(self.socket, self.__inQueue, self.__queuesEvent)
        self.srw.start()
        return self
    
    def openServerMode(self, iface):
        try:
            self.socket.bind(iface)
        except socket.error:
            raise error.CarrierError('bind() for %s failed: %s' % (iface, sys.exc_info()[1],))
        
        self.srw = SocketRecvWaiter(self.socket, self.__inQueue, self.__queuesEvent)
        self.srw.start()
        return self
    def _send(self, outgoingMessage, transportAddress):
        debug.logger & debug.flagIO and debug.logger('handle_write: transportAddress %r -> %r outgoingMessage %s' % (self.socket.getsockname(), transportAddress, "" and debug.hexdump(outgoingMessage)))
        if not transportAddress:
            debug.logger & debug.flagIO and debug.logger('handle_write: missing dst address, loosing outgoing msg')
            return
        
        self.socket.sendto(outgoingMessage, transportAddress)
        
    def loop(self, timeout, time_tick_handler, jobsArePending):
        try:
            # wait until out queue or socket recv event.
            self.__queuesEvent.wait()

            # clear event first
            self.__queuesEvent.clear()

            # handle send
            if not self.__outQueue.empty():
                outgoingMessage, transportAddress = self.__outQueue.get_nowait()
                self._send(outgoingMessage, transportAddress)
    
                while True:
                    try:
                        transportAddress, incomingMessage = self.__inQueue.get(timeout = timeout)
                        self._cbFun(self, transportAddress, incomingMessage)
                    except Empty:
                        time_tick_handler(time())
                        debug.logger & debug.flagIO and debug.logger('loop: tick timeout')

                        if not self.__outQueue.empty():
                            outgoingMessage, transportAddress = self.__outQueue.get_nowait()
                            self._send(outgoingMessage, transportAddress)
                    finally:
                        if not jobsArePending():
                            debug.logger & debug.flagIO and debug.logger("loop: can't get response.")
                            return

            # handle recv
            if not self.__inQueue.empty():
                transportAddress, incomingMessage = self.__inQueue.get_nowait()
                self._cbFun(self, transportAddress, incomingMessage)
                return
        except socket.error:
            if sys.exc_info()[1].args[0] in sockErrors:
                debug.logger & debug.flagIO and debug.logger('loop: ignoring socket error %s' % (sys.exc_info()[1],))
                # sockErrors[sys.exc_info()[1].args[0]] and XXX: handle close here?
                return
            else:
                raise error.CarrierError('loop: sendto or recvfrom failed for %s: %s' % (transportAddress, sys.exc_info()[1]))
