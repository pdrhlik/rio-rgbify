# rio-rgbify
Encode arbitrary bit depth rasters in pseudo base-256 as RGB.

This fork introduces a new ability to output directly to a modern [PMTiles](https://github.com/protomaps/PMTiles) format. It follows the same logic as the previous MBTiles but uses the Writer from the pmtiles library.

## Installation

### Development
```
git clone git@github.com:pdrhlik/rio-rgbify.git

cd rio-rgbify

pip install -e '.[test]'
```

### Install on MacOS with an externally managed environment (using pipx)

Install `pipx` first
```bash
brew install pipx
```

Then you can install the package.
```bash
# Uninstall a previously installed version
pipx uninstall rio-rgbify

# Install the library using the current code
pipx install -e '.[test]' --include-deps

# Inject pmtiles package to the environment
pipx inject rio-rgbify pmtiles
```

There must definitely be a better way to handle this but I don't know much about Python enviroments and packages so I ended up doing this to make it work after some trial and error.

## CLI usage

- Input can be any raster readable by `rasterio`
- Output can be any raster format writable by `rasterio` OR
- To create tiles _directly_ from data (recommended), output to an `.mbtiles`
- This fork can also output directly to a modern [PMTiles](https://github.com/protomaps/PMTiles) format by setting the output extension to `.pmtiles`

```
Usage: rio rgbify [OPTIONS] SRC_PATH DST_PATH

Options:
  -b, --base-val FLOAT   The base value of which to base the output encoding
                         on [DEFAULT=0]
  -i, --interval FLOAT   Describes the precision of the output, by
                         incrementing interval [DEFAULT=1]
  -r, --round-digits     Less significants encoded bits to be set
                         to 0. Round the values, but have better
                         images compression [DEFAULT=0]
  --bidx INTEGER         Band to encode [DEFAULT=1]
  --max-z INTEGER        Maximum zoom to tile (.mbtiles/.pmtiles output)
  --bounding-tile TEXT   Bounding tile '[{x}, {y}, {z}]' to limit output tiles
                         (.mbtiles output only)
  --min-z INTEGER        Minimum zoom to tile (.mbtiles/.pmtiles output)
  --format [png|webp]    Output tile format (.mbtiles/.pmtiles output)
  -j, --workers INTEGER  Workers to run [DEFAULT=4]
  -v, --verbose
  --co NAME=VALUE        Driver specific creation options. See the
                         documentation for the selected output driver for more
                         information.
  --help                 Show this message and exit.
```

## Example

```bash
# Creates RGB pmtiles that allow overzooming
rio rgbify -b -10000 -i 0.1 -j 16 --min-z 5 --max-z 12 --format webp input.tif rgb.pmtiles

# Creates RGB mbtiles (for some reason, overzooming doesn't work here)
rio rgbify -b -10000 -i 0.1 -j 16 --min-z 5 --max-z 12 --format webp input.tif rgb.mbtiles
```
