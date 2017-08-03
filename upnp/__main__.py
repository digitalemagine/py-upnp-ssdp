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
    print("netifaces not available. No interface validation.")

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


class ServiceDescription:

    def __init__(self, dscr):
        with open(dscr) as f:
            _dscrp = self._description_data = yaml.load(f)
        if _dscrp.get('template'):
            # a template in the json will override the template
            template = _dscrp.get('template')
        else:
            # not sure if this the best place to put it
            template = "examples/service.template.xml"

        path = os.path.dirname(__file__)
        with open(os.path.join(path, "..", template)) as f:
            _template = f.read()
        self.description = _template.format(**_dscrp)



def main(description_file, interface=None):
    """

    :param description: where to find the json server description
    :return:
    """

    device_uuid = uuid.uuid4()  # instead use some config
    local_ip_address = get_network_interface_ip_address(interface)

    description = ServiceDescription(description_file)
    http_server = UPNPHTTPServer((local_ip_address, 8088), description.description)
    http_server.start()

    ssdp = SSDPServer()
    # those definitions should probably be automatic, give the UUID!
    ssdp.register('local',
                  'uuid:{}::upnp:rootdevice'.format(device_uuid),
                  'upnp:rootdevice',
                  http_server.description_url)
    ssdp.run()

# @todo instead of making it complicated with the interface, it's easier to just pass an ip address ;-)

# make those parametric from command line...
main('examples/m87.yaml', 'en3')  #bridge100
