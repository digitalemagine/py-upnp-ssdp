# Licensed under the MIT license
# http://opensource.org/licenses/mit-license.php

# Copyright 2005, Tim Potter <tpot@samba.org>
# Copyright 2006 John-Mark Gurney <gurney_j@resnet.uroegon.edu>
# Copyright (C) 2006 Fluendo, S.A. (www.fluendo.com).
# Copyright 2006,2007,2008,2009 Frank Scholz <coherence@beebits.net>
# Copyright 2016 Erwan Martin <public@fzwte.net>
#
# Implementation of a SSDP server.
#

# @TODO - need an asyncio version of this! but... there's a known asyncio multicast bug grrrr :
# https://github.com/python/asyncio/issues/480
# https://github.com/python/cpython/pull/423
# checkout, thou:
# * https://stackoverflow.com/questions/41418023/python-asyncio-how-to-receive-multicast-responses
# * and its source: https://www.reddit.com/r/learnpython/comments/4drk0a/asyncio_multicast_udp_socket_on_342/


import random
import time
import socket
import logging
import struct
import asyncio
from email.utils import formatdate
from errno import ENOPROTOOPT

SSDP_PORT = 1900
SSDP_ADDR = '239.255.255.250'
SERVER_ID = 'SSDP Server'
# or pick it based on interface, which is more flexible

logger = logging.getLogger()


class SSDPServer:
    """A class implementing a SSDP server.  The notify_received and
    searchReceived methods are called when the appropriate type of
    datagram is received by the server."""
    known = {}

    def __init__(self, local_address):
        self.sock = None
        # this is REQUIRED to pick the correct interface!!
        self.local_address = local_address

    def run(self):
        self.register_multicast()

    def register_multicast(self):

        # Create the socket
        sock = self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Set some options to make it multicast-friendly
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            # except AttributeError:
            #     pass  # Some systems don't support SO_REUSEPORT
            except socket.error as le:
                # RHEL6 defines SO_REUSEPORT but it doesn't work
                if le.errno == ENOPROTOOPT:
                    pass
                else:
                    raise
        sock.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_TTL, 4)
        sock.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_LOOP, 1)

        addr = socket.inet_aton(SSDP_ADDR)
        # @TODO: with multiple interfaces and mac os there seems to be some mess...
        # let's try to force the iface we want by setting a specific address.
        # This probably behaves differently also according to the OS and any additional bridging/routing/etc.
        # local_address = '0.0.0.0'
        ttl = struct.pack('b', 1)
        sock.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_TTL, ttl)
        sock.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_LOOP, 1)

        ssdp_addr = socket.inet_aton(SSDP_ADDR)
        iface_addr = socket.inet_aton(self.local_address)

        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, iface_addr)

        # this is for listening to ALL interfaces.. but seems messy and confusing
        # mreq = struct.pack('4sL', ssdp_addr, socket.INADDR_ANY)
        mreq = ssdp_addr + iface_addr
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.bind(('', SSDP_PORT))
        # sock.settimeout(1)
        sock.setblocking(0)

        notify_timeout = time.time()
        while True:
            # @TODO arg - re-implement this without a busy loop?
            try:
                data, addr = self.sock.recvfrom(1024)
                self.datagram_received(data, addr)
            except socket.timeout:
                continue
            except socket.error as e:
                if e.errno == socket.errno.EWOULDBLOCK:  # == errno.EAGAIN
                    # no data yet
                    time.sleep(0.2)
                else:
                    print("Unknown socket error: {}".format(e))
                    break
            if time.time() - notify_timeout > 10:
                self.do_notify()
                notify_timeout = time.time()

        self.shutdown()

    # @TODO we should also send NOTIFY of our own... that's what FLIR does...

    def shutdown(self):
        for st in self.known:
            if self.known[st]['MANIFESTATION'] == 'local':
                self.do_byebye(st)

    def datagram_received(self, data, host_port):
        """Handle a received multicast datagram."""

        (host, port) = host_port

        try:
            header, payload = data.decode().split('\r\n\r\n')[:2]
        except ValueError as err:
            logger.error(err)
            return

        lines = header.split('\r\n')
        cmd = lines[0].split(' ')
        lines = map(lambda x: x.replace(': ', ':', 1), lines[1:])
        lines = filter(lambda x: len(x) > 0, lines)

        headers = [x.split(':', 1) for x in lines]
        headers = dict(map(lambda x: (x[0].lower(), x[1]), headers))

        logger.info('SSDP command %s %s - from %s:%d' % (cmd[0], cmd[1], host, port))
        logger.debug('with headers: {}.'.format(headers))
        if cmd[0] == 'M-SEARCH' and cmd[1] == '*':
            # SSDP discovery
            self.discovery_request(headers, (host, port))
        elif cmd[0] == 'NOTIFY' and cmd[1] == '*':
            # SSDP presence
            logger.debug('NOTIFY *')
        else:
            logger.warning('Unknown SSDP command %s %s' % (cmd[0], cmd[1]))

    def register(self, manifestation, usn, st, location, server=SERVER_ID, cache_control='max-age=1800', silent=False,
                 host=None):
        """Register a service or device that this SSDP server will
        respond to."""
        # @TODO Extremely messy parameters

        logging.info('Registering %s (%s)' % (st, location))

        self.known[usn] = {}
        self.known[usn]['USN'] = usn
        self.known[usn]['LOCATION'] = location
        self.known[usn]['ST'] = st
        self.known[usn]['EXT'] = ''
        self.known[usn]['SERVER'] = server
        self.known[usn]['CACHE-CONTROL'] = cache_control

        self.known[usn]['MANIFESTATION'] = manifestation
        self.known[usn]['SILENT'] = silent
        self.known[usn]['HOST'] = host
        self.known[usn]['last-seen'] = time.time()

        # @todo better naming, but we want an easy way to access our own info!
        self.settings = self.known[usn]

        if manifestation == 'local' and self.sock:
            self.do_notify(usn)

    def unregister(self, usn):
        logger.info("Un-registering %s" % usn)
        del self.known[usn]

    def is_known(self, usn):
        return usn in self.known

    def send_it(self, response, destination, usn, delay):
        logger.debug('send discovery response delayed by %fs for %s to %r', delay, usn, destination)
        try:
            self.sock.sendto(response.encode(), destination)
        except (AttributeError, socket.error) as msg:
            logger.warning("failure sending out byebye notification: %r", msg)

    def discovery_request(self, headers, host_port):
        """Process a discovery request.  The response must be sent to
        the address specified by (host, port)."""

        (host, port) = host_port

        logger.info('Discovery request from (%s,%d) for %s' % (host, port, headers['st']))
        logger.info('Discovery request for %s' % headers['st'])

        # Do we know about this service?
        for i in self.known.values():
            if i['MANIFESTATION'] == 'remote':
                continue
            if headers['st'] == 'ssdp:all' and i['SILENT']:
                continue
            if i['ST'] == headers['st'] or headers['st'] == 'ssdp:all':
                response = ['HTTP/1.1 200 OK']

                usn = None
                for k, v in i.items():
                    if k == 'USN':
                        usn = v
                    if k not in ('MANIFESTATION', 'SILENT', 'HOST'):
                        response.append('%s: %s' % (k, v))

                if usn:
                    response.append('DATE: %s' % formatdate(timeval=None, localtime=False, usegmt=True))

                    response.extend(('', ''))
                    delay = random.random() * int(headers['mx'])

                    self.send_it('\r\n'.join(response), (host, port), usn, delay)

    def do_notify(self, usn=None):
        """Do notification"""
        # I don't think i need to keep usn as an option..
        if usn:
            settings = self.known[usn]
        else:
            settings = self.settings
        if settings['SILENT']:
            return
        logger.info('Sending NOTIFY for %s', settings['USN'])

        resp = [
            'NOTIFY * HTTP/1.1',
            'HOST: %s:%d' % (SSDP_ADDR, SSDP_PORT),
            'NTS: ssdp:alive',
        ]
        stcpy = dict(settings.items())
        stcpy['NT'] = stcpy['ST']
        del stcpy['ST']
        del stcpy['MANIFESTATION']
        del stcpy['SILENT']
        del stcpy['HOST']
        del stcpy['last-seen']

        resp.extend(map(lambda x: ': '.join(x), stcpy.items()))
        resp.extend(('', ''))
        dest = (SSDP_ADDR, SSDP_PORT)
        text = '\r\n'.join(resp)
        logger.info('do_notify content to %s', dest)
        # logger.debug(text)
        try:
            # @todo m87 sends multiple notifications with slight variations...
            # self.sock.sendto('\r\n'.join(resp).encode(), dest)
            print("sent: %d" % self.sock.sendto(text.encode(), dest))
        except (AttributeError, socket.error) as msg:
            logger.warning("failure sending out alive notification: %r" % msg)

    def do_byebye(self, usn):
        """Do byebye"""

        logger.info('Sending byebye notification for %s' % usn)

        resp = [
            'NOTIFY * HTTP/1.1',
            'HOST: %s:%d' % (SSDP_ADDR, SSDP_PORT),
            'NTS: ssdp:byebye',
        ]
        try:
            stcpy = dict(self.known[usn].items())
            stcpy['NT'] = stcpy['ST']
            del stcpy['ST']
            del stcpy['MANIFESTATION']
            del stcpy['SILENT']
            del stcpy['HOST']
            del stcpy['last-seen']
            resp.extend(map(lambda x: ': '.join(x), stcpy.items()))
            resp.extend(('', ''))
            logger.debug('do_byebye content', resp)
            if self.sock:
                try:
                    self.sock.sendto('\r\n'.join(resp), (SSDP_ADDR, SSDP_PORT))
                except (AttributeError, socket.error) as msg:
                    logger.error("failure sending out byebye notification: %r" % msg)
        except KeyError as msg:
            logger.error("error building byebye notification: %r" % msg)
