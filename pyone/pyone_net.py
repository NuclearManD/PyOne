import socket, _thread, pyonefs, ecdsa, json, math

COMMAND_SIGNED_FLAG = 128

COMMAND_PUSH_FS_CHANGE = 0

DEFAULT_PORT = 1152

class KeyPair:
    def __init__(self, prikey=None):
        if prikey==None:
            self.sk = ecdsa.SigningKey.generate(curve=ecdsa.SECP256k1)
        else:
            self.sk = ecdsa.SigningKey.from_string(prikey, curve=ecdsa.SECP256k1)
    def serialize(self):
        return self.sk.to_string()
    def sign(self, data):
        return self.sk.get_verifying_key().to_string() + self.sk.sign(data)

def testSignedMessage(msg):
    'returns (verified:bool, public key:bytes)'
    if len(msg)<132:
        return False, None
    data = msg[132:132+int.from_bytes(msg[128:132], 'little')]
    vk = ecdsa.VerifyingKey.from_string(msg[:64], curve=ecdsa.SECP256k1)
    return vk.verify(msg[64:128], data), msg[:64]
    

class Manager(pyonefs.FsChangeListener):
    def __init__(self, serve = True, port = DEFAULT_PORT, adr = '0.0.0.0'):
        self.peers = []
        if serve:
            sok = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sok.bind((adr, port))
            _thread.start_new_thread(self.__server__, (sok,))
        self.fs_changes = []
        self.new_files = []
        self.port = port
    def addPeer(self, socket):
        self.peers.append(Peer(socket, self))
    def connectPeer(self, ip):
        sok = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sok.connect((ip, self.port))
        self.addPeer(sok)
    def sync(self):
        for i in self.peers:
            i.sync()
    def __server__(self, sok):
        while True:
            con, adr = sok.accept()
            print("Incoming connection from", adr)
            self.addPeer(con)
    def onFlush(self, fs):
        pass
    def onEntryCreate(self, fs, ident, data):
        self.fs_changes.append([ident, data])
        for i in self.new_files:
            if i[0]==ident:
                self.push_fs_change_to_peers(ident)
                return
    def onFileWritten(self, fs, ident, location):
        self.new_files.append([ident, location])
        for i in self.fs_changes:
            if i[0]==ident:
                self.push_fs_change_to_peers(ident)
                return
    def push_fs_changes_to_peers(self,ident):
        filechange_idx = -1
        fschange_idx = -1
        for i in range(len(self.fs_changes)):
            if self.fs_changes[i][0]==ident:
                fschange_idx = i
                break
        for i in range(len(self.new_files)):
            if self.new_files[i][0]==ident:
                filechange_idx = i

        fn = self.new_files[filechange_idx]
        idx = fn.rfind('/')
        epath = fn[idx+1:]
        for i in self.peers:
            i.pushFsChange(ident, self.fs_changes[fschange_idx], fn, epath)
class Peer:
    def __init__(self, socket, manager):
        self.sok = socket
        self.man = manager
        self.live = True
    def sync(self):
        pass
    def pushFsChange(self, ident, data, fn, epath):
        with open(fn, 'rb') as f:
            # get file size
            f.seek(0,2)
            f_size = f.tell()
            
            # go back to the beginning
            f.seek(0)

            # generate JSON header
            packet_content = json.dumps([ident, data, epath])

            # send command and header data
            self.sok.send(bytes([COMMAND_PUSH_FS_CHANGE])+len(packet_content).to_bytes(2, 'little')+packet_content.encode())

            # send file data
            self.sok.send(f_size.to_bytes(4, 'little'))
            for i in range(math.ceil(f_size/2048)):
                self.sok.send(f.read(2048))
    def update(self):
        
'''
class PeerCommand:
    def __init__(self, command, data, keypair=None):
        data = bytes([command])+data
        self.isSigned = keypair!=None
        if keypair==None:
            self.data = len(data).to_bytes(4, 'little') + data
        else:
            self.data = keypair.sign(data) + len(data).to_bytes(4, 'little') + data'''
