# @TODO instead of using threading, replace with aiohttp!
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import json
import logging

logger = logging.getLogger()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)


def parse_jcu_command(path):
    duration = None
    # the logic is slightly weird. The main command is a 'structure' in dot notation,
    # but there can be more than one "nested" value:
    # > axis.t.displacement=-57,duration=0
    # {"axis":{"t":{"displacement":-32,"duration":0}}}
    # this is a generic way to parse, but in any case we'll need to interpret the commands at some point
    """
    for some commands (`button`) the normal pattern:
     
        a.b.c=3,d=4 => a: b: c
        
    is instead:
    
        a.b,c=3,d=4
        
    in that case, _command should include the first additional term.
    """
    # print("parsing {}".format(path))
    commands = {}  # list of all commands
    _commands = commands  # pointer
    _path = path.split('.')

    _v = _path[-1].split(',', 1)
    if '=' not in _v[0]:
        _command = _path[:-1] + [_v[0]]
        # I have no examples yet... but there could be no "values". Might need to protect this.
        _values = _v[1]
    else:
        _command = _path[:-1]
        _values = _path[-1]

    values = dict(v.split('=') for v in _values.split(','))

    while _command:
        k = _command.pop(0)
        _commands[k] = {}
        _commands = _commands[k]
    for k, v in values.items():
        try:
            # check if this is a number...
            v = float(v)
        except:
            pass
        _commands[k] = v
        if k == 'duration':  # special case - do we care?
            duration = v
    return commands


def test_parse_jcu_command():

    for (request, response) in [

        # "jcu_config", {"config":{"timescale":-3,"magnitudescale":0,"keepalive":2000,"commandrepeat":500,"cameraudn":M-Series,"powerondelay":1000,"shutdowndelay":2000,"backlightdelay":1000,"deadbandatrest_idx":25,"deadbandatrest_idy":25,"deadbandatrest_idz":25, "deadbandatrest_idt":25,"deadbandtranslation_idx":0,"deadbandtranslation_idy":0,"deadbandtranslation_idz":0,"deadbandtranslation_idt":0}}),
        ("connect.jcuudn=uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6",
         {"connect": {"jcuudn": "uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6"}}),
        ("keepalive.jcuudn=uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6",
         {"keepalive": {"jcuudn": "uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6"}}),
        ("axis.t.displacement=-32,duration=0",
         {"axis": {"t": {"displacement": -32, "duration": 0}}}),
        ("button.F,state=DOWN,duration=0,jcuudn=uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6",
         {"button": {"F": {"state": "DOWN", "duration": 0}}}),
        ("button.F,state=UP,duration=210,jcuudn=uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6",
         {"button": {"F": {"state": "UP", "duration": 210}}}),
        # the way things are combined is just... crazy....
        ("button.F,state=DOWN,duration=2000,jcuudn=uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6,F,state=UP,duration=2010,jcuudn=uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6", {})
    ]:
        r = parse_jcu_command(request)
        # This test will fail if jcuudn is returned for `button` messages... thou that's because it's a crappy api :-(
        assert r == response, "parsing error: {} != {}".format(r, response)


class UPNPHTTPServerHandler(BaseHTTPRequestHandler):
    """
    A HTTP handler that serves the UPnP XML descriptions and responds to the JCU commands.


    JCU
    ===

    known requests (and responses)



    /bi-cgi?connect.jcuudn=uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6
        {"connect":{"jcuudn":"uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6"}}\r\n
    /bi-cgi?jcu_config
        {"config":{"timescale":-3,"magnitudescale":0,"keepalive":2000,"commandrepeat":500,"cameraudn":M-Series,"powerondelay":1000,"shutdowndelay":2000,"backlightdelay":1000,"deadbandatrest_idx":25,"deadbandatrest_idy":25,"deadbandatrest_idz":25, "deadbandatrest_idt":25,"deadbandtranslation_idx":0,"deadbandtranslation_idy":0,"deadbandtranslation_idz":0,"deadbandtranslation_idt":0}}
    /bi-cgi?keepalive.jcuudn=uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6
        {"keepalive":{"jcuudn":"uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6"}}\r\n
    /bi-cgi?axis.t.displacement=-57,duration=0
        {"axis":{"t":{"displacement":-32,"duration":0}}}\r\n

    /bi-cgi?button.F,state=DOWN,duration=0,jcuudn=uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6
        {"button":{"F":{"state":"DOWN","duration":0}}}
    /bi-cgi?button.F,state=UP,duration=210,jcuudn=uuid:JCU-1_0-1A22-EF16-11DD-84A7-00405F40A3D6
        {"button":{"F":{"state":"UP","duration":210}}}

    # in some cases the jcuudn is sent again... but only in some cases! and it's not replied.
    # also this command is not conform, as it should be:
        button.F,state -> button.F.state


    """

    # Handler for the GET requests
    def do_GET(self):
        logger.info("Got a `GET` for %s from %s", self.path, self.client_address)
        if self.path.startswith('/bi-cgi?'):
            return self.parse_jcu_command(self.path.replace('/bi-cgi?', ''))

        if self.path == '/description.xml':  # this should be parametric... check server.description_url!
            return self.return_description()
        # i could centralize sending the response here
        logger.warning("Unknown request %s", self.path)

    def respond(self, message, content_type='text/html'):
        try:
            self.send_response(200)
            self.send_header('Content-type', content_type)
            self.end_headers()
            self.wfile.write(message)
        except Exception as e:
            logger.error('Could not send out a response to the request `%s`: %s', self.path, e)

    def return_description(self):
        logger.debug("sending description: %s", self.server.description)
        self.respond(self.server.description.encode(), 'application/xml')
        return

    def parse_jcu_command(self, path):
        """
        process jcu_commands
        :return:
        """
        # bit of repetition with bi-cgi. Instead, each response could check if it can handle the path.
        # Or we pass the "command" part to this method
        if path == 'jcu_config':
            # this is a bit of an exception so we could take it out of this method
            # here we should return some config:
            logger.info("received an SSDP XML config request (%s)", self.path)
            response = json.dumps(self.camera_config())
        else:
            commands = parse_jcu_command(path)
            #         if k == 'duration':  # special case - do we care?
            response = json.dumps(commands)

        self.respond(response.encode())

    def camera_config(self):
        # m87
        config = {
            "config": {
                "timescale": -3, "magnitudescale": 0, "keepalive": 2000, "commandrepeat": 500,
                "cameraudn": "M-Series", "powerondelay": 1000, "shutdowndelay": 2000,
                "backlightdelay": 1000, "deadbandatrest_idx": 25, "deadbandatrest_idy": 25,
                "deadbandatrest_idz": 25, "deadbandatrest_idt": 25, "deadbandtranslation_idx": 0,
                "deadbandtranslation_idy": 0, "deadbandtranslation_idz": 0,
                "deadbandtranslation_idt": 0
            }
        }
        return config


class UPNPHTTPServerBase(HTTPServer):
    """
    A simple HTTP server that knows the information about a UPnP device.
    """

    def __init__(self, server_address, request_handler_class, description):
        HTTPServer.__init__(self, server_address, request_handler_class)
        self.port = server_address[1]
        self.description = description


class UPNPHTTPServer(threading.Thread):
    """
    A thread that runs UPNPHTTPServerBase.
    """

    def __init__(self, server_address, description):
        """

        :param server_address: (ip_address, port)
        :param description: (text to be sent back on the description_url
        """
        threading.Thread.__init__(self, daemon=True)
        self.server = UPNPHTTPServerBase(server_address, UPNPHTTPServerHandler, description)

    @property
    def address(self):
        return self.server.server_address

    @property
    def baseurl(self):
        return 'http://{}:{}'.format(*self.address)

    @property
    def description_url(self):
        return '/'.join([self.baseurl, 'description.xml'])

    def run(self):
        self.server.serve_forever()
