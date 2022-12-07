from dataclasses import dataclass

import pandas as pd

from django.db.models import F
from sklearn.linear_model import LinearRegression


@dataclass
class RegressionResults:
    reg: LinearRegression
    endog: pd.DataFrame
    exog: pd.DataFrame
    df: pd.DataFrame
    r2: float
    intercept: int
    coefs: dict


def linear_regression(endog_qs, exog_qs, exog_coefs):
    # endog is generally the reference data that we want to fit to
    endog_qs = (endog_qs
        .annotate(endog_pm25=F('pm25'))
        .values('timestamp', 'endog_pm25')
    )

    if not endog_qs.exists():
        return

    endog_df = pd.DataFrame(endog_qs).set_index('timestamp')
    endog_df = pd.to_numeric(endog_df.endog_pm25)
    endog_df = endog_df.resample('H').mean()

    # exog is the data we want to try to calibrate to the endog
    exog_qs = exog_qs.values('timestamp', *exog_coefs)

    if not exog_qs.exists():
        return

    exog_df = pd.DataFrame(exog_qs).set_index('timestamp')
    exog_df[exog_df.columns] = exog_df[exog_df.columns].apply(pd.to_numeric, errors='coerce')

    exog_df = exog_df.resample('H').mean()

    # Merge the dataframes
    merged = pd.concat([endog_df, exog_df], axis=1, join="inner")
    merged = merged.dropna()

    if not len(merged):
        return

    endog = merged['endog_pm25']
    exog = merged[exog_coefs]

    try:
        reg = LinearRegression()
        reg.fit(exog, endog)
    except ValueError as err:
        # import code
        # code.interact(local=locals())
        print('Linear Regression Error:', err)
        return

    return RegressionResults(
        reg=reg,
        endog=endog_df,
        exog=exog_df,
        df=merged,
        r2=reg.score(exog, endog),
        intercept=reg.intercept_,
        coefs=dict(zip(exog_coefs, reg.coef_)),
    )
