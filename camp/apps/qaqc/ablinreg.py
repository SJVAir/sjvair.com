from dataclasses import dataclass
from datetime import datetime

from django.conf import settings

from sklearn.linear_model import LinearRegression
from sklearn.metrics import explained_variance_score

from .models import SensorAnalysis
from .sensorqueryset import  SensorAnalysisQueryset

@dataclass
class ABLinearRegressionResult:
    r2: float
    intercept: float
    coef: float


class ABLinearRegression(SensorAnalysisQueryset):
    r2_weight = 1
    variance_weight = 1

    def __init__(self, monitor, end_date=None):
        super().__init__(
            monitor,
            end_date=end_date,
            days=7
        )

    def analyze(self):
        linreg = self.generate_regression()
        variance = self.generate_variance()

        grade = ((linreg.r2 * self.r2_weight) + (variance * self.variance_weight)) / (self.r2_weight + self.variance_weight)

        if settings.DEBUG:
            self.__log(linreg.r2, variance, grade)

        return SensorAnalysis(
            monitor=self.monitor,
            r2=linreg.r2,
            grade=grade,
            variance=variance,
            intercept=linreg.intercept,
            coef=linreg.coef,
            start_date=self.start_date,
            end_date=self.end_date,
        )

    def generate_regression(self):
        if self.endog is None or self.exog is None:
            return None

        try:
            linreg = LinearRegression()
            linreg.fit(self.exog, self.endog)
            r2=linreg.score(self.exog, self.endog)

        except ValueError as err:
            print('QAQC Linear Regression Error:', err)
            return None


        return ABLinearRegressionResult(
            r2=r2,
            intercept=linreg.intercept_,
            coef=linreg.coef_[0][0],
        )

    def generate_variance(self):
        return explained_variance_score(
            self.exog['pm25_reported'].values,
            self.endog['pm25_reported'].values
        )


    def __log(self, r2, variance, grade):
        badr2 = r2 < 0.9
        badV = variance < 0.9
        badG = grade < 0.9

        print(f'\nResults for {self.monitor.name}')
        if badr2 or badV or badG:
            issues = list()

            if badr2:
                issues.append("Bad R2")

            if badV:
              issues.append("Bad Variance")

            if badG:
                issues.append("Bad Grade")

            print('Possible issues detected:')
            print(", ".join(issues))

        print(f'R2: {r2}')
        print(f'Variance: {variance}')
        print(f'Grade: {grade}\n')
