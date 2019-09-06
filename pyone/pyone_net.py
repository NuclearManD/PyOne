import socket, _thread

DEFAULT_PORT = 1152

class Manager:
    def __init__(self, serve = True, port = DEFAULT_PORT, adr = '0.0.0.0'):
        self.peers = []
        if serve:
            sok = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sok.bind((adr, port))
            _thread.start_new_thread(self.__server__, (sok,))
    def addPeer(self, socket):
        self.peers.append(Peer(socket, self))
    def sync(self):
        for i in self.peers:
            i.sync()
    def __server__(self, sok):
        while True:
            con, adr = sok.accept()
            print("Incoming connection from", adr)
            self.addPeer(con)
class Peer:
    def __init__(self, socket, manager):
        self.sok = socket
        self.man = manager
        self.live = True
    def sync(self):
        pass
