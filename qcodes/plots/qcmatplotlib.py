"""
Live plotting in Jupyter notebooks
using the nbagg backend and matplotlib
"""
from collections import Mapping
from functools import partial

from qtpy import QtWidgets

import matplotlib.pyplot as plt
from matplotlib.transforms import Bbox
from matplotlib import cm
from matplotlib.widgets import Cursor
import mplcursors


import numpy as np
from numpy.ma import masked_invalid, getmask
from collections import Sequence

from .base import BasePlot


class MatPlot(BasePlot):
    """
    Plot x/y lines or x/y/z heatmap data. The first trace may be included
    in the constructor, other traces can be added with MatPlot.add()

    Args:
        *args: Sequence of data to plot. Each element will have its own subplot.
            An element can be a single array, or a sequence of arrays. In the
            latter case, all arrays will be plotted in the same subplot.

        figsize (Tuple[Float, Float]): (width, height) tuple in inches to pass
            to plt.figure. If not provided, figsize is determined from
            subplots shape

        interval: period in seconds between update checks

        subplots: either a sequence (args) or mapping (kwargs) to pass to
            plt.subplots. default is a single simple subplot (1, 1)
            you can use this to pass kwargs to the plt.figure constructor

        num: integer or None
            specifies the index of the matplotlib figure window to use. If None
            then open a new window

        **kwargs: passed along to MatPlot.add() to add the first data trace
    """

    # Maximum default number of subplot columns. Used to determine shape of
    # subplots when not explicitly provided
    max_subplot_columns = 3

    def __init__(self, *args, figsize=None, interval=1, subplots=None, num=None,
                 **kwargs):
        super().__init__(interval)

        if subplots is None:
            # Subplots is equal to number of args, or 1 if no args provided
            subplots = max(len(args), 1)

        self._init_plot(subplots, figsize, num=num)
        
        # Add data to plot if passed in args, kwargs are passed to all subplots
        for k, arg in enumerate(args):
            if isinstance(arg, Sequence):
                # Arg consists of multiple elements, add all to same subplot
                for subarg in arg:
                    self[k].add(subarg, **kwargs)
            else:
                # Arg is single element, add to subplot
                self[k].add(arg, **kwargs)

        self.tight_layout()

    def __getitem__(self, key):
        """
        Subplots can be accessed via indices.
        Args:
            key: subplot idx

        Returns:
            Subplot with idx key
        """
        return self.subplots[key]

    def _init_plot(self, subplots=None, figsize=None, num=None):
        if isinstance(subplots, Mapping):
            if figsize is None:
                figsize = (6, 4)
            self.fig, self.subplots = plt.subplots(figsize=figsize, num=num,
                                                   **subplots, squeeze=False)
        else:
            # Format subplots as tuple (nrows, ncols)
            if isinstance(subplots, int):
                # self.max_subplot_columns defines the limit on how many
                # subplots can be in one row. Adjust subplot rows and columns
                #  accordingly
                nrows = int(np.ceil(subplots / self.max_subplot_columns))
                ncols = min(subplots, self.max_subplot_columns)
                subplots = (nrows, ncols)

            if figsize is None:
                # Adjust figsize depending on rows and columns in subplots
                figsize = self.default_figsize(subplots)

            self.fig, self.subplots = plt.subplots(*subplots, num=num,
                                                   figsize=figsize,
                                                   squeeze=False)

        # squeeze=False ensures that subplots is always a 2D array independent
        # of the number of subplots.
        # However the qcodes api assumes that subplots is always a 1D array
        # so flatten here
        self.subplots = self.subplots.flatten()

        for k, subplot in enumerate(self.subplots):
            # Include `add` method to subplots, making it easier to add data to
            # subplots. Note that subplot kwarg is 1-based, to adhere to
            # Matplotlib standards
            subplot.add = partial(self.add, subplot=k+1)

        self.title = self.fig.suptitle('')

    def clear(self, subplots=None, figsize=None):
        """
        Clears the plot window and removes all subplots and traces
        so that the window can be reused.
        """
        self.traces = []
        self.fig.clf()
        self._init_plot(subplots, figsize, num=self.fig.number)

    def add_to_plot(self, use_offset=False, **kwargs):
        """
        adds one trace to this MatPlot.

        Args:
            use_offset (bool, Optional): Whether or not ticks can have an offset
            
            kwargs: with the following exceptions (mostly the data!), these are
                passed directly to the matplotlib plotting routine.
                `subplot`: the 1-based axes number to append to (default 1)
                if kwargs include `z`, we will draw a heatmap (ax.pcolormesh):
                    `x`, `y`, and `z` are passed as positional args to
                     pcolormesh
                without `z` we draw a scatter/lines plot (ax.plot):
                    `x`, `y`, and `fmt` (if present) are passed as positional
                    args
        """
        # TODO some way to specify overlaid axes?
        # Note that there is a conversion from subplot kwarg, which is
        # 1-based, to subplot idx, which is 0-based.
        ax = self[kwargs.get('subplot', 1) - 1]
        if 'z' in kwargs:
            plot_object = self._draw_pcolormesh(ax, **kwargs)
        else:
            plot_object = self._draw_plot(ax, **kwargs)

        # Specify if axes ticks can have offset or not
        ax.ticklabel_format(useOffset=use_offset)

        self._update_labels(ax, kwargs)
        prev_default_title = self.get_default_title()

        self.traces.append({
            'config': kwargs,
            'plot_object': plot_object
        })

        if prev_default_title == self.title.get_text():
            # in case the user has updated title, don't change it anymore
            self.title.set_text(self.get_default_title())

    def _update_labels(self, ax, config):
        for axletter in ("x", "y"):
            if axletter+'label' in config:
                label = config[axletter+'label']
            else:
                label = None

            # find if any kwarg from plot.add in the base class
            # matches xunit or yunit, signaling a custom unit
            if axletter+'unit' in config:
                unit = config[axletter+'unit']
            else:
                unit = None

            #  find ( more hope to) unit and label from
            # the data array inside the config
            getter = getattr(ax, "get_{}label".format(axletter))
            if axletter in config and not getter():
                # now if we did not have any kwarg for label or unit
                # fallback to the data_array
                if unit is None:
                    _, unit = self.get_label(config[axletter])
                if label is None:
                    label, _ = self.get_label(config[axletter])
            elif getter():
                # The axis already has label. Assume that is correct
                # We should probably check consistent units and error or warn
                # if not consistent. It's also not at all clear how to handle
                # labels/names as these will in general not be consistent on
                # at least one axis
                return
            axsetter = getattr(ax, "set_{}label".format(axletter))
            axsetter("{} ({})".format(label, unit))

    @staticmethod
    def default_figsize(subplots):
        """
        Provides default figsize for given subplots.
        Args:
            subplots (Tuple[Int, Int]): shape (nrows, ncols) of subplots

        Returns:
            Figsize (Tuple[Float, Float])): (width, height) of default figsize
              for given subplot shape
        """
        if not isinstance(subplots, tuple):
            raise TypeError('Subplots {} must be a tuple'.format(subplots))
        return (min(3 + 3 * subplots[1], 12), 1 + 3 * subplots[0])

    def update_plot(self):
        """
        update the plot. The DataSets themselves have already been updated
        in update, here we just push the changes to the plot.
        """
        # matplotlib doesn't know how to autoscale to a pcolormesh after the
        # first draw (relim ignores it...) so we have to do this ourselves
        bboxes = dict(zip(self.subplots, [[] for p in self.subplots]))

        for trace in self.traces:
            config = trace['config']
            plot_object = trace['plot_object']
            if 'z' in config:
                # pcolormesh doesn't seem to allow editing x and y data, only z
                # so instead, we'll remove and re-add the data.
                if plot_object:
                    plot_object.remove()

                ax = self[config.get('subplot', 1) - 1]
                plot_object = self._draw_pcolormesh(ax, **config)
                trace['plot_object'] = plot_object

                if plot_object:
                    bboxes[plot_object.axes].append(
                        plot_object.get_datalim(plot_object.axes.transData))
            else:
                for axletter in 'xy':
                    setter = 'set_' + axletter + 'data'
                    if axletter in config:
                        getattr(plot_object, setter)(config[axletter])

        for ax in self.subplots:
            if ax.get_autoscale_on():
                ax.relim()
                if bboxes[ax]:
                    bbox = Bbox.union(bboxes[ax])
                    if np.all(np.isfinite(ax.dataLim)):
                        # should take care of the case of lines + heatmaps
                        # where there's already a finite dataLim from relim
                        ax.dataLim.set(Bbox.union(ax.dataLim, bbox))
                    else:
                        # when there's only a heatmap, relim gives inf bounds
                        # so just completely overwrite it
                        ax.dataLim = bbox
                ax.autoscale()

        self.fig.canvas.draw()

    def _draw_plot(self, ax, y, x=None, fmt=None, subplot=1,
                   xlabel=None,
                   ylabel=None,
                   zlabel=None,
                   xunit=None,
                   yunit=None,
                    zunit=None,
                   **kwargs):
        # NOTE(alexj)stripping out subplot because which subplot we're in is
        # already described by ax, and it's not a kwarg to matplotlib's ax.plot.
        # But I didn't want to strip it out of kwargs earlier because it should
        # stay part of trace['config'].
        args = [arg for arg in [x, y, fmt] if arg is not None]

        line, = ax.plot(*args, **kwargs)
        return line

    def _draw_pcolormesh(self, ax, z, x=None, y=None, subplot=1,
                         xlabel=None,
                         ylabel=None,
                         zlabel=None,
                         xunit=None,
                         yunit=None,
                         zunit=None,
                         nticks=None,
                         **kwargs):
        # NOTE(alexj)stripping out subplot because which subplot we're in is already
        # described by ax, and it's not a kwarg to matplotlib's ax.plot. But I
        # didn't want to strip it out of kwargs earlier because it should stay
        # part of trace['config'].
        args_masked = [masked_invalid(arg) for arg in [x, y, z]
                      if arg is not None]

        if np.any([np.all(getmask(arg)) for arg in args_masked]):
            # if the z array is masked, don't draw at all
            # there's nothing to draw, and anyway it throws a warning
            # pcolormesh does not accept masked x and y axes, so we do not need
            # to check for them.
            return False

        if 'cmap' not in kwargs:
            kwargs['cmap'] = cm.hot

        if x is not None and y is not None:
            # If x and y are provided, modify the arrays such that they
            # correspond to grid corners instead of grid centers.
            # This is to ensure that pcolormesh centers correctly and
            # does not ignore edge points.
            args = []
            for k, arr in enumerate(args_masked[:-1]):
                # If a two-dimensional array is provided, only consider the
                # first row/column, depending on the axis
                if arr.ndim > 1:
                    arr = arr[0] if k == 0 else arr[:,0]

                if np.ma.is_masked(arr[1]):
                    # Only the first element is not nan, in this case pad with
                    # a value, and separate their values by 1
                    arr_pad = np.pad(arr, (1, 0), mode='symmetric')
                    arr_pad[:2] += [-0.5, 0.5]
                else:
                    # Add padding on both sides equal to endpoints
                    arr_pad = np.pad(arr, (1, 1), mode='symmetric')
                    # Add differences to edgepoints (may be nan)
                    arr_pad[0] += arr_pad[1] - arr_pad[2]
                    arr_pad[-1] += arr_pad[-2] - arr_pad[-3]

                    diff = np.ma.diff(arr_pad) / 2
                    # Insert value at beginning and end of diff to ensure same
                    # length
                    diff = np.insert(diff, 0, diff[0])

                    arr_pad += diff
                    # Ignore final value
                    arr_pad = arr_pad[:-1]
                args.append(masked_invalid(arr_pad))
            args.append(args_masked[-1])
        else:
            # Only the masked value of z is used as a mask
            args = args_masked[-1:]

        if 'edgecolors' not in kwargs:
            # Matplotlib pcolormesh per default are drawn as individual patches lined up next to each other
            # due to rounding this produces visible gaps in some pdf viewers. To prevent this we draw each
            # mesh with a visible edge (slightly overlapping) this assumes alpha=1 or it will produce artifacts
            # at the overlaps
            kwargs['edgecolors'] = 'face'
        pc = ax.pcolormesh(*args, **kwargs)

        # Set x and y limits if arrays are provided
        if x is not None and y is not None:
            ax.set_xlim(np.nanmin(args[0]), np.nanmax(args[0]))
            ax.set_ylim(np.nanmin(args[1]), np.nanmax(args[1]))

        # Specify preferred number of ticks with labels
        if nticks and ax.get_xscale() != 'log' and ax.get_yscale != 'log':
            ax.locator_params(nbins=nticks)

        if getattr(ax, 'qcodes_colorbar', None):
            # update_normal doesn't seem to work...
            ax.qcodes_colorbar.update_bruteforce(pc)
        else:
            # TODO: what if there are several colormeshes on this subplot,
            # do they get the same colorscale?
            # We should make sure they do, and have it include
            # the full range of both.
            ax.qcodes_colorbar = self.fig.colorbar(pc, ax=ax)

            # ideally this should have been in _update_labels, but
            # the colorbar doesn't necessarily exist there.
            # I guess we could create the colorbar no matter what,
            # and just give it a dummy mappable to start, so we could
            # put this where it belongs.
            if zunit is None:
                _, zunit = self.get_label(z)
            if zlabel is None:
                zlabel, _ = self.get_label(z)

            label = "{} ({})".format(zlabel, zunit)
            ax.qcodes_colorbar.set_label(label)

        # Scale colors if z has elements
        cmin = np.nanmin(args_masked[-1])
        cmax = np.nanmax(args_masked[-1])
        ax.qcodes_colorbar.set_clim(cmin, cmax)

        return pc

    def save(self, filename=None):
        """
        Save current plot to filename, by default
        to the location corresponding to the default 
        title.

        Args:
            filename (Optional[str]): Location of the file
        """
        default = "{}.png".format(self.get_default_title())
        filename = filename or default
        self.fig.savefig(filename)

    def tight_layout(self):
        """
        Perform a tight layout on the figure. A bit of additional spacing at
        the top is also added for the title.
        """
        self.fig.tight_layout(rect=[0, 0, 1, 0.95])

class ClickWidget(BasePlot):

    def __init__(self, dataset):
        super().__init__()
        data = {}
        self.expand_trace(args=[dataset], kwargs=data)
        self.traces = []

        data['xlabel'] = self.get_label(data['x'])
        data['ylabel'] = self.get_label(data['y'])
        data['zlabel'] = self.get_label(data['z'])
        data['xaxis'] = data['x'].ndarray[0, :]
        data['yaxis'] = data['y'].ndarray
        self.traces.append({
            'config': data,
        })
        self.fig = plt.figure()

        self._lines = []
        self._datacursor = []
        self._cid = 0

        hbox = QtWidgets.QHBoxLayout()
        self.fig.canvas.setLayout(hbox)
        hspace = QtWidgets.QSpacerItem(0,
                                       0,
                                       QtWidgets.QSizePolicy.Expanding,
                                       QtWidgets.QSizePolicy.Expanding)
        vspace = QtWidgets.QSpacerItem(0,
                                       0,
                                       QtWidgets.QSizePolicy.Minimum,
                                       QtWidgets.QSizePolicy.Expanding)
        hbox.addItem(hspace)

        vbox = QtWidgets.QVBoxLayout()
        self.crossbtn = QtWidgets.QCheckBox('Cross section')
        self.crossbtn.setToolTip("Display extra subplots with selectable cross sections "
                                 "or sums along axis.")
        self.sumbtn = QtWidgets.QCheckBox('Sum')
        self.sumbtn.setToolTip("Display sums or cross sections.")

        self.savehmbtn = QtWidgets.QPushButton('Save Heatmap')
        self.savehmbtn.setToolTip("Save heatmap as a file (PDF)")
        self.savexbtn = QtWidgets.QPushButton('Save Vert')
        self.savexbtn.setToolTip("Save vertical cross section or sum as a file (PDF)")
        self.saveybtn = QtWidgets.QPushButton('Save Horz')
        self.savexbtn.setToolTip("Save horizontal cross section or sum as a file (PDF)")

        self.crossbtn.toggled.connect(self.toggle_cross)
        self.sumbtn.toggled.connect(self.toggle_sum)

        self.savehmbtn.pressed.connect(self.save_heatmap)
        self.savexbtn.pressed.connect(self.save_subplot_x)
        self.saveybtn.pressed.connect(self.save_subplot_y)

        self.toggle_cross()
        self.toggle_sum()

        vbox.addItem(vspace)
        vbox.addWidget(self.crossbtn)
        vbox.addWidget(self.sumbtn)
        vbox.addWidget(self.savehmbtn)
        vbox.addWidget(self.savexbtn)
        vbox.addWidget(self.saveybtn)

        hbox.addLayout(vbox)

    @staticmethod
    def full_extent(ax, pad=0.0):
        """Get the full extent of an axes, including axes labels, tick labels, and
        titles."""
        # For text objects, we need to draw the figure first, otherwise the extents
        # are undefined.
        from matplotlib.transforms import Bbox
        items = ax.get_xticklabels() + ax.get_yticklabels()
        items += [ax.xaxis.label, ax.yaxis.label]
        items += [ax, ax.title]
        bbox = Bbox.union([item.get_window_extent() for item in items])

        return bbox.expanded(1.0 + pad, 1.0 + pad)

    def save_subplot(self, axnumber, savename, format='pdf'):
        extent = self.full_extent(self.ax[axnumber]).transformed(self.fig.dpi_scale_trans.inverted())
        full_title =  "{}.{}".format(savename, format)
        self.fig.savefig(full_title, bbox_inches=extent)

    def save_subplot_x(self):
        title = self.get_default_title()
        if self.sumbtn.isChecked():
            title += " sum over {}".format(self.traces[0]['config']['xlabel'])
        else:
            title += " cross section {} = {}".format(self.traces[0]['config']['xlabel'],
                                                     self.traces[0]['config']['xpos'])
        self.save_subplot(axnumber=(0,1), savename=title)

    def save_subplot_y(self):
        title = self.get_default_title()
        if self.sumbtn.isChecked():
            title += " sum over {}".format(self.traces[0]['config']['ylabel'])
        else:
            title += " cross section {} = {}".format(self.traces[0]['config']['ylabel'],
                                                     self.traces[0]['config']['ypos'])
        self.save_subplot(axnumber=(1,0), savename=title)

    def save_heatmap(self):
        title = self.get_default_title() + " heatmap"
        self.save_subplot(axnumber=(0, 0), savename=title)

    def toggle_cross(self):
        self.remove_plots()
        self.fig.clear()
        if self._cid:
            self.fig.canvas.mpl_disconnect(self._cid)
        if self.crossbtn.isChecked():
            self.sumbtn.setEnabled(True)
            self.savexbtn.setEnabled(True)
            self.saveybtn.setEnabled(True)
            self.ax = np.empty((2, 2), dtype='O')
            self.ax[0, 0] = self.fig.add_subplot(2, 2, 1)
            self.ax[0, 1] = self.fig.add_subplot(2, 2, 2)
            self.ax[1, 0] = self.fig.add_subplot(2, 2, 3)
            self._cid = self.fig.canvas.mpl_connect('button_press_event', self._click)
            self._cursor = Cursor(self.ax[0, 0], useblit=True, color='black')
            self.toggle_sum()
            figure_rect = (0, 0, 1, 1)
        else:
            self.sumbtn.setEnabled(False)
            self.savexbtn.setEnabled(False)
            self.saveybtn.setEnabled(False)
            self.ax = np.empty((1, 1), dtype='O')
            self.ax[0, 0] = self.fig.add_subplot(1, 1, 1)
            figure_rect = (0, 0.0, 0.75, 1)
        self.ax[0, 0].pcolormesh(self.traces[0]['config']['x'],
                                 self.traces[0]['config']['y'],
                                 self.traces[0]['config']['z'],
                                 edgecolor='face')
        self.ax[0, 0].set_xlabel(self.traces[0]['config']['xlabel'])
        self.ax[0, 0].set_ylabel(self.traces[0]['config']['ylabel'])
        self.fig.tight_layout(rect=figure_rect)
        self.fig.canvas.draw_idle()

    def toggle_sum(self):
        self.remove_plots()
        if not self.crossbtn.isChecked():
            return
        self.ax[1,0].clear()
        self.ax[0,1].clear()
        if self.sumbtn.isChecked():
            self._cursor.set_active(False)
            self.ax[1, 0].set_ylim(0, self.traces[0]['config']['z'].sum(axis=0).max() * 1.05)
            self.ax[0, 1].set_xlim(0, self.traces[0]['config']['z'].sum(axis=1).max() * 1.05)
            self.ax[1, 0].set_xlabel(self.traces[0]['config']['xlabel'])
            self.ax[1, 0].set_ylabel("sum of " + self.traces[0]['config']['zlabel'])
            self.ax[0, 1].set_xlabel("sum of " + self.traces[0]['config']['zlabel'])
            self.ax[0, 1].set_ylabel(self.traces[0]['config']['ylabel'])
            self._lines.append(self.ax[0, 1].plot(self.traces[0]['config']['z'].sum(axis=1),
                                                  self.traces[0]['config']['yaxis'],
                                                  color='C0',
                                                  marker='.')[0])
            self.ax[0, 1].set_title("")
            self._lines.append(self.ax[1, 0].plot(self.traces[0]['config']['xaxis'],
                                                  self.traces[0]['config']['z'].sum(axis=0),
                                                  color='C0',
                                                  marker='.')[0])
            self.ax[1, 0].set_title("")
            self._datacursor = mplcursors.cursor(self._lines, multiple=False)
        else:
            self._cursor.set_active(True)
            self.ax[1, 0].set_xlabel(self.traces[0]['config']['xlabel'])
            self.ax[1, 0].set_ylabel(self.traces[0]['config']['zlabel'])
            self.ax[0, 1].set_xlabel(self.traces[0]['config']['zlabel'])
            self.ax[0, 1].set_ylabel(self.traces[0]['config']['ylabel'])
            self.ax[1, 0].set_ylim(0, self.traces[0]['config']['z'].max() * 1.05)
            self.ax[0, 1].set_xlim(0, self.traces[0]['config']['z'].max() * 1.05)
        self.fig.canvas.draw_idle()

    def remove_plots(self):
        for line in self._lines:
            line.remove()
        self._lines = []
        if self._datacursor:
            self._datacursor.remove()

    def _click(self, event):

        if event.inaxes == self.ax[0, 0] and not self.sumbtn.isChecked():
            xpos = (abs(self.traces[0]['config']['xaxis'] - event.xdata)).argmin()
            ypos = (abs(self.traces[0]['config']['yaxis'] - event.ydata)).argmin()
            self.remove_plots()

            self._lines.append(self.ax[0, 1].plot(self.traces[0]['config']['z'][:, xpos],
                                                  self.traces[0]['config']['yaxis'],
                                                  color='C0',
                                                  marker='.')[0])
            self.ax[0,1].set_title("{} = {} ".format(self.traces[0]['config']['xlabel'],
                                                     self.traces[0]['config']['xaxis'][xpos]),
                                   fontsize='small')
            self.traces[0]['config']['xpos'] = self.traces[0]['config']['xaxis'][xpos]
            self._lines.append(self.ax[1, 0].plot(self.traces[0]['config']['xaxis'],
                                                  self.traces[0]['config']['z'][ypos, :],
                                                  color='C0',
                                                  marker='.')[0])
            self.ax[1, 0].set_title("{} = {} ".format(self.traces[0]['config']['ylabel'],
                                                      self.traces[0]['config']['yaxis'][ypos]),
                                    fontsize='small')
            self.traces[0]['config']['ypos'] = self.traces[0]['config']['yaxis'][ypos]
            self._datacursor = mplcursors.cursor(self._lines, multiple=False)
            self.fig.canvas.draw_idle()
