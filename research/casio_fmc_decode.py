#!/usr/bin/env python3
"""
Casio .fmc (fingering guide) decoder — NEAR-COMPLETE (range coder verified).

Container (VERIFIED by file-size math on multiple files):
    "casi"(4) + version(1) + type(1) + top(3 BE) + r_size(3 BE) + data(r_size)
    e.g. Birthday: 12-byte header + 15661 = 15673 = file size.

Pipeline (from libsssg.so decode() @0x73220, matches M.Hiroi bsrc1.py):
    range_decode(Freq012m, EOS=256) -> [rle_decode(n=7) if type!=0]
    -> mtf_decode -> inverse BWT(top)
    -> plaintext = 10-byte records [u64 LE time][u8 note][u8 finger 1..5]

STATUS:
  [VERIFIED] container framing, pipeline order, RangeCoder math (pyalgo36,
             MIN_RANGE=0x1000000), EOS=256 termination, inverse BWT.
  [PROGRESS] LIMIT1=0x140 (from get_frequency args) makes range_decode hit
             EOS=256 cleanly at a record-aligned length (Birthday: 38480 = 3848*10).
             mtf_decode + inverse BWT independently round-trip-verified.
  [GAP] the model's exact CONTEXT STRUCTURE still differs from the public
        reference (an extra get_frequency(?,0x140,4) context exists), so the
        mtf-decoded buffer is not yet the true BWT output. libsssg.so uses
        the MIXED method (mix_012_frequency / mix_first_frequency /
        select_second_frequency = Freq012m), with each context's (inc,limit)
        set by init_frequency_table. The public-reference Freq012m constants
        do not match bit-exactly, so the range decoder slowly desyncs and the
        post-BWT bytes are not yet valid records. Closing this needs the exact
        (inc,limit) per context from init_frequency / init_frequency_table and
        the precise mixing in mix_012_frequency.

Reference: M.Hiroi pyalgo36 (rangecoder.py), pyalgo48 (mtf.py),
           pyalgo49 (bsrc1.py, rle.py, freq.py).
"""
# ==== rangecoder.py ====

#
# rangecoder.py : レンジコーダ (Range Coder)
#
#                 Copyright (C) 2007-2022 Makoto Hiroi
#


# 定数
ENCODE = "encode"
DECODE = "decode"
MAX_RANGE = 0xffffffff
MIN_RANGE = 0x1000000
MASK      = 0xffffffff
SHIFT     = 24

# レンジコーダー
class RangeCoder:
    def __init__(self, s, mode):
        self.stream = s
        self.range_ = MAX_RANGE
        self.buff = 0
        self.cnt = 0
        if mode == ENCODE:
            self.low = 0
        elif mode == DECODE:
            # buff の初期値 (0) を読み捨てる
            self.stream.getc()
            # 4 byte read
            self.low = self.stream.getc()
            self.low = (self.low << 8) + self.stream.getc()
            self.low = (self.low << 8) + self.stream.getc()
            self.low = (self.low << 8) + self.stream.getc()
        else:
            raise "RangeCoder mode error"

    # 符号化の正規化
    def encode_normalize(self):
        if self.low > MAX_RANGE:
            # 桁上がり
            self.buff += 1
            self.low &= MASK
            if self.cnt > 0:
                self.stream.putc(self.buff)
                for _ in range(self.cnt - 1): self.stream.putc(0)
                self.buff = 0
                self.cnt = 0
        while self.range_ < MIN_RANGE:
            if self.low < (0xff << SHIFT):
                self.stream.putc(self.buff)
                for _ in range(self.cnt): self.stream.putc(0xff)
                self.buff = (self.low >> SHIFT) & 0xff
                self.cnt = 0
            else:
                self.cnt += 1
            self.low = (self.low << 8) & MASK
            self.range_ <<= 8

    # 復号の正規化
    def decode_normalize(self):
        while self.range_ < MIN_RANGE:
            self.range_ <<= 8
            self.low = ((self.low << 8) + self.stream.getc()) & MASK

    # 終了
    def finish(self):
        c = 0xff
        if self.low > MAX_RANGE:
            # 桁上がり
            self.buff += 1
            c = 0
        self.stream.putc(self.buff)
        for _ in range(self.cnt): self.stream.putc(c)
        #
        self.stream.putc((self.low >> 24) & 0xff)
        self.stream.putc((self.low >> 16) & 0xff)
        self.stream.putc((self.low >> 8) & 0xff)
        self.stream.putc(self.low & 0xff)

# ==== freq.py ====

#
# freq.py : 適応型レンジコーダ用の出現頻度表
#
#           Copyright (C) 2007-2022 Makoto Hiroi
#


# 定数
GR = 16

# 出現頻度表
class Freq:
    def __init__(self, size, inc = 1, limit = MIN_RANGE):
        self.size = size
        self.inc = inc
        self.limit = limit
        self.count = [1] * size
        if size % GR == 0:
            self.count_group = [GR] * (size // GR)
        else:
            self.count_group = [GR] * (size // GR + 1)
        self.sum_ = size

    # 出現頻度表の更新
    def update(self, c):
        self.count[c] += self.inc
        self.count_group[c // GR] += self.inc
        self.sum_ += self.inc
        if self.sum_ >= self.limit:
            n = 0
            for x in range(len(self.count_group)):
                self.count_group[x] = 0
            for x in range(self.size):
                self.count[x] = (self.count[x] >> 1) | 1
                self.count_group[x // GR] += self.count[x]
                n += self.count[x]
            self.sum_ = n

    # 記号の累積度数を求める
    def cumul(self, c):
        n = 0
        for x in range(c // GR): n += self.count_group[x]
        for x in range((c // GR) * GR, c): n += self.count[x]
        return n

    # 符号化
    def encode(self, rc, c):
        temp = rc.range_ // self.sum_
        rc.low += self.cumul(c) * temp
        rc.range_ = self.count[c] * temp
        rc.encode_normalize()
        self.update(c)

    # 復号
    def decode(self, rc):
        # 記号の探索
        def search_code(value):
            n = 0
            for x in range(len(self.count_group)):
                if value < n + self.count_group[x]: break
                n += self.count_group[x]
            for c in range(x*GR, self.size):
                if value < n + self.count[c]: break
                n += self.count[c]
            return c, n
        #
        temp = rc.range_ // self.sum_
        c, num = search_code(rc.low // temp)
        rc.low -= temp * num
        rc.range_ = temp * self.count[c]
        rc.decode_normalize()
        self.update(c)
        return c

#
# structured model
#
LIMIT1 = 0x140  # VERIFIED from libsssg.so get_frequency(3,0x140,inc); ref used 0x100
LIMIT2 = 0x200
LIMIT3 = 0x800

class Freq1:
    def __init__(self, size):
        n2 = size >> 1
        n1 = 0
        while n2 > 0:
            n1 += 1
            n2 >>= 1
        self.size = n1
        self.context1 = Freq(n1 + 1, 4, LIMIT2)
        self.context2 = [None] * (n1 + 1)
        for x in range(1, n1 + 1):
            self.context2[x] = Freq(2 ** x, 4, LIMIT3)

    # 符号化
    def encode(self, rc, c):
        n1 = 0
        n2 = (c + 1) >> 1
        while n2 > 0:
            n1 += 1
            n2 >>= 1
        self.context1.encode(rc, n1)
        if n1 > 0:
            self.context2[n1].encode(rc, (c + 1) & ((2 ** n1) - 1))

    # 復号
    def decode(self, rc):
        n1 = self.context1.decode(rc)
        if n1 > 0:
            n2 = self.context2[n1].decode(rc)
            n1 = (1 << n1) + n2 - 1
        return n1

#
# 0-1-2 coding
#
class Freq012:
    def __init__(self, size):
        self.context1 = [Freq(3, 4, LIMIT1) for _ in range(27)]
        self.context2 = Freq1(size - 2)
        self.c0 = self.c1 = self.c2 = 0

    # 符号化
    def encode(self, rc, c):
        freq = self.context1[self.c2 * 9 + self.c1 * 3 + self.c0]
        self.c2 = self.c1
        self.c1 = self.c0
        if c < 2:
            freq.encode(rc, c)
            self.c0 = c
        else:
            freq.encode(rc, 2)
            self.c0 = 2
            self.context2.encode(rc, c - 2)

    # 復号
    def decode(self, rc):
        freq = self.context1[self.c2 * 9 + self.c1 * 3 + self.c0]
        self.c2 = self.c1
        self.c1 = self.c0
        c = freq.decode(rc)
        self.c0 = c
        if c >= 2:
            c = self.context2.decode(rc)
            c += 2
        return c

#
# 混合法
#

# 符号化
def _encode(rc, freq1, freq2, c):
    def cumul():
        n = 0
        for x in range(c):
            n += freq1.count[x] + freq2.count[x]
        return n
    #
    temp = rc.range_ // (freq1.sum_ + freq2.sum_)
    rc.low += cumul() * temp
    rc.range_ = (freq1.count[c] + freq2.count[c]) * temp
    rc.encode_normalize()
    freq1.update(c)
    freq2.update(c)

# 復号
def _decode(rc, freq1, freq2):
    def search_code(value):
        n = 0
        for c in range(freq1.size):
            m = freq1.count[c] + freq2.count[c]
            if value < n + m: break
            n += m
        return c, n
    #
    temp = rc.range_ // (freq1.sum_ + freq2.sum_)
    c, num = search_code(rc.low // temp)
    rc.low -= temp * num
    rc.range_ = temp * (freq1.count[c] + freq2.count[c])
    rc.decode_normalize()
    freq1.update(c)
    freq2.update(c)
    return c

class Freq1m:
    def __init__(self, size):
        n2 = size >> 1
        n1 = 0
        while n2 > 0:
            n1 += 1
            n2 >>= 1
        n1 += 1
        self.size = n1
        self.c0 = self.c1 = 0
        self.context1 = [Freq(n1, 4, LIMIT2) for _ in range(n1 * n1)]  # order-2
        self.context2 = Freq(n1, 12, LIMIT2)
        self.context3 = [None] * n1
        for x in range(1, n1):
            self.context3[x] = Freq(2 ** x, 4, LIMIT3)

    # 符号化
    def encode(self, rc, c):
        n1 = 0
        n2 = (c + 1) >> 1
        while n2 > 0:
            n1 += 1
            n2 >>= 1
        freq1 = self.context1[self.c1 * self.size + self.c0]
        freq2 = self.context2
        _encode(rc, freq1, freq2, n1)
        self.c1 = self.c0
        self.c0 = n1
        if n1 > 0:
            self.context3[n1].encode(rc, (c + 1) & ((2 ** n1) - 1))

    # 復号
    def decode(self, rc):
        freq1 = self.context1[self.c1 * self.size + self.c0]
        freq2 = self.context2
        n1 = _decode(rc, freq1, freq2)
        self.c1 = self.c0
        self.c0 = n1
        if n1 > 0:
            n2 = self.context3[n1].decode(rc)
            n1 = (1 << n1) + n2 - 1
        return n1

class Freq012m:
    def __init__(self, size):
        self.context1 = [Freq(3, 2, LIMIT1) for _ in range(81)]  # order-4
        self.context2 = [Freq(3, 14, LIMIT1) for _ in range(3)]  # order-1
        self.context3 = Freq1m(size - 2)
        self.c0 = self.c1 = self.c2 = self.c3 = 0

    # 符号化
    def encode(self, rc, c):
        freq1 = self.context1[self.c3 * 27 + self.c2 * 9 + self.c1 * 3 + self.c0]
        freq2 = self.context2[self.c0]
        self.c3 = self.c2
        self.c2 = self.c1
        self.c1 = self.c0
        if c < 2:
            _encode(rc, freq1, freq2, c)
            self.c0 = c
        else:
            _encode(rc, freq1, freq2, 2)
            self.c0 = 2
            self.context3.encode(rc, c - 2)

    # 復号
    def decode(self, rc):
        freq1 = self.context1[self.c3 * 27 + self.c2 * 9 + self.c1 * 3 + self.c0]
        freq2 = self.context2[self.c0]
        self.c3 = self.c2
        self.c2 = self.c1
        self.c1 = self.c0
        c = _decode(rc, freq1, freq2)
        self.c0 = c
        if c >= 2:
            c = self.context3.decode(rc) + 2
        return c



# ==== framing + pipeline ====
import struct, sys

class Reader:
    def __init__(self, data): self.d=data; self.p=0
    def getc(self):
        if self.p < len(self.d):
            b=self.d[self.p]; self.p+=1; return b
        self.p+=1; return 0

def mtf_decode(buff):
    t=list(range(256))
    for x in range(len(buff)):
        j=buff[x]; c=t[j]
        if j>0: del t[j]; t.insert(0,c)
        buff[x]=c

def rle_decode(buff, n):  # plain RLE (applied only when type!=0)
    out=[]; size=len(buff); i=0
    while i<size:
        c=buff[i]; i+=1; k=1
        while i<size and k<n:
            if buff[i]!=c: break
            i+=1; k+=1
        if k==n: k+=buff[i]; i+=1
        out.extend([c]*k)
    return out

def inverse_bwt(buff, top):
    size=len(buff); count=[0]*256
    for b in buff: count[b]+=1
    for x in range(1,256): count[x]+=count[x-1]
    idx=[0]*size
    for x in range(size-1,-1,-1):
        c=buff[x]; count[c]-=1; idx[count[c]]=x
    out=bytearray(size); x=idx[top]
    for i in range(size): out[i]=buff[x]; x=idx[x]
    return bytes(out)

def decode_fmc(path):
    data=open(path,'rb').read()
    assert data[:4]==b'casi', 'not a .fmc'
    ver, type_ = data[4], data[5]
    top   = (data[6]<<16)|(data[7]<<8)|data[8]
    rsize = (data[9]<<16)|(data[10]<<8)|data[11]
    body  = data[12:12+rsize]
    r=Reader(body); rc=RangeCoder(r, DECODE); freq=Freq012m(257)
    syms=[]
    while True:
        c=freq.decode(rc)
        if c==256: break               # EOS
        syms.append(c)
        if r.p > len(body)+16: break    # safety (model gap -> may not hit EOS)
    work=list(syms)
    if type_!=0: work=rle_decode(work,7)
    mtf_decode(work)
    plain=inverse_bwt(work, top)
    return dict(ver=ver, type=type_, top=top, rsize=rsize, nsyms=len(syms), plain=plain)

def records(plain):
    out=[]
    for i in range(0,len(plain)-9,10):
        t=struct.unpack_from('<Q',plain,i)[0]
        out.append((t, plain[i+8], plain[i+9]))
    return out

if __name__=='__main__':
    r=decode_fmc(sys.argv[1])
    print(f"ver={r['ver']} type={r['type']} top={r['top']} rsize={r['rsize']} nsyms={r['nsyms']} plain={len(r['plain'])}")
    recs=records(r['plain']); ok=sum(1 for _,n,f in recs if n<=127 and 1<=f<=5)
    print(f"records={len(recs)} valid={ok} (model gap -> not yet valid; see module docstring)")
