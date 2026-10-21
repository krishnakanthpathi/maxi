"""Dependency-free local WebSocket peer for the native HUD recovery checks."""
import base64
import hashlib
import json
import socketserver
import struct
import sys
import threading


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    connections = 0
    lock = threading.Lock()


class Peer(socketserver.StreamRequestHandler):
    def frame(self, opcode, data=b''):
        self.wfile.write(bytes([0x80 | opcode, len(data)]) + data)
        self.wfile.flush()

    def handle(self):
        request = self.rfile.readline().decode().split()
        if len(request) < 2:
            return
        headers = {}
        while line := self.rfile.readline().decode().strip():
            key, value = line.split(':', 1)
            headers[key.lower()] = value.strip()
        if request[1] != '/ws':
            data = json.dumps({'connections': self.server.connections}).encode()
            self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: ' + str(len(data)).encode() + b'\r\n\r\n' + data)
            return
        with self.server.lock:
            self.server.connections += 1
            number = self.server.connections
        accept = base64.b64encode(hashlib.sha1((headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
        self.wfile.write(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
        self.wfile.flush()
        if sys.argv[1] == 'drop-once' and number == 1:
            return
        if sys.argv[1] != 'hang-once' or number > 1:
            # Omit voice_start, as if the client reconnected during a recording.
            self.frame(1, json.dumps({'event': 'audio_level', 'levels': [0.3] * 5, 'elapsed': number, 'locked': False}).encode())
        try:
            while header := self.rfile.read(2):
                if len(header) < 2:
                    return
                opcode = header[0] & 0x0F
                length = header[1] & 0x7F
                if length == 126:
                    length = struct.unpack('!H', self.rfile.read(2))[0]
                elif length == 127:
                    length = struct.unpack('!Q', self.rfile.read(8))[0]
                mask = self.rfile.read(4) if header[1] & 0x80 else None
                data = self.rfile.read(length)
                if mask:
                    data = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
                if opcode == 8:
                    self.frame(8, data)
                    return
                if opcode == 9 and (sys.argv[1] != 'hang-once' or number > 1):
                    self.frame(10, data)
        except (ConnectionError, OSError):
            pass


with Server(('127.0.0.1', 0), Peer) as server:
    print(server.server_address[1], flush=True)
    server.serve_forever()
