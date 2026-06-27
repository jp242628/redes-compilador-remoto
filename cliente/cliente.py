import socket
import base64
import hashlib
import os
from enum import Enum, auto

# Mapeamento dos Estados do Cliente (Ref: Seção 5.4 e 6.1 do README)
class ClientState(Enum):
    IDLE = auto()
    CONNECTING = auto()
    HANDSHAKING = auto()
    IDLE_SESSION = auto()
    SENDING = auto()
    AWAITING_RESULT = auto()
    RECEIVING = auto()
    CLOSING = auto()
    DONE = auto()
    ERROR = auto()

class RCPClient:
    def __init__(self, host='127.0.0.1', port=5000):
        self.host = host
        self.port = port
        self.state = ClientState.IDLE
        self.sock = None
        self.buffer = b""

    def read_line(self):
        """Lê do socket até encontrar a quebra de linha do protocolo (\\r\\n)"""
        while b"\r\n" not in self.buffer:
            try:
                data = self.sock.recv(4096)
                if not data:
                    return None
                self.buffer += data
            except (ConnectionResetError, ConnectionAbortedError):
                return None

        line, self.buffer = self.buffer.split(b"\r\n", 1)
        return line.decode('utf-8')

    def send_cmd(self, command):
        """Formata e envia um comando de texto com \\r\\n"""
        msg = f"{command}\r\n".encode('utf-8')
        self.sock.sendall(msg)

    def preparar_arquivo(self, caminho_arquivo):
        """Lê o arquivo, calcula MD5 e converte para Base64"""
        with open(caminho_arquivo, 'rb') as f:
            conteudo_bruto = f.read()

        tamanho = len(conteudo_bruto)
        checksum = hashlib.md5(conteudo_bruto).hexdigest()
        conteudo_b64 = base64.b64encode(conteudo_bruto).decode('utf-8')
        
        return tamanho, checksum, conteudo_b64

    def iniciar_sessao(self, caminho_arquivo, lang="c"):
        """Máquina de estados principal do cliente"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        try:
            # Estado: CONNECTING
            self.state = ClientState.CONNECTING
            print(f"[CONNECTING] Conectando a {self.host}:{self.port}...")
            self.sock.connect((self.host, self.port))
            
            # Estado: HANDSHAKING
            self.state = ClientState.HANDSHAKING
            self.send_cmd("HELLO version=1")
            
            resposta = self.read_line()
            if not resposta or not resposta.startswith("WELCOME"):
                print(f"[ERROR] Falha no Handshake: {resposta}")
                self.state = ClientState.ERROR
                return

            print(f"[HANDSHAKING] Servidor aceitou: {resposta}")
            
            # Estado: IDLE_SESSION (Sessão pronta)
            self.state = ClientState.IDLE_SESSION
            nome_arquivo = os.path.basename(caminho_arquivo)
            tamanho, checksum, corpo_b64 = self.preparar_arquivo(caminho_arquivo)
            
            # Estado: SENDING
            self.state = ClientState.SENDING
            print(f"[SENDING] Enviando {nome_arquivo} (MD5: {checksum})...")
            cmd_send = f"SEND lang={lang} size={tamanho} filename={nome_arquivo} checksum={checksum}"
            self.send_cmd(cmd_send)
            self.send_cmd(corpo_b64)
            self.send_cmd(".") # Fim do corpo
            
            # Aguardando confirmação de recebimento (READY)
            resposta = self.read_line()
            if resposta == "READY":
                print("[VERIFYING] Servidor validou o arquivo com sucesso.")
                self.state = ClientState.AWAITING_RESULT
            else:
                print(f"[ERROR] Esperava READY, recebeu: {resposta}")
                self.state = ClientState.ERROR
                return

            # Estado: AWAITING_RESULT e RECEIVING
            while self.state == ClientState.AWAITING_RESULT:
                linha = self.read_line()
                
                if linha == "COMPILING":
                    print("[COMPILING] Servidor está compilando o código...")
                    continue
                
                if linha.startswith("SUCCESS"):
                    print(f"[SUCCESS] Compilação concluída! Cabeçalho: {linha}")
                    self.state = ClientState.RECEIVING
                    self._receber_resultado_base64("saida.exe")
                    
                elif linha.startswith("FAILURE"):
                    print(f"[FAILURE] Erro de compilação! Cabeçalho: {linha}")
                    self.state = ClientState.RECEIVING
                    self._receber_resultado_texto()
                
                elif linha.startswith("ERROR"):
                    print(f"[ERROR] Servidor retornou erro: {linha}")
                    self.state = ClientState.ERROR
                    return

            # Estado: CLOSING
            if self.state not in (ClientState.ERROR, ClientState.DONE):
                self.state = ClientState.CLOSING
                self.send_cmd("BYE")
                resposta = self.read_line()
                if resposta == "BYE":
                    self.state = ClientState.DONE
                    print("[DONE] Sessão encerrada de forma graciosa.")

        except Exception as e:
            print(f"[ERROR] Ocorreu uma exceção: {e}")
            self.state = ClientState.ERROR
        finally:
            self.sock.close()

    def _receber_resultado_base64(self, nome_saida):
        """Recebe o binário em Base64, decodifica e salva no disco"""
        b64_data = ""
        while True:
            linha = self.read_line()
            if linha == ".":
                break
            b64_data += linha
            
        dados_binarios = base64.b64decode(b64_data)
        with open(nome_saida, 'wb') as f:
            f.write(dados_binarios)
        print(f"[RECEIVING] Arquivo salvo com sucesso como '{nome_saida}'")

    def _receber_resultado_texto(self):
        """Recebe o log de erros em texto puro e imprime no terminal"""
        print("\n--- LOG DE ERROS DO COMPILADOR ---")
        while True:
            linha = self.read_line()
            if linha == ".":
                break
            print(linha)
        print("----------------------------------\n")


if __name__ == "__main__":
    cliente = RCPClient()
    
    # Testando com o seu arquivo C
    if os.path.exists("teste.c"):
        cliente.iniciar_sessao("teste.c", lang="c")
    else:
        print("Arquivo 'teste.c' não encontrado no diretório.")