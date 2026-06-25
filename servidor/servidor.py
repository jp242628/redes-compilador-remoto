import socket
import threading
import tempfile
import subprocess
import base64
import hashlib
from enum import Enum, auto

#Mapeamento dos estados do Servidor (Ref: Seção 5.5)
class ServerState(Enum):
    NEGOTIATING = auto()
    IDLE_SESSION = auto()
    RECEIVING_FILE = auto()
    VERIFYING = auto()
    COMPILING = auto()
    SENDING_RESULT = auto()
    CLOSING = auto()
    DONE = auto()
    ERROR = auto()

class RCPClientHandler(threading.Thread):
    def __init__(self, client_socket, client_address):
        super().__init__()
        self.sock = client_socket
        self.addr = client_address
        self.state = ServerState.NEGOTIATING
        self.buffer = b""
        self.flags = ""

    def read_line(self): 
        """Lê do socket até encontrar \\r\n"""
        while b"\r\n" not in self.buffer:
            data = self.sock.recv(4096)
            
            if not data:
                return None # Cliente desconectou
            
            self.buffer += data

        line, self.buffer = self.buffer.split(b"\r\n", 1)
        return line.decode('utf-8')
    
    def run(self):
        print(f"[ACCEPTING] Nova conxão de {self.addr}")

        try:
            while self.state not in (ServerState.DONE, ServerState.ERROR):
                line = self.read_line()
                if not line:
                    break # Conexão caiu

                self.proccess_command(line)
        except Exception as e:
            print(f"Erro na conexão {self.addr}: {e}")
            self.send_error(500, "internal_error")
        finally:
            self.sock.close()
            print(f"[DONE] Conexão encerrada com {self.addr}")

    def process_command(self, line):
        """Roteador de comandos baseado no estado atual"""
        parts = line.split(" ")
        command = parts[0].upper()
        params = dict(p.split("=") for p in parts[1:] if "=" in p)

        if self.state == ServerState.NEGOTIATING:
            if command == "HELLO":
                self.handle_hello(params)
            else:
                self.send_error(104, "invalid_message_order")
        
        elif self.state == ServerState.IDLE_SESSION:
            if command == "OPTS":
                self.flags = params.get("flags", "")
            elif command == "SEND":
                self.handle_send(params)
            elif command == "BYE":
                self.handle_bye()
            else:
                self.send_error(104, "invalid_message_order")

        # Continuar implementando os outros estados e comandos conforme necessário

    def handle_hello(self, params):
        version = params.get("version")
        if version == "1":
            self.sock.sendall(b"WELCOME version=1 server=remotecc-python\r\n")
            self.state = ServerState.IDLE_SESSION
        else:
            self.send_error(400, "unsupported_version")

    def handle_send(self, params):
        self.state = ServerState.RECEIVING_FILE
        pass

    def handle_bye(self):
        self.sock.sendall(b"BYE\r\n")
        self.state = ServerState.DONE

    def send_error(self, code, msg):
        response = f"ERROR code={code} msg={msg}\r\n"
        self.sock.sendall(response.encode('utf-8'))
        self.state = ServerState.ERROR

def start_server(host='0.0.0.0 ', port=5000):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    print(f"[STARTED] Servidor escutando em {host}:{port}")

    try:
        while True:
            client_socket, client_address = server_socket.accept()
            handler = RCPClientHandler(client_socket, client_address)
            handler.start()
    except KeyboardInterrupt:
        print("Desligando o servidor...")
    finally:
        server_socket.close()

if __name__ == "__main__":
    start_server()
