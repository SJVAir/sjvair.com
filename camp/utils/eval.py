from decimal import Decimal

from simpleeval import SimpleEval


class DecimalSimpleEval(SimpleEval):
    def _eval_number(self, node):
        return Decimal(str(node.n))  # coerce any parsed number to Decimal

    def _eval_binop(self, node):
        op = self.operators[type(node.op)]
        left = self._eval(node.left)
        right = self._eval(node.right)

        # Force both sides to Decimal
        if isinstance(left, float):
            left = Decimal(str(left))
        if isinstance(right, float):
            right = Decimal(str(right))

        return op(left, right)


def evaluate_formula(formula: str, context: dict):
    evaluator = DecimalSimpleEval()
    evaluator.names = context
    return evaluator.eval(formula)
