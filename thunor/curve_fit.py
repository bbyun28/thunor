import numpy as np
import scipy.optimize
import scipy.stats
from abc import abstractclassmethod, abstractmethod
import pandas as pd

PARAM_EQUAL_ATOL = 1e-16
PARAM_EQUAL_RTOL = 1e-12


class ValueWarning(UserWarning):
    pass


class AUCFitWarning(ValueWarning):
    pass


class AAFitWarning(ValueWarning):
    pass


class DrugCombosNotImplementedError(NotImplementedError):
    """ This function does not support drug combinations yet """
    pass


class HillCurve(object):
    """ Base class defining Hill/log-logistic curve functionality """
    def __init__(self, popt):
        self.popt = popt

    @abstractclassmethod
    def fit_fn(cls, x, *params):
        pass

    def fit(self, x):
        return self.fit_fn(x, *self.popt)

    @abstractclassmethod
    def initial_guess(cls, x, y):
        pass

    @abstractmethod
    def divisor(self):
        pass

    @abstractmethod
    def ec50(self):
        pass

    @abstractmethod
    def e0(self):
        pass

    @abstractmethod
    def emax(self):
        pass

    @abstractmethod
    def hill_slope(self):
        pass


class HillCurveNull(HillCurve):
    @classmethod
    def fit_fn(cls, x, ymean):
        return ymean

    @classmethod
    def initial_guess(cls, x, y):
        return np.mean(y)

    @property
    def divisor(self):
        return self.popt

    def ic(self, ic_num=50):
        return None

    def ec(self, ec_num=50):
        return None

    def hill_slope(self):
        return None


class HillCurveLL4(HillCurve):
    def __init__(self, popt):
        super(HillCurveLL4, self).__init__(popt)
        self._popt_rel = None

    @classmethod
    def fit_fn(cls, x, b, c, d, e):
        """
        Four parameter log-logistic function ("Hill curve")

        Parameters
        ----------
        x: np.ndarray
            One-dimensional array of "x" values
        b: float
            Hill slope
        c: float
            Minimum response (lower plateau)
        d: float
            Maximum response (upper plateau)
        e: float
            EC50 value

        Returns
        -------
        np.ndarray
            Array of "y" values using the supplied curve fit parameters on "x"
        """
        return c + (d - c) / (1 + np.exp(b * (np.log(x) - np.log(e))))

    @classmethod
    def initial_guess(cls, x, y):
        """
        Heuristic function for initial fit values

        Uses the approach followed by R's drc library:
        https://cran.r-project.org/web/packages/drc/index.html

        Parameters
        ----------
        x: np.ndarray
            Array of "x" (dose) values
        y: np.ndarray
            Array of "y" (response) values

        Returns
        -------
        list
            Four-valued list corresponding to initial estimates of the
            parameters defined in the :func:`ll4` function.
        """
        c_val, d_val = _find_cd_ll4(y)
        b_val, e_val = _find_be_ll4(x, y, c_val, d_val)

        return b_val, c_val, d_val, e_val

    @property
    def ec50(self):
        return self.popt[3]

    @property
    def e0(self):
        return self.popt[2]

    @property
    def emax(self):
        return self.popt[1]

    @property
    def hill_slope(self):
        return self.popt[0]

    def ic(self, ic_num=50):
        """
        Find the inhibitory concentration value (e.g. IC50)

        Parameters
        ----------
        ic_num: int
            IC number between 0 and 100 (response level)

        Returns
        -------
        float
            Inhibitory concentration value for requested response value
        """
        emax = self.emax
        if not isinstance(emax, float):
            return None
        e0 = self.e0
        if emax > e0:
            emax, e0 = e0, emax

        ic_frac = ic_num / 100.0

        icN = self.ec50 * (ic_frac / (1 - ic_frac - (emax / e0))) ** (
                           1 / self.hill_slope)

        if np.isnan(icN):
            icN = None

        return icN

    def ec(self, ec_num=50):
        """
        Find the effective concentration value (e.g. IC50)

        Parameters
        ----------
        ec_num: int
            EC number between 0 and 100 (response level)

        Returns
        -------
        float
            Effective concentration value for requested response value
        """
        if ec_num >= 100:
            return None

        ec_frac = ec_num / 100.0

        return self.ec50 * (ec_frac / (1 - ec_frac)) ** (1 / self.hill_slope)

    def auc(self, min_conc):
        """
        Find the area under the curve

        Parameters
        ----------
        min_conc: float
            Minimum concentration to consider for fitting the curve

        Returns
        -------
        float
            Area under the curve (AUC) value
        """
        emax = self.emax
        if not isinstance(emax, float):
            return None
        e0 = self.e0
        if emax > e0:
            emax, e0 = e0, emax
        min_conc_hill = min_conc ** self.hill_slope
        return (np.log10(
            (self.ec50 ** self.hill_slope + min_conc_hill) / min_conc_hill) /
                self.hill_slope) * ((e0 - emax) / e0)

    def aa(self, max_conc, emax_obs=None):
        """
        Find the activity area (area over the curve)

        Parameters
        ----------
        max_conc: float
            Maximum concentration to consider for fitting the curve
        emax_obs: float, optional
            Observed Emax value

        Returns
        -------
        float
            Activity area value
        """
        emax = self.emax
        if not isinstance(emax, float):
            return None
        e0 = self.e0
        if emax > e0:
            emax, e0 = e0, emax

        if emax_obs is not None:
            emax = emax_obs

        ec50_hill = self.ec50 ** self.hill_slope

        return np.log10((ec50_hill + max_conc ** self.hill_slope) /
                        ec50_hill) * ((e0 - emax) / e0) / self.hill_slope

    @property
    def divisor(self):
        return max(self.emax, self.e0)

    @property
    def popt_rel(self):
        if self._popt_rel is None:
            self._popt_rel = self.popt.copy()
            self.popt_rel[2] /= self.divisor
            self.popt_rel[1] /= self.divisor
        return self._popt_rel

    def fit_rel(self, x):
        return self.fit_fn(x, *self.popt_rel)


class HillCurveLL3u(HillCurveLL4):
    @classmethod
    def fit_fn(cls, x, b, c, e):
        """
        Three parameter log-logistic function ("Hill curve")

        Parameters
        ----------
        x: np.ndarray
            One-dimensional array of "x" values
        b: float
            Hill slope
        c: float
            Minimum response (lower plateau)
        e: float
            EC50 value

        Returns
        -------
        np.ndarray
            Array of "y" values using the supplied curve fit parameters on "x"
        """
        return super(HillCurveLL3u, cls).fit_fn(x, b, c, 1.0, e)

    @classmethod
    def initial_guess(cls, x, y):
        b, c, _, e = super(HillCurveLL3u, cls).initial_guess(x, y)
        return b, c, e

    @property
    def ec50(self):
        return self.popt[2]

    @property
    def e0(self):
        return 1.0

    @property
    def popt_rel(self):
        if self._popt_rel is None:
            self._popt_rel = self.popt.copy()
            self._popt_rel[1] /= self.divisor
        return self._popt_rel


class HillCurveLL2(HillCurveLL3u):
    @classmethod
    def fit_fn(cls, x, b, e):
        """
        Two parameter log-logistic function ("Hill curve")

        Parameters
        ----------
        x: np.ndarray
            One-dimensional array of "x" values
        b: float
            Hill slope
        e: float
            EC50 value

        Returns
        -------
        np.ndarray
            Array of "y" values using the supplied curve fit parameters on "x"
        """
        return super(HillCurveLL3u, cls).fit_fn(x, b, 0.0, 1.0, e)

    @classmethod
    def initial_guess(cls, x, y):
        b, _, _, e = super(HillCurveLL3u, cls).initial_guess(x, y)
        return b, e

    @property
    def ec50(self):
        return self.popt[1]

    @property
    def e0(self):
        return 1.0

    @property
    def emax(self):
        return 0.0

    @property
    def popt_rel(self):
        if self._popt_rel is None:
            self._popt_rel = self.popt.copy()
        return self._popt_rel


def fit_drc(doses, responses, response_std_errs=None, fit_cls=HillCurveLL4,
            null_rejection_threshold=0.05, ctrl_dose=None):
    """
    Fit a dose response curve

    Parameters
    ----------
    doses: np.ndarray
        Array of dose values
    responses: np.ndarray
        Array of response values, e.g. viability, DIP rates
    response_std_errs: np.ndarray, optional
        Array of fit standard errors for the response values
    fit_cls: Class
        Class to use for fitting (default: 4 parameter log logistic
        "Hill" curve)
    null_rejection_threshold: float, optional
        p-value for rejecting curve fit against no effect "flat" response
        model by F-test (default: 0.05). Set to None to skip test.
    ctrl_dose: float, optional
        Enter the dose used to represent control values, if you wish to reject
        fits where E0 is not greater than a standard deviation higher than the
        mean of the control response values. Leave as None to skip the test.

    Returns
    -------
    HillCurve
        A HillCurve object containing the fit parameters
    """
    # Remove any NaNs
    response_nans = np.isnan(responses)
    if np.any(response_nans):
        doses = doses[~response_nans]
        responses = responses[~response_nans]
        if response_std_errs is not None:
            response_std_errs = response_std_errs[~response_nans]

    # Sort the data - curve fit can be sensitive to order!
    try:
        if response_std_errs is None:
            doses, responses = zip(*sorted(zip(doses, responses)))
        else:
            doses, responses, response_std_errs = zip(*sorted(zip(
                doses, responses, response_std_errs)))
    except ValueError:
        # Occurs when doses/responses is empty
        return None

    curve_initial_guess = fit_cls.initial_guess(doses, responses)
    try:
        popt, pcov = scipy.optimize.curve_fit(fit_cls.fit_fn,
                                              doses,
                                              responses,
                                              p0=curve_initial_guess,
                                              sigma=response_std_errs
                                              )
    except RuntimeError:
        # Some numerical issue with curve fitting
        return None

    if any(np.isnan(popt)):
        # Ditto
        return None

    fit_obj = fit_cls(popt)

    if null_rejection_threshold is not None:
        response_curve = fit_obj.fit(doses)

        # F test vs flat linear "no effect" fit
        ssq_model = ((response_curve - responses) ** 2).sum()
        ssq_null = ((np.mean(responses) - responses) ** 2).sum()

        df = len(doses) - 4

        f_ratio = (ssq_null-ssq_model)/(ssq_model/df)
        p = 1 - scipy.stats.f.cdf(f_ratio, 1, df)

        if p > null_rejection_threshold:
            return HillCurveNull(np.mean(responses))

    if fit_obj.ec50 < np.min(doses):
        # Reject fit if EC50 less than min dose
        return None

    if ctrl_dose is not None:
        controls = responses[np.equal(doses, ctrl_dose)]
        if fit_obj.e0 > (np.mean(controls) + np.std(controls)):
            return None

    return fit_obj


def _response_transform(y, c_val, d_val):
    return np.log((d_val - y) / (y - c_val))


def _find_be_ll4(x, y, c_val, d_val, slope_scaling_factor=1,
                 dose_transform=np.log,
                 dose_inv_transform=np.exp):
    slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(
        dose_transform(x),
        _response_transform(y, c_val, d_val)
    )
    b_val = slope_scaling_factor * slope
    e_val = dose_inv_transform(-intercept / (slope_scaling_factor * b_val))

    return b_val, e_val


def _find_cd_ll4(y, scale=0.001):
    ymin = np.min(y)
    ymax = np.max(y)
    len_y_range = scale * (ymax - ymin)

    return ymin - len_y_range, ymax + len_y_range


def _get_control_responses(ctrl_dip_data, dataset, cl_name, dip_grp):
    if ctrl_dip_data is None:
        return None

    if dataset is not None and 'dataset' in ctrl_dip_data.index.names:
        ctrl_dip_data_cl = ctrl_dip_data.loc[dataset]
    else:
        ctrl_dip_data_cl = ctrl_dip_data

    ctrl_dip_data_cl = ctrl_dip_data_cl.loc[cl_name]

    # Only use controls from the same plates as the expt
    if 'plate' in dip_grp.index.names:
        plates = dip_grp.index.get_level_values('plate').unique().values
    elif 'plate' in dip_grp.columns:
        plates = dip_grp['plate'].unique()
    else:
        plates = []
    ctrl_dip_data_cl = ctrl_dip_data_cl.loc[plates]

    return ctrl_dip_data_cl

# Parameter fitting section #


def fit_params_minimal(ctrl_data, expt_data,
                       fit_cls=HillCurveLL4,
                       ctrl_dose_fn=lambda doses: np.min(doses) / 10.0):
    """
    Fit dose response curves to DIP or viability, and calculate statistics

    This function only fits curves and stores basic fit parameters. Use
    :func:`fit_params` for more statistics and parameters.

    Parameters
    ----------
    ctrl_data: pd.DataFrame or None
        Control DIP rates from :func:`dip_rates` or :func:`ctrl_dip_rates`.
        Set to None to not use control data.
    expt_data: pd.DataFrame
        Experiment (non-control) DIP rates from :func:`dip_rates` or
        :func:`expt_dip_rates`
    fit_cls: Class
        Class to use for curve fitting (default: :func:`HillCurveLL4`)
    ctrl_dose_fn: function
        Function to use to set an effective "dose" (non-zero) for controls.
        Takes the list of experiment doses as an argument.

    Returns
    -------
    pd.DataFrame
        DataFrame containing DIP rate curve fits and parameters
    """
    expt_data_orig = expt_data

    if 'dataset' in expt_data.index.names:
        datasets = expt_data.index.get_level_values('dataset').unique()
    else:
        datasets = None
    cell_lines = expt_data.index.get_level_values('cell_line').unique()
    drugs = expt_data.index.get_level_values('drug').unique()

    has_drug_combos = drugs.map(len).max() > 1
    if has_drug_combos:
        raise DrugCombosNotImplementedError()
    else:
        # TODO: Support drug combos
        expt_data = expt_data.reset_index(['drug', 'dose'])
        expt_data['drug'] = expt_data['drug'].apply(lambda x: x[0])
        expt_data['dose'] = expt_data['dose'].apply(lambda x: x[0])
        expt_data.set_index(['drug', 'dose'], append=True,
                            inplace=True)
        drugs = expt_data.index.get_level_values('drug').unique()

    if len(drugs) > 1 and len(cell_lines) == 1:
        group_by = ['drug']
    elif len(cell_lines) > 1 and len(drugs) == 1:
        group_by = ['cell_line']
    else:
        group_by = ['cell_line', 'drug']

    if datasets is not None and len(datasets) > 1:
        if len(cell_lines) == 1 and len(drugs) == 1:
            group_by = ['dataset']
        else:
            group_by = ['dataset'] + group_by

    fit_params = []

    is_viability = 'viability' in expt_data.columns

    for group_name, dip_grp in expt_data.groupby(level=group_by):
        if 'dataset' in group_by:
            if len(group_by) > 1:
                dataset = group_name[group_by.index('dataset')]
            else:
                dataset = group_name
        elif datasets is not None:
            dataset = datasets[0]
        else:
            dataset = None

        if 'cell_line' in group_by:
            if len(group_by) > 1:
                cl_name = group_name[group_by.index('cell_line')]
            else:
                cl_name = group_name
        else:
            cl_name = cell_lines[0]

        if 'drug' in group_by:
            if len(group_by) > 1:
                dr_name = group_name[group_by.index('drug')]
            else:
                dr_name = group_name
        else:
            dr_name = drugs[0]

        doses_expt = dip_grp.index.get_level_values('dose').values

        if is_viability:
            resp_expt = dip_grp['viability']
            doses = doses_expt
            fit_obj = fit_drc(
                doses_expt, resp_expt, response_std_errs=None,
                fit_cls=fit_cls
            )
        else:
            if dataset is None and ctrl_data is not None and \
                    'dataset' in ctrl_data.index.names:
                raise ValueError('Experimental data does not have "dataset" '
                                 'in index, but control data does. Please '
                                 'make sure "dataset" is in both dataframes, '
                                 'or neither.')

            ctrl_dip_data_cl = \
                _get_control_responses(ctrl_data, dataset, cl_name,
                                       dip_grp)
            dip_ctrl = []
            dip_ctrl_std_err = []
            if ctrl_dip_data_cl is not None:
                if is_viability:
                    dip_ctrl = ctrl_dip_data_cl.values
                else:
                    dip_ctrl = ctrl_dip_data_cl['dip_rate'].values
                    dip_ctrl_std_err = ctrl_dip_data_cl[
                        'dip_fit_std_err'].values

            n_controls = len(dip_ctrl)
            ctrl_dose_val = ctrl_dose_fn(doses_expt)
            doses_ctrl = np.repeat(ctrl_dose_val, n_controls)
            doses = np.concatenate((doses_ctrl, doses_expt))
            resp_expt = dip_grp['dip_rate'].values
            dip_all = np.concatenate((dip_ctrl, resp_expt))
            dip_std_errs = np.concatenate((
                dip_ctrl_std_err,
                dip_grp['dip_fit_std_err'].values))

            fit_obj = fit_drc(
                doses, dip_all, dip_std_errs,
                fit_cls=fit_cls,
                # ctrl_dose=ctrl_dose_val
            )

        max_dose_measured = np.max(doses)
        min_dose_measured = np.min(doses)

        fit_data = dict(
            dataset_id=dataset if dataset is not None else '',
            cell_line=cl_name,
            drug=dr_name,
            fit_obj=fit_obj,
            min_dose_measured=min_dose_measured,
            max_dose_measured=max_dose_measured,
            emax_obs=np.min(resp_expt)
        )

        fit_params.append(fit_data)

    df_params = pd.DataFrame(fit_params)
    df_params.set_index(['dataset_id', 'cell_line', 'drug'], inplace=True)

    df_params._drmetric = 'viability' if is_viability else 'dip'
    if is_viability:
        df_params._viability_time = expt_data_orig._viability_time
        df_params._viability_assay = expt_data_orig._viability_assay

    return df_params


def _calc_ic(row, ic_num):
    if row.fit_obj is None:
        return None

    ic_n = row.fit_obj.ic(ic_num=ic_num)
    if ic_n is None:
        return None

    ic_n = np.min((ic_n, row.max_dose_measured))
    ic_n = np.max((ic_n, row.min_dose_measured))
    return ic_n


def _calc_ec(row, ec_num):
    if row.fit_obj is None:
        return None

    ec_n = row.fit_obj.ec(ec_num=ec_num)
    if ec_n is None:
        return None

    ec_n = np.min((ec_n, row.max_dose_measured))
    ec_n = np.max((ec_n, row.min_dose_measured))
    return ec_n


def _calc_e(row, ec_lbl, relative=False):
    if row.fit_obj is None:
        return None

    ec_val = row[ec_lbl]
    if ec_val is None:
        return None

    return row.fit_obj.fit_rel(ec_val) if relative else row.fit_obj.fit(ec_val)


def _calc_aa(row):
    if not row.fit_obj or isinstance(row.fit_obj, HillCurveNull):
        return None

    return row.fit_obj.aa(max_conc=row.max_dose_measured,
                          emax_obs=row.emax)


def _calc_auc(row):
    if not row.fit_obj or isinstance(row.fit_obj, HillCurveNull):
        return None

    return row.fit_obj.auc(min_conc=row.min_dose_measured)


def _calc_ec50(row):
    if not row.fit_obj or isinstance(row.fit_obj, HillCurveNull):
        return None

    ec50 = np.min((row.fit_obj.ec50, row.max_dose_measured))
    ec50 = np.max((ec50, row.min_dose_measured))
    return ec50


def _attach_extra_params(base_params,
                         custom_ic_concentrations=frozenset(),
                         custom_ec_concentrations=frozenset(),
                         custom_e_values=frozenset(),
                         custom_e_rel_values=frozenset(),
                         include_aa=False,
                         include_auc=False,
                         include_hill=False,
                         include_emax=False
                         ):
    datasets = base_params.index.get_level_values('dataset_id').unique()
    if len(datasets) == 1 and datasets[0] == '':
        datasets = None

    cell_lines = base_params.index.get_level_values('cell_line').unique()
    drugs = base_params.index.get_level_values('drug').unique()

    if len(drugs) > 1 and len(cell_lines) == 1:
        group_by = ['drug']
    elif len(cell_lines) > 1 and len(drugs) == 1:
        group_by = ['cell_line']
    else:
        group_by = ['cell_line', 'drug']

    if datasets is not None and len(datasets) > 1:
        if len(cell_lines) == 1 and len(drugs) == 1:
            group_by = ['dataset_id']
        else:
            group_by = ['dataset_id'] + group_by

    def _generate_label(index):
        group_name_components = []

        if 'dataset_id' in group_by:
            dataset = index[group_by.index('dataset_id')]
            group_name_components.append(str(dataset))

        if 'cell_line' in group_by:
            cl_name = index[group_by.index('cell_line')]
            group_name_components.append(str(cl_name))

        if 'drug' in group_by:
            dr_name = index[group_by.index('drug')]
            group_name_components.append(str(dr_name))

        return "\n".join(group_name_components)

    base_params['label'] = base_params.index.map(_generate_label)

    for ic_num in custom_ic_concentrations:
        base_params['ic{:d}'.format(ic_num)] = base_params.apply(
            _calc_ic, args=(ic_num,), axis=1)

    if 50 in custom_ec_concentrations:
        base_params['ec50'] = base_params.apply(_calc_ec50, axis=1)

    if include_emax:
        base_params['emax'] = base_params.apply(
            lambda row: None if not row.fit_obj or isinstance(
                row.fit_obj, HillCurveNull) else row.fit_obj.fit(
                row.max_dose_measured),
            axis=1)

    is_viability = base_params._drmetric == 'viability'

    if not is_viability and include_emax:
        divisor = base_params['fit_obj'].apply(lambda fo: fo.divisor if fo
            else None)
        base_params['emax_rel'] = base_params['emax'] / divisor
        base_params['emax_obs_rel'] = base_params['emax_obs'] / divisor

    if include_aa:
        base_params['aa'] = base_params.apply(_calc_aa, axis=1)

    if include_auc:
        base_params['auc'] = base_params.apply(_calc_auc, axis=1)

    if include_hill:
        base_params['hill'] = base_params['fit_obj'].apply(
            lambda fo: fo.hill_slope if fo and not isinstance(
                fo, HillCurveNull) else None)

    custom_ec_concentrations = set(custom_ec_concentrations)
    custom_ec_concentrations.discard(50)
    custom_ec_concentrations = custom_ec_concentrations.union(
        custom_e_values)
    custom_ec_concentrations = custom_ec_concentrations.union(
        custom_e_rel_values)

    for ec_num in custom_ec_concentrations:
        base_params['ec{:d}'.format(ec_num)] = base_params.apply(
            _calc_ec, args=(ec_num,), axis=1)

    for e_num in custom_e_values:
        base_params['e{:d}'.format(e_num)] = base_params.apply(
            _calc_e, args=('ec{:d}'.format(e_num), False), axis=1
        )

    for e_num in custom_e_rel_values:
        base_params['e{:d}_rel'.format(e_num)] = base_params.apply(
            _calc_e, args=('ec{:d}'.format(e_num), True), axis=1
        )

    return base_params


def _attach_response_values(df_params, ctrl_dip_data, expt_dip_data,
                            ctrl_dose_fn):
    is_viability = df_params._drmetric == 'viability'
    data_list = []
    for grp, dip_grp in expt_dip_data.groupby(
            ['dataset', 'cell_line', 'drug'], sort=False):
        # Assumes drug combinations have been ruled out by fit_params_minimal
        doses_expt = [d[0] for d in dip_grp.index.get_level_values(
            'dose').values]
        fit_data = {}
        ctrl_dip_data_cl = \
            _get_control_responses(ctrl_dip_data, grp[0], grp[1],
                                   dip_grp)
        if ctrl_dip_data_cl is not None:
            if is_viability:
                ctrl_dip_data_cl = ctrl_dip_data_cl.to_frame()
            n_controls = len(ctrl_dip_data_cl.index)
            ctrl_dose_val = ctrl_dose_fn(doses_expt)
            doses_ctrl = np.repeat(ctrl_dose_val, n_controls)
            ctrl_dip_data_cl['dose'] = doses_ctrl
            ctrl_dip_data_cl.reset_index('well_id', inplace=True)
            ctrl_dip_data_cl.set_index(['dose', 'well_id'], inplace=True)
            if is_viability:
                fit_data['viability_ctrl'] = ctrl_dip_data_cl['value']
            else:
                fit_data['dip_ctrl'] = ctrl_dip_data_cl['dip_rate']

        if is_viability:
            fit_data['viability_time'] = dip_grp['timepoint'].values
            fit_data['viability'] = pd.Series(
                data=dip_grp['viability'].values,
                index=[doses_expt, dip_grp.index.get_level_values(
                    'well_id')]
            )
            fit_data['viability'].index.rename(['dose', 'well_id'],
                                               inplace=True)
        else:
            fit_data['dip_expt'] = pd.Series(
                data=dip_grp['dip_rate'].values,
                index=[doses_expt,
                       dip_grp.index.get_level_values('well_id')]
            )
            fit_data['dip_expt'].index.rename(['dose', 'well_id'],
                                              inplace=True)

        data_list.append(fit_data)

    df = pd.DataFrame(data_list)
    df.index = df_params.index
    df_params_old = df_params
    df_params = pd.concat([df, df_params], axis=1)

    df_params._drmetric = df_params_old._drmetric
    if is_viability:
        df_params._viability_time = df_params_old._viability_time
        df_params._viability_assay = df_params_old._viability_assay

    return df_params


def fit_params(ctrl_data, expt_data,
               fit_cls=HillCurveLL4,
               ctrl_dose_fn=lambda doses: np.min(doses) / 10.0):
    """
    Fit dose response curves to DIP rates or viability data

    This method computes parameters including IC50, EC50, AUC, AA,
    Hill coefficient, and Emax. For a faster version,
    see :func:`fit_params_minimal`.

    Parameters
    ----------
    ctrl_data: pd.DataFrame or None
        Control DIP rates from :func:`dip_rates` or :func:`ctrl_dip_rates`.
        Set to None to not use control data.
    expt_data: pd.DataFrame
        Experiment (non-control) DIP rates from :func:`dip_rates` or
        :func:`expt_dip_rates`, or viability data from :func:`viability`
    fit_cls: Class
        Class to use for curve fitting (default: :func:`HillCurveLL4`)
    ctrl_dose_fn: function
        Function to use to set an effective "dose" (non-zero) for controls.
        Takes the list of experiment doses as an argument.

    Returns
    -------
    pd.DataFrame
        DataFrame containing DIP rate curve fits and parameters
    """
    base_params = fit_params_minimal(ctrl_data, expt_data, fit_cls,
                                     ctrl_dose_fn)

    return fit_params_from_base(
        base_params, ctrl_data, expt_data,
        ctrl_dose_fn=ctrl_dose_fn,
        custom_ic_concentrations={50},
        custom_ec_concentrations={50},
        include_auc=True,
        include_aa=True,
        include_hill=True,
        include_emax=True,
        include_response_values=True
    )


def fit_params_from_base(
        base_params,
        ctrl_resp_data=None, expt_resp_data=None,
        ctrl_dose_fn=lambda doses: np.min(doses) / 10.0,
        custom_ic_concentrations=frozenset(),
        custom_ec_concentrations=frozenset(),
        custom_e_values=frozenset(),
        custom_e_rel_values=frozenset(),
        include_aa=False,
        include_auc=False,
        include_hill=False,
        include_emax=False,
        include_response_values=True):
    """
    Attach additional parameters to basic set of fit parameters
    """
    df_params = _attach_extra_params(base_params, custom_ic_concentrations,
                                     custom_ec_concentrations,
                                     custom_e_values, custom_e_rel_values,
                                     include_aa, include_auc, include_hill,
                                     include_emax)

    if include_response_values:
        df_params = _attach_response_values(df_params, ctrl_resp_data,
                                            expt_resp_data, ctrl_dose_fn)

    return df_params


def is_param_truncated(df_params, param_name):
    """
    Checks if parameter values are truncated at boundaries of measured range

    Parameters
    ----------
    df_params: pd.DataFrame
        DataFrame of DIP curve fits with parameters from :func:`fit_params`
    param_name: str
        Name of a parameter, e.g. 'ic50'

    Returns
    -------
    np.ndarray
        Array of booleans showing whether each entry in the DataFrame is
        truncated
    """
    values = df_params[param_name].fillna(value=np.nan)
    return np.isclose(
        values, df_params['max_dose_measured'],
        atol=PARAM_EQUAL_ATOL, rtol=PARAM_EQUAL_RTOL) | np.isclose(
        values, df_params['min_dose_measured'],
        atol=PARAM_EQUAL_ATOL, rtol=PARAM_EQUAL_RTOL
    )
