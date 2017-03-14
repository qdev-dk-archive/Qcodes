import qcodes as qc
from os.path import abspath
from os.path import sep
from os import makedirs
import logging
from qcodes.plots.pyqtgraph import QtPlot
from qcodes.plots.qcmatplotlib import MatPlot
from IPython import get_ipython
from matplotlib import cm
CURRENT_EXPERIMENT  = {}
CURRENT_EXPERIMENT["logging_enabled"] = False

def init(mainfolder:str, sample_name: str):
    """

    Args:
        mainfolder:  base location for the data
        sample_name:  name of the sample

    """
    if sep in sample_name:
        raise  TypeError("Use Relative names. That is wihtout {}".format(sep))
    # always remove trailing sep in the main folder
    if mainfolder[-1] ==  sep:
        mainfolder = mainfolder[:-1]

    mainfolder = abspath(mainfolder)

    CURRENT_EXPERIMENT["mainfolder"]  =  mainfolder
    CURRENT_EXPERIMENT["sample_name"] = sample_name
    CURRENT_EXPERIMENT['init']  = True

    path_to_experiment_folder = sep.join([mainfolder, sample_name, ""])
    CURRENT_EXPERIMENT["exp_folder"] = path_to_experiment_folder


    try:
        makedirs(path_to_experiment_folder)
    except FileExistsError:
        pass

    logging.info("experiment started at {}".format(path_to_experiment_folder))

    loc_provider = qc.FormatLocation(
        fmt= path_to_experiment_folder + '{counter}')
    qc.data.data_set.DataSet.location_provider = loc_provider
    CURRENT_EXPERIMENT["provider"] = loc_provider

    ipython = get_ipython()
    # turn on logging only if in ipython
    # else crash and burn
    if ipython is None:
        raise RuntimeWarning("History can't be saved refusing to proceed (use IPython/jupyter)")
    else:
        logfile = "{}{}".format(path_to_experiment_folder, "commands.log")
        if not CURRENT_EXPERIMENT["logging_enabled"]:
            logging.debug("Logging commands to: t{}".format(logfile))
            ipython.magic("%logstart -t {} {}".format(logfile, "append"))
            CURRENT_EXPERIMENT["logging_enabled"] = True
        else:
            logging.debug("Logging already started at {}".format(logfile))


def _plot_setup(data, inst_meas, useQT=True):
    title = "{} #{:03d}".format(CURRENT_EXPERIMENT["sample_name"], data.location_provider.counter)
    if useQT:
        plot = QtPlot()
    else:
        plot = MatPlot()
    for j, i in enumerate(inst_meas):
        if getattr(i, "names", False):
            # deal with multidimensional parameter
            for k, name in enumerate(i.names):
                inst_meas_name = "{}_{}".format(i._instrument.name, name)
                plot.add(getattr(data, inst_meas_name), subplot=j + k + 1)
                if useQT:
                    plot.subplots[j+k].showGrid(True, True)
                    if j == 0:
                        plot.subplots[0].setTitle(title)
                    else:
                        plot.subplots[j+k].setTitle("")
                else:
                    plot.subplots[j+k].grid()
                    if j == 0:
                        plot.subplots[0].set_title(title)
                    else:
                        plot.subplots[j+k].set_title("")
        else:
            # simple_parameters
            inst_meas_name = "{}_{}".format(i._instrument.name, i.name)
            plot.add(getattr(data, inst_meas_name), subplot=j + 1)
            if useQT:
                plot.subplots[j].showGrid(True, True)
                if j == 0:
                    plot.subplots[0].setTitle(title)
                else:
                    plot.subplots[j].setTitle("")
            else:
                plot.subplots[j].grid()
                if j == 0:
                    plot.subplots[0].set_title(title)
                else:
                    plot.subplots[j].set_title("")
    return plot

def do1d(inst_set, start, stop, division, delay, *inst_meas):
    """

    Args:
        inst_set:  Instrument to sweep over
        start:  Start of sweep
        stop:  End of sweep
        division:  Spacing between values
        delay:  Delay at every step
        *inst_meas:  any number of instrument to measure

    Returns:
        plot, data : returns the plot and the dataset

    """
    loop = qc.Loop(inst_set.sweep(start, stop, division), delay).each(*inst_meas)
    data = loop.get_data_set()
    plot = _plot_setup(data, inst_meas)
    try:
        _ = loop.with_bg_task(plot.update, plot.save).run()
    except KeyboardInterrupt:
        print("Measurement Interrupted")
    staticplot = _plot_setup(data, inst_meas, useQT=False)
    staticplot.save(staticplot.get_default_title()+'.pdf')
    return plot, data


def do1dDiagonal(inst_set, inst2_set, start, stop, division, delay, start2, slope, *inst_meas):
    """
    Perform diagonal sweep in 1 dimension, given two instruments

    Args:
        inst_set:  Instrument to sweep over
        inst2_set: Second instrument to sweep over
        start:  Start of sweep
        stop:  End of sweep
        division:  Spacing between values
        delay:  Delay at every step
        start2:  Second start point
        slope:  slope of the diagonal cut
        *inst_meas:  any number of instrument to measure

    Returns:
        plot, data : returns the plot and the dataset

    """
    loop = qc.Loop(inst_set.sweep(start, stop, division), delay).each(
        qc.Task(inst2_set, (inst_set) * slope + (slope * start - start2)), *inst_meas, inst2_set)
    data = loop.get_data_set()
    plot = _plot_setup(data, inst_meas)
    try:
        _ = loop.with_bg_task(plot.update, plot.save).run()
    except KeyboardInterrupt:
        print("Measurement Interrupted")
    staticplot = _plot_setup(data, inst_meas, useQT=False)
    staticplot.save(staticplot.get_default_title()+'.pdf')
    return plot, data


def do2d(inst_set, start, stop, division, delay, inst_set2, start2, stop2, division2, delay2, *inst_meas):
    """

    Args:
        inst_set:  Instrument to sweep over
        start:  Start of sweep
        stop:  End of sweep
        division:  Spacing between values
        delay:  Delay at every step
        inst_set_2:  Second instrument to sweep over
        start_2:  Start of sweep for second instrument
        stop_2:  End of sweep for second instrument
        division_2:  Spacing between values for second instrument
        delay_2:  Delay at every step for second instrument
        *inst_meas:

    Returns:
        plot, data : returns the plot and the dataset

    """
    for inst in inst_meas:
        if getattr(inst, "setpoints", False):
            raise ValueError("3d plotting is not supported")

    loop = qc.Loop(inst_set.sweep(start, stop, division), delay).loop(inst_set2.sweep(start2,stop2,division2), delay2).each(
        *inst_meas)
    data = loop.get_data_set()
    plot = _plot_setup(data, inst_meas)
    try:
        _ = loop.with_bg_task(plot.update, plot.save).run()
    except KeyboardInterrupt:
        print("Measurement Interrupted")
    staticplot = _plot_setup(data, inst_meas, useQT=False)
    staticplot.save(staticplot.get_default_title()+'.pdf')
    return plot, data


def show_num(id):
    """
    Show  and return plot and data for id in current instrument.
    Args:
        id(number): id of instrument

    Returns:
        plot, data : returns the plot and the dataset

    """
    if not getattr(CURRENT_EXPERIMENT, "init", True):
        raise RuntimeError("Experiment not initalized. use qc.Init(mainfolder, samplename)")

    str_id = '{0:03d}'.format(id)

    t = qc.DataSet.location_provider.fmt.format(counter=str_id)
    data = qc.load_data(t)

    plots = []
    for value in data.arrays.keys():
        if "set" not in value:
            plot = QtPlot(getattr(data, value))
            title = "{} #{}".format(CURRENT_EXPERIMENT["sample_name"], str_id)
            plot.subplots[0].setTitle(title)
            plot.subplots[0].showGrid(True, True)
            plots.append(plot)
    return data, plots
