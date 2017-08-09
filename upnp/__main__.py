import argparse
import os
import uuid
import json
import yaml
from time import sleep
import logging

try:
    import netifaces
except:
    netifaces = None
    print("netifaces not available. You need to specify an IP address to bind to.")

from .ssdp import SSDPServer
from .http_server import UPNPHTTPServer


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def get_network_interface_ip_address(interface):
    """
    Get the first IP address of a network interface.
    :param interface: The name of the interface.
    :return: The IP address.
    """
    if not netifaces:
        # you will have to set your own uip address, or I can guess one from a local socket
        return None

    if not interface:
        interface = 'eth0'
    while True:
        if interface not in netifaces.interfaces():
            logger.error('Could not find interface %s.' % (interface,))
            exit(1)
        interface = netifaces.ifaddresses(interface)
        if len(interface) <2 or not len(interface[2]):
            logger.warning('Could not find IP of interface %s. Sleeping.' % (interface,))
            # shoudn't I just quit?
            sleep(60)
            continue
        return interface[2][0]['addr']


# @TODO once clean, move into separate file
class ServiceDescription:

    def __init__(self, dscr, address):
        with open(dscr) as f:
            values = self._description_data = yaml.load(f)
        if values.get('template'):
            # a template in the json will override the template
            template = values.get('template')
        else:
            # not sure if this the best place to put it
            template = "examples/service.template.xml"

        values.update({'presentation_url': 'http://{}:{}/description.xml'.format(*address)})
        self._values = values
        path = os.path.dirname(__file__)
        with open(os.path.join(path, "..", template)) as f:
            _template = f.read()
        self.description = _template.format(**values)

    def __getattr__(self, item):
        return self._values[item]

    @property
    def usn(self):
        # USN: uuid:Upnp-IRCamera-1_0-858fba00-d3a0-11dd-a001-00407F401ABA::upnp:rootdevice
        return 'uuid:{}-{}::upnp:rootdevice'.format(self._values['UDN'], self._values['MAC'])



def main(description_file, interface=None, address=None):
    """

    :param description: where to find the json server description
    :return:
    """

    local_ip_address = get_network_interface_ip_address(interface) or address
    port = 8088  # @todo make this parameteric as well

    assert local_ip_address, "You need to specify a local IP address, either by IP or interface (requires netifaces)"

    description = ServiceDescription(description_file, address=(local_ip_address, port))
    http_server = UPNPHTTPServer((local_ip_address, port), description.description)
    # http_server = UPNPHTTPServer(('0.0.0.0', port), description.description)
    http_server.start()

    ssdp = SSDPServer(local_ip_address)
    # those definitions should probably be automatic, give the UUID!
    ssdp.register('local',
                  description.usn,
                  'upnp:rootdevice',  # what are options exist?
                  http_server.description_url)
    ssdp.run()

# @todo instead of making it complicated with the interface, it's easier to just pass an ip address ;-)
# but of course that's way less future proof...



parser = argparse.ArgumentParser(description='UPNP Server.')
parser.add_argument('device_description', default='examples/m87.yaml', nargs='?',
                    help='description of the services(s) offered by this server')
parser.add_argument('-i', '--iface', default='eth0',
                    help='interface to be used to subscribe and send multicast packets. '
                         'Due to how networking works on *nix we get an ipaddress from the iface,'
                         ' which is then used to associate the socket (IP_MULTICAST_IF)')
parser.add_argument('-a', '--address', default=None,
                    help='address to be used to subscribe and send multicast packets.')

args = parser.parse_args()

# make those parametric from command line...
main(args.device_description, args.iface, args.address)
