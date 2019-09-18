import socket, _thread, ecdsa, json, math, ssl, os, time
from . import pyonefs
COMMAND_SIGNED_FLAG = 128

COMMAND_PUSH_FS_CHANGE = 0
COMMAND_GET_FS_JSON = 1
COMMAND_RETURN_FS_JSON = 2
COMMAND_GET_FILE = 3

cmd_strs = {
    -1:'IDLE',
    0:'COMMAND_PUSH_FS_CHANGE',
    1:'COMMAND_GET_FS_JSON',
    2:'COMMAND_RETURN_FS_JSON',
    3:'COMMAND_GET_FILE'
}

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
    def __init__(self, fs, serve = True, port = DEFAULT_PORT, adr = '0.0.0.0', certfile = 'certs/cert_01.crt', keyfile = 'certs/key_01.key'):
        self.peers = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS)
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        context.load_verify_locations(cafile=verifier_cert)
        self.context = context
        self.fs = fs
        fs.addFsChangeListener(self)

        if serve:
            sok = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sok.bind((adr, port))
            sok.listen(5)
            _thread.start_new_thread(self.__server__, (sok,))
        _thread.start_new_thread(self.__peerupdate__, ())
        self.fs_changes = []
        self.new_files = []
        self.port = port
    def addPeer(self, socket):
        socket.setblocking(0)
        peer = Peer(socket, self)
        self.peers.append(peer)
    def connectPeer(self, ip):
        sok = self.context.wrap_socket(socket.socket(socket.AF_INET, socket.SOCK_STREAM), server_side = False)
        try:
            sok.connect((ip, self.port))
        except BlockingIOError:
            pass
        sok.setblocking(0)
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
    def __peerupdate__(self):
        while True:
            to_rm = []
            for i in self.peers:
                try:
                    i.update()
                except ssl.SSLError:
                    to_rm.append(i)
            for i in to_rm:
                self.peers.remove(i)
            time.sleep(.01)
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
    def push_fs_change_to_peers(self,ident):
        print("Pushing", ident)
        filechange_idx = -1
        fschange_idx = -1
        for i in range(len(self.fs_changes)):
            if self.fs_changes[i][0]==ident:
                fschange_idx = i
                break
        for i in range(len(self.new_files)):
            if self.new_files[i][0]==ident:
                filechange_idx = i
        self.new_files.pop(filechange_idx)
        self.fs_changes.pop(fschange_idx)
        for i in self.peers:
            i.pushFsChange(ident)
class Peer:
    def __init__(self, socket, manager):
        self.sok = socket
        self.man = manager
        self.live = True
        self.inbuffer = b''
        self.current_command = -1
        self.state = 0
        self.state_val = None
        self.isSynced = False
    def __send_file__(self, filepath):
        with open(filepath, 'rb') as f:
            # get file size
            f.seek(0,2)
            f_size = f.tell()
            
            # go back to the beginning
            f.seek(0)

            # send file data in 2048 byte chunks to avoid wasting memory
            self.sok.sendall(f_size.to_bytes(4, 'little'))
            for i in range(math.ceil(f_size/2048)):
                self.sok.sendall(f.read(2048))
    def sync(self):
        # this command initiates the synchronization process.
        self.sok.sendall(bytes([COMMAND_GET_FS_JSON]))
        # the peer will send back their filesystem JSON, which we can compare to our own filesystem.
        # This comparison allows us to know what entries need to be created and files downloaded.
        # The first step is asking for the remote filesystem JSON.
        self.isSynced = True
    def pushFsChange(self, ident):
        fn = self.man.fs.localPathOf(ident)
        idx = fn.rfind('/')
        epath = fn[idx+1:]
        data = self.man.fs.files[ident[0]][ident[1]]
        with open(fn, 'rb') as f:
            # get file size
            f.seek(0,2)
            f_size = f.tell()
            
            # go back to the beginning
            f.seek(0)

            # generate JSON header
            packet_content = json.dumps([ident, data, epath])

            # send command and header data
            self.sok.sendall(bytes([COMMAND_PUSH_FS_CHANGE])+len(packet_content).to_bytes(2, 'little')+packet_content.encode())

            # send file data in 2048 byte chunks to avoid wasting memory
            self.sok.sendall(f_size.to_bytes(4, 'little'))
            for i in range(math.ceil(f_size/2048)):
                self.sok.sendall(f.read(2048))
    def sendFsJson(self):
        # send command
        self.sok.sendall(bytes([COMMAND_RETURN_FS_JSON]))
        # we want to send only what has been flushed to the disk
        self.__send_file__(self.man.fs.corepath)
    def requestFileFromIdent(self, ident):
        packet_content = json.dumps(ident)
        self.sok.sendall(bytes([COMMAND_GET_FILE])+len(packet_content).to_bytes(2, 'little')+packet_content.encode())
        
    def update(self):
        try:
            tmp = self.sok.recv(8192)

            # tmp will be empty if the socket was closed by the remote
            if tmp==b'':
                raise Exception("Peer Disconnected")
            self.inbuffer+=tmp
        except (BlockingIOError, ssl.SSLError):
            return # if there's no new data then just leave the function

        if not self.isSynced:
            self.sync()
        
        cmd = self.current_command
        # breaks when it needs more data to parse
        while True:
            #print('{   '+repr(self)+' '+str(self.state)+' '+cmd_strs[cmd]+'\n')
            if self.state==0:
                if len(self.inbuffer)==0:
                    self.state = 0
                    break
                # reading new command byte
                # for now I will not support authentication
                self.current_command = cmd = self.inbuffer[0] & 255

                self.state = 1
                self.inbuffer = self.inbuffer[1:]
            elif self.state==1:
                self.state = 2
                if cmd==COMMAND_PUSH_FS_CHANGE or cmd==COMMAND_GET_FILE:
                    if len(self.inbuffer)<2:
                        self.state = 1
                        break
                    # store size of packet content in state_val
                    self.state_val = int.from_bytes(self.inbuffer[:2], 'little')
                    self.inbuffer=self.inbuffer[2:]
                elif cmd==COMMAND_GET_FS_JSON:
                    self.sendFsJson()

                    # now return to state zero
                    self.state = 0
                elif cmd==COMMAND_RETURN_FS_JSON:
                    # got the new JSON, need to read 4-byte file length
                    if len(self.inbuffer)<4:
                        self.state = 1
                        break
                    self.state_val = int.from_bytes(self.inbuffer[:4], 'little')
                    self.inbuffer=self.inbuffer[4:]
                    
                    # INSERT HONEYPOT FOR MEMORY ATTACK HERE
                    #     Essentially, someone could claim their JSON is 4GB in size, and send 4GB of data.
                    #     Doing this would waste 4GB of RAM, which is not trivial.  A honeypot could be created
                    #     here to protect the machine running this software and attack the attacker.
                    
                    # INSERT HONEYPOT FOR CPU USAGE ATTACK HERE
                    #     An attacker could send large, valid JSON filesystems in quick succession.  These need
                    #     to be compared, which requires a large CPU overhead.  The quick succession could result
                    #     in the Python script using all or almost all of it's available computing power,
                    #     basically a denial of service attack.

            elif self.state==2:
                self.state = 3
                if cmd==COMMAND_PUSH_FS_CHANGE:
                    # make sure more can be loaded
                    if len(self.inbuffer)<self.state_val:
                        self.state = 2
                        break
                    ident, data, epath = json.loads(self.inbuffer[:self.state_val])
                    self.inbuffer = self.inbuffer[self.state_val:]
                    self.man.fs.try_create_entry(ident, data)
                    q=None
                    loc = os.path.join(self.man.fs.loc, epath)
                    if not os.path.isfile(loc):
                        q = open(loc, 'wb')
                    self.state_val = [q, -1]
                elif cmd==COMMAND_GET_FILE:
                    ident = json.loads(self.inbuffer[:self.state_val])
                    self.inbuffer = self.inbuffer[self.state_val:]

                    print("Sending", ident, 'to peer as requested')
                    # this will send the peer all the data it needs
                    self.pushFsChange(ident)

                    # now return to state zero
                    self.state = 0
                elif cmd==COMMAND_RETURN_FS_JSON:
                    # load the entire JSON in the buffer first
                    if len(self.inbuffer)<self.state_val:
                        self.state = 2
                        break
                    fs_data = json.loads(self.inbuffer[:self.state_val])
                    self.inbuffer = self.inbuffer[self.state_val:]

                    # now we have the FS data, time to compare.
                    for k, v in fs_data.items():
                        print("[sync] checking ",k)
                        if k in self.man.fs.files.keys():
                            # the key is there; are there new file versions though?
                            for val in v.keys():
                                if not val in self.man.fs.files[i].keys():
                                    # a new entry
                                    ident = [k, val]
                                    self.requestFileFromIdent(ident)
                                    print('[sync] requesting',ident)
                        else:
                            # a new key entirely!
                            for val in v.keys():
                                ident = [k, val]
                                self.requestFileFromIdent(ident)
                                print('[sync] requesting',ident)

                    # now return to state zero
                    self.state = 0
            elif self.state==3:
                self.state = 4
                if cmd==COMMAND_PUSH_FS_CHANGE:
                    # 4 bytes to encode length of file
                    if len(self.inbuffer)<4:
                        self.state = 3
                        break
                    self.state_val[1] = int.from_bytes(self.inbuffer[:4], 'little')
                    self.inbuffer = self.inbuffer[4:]
            elif self.state==4:
                if cmd==COMMAND_PUSH_FS_CHANGE:
                    f = self.state_val[0]
                    if len(self.inbuffer)>self.state_val[1]:
                        next_data = self.inbuffer[:self.state_val[1]]
                        self.inbuffer = self.inbuffer[self.state_val[1]:]
                    else:
                        next_data = self.inbuffer
                        self.inbuffer = b''
                    if f!=None:
                        f.write(next_data)
                    if len(next_data)==self.state_val[1]:
                        self.state = 0  # all data is read, more may be in buffer.
                        f.close()
                        self.man.fs.flush()
                    else:
                        self.state = 4  # more to read; break & wait for more data to be available
                        self.state_val[1]-=len(next_data)
                        self.state = 4
                        break
            #print(repr(self)+' '+str(self.state)+' '+cmd_strs[cmd]+'  }\n')

if __name__=='__main__':                      
    fs = pyonefs.PyOneFS('./fs')
    man = Manager(fs)
