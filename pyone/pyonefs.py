import os, json, random

class PyOneFile:
    def __init__(self, fs, ident, loc, mode, ext):
        self.fs = fs
        self.id = ident
        self.fn = loc
        self.f = open(loc, mode)
        self.ext = ext
        self.mode = mode
    def write(self, data):
        self.f.write(data)
    def read(self, n=-1):
        return self.f.read(n)
    def flush(self):
        if not self.mode[0] in ['w', 'a']:
            raise Exception("Not opened for writing!")
        self.f.flush()
        self.fs.files[self.id[0]][self.id[1]] = self.ext
        self.fs.flush()
    def close(self):
        if self.mode[0] in ['w', 'a']:
            self.flush()
            for i in self.fs.listeners:
                i.onFileWritten(self.fs, self.loc)
        self.f.close()
        return self.id

class PyOneFS:
    def __init__(self, location, create_if_not_exist=True):
        self.loc = location
        self.corepath = os.path.join(location, 'fsdat.json')
        if not os.path.isfile(self.corepath):
            if create_if_not_exist:
                os.makedirs(location, exist_ok=True)
                self.files = {}
                self.flush()
            else:
                raise Exception("Filesystem not found.")
        else:
            with open(self.corepath) as f:
                self.files = json.load(f)
        self.listeners = []
    def flush(self):
        with open(self.corepath, 'w') as f:
            json.dump(self.files, f)

        # tell listeners that the FS metadata was pushed to the disk
        for i in self.listeners:
            i.onFlush(self)
    def wr_entry(self, name, data):
        '''returns the UID for the entry, does not flush the filesystem.'''
        vec = hex(random.randint(0,0x10000000))[2:]
        ident = [name, vec]
        if name in self.files.keys():
            while vec in self.files[name].keys():
                vec = hex(random.randint(0,0x10000000))[2:]
            self.files[name][vec] = data
        else:
            self.files[name] = {vec:data}

        # push data to listeners
        if data!=None:
            for i in self.listeners:
                i.onEntryCreate(self, ident, data)
                
        return ident
    def get_entry(self, name):
        if type(name)==list:
            name = name[0]+':'+str(name[1])
        i=name.rfind(':')
        if i!=-1:
            path = name[:i]
            ident = [path, name[i+1:]]
            if not path in self.files.keys():
                raise Exception("Path not found: no files match the name "+path)
            if not ident[1] in self.files[path].keys():
                raise Exception("Path not found: no files match the id "+ident[1])
        else:
            if not name in self.files.keys():
                raise Exception("Path not found: no files match the name "+name)
            if len(self.files[name].keys())!=1:
                raise Exception("Too many paths match "+name)
            ident = [name, list(self.files[name].keys()).pop()]
        return ident
    '''def mkdir(self, dirname):
        # directories have a dict in their entries
        ident = self.wr_entry(dirname, {})
        return ident'''
    def localPathOf(self, ident):
        name = ident[0]
        ext = name[name.rfind('.'):]
        return os.path.join(self.loc, ident[1]+'_'+ident[0][:3].replace('/', '_')+ext)
    def open(self, name, mode = 'r'):
        if mode[0]=='w':
            ident = self.wr_entry(name, None)
        elif mode[0]=='r':
            ident = self.get_entry(name)
        else:
            raise ValueError("Unsupported mode: "+mode)

        ext = ident[0][ident[0].rfind('.'):]
        
        return PyOneFile(self, ident, self.localPathOf(ident), mode, ext)
    def ls(self):
        return list(self.files.keys())
    def lsentries(self, name):
        out = []
        if not name in self.files.keys():
            return out
        for i in self.files[name].keys():
            out.append(name+':'+i)
        return out
    def addFsChangeListener(self, lis):
        self.listeners.append(lis)
class FsChangeListener:
    def __init__(self):
        pass
    def onFlush(self, fs):
        pass
    def onEntryCreate(self, fs, ident, data):
        pass
    def onFileWritten(self, fs, location):
        pass
