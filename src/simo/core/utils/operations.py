import operator

OPERATIONS = {
    '==': operator.eq,
    '>': operator.gt,
    '>=': operator.ge,
    '<': operator.lt,
    '<=': operator.le,
    'in': lambda a, b: a in b
}