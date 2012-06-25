# Implements twisted-based generic DGRAM transport
import sys
from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
from pysnmp.carrier.twisted.base import AbstractTwistedTransport
from pysnmp.carrier.address import TransportAddressPair
from pysnmp.carrier import error
from pysnmp import debug

class DgramTwistedTransport(DatagramProtocol, AbstractTwistedTransport):
    """Base Twisted datagram Transport, to be used with TwistedDispatcher"""

    # Twisted Datagram API
    
    def datagramReceived(self, datagram, transportAddress):
        if self._cbFun is None:
            raise error.CarrierError('Unable to call cbFun')
        else:
            # XXX fetch local endpoint from Twisted
            transportAddress = TransportAddressPair(None, transportAddress)
            # Callback fun is called through callLater() in attempt
            # to make Twisted timed calls work under high load.
            reactor.callLater(0, self._cbFun, self, transportAddress, datagram)

    def startProtocol(self):
        debug.logger & debug.flagIO and debug.logger('startProtocol: invoked')
        while self._writeQ:
            outgoingMessage, transportAddress = self._writeQ.pop(0)
            if isinstance(transportAddress, TransportAddressPair):
                transportAddress = transportAddress.getRemoteAddr()
            debug.logger & debug.flagIO and debug.logger('startProtocol: transportAddress %r outgoingMessage %r' % (transportAddress, outgoingMessage))
            try:
                self.transport.write(outgoingMessage, transportAddress)
            except Exception:
                raise error.CarrierError('Twisted exception: %s' % (sys.exc_info()[1],))

    def stopProtocol(self):
        debug.logger & debug.flagIO and debug.logger('stopProtocol: invoked')
        self.closeTransport()

    def sendMessage(self, outgoingMessage, transportAddress):
        debug.logger & debug.flagIO and debug.logger('startProtocol: %s transportAddress %r outgoingMessage %r' % ((self.transport is None and "queuing" or "sending"), transportAddress, outgoingMessage))
        if self.transport is None:
            self._writeQ.append((outgoingMessage, transportAddress))
        else:
            if isinstance(transportAddress, TransportAddressPair):
                transportAddress = transportAddress.getRemoteAddr()
            try:
                self.transport.write(outgoingMessage, transportAddress)
            except Exception:
                raise error.CarrierError('Twisted exception: %s' % (sys.exc_info()[1],))
