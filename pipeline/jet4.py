"""Minimal read-only reader for Microsoft Access Jet 4 (.mdb) files."""
import struct, datetime, mmap

PG = 4096

class Col:
    __slots__ = ("name","type","num","var_num","row_num","flags","fixed_off","size")

class Table:
    def __init__(self, name, cols, tdef_pg):
        self.name, self.cols, self.tdef_pg = name, cols, tdef_pg

def u8(b,o): return b[o]
def u16(b,o): return struct.unpack_from("<H",b,o)[0]
def u32(b,o): return struct.unpack_from("<I",b,o)[0]

def decode_text(raw):
    if len(raw) >= 2 and raw[0] == 0xFF and raw[1] == 0xFE:
        out = []; compressed = True; i = 2; n = len(raw)
        while i < n:
            c = raw[i]
            if c == 0:
                compressed = not compressed; i += 1; continue
            if compressed:
                out.append(chr(c)); i += 1
            else:
                if i + 1 >= n: break
                out.append(chr(raw[i] | (raw[i+1] << 8))); i += 2
        return "".join(out)
    return raw.decode("utf-16le", errors="replace")

class MDB:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.m = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        self.npages = len(self.m) // PG
        assert self.m[0x14] == 1, "not Jet 4"
        self._index = None
        self.catalog = self._read_catalog()

    def page(self, n):
        return self.m[n*PG:(n+1)*PG]

    def _tdef_bytes(self, pg):
        p = self.page(pg); assert p[0] == 2, ("not tdef", pg, p[0])
        buf = bytearray(p); nxt = u32(p, 4)
        while nxt:
            q = self.page(nxt); buf += q[8:]; nxt = u32(q, 4)
        return bytes(buf)

    def read_tdef(self, pg, name=""):
        b = self._tdef_bytes(pg)
        num_var = u16(b, 0x2B); num_cols = u16(b, 0x2D)
        num_real_idx = u32(b, 0x33)
        o = 0x3F + num_real_idx * 12
        cols = []
        for _ in range(num_cols):
            c = Col()
            c.type = b[o]; c.num = u16(b, o+5); c.var_num = u16(b, o+7); c.row_num = u16(b, o+9)
            c.flags = b[o+15]; c.fixed_off = u16(b, o+21); c.size = u16(b, o+23)
            cols.append(c); o += 25
        for c in cols:
            ln = u16(b, o); c.name = b[o+2:o+2+ln].decode("utf-16le", errors="replace"); o += 2 + ln
        cols.sort(key=lambda c: c.num)
        return Table(name, cols, pg)

    def _build_index(self):
        idx = {}
        m = self.m
        for n in range(1, self.npages):
            off = n*PG
            if m[off] == 1:
                t = struct.unpack_from("<I", m, off+4)[0]
                idx.setdefault(t, []).append(n)
        self._index = idx

    def data_pages(self, tdef_pg):
        if self._index is None: self._build_index()
        return self._index.get(tdef_pg, [])

    def _row_bytes(self, pg, rownum, depth=0):
        p = self.page(pg)
        nrows = u16(p, 0x0C)
        if rownum >= nrows: return None
        raw = u16(p, 0x0E + rownum*2)
        start = raw & 0x1FFF
        end = PG if rownum == 0 else (u16(p, 0x0E + (rownum-1)*2) & 0x1FFF)
        if raw & 0x8000 and not raw & 0x4000: return None
        data = p[start:end]
        if raw & 0x4000:
            if depth > 3 or len(data) < 4: return None
            r = data[0]; pg2 = data[1] | (data[2] << 8) | (data[3] << 16)
            return self._row_bytes(pg2, r, depth+1)
        return data

    def _lval(self, raw):
        if len(raw) < 12: return b""
        hdr = u32(raw, 0); ln = hdr & 0x3FFFFFFF
        if hdr & 0x80000000:
            return raw[12:12+ln]
        ptr = u32(raw, 4); r = ptr & 0xFF; pg = ptr >> 8
        if hdr & 0x40000000:
            d = self._row_bytes(pg, r); return (d or b"")[:ln]
        out = bytearray()
        guard = 0
        while pg and len(out) < ln and guard < 10000:
            d = self._row_bytes(pg, r)
            if not d: break
            nxt = u32(d, 0); out += d[4:]
            r = nxt & 0xFF; pg = nxt >> 8; guard += 1
        return bytes(out[:ln])

    def _value(self, c, raw):
        t = c.type
        if t == 2: return raw[0]
        if t == 3: return struct.unpack("<h", raw[:2])[0]
        if t == 4: return struct.unpack("<i", raw[:4])[0]
        if t == 5: return struct.unpack("<q", raw[:8])[0] / 10000.0
        if t == 6: return struct.unpack("<f", raw[:4])[0]
        if t == 7: return struct.unpack("<d", raw[:8])[0]
        if t == 8:
            d = struct.unpack("<d", raw[:8])[0]
            try: return datetime.datetime(1899,12,30) + datetime.timedelta(days=d)
            except Exception: return None
        if t == 10: return decode_text(raw)
        if t == 12: return decode_text(self._lval(raw))
        if t == 11: return None
        if t == 15: return raw.hex()
        if t == 16:
            if len(raw) < 17: return None
            neg = raw[1] & 0x80; scale = c.size and 0
            v = int.from_bytes(raw[1+0:1+16], "little") if False else None
            return None
        return raw.hex()

    def rows(self, table):
        cols = table.cols
        fixed = [c for c in cols if c.flags & 0x01]
        var = [c for c in cols if not c.flags & 0x01]
        for pg in self.data_pages(table.tdef_pg):
            p = self.page(pg)
            for r in range(u16(p, 0x0C)):
                raw = u16(p, 0x0E + r*2)
                if raw & 0x4000: continue  # overflow targets appear elsewhere; pointer rows handled via lookup
                if raw & 0x8000: continue
                d = self._row_bytes(pg, r)
                if not d or len(d) < 4: continue
                try:
                    yield self._parse_row(d, cols, fixed, var)
                except Exception:
                    continue
            # rows stored via overflow pointers
            for r in range(u16(p, 0x0C)):
                raw = u16(p, 0x0E + r*2)
                if raw & 0x4000 and not raw & 0x8000:
                    d = self._row_bytes(pg, r)
                    if d and len(d) >= 4:
                        try: yield self._parse_row(d, cols, fixed, var)
                        except Exception: pass

    def _parse_row(self, d, cols, fixed, var):
        n = len(d)
        ncols = u16(d, 0)
        bm = (ncols + 7) // 8
        nullmask = d[n-bm:]
        def present(cn):
            if cn >= ncols: return False
            return bool(nullmask[cn // 8] & (1 << (cn % 8)))
        nvar = u16(d, n - bm - 2)
        offs = [u16(d, n - bm - 4 - i*2) for i in range(nvar + 1)]
        rec = {}
        for c in cols:
            if c.type == 1:
                rec[c.name] = present(c.row_num); continue
            if not present(c.row_num):
                rec[c.name] = None; continue
            if c.flags & 0x01:
                s = 2 + c.fixed_off
                rec[c.name] = self._value(c, d[s:s+c.size])
            else:
                if c.var_num >= nvar: rec[c.name] = None; continue
                a, b = offs[c.var_num], offs[c.var_num+1]
                rec[c.name] = self._value(c, d[a:b]) if b > a else ("" if c.type in (10,12) else None)
        return rec

    def _read_catalog(self):
        t = self.read_tdef(2, "MSysObjects")
        cat = {}
        for r in self.rows(t):
            if r.get("Type") == 1 and r.get("Name") is not None:
                cat[r["Name"]] = (r["Id"] & 0x00FFFFFF, r.get("Flags"))
        return cat

    def table(self, name):
        pg, _ = self.catalog[name]
        return self.read_tdef(pg, name)
