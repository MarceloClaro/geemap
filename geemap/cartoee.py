import ee
import os
import sys
import json
import logging
import requests
import warnings
import subprocess
import numpy as np
from io import BytesIO
import matplotlib as mpl
# import matplotlib.pyplot as plt
from matplotlib import cm, colors
from collections.abc import Iterable


try:

    from PIL import Image
    import cartopy.crs as ccrs
    from cartopy.mpl.geoaxes import GeoAxes, GeoAxesSubplot
    from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER

except ImportError:

    print("cartopy is not installed. Please see https://scitools.org.uk/cartopy/docs/latest/installing.html#installing for instructions on how to install cartopy.\n")
    print('The easiest way to install cartopy is using conda: conda install -c conda-forge cartopy')


def check_dependencies():
    """Helper function to check dependencies used for cartoee
    Dependencies not included in main geemap are: cartopy, PIL, and scipys

    raises:
        Exception: when conda is not found in path
        Exception: when auto install fails to install/import packages 
    """

    import importlib

    # check if conda in in path and available to use
    is_conda = os.path.exists(os.path.join(sys.prefix, "conda-meta"))

    # raise error if conda not found
    if not is_conda:
        raise Exception(
            "Auto installation requires `conda`. Please install conda using the following instructions before use: https://docs.conda.io/projects/conda/en/latest/user-guide/install/"
        )

    # list of dependencies to check, ordered in decreasing complexity
    # i.e. cartopy install should install PIL
    dependencies = ["cartopy", "pillow", "scipy"]

    # loop through dependency list and check if we can import module
    # if not try to install
    # install fail will be silent to continue through others if there is a failure
    # correct install will be checked later
    for dependency in dependencies:
        try:
            # see if we can import
            mod = importlib.import_module(dependency)
        except ImportError:
            # change the dependency name if it is PIL
            # import vs install names are different for PIL...
            # dependency = dependency if dependency is not "PIL" else "pillow"

            # print info if not installed
            logging.info(f"The {dependency} package is not installed. Trying install...")

            logging.info(f"Installing {dependency} ...")

            # run the command
            cmd = f"conda install -c conda-forge {dependency} -y"
            proc = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            # send command
            out, err = proc.communicate()

            logging.info(out.decode())

    # second pass through dependencies to check if everything was installed correctly
    failed = []

    for dependency in dependencies:
        try:
            mod = importlib.import_module(dependency)
        except ImportError:
            # append failed imports
            failed.append(dependency)

    # check if there were any failed imports after trying install
    if len(failed) > 0:
        failed_str = ",".join(failed)
        raise Exception(
            f"Auto installation failed...the following dependencies were not installed '{failed_str}'"
        )
    else:
        logging.info("All dependencies are successfully imported/installed!")

    return


# check_dependencies()


def get_map(img_obj, proj=None, **kwargs):
    """
    Wrapper function to create a new cartopy plot with project and adds Earth
    Engine image results
    Args:
        img_obj (ee.Image): Earth Engine image result to plot
        proj (cartopy.crs, optional): Cartopy projection that determines the projection of the resulting plot. By default uses an equirectangular projection, PlateCarree
        **kwargs: remaining keyword arguments are passed to addLayer()
    Returns:
        ax (cartopy.mpl.geoaxes.GeoAxesSubplot): cartopy GeoAxesSubplot object with Earth Engine results displayed
    """
    if proj is None:
        proj = ccrs.PlateCarree()

    ax = mpl.pyplot.axes(projection=proj)
    add_layer(ax, img_obj, **kwargs)

    return ax


def add_layer(ax, img_obj, dims=1000, region=None, cmap=None, vis_params=None):
    """Add an Earth Engine image to a cartopy plot.

    args:
        img_obj (ee.image.Image): Earth Engine image result to plot.
        ax (cartopy.mpl.geoaxes.GeoAxesSubplot | cartopy.mpl.geoaxes.GeoAxes): required cartopy GeoAxesSubplot object to add image overlay to
        dims (list | tuple | int, optional): dimensions to request earth engine result as [WIDTH,HEIGHT]. If only one number is passed, it is used as the maximum, and the other dimension is computed by proportional scaling. Default None and infers dimesions
        region (list | tuple, optional): geospatial region of the image to render in format [E,S,W,N]. By default, the whole image
        cmap (str, optional): string specifying matplotlib colormap to colorize image. If cmap is specified visParams cannot contain 'palette' key
        vis_params (dict, optional): visualization parameters as a dictionary. See https://developers.google.com/earth-engine/image_visualization for options

    returns:
        ax (cartopy.mpl.geoaxes.GeoAxesSubplot): cartopy GeoAxesSubplot object with Earth Engine results displayed

    raises:
        ValueError: If `dims` is not of type list, tuple, or int
        ValueError: If `imgObj` is not of type ee.image.Image
        ValueError: If `ax` if not of type cartopy.mpl.geoaxes.GeoAxesSubplot '
    """

    if type(img_obj) is not ee.image.Image:
        raise ValueError("provided `img_obj` is not of type ee.Image")

    if region is not None:
        map_region = ee.Geometry.Rectangle(region).getInfo()["coordinates"]
        view_extent = (region[0], region[2], region[1], region[3])
    else:
        map_region = img_obj.geometry(100).bounds().getInfo()["coordinates"]
        # get the image bounds
        x, y = list(zip(*map_region[0]))
        view_extent = [min(x), max(x), min(y), max(y)]

    if type(dims) not in [list, tuple, int]:
        raise ValueError("provided dims not of type list, tuple, or int")

    if type(ax) not in [GeoAxes, GeoAxesSubplot]:
        raise ValueError(
            "provided axes not of type cartopy.mpl.geoaxes.GeoAxes "
            "or cartopy.mpl.geoaxes.GeoAxesSubplot"
        )

    args = {"format": "png"}
    if region:
        args["region"] = map_region
    if dims:
        args["dimensions"] = dims

    if vis_params:
        keys = list(vis_params.keys())
        if cmap and ("palette" in keys):
            raise KeyError(
                "cannot provide `palette` in vis_params if `cmap` is specified"
            )
        elif cmap:
            args["palette"] = ",".join(build_palette(cmap))
        else:
            pass

        args = {**args, **vis_params}

    url = img_obj.getThumbUrl(args)
    response = requests.get(url)
    if response.status_code != 200:
        error = eval(response.content)["error"]
        raise requests.exceptions.HTTPError(f"{error}")

    image = np.array(Image.open(BytesIO(response.content)))

    if image.shape[-1] == 2:
        image = np.concatenate(
            [np.repeat(image[:, :, 0:1], 3, axis=2), image[:, :, -1:]], axis=2
        )

    ax.imshow(
        np.squeeze(image),
        extent=view_extent,
        origin="upper",
        transform=ccrs.PlateCarree(),
    )

    return


def build_palette(cmap, n=256):
    """Creates hex color code palette from a matplotlib colormap

    args:
        cmap (str): string specifying matplotlib colormap to colorize image. If cmap is specified visParams cannot contain 'palette' key
        n (int, optional): Number of hex color codes to create from colormap. Default is 256

    returns:
        palette (list[str]): list of hex color codes from matplotlib colormap for n intervals
    """

    colormap = cm.get_cmap(cmap, n)
    vals = np.linspace(0, 1, n)
    palette = list(map(lambda x: colors.rgb2hex(colormap(x)[:3]), vals))

    return palette


def add_colorbar(
    ax, vis_params, loc=None, cmap="gray", discrete=False, label=None, **kwargs
):
    """
    Add a colorbar tp the map based on visualization parameters provided
    args:
        ax (cartopy.mpl.geoaxes.GeoAxesSubplot | cartopy.mpl.geoaxes.GeoAxes): required cartopy GeoAxesSubplot object to add image overlay to
        loc (str, optional): string specifying the position
        vis_params (dict, optional): visualization parameters as a dictionary. See https://developers.google.com/earth-engine/image_visualization for options
        **kwargs: remaining keyword arguments are passed to colorbar()

    raises:
        Warning: If 'discrete' is true when "palette" key is not in visParams
        ValueError: If `ax` is not of type cartopy.mpl.geoaxes.GeoAxesSubplot
        ValueError: If 'cmap' or "palette" key in visParams is not provided
        ValueError: If "min" in visParams is not of type scalar
        ValueError: If "max" in visParams is not of type scalar
        ValueError: If 'loc' or 'cax' keywords are not provided
        ValueError: If 'loc' is not of type str or does not equal available options
    """

    if type(ax) not in [GeoAxes, GeoAxesSubplot]:
        raise ValueError(
            "provided axes not of type cartopy.mpl.geoaxes.GeoAxes "
            "or cartopy.mpl.geoaxes.GeoAxesSubplot"
        )

    if loc:
        if (type(loc) == str) and (loc in ["left", "right", "bottom", "top"]):
            posOpts = {
                "left": [0.01, 0.25, 0.02, 0.5],
                "right": [0.88, 0.25, 0.02, 0.5],
                "bottom": [0.25, 0.15, 0.5, 0.02],
                "top": [0.25, 0.88, 0.5, 0.02],
            }

            cax = ax.figure.add_axes(posOpts[loc])

            if loc == "left":
                mpl.pyplot.subplots_adjust(left=0.18)
            elif loc == "right":
                mpl.pyplot.subplots_adjust(right=0.85)
            else:
                pass

        else:
            raise ValueError(
                'provided loc not of type str. options are "left", '
                '"top", "right", or "bottom"'
            )

    elif "cax" in kwargs:
        cax = kwargs["cax"]
        kwargs = {key: kwargs[key] for key in kwargs.keys() if key != "cax"}

    else:
        raise ValueError("loc or cax keywords must be specified")

    vis_keys = list(vis_params.keys())
    if vis_params:
        if "min" in vis_params:
            vmin = vis_params["min"]
            if type(vmin) not in (int, float):
                raise ValueError("provided min value not of scalar type")
        else:
            vmin = 0

        if "max" in vis_params:
            vmax = vis_params["max"]
            if type(vmax) not in (int, float):
                raise ValueError("provided max value not of scalar type")
        else:
            vmax = 1

        if "opacity" in vis_params:
            alpha = vis_params["opacity"]
            if type(alpha) not in (int, float):
                raise ValueError("provided opacity value of not type scalar")
        elif "alpha" in kwargs:
            alpha = kwargs["alpha"]
        else:
            alpha = 1

        if cmap is not None:
            if discrete:
                warnings.warn(
                    'discrete keyword used when "palette" key is '
                    "supplied with visParams, creating a continuous "
                    "colorbar..."
                )

            cmap = mpl.pyplot.get_cmap(cmap)
            norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)

        if "palette" in vis_keys:
            hexcodes = vis_params["palette"].split(",")
            hexcodes = [i if i[0] == "#" else "#" + i for i in hexcodes]

            if discrete:
                cmap = mpl.colors.ListedColormap(hexcodes)
                vals = np.linspace(vmin, vmax, cmap.N + 1)
                norm = mpl.colors.BoundaryNorm(vals, cmap.N)

            else:
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    "custom", hexcodes, N=256
                )
                norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)

            cmap = cmap

        elif cmap is not None:
            if discrete:
                warnings.warn(
                    'discrete keyword used when "palette" key is '
                    "supplied with visParams, creating a continuous "
                    "colorbar..."
                )

            cmap = mpl.pyplot.get_cmap(cmap)
            norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)

        else:
            raise ValueError(
                'cmap keyword or "palette" key in visParams must be provided'
            )

    cb = mpl.colorbar.ColorbarBase(cax, norm=norm, alpha=alpha, cmap=cmap, **kwargs)

    if "bands" in vis_keys:
        cb.set_label(vis_params["bands"])
    elif label is not None:
        cb.set_label(label)

    return


def _buffer_box(bbox, interval):
    """Helper function to buffer a bounding box to the nearest multiple of interval

    args:
        bbox (list[float]): list of float values specifying coordinates, expects order to be [W,E,S,N]
        interval (float): float specifying multiple at which to buffer coordianates to

    returns:
        extent (tuple[float]): returns tuple of buffered coordinates rounded to interval in order of [W,E,S,N]
    """

    if bbox[0] % interval != 0:
        xmin = bbox[0] - (bbox[0] % interval)
    else:
        xmin = bbox[0]

    if bbox[1] % interval != 0:
        xmax = bbox[1] + (interval - (bbox[1] % interval))
    else:
        xmax = bbox[1]

    if bbox[2] % interval != 0:
        ymin = bbox[2] - (bbox[2] % interval)
    else:
        ymin = bbox[2]

    if bbox[3] % interval != 0:
        ymax = bbox[3] + (interval - (bbox[3] % interval))
    else:
        ymax = bbox[3]

    return (xmin, xmax, ymin, ymax)


def bbox_to_extent(bbox):
    """Helper function to reorder a list of coordinates from [W,S,E,N] to [W,E,S,N]

    args:
        bbox (list[float]): list (or tuple) or coordinates in the order of [W,S,E,N]

    returns:
        extent (tuple[float]): tuple of coordinates in the order of [W,E,S,N]
    """
    return (bbox[0], bbox[2], bbox[1], bbox[3])


def add_gridlines(
    ax,
    interval=None,
    n_ticks=None,
    xs=None,
    ys=None,
    buffer_out=True,
    xtick_rotation="horizontal",
    ytick_rotation="horizontal",
    **kwargs,
):
    """Helper function to add gridlines and format ticks to map

    args:
        ax (cartopy.mpl.geoaxes.GeoAxesSubplot | cartopy.mpl.geoaxes.GeoAxes): required cartopy GeoAxesSubplot object to add the gridlines to
        interval (float | list[float], optional): float specifying an interval at which to create gridlines, units are decimal degrees. lists will be interpreted a [x_interval, y_interval]. default = None
        n_ticks (int | list[int], optional): integer specifying number gridlines to create within map extent. lists will be interpreted a [nx, ny]. default = None
        xs (list, optional): list of x coordinates to create gridlines. default = None
        ys (list, optional): list of y coordinates to create gridlines. default = None
        buffer_out (boolean, optional): boolean option to buffer out the extent to insure coordinates created cover map extent. default=true
        xtick_rotation (str | float, optional):
        ytick_rotation (str | float, optional):
        **kwargs: remaining keyword arguments are passed to gridlines()

    raises:
        ValueError: if all interval, n_ticks, or (xs,ys) are set to None

    """

    view_extent = ax.get_extent()
    extent = view_extent

    if xs is not None:
        xmain = xs

    elif interval is not None:
        if isinstance(interval, Iterable):
            xspace = interval[0]
        else:
            xspace = interval

        if buffer_out:
            extent = _buffer_box(extent, xspace)

        xmain = np.arange(extent[0], extent[1] + xspace, xspace)

    elif n_ticks is not None:
        if isinstance(n_ticks, Iterable):
            n_x = n_ticks[0]
        else:
            n_x = n_ticks

        xmain = np.linspace(extent[0], extent[1], n_x)
    else:
        raise ValueError(
            "one of variables interval, n_ticks, or xs must be defined. If you would like default gridlines, please use `ax.gridlines()`"
        )

    if ys is not None:
        ymain = ys

    elif interval is not None:
        if isinstance(interval, Iterable):
            yspace = interval[1]
        else:
            yspace = interval

        if buffer_out:
            extent = _buffer_box(extent, yspace)

        ymain = np.arange(extent[2], extent[3] + yspace, yspace)

    elif n_ticks is not None:
        if isinstance(n_ticks, Iterable):
            n_y = n_ticks[1]
        else:
            n_y = n_ticks

        ymain = np.linspace(extent[2], extent[3], n_y)

    else:
        raise ValueError(
            "one of variables interval, n_ticks, or ys must be defined. If you would like default gridlines, please use `ax.gridlines()`"
        )

    gl = ax.gridlines(xlocs=xmain, ylocs=ymain, **kwargs)

    xin = xmain[(xmain >= view_extent[0]) & (xmain <= view_extent[1])]
    yin = ymain[(ymain >= view_extent[2]) & (ymain <= view_extent[3])]

    # set tick labels
    ax.set_xticks(xin, crs=ccrs.PlateCarree())
    ax.set_yticks(yin, crs=ccrs.PlateCarree())

    ax.set_xticklabels(xin, rotation=xtick_rotation, ha="center")
    ax.set_yticklabels(yin, rotation=ytick_rotation, va="center")

    ax.xaxis.set_major_formatter(LONGITUDE_FORMATTER)
    ax.yaxis.set_major_formatter(LATITUDE_FORMATTER)

    return


def pad_view(ax, factor=0.05):
    """Function to pad area around the view extent of a map, used for visual appeal

    args:
        ax (cartopy.mpl.geoaxes.GeoAxesSubplot | cartopy.mpl.geoaxes.GeoAxes): required cartopy GeoAxesSubplot object to pad view extent
        factor (float | list[float], optional): factor to pad view extent accepts float [0-1] of a list of floats which will be interpreted at [xfactor, yfactor]

    """

    view_extent = ax.get_extent()

    if isinstance(factor, Iterable):
        xfactor, yfactor = factor
    else:
        xfactor, yfactor = factor, factor

    x_diff = view_extent[1] - view_extent[0]
    y_diff = view_extent[3] - view_extent[2]

    xmin = view_extent[0] - (x_diff * xfactor)
    xmax = view_extent[1] + (x_diff * xfactor)
    ymin = view_extent[2] - (y_diff * yfactor)
    ymax = view_extent[3] + (y_diff * yfactor)

    ax.set_ylim(ymin, ymax)
    ax.set_xlim(xmin, xmax)

    return
