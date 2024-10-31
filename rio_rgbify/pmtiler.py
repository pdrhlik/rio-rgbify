from __future__ import with_statement, division

import sys
import traceback
import itertools
import mercantile
import rasterio
import numpy as np
from io import BytesIO
from PIL import Image
from rasterio import transform
from rasterio.warp import reproject, transform_bounds
from rasterio.enums import Resampling
from rio_rgbify.encoders import data_to_rgb
from multiprocessing import Pool
from pmtiles.writer import Writer  # Ensure pmtiles library is installed
from pmtiles.tile import Compression, TileType, zxy_to_tileid

from rasterio._io import virtual_file_to_buffer
from riomucho.single_process_pool import MockTub

buffer = bytes if sys.version_info > (3,) else buffer

# Set global variables for pool workers
work_func = None
global_args = None
src = None

def _main_worker(inpath, g_work_func, g_args):
    global work_func, global_args, src
    work_func = g_work_func
    global_args = g_args
    src = rasterio.open(inpath)

def _encode_as_webp(data, profile=None, affine=None):
    with BytesIO() as f:
        im = Image.fromarray(np.rollaxis(data, 0, 3))
        im.save(f, format="webp", lossless=True)
        return f.getvalue()

def _encode_as_png(data, profile, dst_transform):
    profile["affine"] = dst_transform
    with rasterio.open("/vsimem/tileimg", "w", **profile) as dst:
        dst.write(data)
    return bytearray(virtual_file_to_buffer("/vsimem/tileimg"))

def _tile_worker(tile):
    x, y, z = tile
    bounds = [c for i in (mercantile.xy(*mercantile.ul(x, y + 1, z)),
                          mercantile.xy(*mercantile.ul(x + 1, y, z))) for c in i]
    toaffine = transform.from_bounds(*bounds + [512, 512])
    out = np.empty((512, 512), dtype=src.meta["dtype"])
    reproject(
        rasterio.band(src, 1),
        out,
        dst_transform=toaffine,
        dst_crs="EPSG:3857",
        resampling=Resampling.bilinear,
    )
    out = data_to_rgb(out, global_args["base_val"], global_args["interval"], global_args["round_digits"])
    return tile, global_args["writer_func"](out, global_args["kwargs"].copy(), toaffine)

def _tile_range(min_tile, max_tile):
    min_x, min_y, _ = min_tile
    max_x, max_y, _ = max_tile
    return itertools.product(range(min_x, max_x + 1), range(min_y, max_y + 1))

def _make_tiles(bbox, src_crs, minz, maxz):
    w, s, e, n = transform_bounds(*[src_crs, "EPSG:4326"] + bbox, densify_pts=2)
    EPSILON = 1.0e-10
    w += EPSILON; s += EPSILON; e -= EPSILON; n -= EPSILON
    for z in range(minz, maxz + 1):
        for x, y in _tile_range(mercantile.tile(w, n, z), mercantile.tile(e, s, z)):
            yield [x, y, z]

class RGBTilerPMTiles:
    """
    Takes continuous source data and encodes it into RGB tiles saved in PMTiles format.

    ```
    with RGBTiler(inpath, outpath, min_z, max_x, **kwargs) as tiler:
        tiler.run(processes)
    ```

    Parameters
    -----------
    inpath: string
        filepath of the source file to read and encode
    outpath: string
        filepath of the output `mbtiles`
    min_z: int
        minimum zoom level to tile
    max_z: int
        maximum zoom level to tile

    Keyword Arguments
    ------------------
    baseval: float
        the base value of the RGB numbering system.
        (will be treated as zero for this encoding)
        Default=0
    interval: float
        the interval at which to encode
        Default=1
    round_digits: int
        Erased less significant digits
        Default=0
    format: str
        output tile image format (png or webp)
        Default=png
    bounding_tile: list
        [x, y, z] of bounding tile; limits tiled output to this extent

    Returns
    --------
    None

    """

    def __init__(self, inpath, outpath, min_z, max_z, interval=1, base_val=0, round_digits=0, bounding_tile=None, **kwargs):
        self.run_function = _tile_worker
        self.inpath = inpath
        self.outpath = outpath
        self.min_z = min_z
        self.max_z = max_z
        self.bounding_tile = bounding_tile

        if not "format" in kwargs:
            writer_func = _encode_as_png
            self.image_format = "png"
            self.tile_type = TileType.PNG
        elif kwargs["format"].lower() == "png":
            writer_func = _encode_as_png
            self.image_format = "png"
            self.tile_type = TileType.PNG
        elif kwargs["format"].lower() == "webp":
            writer_func = _encode_as_webp
            self.image_format = "webp"
            self.tile_type = TileType.WEBP
        else:
            raise ValueError(f"{kwargs['format']} is not a supported filetype!")


        self.global_args = {
            "kwargs": {
                "driver": "PNG",
                "dtype": "uint8",
                "height": 512,
                "width": 512,
                "count": 3,
                "crs": "EPSG:3857",
            },
            "base_val": base_val,
            "interval": interval,
            "round_digits": round_digits,
            "writer_func": writer_func,
        }

    def __enter__(self):
        self.file_handle = open(self.outpath, "wb")
        self.pm_writer = Writer(self.file_handle)
        return self

    def __exit__(self, ext_t, ext_v, trace):
        if ext_t:
            traceback.print_exc()
        self.file_handle.close()

    def run(self, processes=4):
        with rasterio.open(self.inpath) as src:
            bbox = list(src.bounds)
            src_crs = src.crs

        if processes == 1:
            self.pool = MockTub(_main_worker, (self.inpath, self.run_function, self.global_args))
        else:
            self.pool = Pool(processes, _main_worker, (self.inpath, self.run_function, self.global_args))

        if self.bounding_tile is None:
            tiles = _make_tiles(bbox, src_crs, self.min_z, self.max_z)
        else:
            constrained_bbox = list(mercantile.bounds(self.bounding_tile))
            tiles = _make_tiles(constrained_bbox, "EPSG:4326", self.min_z, self.max_z)

        for tile, contents in self.pool.imap_unordered(self.run_function, tiles):
            x, y, z = tile
            tileid = zxy_to_tileid(z, x, y)
            self.pm_writer.write_tile(tileid, bytes(contents))

        header = {
            "tile_type": self.tile_type,
            "tile_compression": Compression.NONE,
            "min_zoom": self.min_z,
            "max_zoom": self.max_z,
            "min_lon_e7": int(bbox[0] * 10000000),
            "min_lat_e7": int(bbox[1] * 10000000),
            "max_lon_e7": int(bbox[2] * 10000000),
            "max_lat_e7": int(bbox[3] * 10000000),
            "center_zoom": self.min_z,
            "center_lon_e7": int((bbox[0] + bbox[2]) / 2 * 10000000),
            "center_lat_e7": int((bbox[1] + bbox[3]) / 2 * 10000000),
        }

        # TODO: pass metadata
        metadata = {}

        self.pool.close()
        self.pool.join()
        self.pm_writer.finalize(header, metadata)

        return None
