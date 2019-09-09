import socket, _thread, pyonefs, ecdsa, json, math, ssl

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

verifier_cert = 'verify.pem'

class Manager(pyonefs.FsChangeListener):
    def __init__(self, serve = True, port = DEFAULT_PORT, adr = '0.0.0.0', certfile = 'certs/cert_01.crt', keyfile = 'certs/key_01.key'):
        self.peers = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS)
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        context.load_verify_locations(cafile=verifier_cert)
        self.context = context

        if serve:
            sok = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sok.bind((adr, port))
            sok.listen(5)
            _thread.start_new_thread(self.__server__, (sok,))
        self.fs_changes = []
        self.new_files = []
        self.port = port
    def addPeer(self, socket):
        socket.setblocking(False)
        self.peers.append(Peer(socket, self))
    def connectPeer(self, ip):
        sok = self.context.wrap_socket(socket.socket(socket.AF_INET, socket.SOCK_STREAM), server_side = False)
        try:
            sok.connect((ip, self.port))
        except BlockingIOError:
            pass
        sok.setblocking(False)
        #print("SSL established. Peer: {}".format(sok.getpeercert()))
        self.addPeer(sok)
    def sync(self):
        for i in self.peers:
            i.sync()
    def __server__(self, sok):
        while True:
            con, adr = sok.accept()
            print("Incoming connection from", adr)
            self.addPeer(self.context.wrap_socket(con, server_side = True))
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
        self.inbuffer = b''
        self.current_command = -1
        self.state = 0
        self.state_val = None
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
        try:
            tmp = self.sok.recv(8192)

            # tmp will be empty if the socket was closed by the remote
            if tmp==b'':
                raise Exception("Peer Disconnected")
            self.inbuffer+=tmp
        except BlockingIOError:
            return # if there's no new data then just leave the function
        
        cmd = self.current_command
        # breaks when it needs more data to parse
        while True:
            if self.state==0:
                # reading new command byte
                # for now I will not support authentication
                self.current_command = cmd = self.inbuffer[0] & 255

                self.state = 1
                self.inbuffer = self.inbuffer[1:]
            elif self.state==1:
                if cmd==COMMAND_PUSH_FS_CHANGE:
                    if len(self.inbuffer)<2:
                        break
                    # store size of packet content in state_val
                    self.state_val = int.from_bytes(self.inbuffer[:2], 'little')
                    self.inbuffer=self.inbuffer[2:]
                self.state = 2
            elif self.state==2:
                if cmd==COMMAND_PUSH_FS_CHANGE:
                    # make sure more can be loaded
                    if len(self.inbuffer)<self.state_val:
                        break
                    ident, data, epath = json.loads(self.inbuffer[:self.state_val])
                    self.inbuffer = self.inbuffer[self.state_val:]
                    self.man.fs.try_create_entry(ident, data)
                    self.state_val = [epath, -1]
                self.state = 3
            elif self.state==3:
                if cmd==COMMAND_PUSH_FS_CHANGE:
                    # 4 bytes to encode length of file
                    if len(self.inbuffer)<4:
                        break
                    self.state_val[1] = int.from_bytes(self.inbuffer[:4], 'little')
                    self.inbuffer = self.inbuffer[4:]
                self.state = 4
            elif self.state==4:
                
'''
class PeerCommand:
    def __init__(self, command, data, keypair=None):
        data = bytes([command])+data
        self.isSigned = keypair!=None
        if keypair==None:
            self.data = len(data).to_bytes(4, 'little') + data
        else:
            self.data = keypair.sign(data) + len(data).to_bytes(4, 'little') + data'''
