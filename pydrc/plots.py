import plotly.graph_objs as go
import numpy as np
import seaborn as sns
from .helpers import format_dose
from .curve_fit import ll4


SECONDS_IN_HOUR = 3600.0
PLOT_AXIS_LABELS = {'auc': 'Area under curve (AUC)',
                    'ic50': 'IC50',
                    'ec50': 'EC50',
                    'emax': 'Emax',
                    'hill': 'Hill coefficient'}


def plot_dip(fit_params, is_absolute=False,
             title=None, hill_fn=ll4):

    colours = sns.color_palette("husl", len(fit_params))

    yaxis_title = 'DIP rate'
    if not is_absolute:
        yaxis_title = 'Relative ' + yaxis_title

    show_replicates = len(fit_params) == 1

    annotations = []
    traces = []
    for trace_idx, fp in enumerate(fit_params):
        c = colours.pop()
        this_colour = 'rgb(%d, %d, %d)' % \
                      (c[0] * 255, c[1] * 255, c[2] * 255)
        group_name_disp = fp['label']

        popt_plot = fp['popt'] if is_absolute else fp['popt_rel']

        doses = np.concatenate((fp['doses_ctrl'], fp['doses_expt']))

        # Calculate the dip rate fit
        log_dose_min = int(np.floor(np.log10(min(doses))))
        log_dose_max = int(np.ceil(np.log10(max(doses))))

        dose_x_range = np.concatenate(
            # [np.arange(2, 11) * 10 ** dose_mag
            [0.5 * np.arange(3, 21) * 10 ** dose_mag
             for dose_mag in range(log_dose_min, log_dose_max + 1)],
            axis=0)

        dose_x_range = np.append([10 ** log_dose_min], dose_x_range,
                                 axis=0)

        if popt_plot is None:
            dip_rate_fit = [1 if not is_absolute else fp['divisor']] * \
                           len(dose_x_range)
        else:
            dip_rate_fit = hill_fn(dose_x_range, *popt_plot)

        traces.append(go.Scatter(x=dose_x_range,
                                 y=dip_rate_fit,
                                 mode='lines',
                                 line={'shape': 'spline',
                                       'color': this_colour,
                                       'dash': 5 if popt_plot is None else
                                       'solid',
                                       'width': 3},
                                 legendgroup=group_name_disp,
                                 showlegend=not show_replicates,
                                 name=group_name_disp)
                      )

        if show_replicates:
            y_trace = fp['dip_expt']
            dip_ctrl = fp['dip_ctrl']
            if not is_absolute:
                y_trace /= fp['divisor']
                dip_ctrl /= fp['divisor']

            traces.append(go.Scatter(x=fp['doses_expt'],
                                     y=y_trace,
                                     mode='markers',
                                     line={'shape': 'spline',
                                           'color': this_colour,
                                           'width': 3},
                                     legendgroup=group_name_disp,
                                     showlegend=False,
                                     name='Replicate',
                                     marker={'size': 5})
                          )
            traces.append(go.Scatter(x=fp['doses_ctrl'],
                                     y=dip_ctrl,
                                     mode='markers',
                                     line={'shape': 'spline',
                                           'color': 'black',
                                           'width': 3},
                                     hoverinfo='y+text',
                                     text='Control',
                                     legendgroup=group_name_disp,
                                     showlegend=False,
                                     marker={'size': 5})
                          )

            annotation_label = ''
            if fp['ec50'] is not None:
                annotation_label += 'EC50: {} '.format(format_dose(
                    fp['ec50'], sig_digits=5
                ))
            if fp['ic50'] is not None:
                annotation_label += 'IC50: {} '.format(format_dose(
                    fp['ic50'], sig_digits=5
                ))
            if fp['emax'] is not None:
                annotation_label += 'Emax: {0:.5g}'.format(fp['emax'])
            if annotation_label:
                annotations.append({
                    'x': 0.5,
                    'y': 1.1,
                    'xref': 'paper',
                    'yref': 'paper',
                    'showarrow': False,
                    'text': annotation_label
                })
    data = go.Data(traces)
    layout = go.Layout(title=title,
                       hovermode='closest' if show_replicates else 'x',
                       xaxis={'title': 'Dose (M)',
                              'range': np.log10((1e-12, 1e-5)),
                              'type': 'log'},
                       yaxis={'title': yaxis_title,
                              'range': (-0.02, 0.07) if is_absolute else
                              (-0.2, 1.2)
                              },
                       annotations=annotations,
                       )

    return go.Figure(data=data, layout=layout)


def plot_dip_params(fit_params, fit_params_sort, title=None, **kwargs):
    # Sort lists by chosen index. The sort order key ensures that Nones
    # appear at the start of the sort.
    fit_params = sorted(fit_params, key=lambda x:
        (x[fit_params_sort] is not None, x[fit_params_sort])
    )
    groups = [fp['label'] for fp in fit_params]

    yaxis_title = PLOT_AXIS_LABELS.get(fit_params_sort, fit_params_sort)
    yvals = [fp[fit_params_sort] for fp in fit_params]
    data = [go.Bar(x=groups, y=yvals)]
    annotations = [{'x': x, 'y': 0, 'text': '<em>N/A</em>',
                    'textangle': 90,
                    'xanchor': 'center', 'yanchor': 'bottom',
                    'showarrow': False,
                    'font': {'color': 'rgba(150, 150, 150, 1)'}}
                   for x, y in zip(groups, yvals) if y is None]

    layout = go.Layout(title=title,
                       barmode='group',
                       annotations=annotations,
                       yaxis={'title': yaxis_title,
                              'type': 'log' if kwargs.get('log_yaxis',
                                                          False) else None})

    return go.Figure(data=data, layout=layout)


def plot_time_course(df_doses, df_vals, df_controls,
                     log_yaxis=False, assay_name='Assay', title=None):
    traces = []

    colours = sns.color_palette("husl", len(df_doses.index.get_level_values(
        level='dose').unique()))

    # Controls
    if df_controls is not None:
        is_first_control = True
        for well_id, timecourse in df_controls.groupby(level='well_id'):
            timecourse = timecourse['value']
            if log_yaxis:
                timecourse = np.log2(timecourse)
                timecourse -= timecourse[0]
            traces.append(go.Scatter(
                x=[t.total_seconds() / SECONDS_IN_HOUR for t in
                   timecourse.index.get_level_values('timepoint')],
                y=timecourse,
                mode='lines+markers',
                line={'color': 'black',
                      'shape': 'spline'},
                marker={'size': 5},
                name='Control',
                legendgroup='__Control',
                showlegend=is_first_control
            ))
            is_first_control = False

    # Experiment (non-control)
    for dose, wells in df_doses.groupby(level='dose'):
        c = colours.pop()
        this_colour = 'rgb(%d, %d, %d)' % (c[0] * 255, c[1] * 255, c[2] * 255)

        for well_idx, well_id in enumerate(wells['well_id']):
            timecourse = df_vals.loc[well_id, 'value']
            if log_yaxis:
                timecourse = np.log2(timecourse)
                timecourse -= timecourse[0]
            traces.append(go.Scatter(
                x=[t.total_seconds() / SECONDS_IN_HOUR for t in
                   timecourse.index.get_level_values('timepoint')],
                y=timecourse,
                mode='lines+markers',
                line={'color': this_colour,
                      'shape': 'spline'},
                marker={'size': 5},
                name=format_dose(dose),
                legendgroup=str(dose),
                showlegend=well_idx == 0
            ))

    data = go.Data(traces)
    if log_yaxis:
        assay_name = "Change in log2 {}".format(assay_name)
    max_time = df_vals.index.get_level_values('timepoint').max()
    layout = go.Layout(title=title,
                       xaxis={'title': 'Time (hours)',
                              'range': (0, 120) if max_time <=
                                       np.timedelta64(120, 'h') else None,
                              'dtick': 12},
                       yaxis={'title': assay_name,
                              'range': (-2, 7) if log_yaxis else None},
                       )
    return go.Figure(data=data, layout=layout)
