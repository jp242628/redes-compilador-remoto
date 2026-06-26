import socket
import threading
import tempfile
import subprocess
import base64
import hashlib
import os
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

                self.process_command(line)
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
        file_b64 = ""

        while True:
            line = self.read_line()
            if line is None:
                return # Cliente desconectou
            if line == ".":
                break

            file_b64 += line

        try:
            file_bytes = base64.b64decode(file_b64)
        except Exception:
            self.send_error(104, "invalid_base64")
            return

        # Verificação de integridade
        self.state = ServerState.VERIFYING
        client_checksum = params.get("checksum")
        server_checksum = hashlib.md5(file_bytes).hexdigest()

        if client_checksum != server_checksum:
            self.send_error(102, "checksum_mismatch")
            return

        self.sock.sendall(b"READY\r\n")

        # Iniciar compilação
        lang = params.get("lang", "c")
        if lang not in ("c", "cpp"):
            self.send_error(400, "unsupported_language")
            return
        
        self.compile_and_send(file_bytes, lang)

    def compile_and_send(self, file_bytes, lang):
        self.state = ServerState.COMPILING
        self.sock.sendall(b"COMPILING\r\n")

        suffix = ".c" if lang == "c" else ".cpp"
        compiler = "gcc" if lang == "c" else "g++"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as source_file:
            source_file.write(file_bytes)
            source_path = source_file.name

        out_path = source_path + ".out"

        cmd = [compiler, source_path, "-o", out_path]
        if self.flags:
            cmd.extend(self.flags.split()) # Adiciona as flags passadas no OPTS

        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self.state = ServerState.SENDING_RESULT

        if process.returncode == 0:
            # Sucesso na compilação
            with open(out_path, "rb") as f:
                bin_data = f.read()

            bin_b64 = base64.b64encode(bin_data).decode('utf-8')
            bin_md5 = hashlib.md5(bin_data).hexdigest()
            size = len(bin_data)

            header = f"SUCCESS size={size} checksum={bin_md5}\r\n"
            self.sock.sendall(header.encode('utf-8'))
            self.sock.sendall(bin_b64.encode('utf-8') + b"\r\n.\r\n")
        else:
            # Falha na compilação
            error_log = process.stderr.decode('utf-8')
            header = f"FAILURE code={process.returncode}\r\n"

            self.sock.sendall(header.encode('utf-8'))
            self.sock.sendall(error_log.encode('utf-8'))

            if not error_log.endswith("\r\n"):
                self.sock.sendall(b"\r\n")
            self.sock.sendall(b".\r\n")

        # Limpeza dos arquivos temporários
        os.remove(source_path)
        if os.path.exists(out_path):
            os.remove(out_path)

        self.state = ServerState.IDLE_SESSION

    def handle_bye(self):
        self.sock.sendall(b"BYE\r\n")
        self.state = ServerState.DONE

    def send_error(self, code, msg):
        response = f"ERROR code={code} msg={msg}\r\n"
        self.sock.sendall(response.encode('utf-8'))
        self.state = ServerState.ERROR

def start_server(host='0.0.0.0', port=5000):
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
