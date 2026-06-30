import socket
import base64
import hashlib
import sys
import os
from enum import Enum, auto

# ==========================
# Estados da máquina de estados
# ==========================

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


# ==========================
# Cliente RemoteCC
# ==========================

class RCPClient:
    def __init__(self, host='127.0.0.1', port=5000):
        self.host = host
        self.port = port
        self.state = ClientState.IDLE
        self.sock = None
        self.buffer = b""

    # ==========================
    # Comunicação com o servidor
    # ==========================

    def read_line(self):
        """Lê dados até encontrar \\r\\n"""
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
        """Envia um comando do protocolo"""
        msg = f"{command}\r\n".encode('utf-8')
        self.sock.sendall(msg)

    # ==========================
    # Preparação do arquivo
    # ==========================

    def preparar_arquivo(self, caminho_arquivo):
        """Calcula tamanho, MD5 e Base64"""
        with open(caminho_arquivo, 'rb') as f:
            conteudo_bruto = f.read()

        tamanho = len(conteudo_bruto)
        checksum = hashlib.md5(conteudo_bruto).hexdigest()
        conteudo_b64 = base64.b64encode(conteudo_bruto).decode('utf-8')

        return tamanho, checksum, conteudo_b64

    # ==========================
    # Máquina de estados principal
    # ==========================

    def iniciar_sessao(self, caminho_arquivo, lang="c", flags=""):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            # CONNECTING
            self.state = ClientState.CONNECTING
            print(f"[CONNECTING] Conectando a {self.host}:{self.port}...")
            self.sock.connect((self.host, self.port))

            # HANDSHAKING
            self.state = ClientState.HANDSHAKING
            self.send_cmd("HELLO version=1")

            resposta = self.read_line()

            if not resposta or not resposta.startswith("WELCOME"):
                print(f"[ERROR] Falha no Handshake: {resposta}")
                self.state = ClientState.ERROR
                return

            print(f"[HANDSHAKING] Servidor aceitou: {resposta}")

            # IDLE_SESSION
            self.state = ClientState.IDLE_SESSION

            if flags:
                print(f"[IDLE_SESSION] Enviando flags: {flags}")
                self.send_cmd(f"OPTS flags={flags}")

            nome_arquivo = os.path.basename(caminho_arquivo)
            tamanho, checksum, corpo_b64 = self.preparar_arquivo(caminho_arquivo)

            # SENDING
            self.state = ClientState.SENDING

            print(f"[SENDING] Enviando {nome_arquivo} (MD5: {checksum})...")

            cmd_send = (
                f"SEND lang={lang} "
                f"size={tamanho} "
                f"filename={nome_arquivo} "
                f"checksum={checksum}"
            )

            self.send_cmd(cmd_send)
            self.send_cmd(corpo_b64)
            self.send_cmd(".")

            resposta = self.read_line()

            if resposta == "READY":
                print("[VERIFYING] Servidor validou o arquivo.")
                self.state = ClientState.AWAITING_RESULT
            else:
                print(f"[ERROR] Esperava READY, recebeu: {resposta}")
                self.state = ClientState.ERROR
                return

            while self.state == ClientState.AWAITING_RESULT:
                linha = self.read_line()

                if linha == "COMPILING":
                    print("[COMPILING] Servidor compilando...")
                    continue

                if linha.startswith("SUCCESS"):
                    print(f"[SUCCESS] Compilação concluída.")
                    self.state = ClientState.RECEIVING

                    diretorio_origem = os.path.dirname(caminho_arquivo)
                    nome_original = os.path.basename(caminho_arquivo)
                    nome_saida = nome_original.replace(".c", ".out")

                    self._receber_resultado_base64(
                        nome_saida,
                        diretorio_origem
                    )

                elif linha.startswith("FAILURE"):
                    print(f"[FAILURE] Erro de compilação.")
                    self.state = ClientState.RECEIVING
                    self._receber_resultado_texto()

                elif linha.startswith("ERROR"):
                    print(f"[ERROR] Servidor retornou: {linha}")
                    self.state = ClientState.ERROR
                    return

            # CLOSING
            if self.state not in (ClientState.ERROR, ClientState.DONE):
                self.state = ClientState.CLOSING

                self.send_cmd("BYE")

                resposta = self.read_line()

                if resposta == "BYE":
                    self.state = ClientState.DONE
                    print("[DONE] Sessão encerrada.")

        except Exception as e:
            print(f"[ERROR] Ocorreu uma exceção: {e}")
            self.state = ClientState.ERROR

        finally:
            self.sock.close()

    # ==========================
    # Recebimento do executável
    # ==========================

    def _receber_resultado_base64(self, nome_saida, diretorio_destino):
        """Recebe e salva o executável"""

        b64_data = ""

        while True:
            linha = self.read_line()

            if linha == ".":
                break

            b64_data += linha

        dados_binarios = base64.b64decode(b64_data)

        caminho_completo = os.path.join(
            diretorio_destino,
            nome_saida
        )

        with open(caminho_completo, 'wb') as f:
            f.write(dados_binarios)

        print(
            f"[RECEIVING] Arquivo salvo como "
            f"'{caminho_completo}'"
        )

    # ==========================
    # Recebimento do log de erros
    # ==========================

    def _receber_resultado_texto(self):
        """Exibe erros de compilação"""

        print("\n--- LOG DE ERROS DO COMPILADOR ---")

        while True:
            linha = self.read_line()

            if linha == ".":
                break

            print(linha)

        print("----------------------------------\n")


# ==========================
# Programa principal
# ==========================

if __name__ == "__main__":

    print("=== RemoteCC - Cliente ===")

    caminho_arquivo = input(
        "Digite o caminho do arquivo .c: "
    ).strip()

    if not caminho_arquivo:
        print("Nenhum arquivo fornecido.")
        sys.exit(1)

    if not os.path.exists(caminho_arquivo):
        print(
            f"Erro: O arquivo '{caminho_arquivo}' "
            f"não foi encontrado."
        )
        sys.exit(1)

    print("\nFlags disponíveis:")
    print("0 - Sem flags")
    print("1 - -Wall")
    print("2 - -Wall -Wextra")
    print("3 - -O2")
    print("4 - -g")
    print("5 - Personalizada")

    opcao = input("\nEscolha uma opção: ").strip()

    flags_map = {
        "0": "",
        "1": "-Wall",
        "2": "-Wall -Wextra",
        "3": "-O2",
        "4": "-g"
    }

    if opcao == "5":
        flags_input = input(
            "Digite as flags desejadas: "
        ).strip()
    else:
        flags_input = flags_map.get(opcao, "")

    cliente = RCPClient()

    cliente.iniciar_sessao(
        caminho_arquivo,
        lang="c",
        flags=flags_input
    )
