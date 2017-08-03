
# @TODO instead of using threading, replace with aiohttp!
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading


class UPNPHTTPServerHandler(BaseHTTPRequestHandler):
    """
    A HTTP handler that serves the UPnP XML files.
    """

    # Handler for the GET requests
    def do_GET(self):
        print("sending description:", self.server.description)
        self.send_response(200)
        self.send_header('Content-type', 'application/xml')
        self.end_headers()
        self.wfile.write(self.server.description.encode())
        return


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
