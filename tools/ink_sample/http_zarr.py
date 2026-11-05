"""Read-only zarr (v2 or v3, unsharded) over plain HTTP(S) with the standard library + numcodecs (MIT).

Only what ink_sample needs: `shape`, `dtype`, and `arr[z0:z1, y0:y1, x0:x1]`, fetching only the chunks
that box touches (in parallel, cached). A missing chunk (403/404) is the fill value, as zarr defines it.
"""
from __future__ import annotations

import collections
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np


class HttpZarrError(ValueError):
    pass


STATS = {"bytes": 0, "requests": 0}       # running total of what this process downloaded


def _get(url, tries=4, timeout=90):
    err = None
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
                b = r.read()
                STATS["bytes"] += len(b)
                STATS["requests"] += 1
                return b
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            err = e
        except Exception as e:  # noqa: BLE001 - network noise, retried
            err = e
    raise ConnectionError(f"fetch failed {url}: {err}")


def _json(url):
    b = _get(url)
    return None if b is None else json.loads(b)


def _v3_dtype(dt):
    names = {"uint8": "u1", "uint16": "<u2", "uint32": "<u4", "int8": "i1", "int16": "<i2", "int32": "<i4",
             "float32": "<f4", "float64": "<f8"}
    if dt not in names:
        raise HttpZarrError(f"unsupported zarr v3 data_type {dt!r}")
    return np.dtype(names[dt])


class _LRU(collections.OrderedDict):
    """Keeps the `cap` most recently used decoded chunks (a 256^3 uint8 chunk is about 16 MB)."""

    def __init__(self, cap):
        super().__init__()
        self.cap = cap

    def __contains__(self, k):
        hit = super().__contains__(k)
        if hit:
            self.move_to_end(k)
        return hit

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        while len(self) > self.cap:
            self.popitem(last=False)


class HttpZarrArray:
    def __init__(self, url, jobs=16, max_chunks=64):
        import numcodecs
        self.url, self.jobs, self.cache = url.rstrip("/"), jobs, _LRU(max(1, int(max_chunks)))
        za = _json(self.url + "/.zarray")
        if za is not None:                                              # zarr v2
            self.shape, self.chunks = tuple(za["shape"]), tuple(za["chunks"])
            self.dtype = np.dtype(za["dtype"])
            self.order = za.get("order", "C")
            self.fill = za.get("fill_value") or 0
            self.sep = za.get("dimension_separator", ".")
            self.codecs = [numcodecs.get_codec(f) for f in (za.get("filters") or [])][::-1]
            comp = za.get("compressor")
            self.comp = numcodecs.get_codec(comp) if comp else None
            self.v3_endian = None
            self._key = lambda idx: self.sep.join(str(i) for i in idx)
            return
        zj = _json(self.url + "/zarr.json")
        if zj is None or zj.get("node_type") != "array":
            raise HttpZarrError(f"no zarr array at {self.url} (.zarray / zarr.json not found)")
        self.shape = tuple(zj["shape"])
        cg = zj["chunk_grid"]["configuration"]["chunk_shape"]
        self.chunks = tuple(cg)
        self.dtype = _v3_dtype(zj["data_type"])
        self.fill = zj.get("fill_value") or 0
        self.order = "C"
        enc = zj.get("chunk_key_encoding", {"name": "default"})
        sep = (enc.get("configuration") or {}).get("separator", "/" if enc.get("name") == "default" else ".")
        prefix = "c" + sep if enc.get("name", "default") == "default" else ""
        self._key = lambda idx: prefix + sep.join(str(i) for i in idx)
        self.comp, self.codecs, self.v3_endian = None, [], "little"
        for c in zj["codecs"]:
            n, cfg = c["name"], c.get("configuration") or {}
            if n == "bytes":
                self.v3_endian = cfg.get("endian", "little")
            elif n == "transpose":
                raise HttpZarrError("zarr v3 transpose codec not supported")
            elif n == "sharding_indexed":
                raise HttpZarrError("sharded zarr v3 arrays are not supported by this reader")
            elif n in ("blosc", "zstd", "gzip"):
                if self.comp is not None:
                    raise HttpZarrError("more than one compressor codec")
                if n == "blosc":
                    cfg = dict(cfg)
                    shuf = {"noshuffle": 0, "shuffle": 1, "bitshuffle": 2}.get(cfg.get("shuffle"), cfg.get("shuffle", 1))
                    self.comp = numcodecs.Blosc(cname=cfg.get("cname", "lz4"), clevel=cfg.get("clevel", 5),
                                                shuffle=int(shuf), blocksize=cfg.get("blocksize", 0))
                elif n == "zstd":
                    self.comp = numcodecs.Zstd(level=cfg.get("level", 0))
                else:
                    self.comp = numcodecs.GZip(level=cfg.get("level", 5))
            else:
                raise HttpZarrError(f"unsupported zarr v3 codec {n!r}")

    def _chunk(self, idx):
        if idx in self.cache:
            return self.cache[idx]
        b = _get(f"{self.url}/{self._key(idx)}")
        cs = self.chunks
        if b is None:
            a = np.full(cs, self.fill, self.dtype)
        else:
            if self.comp is not None:
                b = self.comp.decode(b)
            for f in self.codecs:
                b = f.decode(b)
            dt = self.dtype.newbyteorder("<" if self.v3_endian == "little" else ">") if self.v3_endian else self.dtype
            a = np.frombuffer(bytes(b) if not isinstance(b, np.ndarray) else b.tobytes(), dt)
            if a.size != int(np.prod(cs)):
                raise HttpZarrError(f"chunk {idx} decoded to {a.size} values, expected {int(np.prod(cs))}")
            a = a.reshape(cs, order=self.order).astype(self.dtype, copy=False)
        self.cache[idx] = a
        return a

    def __getitem__(self, key):
        if not (isinstance(key, tuple) and len(key) == len(self.shape) and all(isinstance(k, slice) for k in key)):
            raise TypeError("HttpZarrArray supports only a tuple of slices, one per axis")
        lo = [0 if k.start is None else int(k.start) for k in key]
        hi = [s if k.stop is None else min(int(k.stop), s) for k, s in zip(key, self.shape)]
        out = np.full([max(0, h - l) for l, h in zip(lo, hi)], self.fill, self.dtype)
        if out.size == 0:
            return out
        rngs = [range(l // c, (h - 1) // c + 1) for l, h, c in zip(lo, hi, self.chunks)]
        idxs = [(a, b, c) for a in rngs[0] for b in rngs[1] for c in rngs[2]]
        if len(idxs) > self.cache.cap:
            raise HttpZarrError(f"one read needs {len(idxs)} chunks, more than the cache holds ({self.cache.cap}); "
                                "use a smaller --tile")
        with ThreadPoolExecutor(self.jobs) as ex:
            got = dict(zip(idxs, ex.map(self._chunk, idxs)))
        for idx, ch in got.items():
            c0 = [i * c for i, c in zip(idx, self.chunks)]
            s_lo = [max(l, a) for l, a in zip(lo, c0)]
            s_hi = [min(h, a + c) for h, a, c in zip(hi, c0, self.chunks)]
            out[tuple(slice(a - l, b - l) for a, b, l in zip(s_lo, s_hi, lo))] = \
                ch[tuple(slice(a - o, b - o) for a, b, o in zip(s_lo, s_hi, c0))]
        return out


def open_level(url, level):
    """(array, multiscale datasets list or None) for OME level `level` of the group at `url`."""
    url = url.rstrip("/")
    attrs = _json(url + "/.zattrs")
    if attrs is None:
        zj = _json(url + "/zarr.json")
        attrs = (zj or {}).get("attributes") or {}
    ms = attrs.get("multiscales") or (attrs.get("ome") or {}).get("multiscales")
    datasets = ms[0].get("datasets", []) if ms else None
    path = str(level)
    if datasets and level < len(datasets):
        path = datasets[level].get("path", path)
    return HttpZarrArray(f"{url}/{path}"), datasets
